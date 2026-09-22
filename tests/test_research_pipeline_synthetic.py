from __future__ import annotations

import unittest

import polars as pl

from research.baselines import build_baseline_report
from research.dataset import build_research_dataset
from research.features import build_m15_feature_frame
from research.targets import build_peak_targets
from sessions import SESSION_PRESETS
from tests.helpers import make_market_context


class SyntheticResearchPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.m1, cls.m15, cls.h1 = make_market_context(days=12)

    def test_new_york_pipeline_end_to_end(self) -> None:
        session = SESSION_PRESETS["new_york"]
        features = build_m15_feature_frame(
            m15=self.m15,
            h1=self.h1,
            session=session,
        )
        self.assertGreater(features.data.height, 0)
        self.assertEqual(features.data["session_code"].unique().to_list(), ["new_york"])

        invalid_membership = features.data.filter(
            (pl.col("timestamp_cot").dt.time() < session.start)
            | (pl.col("timestamp_cot").dt.time() >= session.end)
        )
        self.assertTrue(invalid_membership.is_empty())

        targets = build_peak_targets(
            observations=features.data,
            m1=self.m1,
            session=session,
        )
        self.assertGreater(targets.data.height, 0)
        self.assertTrue(
            targets.data.filter(
                pl.col("target_horizon_end_utc") > pl.col("session_end_utc")
            ).is_empty()
        )

        dataset = build_research_dataset(
            target_data=targets.data,
            feature_report=features.report,
            target_report=targets.report,
        )
        self.assertEqual(dataset.data.height, targets.data.height)
        self.assertEqual(dataset.feature_frame().width, len(dataset.features))
        self.assertNotIn("mfe_atr", dataset.features)

        baseline = build_baseline_report(dataset)
        self.assertEqual(baseline.rows, dataset.data.height)
        self.assertFalse(baseline.global_rates.is_empty())

    def test_target_thresholds_are_monotonic(self) -> None:
        session = SESSION_PRESETS["asia"]
        features = build_m15_feature_frame(
            m15=self.m15,
            h1=self.h1,
            session=session,
        )
        targets = build_peak_targets(
            observations=features.data,
            m1=self.m1,
            session=session,
        )
        invalid = targets.data.filter(
            (pl.col("target_peak_100_atr") > pl.col("target_peak_075_atr"))
            | (pl.col("target_peak_075_atr") > pl.col("target_peak_050_atr"))
        )
        self.assertTrue(invalid.is_empty())


if __name__ == "__main__":
    unittest.main()
