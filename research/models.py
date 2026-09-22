"""Modelos experimentales de Dentour Protocol MT5 Research.

Primera version:
- regresion logistica regularizada;
- escalado aprendido exclusivamente con train;
- validacion opcional para elegir C;
- predicciones probabilisticas auditables;
- cero escritura de artefactos y cero entrenamiento HTTP.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

import numpy as np
import polars as pl
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from research.dataset import ResearchDataset
from research.validation import TemporalSplit


DEFAULT_TARGET: Final[str] = "target_peak_075_atr"
DEFAULT_C_GRID: Final[tuple[float, ...]] = (0.01, 0.1, 1.0, 10.0)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    target: str = DEFAULT_TARGET
    c_values: tuple[float, ...] = DEFAULT_C_GRID
    max_iter: int = 2000
    class_weight: str | None = None
    random_state: int = 42
    solver: str = "liblinear"

    def __post_init__(self) -> None:
        if not self.target.startswith("target_peak_"):
            raise ValueError("El primer modelo solo admite targets binarios peak.")
        if not self.c_values or any(value <= 0 for value in self.c_values):
            raise ValueError("c_values debe contener valores positivos.")
        if self.max_iter < 100:
            raise ValueError("max_iter debe ser al menos 100.")


@dataclass(frozen=True, slots=True)
class CandidateResult:
    c_value: float
    validation_brier: float
    validation_log_loss: float


@dataclass(frozen=True, slots=True)
class TrainedModel:
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
    data: pl.DataFrame
    target: str
    rows: int


def _validate_binary_target(dataframe: pl.DataFrame, target: str) -> None:
    if target not in dataframe.columns:
        raise ValueError(f"El DataFrame no contiene {target!r}.")
    values = set(dataframe[target].unique().to_list())
    if not values <= {0, 1}:
        raise ValueError(f"{target} contiene valores no binarios: {values}")
    if len(values) < 2:
        raise ValueError(
            f"{target} solo contiene una clase. No se puede entrenar regresion logistica."
        )


def _matrix(
    dataframe: pl.DataFrame,
    feature_columns: tuple[str, ...],
) -> np.ndarray:
    missing = set(feature_columns) - set(dataframe.columns)
    if missing:
        raise ValueError(f"Faltan features: {sorted(missing)}")
    matrix = dataframe.select(feature_columns).to_numpy()
    if not np.isfinite(matrix).all():
        raise ValueError("La matriz X contiene NaN o infinito.")
    return matrix.astype(np.float64, copy=False)


def _target_vector(dataframe: pl.DataFrame, target: str) -> np.ndarray:
    _validate_binary_target(dataframe, target)
    return dataframe[target].to_numpy().astype(np.int8, copy=False)


def _new_pipeline(config: ModelConfig, c_value: float) -> Pipeline:
    return Pipeline(
        steps=[
            ("scaler", StandardScaler()),
            (
                "classifier",
                LogisticRegression(
                    C=c_value,
                    penalty="l2",
                    solver=config.solver,
                    max_iter=config.max_iter,
                    class_weight=config.class_weight,
                    random_state=config.random_state,
                ),
            ),
        ]
    )


def train_logistic_model(
    split: TemporalSplit,
    dataset: ResearchDataset,
    *,
    config: ModelConfig = ModelConfig(),
) -> TrainedModel:
    """Elige C con validation y reentrena solo con train.

    Validation se usa para seleccion de hiperparametro. Test no participa.
    El modelo retornado queda entrenado en train, no train+validation, para
    mantener una separacion estricta en esta primera version.
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
        candidates.append(
            CandidateResult(
                c_value=c_value,
                validation_brier=brier,
                validation_log_loss=loss,
            )
        )
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


def predict_probabilities(
    model: TrainedModel,
    dataframe: pl.DataFrame,
) -> PredictionResult:
    """Genera probabilidades sin leer la columna target como entrada."""

    x = _matrix(dataframe, model.feature_columns)
    probability = model.pipeline.predict_proba(x)[:, 1]

    identifier_columns = tuple(
        column
        for column in (
            "observation_id",
            "observation_time_utc",
            "observation_time_cot",
            "session_code",
            "session_date",
            "minute_of_session",
        )
        if column in dataframe.columns
    )

    output = dataframe.select(identifier_columns).with_columns(
        pl.Series("model_probability", probability),
        pl.lit(model.target).alias("model_target"),
        pl.lit(model.selected_c).alias("model_c"),
    )

    if model.target in dataframe.columns:
        output = output.with_columns(
            dataframe[model.target].alias("actual_target")
        )

    return PredictionResult(
        data=output,
        target=model.target,
        rows=output.height,
    )


def coefficient_table(model: TrainedModel) -> pl.DataFrame:
    """Coeficientes estandarizados ordenados por magnitud absoluta."""

    classifier = model.pipeline.named_steps["classifier"]
    coefficients = classifier.coef_[0]
    return (
        pl.DataFrame(
            {
                "feature": model.feature_columns,
                "coefficient": coefficients,
            }
        )
        .with_columns(
            pl.col("coefficient").abs().alias("absolute_coefficient")
        )
        .sort("absolute_coefficient", descending=True)
    )


def candidate_table(model: TrainedModel) -> pl.DataFrame:
    return pl.DataFrame(
        [
            {
                "c_value": candidate.c_value,
                "validation_brier": candidate.validation_brier,
                "validation_log_loss": candidate.validation_log_loss,
                "selected": candidate.c_value == model.selected_c,
            }
            for candidate in model.candidates
        ]
    ).sort("c_value")
