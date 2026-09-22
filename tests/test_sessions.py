from __future__ import annotations

import unittest
from datetime import datetime, time
from zoneinfo import ZoneInfo

import polars as pl

from sessions import SESSION_PRESETS, SessionWindow, filter_session, resolve_session


class SessionContractTests(unittest.TestCase):
    def test_presets_have_positive_duration(self) -> None:
        for code, session in SESSION_PRESETS.items():
            with self.subTest(session=code):
                self.assertGreater(session.duration_minutes, 0)

    def test_custom_session_crosses_midnight(self) -> None:
        session = resolve_session("custom", "22:00", "02:00")
        self.assertTrue(session.crosses_midnight)
        self.assertEqual(session.duration_minutes, 240)

    def test_filter_session_assigns_night_session_date(self) -> None:
        zone = ZoneInfo("America/Bogota")
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
                "timestamp_cot": pl.Datetime("us", time_zone="America/Bogota")
            },
        )
        session = SessionWindow("night", "Nocturna", time(22), time(2))
        result = filter_session(frame, session)
        self.assertEqual(result.height, 2)
        self.assertEqual(result["minute_of_session"].to_list(), [0, 150])
        self.assertEqual(result["session_date"].n_unique(), 1)

    def test_invalid_custom_equal_hours_fails(self) -> None:
        with self.assertRaisesRegex(ValueError, "inicio y fin"):
            resolve_session("custom", "07:00", "07:00")


if __name__ == "__main__":
    unittest.main()
