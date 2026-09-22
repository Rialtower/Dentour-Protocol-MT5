"""Características causales y dinámicas por sesión para Research.

Flujo:
1. Calcula características históricas sobre M15 completo.
2. Convierte timestamps de apertura en tiempos de disponibilidad.
3. Une únicamente el último H1 completamente cerrado.
4. Filtra la sesión solicitada sin perder el calentamiento previo.
5. Calcula VWAP acumulativo de la sesión.
6. Devuelve observaciones listas para construir targets.

No consulta archivos, no mira al futuro y no entrena modelos.

GUÍA DIDÁCTICA AMPLIADA
========================

PROPÓSITO
---------
Este módulo transforma barras M15 y contexto H1 en variables disponibles al
momento real de decisión. No consulta archivos y no utiliza trayectorias futuras.

CAUSALIDAD TEMPORAL
-------------------
- timestamp_* representa la apertura original de la M15.
- observation_time_* representa el cierre confirmado, apertura + 15 minutos.
- H1 solo se expone 60 minutos después de su apertura.
- Las referencias de volumen se desplazan una barra antes de calcular medias.
- Los extremos previos usan shift(1), excluyendo la barra actual.

ORDEN CRÍTICO
-------------
Las ventanas históricas se calculan sobre M15 completo antes de filtrar una
sesión. Así ATR, retornos y volumen relativo aprovechan el historial anterior y
no se reinician artificialmente en cada apertura de sesión. El VWAP de sesión,
en cambio, sí se calcula después del filtro y se reinicia por session_date.

FAMILIAS DE FEATURES
--------------------
1. Geometría de vela.
2. Retornos y volatilidad realizada.
3. True Range y ATR.
4. Volumen relativo y Z-score.
5. VWAP diario.
6. Extremos y sweeps previos.
7. Variables temporales cíclicas.
8. Último H1 totalmente cerrado.
9. VWAP acumulativo de sesión.

PERTENENCIA Y DISPONIBILIDAD
----------------------------
La apertura M15 determina si una barra pertenece a una sesión. El cierre
confirmado determina minute_of_session. Por eso la M15 abierta en 07:00 pertenece
a Nueva York y se convierte en una observación disponible a las 07:15.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

import polars as pl

from research.contracts import DEFAULT_EXPERIMENT, ExperimentConfig
from sessions import (
    SessionWindow,
    add_session_columns,
)


EPSILON: Final[float] = 1e-12
M15_DURATION_MINUTES: Final[int] = 15
H1_DURATION_MINUTES: Final[int] = 60

BASE_BAR_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp_utc",
    "timestamp_cot",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "spread",
    "real_volume",
)


@dataclass(frozen=True, slots=True)
# -----------------------------------------------------------------------------
# Contabilidad auditable de entrada, warmup, salida y columnas creadas.
# -----------------------------------------------------------------------------
class FeatureBuildReport:
    """Resumen de construcción de características de una sesión."""

    session_code: str
    session_label: str
    input_rows_m15: int
    session_rows_before_cleanup: int
    output_rows: int
    dropped_warmup_rows: int
    first_timestamp: object | None
    last_timestamp: object | None
    feature_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
# -----------------------------------------------------------------------------
# Devuelve conjuntamente datos y reporte para targets.py.
# -----------------------------------------------------------------------------
class FeatureBuildResult:
    data: pl.DataFrame
    report: FeatureBuildReport


# -----------------------------------------------------------------------------
# Defensa de esquema, orden y unicidad antes de rolling windows.
# -----------------------------------------------------------------------------
def validate_bar_frame(dataframe: pl.DataFrame, *, frame_name: str) -> None:
    """Valida esquema, orden y unicidad de un DataFrame OHLCV."""

    missing = set(BASE_BAR_COLUMNS) - set(dataframe.columns)
    if missing:
        raise ValueError(
            f"{frame_name} no contiene columnas requeridas: {sorted(missing)}"
        )
    if dataframe.is_empty():
        raise ValueError(f"{frame_name} está vacío.")
    if not dataframe["timestamp_utc"].is_sorted():
        raise ValueError(f"{frame_name} debe estar ordenado por timestamp_utc.")

    duplicates = dataframe.select(
        pl.col("timestamp_utc").is_duplicated().sum()
    ).item()
    if duplicates:
        raise ValueError(
            f"{frame_name} contiene {duplicates} timestamps duplicados."
        )


# -----------------------------------------------------------------------------
# Separa apertura M15 de su instante real de disponibilidad.
# -----------------------------------------------------------------------------
def add_availability_columns(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Conserva apertura M15 y agrega el instante real de disponibilidad."""

    return dataframe.with_columns(
        (
            pl.col("timestamp_utc")
            + pl.duration(minutes=M15_DURATION_MINUTES)
        ).alias("observation_time_utc"),
        (
            pl.col("timestamp_cot")
            + pl.duration(minutes=M15_DURATION_MINUTES)
        ).alias("observation_time_cot"),
    )


