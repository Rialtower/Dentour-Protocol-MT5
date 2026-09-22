"""Construcción del dataset final de Research.

Responsabilidades:
- Recibir el resultado válido de research.targets.
- Separar identificadores, features y targets mediante listas explícitas.
- Impedir que columnas futuras entren como variables del modelo.
- Agregar versiones y un identificador determinista por observación.
- Construir datasets individuales o combinar sesiones compatibles.
- No consultar archivos, no recalcular features/targets y no escribir a disco.

GUÍA DIDÁCTICA AMPLIADA
========================

PROPÓSITO
---------
Este módulo convierte la salida de targets.py en el contrato final que podrán
consumir baselines, validación y modelos. No calcula nuevas variables ni vuelve
a consultar datos. Su tarea principal es separar explícitamente:

    identificadores | contexto | features X | targets y | calidad | versiones

PROTECCIÓN CONTRA DATA LEAKAGE
------------------------------
El módulo rechaza columnas futuras o derivadas del resultado, como MFE, MAE,
triple barrera, timestamps futuros y columnas con prefijos target_ o future_.
Esta defensa es independiente del modelo para que cualquier algoritmo posterior
reciba el mismo contrato causal.

IDENTIDAD Y REPRODUCIBILIDAD
----------------------------
Cada observación obtiene un observation_id determinista basado en símbolo,
sesión, timestamp UTC y versión experimental. Además, un fingerprint SHA-256
abreviado identifica el conjunto y orden de features y targets.

COMBINACIÓN DE SESIONES
-----------------------
Los datasets solo pueden concatenarse cuando coinciden features, targets y
esquema Polars. La identidad session_code se conserva como metadato, pero no se
incluye automáticamente como feature numérica.

ORDEN DE LECTURA
----------------
1. Listas de columnas y defensas contra fuga.
2. DatasetReport y ResearchDataset.
3. observation_id y fingerprint.
4. Validación integral del DataFrame.
5. Construcción de una sesión.
6. Combinación de múltiples sesiones.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Iterable

import polars as pl

from research.contracts import DEFAULT_EXPERIMENT, ExperimentConfig
from research.features import FeatureBuildReport
from research.targets import TargetBuildReport


IDENTIFIER_COLUMNS: Final[tuple[str, ...]] = (
    "observation_id",
    "timestamp_utc",
    "timestamp_cot",
    "observation_time_utc",
    "observation_time_cot",
    "session_code",
    "session_date",
    "minute_of_session",
    "session_progress",
)

CONTEXT_COLUMNS: Final[tuple[str, ...]] = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "spread",
    "real_volume",
    "atr",
    "daily_vwap",
    "session_vwap",
    "reference_price",
    "session_start_utc",
    "session_end_utc",
    "target_horizon_end_utc",
)

TARGET_COLUMNS: Final[tuple[str, ...]] = (
    "target_peak_050_atr",
    "target_peak_075_atr",
    "target_peak_100_atr",
    "mfe_points",
    "mae_points",
    "adverse_before_peak_points",
    "mfe_atr",
    "mae_atr",
    "adverse_before_peak_atr",
    "time_to_peak_minutes",
    "time_to_trough_minutes",
    "peak_timestamp_utc",
    "trough_timestamp_utc",
    "triple_barrier_label",
    "triple_barrier_threshold_atr",
    "adverse_barrier_threshold_atr",
    "first_barrier_touch_minutes",
)

QUALITY_COLUMNS: Final[tuple[str, ...]] = (
    "target_valid",
    "target_ambiguous",
    "target_horizon_inside_session",
    "target_exclusion_reason",
)

VERSION_COLUMNS: Final[tuple[str, ...]] = (
    "feature_version",
    "target_version",
    "dataset_version",
    "experiment_version",
)

FORBIDDEN_FEATURE_PREFIXES: Final[tuple[str, ...]] = (
    "target_",
    "future_",
)

FORBIDDEN_FEATURE_COLUMNS: Final[frozenset[str]] = frozenset(
    set(TARGET_COLUMNS)
    | set(QUALITY_COLUMNS)
    | {
        "reference_price",
        "session_start_utc",
        "session_end_utc",
        "mfe_points",
        "mae_points",
        "mfe_atr",
        "mae_atr",
        "adverse_before_peak_points",
        "adverse_before_peak_atr",
        "time_to_peak_minutes",
        "time_to_trough_minutes",
        "peak_timestamp_utc",
        "trough_timestamp_utc",
        "triple_barrier_label",
        "first_barrier_touch_minutes",
    }
)


@dataclass(frozen=True, slots=True)
# -----------------------------------------------------------------------------
# Contrato inmutable que resume tamaño, rango temporal y esquema del dataset.
# -----------------------------------------------------------------------------
class DatasetReport:
    """Resumen auditable del dataset construido."""

    session_codes: tuple[str, ...]
    rows: int
    feature_count: int
    target_count: int
    first_observation_time: object | None
    last_observation_time: object | None
    duplicate_observation_ids: int
    feature_columns: tuple[str, ...]
    target_columns: tuple[str, ...]
    estimated_size_bytes: int


@dataclass(frozen=True, slots=True)
# -----------------------------------------------------------------------------
# Contenedor principal; mantiene X, y, identificadores y contexto separados.
# -----------------------------------------------------------------------------
class ResearchDataset:
    """Dataset final con contratos explícitos para entrenamiento posterior."""

    data: pl.DataFrame
    identifiers: tuple[str, ...]
    features: tuple[str, ...]
    targets: tuple[str, ...]
    context: tuple[str, ...]
    report: DatasetReport

    def feature_frame(self) -> pl.DataFrame:
        """Devuelve únicamente X, sin identificadores ni targets."""

        return self.data.select(self.features)

    def target_frame(self, *target_columns: str) -> pl.DataFrame:
        """Devuelve y para uno o varios targets permitidos."""

        selected = target_columns or self.targets
        unknown = set(selected) - set(self.targets)
        if unknown:
            raise ValueError(f"Targets no registrados: {sorted(unknown)}")
        return self.data.select(selected)

    def identifier_frame(self) -> pl.DataFrame:
        return self.data.select(self.identifiers)


# -----------------------------------------------------------------------------
# Conserva únicamente columnas realmente presentes sin alterar el orden declarado.
# -----------------------------------------------------------------------------
def _existing_columns(
    dataframe: pl.DataFrame,
    columns: Iterable[str],
) -> tuple[str, ...]:
    available = set(dataframe.columns)
    return tuple(column for column in columns if column in available)


# -----------------------------------------------------------------------------
# Construye una clave legible y determinista para uniones y auditoría.
# -----------------------------------------------------------------------------
def _observation_id_expression(config: ExperimentConfig) -> pl.Expr:
    """Crea una clave legible; su unicidad se valida posteriormente."""

    return pl.concat_str(
        [
            pl.lit(config.symbol),
            pl.col("session_code"),
            pl.col("observation_time_utc").dt.strftime(
                "%Y%m%dT%H%M%S%z"
            ),
            pl.lit(config.experiment_version),
        ],
        separator="|",
    ).alias("observation_id")


# -----------------------------------------------------------------------------
# Resume versiones y orden de columnas en un hash estable de 16 caracteres.
# -----------------------------------------------------------------------------
def _schema_fingerprint(
    feature_columns: tuple[str, ...],
    target_columns: tuple[str, ...],
    config: ExperimentConfig,
) -> str:
    payload = "|".join(
        (
            config.dataset_version,
            config.feature_version,
            config.target_version,
            *feature_columns,
            "--targets--",
            *target_columns,
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


# -----------------------------------------------------------------------------
# Primera barrera explícita contra targets o futuro dentro de X.
# -----------------------------------------------------------------------------
def validate_feature_contract(feature_columns: tuple[str, ...]) -> None:
    """Impide introducir targets o futuro dentro de X."""

    duplicated = {
        column
        for column in feature_columns
        if feature_columns.count(column) > 1
    }
    if duplicated:
        raise ValueError(f"Features duplicadas: {sorted(duplicated)}")

    forbidden = set(feature_columns) & FORBIDDEN_FEATURE_COLUMNS
    forbidden.update(
        column
        for column in feature_columns
        if column.startswith(FORBIDDEN_FEATURE_PREFIXES)
    )
    if forbidden:
        raise ValueError(
            "Data leakage: columnas futuras registradas como features: "
            f"{sorted(forbidden)}"
        )


# -----------------------------------------------------------------------------
# Auditoría integral antes de aceptar el dataset como entrenable.
# -----------------------------------------------------------------------------
def validate_dataset_frame(
    dataframe: pl.DataFrame,
    *,
    feature_columns: tuple[str, ...],
    target_columns: tuple[str, ...],
) -> None:
    """Valida orden, unicidad, nulos, finitud y coherencia de targets."""

    if dataframe.is_empty():
        raise ValueError("El dataset final está vacío.")

    required = {
        "observation_id",
        "observation_time_utc",
        "session_code",
        "session_date",
        *feature_columns,
        *target_columns,
    }
    missing = required - set(dataframe.columns)
    if missing:
        raise ValueError(f"Faltan columnas del dataset: {sorted(missing)}")

    if not dataframe["observation_time_utc"].is_sorted():
        raise ValueError("El dataset no está ordenado temporalmente.")

    duplicate_ids = dataframe.select(
        pl.col("observation_id").is_duplicated().sum()
    ).item()
    if duplicate_ids:
        raise ValueError(
            f"El dataset contiene {duplicate_ids} observation_id duplicados."
        )

    null_counts = dataframe.select(
        [
            pl.col(column).null_count().alias(column)
            for column in (*feature_columns, *target_columns)
        ]
    ).row(0, named=True)
    nulls = {column: count for column, count in null_counts.items() if count}
    if nulls:
        raise ValueError(f"El dataset contiene nulos: {nulls}")

    non_finite: dict[str, int] = {}
    for column in feature_columns:
        dtype = dataframe.schema[column]
        if dtype.is_float():
            count = dataframe.select(
                (~pl.col(column).is_finite()).sum()
            ).item()
            if count:
                non_finite[column] = int(count)
    if non_finite:
        raise ValueError(f"Features no finitas: {non_finite}")

    binary_targets = tuple(
        column
        for column in target_columns
        if column.startswith("target_peak_")
    )
    for column in binary_targets:
        values = set(dataframe[column].unique().to_list())
        if not values <= {0, 1}:
            raise ValueError(
                f"{column} contiene valores fuera de 0/1: {sorted(values)}"
            )

    required_monotonic = {
        "target_peak_050_atr",
        "target_peak_075_atr",
        "target_peak_100_atr",
    }
    if required_monotonic <= set(dataframe.columns):
        inconsistent = dataframe.filter(
            (pl.col("target_peak_100_atr") > pl.col("target_peak_075_atr"))
            | (pl.col("target_peak_075_atr") > pl.col("target_peak_050_atr"))
        )
        if not inconsistent.is_empty():
            raise ValueError(
                f"Existen {inconsistent.height} targets ATR no monotónicos."
            )


# -----------------------------------------------------------------------------
# Formaliza el dataset de una única sesión a partir de targets válidos.
# -----------------------------------------------------------------------------
def build_research_dataset(
    target_data: pl.DataFrame,
    feature_report: FeatureBuildReport,
    target_report: TargetBuildReport,
    *,
    config: ExperimentConfig = DEFAULT_EXPERIMENT,
) -> ResearchDataset:
    """Formaliza un dataset de una sesión a partir de targets ya construidos."""

    if target_data.is_empty():
        raise ValueError("target_data está vacío.")

    if feature_report.session_code != target_report.session_code:
        raise ValueError(
            "FeatureBuildReport y TargetBuildReport pertenecen a sesiones distintas."
        )

    session_values = set(target_data["session_code"].unique().to_list())
    expected_session = feature_report.session_code
    if session_values != {expected_session}:
        raise ValueError(
            "target_data contiene sesiones inesperadas: "
            f"{sorted(session_values)}; esperada={expected_session!r}."
        )

    feature_columns = tuple(feature_report.feature_columns)
    target_columns = tuple(target_report.target_columns)
    validate_feature_contract(feature_columns)

    missing_features = set(feature_columns) - set(target_data.columns)
    missing_targets = set(target_columns) - set(target_data.columns)
    if missing_features or missing_targets:
        raise ValueError(
            "Contrato incompleto. "
            f"Features faltantes={sorted(missing_features)}; "
            f"targets faltantes={sorted(missing_targets)}"
        )

    schema_fingerprint = _schema_fingerprint(
        feature_columns,
        target_columns,
        config,
    )

    data = (
        target_data
        .filter(pl.col("target_valid"))
        .with_columns(
            _observation_id_expression(config),
            pl.lit(config.feature_version).alias("feature_version"),
            pl.lit(config.target_version).alias("target_version"),
            pl.lit(config.dataset_version).alias("dataset_version"),
            pl.lit(config.experiment_version).alias("experiment_version"),
            pl.lit(schema_fingerprint).alias("schema_fingerprint"),
        )
        .sort("observation_time_utc")
    )

    identifiers = _existing_columns(data, IDENTIFIER_COLUMNS)
    context = _existing_columns(data, CONTEXT_COLUMNS)
    quality = _existing_columns(data, QUALITY_COLUMNS)
    versions = _existing_columns(
        data,
        (*VERSION_COLUMNS, "schema_fingerprint"),
    )

    selected_columns = tuple(
        dict.fromkeys(
            (
                *identifiers,
                *context,
                *feature_columns,
                *target_columns,
                *quality,
                *versions,
            )
        )
    )
    data = data.select(selected_columns)

    validate_dataset_frame(
        data,
        feature_columns=feature_columns,
        target_columns=target_columns,
    )

    bounds = data.select(
        pl.col("observation_time_utc").min().alias("first"),
        pl.col("observation_time_utc").max().alias("last"),
    ).row(0, named=True)

    report = DatasetReport(
        session_codes=tuple(sorted(session_values)),
        rows=data.height,
        feature_count=len(feature_columns),
        target_count=len(target_columns),
        first_observation_time=bounds["first"],
        last_observation_time=bounds["last"],
        duplicate_observation_ids=0,
        feature_columns=feature_columns,
        target_columns=target_columns,
        estimated_size_bytes=data.estimated_size(unit="b"),
    )

    return ResearchDataset(
        data=data,
        identifiers=identifiers,
        features=feature_columns,
        targets=target_columns,
        context=context,
        report=report,
    )


# -----------------------------------------------------------------------------
# Concatena sesiones solo cuando sus contratos son completamente compatibles.
# -----------------------------------------------------------------------------
def combine_research_datasets(
    datasets: Iterable[ResearchDataset],
    *,
    config: ExperimentConfig = DEFAULT_EXPERIMENT,
) -> ResearchDataset:
    """Combina sesiones con contratos idénticos sin mezclar esquemas."""

    items = tuple(datasets)
    if not items:
        raise ValueError("No se proporcionaron datasets para combinar.")

    reference = items[0]
    for item in items[1:]:
        if item.features != reference.features:
            raise ValueError("Los datasets tienen contratos de features distintos.")
        if item.targets != reference.targets:
            raise ValueError("Los datasets tienen contratos de targets distintos.")
        if item.data.schema != reference.data.schema:
            raise ValueError("Los datasets tienen esquemas Polars incompatibles.")

    combined = pl.concat(
        [item.data for item in items],
        how="vertical",
        rechunk=True,
    ).sort("observation_time_utc")

    validate_dataset_frame(
        combined,
        feature_columns=reference.features,
        target_columns=reference.targets,
    )

    session_codes = tuple(
        sorted(combined["session_code"].unique().to_list())
    )
    bounds = combined.select(
        pl.col("observation_time_utc").min().alias("first"),
        pl.col("observation_time_utc").max().alias("last"),
    ).row(0, named=True)

    report = DatasetReport(
        session_codes=session_codes,
        rows=combined.height,
        feature_count=len(reference.features),
        target_count=len(reference.targets),
        first_observation_time=bounds["first"],
        last_observation_time=bounds["last"],
        duplicate_observation_ids=0,
        feature_columns=reference.features,
        target_columns=reference.targets,
        estimated_size_bytes=combined.estimated_size(unit="b"),
    )

    return ResearchDataset(
        data=combined,
        identifiers=reference.identifiers,
        features=reference.features,
        targets=reference.targets,
        context=reference.context,
        report=report,
    )
