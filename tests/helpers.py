"""Fixtures sintéticos y utilidades compartidas por la suite de DPMT5.

Los fixtures de este archivo no intentan reproducir un mercado real. Su función
es generar datos deterministas con contratos similares a los DataFrames del
proyecto para poder detectar errores de programación sin depender de MT5,
Parquet o conectividad externa.
"""

from __future__ import annotations

# ``dataclass`` permite crear pequeños contenedores tipados para pruebas.
from dataclasses import dataclass
# Tipos temporales usados para construir series cronológicas controladas.
from datetime import date, datetime, timedelta, timezone
# ``Path`` permite localizar la raíz del proyecto de forma portable.
from pathlib import Path
# Zona IANA utilizada por el calendario operativo de DPMT5.
from zoneinfo import ZoneInfo

# NumPy genera secuencias numéricas deterministas y eficientes.
import numpy as np
# Polars crea los DataFrames con el mismo enfoque columnar de Research.
import polars as pl


# Zona operativa usada por app.py, sessions.py y Research.
TZ_COT = ZoneInfo("America/Bogota")


def project_root() -> Path:
    """Devuelve la raíz del proyecto donde debe estar ``app.py``.

    ``helpers.py`` vive en ``tests/``. Por eso ``parents[1]`` corresponde a la
    carpeta raíz que contiene tanto ``tests`` como los módulos productivos.
    """

    return Path(__file__).resolve().parents[1]


def required_project_files() -> tuple[str, ...]:
    """Enumera los archivos operativos mínimos esperados en DPMT5.

    La lista se mantiene explícita para que una prueba pueda indicar exactamente
    qué archivo falta, en vez de fallar después con un ImportError ambiguo.
    """

    return (
        "app.py",
        "ingest.py",
        "warroom.py",
        "sessions.py",
        "requirements.txt",
        "research/__init__.py",
        "research/api.py",
        "research/contracts.py",
        "research/data_access.py",
        "research/features.py",
        "research/targets.py",
        "research/dataset.py",
        "research/baselines.py",
        "research/validation.py",
        "research/models.py",
        "research/evaluation.py",
        "research/templates/research_home.html",
    )


def make_bar_frame(
    *,
    start_utc: datetime,
    periods: int,
    minutes: int,
    base_price: float = 100.0,
) -> pl.DataFrame:
    """Genera barras OHLCV deterministas y temporalmente ordenadas.

    Parameters
    ----------
    start_utc:
        Apertura UTC de la primera barra.
    periods:
        Cantidad de barras que se generarán.
    minutes:
        Separación temporal entre barras, por ejemplo 1, 15 o 60.
    base_price:
        Precio central sintético inicial.

    Las fórmulas combinan tendencia y oscilaciones suaves. No se usa azar, por
    lo que una prueba produce exactamente el mismo resultado en cada ejecución.
    """

    # Construye timestamps equidistantes, conscientes de UTC.
    timestamps = [
        start_utc + timedelta(minutes=minutes * index)
        for index in range(periods)
    ]

    # Índice numérico usado por las funciones sintéticas de precio y volumen.
    index = np.arange(periods, dtype=np.float64)

    # Precio central con una tendencia pequeña y una oscilación periódica.
    centre = base_price + index * 0.015 + np.sin(index / 11.0) * 0.75

    # Open y close son cercanos, pero no idénticos.
    opens = centre
    closes = centre + np.sin(index / 3.5) * 0.20

    # High nunca queda por debajo de open/close y low nunca queda por encima.
    highs = np.maximum(opens, closes) + 0.35
    lows = np.minimum(opens, closes) - 0.35

    # Volumen entero positivo con una variación periódica simple.
    volumes = 100 + (index.astype(np.int64) % 70)

    # Se especifican tipos explícitos para imitar el contrato de data_access.py.
    return pl.DataFrame(
        {
            "timestamp_utc": timestamps,
            "timestamp_cot": [
                timestamp.astimezone(TZ_COT)
                for timestamp in timestamps
            ],
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": volumes,
            "spread": np.full(periods, 20, dtype=np.int32),
            "real_volume": np.zeros(periods, dtype=np.int64),
        },
        schema_overrides={
            "timestamp_utc": pl.Datetime("us", time_zone="UTC"),
            "timestamp_cot": pl.Datetime(
                "us",
                time_zone="America/Bogota",
            ),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
            "spread": pl.Int32,
            "real_volume": pl.Int64,
        },
    )


