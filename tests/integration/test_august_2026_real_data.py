"""Integración opcional contra agosto de 2026 en el Data Lake real.

Esta prueba se omite en ejecuciones normales porque consulta Parquet reales y
consume más tiempo y memoria que las pruebas sintéticas. Para activarla:

    $env:DPMT5_RUN_REAL_DATA_TESTS="1"
    python run_tests.py
"""

from __future__ import annotations

# Variable de entorno usada como interruptor explícito de integración real.
import os
import unittest

from research.data_access import (
    create_closed_months_period,
    load_historical_context,
)
from research.dataset import build_research_dataset
from research.features import build_m15_feature_frame
from research.targets import build_peak_targets
from sessions import SESSION_PRESETS


@unittest.skipUnless(
    os.getenv("DPMT5_RUN_REAL_DATA_TESTS") == "1",
    "Data Lake real deshabilitado. Use DPMT5_RUN_REAL_DATA_TESTS=1.",
)
class August2026RealDataTests(unittest.TestCase):
    """Valida que agosto complete el pipeline para sesiones principales."""

    @classmethod
    def setUpClass(cls) -> None:
        """Carga agosto una sola vez para no repetir consultas costosas."""

        period = create_closed_months_period(
            2026,
            8,
            2026,
            8,
        )
        cls.context = load_historical_context(period)

    def test_timeframes_are_loaded(self) -> None:
        """M1, M15 y H1 deben contener filas reales."""

        self.assertGreater(self.context.m1.data.height, 0)
        self.assertGreater(self.context.m15.data.height, 0)
        self.assertGreater(self.context.h1.data.height, 0)

    def test_each_primary_session_builds_dataset(self) -> None:
        """Cada sesión debe generar un dataset válido y no vacío."""

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
                self.assertEqual(
                    dataset.report.duplicate_observation_ids,
                    0,
                )


if __name__ == "__main__":
    unittest.main()
