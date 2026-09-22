"""Interfaz web operativa del laboratorio Research.

La ruta ejecuta de forma sincrónica y sin persistencia:
Parquet -> contexto -> features -> targets -> dataset -> baselines -> split.

No entrena modelos dentro de solicitudes HTTP.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from typing import Final

import polars as pl
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from research.baselines import build_baseline_report
from research.data_access import (
    create_closed_months_period,
    load_historical_context,
    summarize_context,
)
from research.dataset import build_research_dataset
from research.features import build_m15_feature_frame
from research.targets import build_peak_targets
from research.validation import build_single_month_development_split
from sessions import DEFAULT_SESSION_CODE, SESSION_PRESETS, resolve_session


logger = logging.getLogger("research.api")
BASE_DIR: Final[Path] = Path(__file__).resolve().parent
TEMPLATES_DIR: Final[Path] = BASE_DIR / "templates"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
router = APIRouter(prefix="/research", tags=["Research"])


def _table_html(frame: pl.DataFrame, *, max_rows: int = 40) -> str:
    """Convierte exclusivamente resultados pequeños a HTML."""

    if frame.is_empty():
        return "<p>Sin filas.</p>"
    return frame.head(max_rows).to_pandas().round(6).to_html(
        index=False,
        classes="data-table",
        border=0,
    )


def _session_options() -> tuple[dict[str, str], ...]:
    return tuple(
        {"code": code, "label": session.label}
        for code, session in SESSION_PRESETS.items()
    ) + ({"code": "custom", "label": "Personalizada"},)


def _base_context(
    *,
    year: int,
    month: int,
    session_code: str,
    session_start: str,
    session_end: str,
) -> dict[str, object]:
    return {
        "year": year,
        "month": month,
        "session_code": session_code,
        "session_start": session_start,
        "session_end": session_end,
        "session_options": _session_options(),
    }


@router.get("/", response_class=HTMLResponse)
def research_home(
    request: Request,
    year: int = Query(2026, ge=1970, le=9998),
    month: int = Query(8, ge=1, le=12),
    session_code: str = Query(DEFAULT_SESSION_CODE),
    session_start: str = Query("07:00"),
    session_end: str = Query("10:00"),
) -> HTMLResponse:
    """Muestra los controles sin ejecutar el pipeline."""

    context = _base_context(
        year=year,
        month=month,
        session_code=session_code,
        session_start=session_start,
        session_end=session_end,
    )
    context.update(
        {
            "request": request,
            "executed": False,
            "error": "",
        }
    )
    return templates.TemplateResponse(
        request=request,
        name="research_home.html",
        context=context,
    )


@router.get("/analyze", response_class=HTMLResponse)
def research_analyze(
    request: Request,
    year: int = Query(..., ge=1970, le=9998),
    month: int = Query(..., ge=1, le=12),
    session_code: str = Query(DEFAULT_SESSION_CODE),
    session_start: str = Query("07:00"),
    session_end: str = Query("10:00"),
) -> HTMLResponse:
    """Ejecuta el experimento descriptivo de un mes y una sesión."""

    context = _base_context(
        year=year,
        month=month,
        session_code=session_code,
        session_start=session_start,
        session_end=session_end,
    )
    context.update({"request": request, "executed": True, "error": ""})

    started = perf_counter()
    try:
        session = resolve_session(
            session_code,
            start=session_start,
            end=session_end,
        )
        period = create_closed_months_period(
            start_year=year,
            start_month=month,
            end_year=year,
            end_month=month,
        )
        historical = load_historical_context(period)

        features = build_m15_feature_frame(
            m15=historical.m15.data,
            h1=historical.h1.data,
            session=session,
        )
        targets = build_peak_targets(
            observations=features.data,
            m1=historical.m1.data,
            session=session,
        )
        dataset = build_research_dataset(
            target_data=targets.data,
            feature_report=features.report,
            target_report=targets.report,
        )
        baselines = build_baseline_report(
            dataset,
            minimum_minute_observations=3,
        )

        split = None
        split_error = ""
        try:
            split = build_single_month_development_split(dataset)
        except ValueError as exc:
            split_error = str(exc)

        preview_columns = tuple(
            column
            for column in (
                "observation_time_cot",
                "session_code",
                "minute_of_session",
                "atr",
                "volume_ratio",
                "distance_session_vwap_atr",
                "target_peak_075_atr",
                "mfe_atr",
                "mae_atr",
                "triple_barrier_label",
            )
            if column in dataset.data.columns
        )

        context.update(
            {
                "session_label": session.label,
                "elapsed_ms": (perf_counter() - started) * 1000.0,
                "historical_table": _table_html(summarize_context(historical)),
                "feature_report": asdict(features.report),
                "target_report": asdict(targets.report),
                "dataset_report": asdict(dataset.report),
                "global_baseline_table": _table_html(baselines.global_rates),
                "session_baseline_table": _table_html(baselines.by_session),
                "minute_baseline_table": _table_html(
                    baselines.by_session_minute,
                    max_rows=24,
                ),
                "weekday_baseline_table": _table_html(baselines.by_weekday),
                "volatility_baseline_table": _table_html(
                    baselines.by_volatility_regime
                ),
                "dataset_preview_table": _table_html(
                    dataset.data.select(preview_columns),
                    max_rows=20,
                ),
                "split": split,
                "split_error": split_error,
                "model_status": (
                    "Entrenamiento deshabilitado en HTTP. "
                    "La interfaz valida datos, baselines y separación temporal."
                ),
            }
        )

        logger.info(
            "Research UI year=%d month=%d session=%s rows=%d elapsed_ms=%.1f",
            year,
            month,
            session.code,
            dataset.data.height,
            context["elapsed_ms"],
        )

    except Exception as exc:
        logger.exception(
            "Fallo Research UI year=%d month=%d session=%s",
            year,
            month,
            session_code,
        )
        context.update(
            {
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": (perf_counter() - started) * 1000.0,
            }
        )

    return templates.TemplateResponse(
        request=request,
        name="research_home.html",
        context=context,
    )
