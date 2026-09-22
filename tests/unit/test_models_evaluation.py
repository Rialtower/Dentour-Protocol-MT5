from __future__ import annotations

import unittest

from research.baselines import build_constant_predictions
from research.dataset import DatasetReport, ResearchDataset
from research.evaluation import evaluate_model_against_baseline
from research.models import ModelConfig, coefficient_table, predict_probabilities, train_logistic_model
from research.validation import MonthKey, TemporalSplit, WalkForwardFold
from tests.helpers import make_binary_model_frame


class ModelsAndEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        frame = make_binary_model_frame(160)
        cls.dataset = ResearchDataset(
            data=frame,
            identifiers=("observation_id", "observation_time_utc"),
            features=("feature_a", "feature_b", "feature_c"),
            targets=("target_peak_075_atr",),
            context=(),
            report=DatasetReport(
                session_codes=("new_york",), rows=160,
                feature_count=3, target_count=1,
                first_observation_time=frame["observation_time_utc"].min(),
                last_observation_time=frame["observation_time_utc"].max(),
                duplicate_observation_ids=0,
                feature_columns=("feature_a", "feature_b", "feature_c"),
                target_columns=("target_peak_075_atr",),
                estimated_size_bytes=frame.estimated_size(unit="b"),
            ),
        )
        fold = WalkForwardFold(0, (MonthKey(2026, 8),), (MonthKey(2026, 8),), (MonthKey(2026, 8),))
        cls.split = TemporalSplit(
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

    def test_train_predict_evaluate(self) -> None:
        model = train_logistic_model(
            self.split,
            self.dataset,
            config=ModelConfig(c_values=(0.01, 0.1, 1.0)),
        )
        self.assertIn(model.selected_c, (0.01, 0.1, 1.0))
        self.assertEqual(coefficient_table(model).height, 3)

        model_predictions = predict_probabilities(model, self.split.test)
        baseline_predictions = build_constant_predictions(
            self.split.train,
            self.split.test,
            target="target_peak_075_atr",
        )
        report = evaluate_model_against_baseline(
            model_predictions.data,
            baseline_predictions,
        )
        self.assertEqual(report.model_metrics.rows, self.split.test.height)
        self.assertEqual(report.baseline_metrics.rows, self.split.test.height)
        self.assertEqual(report.comparison.height, 2)
        self.assertFalse(report.calibration.is_empty())
        self.assertFalse(report.threshold_analysis.is_empty())


if __name__ == "__main__":
    unittest.main()
