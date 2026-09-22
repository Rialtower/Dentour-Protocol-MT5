"""Ejecutor comentado de pruebas para Dentour Protocol MT5.

Este script descubre automáticamente archivos ``test_*.py``, ejecuta las
pruebas y genera dos informes:

- TXT para lectura humana.
- JSON para automatización, CI o una futura página administrativa.

El código no modifica datos productivos ni escribe dentro del Data Lake.
"""

from __future__ import annotations

# Consulta versiones instaladas sin importar cada paquete.
import importlib.metadata
# Captura la salida textual de unittest para incorporarla al reporte.
import io
# Serializa el informe estructurado.
import json
# Lee variables como DATA_LAKE_DIR y el interruptor de integración real.
import os
# Describe el sistema operativo del entorno de pruebas.
import platform
# Obtiene intérprete, versión y código de salida.
import sys
# Mide duración total e individual.
import time
# Convierte excepciones en tracebacks completos.
import traceback
# Framework de pruebas incluido con Python.
import unittest
# Contenedores tipados para resultados individuales.
from dataclasses import asdict, dataclass
# Genera timestamps únicos para los nombres de informes.
from datetime import datetime
# Gestiona rutas de forma portable.
from pathlib import Path


# Raíz donde viven run_tests.py, tests/ y reports/.
ROOT = Path(__file__).resolve().parent
TESTS_DIR = ROOT / "tests"
REPORTS_DIR = ROOT / "reports"

# Dependencias directas relevantes para diagnosticar incompatibilidades.
PACKAGES = (
    "fastapi",
    "uvicorn",
    "duckdb",
    "polars",
    "pandas",
    "pyarrow",
    "plotly",
    "Jinja2",
    "scikit-learn",
    "python-multipart",
    "MetaTrader5",
    "numpy",
)


@dataclass(slots=True)
class TestRecord:
    """Resultado serializable de una prueba individual."""

    test: str
    status: str
    duration_ms: float
    detail: str = ""
    traceback: str = ""


class DetailedResult(unittest.TextTestResult):
    """Extiende unittest para guardar tiempos y tracebacks por prueba."""

    def __init__(self, *args, **kwargs):
        """Inicializa el resultado estándar y estructuras auxiliares."""

        super().__init__(*args, **kwargs)
        self.records: list[TestRecord] = []
        self._start_times: dict[str, float] = {}

    def startTest(self, test) -> None:
        """Registra el instante de inicio antes de delegar a unittest."""

        self._start_times[str(test)] = time.perf_counter()
        super().startTest(test)

    def _duration(self, test) -> float:
        """Calcula milisegundos transcurridos para una prueba."""

        started = self._start_times.pop(
            str(test),
            time.perf_counter(),
        )
        return (time.perf_counter() - started) * 1000.0

    def addSuccess(self, test) -> None:
        """Registra PASS y conserva el comportamiento estándar."""

        self.records.append(
            TestRecord(
                test=str(test),
                status="PASS",
                duration_ms=self._duration(test),
            )
        )
        super().addSuccess(test)

    def addSkip(self, test, reason) -> None:
        """Registra SKIP con su razón, por ejemplo integración desactivada."""

        self.records.append(
            TestRecord(
                test=str(test),
                status="SKIP",
                duration_ms=self._duration(test),
                detail=reason,
            )
        )
        super().addSkip(test, reason)

    def addFailure(self, test, err) -> None:
        """Registra FAIL cuando una aserción no se cumple."""

        formatted_traceback = "".join(
            traceback.format_exception(*err)
        )
        self.records.append(
            TestRecord(
                test=str(test),
                status="FAIL",
                duration_ms=self._duration(test),
                detail=str(err[1]),
                traceback=formatted_traceback,
            )
        )
        super().addFailure(test, err)

    def addError(self, test, err) -> None:
        """Registra ERROR cuando una excepción impide terminar la prueba."""

        formatted_traceback = "".join(
            traceback.format_exception(*err)
        )
        self.records.append(
            TestRecord(
                test=str(test),
                status="ERROR",
                duration_ms=self._duration(test),
                detail=str(err[1]),
                traceback=formatted_traceback,
            )
        )
        super().addError(test, err)


class DetailedRunner(unittest.TextTestRunner):
    """Indica a unittest que utilice DetailedResult."""

    resultclass = DetailedResult


def package_versions() -> dict[str, str]:
    """Devuelve versiones instaladas o NOT_INSTALLED."""

    versions: dict[str, str] = {}

    for package in PACKAGES:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "NOT_INSTALLED"

    return versions


