"""Baselines estadisticos para Dentour Protocol MT5 Research.

Calcula referencias simples que cualquier modelo debe superar fuera de muestra.
No entrena modelos, no consulta archivos y no escribe resultados.

GUÍA DIDÁCTICA AMPLIADA
========================

PROPÓSITO
---------
Los baselines son referencias estadísticas simples. Un modelo experimental no
demuestra valor por producir probabilidades; debe compararse con una estrategia
mucho más sencilla calculada únicamente con datos anteriores.

REFERENCIAS DESCRIPTIVAS
------------------------
- Frecuencia global.
- Frecuencia por sesión.
- Frecuencia por minuto de sesión.
- Frecuencia por día de semana.
- Frecuencia por régimen ATR.

PREDICCIÓN CONSTANTE
--------------------
build_constant_predictions aprende la frecuencia del target en train y aplica
esa probabilidad a observaciones posteriores. Si se agrupa, calcula frecuencias
por grupo y puede usar la frecuencia global como fallback para grupos ausentes.
Nunca lee el target de inference_data para construir la probabilidad.

RÉGIMEN DE VOLATILIDAD
----------------------
Los cortes q33 y q67 deben ajustarse con train y aplicarse sin recalcular en
test. Cuando reference_data no se proporciona, el resultado es descriptivo y
no debe interpretarse como evaluación fuera de muestra.

LIMITACIÓN
----------
El reporte descriptivo construye constant_predictions usando el mismo dataset
como train e inference. Esa salida sirve para inspección, no para evaluación.
La evaluación real debe llamar build_constant_predictions con train y test
separados por validation.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

import polars as pl

from research.dataset import ResearchDataset


DEFAULT_BINARY_TARGETS: Final[tuple[str, ...]] = (
    "target_peak_050_atr",
    "target_peak_075_atr",
    "target_peak_100_atr",
)

WEEKDAY_LABELS: Final[dict[int, str]] = {
    1: "lunes",
    2: "martes",
    3: "miercoles",
    4: "jueves",
    5: "viernes",
    6: "sabado",
    7: "domingo",
}


@dataclass(frozen=True, slots=True)
# -----------------------------------------------------------------------------
# Agrupa todas las referencias descriptivas y predicciones constantes.
# -----------------------------------------------------------------------------
class BaselineReport:
    rows: int
    session_codes: tuple[str, ...]
    binary_targets: tuple[str, ...]
    global_rates: pl.DataFrame
    by_session: pl.DataFrame
    by_session_minute: pl.DataFrame
    by_weekday: pl.DataFrame
    by_volatility_regime: pl.DataFrame
    constant_predictions: pl.DataFrame


# -----------------------------------------------------------------------------
# Exige targets existentes y limitados a 0/1.
# -----------------------------------------------------------------------------
def _validate_binary_targets(
    dataframe: pl.DataFrame,
    targets: tuple[str, ...],
) -> None:
    missing = set(targets) - set(dataframe.columns)
    if missing:
        raise ValueError(f"Faltan targets binarios: {sorted(missing)}")

    for target in targets:
        values = set(dataframe[target].unique().to_list())
        if not values <= {0, 1}:
            raise ValueError(
                f"{target} contiene valores fuera de 0/1: {sorted(values)}"
            )


# -----------------------------------------------------------------------------
# Genera expresiones Polars reutilizables para frecuencias.
# -----------------------------------------------------------------------------
def _rate_expressions(
    targets: Iterable[str],
) -> list[pl.Expr]:
    return [
        pl.col(target).mean().alias(f"rate__{target}")
        for target in targets
    ]


# -----------------------------------------------------------------------------
# Genera conteos positivos para auditar las tasas.
# -----------------------------------------------------------------------------
def _count_positive_expressions(
    targets: Iterable[str],
) -> list[pl.Expr]:
    return [
        pl.col(target).sum().alias(f"positives__{target}")
        for target in targets
    ]


# -----------------------------------------------------------------------------
# Resume la frecuencia histórica total y medianas de excursión.
# -----------------------------------------------------------------------------
def calculate_global_rates(
    dataset: ResearchDataset,
    *,
    targets: tuple[str, ...] = DEFAULT_BINARY_TARGETS,
) -> pl.DataFrame:
    """Frecuencia histórica constante en todo el dataset."""

    _validate_binary_targets(dataset.data, targets)
    return dataset.data.select(
        pl.len().alias("observations"),
        *_count_positive_expressions(targets),
        *_rate_expressions(targets),
        pl.col("mfe_atr").median().alias("median_mfe_atr"),
        pl.col("mae_atr").median().alias("median_mae_atr"),
        pl.col("time_to_peak_minutes")
        .median()
        .alias("median_time_to_peak_minutes"),
    )


# -----------------------------------------------------------------------------
# Separa referencias para evitar que una sesión oculte a otra.
# -----------------------------------------------------------------------------
def calculate_by_session(
    dataset: ResearchDataset,
    *,
    targets: tuple[str, ...] = DEFAULT_BINARY_TARGETS,
) -> pl.DataFrame:
    """Baseline separado por identidad de sesión."""

    _validate_binary_targets(dataset.data, targets)
    return (
        dataset.data
        .group_by("session_code")
        .agg(
            pl.len().alias("observations"),
            *_count_positive_expressions(targets),
            *_rate_expressions(targets),
            pl.col("mfe_atr").median().alias("median_mfe_atr"),
            pl.col("mae_atr").median().alias("median_mae_atr"),
            pl.col("time_to_peak_minutes")
            .median()
            .alias("median_time_to_peak_minutes"),
        )
        .sort("session_code")
    )


# -----------------------------------------------------------------------------
# Estudia cómo cambia la frecuencia dentro de la sesión.
# -----------------------------------------------------------------------------
def calculate_by_session_minute(
    dataset: ResearchDataset,
    *,
    targets: tuple[str, ...] = DEFAULT_BINARY_TARGETS,
    minimum_observations: int = 1,
) -> pl.DataFrame:
    """Frecuencias por sesión y momento M15 dentro de la sesión."""

    if minimum_observations < 1:
        raise ValueError("minimum_observations debe ser al menos 1.")

    _validate_binary_targets(dataset.data, targets)
    return (
        dataset.data
        .group_by(["session_code", "minute_of_session"])
        .agg(
            pl.len().alias("observations"),
            *_rate_expressions(targets),
            pl.col("mfe_atr").median().alias("median_mfe_atr"),
            pl.col("mae_atr").median().alias("median_mae_atr"),
        )
        .filter(pl.col("observations") >= minimum_observations)
        .sort(["session_code", "minute_of_session"])
    )


# -----------------------------------------------------------------------------
# Agrupa por día ISO y agrega una etiqueta legible.
# -----------------------------------------------------------------------------
def calculate_by_weekday(
    dataset: ResearchDataset,
    *,
    targets: tuple[str, ...] = DEFAULT_BINARY_TARGETS,
) -> pl.DataFrame:
    """Frecuencias por sesión y día ISO de la observación."""

    _validate_binary_targets(dataset.data, targets)
    return (
        dataset.data
        .group_by(["session_code", "iso_weekday"])
        .agg(
            pl.len().alias("observations"),
            *_rate_expressions(targets),
            pl.col("mfe_atr").median().alias("median_mfe_atr"),
            pl.col("mae_atr").median().alias("median_mae_atr"),
        )
        .with_columns(
            pl.col("iso_weekday")
            .replace_strict(
                WEEKDAY_LABELS,
                default="desconocido",
                return_dtype=pl.String,
            )
            .alias("weekday_name")
        )
        .sort(["session_code", "iso_weekday"])
    )


# -----------------------------------------------------------------------------
# Ajusta terciles ATR exclusivamente con datos de referencia.
# -----------------------------------------------------------------------------
def _fit_atr_regime_thresholds(
    reference_data: pl.DataFrame,
) -> tuple[float, float]:
    """Ajusta cortes terciles usando solo los datos de referencia."""

    if reference_data.is_empty():
        raise ValueError("reference_data está vacío.")
    if "atr" not in reference_data.columns:
        raise ValueError("reference_data no contiene la columna atr.")

    quantiles = reference_data.select(
        pl.col("atr").quantile(1 / 3, interpolation="linear").alias("q33"),
        pl.col("atr").quantile(2 / 3, interpolation="linear").alias("q67"),
    ).row(0, named=True)

    q33 = float(quantiles["q33"])
    q67 = float(quantiles["q67"])
    if q33 > q67:
        raise ValueError("Los cuantiles ATR son inconsistentes.")
    return q33, q67


# -----------------------------------------------------------------------------
# Aplica cortes ya aprendidos sin recalcularlos en inference.
# -----------------------------------------------------------------------------
def add_atr_regime(
    dataframe: pl.DataFrame,
    *,
    q33: float,
    q67: float,
) -> pl.DataFrame:
    """Aplica cortes previamente ajustados, sin recalcularlos en test."""

    return dataframe.with_columns(
        pl.when(pl.col("atr") <= q33)
        .then(pl.lit("low"))
        .when(pl.col("atr") <= q67)
        .then(pl.lit("medium"))
        .otherwise(pl.lit("high"))
        .alias("atr_regime")
    )


# -----------------------------------------------------------------------------
# Resume resultados dentro de volatilidad baja, media y alta.
# -----------------------------------------------------------------------------
def calculate_by_volatility_regime(
    dataset: ResearchDataset,
    *,
    targets: tuple[str, ...] = DEFAULT_BINARY_TARGETS,
    reference_data: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """Baseline por terciles ATR.

    En pruebas futuras, reference_data debe ser exclusivamente train. Si no se
    proporciona, usa el dataset recibido y el resultado es descriptivo.
    """

    _validate_binary_targets(dataset.data, targets)
    reference = reference_data if reference_data is not None else dataset.data
    q33, q67 = _fit_atr_regime_thresholds(reference)
    classified = add_atr_regime(dataset.data, q33=q33, q67=q67)

    return (
        classified
        .group_by(["session_code", "atr_regime"])
        .agg(
            pl.len().alias("observations"),
            *_rate_expressions(targets),
            pl.col("mfe_atr").median().alias("median_mfe_atr"),
            pl.col("mae_atr").median().alias("median_mae_atr"),
        )
        .with_columns(
            pl.lit(q33).alias("atr_q33"),
            pl.lit(q67).alias("atr_q67"),
        )
        .sort(["session_code", "atr_regime"])
    )


# -----------------------------------------------------------------------------
# Aprende frecuencias en train y las aplica a filas posteriores.
# -----------------------------------------------------------------------------
def build_constant_predictions(
    train_data: pl.DataFrame,
    inference_data: pl.DataFrame,
    *,
    target: str = "target_peak_075_atr",
    group_columns: tuple[str, ...] = (),
    minimum_group_observations: int = 1,
    fallback_to_global: bool = True,
) -> pl.DataFrame:
    """Predice la frecuencia observada en train sobre filas posteriores.

    Nunca usa el target de inference_data para crear la probabilidad. Esta
    función será reutilizable en validación walk-forward.
    """

    if target not in train_data.columns:
        raise ValueError(f"train_data no contiene {target!r}.")
    missing_groups = set(group_columns) - set(train_data.columns)
    missing_groups |= set(group_columns) - set(inference_data.columns)
    if missing_groups:
        raise ValueError(
            f"Faltan columnas de agrupación: {sorted(missing_groups)}"
        )
    if train_data.is_empty() or inference_data.is_empty():
        raise ValueError("train_data e inference_data deben contener filas.")

    global_probability = float(train_data[target].mean())

    if not group_columns:
        return inference_data.select("observation_id").with_columns(
            pl.lit(global_probability).alias("baseline_probability"),
            pl.lit("global").alias("baseline_source"),
            pl.lit(target).alias("baseline_target"),
        )

    rates = (
        train_data
        .group_by(list(group_columns))
        .agg(
            pl.len().alias("baseline_group_observations"),
            pl.col(target).mean().alias("baseline_group_probability"),
        )
        .filter(
            pl.col("baseline_group_observations")
            >= minimum_group_observations
        )
    )

    predictions = inference_data.select(
        "observation_id",
        *group_columns,
    ).join(
        rates,
        on=list(group_columns),
        how="left",
        validate="m:1",
    )

    if fallback_to_global:
        predictions = predictions.with_columns(
            pl.col("baseline_group_probability")
            .fill_null(global_probability)
            .alias("baseline_probability"),
            pl.when(pl.col("baseline_group_probability").is_null())
            .then(pl.lit("global_fallback"))
            .otherwise(pl.lit("group"))
            .alias("baseline_source"),
        )
    else:
        predictions = predictions.with_columns(
            pl.col("baseline_group_probability").alias(
                "baseline_probability"
            ),
            pl.lit("group").alias("baseline_source"),
        )

    return predictions.with_columns(
        pl.lit(target).alias("baseline_target")
    )


# -----------------------------------------------------------------------------
# Orquesta todas las referencias descriptivas del dataset.
# -----------------------------------------------------------------------------
def build_baseline_report(
    dataset: ResearchDataset,
    *,
    targets: tuple[str, ...] = DEFAULT_BINARY_TARGETS,
    minimum_minute_observations: int = 1,
) -> BaselineReport:
    """Construye el reporte descriptivo completo del dataset recibido."""

    global_rates = calculate_global_rates(dataset, targets=targets)
    by_session = calculate_by_session(dataset, targets=targets)
    by_session_minute = calculate_by_session_minute(
        dataset,
        targets=targets,
        minimum_observations=minimum_minute_observations,
    )
    by_weekday = calculate_by_weekday(dataset, targets=targets)
    by_volatility = calculate_by_volatility_regime(
        dataset,
        targets=targets,
    )
    constant_predictions = build_constant_predictions(
        dataset.data,
        dataset.data,
        target="target_peak_075_atr",
    )

    return BaselineReport(
        rows=dataset.data.height,
        session_codes=tuple(
            sorted(dataset.data["session_code"].unique().to_list())
        ),
        binary_targets=targets,
        global_rates=global_rates,
        by_session=by_session,
        by_session_minute=by_session_minute,
        by_weekday=by_weekday,
        by_volatility_regime=by_volatility,
        constant_predictions=constant_predictions,
    )
