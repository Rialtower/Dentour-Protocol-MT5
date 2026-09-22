"""War Room mensual de Dentour Protocol MT5.

Estado funcional documentado en este archivo:
- Valida que el periodo solicitado sea un mes calendario cerrado.
- Convierte las fronteras del calendario COT a UTC.
- Localiza las particiones M1 creadas por ingest.py.
- Consulta archivos Parquet directamente mediante DuckDB.
- Convierte timestamps a America/Bogota para calendario y presentación.
- Calcula cobertura básica por día laborable de calendario.
- Renderiza una interfaz HTML mínima.
- No escribe resultados ni mantiene estado analítico entre solicitudes.

Este módulo corresponde a la primera capa de War Room. Los indicadores
financieros mensuales deben construirse sobre estos contratos y evitar cargar
ticks mensuales completos en memoria.
"""

# Pospone la resolución de anotaciones para facilitar tipos modernos.
from __future__ import annotations

# Escapa mensajes antes de insertarlos dentro del HTML generado.
import html
# Registra métricas y tracebacks de errores operativos.
import logging
# Lee variables de entorno para rutas y símbolo.
import os
# Proporciona nombres de meses para etiquetas legibles.
from calendar import month_name
# Reduce código repetitivo en contratos inmutables.
from dataclasses import dataclass
# Tipos de fecha, instantes, diferencias temporales y UTC.
from datetime import date, datetime, timedelta, timezone
# Construcción segura de rutas.
from pathlib import Path
# Medición de duración con reloj monotónico de alta resolución.
from time import perf_counter
# Declara constantes que no deberían reasignarse.
from typing import Final
# Maneja zonas horarias IANA.
from zoneinfo import ZoneInfo

# DuckDB consulta Parquet directamente mediante SQL analítico.
import duckdb
# Polars recibe resultados columnares y calcula cobertura.
import polars as pl
# APIRouter permite integrar War Room sin crear otra aplicación FastAPI.
from fastapi import APIRouter, Query
# HTMLResponse devuelve la interfaz directamente al navegador.
from fastapi.responses import HTMLResponse


# Logger específico para identificar eventos originados en War Room.
logger = logging.getLogger("warroom")

# Raíz del Data Lake. Puede sobrescribirse sin modificar código.
DATA_LAKE_DIR: Final[Path] = Path(
    os.getenv("DATA_LAKE_DIR", "./data_lake")
)

# Archivo DuckDB local. En esta fase se usa como motor de conexión aunque las
# consultas lean directamente los Parquet.
DB_PATH: Final[str] = os.getenv(
    "DB_PATH",
    "./local_analytics.duckdb",
)

# Símbolo documentado por el módulo. La fase actual no lo usa en el SQL porque
# las particiones ya corresponden al instrumento ingerido.
SYMBOL: Final[str] = os.getenv("MT5_SYMBOL", "XAUUSDm")

# Zona operativa de Colombia y objeto reutilizable.
TZ_COT_NAME: Final[str] = "America/Bogota"
TZ_COT: Final[ZoneInfo] = ZoneInfo(TZ_COT_NAME)

# UTC estándar utilizado para parametrizar las consultas.
TZ_UTC: Final[timezone] = timezone.utc

# Todas las rutas de este módulo quedan bajo /war-room.
router = APIRouter(
    prefix="/war-room",
    tags=["War Room"],
)


@dataclass(frozen=True, slots=True)
class PeriodoMensual:
    """Mes calendario cerrado expresado simultáneamente en COT y UTC.

    Las fronteras COT definen el significado operativo del mes. Las fronteras
    UTC se utilizan para consultar timestamps almacenados en Parquet.
    """

    year: int
    month: int
    inicio_cot: datetime
    fin_cot: datetime
    inicio_utc: datetime
    fin_utc: datetime

    @property
    def etiqueta(self) -> str:
        """Devuelve una etiqueta como ``August 2026``.

        ``calendar.month_name`` utiliza los nombres configurados por Python,
        normalmente en inglés salvo configuración regional adicional.
        """

        return f"{month_name[self.month]} {self.year}"


@dataclass(frozen=True, slots=True)
class CoberturaMensual:
    """Resumen de disponibilidad de barras M1 por fecha COT.

    La cobertura compara días con datos contra días de lunes a viernes. No usa
    todavía un calendario oficial de festivos o cierres extraordinarios.
    """

    dias_con_datos: int
    dias_laborables_calendario: int
    barras: int
    primer_timestamp: datetime | None
    ultimo_timestamp: datetime | None

    @property
    def porcentaje(self) -> float:
        """Calcula cobertura porcentual evitando división por cero."""

        if self.dias_laborables_calendario == 0:
            return 0.0

        return (
            100.0
            * self.dias_con_datos
            / self.dias_laborables_calendario
        )


