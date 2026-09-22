"""War Room mensual de Dentour Protocol MT5.

Incremento 1:
- Valida que el periodo sea un mes calendario cerrado.
- Convierte las fronteras COT a UTC.
- Localiza las particiones M1 del mes según la fecha COT usada por ingest.py.
- Consulta barras M1 directamente desde Parquet mediante DuckDB.
- Calcula cobertura básica por día operativo.
- No escribe datos ni mantiene estado entre solicitudes.
"""

from __future__ import annotations

import html
import logging
import os
from calendar import month_name
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from time import perf_counter
from typing import Final
from zoneinfo import ZoneInfo

import duckdb
import polars as pl
from fastapi import APIRouter, Query
from fastapi.responses import HTMLResponse


logger = logging.getLogger("warroom")

DATA_LAKE_DIR: Final[Path] = Path(os.getenv("DATA_LAKE_DIR", "./data_lake"))
DB_PATH: Final[str] = os.getenv("DB_PATH", "./local_analytics.duckdb")
SYMBOL: Final[str] = os.getenv("MT5_SYMBOL", "XAUUSDm")
TZ_COT_NAME: Final[str] = "America/Bogota"
TZ_COT: Final[ZoneInfo] = ZoneInfo(TZ_COT_NAME)
TZ_UTC: Final[timezone] = timezone.utc

router = APIRouter(prefix="/war-room", tags=["War Room"])


@dataclass(frozen=True, slots=True)
class PeriodoMensual:
    """Mes calendario cerrado expresado en COT y UTC."""

    year: int
    month: int
    inicio_cot: datetime
    fin_cot: datetime
    inicio_utc: datetime
    fin_utc: datetime

    @property
    def etiqueta(self) -> str:
        return f"{month_name[self.month]} {self.year}"


@dataclass(frozen=True, slots=True)
class CoberturaMensual:
    """Resumen de disponibilidad de barras M1 por fecha COT."""

    dias_con_datos: int
    dias_laborables_calendario: int
    barras: int
    primer_timestamp: datetime | None
    ultimo_timestamp: datetime | None

    @property
    def porcentaje(self) -> float:
        if self.dias_laborables_calendario == 0:
            return 0.0
        return 100.0 * self.dias_con_datos / self.dias_laborables_calendario


def crear_periodo_mensual(year: int, month: int) -> PeriodoMensual:
    """Valida y construye un mes cerrado usando COT como calendario."""

    if not 1 <= month <= 12:
        raise ValueError("El mes debe estar entre 1 y 12.")
    if year < 1970 or year > 9998:
        raise ValueError("El año debe estar entre 1970 y 9998.")

    inicio_cot = datetime(year, month, 1, tzinfo=TZ_COT)
    fin_cot = (
        datetime(year + 1, 1, 1, tzinfo=TZ_COT)
        if month == 12
        else datetime(year, month + 1, 1, tzinfo=TZ_COT)
    )

    ahora_cot = datetime.now(TZ_COT)
    inicio_mes_actual = datetime(
        ahora_cot.year, ahora_cot.month, 1, tzinfo=TZ_COT
    )
    if fin_cot > inicio_mes_actual:
        raise ValueError(
            "War Room solo permite meses calendario completamente finalizados."
        )

    return PeriodoMensual(
        year=year,
        month=month,
        inicio_cot=inicio_cot,
        fin_cot=fin_cot,
        inicio_utc=inicio_cot.astimezone(TZ_UTC),
        fin_utc=fin_cot.astimezone(TZ_UTC),
    )


def _fechas_cot_a_escanear(periodo: PeriodoMensual) -> tuple[date, ...]:
    """Devuelve cada fecha COT incluida en el mes calendario seleccionado.

    ingest.py particiona físicamente con la fecha COT enviada al pipeline,
    aunque los timestamps almacenados dentro del Parquet estén en UTC.
    """

    cantidad = (periodo.fin_cot.date() - periodo.inicio_cot.date()).days
    return tuple(
        periodo.inicio_cot.date() + timedelta(days=i)
        for i in range(cantidad)
    )


def localizar_parquet_m1(periodo: PeriodoMensual) -> tuple[Path, ...]:
    """Localiza archivos M1 en las particiones Hive creadas por ingest.py."""

    archivos: list[Path] = []
    raiz = DATA_LAKE_DIR / "m1"
    for dia_cot in _fechas_cot_a_escanear(periodo):
        particion = (
            raiz
            / f"year={dia_cot:%Y}"
            / f"month={dia_cot:%m}"
            / f"day={dia_cot:%d}"
        )
        if particion.is_dir():
            archivos.extend(sorted(particion.glob("*.parquet")))
    return tuple(dict.fromkeys(archivos))


