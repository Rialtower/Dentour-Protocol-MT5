"""Evaluacion probabilistica para Dentour Protocol MT5 Research.

Responsabilidades:
- Evaluar probabilidades del modelo y del baseline sobre el mismo bloque test.
- Calcular Brier score, log loss, Average Precision y ROC-AUC cuando aplique.
- Calcular precision, recall, F1 y matriz de confusion para umbrales elegidos.
- Construir tablas de calibracion y resultados por sesion.
- Comparar modelo contra baseline sin entrenar ni modificar artefactos.

Este modulo no consulta archivos, no entrena modelos y no escribe resultados.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Iterable

import numpy as np
import polars as pl
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    confusion_matrix,
    f1_score,
    log_loss,
    precision_score,
    recall_score,
    roc_auc_score,
)


DEFAULT_THRESHOLD: Final[float] = 0.50
DEFAULT_CALIBRATION_BINS: Final[int] = 10
DEFAULT_DECISION_THRESHOLDS: Final[tuple[float, ...]] = (
    0.30,
    0.40,
    0.50,
    0.60,
    0.70,
)


@dataclass(frozen=True, slots=True)
class ProbabilityMetrics:
    """Metricas de una fuente de probabilidades sobre un mismo target."""

    source: str
    rows: int
    positives: int
    positive_rate: float
    mean_probability: float
    brier: float
    log_loss: float
    average_precision: float | None
    roc_auc: float | None
    threshold: float
    true_negative: int
    false_positive: int
    false_negative: int
    true_positive: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Resultado completo de comparar modelo y baseline."""

    target: str
    model_metrics: ProbabilityMetrics
    baseline_metrics: ProbabilityMetrics
    comparison: pl.DataFrame
    calibration: pl.DataFrame
    by_session: pl.DataFrame
    threshold_analysis: pl.DataFrame
    joined_predictions: pl.DataFrame


def _validate_probability_frame(
    dataframe: pl.DataFrame,
    *,
    probability_column: str,
    actual_column: str,
    source: str,
) -> None:
    required = {
        "observation_id",
        probability_column,
        actual_column,
    }
    missing = required - set(dataframe.columns)
    if missing:
        raise ValueError(
            f"{source}: faltan columnas requeridas: {sorted(missing)}"
        )
    if dataframe.is_empty():
        raise ValueError(f"{source}: no hay predicciones para evaluar.")

    duplicate_ids = dataframe.select(
        pl.col("observation_id").is_duplicated().sum()
    ).item()
    if duplicate_ids:
        raise ValueError(
            f"{source}: existen {duplicate_ids} observation_id duplicados."
        )

    invalid_probabilities = dataframe.filter(
        pl.col(probability_column).is_null()
        | (~pl.col(probability_column).is_finite())
        | (pl.col(probability_column) < 0.0)
        | (pl.col(probability_column) > 1.0)
    )
    if not invalid_probabilities.is_empty():
        raise ValueError(
            f"{source}: {invalid_probabilities.height} probabilidades invalidas."
        )

    actual_values = set(dataframe[actual_column].drop_nulls().unique().to_list())
    if not actual_values <= {0, 1}:
        raise ValueError(
            f"{source}: actual_target contiene valores no binarios: "
            f"{sorted(actual_values)}"
        )
    if dataframe[actual_column].null_count() > 0:
        raise ValueError(f"{source}: actual_target contiene nulos.")


def _safe_ranking_metrics(
    actual: np.ndarray,
    probability: np.ndarray,
) -> tuple[float | None, float | None]:
    """Devuelve AP y ROC-AUC; ROC-AUC no existe con una sola clase."""

    if np.unique(actual).size < 2:
        return None, None
    return (
        float(average_precision_score(actual, probability)),
        float(roc_auc_score(actual, probability)),
    )


def calculate_probability_metrics(
    dataframe: pl.DataFrame,
    *,
    source: str,
    probability_column: str,
    actual_column: str = "actual_target",
    threshold: float = DEFAULT_THRESHOLD,
) -> ProbabilityMetrics:
    """Calcula metricas probabilisticas y binarias para una fuente."""

    if not 0.0 < threshold < 1.0:
        raise ValueError("threshold debe estar entre 0 y 1.")

    _validate_probability_frame(
        dataframe,
        probability_column=probability_column,
        actual_column=actual_column,
        source=source,
    )

    actual = dataframe[actual_column].to_numpy().astype(np.int8, copy=False)
    probability = dataframe[probability_column].to_numpy().astype(
        np.float64,
        copy=False,
    )
    predicted = (probability >= threshold).astype(np.int8)

    tn, fp, fn, tp = confusion_matrix(
        actual,
        predicted,
        labels=[0, 1],
    ).ravel()
    average_precision, roc_auc = _safe_ranking_metrics(actual, probability)

    return ProbabilityMetrics(
        source=source,
        rows=int(actual.size),
        positives=int(actual.sum()),
        positive_rate=float(actual.mean()),
        mean_probability=float(probability.mean()),
        brier=float(brier_score_loss(actual, probability)),
        log_loss=float(log_loss(actual, probability, labels=[0, 1])),
        average_precision=average_precision,
        roc_auc=roc_auc,
        threshold=threshold,
        true_negative=int(tn),
        false_positive=int(fp),
        false_negative=int(fn),
        true_positive=int(tp),
        precision=float(
            precision_score(actual, predicted, zero_division=0)
        ),
        recall=float(recall_score(actual, predicted, zero_division=0)),
        f1=float(f1_score(actual, predicted, zero_division=0)),
    )