def crear_periodo_mensual(
    year: int,
    month: int,
) -> PeriodoMensual:
    """Valida y construye un mes completamente cerrado.

    El mes se define primero en America/Bogota. Solo después se convierte a UTC,
    evitando interpretar agosto según la fecha UTC literal.
    """

    if not 1 <= month <= 12:
        raise ValueError(
            "El mes debe estar entre 1 y 12."
        )

    if year < 1970 or year > 9998:
        raise ValueError(
            "El año debe estar entre 1970 y 9998."
        )

    # Inicio incluido del mes solicitado.
    inicio_cot = datetime(
        year,
        month,
        1,
        tzinfo=TZ_COT,
    )

    # Fin exclusivo. Diciembre requiere avanzar al año siguiente.
    fin_cot = (
        datetime(
            year + 1,
            1,
            1,
            tzinfo=TZ_COT,
        )
        if month == 12
        else datetime(
            year,
            month + 1,
            1,
            tzinfo=TZ_COT,
        )
    )

    # Se calcula el inicio del mes actual para rechazar meses incompletos.
    ahora_cot = datetime.now(TZ_COT)
    inicio_mes_actual = datetime(
        ahora_cot.year,
        ahora_cot.month,
        1,
        tzinfo=TZ_COT,
    )

    # Un mes es válido únicamente cuando su fin exclusivo no supera el inicio
    # del mes actual. Esto permite el último mes cerrado y rechaza el actual.
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


def _fechas_cot_a_escanear(
    periodo: PeriodoMensual,
) -> tuple[date, ...]:
    """Enumera cada fecha COT incluida en el mes.

    ingest.py crea las carpetas Hive usando la fecha COT solicitada, aunque los
    timestamps dentro del archivo estén almacenados en UTC. Por esa razón no se
    debe descubrir particiones basándose en la fecha UTC.
    """

    cantidad = (
        periodo.fin_cot.date()
        - periodo.inicio_cot.date()
    ).days

    return tuple(
        periodo.inicio_cot.date()
        + timedelta(days=offset)
        for offset in range(cantidad)
    )


def localizar_parquet_m1(
    periodo: PeriodoMensual,
) -> tuple[Path, ...]:
    """Localiza Parquet M1 en las particiones Hive del mes.

    Las carpetas inexistentes no producen error inmediato; simplemente no
    aportan archivos. El resultado final puede estar vacío y será tratado por
    ``consultar_m1_mensual``.
    """

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
            archivos.extend(
                sorted(particion.glob("*.parquet"))
            )

    # dict conserva el orden de inserción y elimina rutas repetidas.
    return tuple(dict.fromkeys(archivos))


def conexion() -> duckdb.DuckDBPyConnection:
    """Abre DuckDB y aplica límites operativos del proyecto.

    Quien llama es responsable de cerrar la conexión, preferiblemente dentro de
    ``finally``.
    """

    con = duckdb.connect(DB_PATH)

    # Cuatro hilos controlan uso de CPU durante la consulta mensual.
    con.execute("PRAGMA threads=4")

    # El límite restringe el máximo permitido, no reserva 8 GB inmediatamente.
    con.execute("PRAGMA memory_limit='8GB'")

    # DuckDB puede optimizar sin conservar el orden físico de lectura. El SQL
    # final ordena explícitamente por timestamp.
    con.execute("PRAGMA preserve_insertion_order=false")

    return con


def consultar_m1_mensual(
    con: duckdb.DuckDBPyConnection,
    periodo: PeriodoMensual,
    archivos: tuple[Path, ...],
) -> pl.DataFrame:
    """Consulta M1 del mes y devuelve timestamps localizados en COT.

    La consulta selecciona columnas explícitas, filtra mediante parámetros UTC y
    descarta sábados y domingos después de convertir cada instante a COT.
    """

    if not archivos:
        # Un DataFrame vacío con esquema estable permite que cobertura y render
        # continúen sin errores de columnas ausentes.
        return pl.DataFrame(
            schema={
                "timestamp": pl.Datetime(
                    "us",
                    time_zone=TZ_COT_NAME,
                ),
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
                "spread": pl.Int32,
                "real_volume": pl.Int64,
            }
        )

    # DuckDB recibe rutas absolutas para evitar dependencia del cwd.
    rutas = [
        str(path.resolve())
        for path in archivos
    ]

    # No se colocan comentarios Python dentro del SQL. Los parámetros ? evitan
    # concatenar valores y mantienen límites temporales tipados.
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
        [
            rutas,
            periodo.inicio_utc,
            periodo.fin_utc,
        ],
    ).pl()