def conexion() -> duckdb.DuckDBPyConnection:
    """Abre DuckDB con los límites definidos por el proyecto."""

    con = duckdb.connect(DB_PATH)
    con.execute("PRAGMA threads=4")
    con.execute("PRAGMA memory_limit='8GB'")
    con.execute("PRAGMA preserve_insertion_order=false")
    return con


def consultar_m1_mensual(
    con: duckdb.DuckDBPyConnection,
    periodo: PeriodoMensual,
    archivos: tuple[Path, ...],
) -> pl.DataFrame:
    """Consulta M1 del mes cerrado y devuelve timestamps localizados en COT.

    El filtro principal usa límites UTC parametrizados. El día de semana se
    calcula después de convertir el instante a America/Bogota. DuckDB usa
    isodow: lunes=1, ..., sábado=6, domingo=7.
    """

    if not archivos:
        return pl.DataFrame(
            schema={
                "timestamp": pl.Datetime("us", time_zone=TZ_COT_NAME),
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
                "spread": pl.Int32,
                "real_volume": pl.Int64,
            }
        )

    rutas = [str(r.resolve()) for r in archivos]
    consulta = """
        WITH base AS (
            SELECT
                timezone('America/Bogota', timestamp) AS timestamp_cot,
                open,
                high,
                low,
                close,
                volume,
                spread,
                real_volume
            FROM read_parquet(?, union_by_name=true)
            WHERE timestamp >= ?
              AND timestamp < ?
        )
        SELECT
            timestamp_cot AS timestamp,
            open,
            high,
            low,
            close,
            volume,
            spread,
            real_volume
        FROM base
        WHERE extract('isodow' FROM timestamp_cot) BETWEEN 1 AND 5
        ORDER BY timestamp_cot
    """
    return con.execute(
        consulta,
        [rutas, periodo.inicio_utc, periodo.fin_utc],
    ).pl()


def calcular_cobertura(
    barras_m1: pl.DataFrame,
    periodo: PeriodoMensual,
) -> CoberturaMensual:
    """Calcula cobertura observada sin asumir calendario de festivos."""

    dias_laborables = sum(
        1
        for offset in range((periodo.fin_cot.date() - periodo.inicio_cot.date()).days)
        if (periodo.inicio_cot.date() + timedelta(days=offset)).weekday() < 5
    )

    if barras_m1.is_empty():
        return CoberturaMensual(0, dias_laborables, 0, None, None)

    resumen = barras_m1.select(
        pl.col("timestamp").dt.date().n_unique().alias("dias"),
        pl.len().alias("barras"),
        pl.col("timestamp").min().alias("primero"),
        pl.col("timestamp").max().alias("ultimo"),
    ).row(0, named=True)

    return CoberturaMensual(
        dias_con_datos=int(resumen["dias"]),
        dias_laborables_calendario=dias_laborables,
        barras=int(resumen["barras"]),
        primer_timestamp=resumen["primero"],
        ultimo_timestamp=resumen["ultimo"],
    )


def _selector_periodo(year: int, month: int) -> str:
    opciones_mes = "".join(
        f'<option value="{m}" {"selected" if m == month else ""}>{m:02d}</option>'
        for m in range(1, 13)
    )
    return f"""
    <form method="get" action="/war-room/" class="selector">
        <label>Año<input type="number" name="year" value="{year}" min="1970" max="9998" required></label>
        <label>Mes<select name="month">{opciones_mes}</select></label>
        <button type="submit">Cargar mes</button>
    </form>
    """


