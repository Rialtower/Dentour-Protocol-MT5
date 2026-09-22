from __future__ import annotations

import importlib
import unittest
from pathlib import Path


MODULES = (
    "sessions",
    "research.contracts",
    "research.data_access",
    "research.features",
    "research.targets",
    "research.dataset",
    "research.baselines",
    "research.validation",
    "research.models",
    "research.evaluation",
    "research.api",
    "warroom",
    "app",
)


class ImportAndTemplateTests(unittest.TestCase):
    def test_modules_import_without_error(self) -> None:
        for module_name in MODULES:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)

    def test_research_template_exists_and_is_not_empty(self) -> None:
        path = Path(__file__).resolve().parents[2] / "research" / "templates" / "research_home.html"
        self.assertTrue(path.is_file(), f"No existe la plantilla: {path}")
        text = path.read_text(encoding="utf-8")
        self.assertGreater(len(text.strip()), 500)
        self.assertIn("Research Lab", text)
        self.assertIn("session_code", text)


if __name__ == "__main__":
    unittest.main()
