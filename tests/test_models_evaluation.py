from __future__ import annotations

import unittest
from dataclasses import replace

import polars as pl

from research.baselines import build_constant_predictions
from research.dataset import DatasetReport, ResearchDataset
from research.evaluation import evaluate_model_against_baseline
from research.models import ModelConfig, predict_probabilities, train_logistic_model
from research.validation import TemporalSplit, WalkForwardFold, MonthKey
from tests.helpers import make_model_frame


class ModelAndEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        frame = make_model_frame(120)
        features = ("feature_a", "feature_b")
        targets = ("target_peak_075_atr",)
        cls.dataset = ResearchDataset(
            data=frame,
            identifiers=("observation_id", "observation_time_utc", "session_code"),
            features=features,
            targets=targets,
            context=(),
            report=DatasetReport(
                session_codes=("new_york",),
                rows=frame.height,
                feature_count=2,
                target_count=1,
                first_observation_time=frame["observation_time_utc"].min(),
                last_observation_time=frame["observation_time_utc"].max(),
                duplicate_observation_ids=0,
                feature_columns=features,
                target_columns=targets,
                estimated_size_bytes=frame.estimated_size(unit="b"),
            ),
        )
        fold = WalkForwardFold(
            fold_index=0,
            train_months=(MonthKey(2026, 8),),
            validation_months=(MonthKey(2026, 8),),
            test_months=(MonthKey(2026, 8),),
        )
        cls.split = TemporalSplit(
            fold=fold,
            train=frame.head(70),
            validation=frame.slice(70, 25),
            test=frame.tail(25),
            train_rows_before_purge=70,
            validation_rows_before_purge=25,
            test_rows_before_purge=25,
            purged_train_rows=0,
            purged_validation_rows=0,
            embargo_minutes=60,
        )

    def test_logistic_model_and_evaluation(self) -> None:
        model = train_logistic_model(
            self.split,
            self.dataset,
            config=ModelConfig(c_values=(0.1, 1.0)),
        )
        predictions = predict_probabilities(model, self.split.test)
        self.assertEqual(predictions.rows, self.split.test.height)

        baseline = build_constant_predictions(
            self.split.train,
            self.split.test,
            target="target_peak_075_atr",
        )
        evaluation = evaluate_model_against_baseline(
            predictions.data,
            baseline,
        )
        self.assertEqual(evaluation.model_metrics.rows, self.split.test.height)
        self.assertEqual(evaluation.baseline_metrics.rows, self.split.test.height)
        self.assertEqual(evaluation.comparison.height, 2)
        self.assertFalse(evaluation.calibration.is_empty())


if __name__ == "__main__":
    unittest.main()
