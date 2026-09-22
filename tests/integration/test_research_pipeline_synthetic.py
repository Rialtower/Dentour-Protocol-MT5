"""Integración sintética del pipeline Research completo."""

from __future__ import annotations

import unittest

import polars as pl

from research.baselines import build_baseline_report
from research.dataset import (
    build_research_dataset,
    combine_research_datasets,
)
from research.features import build_m15_feature_frame
from research.targets import build_peak_targets
from sessions import SESSION_PRESETS
from tests.helpers import make_market_context


class SyntheticPipelineIntegrationTests(unittest.TestCase):
    """Ejecuta varias capas sin acceder al Data Lake real."""

    @classmethod
    def setUpClass(cls) -> None:
        """Genera una sola vez el contexto sintético compartido."""

        cls.m1, cls.m15, cls.h1 = make_market_context(days=14)

    def test_pipeline_by_session(self) -> None:
        """Valida Asia, Londres, Nueva York y la combinación final."""

        datasets = []

        for code in ("asia", "london", "new_york"):
            with self.subTest(session=code):
                session = SESSION_PRESETS[code]

                # Primero se crean únicamente features causales.
                features = build_m15_feature_frame(
                    self.m15,
                    self.h1,
                    session=session,
                )
                self.assertGreater(features.data.height, 0)
                self.assertEqual(
                    set(features.data["session_code"].unique()),
                    {code},
                )

                # Ninguna apertura M15 puede quedar fuera de [start, end).
                invalid_open = features.data.filter(
                    (pl.col("timestamp_cot").dt.time() < session.start)
                    | (pl.col("timestamp_cot").dt.time() >= session.end)
                )
                self.assertTrue(invalid_open.is_empty())

                # Después se mide el futuro mediante M1.
                targets = build_peak_targets(
                    features.data,
                    self.m1,
                    session=session,
                )
                self.assertGreater(targets.data.height, 0)

                # Los targets aceptados no pueden terminar fuera de la sesión.
                outside_session = targets.data.filter(
                    pl.col("target_horizon_end_utc")
                    > pl.col("session_end_utc")
                )
                self.assertTrue(outside_session.is_empty())

                # Alcanzar 1.00 ATR implica haber alcanzado 0.75 y 0.50 ATR.
                invalid_thresholds = targets.data.filter(
                    (
                        pl.col("target_peak_100_atr")
                        > pl.col("target_peak_075_atr")
                    )
                    | (
                        pl.col("target_peak_075_atr")
                        > pl.col("target_peak_050_atr")
                    )
                )
                self.assertTrue(invalid_thresholds.is_empty())

                # Dataset separa expresamente identificadores, X e y.
                dataset = build_research_dataset(
                    targets.data,
                    features.report,
                    targets.report,
                )
                self.assertEqual(
                    dataset.data.height,
                    targets.data.height,
                )
                self.assertNotIn("mfe_atr", dataset.features)
                self.assertEqual(
                    dataset.report.duplicate_observation_ids,
                    0,
                )

                # Baselines deben producir una referencia no vacía.
                baseline = build_baseline_report(dataset)
                self.assertFalse(baseline.global_rates.is_empty())
                datasets.append(dataset)

        # Los datasets individuales deben conservar un esquema compatible.
        combined = combine_research_datasets(datasets)
        expected_rows = sum(
            dataset.data.height
            for dataset in datasets
        )
        self.assertEqual(combined.data.height, expected_rows)
        self.assertEqual(
            set(combined.report.session_codes),
            {"asia", "london", "new_york"},
        )


if __name__ == "__main__":
    unittest.main()
