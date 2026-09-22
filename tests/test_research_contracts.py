from __future__ import annotations

import unittest

from research.contracts import DEFAULT_EXPERIMENT, ExperimentConfig, Timeframe


class ResearchContractTests(unittest.TestCase):
    def test_default_experiment(self) -> None:
        self.assertEqual(DEFAULT_EXPERIMENT.observation_timeframe, Timeframe.M15)
        self.assertEqual(DEFAULT_EXPERIMENT.horizon_minutes, 60)
        self.assertEqual(DEFAULT_EXPERIMENT.horizon_observation_bars, 4)
        self.assertEqual(DEFAULT_EXPERIMENT.session.code, "new_york")

    def test_unsorted_thresholds_fail(self) -> None:
        with self.assertRaisesRegex(ValueError, "ordenado"):
            ExperimentConfig(peak_thresholds_atr=(1.0, 0.5, 0.75))

    def test_invalid_horizon_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "horizon_minutes"):
            ExperimentConfig(horizon_minutes=0)


if __name__ == "__main__":
    unittest.main()