def metrics_table(*metrics: ProbabilityMetrics) -> pl.DataFrame:
    """Convierte metricas a una tabla Polars pequena."""

    return pl.DataFrame(
        [
            {
                "source": item.source,
                "rows": item.rows,
                "positives": item.positives,
                "positive_rate": item.positive_rate,
                "mean_probability": item.mean_probability,
                "brier": item.brier,
                "log_loss": item.log_loss,
                "average_precision": item.average_precision,
                "roc_auc": item.roc_auc,
                "threshold": item.threshold,
                "tn": item.true_negative,
                "fp": item.false_positive,
                "fn": item.false_negative,
                "tp": item.true_positive,
                "precision": item.precision,
                "recall": item.recall,
                "f1": item.f1,
            }
            for item in metrics
        ]
    )


def build_calibration_table(
    dataframe: pl.DataFrame,
    *,
    probability_columns: tuple[str, ...] = (
        "model_probability",
        "baseline_probability",
    ),
    actual_column: str = "actual_target",
    bins: int = DEFAULT_CALIBRATION_BINS,
) -> pl.DataFrame:
    """Agrupa probabilidades en intervalos iguales de [0, 1]."""

    if bins < 2:
        raise ValueError("bins debe ser al menos 2.")

    rows: list[dict[str, object]] = []
    for probability_column in probability_columns:
        _validate_probability_frame(
            dataframe,
            probability_column=probability_column,
            actual_column=actual_column,
            source=probability_column,
        )

        classified = dataframe.with_columns(
            pl.when(pl.col(probability_column) >= 1.0)
            .then(bins - 1)
            .otherwise(
                (pl.col(probability_column) * bins)
                .floor()
                .cast(pl.Int32)
            )
            .alias("_calibration_bin")
        )

        grouped = (
            classified
            .group_by("_calibration_bin")
            .agg(
                pl.len().alias("observations"),
                pl.col(probability_column)
                .mean()
                .alias("mean_predicted_probability"),
                pl.col(actual_column)
                .mean()
                .alias("observed_frequency"),
            )
            .sort("_calibration_bin")
        )

        for row in grouped.iter_rows(named=True):
            bin_index = int(row["_calibration_bin"])
            rows.append(
                {
                    "source": probability_column,
                    "bin": bin_index,
                    "bin_lower": bin_index / bins,
                    "bin_upper": (bin_index + 1) / bins,
                    "observations": row["observations"],
                    "mean_predicted_probability": row[
                        "mean_predicted_probability"
                    ],
                    "observed_frequency": row["observed_frequency"],
                    "calibration_error": abs(
                        row["mean_predicted_probability"]
                        - row["observed_frequency"]
                    ),
                }
            )

    return pl.DataFrame(rows).sort(["source", "bin"])


def build_threshold_analysis(
    dataframe: pl.DataFrame,
    *,
    probability_column: str = "model_probability",
    actual_column: str = "actual_target",
    thresholds: Iterable[float] = DEFAULT_DECISION_THRESHOLDS,
) -> pl.DataFrame:
    """Explora consecuencias binarias sin elegir un umbral operativo."""

    _validate_probability_frame(
        dataframe,
        probability_column=probability_column,
        actual_column=actual_column,
        source=probability_column,
    )
    actual = dataframe[actual_column].to_numpy().astype(np.int8, copy=False)
    probability = dataframe[probability_column].to_numpy().astype(
        np.float64,
        copy=False,
    )

    rows: list[dict[str, object]] = []
    for threshold in thresholds:
        if not 0.0 < threshold < 1.0:
            raise ValueError(f"Umbral invalido: {threshold}")
        predicted = (probability >= threshold).astype(np.int8)
        tn, fp, fn, tp = confusion_matrix(
            actual,
            predicted,
            labels=[0, 1],
        ).ravel()
        rows.append(
            {
                "threshold": float(threshold),
                "predicted_positive_rate": float(predicted.mean()),
                "precision": float(
                    precision_score(actual, predicted, zero_division=0)
                ),
                "recall": float(
                    recall_score(actual, predicted, zero_division=0)
                ),
                "f1": float(f1_score(actual, predicted, zero_division=0)),
                "tn": int(tn),
                "fp": int(fp),
                "fn": int(fn),
                "tp": int(tp),
            }
        )
    return pl.DataFrame(rows).sort("threshold")


