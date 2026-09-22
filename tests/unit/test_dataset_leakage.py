"""Pruebas de defensa contra filtración de información futura."""

from __future__ import annotations

import unittest

from research.dataset import validate_feature_contract


class DatasetLeakageTests(unittest.TestCase):
    """Impide que targets o resultados posteriores entren dentro de X."""

    def test_clean_features_pass(self) -> None:
        """Variables causales ordinarias deben aceptarse."""

        validate_feature_contract(
            ("atr", "volume_ratio", "h1_direction")
        )

    def test_future_and_target_columns_are_rejected(self) -> None:
        """Cada columna futura conocida debe provocar ValueError."""

        forbidden_columns = (
            "mfe_atr",
            "future_high",
            "target_peak_075_atr",
            "triple_barrier_label",
        )

        for column in forbidden_columns:
            with self.subTest(column=column):
                with self.assertRaisesRegex(
                    ValueError,
                    "Data leakage",
                ):
                    validate_feature_contract(("atr", column))

    def test_duplicate_features_are_rejected(self) -> None:
        """Una columna repetida alteraría la matriz y debe rechazarse."""

        with self.assertRaisesRegex(ValueError, "duplicadas"):
            validate_feature_contract(("atr", "atr"))


if __name__ == "__main__":
    unittest.main()