def environment_diagnostics() -> dict[str, object]:
    """Captura datos necesarios para reproducir un fallo."""

    return {
        "python_executable": sys.executable,
        "python_version": sys.version,
        "platform": platform.platform(),
        "project_root": str(ROOT),
        "working_directory": os.getcwd(),
        "real_data_tests_enabled": (
            os.getenv("DPMT5_RUN_REAL_DATA_TESTS") == "1"
        ),
        "data_lake_dir": os.getenv(
            "DATA_LAKE_DIR",
            "./data_lake",
        ),
        "packages": package_versions(),
    }


def main() -> int:
    """Descubre, ejecuta, reporta y devuelve un código de salida confiable."""

    # La carpeta puede no existir tras clonar el repositorio.
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    # El timestamp evita sobrescribir informes anteriores.
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # Discovery encuentra recursivamente todos los test_*.py dentro de tests/.
    suite = unittest.defaultTestLoader.discover(
        start_dir=str(TESTS_DIR),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )

    # StringIO conserva el texto normal de unittest para el informe TXT.
    console = io.StringIO()
    runner = DetailedRunner(
        stream=console,
        verbosity=2,
    )

    started = time.perf_counter()
    result: DetailedResult = runner.run(suite)
    elapsed_ms = (time.perf_counter() - started) * 1000.0

    # Resumen numérico centralizado para TXT y JSON.
    summary = {
        "tests_run": result.testsRun,
        "passed": sum(
            record.status == "PASS"
            for record in result.records
        ),
        "failed": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "successful": result.wasSuccessful(),
        "elapsed_ms": elapsed_ms,
    }

    # Payload JSON completo, adecuado para análisis automatizado.
    payload = {
        "generated_at": datetime.now().isoformat(),
        "environment": environment_diagnostics(),
        "summary": summary,
        "records": [
            asdict(record)
            for record in result.records
        ],
    }

    json_path = REPORTS_DIR / (
        f"dpmt5_test_report_{timestamp}.json"
    )
    txt_path = REPORTS_DIR / (
        f"dpmt5_test_report_{timestamp}.txt"
    )

    json_path.write_text(
        json.dumps(
            payload,
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Secciones iniciales del reporte humano.
    lines = [
        "DENTOUR PROTOCOL MT5 - INFORME DETALLADO DE PRUEBAS",
        "=" * 88,
        f"Generado: {payload['generated_at']}",
        (
            "Ejecutable: "
            f"{payload['environment']['python_executable']}"
        ),
        f"Python: {payload['environment']['python_version']}",
        f"Plataforma: {payload['environment']['platform']}",
        f"Data Lake: {payload['environment']['data_lake_dir']}",
        (
            "Integración real: "
            f"{payload['environment']['real_data_tests_enabled']}"
        ),
        "",
        "RESUMEN",
        "-" * 88,
        f"Pruebas ejecutadas: {summary['tests_run']}",
        f"PASS: {summary['passed']}",
        f"FAIL: {summary['failed']}",
        f"ERROR: {summary['errors']}",
        f"SKIP: {summary['skipped']}",
        (
            "Resultado global: "
            f"{'OK' if summary['successful'] else 'FALLÓ'}"
        ),
        f"Duración total: {summary['elapsed_ms']:.1f} ms",
        "",
        "VERSIONES",
        "-" * 88,
    ]

    # Incluye todas las versiones inspeccionadas.
    lines.extend(
        f"{name}: {version}"
        for name, version in payload["environment"]["packages"].items()
    )

    # Añade salida estándar y encabezado de detalle.
    lines.extend(
        [
            "",
            "SALIDA UNITTEST",
            "-" * 88,
            console.getvalue(),
            "",
            "DETALLE POR PRUEBA",
            "-" * 88,
        ]
    )

    # Cada prueba conserva su propia duración, mensaje y traceback.
    for record in result.records:
        lines.extend(
            [
                f"[{record.status}] {record.test}",
                f"Duración: {record.duration_ms:.2f} ms",
            ]
        )

        if record.detail:
            lines.append(f"Detalle: {record.detail}")

        if record.traceback:
            lines.extend(
                [
                    "Traceback completo:",
                    record.traceback,
                ]
            )

        lines.append("")

    txt_path.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    # La consola muestra el resumen y la ubicación exacta de los artefactos.
    print(console.getvalue())
    print(f"Informe TXT:  {txt_path}")
    print(f"Informe JSON: {json_path}")

    # Código 0 permite que GitHub Actions considere exitosa la ejecución.
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