def build_session_evaluation(
    dataframe: pl.DataFrame,
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> pl.DataFrame:
    """Evalua modelo y baseline por sesion con las mismas filas."""

    if "session_code" not in dataframe.columns:
        raise ValueError("No existe session_code para evaluar por sesion.")

    rows: list[dict[str, object]] = []
    for session_code in sorted(dataframe["session_code"].unique().to_list()):
        session_frame = dataframe.filter(
            pl.col("session_code") == session_code
        )
        for source, column in (
            ("model", "model_probability"),
            ("baseline", "baseline_probability"),
        ):
            metrics = calculate_probability_metrics(
                session_frame,
                source=source,
                probability_column=column,
                threshold=threshold,
            )
            rows.append(
                {
                    "session_code": session_code,
                    "source": source,
                    "rows": metrics.rows,
                    "positive_rate": metrics.positive_rate,
                    "mean_probability": metrics.mean_probability,
                    "brier": metrics.brier,
                    "log_loss": metrics.log_loss,
                    "average_precision": metrics.average_precision,
                    "roc_auc": metrics.roc_auc,
                    "precision": metrics.precision,
                    "recall": metrics.recall,
                    "f1": metrics.f1,
                }
            )
    return pl.DataFrame(rows).sort(["session_code", "source"])


def join_prediction_sources(
    model_predictions: pl.DataFrame,
    baseline_predictions: pl.DataFrame,
) -> pl.DataFrame:
    """Une ambas fuentes y verifica que evalúen exactamente las mismas filas."""

    _validate_probability_frame(
        model_predictions,
        probability_column="model_probability",
        actual_column="actual_target",
        source="model",
    )
    if "baseline_probability" not in baseline_predictions.columns:
        raise ValueError(
            "baseline_predictions no contiene baseline_probability."
        )

    baseline_columns = tuple(
        column
        for column in (
            "observation_id",
            "baseline_probability",
            "baseline_source",
            "baseline_target",
        )
        if column in baseline_predictions.columns
    )

    joined = model_predictions.join(
        baseline_predictions.select(baseline_columns),
        on="observation_id",
        how="inner",
        validate="1:1",
    )

    if joined.height != model_predictions.height:
        raise ValueError(
            "Modelo y baseline no contienen las mismas observaciones: "
            f"model={model_predictions.height}, joined={joined.height}."
        )
    if joined.height != baseline_predictions.height:
        raise ValueError(
            "El baseline contiene observaciones adicionales o faltantes: "
            f"baseline={baseline_predictions.height}, joined={joined.height}."
        )

    return joined.sort("observation_time_utc")


def evaluate_model_against_baseline(
    model_predictions: pl.DataFrame,
    baseline_predictions: pl.DataFrame,
    *,
    target: str = "target_peak_075_atr",
    threshold: float = DEFAULT_THRESHOLD,
    calibration_bins: int = DEFAULT_CALIBRATION_BINS,
) -> EvaluationReport:
    """Construye la evaluación principal sobre test."""

    joined = join_prediction_sources(
        model_predictions,
        baseline_predictions,
    )

    model_metrics = calculate_probability_metrics(
        joined,
        source="model",
        probability_column="model_probability",
        threshold=threshold,
    )
    baseline_metrics = calculate_probability_metrics(
        joined,
        source="baseline",
        probability_column="baseline_probability",
        threshold=threshold,
    )

    comparison = metrics_table(model_metrics, baseline_metrics).with_columns(
        pl.when(pl.col("source") == "model")
        .then(pl.col("brier") - baseline_metrics.brier)
        .otherwise(0.0)
        .alias("brier_delta_vs_baseline"),
        pl.when(pl.col("source") == "model")
        .then(pl.col("log_loss") - baseline_metrics.log_loss)
        .otherwise(0.0)
        .alias("log_loss_delta_vs_baseline"),
    )

    return EvaluationReport(
        target=target,
        model_metrics=model_metrics,
        baseline_metrics=baseline_metrics,
        comparison=comparison,
        calibration=build_calibration_table(
            joined,
            bins=calibration_bins,
        ),
        by_session=build_session_evaluation(
            joined,
            threshold=threshold,
        ),
        threshold_analysis=build_threshold_analysis(
            joined,
        ),
        joined_predictions=joined,
    )