# -----------------------------------------------------------------------------
# Describe cuerpo, rango, mechas, ubicación del cierre y dirección.
# -----------------------------------------------------------------------------
def add_candle_geometry(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Añade geometría conocida al cierre de cada M15."""

    bar_range = pl.col("high") - pl.col("low")
    body = pl.col("close") - pl.col("open")

    return dataframe.with_columns(
        body.alias("body"),
        body.abs().alias("body_abs"),
        bar_range.alias("bar_range"),
        (pl.col("high") - pl.max_horizontal("open", "close")).alias(
            "upper_wick"
        ),
        (pl.min_horizontal("open", "close") - pl.col("low")).alias(
            "lower_wick"
        ),
        pl.when(bar_range.abs() > EPSILON)
        .then(body / bar_range)
        .otherwise(0.0)
        .alias("body_to_range"),
        pl.when(bar_range.abs() > EPSILON)
        .then((pl.col("close") - pl.col("low")) / bar_range)
        .otherwise(0.5)
        .alias("close_location"),
        pl.when(pl.col("close") > pl.col("open"))
        .then(1)
        .when(pl.col("close") < pl.col("open"))
        .then(-1)
        .otherwise(0)
        .cast(pl.Int8)
        .alias("candle_direction"),
    )


# -----------------------------------------------------------------------------
# Crea retornos causales y volatilidad terminada en la barra actual.
# -----------------------------------------------------------------------------
def add_return_features(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Añade retornos y volatilidad histórica terminados en la barra actual."""

    one_bar_return = pl.col("close") / pl.col("close").shift(1) - 1.0

    return dataframe.with_columns(
        one_bar_return.alias("return_15m"),
        (pl.col("close") / pl.col("close").shift(2) - 1.0).alias(
            "return_30m"
        ),
        (pl.col("close") / pl.col("close").shift(4) - 1.0).alias(
            "return_60m"
        ),
        one_bar_return.rolling_std(
            window_size=4,
            min_samples=4,
        ).alias("realized_vol_60m"),
        one_bar_return.rolling_std(
            window_size=16,
            min_samples=16,
        ).alias("realized_vol_4h"),
        pl.col("close")
        .diff()
        .sign()
        .rolling_sum(window_size=4, min_samples=4)
        .cast(pl.Int8)
        .alias("direction_balance_60m"),
    )


# -----------------------------------------------------------------------------
# Calcula True Range y ATR sin mirar barras posteriores.
# -----------------------------------------------------------------------------
def add_atr_features(
    dataframe: pl.DataFrame,
    *,
    period: int,
) -> pl.DataFrame:
    """Calcula True Range y ATR simple, ambos causales."""

    if period < 2:
        raise ValueError("period debe ser al menos 2.")

    previous_close = pl.col("close").shift(1)
    true_range = pl.max_horizontal(
        pl.col("high") - pl.col("low"),
        (pl.col("high") - previous_close).abs(),
        (pl.col("low") - previous_close).abs(),
    )

    return (
        dataframe
        .with_columns(true_range.alias("true_range"))
        .with_columns(
            pl.col("true_range")
            .rolling_mean(window_size=period, min_samples=period)
            .alias("atr")
        )
        .with_columns(
            pl.when(pl.col("atr") > EPSILON)
            .then(pl.col("bar_range") / pl.col("atr"))
            .otherwise(None)
            .alias("range_atr"),
            pl.when(pl.col("atr") > EPSILON)
            .then(pl.col("body") / pl.col("atr"))
            .otherwise(None)
            .alias("body_atr"),
        )
    )


# -----------------------------------------------------------------------------
# Compara volumen actual contra una referencia exclusivamente anterior.
# -----------------------------------------------------------------------------
def add_volume_features(
    dataframe: pl.DataFrame,
    *,
    short_window: int = 4,
    reference_window: int = 32,
) -> pl.DataFrame:
    """Compara el volumen actual con una referencia exclusivamente anterior."""

    if short_window < 1:
        raise ValueError("short_window debe ser positivo.")
    if reference_window < 2:
        raise ValueError("reference_window debe ser al menos 2.")

    prior_mean = (
        pl.col("volume")
        .shift(1)
        .rolling_mean(
            window_size=reference_window,
            min_samples=reference_window,
        )
    )
    prior_std = (
        pl.col("volume")
        .shift(1)
        .rolling_std(
            window_size=reference_window,
            min_samples=reference_window,
        )
    )

    return dataframe.with_columns(
        pl.col("volume")
        .rolling_sum(window_size=short_window, min_samples=short_window)
        .alias("volume_sum_short"),
        prior_mean.alias("volume_mean_prior"),
        prior_std.alias("volume_std_prior"),
        pl.when(prior_mean > 0)
        .then(pl.col("volume") / prior_mean)
        .otherwise(None)
        .alias("volume_ratio"),
        pl.when(prior_std > EPSILON)
        .then((pl.col("volume") - prior_mean) / prior_std)
        .otherwise(None)
        .alias("volume_zscore"),
        pl.when(pl.col("volume") > 0)
        .then(pl.col("real_volume") / pl.col("volume"))
        .otherwise(0.0)
        .alias("real_to_tick_volume"),
    )


# -----------------------------------------------------------------------------
# Reinicia VWAP a medianoche del calendario COT.
# -----------------------------------------------------------------------------
def add_daily_vwap_features(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Calcula VWAP causal desde las 00:00 COT de cada fecha."""

    typical_price = (
        pl.col("high") + pl.col("low") + pl.col("close")
    ) / 3.0

    return (
        dataframe
        .with_columns(
            pl.col("timestamp_cot").dt.date().alias("calendar_date"),
            typical_price.alias("typical_price"),
            (typical_price * pl.col("volume")).alias("price_volume"),
        )
        .with_columns(
            pl.col("price_volume")
            .cum_sum()
            .over("calendar_date")
            .alias("daily_cum_price_volume"),
            pl.col("volume")
            .cum_sum()
            .over("calendar_date")
            .alias("daily_cum_volume"),
        )
        .with_columns(
            pl.when(pl.col("daily_cum_volume") > 0)
            .then(
                pl.col("daily_cum_price_volume")
                / pl.col("daily_cum_volume")
            )
            .otherwise(None)
            .alias("daily_vwap")
        )
        .with_columns(
            (pl.col("close") - pl.col("daily_vwap")).alias(
                "distance_daily_vwap"
            ),
            pl.when(pl.col("atr") > EPSILON)
            .then(
                (pl.col("close") - pl.col("daily_vwap"))
                / pl.col("atr")
            )
            .otherwise(None)
            .alias("distance_daily_vwap_atr"),
            pl.col("daily_vwap")
            .diff()
            .over("calendar_date")
            .alias("daily_vwap_slope"),
        )
    )


# -----------------------------------------------------------------------------
# Usa shift(1) para excluir la barra actual de extremos previos.
# -----------------------------------------------------------------------------
def add_prior_extreme_features(
    dataframe: pl.DataFrame,
    *,
    lookback_bars: int = 16,
) -> pl.DataFrame:
    """Calcula extremos anteriores excluyendo la barra actual."""

    if lookback_bars < 2:
        raise ValueError("lookback_bars debe ser al menos 2.")

    prior_high = (
        pl.col("high")
        .shift(1)
        .rolling_max(
            window_size=lookback_bars,
            min_samples=lookback_bars,
        )
    )
    prior_low = (
        pl.col("low")
        .shift(1)
        .rolling_min(
            window_size=lookback_bars,
            min_samples=lookback_bars,
        )
    )

    return (
        dataframe
        .with_columns(
            prior_high.alias("prior_high"),
            prior_low.alias("prior_low"),
        )
        .with_columns(
            pl.when(pl.col("atr") > EPSILON)
            .then(
                (pl.col("prior_high") - pl.col("close"))
                / pl.col("atr")
            )
            .otherwise(None)
            .alias("distance_prior_high_atr"),
            pl.when(pl.col("atr") > EPSILON)
            .then(
                (pl.col("close") - pl.col("prior_low"))
                / pl.col("atr")
            )
            .otherwise(None)
            .alias("distance_prior_low_atr"),
            (
                (pl.col("high") > pl.col("prior_high"))
                & (pl.col("close") < pl.col("prior_high"))
            )
            .cast(pl.Int8)
            .alias("sweep_prior_high"),
            (
                (pl.col("low") < pl.col("prior_low"))
                & (pl.col("close") > pl.col("prior_low"))
            )
            .cast(pl.Int8)
            .alias("sweep_prior_low"),
        )
    )


# -----------------------------------------------------------------------------
# Codifica hora cíclica y calendario sin imponer discontinuidad 23:59/00:00.
# -----------------------------------------------------------------------------
def add_time_features(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Añade variables cíclicas del calendario COT."""

    minute_of_day = (
        pl.col("timestamp_cot")
        .dt.hour()
        .cast(pl.Int32)
        * 60
        + pl.col("timestamp_cot")
        .dt.minute()
        .cast(pl.Int32)
    )
    angle = minute_of_day.cast(pl.Float64) * (
        2.0 * math.pi / 1440.0
    )

    return dataframe.with_columns(
        minute_of_day.cast(pl.Int16).alias("minute_of_day"),
        pl.col("timestamp_cot")
        .dt.weekday()
        .cast(pl.Int8)
        .alias("iso_weekday"),
        angle.sin().alias("time_sin"),
        angle.cos().alias("time_cos"),
        pl.col("timestamp_cot")
        .dt.ordinal_day()
        .cast(pl.Int16)
        .alias("day_of_year"),
        pl.col("timestamp_cot")
        .dt.month()
        .cast(pl.Int8)
        .alias("month"),
    )


# -----------------------------------------------------------------------------
# Hace disponible una H1 solamente cuando la hora completa ya cerró.
# -----------------------------------------------------------------------------
def prepare_h1_context(h1: pl.DataFrame) -> pl.DataFrame:
    """Expone cada H1 únicamente 60 minutos después de su apertura."""

    validate_bar_frame(h1, frame_name="h1")

    return (
        h1
        .select(
            "timestamp_utc",
            "open",
            "high",
            "low",
            "close",
        )
        .with_columns(
            (
                pl.col("timestamp_utc")
                + pl.duration(minutes=H1_DURATION_MINUTES)
            ).alias("h1_available_at_utc"),
            (pl.col("close") - pl.col("open")).alias("h1_body"),
            pl.when(pl.col("close") > pl.col("open"))
            .then(1)
            .when(pl.col("close") < pl.col("open"))
            .then(-1)
            .otherwise(0)
            .cast(pl.Int8)
            .alias("h1_direction"),
            (
                pl.col("close") / pl.col("close").shift(1) - 1.0
            ).alias("h1_return_1"),
        )
        .select(
            "h1_available_at_utc",
            "h1_body",
            "h1_direction",
            "h1_return_1",
        )
        .sort("h1_available_at_utc")
    )


# -----------------------------------------------------------------------------
# join_asof backward: asigna el último H1 disponible, nunca uno futuro.
# -----------------------------------------------------------------------------
def join_h1_context(
    m15_features: pl.DataFrame,
    h1_context: pl.DataFrame,
) -> pl.DataFrame:
    """Une el último H1 cerrado disponible al cierre de cada M15."""

    return (
        m15_features
        .sort("observation_time_utc")
        .join_asof(
            h1_context.sort("h1_available_at_utc"),
            left_on="observation_time_utc",
            right_on="h1_available_at_utc",
            strategy="backward",
            check_sortedness=True,
        )
    )


# -----------------------------------------------------------------------------
# Reinicia acumulados por session_code y session_date.
# -----------------------------------------------------------------------------
def add_session_vwap_features(
    session_frame: pl.DataFrame,
) -> pl.DataFrame:
    """Calcula VWAP causal reiniciado en cada session_date."""

    return (
        session_frame
        .sort(
            [
                "session_code",
                "session_date",
                "observation_time_utc",
            ]
        )
        .with_columns(
            (
                pl.col("typical_price") * pl.col("volume")
            ).alias("session_price_volume")
        )
        .with_columns(
            pl.col("session_price_volume")
            .cum_sum()
            .over(["session_code", "session_date"])
            .alias("session_cum_price_volume"),
            pl.col("volume")
            .cum_sum()
            .over(["session_code", "session_date"])
            .alias("session_cum_volume"),
        )
        .with_columns(
            pl.when(pl.col("session_cum_volume") > 0)
            .then(
                pl.col("session_cum_price_volume")
                / pl.col("session_cum_volume")
            )
            .otherwise(None)
            .alias("session_vwap")
        )
        .with_columns(
            (pl.col("close") - pl.col("session_vwap")).alias(
                "distance_session_vwap"
            ),
            pl.when(pl.col("atr") > EPSILON)
            .then(
                (pl.col("close") - pl.col("session_vwap"))
                / pl.col("atr")
            )
            .otherwise(None)
            .alias("distance_session_vwap_atr"),
            pl.col("session_vwap")
            .diff()
            .over(
                [
                    "session_code",
                    "session_date",
                ]
            )
            .fill_null(0.0)
            .alias(
                "session_vwap_slope"
            )
        )
    )

# -----------------------------------------------------------------------------
# Filtra por apertura M15 y posiciona por cierre confirmado.
# -----------------------------------------------------------------------------
def filter_observations_for_session(
    dataframe: pl.DataFrame,
    session: SessionWindow,
) -> pl.DataFrame:
    """Selecciona barras M15 completas pertenecientes a la sesión.

    La apertura M15 determina la pertenencia.
    El cierre confirmado determina minute_of_session.
    Una barra abierta antes del final puede cerrar exactamente en el final.
    """

    required_columns = {
        "timestamp_cot",
        "observation_time_cot",
        "observation_time_utc",
    }

    missing_columns = (
        required_columns
        - set(dataframe.columns)
    )

    if missing_columns:
        raise ValueError(
            "No se puede filtrar la sesión. "
            f"Faltan columnas: {sorted(missing_columns)}"
        )

    if dataframe.is_empty():
        return dataframe

    opening_time = (
        pl.col("timestamp_cot")
        .dt.time()
    )

    if session.is_full_day:
        filtered = dataframe

    elif session.crosses_midnight:
        filtered = dataframe.filter(
            (opening_time >= session.start)
            | (opening_time < session.end)
        )

    else:
        filtered = dataframe.filter(
            (opening_time >= session.start)
            & (opening_time < session.end)
        )

    if filtered.is_empty():
        return filtered.with_columns(
            pl.lit(session.code).alias(
                "session_code"
            )
        )

    # Agrega la posición temporal usando el cierre confirmado,
    # pero no vuelve a filtrar por la hora de cierre.
    filtered = add_session_columns(
        filtered,
        session,
        timestamp_column="observation_time_cot",
    )

    # La fecha de sesión se deriva de la apertura M15.
    if session.is_full_day:
        session_date = (
            pl.col("timestamp_cot")
            .dt.date()
        )

    elif session.crosses_midnight:
        session_date = (
            pl.when(
                pl.col("timestamp_cot").dt.time()
                < session.end
            )
            .then(
                pl.col("timestamp_cot").dt.date()
                - pl.duration(days=1)
            )
            .otherwise(
                pl.col("timestamp_cot").dt.date()
            )
        )

    else:
        session_date = (
            pl.col("timestamp_cot")
            .dt.date()
        )

    return (
        filtered
        .with_columns(
            session_date.alias(
                "session_date"
            )
        )
        .sort("observation_time_utc")
    )

# -----------------------------------------------------------------------------
# Orquestador completo del pipeline causal de features.
# -----------------------------------------------------------------------------
def build_m15_feature_frame(
    m15: pl.DataFrame,
    h1: pl.DataFrame,
    *,
    session: SessionWindow | None = None,
    config: ExperimentConfig = DEFAULT_EXPERIMENT,
    drop_incomplete_rows: bool = True,
) -> FeatureBuildResult:
    """Construye features M15 para una sesión sin perder historia previa.

    Las ventanas históricas se calculan antes del filtro de sesión. El VWAP de
    sesión se calcula después del filtro y se reinicia por session_date.
    """

    validate_bar_frame(m15, frame_name="m15")
    validate_bar_frame(h1, frame_name="h1")

    selected_session = session or config.session
    input_rows = m15.height

    features = m15.sort("timestamp_utc")
    features = add_availability_columns(features)
    features = add_candle_geometry(features)
    features = add_return_features(features)
    features = add_atr_features(features, period=config.atr_period)
    features = add_volume_features(features)
    features = add_daily_vwap_features(features)
    features = add_prior_extreme_features(features)
    features = add_time_features(features)
    features = join_h1_context(features, prepare_h1_context(h1))

    # La pertenencia se define por la apertura de la M15. Por ejemplo, la M15
    # 07:00 pertenece a Nueva York y queda disponible como observación 07:15.
    features = filter_observations_for_session(
        features,
        selected_session,
    )

    session_rows_before_cleanup = features.height
    features = add_session_vwap_features(features)

    model_feature_columns = (
        "body_to_range",
        "close_location",
        "candle_direction",
        "return_15m",
        "return_30m",
        "return_60m",
        "realized_vol_60m",
        "realized_vol_4h",
        "direction_balance_60m",
        "atr",
        "range_atr",
        "body_atr",
        "volume_ratio",
        "volume_zscore",
        "real_to_tick_volume",
        "distance_daily_vwap_atr",
        "daily_vwap_slope",
        "distance_session_vwap_atr",
        "session_vwap_slope",
        "distance_prior_high_atr",
        "distance_prior_low_atr",
        "sweep_prior_high",
        "sweep_prior_low",
        "iso_weekday",
        "time_sin",
        "time_cos",
        "month",
        "minute_of_session",
        "session_progress",
        "h1_body",
        "h1_direction",
        "h1_return_1",
    )

    if drop_incomplete_rows:
        features = features.drop_nulls(list(model_feature_columns))

    first_timestamp = None
    last_timestamp = None
    if not features.is_empty():
        bounds = features.select(
            pl.col("observation_time_utc").min().alias("first"),
            pl.col("observation_time_utc").max().alias("last"),
        ).row(0, named=True)
        first_timestamp = bounds["first"]
        last_timestamp = bounds["last"]

    report = FeatureBuildReport(
        session_code=selected_session.code,
        session_label=selected_session.label,
        input_rows_m15=input_rows,
        session_rows_before_cleanup=session_rows_before_cleanup,
        output_rows=features.height,
        dropped_warmup_rows=(
            session_rows_before_cleanup - features.height
        ),
        first_timestamp=first_timestamp,
        last_timestamp=last_timestamp,
        feature_columns=model_feature_columns,
    )

    return FeatureBuildResult(data=features, report=report)
