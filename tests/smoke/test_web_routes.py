from __future__ import annotations

import unittest

from fastapi.testclient import TestClient
from app import app


class WebRouteSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app, raise_server_exceptions=True)

    def test_dashboard_returns_html(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/html", response.headers.get("content-type", ""))

    def test_research_home_returns_controls(self) -> None:
        response = self.client.get("/research/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Research Lab", response.text)
        self.assertIn("Validar Research", response.text)

    def test_openapi_schema_contains_research_route(self) -> None:
        response = self.client.get("/openapi.json")
        self.assertEqual(response.status_code, 200)
        paths = response.json()["paths"]
        self.assertIn("/research/", paths)
        self.assertIn("/research/analyze", paths)


if __name__ == "__main__":
    unittest.main()
