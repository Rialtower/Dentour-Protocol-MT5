"""Pruebas unitarias de periodos y calidad OHLCV."""

from __future__ import annotations

import unittest
from datetime import date, datetime, timezone

import polars as pl

from research.contracts import Timeframe
from research.data_access import (
    create_research_period,
    validate_bars_frame,
)
from tests.helpers import make_bar_frame


class DataAccessValidationTests(unittest.TestCase):
    """Valida contratos antes de consultar o transformar históricos."""

    def test_period_is_semi_open_and_converted_to_utc(self) -> None:
        """El periodo incluye 1 de agosto y excluye 1 de septiembre."""

        period = create_research_period(
            date(2026, 8, 1),
            date(2026, 9, 1),
        )

        self.assertEqual(period.start_cot.date(), date(2026, 8, 1))
        self.assertEqual(period.end_cot.date(), date(2026, 9, 1))
        self.assertEqual(period.start_utc.tzinfo, timezone.utc)
        self.assertGreater(period.end_utc, period.start_utc)

    def test_invalid_period_is_rejected(self) -> None:
        """Un intervalo vacío no puede producir consultas históricas."""

        with self.assertRaises(ValueError):
            create_research_period(
                date(2026, 8, 1),
                date(2026, 8, 1),
            )

    def test_valid_frame_passes(self) -> None:
        """Un DataFrame ordenado, único y OHLC válido debe aceptarse."""

        frame = make_bar_frame(
            start_utc=datetime(2026, 8, 1, tzinfo=timezone.utc),
            periods=20,
            minutes=1,
        )
        validate_bars_frame(frame, timeframe=Timeframe.M1)

    def test_duplicate_timestamp_is_rejected(self) -> None:
        """La validación estricta no debe permitir tiempos duplicados."""

        frame = make_bar_frame(
            start_utc=datetime(2026, 8, 1, tzinfo=timezone.utc),
            periods=5,
            minutes=1,
        )
        duplicated = pl.concat([frame, frame.head(1)]).sort(
            "timestamp_utc"
        )

        with self.assertRaisesRegex(ValueError, "duplicados"):
            validate_bars_frame(
                duplicated,
                timeframe=Timeframe.M1,
            )

    def test_invalid_ohlc_is_rejected(self) -> None:
        """High por debajo de open/close debe considerarse corrupción."""

        frame = make_bar_frame(
            start_utc=datetime(2026, 8, 1, tzinfo=timezone.utc),
            periods=5,
            minutes=1,
        ).with_row_index("row_number")

        invalid = (
            frame
            .with_columns(
                pl.when(pl.col("row_number") == 0)
                .then(50.0)
                .otherwise(pl.col("high"))
                .alias("high")
            )
            .drop("row_number")
        )

        with self.assertRaisesRegex(ValueError, "OHLC"):
            validate_bars_frame(
                invalid,
                timeframe=Timeframe.M1,
            )


if __name__ == "__main__":
    unittest.main()
