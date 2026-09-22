"""Pruebas unitarias de configuraciones inmutables de Research."""

from __future__ import annotations

import unittest

from research.contracts import (
    DEFAULT_EXPERIMENT,
    DEFAULT_SPLIT,
    ExperimentConfig,
    ResearchScope,
    Timeframe,
)


class ResearchContractTests(unittest.TestCase):
    """Impide que cambios futuros rompan los contratos del experimento."""

    def test_default_experiment_is_expected_v2(self) -> None:
        """Valida la configuración base usada por el pipeline actual."""

        self.assertEqual(
            DEFAULT_EXPERIMENT.observation_timeframe,
            Timeframe.M15,
        )
        self.assertEqual(
            DEFAULT_EXPERIMENT.path_timeframe,
            Timeframe.M1,
        )
        self.assertEqual(DEFAULT_EXPERIMENT.horizon_minutes, 60)
        self.assertEqual(DEFAULT_EXPERIMENT.horizon_observation_bars, 4)
        self.assertEqual(DEFAULT_EXPERIMENT.session.code, "new_york")
        self.assertEqual(
            DEFAULT_EXPERIMENT.scope,
            ResearchScope.SINGLE_SESSION,
        )

    def test_default_split_requires_eight_months(self) -> None:
        """Se requieren 6 train + 1 validation + 1 test."""

        required_months = (
            DEFAULT_SPLIT.minimum_train_months
            + DEFAULT_SPLIT.validation_months
            + DEFAULT_SPLIT.test_months
        )
        self.assertEqual(required_months, 8)
        self.assertEqual(DEFAULT_SPLIT.embargo_minutes, 60)

    def test_invalid_atr_period_is_rejected(self) -> None:
        """ATR necesita al menos dos observaciones por contrato."""

        with self.assertRaisesRegex(ValueError, "atr_period"):
            ExperimentConfig(atr_period=1)

    def test_duplicate_or_unsorted_thresholds_are_rejected(self) -> None:
        """Los targets ATR deben ser crecientes y no repetidos."""

        with self.assertRaisesRegex(ValueError, "ordenado"):
            ExperimentConfig(
                peak_thresholds_atr=(0.75, 0.50, 1.00)
            )

        with self.assertRaisesRegex(ValueError, "ordenado"):
            ExperimentConfig(
                peak_thresholds_atr=(0.50, 0.50, 1.00)
            )

    def test_custom_session_requires_explicit_injection(self) -> None:
        """Una sesión custom no puede resolverse sin start/end explícitos."""

        config = ExperimentConfig(session_code="custom")
        with self.assertRaisesRegex(ValueError, "personalizada"):
            _ = config.session


if __name__ == "__main__":
    unittest.main()
