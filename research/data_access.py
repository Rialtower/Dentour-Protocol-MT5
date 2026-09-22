"""Acceso histórico para el laboratorio Research.

Responsabilidades:
- Construir intervalos históricos usando días de America/Bogota.
- Convertir los límites operativos COT a UTC.
- Localizar archivos Parquet M1, M15 y H1.
- Consultar Parquet mediante DuckDB.
- Seleccionar exclusivamente las columnas necesarias.
- Filtrar mediante timestamps UTC.
- Excluir fines de semana según el calendario COT.
- Entregar DataFrames Polars ordenados.

Este módulo no:
- calcula features;
- calcula targets;
- entrena modelos;
- escribe resultados;
- mantiene conexiones globales;
- consulta ticks.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from collections.abc import Iterator
from typing import Final
from zoneinfo import ZoneInfo

import duckdb
import polars as pl

from research.contracts import (
    DEFAULT_EXPERIMENT,
    ExperimentConfig,
    Timeframe,
)


logger = logging.getLogger("research.data_access")


# ---------------------------------------------------------------------------
# Configuración general
# ---------------------------------------------------------------------------

DATA_LAKE_DIR: Final[Path] = Path(
    os.getenv(
        "DATA_LAKE_DIR",
        "./data_lake",
    )
)

DB_PATH: Final[str] = os.getenv(
    "DB_PATH",
    "./local_analytics.duckdb",
)

TZ_UTC: Final[timezone] = timezone.utc

BAR_COLUMNS: Final[tuple[str, ...]] = (
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "spread",
    "real_volume",
)

SUPPORTED_TIMEFRAMES: Final[tuple[Timeframe, ...]] = (
    Timeframe.M1,
    Timeframe.M15,
    Timeframe.H1,
)


# ---------------------------------------------------------------------------
# Contratos de acceso
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class ResearchPeriod:
    """Intervalo histórico semiabierto expresado en COT y UTC.

    El intervalo utiliza la convención:

        [inicio, fin)

    `start_date_cot` está incluido.
    `end_date_cot` está excluido.

    Ejemplo:

        start_date_cot = 2026-01-01
        end_date_cot   = 2026-04-01

    Incluye enero, febrero y marzo completos.
    """

    start_date_cot: date
    end_date_cot: date

    start_cot: datetime
    end_cot: datetime

    start_utc: datetime
    end_utc: datetime

    timezone_name: str

    @property
    def calendar_days(self) -> int:
        """Cantidad de días calendario contenidos en el intervalo."""

        return (
            self.end_date_cot
            - self.start_date_cot
        ).days

    @property
    def business_days(self) -> int:
        """Cantidad de lunes a viernes del intervalo.

        No incluye un calendario oficial de festivos.
        """

        return sum(
            1
            for current_date in iter_dates(
                self.start_date_cot,
                self.end_date_cot,
            )
            if current_date.weekday() < 5
        )


@dataclass(frozen=True, slots=True)
class TimeframeFiles:
    """Archivos encontrados para una temporalidad."""

    timeframe: Timeframe
    files: tuple[Path, ...]

    @property
    def count(self) -> int:
        """Cantidad de archivos encontrados."""

        return len(self.files)

    @property
    def total_bytes(self) -> int:
        """Tamaño total de los archivos encontrados."""

        return sum(
            path.stat().st_size
            for path in self.files
            if path.is_file()
        )


@dataclass(frozen=True, slots=True)
class QueryMetrics:
    """Métricas operativas de una consulta histórica."""

    timeframe: Timeframe
    file_count: int
    file_bytes: int
    rows: int
    elapsed_ms: float
    minimum_timestamp: datetime | None
    maximum_timestamp: datetime | None


@dataclass(frozen=True, slots=True)
class HistoricalBars:
    """Resultado de consultar una temporalidad."""

    timeframe: Timeframe
    data: pl.DataFrame
    metrics: QueryMetrics


@dataclass(frozen=True, slots=True)
class HistoricalContext:
    """Conjunto histórico necesario para construir el dataset Research."""

    period: ResearchPeriod
    m1: HistoricalBars
    m15: HistoricalBars
    h1: HistoricalBars

    def get(self, timeframe: Timeframe) -> HistoricalBars:
        """Devuelve el resultado correspondiente a una temporalidad."""

        match timeframe:
            case Timeframe.M1:
                return self.m1

            case Timeframe.M15:
                return self.m15

            case Timeframe.H1:
                return self.h1

            case _:
                raise ValueError(
                    f"Temporalidad no disponible: {timeframe}"
                )


# ---------------------------------------------------------------------------
# Creación y validación del periodo histórico
# ---------------------------------------------------------------------------

def create_research_period(
    start_date_cot: date,
    end_date_cot: date,
    *,
    timezone_name: str = DEFAULT_EXPERIMENT.timezone_name,
    require_completed_days: bool = True,
) -> ResearchPeriod:
    """Construye un intervalo histórico usando fechas operativas COT.

    Parameters
    ----------
    start_date_cot:
        Primer día incluido.

    end_date_cot:
        Primer día excluido.

    timezone_name:
        Zona horaria que define el calendario operativo.

    require_completed_days:
        Si es True, no permite que el intervalo incluya el día actual
        incompleto ni fechas futuras.
    """

    if end_date_cot <= start_date_cot:
        raise ValueError(
            "end_date_cot debe ser posterior a start_date_cot."
        )

    timezone_cot = ZoneInfo(timezone_name)

    start_cot = datetime.combine(
        start_date_cot,
        datetime.min.time(),
        tzinfo=timezone_cot,
    )

    end_cot = datetime.combine(
        end_date_cot,
        datetime.min.time(),
        tzinfo=timezone_cot,
    )

    if require_completed_days:
        today_cot = datetime.now(timezone_cot).date()

        if end_date_cot > today_cot:
            raise ValueError(
                "El periodo Research solo puede utilizar días "
                "completamente finalizados."
            )

    return ResearchPeriod(
        start_date_cot=start_date_cot,
        end_date_cot=end_date_cot,
        start_cot=start_cot,
        end_cot=end_cot,
        start_utc=start_cot.astimezone(TZ_UTC),
        end_utc=end_cot.astimezone(TZ_UTC),
        timezone_name=timezone_name,
    )


def create_closed_months_period(
    start_year: int,
    start_month: int,
    end_year: int,
    end_month: int,
    *,
    timezone_name: str = DEFAULT_EXPERIMENT.timezone_name,
) -> ResearchPeriod:
    """Construye un periodo formado por meses calendario completos.

    El mes final está incluido.

    Ejemplo:

        create_closed_months_period(
            2026,
            1,
            2026,
            3,
        )

    Devuelve el intervalo:

        [2026-01-01, 2026-04-01)
    """

    _validate_year_month(
        start_year,
        start_month,
    )

    _validate_year_month(
        end_year,
        end_month,
    )

    start_date = date(
        start_year,
        start_month,
        1,
    )

    end_month_start = date(
        end_year,
        end_month,
        1,
    )

    if end_month_start < start_date:
        raise ValueError(
            "El mes final no puede ser anterior al mes inicial."
        )

    exclusive_end = _next_month(
        end_year,
        end_month,
    )

    timezone_cot = ZoneInfo(timezone_name)
    current_month_start = datetime.now(
        timezone_cot
    ).date().replace(day=1)

    if exclusive_end > current_month_start:
        raise ValueError(
            "Research solo puede utilizar meses calendario cerrados."
        )

    return create_research_period(
        start_date_cot=start_date,
        end_date_cot=exclusive_end,
        timezone_name=timezone_name,
        require_completed_days=True,
    )


def _validate_year_month(
    year: int,
    month: int,
) -> None:
    """Valida una combinación de año y mes."""

    if year < 1970 or year > 9998:
        raise ValueError(
            "El año debe estar entre 1970 y 9998."
        )

    if month < 1 or month > 12:
        raise ValueError(
            "El mes debe estar entre 1 y 12."
        )


def _next_month(
    year: int,
    month: int,
) -> date:
    """Devuelve el primer día del mes siguiente."""

    if month == 12:
        return date(
            year + 1,
            1,
            1,
        )

    return date(
        year,
        month + 1,
        1,
    )


def iter_dates(
    start_date: date,
    end_date: date,
) -> Iterator[date]:
    """Itera las fechas del intervalo semiabierto [inicio, fin)."""

    current_date = start_date

    while current_date < end_date:
        yield current_date
        current_date += timedelta(days=1)

# ---------------------------------------------------------------------------
# Descubrimiento de archivos
# ---------------------------------------------------------------------------

def discover_timeframe_files(
    period: ResearchPeriod,
    timeframe: Timeframe,
    *,
    symbol: str = DEFAULT_EXPERIMENT.symbol,
    data_lake_dir: Path = DATA_LAKE_DIR,
) -> TimeframeFiles:
    """Localiza Parquet para una temporalidad y un periodo COT.

    ingest.py particiona los archivos utilizando la fecha operativa
    colombiana enviada al pipeline:

        year=YYYY/month=MM/day=DD

    Por eso el descubrimiento utiliza días COT. El filtrado definitivo
    siempre se realiza posteriormente con timestamps UTC.
    """

    _validate_timeframe(
        timeframe
    )

    clean_symbol = symbol.strip()

    if not clean_symbol:
        raise ValueError(
            "symbol no puede estar vacío."
        )

    root = (
        data_lake_dir
        / timeframe.value
    )

    files: list[Path] = []

    for current_date in iter_dates(
        period.start_date_cot,
        period.end_date_cot,
    ):
        partition = (
            root
            / f"year={current_date:%Y}"
            / f"month={current_date:%m}"
            / f"day={current_date:%d}"
        )

        if not partition.is_dir():
            continue

        filename_pattern = (
            f"{clean_symbol}_"
            f"{timeframe.value}_"
            f"*.parquet"
        )

        files.extend(
            sorted(
                path
                for path in partition.glob(
                    filename_pattern
                )
                if path.is_file()
            )
        )

    # dict.fromkeys elimina duplicados conservando el orden.
    unique_files = tuple(
        dict.fromkeys(files)
    )

    return TimeframeFiles(
        timeframe=timeframe,
        files=unique_files,
    )


def discover_context_files(
    period: ResearchPeriod,
    *,
    config: ExperimentConfig = DEFAULT_EXPERIMENT,
    data_lake_dir: Path = DATA_LAKE_DIR,
) -> dict[Timeframe, TimeframeFiles]:
    """Localiza los archivos de todas las temporalidades de contexto."""

    discovered: dict[
        Timeframe,
        TimeframeFiles,
    ] = {}

    for timeframe in config.context_timeframes:
        discovered[timeframe] = discover_timeframe_files(
            period=period,
            timeframe=timeframe,
            symbol=config.symbol,
            data_lake_dir=data_lake_dir,
        )

    return discovered


def _validate_timeframe(
    timeframe: Timeframe,
) -> None:
    """Rechaza temporalidades no admitidas."""

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(
            f"Temporalidad no soportada: {timeframe}"
        )


# ---------------------------------------------------------------------------
# Conexión DuckDB
# ---------------------------------------------------------------------------

def open_connection(
    *,
    db_path: str = DB_PATH,
) -> duckdb.DuckDBPyConnection:
    """Abre una conexión DuckDB configurada para consultas históricas.

    Cada operación de alto nivel debe cerrar esta conexión mediante
    un bloque try/finally.
    """

    connection = duckdb.connect(
        database=db_path,
    )

    connection.execute(
        "PRAGMA threads=4"
    )

    connection.execute(
        "PRAGMA memory_limit='8GB'"
    )

    connection.execute(
        "PRAGMA preserve_insertion_order=false"
    )

    return connection


# ---------------------------------------------------------------------------
# Consulta de barras
# ---------------------------------------------------------------------------

def query_bars(
    connection: duckdb.DuckDBPyConnection,
    period: ResearchPeriod,
    timeframe_files: TimeframeFiles,
) -> HistoricalBars:
    """Consulta una temporalidad y devuelve un DataFrame Polars.

    DuckDB realiza:
    - lectura selectiva;
    - filtrado UTC;
    - exclusión de sábado y domingo en COT;
    - ordenamiento cronológico.

    Polars realiza:
    - normalización explícita del timestamp UTC;
    - creación de timestamp_cot;
    - validación final del resultado.
    """

    start_measurement = perf_counter()

    if not timeframe_files.files:
        empty_data = empty_bars_frame(
            period.timezone_name
        )

        elapsed_ms = (
            perf_counter()
            - start_measurement
        ) * 1000.0

        return HistoricalBars(
            timeframe=timeframe_files.timeframe,
            data=empty_data,
            metrics=QueryMetrics(
                timeframe=timeframe_files.timeframe,
                file_count=0,
                file_bytes=0,
                rows=0,
                elapsed_ms=elapsed_ms,
                minimum_timestamp=None,
                maximum_timestamp=None,
            ),
        )

    resolved_paths = [
        str(path.resolve())
        for path in timeframe_files.files
    ]

    query = """
        WITH filtered AS (
            SELECT
                timestamp AS timestamp_utc,
                timezone(
                    'America/Bogota',
                    timestamp
                ) AS timestamp_cot_local,
                open,
                high,
                low,
                close,
                volume,
                spread,
                real_volume
            FROM read_parquet(
                ?,
                union_by_name = true
            )
            WHERE timestamp >= ?
              AND timestamp < ?
        )
        SELECT
            timestamp_utc,
            open,
            high,
            low,
            close,
            volume,
            spread,
            real_volume
        FROM filtered
        WHERE extract(
            'isodow'
            FROM timestamp_cot_local
        ) BETWEEN 1 AND 5
        ORDER BY timestamp_utc
    """

    result = connection.execute(
        query,
        [
            resolved_paths,
            period.start_utc,
            period.end_utc,
        ],
    ).pl()

    result = normalize_bars_frame(
        result,
        timezone_name=period.timezone_name,
    )

    result, duplicate_rows_removed = reconcile_duplicate_bars(
        result,
        timeframe=timeframe_files.timeframe,
    )

    validate_bars_frame(
        result,
        timeframe=timeframe_files.timeframe,
    )

    elapsed_ms = (
        perf_counter()
        - start_measurement
    ) * 1000.0

    if result.is_empty():
        minimum_timestamp = None
        maximum_timestamp = None
    else:
        bounds = result.select(
            pl.col(
                "timestamp_utc"
            ).min().alias("minimum"),

            pl.col(
                "timestamp_utc"
            ).max().alias("maximum"),
        ).row(
            0,
            named=True,
        )

        minimum_timestamp = bounds[
            "minimum"
        ]

        maximum_timestamp = bounds[
            "maximum"
        ]

    metrics = QueryMetrics(
        timeframe=timeframe_files.timeframe,
        file_count=timeframe_files.count,
        file_bytes=timeframe_files.total_bytes,
        rows=result.height,
        elapsed_ms=elapsed_ms,
        minimum_timestamp=minimum_timestamp,
        maximum_timestamp=maximum_timestamp,
    )

    logger.info(
        (
            "Research query timeframe=%s "
            "files=%d rows=%d bytes=%d "
            "duplicates_removed=%d "
            "elapsed_ms=%.1f"
        ),
        timeframe_files.timeframe.value,
        metrics.file_count,
        metrics.rows,
        metrics.file_bytes,
        duplicate_rows_removed,
        metrics.elapsed_ms,
    )

    return HistoricalBars(
        timeframe=timeframe_files.timeframe,
        data=result,
        metrics=metrics,
    )


def normalize_bars_frame(
    dataframe: pl.DataFrame,
    *,
    timezone_name: str,
) -> pl.DataFrame:
    """Normaliza tipos y añade la representación horaria COT.

    Se conservan dos timestamps:

    timestamp_utc:
        Instante original para uniones y filtros.

    timestamp_cot:
        El mismo instante presentado en el calendario operativo.
    """

    if dataframe.is_empty():
        return empty_bars_frame(
            timezone_name
        )

    timestamp_type = dataframe.schema.get(
        "timestamp_utc"
    )

    if not isinstance(
        timestamp_type,
        pl.Datetime,
    ):
        raise TypeError(
            "timestamp_utc debe ser Datetime."
        )

    normalized = dataframe

    if timestamp_type.time_zone is None:
        normalized = normalized.with_columns(
            pl.col("timestamp_utc")
            .dt.replace_time_zone("UTC")
        )

    elif timestamp_type.time_zone != "UTC":
        normalized = normalized.with_columns(
            pl.col("timestamp_utc")
            .dt.convert_time_zone("UTC")
        )

    return (
        normalized
        .with_columns(
            pl.col("timestamp_utc")
            .dt.convert_time_zone(
                timezone_name
            )
            .alias("timestamp_cot"),

            pl.col("open").cast(
                pl.Float64,
                strict=True,
            ),

            pl.col("high").cast(
                pl.Float64,
                strict=True,
            ),

            pl.col("low").cast(
                pl.Float64,
                strict=True,
            ),

            pl.col("close").cast(
                pl.Float64,
                strict=True,
            ),

            pl.col("volume").cast(
                pl.Int64,
                strict=True,
            ),

            pl.col("spread").cast(
                pl.Int32,
                strict=True,
            ),

            pl.col("real_volume").cast(
                pl.Int64,
                strict=True,
            ),
        )
        .select(
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
        .sort("timestamp_utc")
    )


def empty_bars_frame(
    timezone_name: str,
) -> pl.DataFrame:
    """Crea un DataFrame vacío con esquema estable."""

    return pl.DataFrame(
        schema={
            "timestamp_utc": pl.Datetime(
                "us",
                time_zone="UTC",
            ),
            "timestamp_cot": pl.Datetime(
                "us",
                time_zone=timezone_name,
            ),
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
            "spread": pl.Int32,
            "real_volume": pl.Int64,
        }
    )


# ---------------------------------------------------------------------------
# Validación de resultados
# ---------------------------------------------------------------------------

def reconcile_duplicate_bars(
    dataframe: pl.DataFrame,
    *,
    timeframe: Timeframe,
) -> tuple[pl.DataFrame, int]:
    """Consolida duplicados idénticos y rechaza duplicados conflictivos.

    Un mismo timestamp puede aparecer en dos particiones diarias cuando
    la API de MT5 incluye la frontera final del intervalo.

    Solo se consolidan registros cuyos valores OHLCV sean idénticos.
    """

    if dataframe.is_empty():
        return dataframe, 0

    duplicate_mask = pl.col(
        "timestamp_utc"
    ).is_duplicated()

    duplicate_rows = dataframe.filter(
        duplicate_mask
    )

    if duplicate_rows.is_empty():
        return dataframe, 0

    value_columns = [
        "open",
        "high",
        "low",
        "close",
        "volume",
        "spread",
        "real_volume",
    ]

    conflicts = (
        duplicate_rows
        .group_by("timestamp_utc")
        .agg(
            pl.struct(value_columns)
            .n_unique()
            .alias("different_versions"),

            pl.len().alias("rows"),
        )
        .filter(
            pl.col("different_versions") > 1
        )
    )

    if not conflicts.is_empty():
        examples = conflicts.head(10)

        raise ValueError(
            f"{timeframe.value} contiene timestamps duplicados "
            "con valores OHLCV diferentes. "
            f"Ejemplos:\n{examples}"
        )

    original_rows = dataframe.height

    cleaned = (
        dataframe
        .unique(
            subset=["timestamp_utc"],
            keep="first",
            maintain_order=True,
        )
        .sort("timestamp_utc")
    )

    removed_rows = original_rows - cleaned.height

    logger.warning(
        (
            "Research consolido duplicados identicos "
            "timeframe=%s filas_eliminadas=%d"
        ),
        timeframe.value,
        removed_rows,
    )

    return cleaned, removed_rows

def validate_bars_frame(
    dataframe: pl.DataFrame,
    *,
    timeframe: Timeframe,
) -> None:
    """Valida invariantes mínimos de calidad.

    No rellena datos ni corrige precios automáticamente.
    Los problemas de calidad deben detectarse y registrarse.
    """

    required_columns = {
        "timestamp_utc",
        "timestamp_cot",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "spread",
        "real_volume",
    }

    missing_columns = (
        required_columns
        - set(dataframe.columns)
    )

    if missing_columns:
        raise ValueError(
            "Faltan columnas en "
            f"{timeframe.value}: "
            f"{sorted(missing_columns)}"
        )

    if dataframe.is_empty():
        return

    null_counts = dataframe.select(
        pl.all().null_count()
    ).row(
        0,
        named=True,
    )

    columns_with_nulls = {
        column: count
        for column, count in null_counts.items()
        if count > 0
    }

    if columns_with_nulls:
        raise ValueError(
            "Se encontraron valores nulos en "
            f"{timeframe.value}: "
            f"{columns_with_nulls}"
        )

    invalid_prices = dataframe.filter(
        (pl.col("open") <= 0)
        | (pl.col("high") <= 0)
        | (pl.col("low") <= 0)
        | (pl.col("close") <= 0)
        | (pl.col("high") < pl.col("low"))
        | (
            pl.col("high")
            < pl.max_horizontal(
                "open",
                "close",
            )
        )
        | (
            pl.col("low")
            > pl.min_horizontal(
                "open",
                "close",
            )
        )
    )

    if not invalid_prices.is_empty():
        raise ValueError(
            f"{timeframe.value} contiene "
            f"{invalid_prices.height} barras OHLC inválidas."
        )

    invalid_volume = dataframe.filter(
        (pl.col("volume") < 0)
        | (pl.col("real_volume") < 0)
        | (pl.col("spread") < 0)
    )

    if not invalid_volume.is_empty():
        raise ValueError(
            f"{timeframe.value} contiene "
            f"{invalid_volume.height} valores negativos "
            "de volumen o spread."
        )

    duplicate_count = (
        dataframe
        .select(
            pl.col("timestamp_utc")
            .is_duplicated()
            .sum()
            .alias("duplicates")
        )
        .item()
    )

    if duplicate_count:
        raise ValueError(
            f"{timeframe.value} contiene "
            f"{duplicate_count} timestamps duplicados."
        )

    if not dataframe[
        "timestamp_utc"
    ].is_sorted():
        raise ValueError(
            f"{timeframe.value} no está ordenado "
            "cronológicamente."
        )


# ---------------------------------------------------------------------------
# Carga de contexto completo
# ---------------------------------------------------------------------------

def load_historical_context(
    period: ResearchPeriod,
    *,
    config: ExperimentConfig = DEFAULT_EXPERIMENT,
    data_lake_dir: Path = DATA_LAKE_DIR,
    db_path: str = DB_PATH,
    require_all_timeframes: bool = True,
) -> HistoricalContext:
    """Carga M1, M15 y H1 para el periodo indicado.

    La conexión DuckDB se abre una sola vez para las tres consultas y
    siempre se cierra mediante finally.
    """

    discovered = discover_context_files(
        period=period,
        config=config,
        data_lake_dir=data_lake_dir,
    )

    required = {
        Timeframe.M1,
        Timeframe.M15,
        Timeframe.H1,
    }

    missing_configuration = (
        required
        - set(discovered)
    )

    if missing_configuration:
        raise ValueError(
            "La configuración no incluye todas las "
            "temporalidades necesarias: "
            f"{sorted(tf.value for tf in missing_configuration)}"
        )

    if require_all_timeframes:
        without_files = [
            timeframe.value
            for timeframe in required
            if discovered[timeframe].count == 0
        ]

        if without_files:
            raise FileNotFoundError(
                "No se encontraron Parquet para: "
                f"{without_files}"
            )

    connection = open_connection(
        db_path=db_path,
    )

    try:
        m1 = query_bars(
            connection=connection,
            period=period,
            timeframe_files=discovered[
                Timeframe.M1
            ],
        )

        m15 = query_bars(
            connection=connection,
            period=period,
            timeframe_files=discovered[
                Timeframe.M15
            ],
        )

        h1 = query_bars(
            connection=connection,
            period=period,
            timeframe_files=discovered[
                Timeframe.H1
            ],
        )

    finally:
        connection.close()

    return HistoricalContext(
        period=period,
        m1=m1,
        m15=m15,
        h1=h1,
    )


# ---------------------------------------------------------------------------
# Utilidades operativas
# ---------------------------------------------------------------------------

def summarize_context(
    context: HistoricalContext,
) -> pl.DataFrame:
    """Devuelve una tabla pequeña con métricas de carga."""

    rows = []

    for timeframe in SUPPORTED_TIMEFRAMES:
        historical = context.get(
            timeframe
        )

        rows.append(
            {
                "timeframe": timeframe.value,
                "files": historical.metrics.file_count,
                "file_bytes": historical.metrics.file_bytes,
                "rows": historical.metrics.rows,
                "elapsed_ms": historical.metrics.elapsed_ms,
                "minimum_timestamp": (
                    historical.metrics.minimum_timestamp
                ),
                "maximum_timestamp": (
                    historical.metrics.maximum_timestamp
                ),
            }
        )

    return pl.DataFrame(rows)


def estimate_context_memory_bytes(
    context: HistoricalContext,
) -> int:
    """Estima la memoria ocupada por los DataFrames Polars."""

    return sum(
        historical.data.estimated_size(
            unit="b"
        )
        for historical in (
            context.m1,
            context.m15,
            context.h1,
        )
    )