"""Modelos experimentales de Dentour Protocol MT5 Research.

Este módulo implementa la primera referencia de machine learning de DPMT5:
una regresión logística regularizada que devuelve probabilidades para un target
binario de expansión futura. No guarda artefactos, no lee Parquet y no entrena
dentro de solicitudes HTTP.

Flujo:
    TemporalSplit + ResearchDataset
    -> extraer X e y de train
    -> ajustar StandardScaler únicamente con train
    -> probar varios valores C
    -> evaluar cada candidato en validation
    -> elegir menor Brier, luego menor log loss y luego menor C
    -> reentrenar el candidato elegido únicamente con train
    -> producir probabilidades auditables

El test nunca participa en selección de C ni en escalado.
"""
from __future__ import annotations

# Dataclasses inmutables conservan configuración y resultados auditables.
from dataclasses import dataclass
from typing import Final

# NumPy representa las matrices que consume scikit-learn.
import numpy as np
# Polars conserva identificadores y presenta resultados tabulares.
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from research.dataset import ResearchDataset
from research.validation import TemporalSplit

# Target binario inicial: alcanzar al menos 0.75 ATR dentro del horizonte.
DEFAULT_TARGET: Final[str] = "target_peak_075_atr"
# C pequeño implica regularización más fuerte; C grande, más flexibilidad.
DEFAULT_C_GRID: Final[tuple[float, ...]] = (0.01, 0.1, 1.0, 10.0)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Configuración reproducible del modelo logístico."""
    target: str = DEFAULT_TARGET
    c_values: tuple[float, ...] = DEFAULT_C_GRID
    max_iter: int = 2000
    class_weight: str | None = None
    random_state: int = 42
    solver: str = "liblinear"

    def __post_init__(self) -> None:
        # La primera versión solo admite targets binarios de expansión.
        if not self.target.startswith("target_peak_"):
            raise ValueError("El primer modelo solo admite targets binarios peak.")
        if not self.c_values or any(value <= 0 for value in self.c_values):
            raise ValueError("c_values debe contener valores positivos.")
        if self.max_iter < 100:
            raise ValueError("max_iter debe ser al menos 100.")


@dataclass(frozen=True, slots=True)
class CandidateResult:
    """Métricas de validation para un valor C candidato."""
    c_value: float
    validation_brier: float
    validation_log_loss: float


@dataclass(frozen=True, slots=True)
class TrainedModel:
    """Pipeline ajustado y metadatos necesarios para auditarlo."""
    pipeline: Pipeline
    target: str
    feature_columns: tuple[str, ...]
    selected_c: float
    candidates: tuple[CandidateResult, ...]
    train_rows: int
    validation_rows: int
    positive_rate_train: float
    positive_rate_validation: float


@dataclass(frozen=True, slots=True)
class PredictionResult:
    """Predicciones probabilísticas asociadas a sus identificadores."""
    data: pl.DataFrame
    target: str
    rows: int


def _validate_binary_target(dataframe: pl.DataFrame, target: str) -> None:
    """Exige existencia, valores 0/1 y presencia de ambas clases."""
    if target not in dataframe.columns:
        raise ValueError(f"El DataFrame no contiene {target!r}.")
    values = set(dataframe[target].unique().to_list())
    if not values <= {0, 1}:
        raise ValueError(f"{target} contiene valores no binarios: {values}")
    if len(values) < 2:
        raise ValueError(
            f"{target} solo contiene una clase. No se puede entrenar regresion logistica."
        )


def _matrix(dataframe: pl.DataFrame, feature_columns: tuple[str, ...]) -> np.ndarray:
    """Convierte exclusivamente las features registradas a una matriz float64."""
    missing = set(feature_columns) - set(dataframe.columns)
    if missing:
        raise ValueError(f"Faltan features: {sorted(missing)}")
    matrix = dataframe.select(feature_columns).to_numpy()
    if not np.isfinite(matrix).all():
        raise ValueError("La matriz X contiene NaN o infinito.")
    return matrix.astype(np.float64, copy=False)


def _target_vector(dataframe: pl.DataFrame, target: str) -> np.ndarray:
    """Valida y convierte y a un vector entero compacto."""
    _validate_binary_target(dataframe, target)
    return dataframe[target].to_numpy().astype(np.int8, copy=False)


def _new_pipeline(config: ModelConfig, c_value: float) -> Pipeline:
    """Crea un escalador y clasificador nuevos para evitar reutilizar estado."""
    return Pipeline(steps=[
        ("scaler", StandardScaler()),
        ("classifier", LogisticRegression(
            C=c_value,
            solver=config.solver,
            max_iter=config.max_iter,
            class_weight=config.class_weight,
            random_state=config.random_state,
        )),
    ])


def train_logistic_model(
    split: TemporalSplit,
    dataset: ResearchDataset,
    *,
    config: ModelConfig = ModelConfig(),
) -> TrainedModel:
    """Selecciona C con validation y devuelve un modelo ajustado con train.

    El escalador se ajusta dentro del Pipeline al llamar fit sobre train. Cada
    candidato es independiente. Validation solo decide C; test no se consulta.
    """
    if config.target not in dataset.targets:
        raise ValueError(f"Target no registrado en ResearchDataset: {config.target}")

    features = dataset.features
    x_train = _matrix(split.train, features)
    y_train = _target_vector(split.train, config.target)
    x_validation = _matrix(split.validation, features)
    y_validation = _target_vector(split.validation, config.target)

    candidates: list[CandidateResult] = []
    best_c: float | None = None
    best_key: tuple[float, float, float] | None = None

    for c_value in config.c_values:
        pipeline = _new_pipeline(config, c_value)
        pipeline.fit(x_train, y_train)
        probability = pipeline.predict_proba(x_validation)[:, 1]
        brier = float(brier_score_loss(y_validation, probability))
        loss = float(log_loss(y_validation, probability, labels=[0, 1]))
        candidates.append(CandidateResult(c_value, brier, loss))

        # Comparación lexicográfica: Brier, log loss y C más pequeño.
        key = (brier, loss, c_value)
        if best_key is None or key < best_key:
            best_key = key
            best_c = c_value

    if best_c is None:
        raise RuntimeError("No se pudo seleccionar C.")

    final_pipeline = _new_pipeline(config, best_c)
    final_pipeline.fit(x_train, y_train)

    return TrainedModel(
        pipeline=final_pipeline,
        target=config.target,
        feature_columns=features,
        selected_c=best_c,
        candidates=tuple(candidates),
        train_rows=split.train.height,
        validation_rows=split.validation.height,
        positive_rate_train=float(y_train.mean()),
        positive_rate_validation=float(y_validation.mean()),
    )


def predict_probabilities(model: TrainedModel, dataframe: pl.DataFrame) -> PredictionResult:
    """Aplica el pipeline sin utilizar el target como entrada."""
    x = _matrix(dataframe, model.feature_columns)
    probability = model.pipeline.predict_proba(x)[:, 1]

    # Conserva únicamente identificadores disponibles para unir y auditar.
    identifier_columns = tuple(column for column in (
        "observation_id", "observation_time_utc", "observation_time_cot",
        "session_code", "session_date", "minute_of_session",
    ) if column in dataframe.columns)

    output = dataframe.select(identifier_columns).with_columns(
        pl.Series("model_probability", probability),
        pl.lit(model.target).alias("model_target"),
        pl.lit(model.selected_c).alias("model_c"),
    )
    # actual_target se agrega solo para evaluación, nunca como feature.
    if model.target in dataframe.columns:
        output = output.with_columns(dataframe[model.target].alias("actual_target"))

    return PredictionResult(output, model.target, output.height)


def coefficient_table(model: TrainedModel) -> pl.DataFrame:
    """Ordena coeficientes estandarizados por magnitud absoluta.

    Un coeficiente no demuestra causalidad; expresa una asociación lineal dentro
    del modelo ajustado y depende del resto de variables y del periodo.
    """
    classifier = model.pipeline.named_steps["classifier"]
    coefficients = classifier.coef_[0]
    return (
        pl.DataFrame({"feature": model.feature_columns, "coefficient": coefficients})
        .with_columns(pl.col("coefficient").abs().alias("absolute_coefficient"))
        .sort("absolute_coefficient", descending=True)
    )


def candidate_table(model: TrainedModel) -> pl.DataFrame:
    """Convierte los candidatos de validation en una tabla auditable."""
    return pl.DataFrame([
        {
            "c_value": candidate.c_value,
            "validation_brier": candidate.validation_brier,
            "validation_log_loss": candidate.validation_log_loss,
            "selected": candidate.c_value == model.selected_c,
        }
        for candidate in model.candidates
    ]).sort("c_value")