def render_war_room(
    year: int,
    month: int,
    mensaje: str = "",
    periodo: PeriodoMensual | None = None,
    cobertura: CoberturaMensual | None = None,
    archivos: int = 0,
    duracion_ms: float | None = None,
) -> HTMLResponse:
    """Render mínimo del backend mensual, todavía sin indicadores financieros."""

    aviso = (
        f'<section class="error">{html.escape(mensaje)}</section>' if mensaje else ""
    )
    resumen = ""
    if periodo is not None and cobertura is not None:
        primero = cobertura.primer_timestamp.isoformat() if cobertura.primer_timestamp else "Sin datos"
        ultimo = cobertura.ultimo_timestamp.isoformat() if cobertura.ultimo_timestamp else "Sin datos"
        resumen = f"""
        <section class="grid">
            <article><span>Periodo</span><strong>{html.escape(periodo.etiqueta)}</strong></article>
            <article><span>Archivos M1</span><strong>{archivos}</strong></article>
            <article><span>Barras M1</span><strong>{cobertura.barras:,}</strong></article>
            <article><span>Días con datos</span><strong>{cobertura.dias_con_datos}/{cobertura.dias_laborables_calendario}</strong></article>
            <article><span>Cobertura calendario</span><strong>{cobertura.porcentaje:.1f}%</strong></article>
            <article><span>Consulta</span><strong>{duracion_ms:.1f} ms</strong></article>
        </section>
        <section class="details">
            <p><b>Inicio COT:</b> {periodo.inicio_cot.isoformat()}</p>
            <p><b>Fin COT exclusivo:</b> {periodo.fin_cot.isoformat()}</p>
            <p><b>Inicio UTC:</b> {periodo.inicio_utc.isoformat()}</p>
            <p><b>Fin UTC exclusivo:</b> {periodo.fin_utc.isoformat()}</p>
            <p><b>Primera barra:</b> {html.escape(primero)}</p>
            <p><b>Última barra:</b> {html.escape(ultimo)}</p>
        </section>
        """

    return HTMLResponse(f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>War Room | Dentour Protocol MT5</title>
<link rel="icon" type="image/x-icon" href="/static/favicon.ico?v=2">
<style>
body{{background:#0d1117;color:#c9d1d9;font-family:monospace;margin:24px}}
header{{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap}}
a,button{{color:#c9d1d9;background:#21262d;border:1px solid #30363d;border-radius:5px;padding:9px 12px;text-decoration:none;cursor:pointer}}
.selector{{display:flex;gap:10px;align-items:end;flex-wrap:wrap;background:#161b22;padding:16px;border:1px solid #30363d;border-radius:8px}}
label{{display:grid;gap:5px}} input,select{{background:#21262d;color:#c9d1d9;border:1px solid #30363d;padding:9px;border-radius:5px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin-top:18px}}
article,.details,.error{{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}}
article span{{display:block;color:#8b949e;margin-bottom:8px}} article strong{{font-size:1.25rem;color:#58a6ff}}
.details{{margin-top:14px}} .details p{{margin:7px 0}} .error{{margin-top:14px;border-color:#f85149;color:#ffb3ad}}
</style>
</head>
<body>
<header><div><h2>Dentour Protocol MT5 | War Room</h2><p>Motor mensual on-the-fly · Fase 1: periodo, particiones y cobertura M1</p></div><a href="/">Volver al análisis diario</a></header>
{_selector_periodo(year, month)}
{aviso}
{resumen}
</body>
</html>""")


@router.get("/", response_class=HTMLResponse)
def war_room_home(
    year: int | None = Query(default=None, ge=1970, le=9998),
    month: int | None = Query(default=None, ge=1, le=12),
) -> HTMLResponse:
    """Carga cobertura M1 de un mes cerrado sin persistir resultados."""

    hoy_cot = datetime.now(TZ_COT).date()
    if year is None or month is None:
        # Selección inicial: último mes calendario cerrado.
        primero_actual = date(hoy_cot.year, hoy_cot.month, 1)
        ultimo_cerrado = primero_actual - timedelta(days=1)
        year, month = ultimo_cerrado.year, ultimo_cerrado.month

    try:
        periodo = crear_periodo_mensual(year, month)
        inicio_medicion = perf_counter()
        archivos = localizar_parquet_m1(periodo)
        con = conexion()
        try:
            barras = consultar_m1_mensual(con, periodo, archivos)
        finally:
            con.close()
        cobertura = calcular_cobertura(barras, periodo)
        duracion_ms = (perf_counter() - inicio_medicion) * 1000.0
        logger.info(
            "War Room mes=%04d-%02d archivos=%d barras=%d dias=%d duracion_ms=%.1f",
            year,
            month,
            len(archivos),
            cobertura.barras,
            cobertura.dias_con_datos,
            duracion_ms,
        )
        return render_war_room(
            year=year,
            month=month,
            periodo=periodo,
            cobertura=cobertura,
            archivos=len(archivos),
            duracion_ms=duracion_ms,
        )
    except ValueError as exc:
        return render_war_room(year, month, mensaje=str(exc))
    except Exception as exc:
        logger.exception("Fallo al cargar War Room para %04d-%02d", year, month)
        return render_war_room(year, month, mensaje=f"Error técnico: {exc}")
