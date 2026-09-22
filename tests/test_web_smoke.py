from __future__ import annotations

import unittest

try:
    from fastapi.testclient import TestClient
    from app import app
except Exception as exc:  # pragma: no cover
    TestClient = None
    app = None
    IMPORT_ERROR = exc
else:
    IMPORT_ERROR = None


@unittest.skipIf(TestClient is None, f"FastAPI TestClient no disponible: {IMPORT_ERROR}")
class WebSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.client = TestClient(app)

    def test_home_route(self) -> None:
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)

    def test_research_route(self) -> None:
        response = self.client.get("/research/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Research Lab", response.text)

    def test_openapi_route(self) -> None:
        response = self.client.get("/docs")
        self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
