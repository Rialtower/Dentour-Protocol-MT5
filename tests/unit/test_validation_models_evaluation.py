"""Pruebas de división temporal, modelo logístico y evaluación."""

from __future__ import annotations

import unittest

from research.baselines import build_constant_predictions
from research.dataset import DatasetReport, ResearchDataset
from research.evaluation import evaluate_model_against_baseline
from research.models import (
    ModelConfig,
    coefficient_table,
    predict_probabilities,
    train_logistic_model,
)
from research.validation import (
    MonthKey,
    TemporalSplit,
    WalkForwardFold,
    build_single_month_development_split,
    build_walk_forward_folds,
)
from tests.helpers import make_binary_model_frame


class ValidationModelEvaluationTests(unittest.TestCase):
    """Comprueba el flujo train-validation-test sin Data Lake."""

    @classmethod
    def setUpClass(cls) -> None:
        """Construye un ResearchDataset mínimo con tres features."""

        frame = make_binary_model_frame(160)
        feature_columns = (
            "feature_a",
            "feature_b",
            "feature_c",
        )
        target_columns = ("target_peak_075_atr",)

        cls.dataset = ResearchDataset(
            data=frame,
            identifiers=(
                "observation_id",
                "observation_time_utc",
            ),
            features=feature_columns,
            targets=target_columns,
            context=(),
            report=DatasetReport(
                session_codes=("new_york",),
                rows=frame.height,
                feature_count=len(feature_columns),
                target_count=len(target_columns),
                first_observation_time=(
                    frame["observation_time_utc"].min()
                ),
                last_observation_time=(
                    frame["observation_time_utc"].max()
                ),
                duplicate_observation_ids=0,
                feature_columns=feature_columns,
                target_columns=target_columns,
                estimated_size_bytes=frame.estimated_size(unit="b"),
            ),
        )

    def test_single_month_split_uses_disjoint_days(self) -> None:
        """Ningún session_date debe aparecer en más de un bloque."""

        split = build_single_month_development_split(self.dataset)

        train_days = set(split.train["session_date"].unique())
        validation_days = set(
            split.validation["session_date"].unique()
        )
        test_days = set(split.test["session_date"].unique())

        self.assertTrue(train_days.isdisjoint(validation_days))
        self.assertTrue(train_days.isdisjoint(test_days))
        self.assertTrue(validation_days.isdisjoint(test_days))

        # La purga debe impedir que el horizonte de train invada validation.
        self.assertLessEqual(
            split.train["target_horizon_end_utc"].max(),
            split.validation["observation_time_utc"].min(),
        )

    def test_walk_forward_month_order(self) -> None:
        """Con ocho meses debe producir enero-junio, julio y agosto."""

        months = tuple(
            MonthKey(2026, month)
            for month in range(1, 9)
        )
        folds = build_walk_forward_folds(months)

        self.assertEqual(
            folds[0].train_months[0],
            MonthKey(2026, 1),
        )
        self.assertEqual(
            folds[0].validation_months,
            (MonthKey(2026, 7),),
        )
        self.assertEqual(
            folds[0].test_months,
            (MonthKey(2026, 8),),
        )

    def test_model_and_baseline_evaluate_same_test_rows(self) -> None:
        """Modelo y baseline deben evaluarse sobre IDs idénticos."""

        frame = self.dataset.data

        # Se crea una división explícita para aislar el test del entrenamiento.
        fold = WalkForwardFold(
            fold_index=0,
            train_months=(MonthKey(2026, 8),),
            validation_months=(MonthKey(2026, 8),),
            test_months=(MonthKey(2026, 8),),
        )
        split = TemporalSplit(
            fold=fold,
            train=frame.head(95),
            validation=frame.slice(95, 30),
            test=frame.tail(35),
            train_rows_before_purge=95,
            validation_rows_before_purge=30,
            test_rows_before_purge=35,
            purged_train_rows=0,
            purged_validation_rows=0,
            embargo_minutes=60,
        )

        # Validation selecciona C. Test queda fuera del ajuste.
        model = train_logistic_model(
            split,
            self.dataset,
            config=ModelConfig(
                c_values=(0.01, 0.1, 1.0),
            ),
        )
        self.assertIn(model.selected_c, (0.01, 0.1, 1.0))
        self.assertEqual(coefficient_table(model).height, 3)

        model_predictions = predict_probabilities(
            model,
            split.test,
        )

        # El baseline aprende únicamente la frecuencia histórica de train.
        baseline_predictions = build_constant_predictions(
            split.train,
            split.test,
            target="target_peak_075_atr",
        )

        report = evaluate_model_against_baseline(
            model_predictions.data,
            baseline_predictions,
        )

        self.assertEqual(
            report.model_metrics.rows,
            split.test.height,
        )
        self.assertEqual(
            report.baseline_metrics.rows,
            split.test.height,
        )
        self.assertEqual(report.comparison.height, 2)
        self.assertFalse(report.calibration.is_empty())
        self.assertFalse(report.threshold_analysis.is_empty())


if __name__ == "__main__":
    unittest.main()
