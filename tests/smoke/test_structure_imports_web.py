"""Pruebas de humo de estructura, imports, Jinja2 y FastAPI."""

from __future__ import annotations

# Importación dinámica para comprobar módulos sin duplicar sentencias import.
import importlib
import unittest
from pathlib import Path

# TestClient ejecuta rutas ASGI sin iniciar un servidor Uvicorn real.
from fastapi.testclient import TestClient

from app import app
from tests.helpers import project_root, required_project_files


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


class StructureImportAndWebTests(unittest.TestCase):
    """Detecta rápidamente archivos ausentes, imports rotos y rutas 500."""

    @classmethod
    def setUpClass(cls) -> None:
        """Crea un cliente local y propaga excepciones del backend."""

        cls.client = TestClient(
            app,
            raise_server_exceptions=True,
        )

    def test_required_files_exist(self) -> None:
        """Informa todos los archivos faltantes en un único fallo."""

        root = project_root()
        missing = [
            relative_path
            for relative_path in required_project_files()
            if not (root / relative_path).is_file()
        ]

        self.assertFalse(
            missing,
            "Archivos requeridos ausentes:\n- "
            + "\n- ".join(missing),
        )

    def test_modules_import_without_error(self) -> None:
        """Cada módulo principal debe poder importarse en el entorno virtual."""

        for module_name in MODULES:
            with self.subTest(module=module_name):
                importlib.import_module(module_name)

    def test_research_template_is_complete(self) -> None:
        """Evita repetir el error de una plantilla inexistente o vacía."""

        path = (
            project_root()
            / "research"
            / "templates"
            / "research_home.html"
        )
        self.assertTrue(
            path.is_file(),
            f"No existe la plantilla: {path}",
        )

        text = path.read_text(encoding="utf-8")
        self.assertGreater(len(text.strip()), 500)
        self.assertIn("Research Lab", text)
        self.assertIn("session_code", text)

    def test_dashboard_returns_html(self) -> None:
        """La ruta principal debe responder HTML 200."""

        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "text/html",
            response.headers.get("content-type", ""),
        )

    def test_research_home_returns_controls(self) -> None:
        """Research debe presentar controles, no una página vacía."""

        response = self.client.get("/research/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Research Lab", response.text)
        self.assertIn("Validar Research", response.text)

    def test_openapi_contains_research_routes(self) -> None:
        """Los routers deben quedar registrados dentro de app.py."""

        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)

        paths = response.json()["paths"]
        self.assertIn("/research/", paths)
        self.assertIn("/research/analyze", paths)


if __name__ == "__main__":
    unittest.main()