def calcular_cobertura(
    barras_m1: pl.DataFrame,
    periodo: PeriodoMensual,
) -> CoberturaMensual:
    """Resume días observados, barras y límites temporales.

    Los días laborables son lunes a viernes. Festivos y cierres particulares del
    mercado todavía no se descuentan, por lo que el porcentaje es una cobertura
    de calendario, no una auditoría bursátil oficial.
    """

    dias_laborables = sum(
        1
        for offset in range(
            (
                periodo.fin_cot.date()
                - periodo.inicio_cot.date()
            ).days
        )
        if (
            periodo.inicio_cot.date()
            + timedelta(days=offset)
        ).weekday() < 5
    )

    if barras_m1.is_empty():
        return CoberturaMensual(
            dias_con_datos=0,
            dias_laborables_calendario=dias_laborables,
            barras=0,
            primer_timestamp=None,
            ultimo_timestamp=None,
        )

    # Polars calcula todos los agregados en una única selección.
    resumen = barras_m1.select(
        pl.col("timestamp")
        .dt.date()
        .n_unique()
        .alias("dias"),
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


def _selector_periodo(
    year: int,
    month: int,
) -> str:
    """Genera el formulario HTML para seleccionar año y mes."""

    opciones_mes = "".join(
        (
            f'<option value="{candidate}" '
            f'{"selected" if candidate == month else ""}>'
            f'{candidate:02d}'
            f'</option>'
        )
        for candidate in range(1, 13)
    )

    return f"""
    <form method="get" action="/war-room/" class="selector">
    <label>
        Año
        <input type="number" name="year" value="{year}" min="1970" max="9998" required>
    </label>
    <label>
        Mes
        <select name="month">{opciones_mes}</select>
    </label>
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
    """Renderiza el estado mensual sin persistir resultados.

    La interfaz está deliberadamente contenida en esta fase. A medida que War
    Room crezca, conviene migrar HTML y CSS a plantillas y archivos estáticos.
    """

    # El mensaje se escapa para impedir que una excepción inyecte HTML.
    aviso = (
        f'<section class="error">'
        f'{html.escape(mensaje)}'
        f'</section>'
        if mensaje
        else ""
    )

    resumen = ""

    if periodo is not None and cobertura is not None:
        primero = (
            cobertura.primer_timestamp.isoformat()
            if cobertura.primer_timestamp
            else "Sin datos"
        )
        ultimo = (
            cobertura.ultimo_timestamp.isoformat()
            if cobertura.ultimo_timestamp
            else "Sin datos"
        )

        # duracion_ms llega como float en ejecuciones exitosas.
        consulta_ms = 0.0 if duracion_ms is None else duracion_ms

        resumen = f"""
        <section class="grid">
    <article><span>Periodo</span><strong>{html.escape(periodo.etiqueta)}</strong></article>
    <article><span>Archivos M1</span><strong>{archivos}</strong></article>
    <article><span>Barras M1</span><strong>{cobertura.barras:,}</strong></article>
    <article><span>Días con datos</span><strong>{cobertura.dias_con_datos}/{cobertura.dias_laborables_calendario}</strong></article>
    <article><span>Cobertura calendario</span><strong>{cobertura.porcentaje:.1f}%</strong></article>
    <article><span>Consulta</span><strong>{consulta_ms:.1f} ms</strong></article>
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

    return HTMLResponse(
        f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>War Room | Dentour Protocol MT5</title>
<link rel="icon" type="image/x-icon" href="/static/favicon.ico?v=2">
<style>
:root {{
    --bg: #09090b;
    --panel: #18181b;
    --border: #27272a;
    --text: #e4e4e7;
    --text-dim: #a1a1aa;
    --text-faint: #71717a;
}}

* {{ box-sizing: border-box; }}

body {{ background: var(--bg); color: var(--text); font-family: system-ui, -apple-system, sans-serif; margin: 24px; line-height: 1.5; }}

a, button {{
    color: var(--text);
    background: #27272a;
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 9px 12px;
    text-decoration: none;
    cursor: pointer;
    font-family: inherit;
}}

a:hover, button:hover {{ background: #3f3f46; border-color: #52525b; }}

.selector {{
    display: flex;
    gap: 10px;
    align-items: end;
    flex-wrap: wrap;
    background: rgba(23, 37, 84, 0.40);
    border: 1px solid rgba(59, 130, 246, 0.30);
    padding: 16px;
    border-radius: 8px;
}}

label {{ display: grid; gap: 5px; font-size: 13px; color: var(--text-dim); }}

input, select {{
    background: #000000;
    color: var(--text);
    border: 1px solid var(--border);
    padding: 9px;
    border-radius: 5px;
    font-family: inherit;
}}

.grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 12px;
    margin-top: 18px;
    background: rgba(6, 78, 59, 0.35);
    border: 1px solid rgba(16, 185, 129, 0.30);
    border-radius: 8px;
    padding: 14px;
}}

article, .details, .error {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px;
}}

article span {{ display: block; color: var(--text-faint); margin-bottom: 8px; }}
article strong {{ font-size: 1.25rem; color: #3b82f6; }}

.details {{ margin-top: 14px; }}
.details p {{ margin: 7px 0; }}

.error {{ margin-top: 14px; border-color: #b91c1c; color: #fca5a5; }}

.topbar {{
    position: sticky;
    top: 0;
    z-index: 100;
    margin: -24px -24px 20px -24px;
    padding: 16px 24px;
    background: var(--bg);
    border-bottom: 1px solid var(--border);
}}

.topbar h2 {{
    font-weight: 600;
    letter-spacing: -.01em;
    margin: 0;
}}
.module-link {{
    display: inline-flex;
    align-items: center;
    padding: 0 13px;
    min-height: 32px;
    color: var(--text);
    text-decoration: none;
    background: #27272a;
    border: 1px solid var(--border);
    border-radius: 5px;
}}
.module-link:hover {{
    color: #fafafa;
    background: #3f3f46;
    border-color: #52525b;
    box-shadow: 0 0 0 1px rgba(161, 161, 170, 0.08);
}}
</style>
</head>
<body>
<div class="topbar">
    <h2>Dentour Protocol MT5 [Beta version v1.0]</h2>
    <a href="/" class="module-link">← Dashboard</a>
</div>
{_selector_periodo(year, month)}
{aviso}
{resumen}
</body>
</html>"""
    )


@router.get(
    "/",
    response_class=HTMLResponse,
)
def war_room_home(
    year: int | None = Query(
        default=None,
        ge=1970,
        le=9998,
    ),
    month: int | None = Query(
        default=None,
        ge=1,
        le=12,
    ),
) -> HTMLResponse:
    """Carga cobertura M1 de un mes cerrado sin persistir resultados."""

    hoy_cot = datetime.now(TZ_COT).date()

    if year is None or month is None:
        # La primera visita selecciona automáticamente el último mes cerrado.
        primero_actual = date(
            hoy_cot.year,
            hoy_cot.month,
            1,
        )
        ultimo_cerrado = primero_actual - timedelta(days=1)
        year = ultimo_cerrado.year
        month = ultimo_cerrado.month

    try:
        # Valida el periodo antes de escanear archivos o abrir DuckDB.
        periodo = crear_periodo_mensual(year, month)

        inicio_medicion = perf_counter()
        archivos = localizar_parquet_m1(periodo)

        # La conexión se cierra incluso si DuckDB lanza una excepción.
        con = conexion()
        try:
            barras = consultar_m1_mensual(
                con,
                periodo,
                archivos,
            )
        finally:
            con.close()

        cobertura = calcular_cobertura(
            barras,
            periodo,
        )
        duracion_ms = (
            perf_counter() - inicio_medicion
        ) * 1000.0

        logger.info(
            (
                "War Room mes=%04d-%02d archivos=%d "
                "barras=%d dias=%d duracion_ms=%.1f"
            ),
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
        # Los errores de validación se presentan sin traceback al usuario.
        return render_war_room(
            year,
            month,
            mensaje=str(exc),
        )

    except Exception as exc:
        # Los errores técnicos se registran con traceback completo en logs.
        logger.exception(
            "Fallo al cargar War Room para %04d-%02d",
            year,
            month,
        )
        return render_war_room(
            year,
            month,
            mensaje=f"Error técnico: {exc}",
        )