def make_market_context(
    days: int = 14,
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """Crea M1, M15 y H1 continuos para integración sintética.

    Se inicia antes de agosto para proporcionar suficiente calentamiento a ATR,
    volatilidad, volumen relativo y contexto H1.
    """

    start = datetime(2026, 7, 31, 5, 0, tzinfo=timezone.utc)
    total_minutes = days * 24 * 60

    # Cada temporalidad se genera con el mismo contrato de columnas.
    m1 = make_bar_frame(
        start_utc=start,
        periods=total_minutes,
        minutes=1,
    )
    m15 = make_bar_frame(
        start_utc=start,
        periods=total_minutes // 15,
        minutes=15,
    )
    h1 = make_bar_frame(
        start_utc=start,
        periods=total_minutes // 60,
        minutes=60,
    )
    return m1, m15, h1


def make_binary_model_frame(rows: int = 160) -> pl.DataFrame:
    """Crea un dataset binario para modelos, baselines y evaluación.

    El target depende de tres features conocidas, de forma que la regresión
    logística tenga una relación aprendible sin recurrir a datos reales.
    """

    start = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
    index = np.arange(rows)

    # Tres variables numéricas simples destinadas a formar X.
    feature_a = np.sin(index / 6.0)
    feature_b = np.cos(index / 10.0)
    feature_c = (index % 8) / 8.0

    # Target binario determinista. No se utiliza azar.
    target = (
        (feature_a + 0.7 * feature_b + feature_c) > 0.35
    ).astype(np.int64)

    # Cada ocho observaciones se asigna un nuevo session_date.
    session_dates = [
        date(2026, 8, 1) + timedelta(days=position // 8)
        for position in range(rows)
    ]

    return pl.DataFrame(
        {
            "observation_id": [
                f"synthetic-{position:05d}"
                for position in range(rows)
            ],
            "timestamp_utc": [
                start + timedelta(minutes=15 * position - 15)
                for position in range(rows)
            ],
            "timestamp_cot": [
                (
                    start + timedelta(minutes=15 * position - 15)
                ).astimezone(TZ_COT)
                for position in range(rows)
            ],
            "observation_time_utc": [
                start + timedelta(minutes=15 * position)
                for position in range(rows)
            ],
            "observation_time_cot": [
                (
                    start + timedelta(minutes=15 * position)
                ).astimezone(TZ_COT)
                for position in range(rows)
            ],
            "target_horizon_end_utc": [
                start + timedelta(minutes=15 * position + 60)
                for position in range(rows)
            ],
            "session_code": ["new_york"] * rows,
            "session_date": session_dates,
            "minute_of_session": [
                ((position % 8) + 1) * 15
                for position in range(rows)
            ],
            "session_progress": [
                ((position % 8) + 1) / 12.0
                for position in range(rows)
            ],
            "feature_a": feature_a,
            "feature_b": feature_b,
            "feature_c": feature_c,
            "target_peak_075_atr": target,
        },
        schema_overrides={
            "timestamp_utc": pl.Datetime("us", time_zone="UTC"),
            "timestamp_cot": pl.Datetime(
                "us",
                time_zone="America/Bogota",
            ),
            "observation_time_utc": pl.Datetime(
                "us",
                time_zone="UTC",
            ),
            "observation_time_cot": pl.Datetime(
                "us",
                time_zone="America/Bogota",
            ),
            "target_horizon_end_utc": pl.Datetime(
                "us",
                time_zone="UTC",
            ),
        },
    ).sort("observation_time_utc")


@dataclass(frozen=True, slots=True)
class ExpectedPipelineCounts:
    """Contenedor opcional para conteos esperados en pruebas futuras."""

    features: int
    targets: int
    dataset: int

# ---------------------------------------------------------------------------
# Compatibilidad con pruebas anteriores
# ---------------------------------------------------------------------------
# Algunas pruebas todavía importan make_model_frame. La fixture vigente se
# llama make_binary_model_frame, por lo que este alias mantiene compatibilidad
# sin duplicar la generación de datos sintéticos.
make_model_frame = make_binary_model_frame