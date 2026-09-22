"""Prueba opcional contra el Data Lake real de agosto de 2026.

Activar con:
    $env:DPMT5_RUN_INTEGRATION="1"
    python run_tests.py
"""

from __future__ import annotations

import os
import unittest

from research.data_access import create_closed_months_period, load_historical_context
from research.dataset import build_research_dataset
from research.features import build_m15_feature_frame
from research.targets import build_peak_targets
from sessions import SESSION_PRESETS


@unittest.skipUnless(
    os.getenv("DPMT5_RUN_INTEGRATION") == "1",
    "Integración real deshabilitada. Use DPMT5_RUN_INTEGRATION=1.",
)
class AugustDataLakeIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        period = create_closed_months_period(2026, 8, 2026, 8)
        cls.context = load_historical_context(period)

    def test_expected_timeframes_are_non_empty(self) -> None:
        self.assertGreater(self.context.m1.data.height, 0)
        self.assertGreater(self.context.m15.data.height, 0)
        self.assertGreater(self.context.h1.data.height, 0)

    def test_sessions_build_valid_datasets(self) -> None:
        for code in ("asia", "london", "new_york"):
            with self.subTest(session=code):
                session = SESSION_PRESETS[code]
                features = build_m15_feature_frame(
                    self.context.m15.data,
                    self.context.h1.data,
                    session=session,
                )
                targets = build_peak_targets(
                    features.data,
                    self.context.m1.data,
                    session=session,
                )
                dataset = build_research_dataset(
                    targets.data,
                    features.report,
                    targets.report,
                )
                self.assertGreater(dataset.data.height, 0)
                self.assertEqual(dataset.report.duplicate_observation_ids, 0)


if __name__ == "__main__":
    unittest.main()
