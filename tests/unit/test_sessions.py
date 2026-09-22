"""Pruebas unitarias del contrato compartido de sesiones."""

from __future__ import annotations

# ``unittest`` pertenece a la biblioteca estándar y no requiere pytest.
import unittest
# Tipos temporales utilizados para escenarios específicos de sesión.
from datetime import datetime, time
# Zona IANA que representa el calendario operativo COT.
from zoneinfo import ZoneInfo

# Polars construye DataFrames pequeños para verificar filtros y columnas.
import polars as pl

# Funciones productivas que esta prueba audita directamente.
from sessions import (
    SESSION_PRESETS,
    SessionWindow,
    add_session_columns,
    filter_session,
    resolve_session,
)


class SessionWindowTests(unittest.TestCase):
    """Verifica horarios, medianoche y posición relativa en la sesión."""

    def test_all_presets_have_valid_duration_and_label(self) -> None:
        """Cada preset debe tener código, etiqueta y duración positiva."""

        for code, session in SESSION_PRESETS.items():
            # ``subTest`` indica qué preset falló sin detener los demás casos.
            with self.subTest(session=code):
                self.assertGreater(session.duration_minutes, 0)
                self.assertTrue(session.label)
                self.assertEqual(session.code, code)

    def test_full_day_is_1440_minutes(self) -> None:
        """El preset full_day debe representar exactamente un día completo."""

        session = SESSION_PRESETS["full_day"]
        self.assertTrue(session.is_full_day)
        self.assertEqual(session.duration_minutes, 1440)

    def test_custom_cross_midnight(self) -> None:
        """Una ventana 22:00-02:00 debe cruzar medianoche y durar 240 min."""

        session = resolve_session("custom", "22:00", "02:00")
        self.assertTrue(session.crosses_midnight)
        self.assertEqual(session.duration_minutes, 240)

    def test_custom_equal_hours_is_rejected(self) -> None:
        """Una sesión personalizada igual al inicio y final es ambigua."""

        with self.assertRaises(ValueError):
            resolve_session("custom", "07:00", "07:00")

    def test_unknown_session_is_rejected(self) -> None:
        """Los códigos inexistentes deben fallar con un mensaje explícito."""

        with self.assertRaisesRegex(ValueError, "Sesion desconocida"):
            resolve_session("invalid-session")

    def test_night_filter_assigns_previous_session_date(self) -> None:
        """Las barras posteriores a medianoche pertenecen al día de inicio."""

        zone = ZoneInfo("America/Bogota")

        # Solo 22:00 y 00:30 pertenecen a [22:00, 02:00).
        frame = pl.DataFrame(
            {
                "timestamp_cot": [
                    datetime(2026, 8, 10, 21, 45, tzinfo=zone),
                    datetime(2026, 8, 10, 22, 0, tzinfo=zone),
                    datetime(2026, 8, 11, 0, 30, tzinfo=zone),
                    datetime(2026, 8, 11, 2, 0, tzinfo=zone),
                ]
            },
            schema_overrides={
                "timestamp_cot": pl.Datetime(
                    "us",
                    time_zone="America/Bogota",
                )
            },
        )

        session = SessionWindow(
            "night",
            "Nocturna",
            time(22),
            time(2),
        )
        result = filter_session(frame, session)

        self.assertEqual(result.height, 2)
        self.assertEqual(
            result["minute_of_session"].to_list(),
            [0, 150],
        )
        self.assertEqual(result["session_date"].n_unique(), 1)

    def test_minute_calculation_does_not_overflow(self) -> None:
        """Protege contra el overflow Int8 detectado durante el desarrollo."""

        zone = ZoneInfo("America/Bogota")
        frame = pl.DataFrame(
            {
                "timestamp_cot": [
                    datetime(2026, 8, 10, 8, 15, tzinfo=zone)
                ]
            },
            schema_overrides={
                "timestamp_cot": pl.Datetime(
                    "us",
                    time_zone="America/Bogota",
                )
            },
        )

        result = add_session_columns(
            frame,
            SESSION_PRESETS["full_day"],
        )

        # 08:15 equivale a 8 * 60 + 15 = 495 minutos.
        self.assertEqual(result["minute_of_session"].item(), 495)
        self.assertAlmostEqual(
            result["session_progress"].item(),
            495 / 1440,
        )


# Permite ejecutar este archivo directamente con Python además de discovery.
if __name__ == "__main__":
    unittest.main()
