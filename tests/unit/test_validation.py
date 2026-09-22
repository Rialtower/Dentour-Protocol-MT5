from __future__ import annotations

import unittest

from research.contracts import DatasetSplitConfig
from research.dataset import DatasetReport, ResearchDataset
from research.validation import (
    MonthKey,
    available_months,
    build_single_month_development_split,
    build_walk_forward_folds,
)
from tests.helpers import make_binary_model_frame


class TemporalValidationTests(unittest.TestCase):
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
                session_codes=("new_york",), rows=frame.height,
                feature_count=3, target_count=1,
                first_observation_time=frame["observation_time_utc"].min(),
                last_observation_time=frame["observation_time_utc"].max(),
                duplicate_observation_ids=0,
                feature_columns=("feature_a", "feature_b", "feature_c"),
                target_columns=("target_peak_075_atr",),
                estimated_size_bytes=frame.estimated_size(unit="b"),
            ),
        )

    def test_single_month_split_has_disjoint_days(self) -> None:
        split = build_single_month_development_split(self.dataset)
        train_days = set(split.train["session_date"].unique())
        validation_days = set(split.validation["session_date"].unique())
        test_days = set(split.test["session_date"].unique())
        self.assertTrue(train_days.isdisjoint(validation_days))
        self.assertTrue(train_days.isdisjoint(test_days))
        self.assertTrue(validation_days.isdisjoint(test_days))
        self.assertLessEqual(
            split.train["target_horizon_end_utc"].max(),
            split.validation["observation_time_utc"].min(),
        )

    def test_walk_forward_requires_enough_months(self) -> None:
        config = DatasetSplitConfig(
            minimum_train_months=3,
            validation_months=1,
            test_months=1,
            embargo_minutes=60,
        )
        with self.assertRaisesRegex(ValueError, "insuficiente"):
            build_walk_forward_folds(
                (MonthKey(2026, 8), MonthKey(2026, 9)),
                config=config,
            )

    def test_walk_forward_month_order(self) -> None:
        months = tuple(MonthKey(2026, month) for month in range(1, 9))
        folds = build_walk_forward_folds(months)
        self.assertEqual(folds[0].train_months[0], MonthKey(2026, 1))
        self.assertEqual(folds[0].validation_months, (MonthKey(2026, 7),))
        self.assertEqual(folds[0].test_months, (MonthKey(2026, 8),))


if __name__ == "__main__":
    unittest.main()
