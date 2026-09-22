"""Dashboard MT5 version 0.2, edición didáctica.

Este archivo conserva la lógica de app.py y añade comentarios para estudio.
Arquitectura resumida:
1. FastAPI recibe formularios HTTP.
2. DuckDB consulta particiones Parquet.
3. Polars calcula VWAP, CVD y confluencia multitemporal.
4. Pandas prepara tablas pequeñas para HTML.
5. Plotly genera el gráfico interactivo.
6. ingest.py es la frontera con MetaTrader 5; app.py no llama directamente a la API MetaTrader5.

Nota: los comentarios explican tanto la intención como supuestos y riesgos.
"""

# seccion de imports liberias de mt5, duckBD,pandas,polars,Fastapi y rutas -------------
# Pospone la evaluación de las anotaciones de tipo. Esto permite usar tipos modernos y referencias adelantadas sin evaluarlas inmediatamente.
from __future__ import annotations

# Utilidades de la biblioteca estándar para escapar texto antes de insertarlo en HTML y reducir riesgos de inyección.
import html
# Sistema estándar de registros. Se usa para guardar trazas completas cuando falla la ingesta o el análisis.
import logging
# Permite leer variables de entorno, usadas aquí para configurar rutas sin modificar el código.
import os
# Tipos temporales: date representa un día, datetime un instante con fecha/hora y time una hora del día.
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
# Path construye y valida rutas de archivos de forma portable y más segura que concatenar cadenas.
from pathlib import Path
# Final comunica al analizador estático que una constante no debería reasignarse durante la ejecución.
from typing import Final
# Convierte un diccionario en parámetros seguros de una URL, por ejemplo fecha=...&tf=m15.
from urllib.parse import urlencode
# ZoneInfo usa la base IANA de zonas horarias y aplica automáticamente cambios de horario de verano.
from zoneinfo import ZoneInfo

# DuckDB ejecuta SQL analítico directamente sobre archivos Parquet sin cargarlos primero en una base de datos tradicional.
import duckdb
# Pandas se usa al final del flujo para producir tablas HTML y algunas estadísticas sencillas.
import pandas as pd
# Polars realiza las transformaciones columnares principales con expresiones eficientes y tipadas.
import polars as pl
# Plotly Graph Objects permite construir velas, líneas y mapas de calor interactivos.
import plotly.graph_objects as go
# FastAPI crea la aplicación web; Form declara valores recibidos desde formularios HTML.
from fastapi import FastAPI, Form
# Importación duplicada: no rompe la aplicación, pero es redundante y puede eliminarse en una refactorización.
from fastapi import FastAPI
# StaticFiles publica archivos locales como favicon, CSS o JavaScript bajo una ruta HTTP.
from fastapi.staticfiles import StaticFiles
# HTMLResponse devuelve HTML; RedirectResponse ordena al navegador visitar otra URL.
from fastapi.responses import HTMLResponse, RedirectResponse
# Crea una figura Plotly con varios paneles que comparten el eje temporal.
from plotly.subplots import make_subplots
# Integra app.py con ingest.py. La conexión directa a MetaTrader 5 ocurre en ingest.py, no en este archivo.
from ingest import ejecutar_pipeline, rango_dia_cot_en_utc

# uso de router para redirigir a la ruta del war room, donde se realizan analisis mensuales y el modulo de investigacion.
from warroom import router as warroom_router
from research.api import router as research_router

#---------------------------------------------------------------------------------------

# Logger con nombre "app". Su salida efectiva depende de la configuración de logging iniciada por Uvicorn o el proyecto.
logger = logging.getLogger("app")
# Instancia ASGI principal que Uvicorn servirá y sobre la cual se registran las rutas HTTP.
app = FastAPI(
    title="Dentour Dashboard MT5",
    description="Analytics & Data Lake for MetaTrader 5",
    version="0.5.0" 
    )
# Incluye el router de warroom, que contiene rutas adicionales para análisis mensuales y el módulo de investigación.
app.include_router(warroom_router)
app.include_router(research_router)
# Expone el directorio local ./static en la URL /static. El directorio debe existir al arrancar.
app.mount("/static", StaticFiles(directory="static"), name="static")
# Raíz del Data Lake. Puede sobreescribirse con DATA_LAKE_DIR; si no existe, usa ./data_lake relativo al directorio de ejecución.
DATA_LAKE_DIR: Final[Path] = Path(os.getenv("DATA_LAKE_DIR", "./data_lake")) #ruta local en users
# Ruta del archivo DuckDB. Aunque las consultas leen Parquet, el archivo permite persistir estado si luego se crean tablas o vistas.
DB_PATH: Final[str] = os.getenv("DB_PATH", "local_analytics.duckdb")
# Zona operativa de Colombia. No tiene horario de verano y normalmente corresponde a UTC-5.
TZ_COT: Final[ZoneInfo] = ZoneInfo("America/Bogota")
# Zona configurada para el servidor del broker. Europe/Athens alterna EET/EEST según el calendario de horario de verano.
TZ_BROKER: Final[ZoneInfo] = ZoneInfo("Europe/Athens")  # EET/EEST con DST real
# Lista cerrada de temporalidades aceptadas. También define el orden H1, M15 y M1 usado más adelante.
TIMEFRAMES: Final[tuple[str, ...]] = ("h1", "m15", "m1")


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """Ventana horaria operativa expresada en America/Bogota."""

    code: str
    name: str
    start: time
    end: time

    @property
    def is_full_day(self) -> bool:
        return self.code == "full_day"

    @property
    def crosses_midnight(self) -> bool:
        return not self.is_full_day and self.end <= self.start

    @property
    def label(self) -> str:
        if self.is_full_day:
            return "Día completo COT"
        return f"{self.name} ({self.start:%H:%M}-{self.end:%H:%M} COT)"


SESSION_PRESETS: Final[dict[str, SessionWindow]] = {
    "new_york": SessionWindow("new_york", "Nueva York", time(7), time(10)),
    "london": SessionWindow("london", "Londres", time(2), time(5)),
    "asia": SessionWindow("asia", "Asia", time(19), time(23)),
    "full_day": SessionWindow("full_day", "Día completo", time(0), time(0)),
}
DEFAULT_SESSION_CODE: Final[str] = "new_york"


def _parse_hora(valor: str) -> time:
    """Convierte HH:MM en time y rechaza formatos ambiguos."""

    try:
        return time.fromisoformat(valor)
    except (TypeError, ValueError) as exc:
        raise ValueError("La hora debe usar el formato HH:MM.") from exc


def resolver_sesion(
    session_code: str,
    session_start: str,
    session_end: str,
) -> SessionWindow:
    """Resuelve un preset o una ventana personalizada."""

    if session_code == "custom":
        inicio = _parse_hora(session_start)
        fin = _parse_hora(session_end)
        if inicio == fin:
            raise ValueError(
                "En una sesión personalizada la hora inicial y final no pueden ser iguales."
            )
        return SessionWindow("custom", "Personalizada", inicio, fin)

    try:
        return SESSION_PRESETS[session_code]
    except KeyError as exc:
        raise ValueError(f"Sesión desconocida: {session_code}") from exc


# Abre una conexión DuckDB y fija límites de ejecución para las consultas analíticas.
# Retorna la conexión abierta; quien llama es responsable de cerrarla, preferiblemente dentro de `finally`.
def conexion() -> duckdb.DuckDBPyConnection:
    # Abre o crea el archivo DuckDB configurado.
    con = duckdb.connect(DB_PATH)
    # Limita DuckDB a cuatro hilos de trabajo para controlar el uso de CPU.
    con.execute("PRAGMA threads=4")     # no mover excepto que los datos sean mayores a 5 dias
    # Establece un máximo de memoria para DuckDB; no reserva 8 GB de inmediato.
    con.execute("PRAGMA memory_limit='8GB'")    # no mover en caso de archivos pesados
    return con

#validacion de parquet personalizado de mt5 ------------------------------------------------------

# Genera el patrón de archivos de una única partición Hive: tipo/año/mes/día/*.parquet.
# El prefijo `_` expresa que es una función interna del módulo, aunque Python no impide importarla.
def _glob(tipo: str, dia: date) -> str:
    """Construye la ruta exacta de la partición Hive para evitar escaneo histórico."""
    # Compone la ruta con `Path` y la convierte a texto porque DuckDB recibe el patrón como parámetro SQL.
    return str(DATA_LAKE_DIR / tipo / f"year={dia:%Y}" / f"month={dia:%m}" / f"day={dia:%d}" / "*.parquet")



# Comprueba antes de consultar que la carpeta diaria exista y contenga al menos un Parquet.
# Esta validación produce un error comprensible y evita que DuckDB falle con un mensaje menos claro.
def _validar_archivos(tipo: str, dia: date) -> None:
    """Valida únicamente la partición solicitada, en tiempo O(archivos del día)."""
    # Construye la carpeta exacta del día usando convenciones Hive year=, month= y day=.
    particion = DATA_LAKE_DIR / tipo / f"year={dia:%Y}" / f"month={dia:%m}" / f"day={dia:%d}"
    # Falla si la carpeta no existe o si no contiene archivos con extensión .parquet.
    if not particion.is_dir() or not any(particion.glob("*.parquet")):
        raise FileNotFoundError(f"No hay Parquet para {tipo} en {dia.isoformat()}.")

# Verifica que `timestamp` sea un Datetime con zona y convierte su visualización a America/Bogota.
# `convert_time_zone` conserva el instante absoluto; no reemplaza ni reinterpreta la zona original.
def _localizar_cot(df: pl.DataFrame) -> pl.DataFrame:
    """Convierte TIMESTAMPTZ UTC a COT sin reinterpretar el instante absoluto.

    Raises:
        TypeError: Si ``timestamp`` no es un Datetime con zona horaria.
    """
    # Consulta el tipo Polars de la columna sin leer fila por fila.
    dtype = df.schema.get("timestamp")
    # Exige zona horaria explícita para evitar conversiones ambiguas de timestamps ingenuos.
    if not isinstance(dtype, pl.Datetime) or dtype.time_zone is None:
        raise TypeError(f"timestamp debe ser tz-aware; DuckDB entregó {dtype!r}")
    # Cambia la zona de presentación a COT conservando el momento real.
    return df.with_columns(pl.col("timestamp").dt.convert_time_zone("America/Bogota"))

# construccion de dataframes ------------------------------------------------------------------

# Lee barras OHLCV de una temporalidad para el día operativo colombiano solicitado.
# El filtro temporal es semiabierto [inicio, fin): incluye el inicio y excluye el comienzo del día siguiente.
def consultar_barras(con: duckdb.DuckDBPyConnection, tipo: str, dia: date) -> pl.DataFrame:
    # Valida la partición antes de pedir a DuckDB que la abra.
    _validar_archivos(tipo, dia)
    # Convierte los límites del día COT a instantes UTC compatibles con el almacenamiento.
    inicio, fin = rango_dia_cot_en_utc(dia)
    # Ejecuta SQL parametrizado. El patrón y las fechas viajan separados del SQL, evitando concatenación insegura.
    df = con.execute("""
        SELECT timestamp, open, high, low, close, volume
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE timestamp >= ? AND timestamp < ?
        ORDER BY timestamp
    """, [_glob(tipo, dia), inicio, fin]).pl()
    # Convierte el resultado DuckDB a horario colombiano antes de entregarlo a la analítica.
    return _localizar_cot(df)


# Lee ticks bid/ask/last y sus volúmenes desde la partición diaria, los ordena y los presenta en COT.
def consultar_ticks(con: duckdb.DuckDBPyConnection, dia: date) -> pl.DataFrame:
    # Valida la partición antes de pedir a DuckDB que la abra.
    _validar_archivos("ticks", dia)
    # Convierte los límites del día COT a instantes UTC compatibles con el almacenamiento.
    inicio, fin = rango_dia_cot_en_utc(dia)
    # Ejecuta SQL parametrizado. El patrón y las fechas viajan separados del SQL, evitando concatenación insegura.
    df = con.execute("""
        SELECT timestamp, bid, ask, last, volume, volume_real
        FROM read_parquet(?, hive_partitioning=true, union_by_name=true)
        WHERE timestamp >= ? AND timestamp < ?
        ORDER BY timestamp
    """, [_glob("ticks", dia), inicio, fin]).pl()
    # Convierte el resultado DuckDB a horario colombiano antes de entregarlo a la analítica.
    return _localizar_cot(df)


# Calcula VWAP acumulado y desviación estándar ponderada usando el precio típico (high + low + close) / 3.
# Las columnas auxiliares empiezan con `_`; permanecen en el DataFrame resultante y podrían eliminarse si se desea ahorrar memoria.
def calcular_vwap(df: pl.DataFrame) -> pl.DataFrame:
    # Detiene el cálculo porque una serie vacía no puede producir un VWAP válido.
    if df.is_empty():
        raise ValueError("La temporalidad base no contiene barras.")
    # Define una expresión Polars perezosa para el precio típico de cada barra.
    tp = (pl.col("high") + pl.col("low") + pl.col("close")) / 3.0
    # Crea productos precio-volumen y precio²-volumen necesarios para media y varianza ponderadas.
    return (df.with_columns(_pv=tp * pl.col("volume"), _p2v=tp.pow(2) * pl.col("volume"))
            # Acumula volumen y los productos ponderados desde la primera barra del día.
            .with_columns(_cv=pl.col("volume").cum_sum(), _cpv=pl.col("_pv").cum_sum(),
                          _cp2v=pl.col("_p2v").cum_sum())
            # Divide precio-volumen acumulado entre volumen acumulado.
            .with_columns(vwap=pl.col("_cpv") / pl.col("_cv"))
            # Obtiene sigma ponderada; clip(0) elimina pequeños negativos por error de coma flotante antes de sqrt.
            .with_columns(sigma=((pl.col("_cp2v") / pl.col("_cv") - pl.col("vwap").pow(2))
                                 .clip(0)).sqrt()))


# Estima si cada tick pertenece al lado comprador (+1) o vendedor (-1), asigna un peso y acumula el CVD.
# Es una clasificación heurística: prioriza ejecuciones `last` contra ask/bid y usa tick rule cuando no puede clasificarlas así.
def calcular_ticks_firmados(ticks: pl.DataFrame) -> pl.DataFrame:
    if ticks.is_empty():
        raise ValueError("No existen ticks para calcular CVD.")
    # Usa `last` cuando existe; si no, aproxima el precio negociado con el punto medio bid-ask.
    precio = pl.when(pl.col("last") > 0).then(pl.col("last")).otherwise((pl.col("bid") + pl.col("ask")) / 2)
    # Ordena cronológicamente porque shift y acumulados dependen del orden.
    return (ticks.sort("timestamp").with_columns(precio=precio)
            # Calcula el signo del cambio de precio y el peso preferido: volumen real, volumen de ticks o 1.
            .with_columns(movimiento=(pl.col("precio") - pl.col("precio").shift(1)).sign(),
                          peso=pl.when(pl.col("volume_real") > 0).then(pl.col("volume_real"))
                          .when(pl.col("volume") > 0).then(pl.col("volume")).otherwise(1.0))
            # Clasifica compra/venta por relación con ask/bid; si no aplica, hereda el signo del movimiento de precio.
            .with_columns(lado=pl.when((pl.col("last") > 0) & (pl.col("last") >= pl.col("ask"))).then(1)
                          .when((pl.col("last") > 0) & (pl.col("last") <= pl.col("bid"))).then(-1)
                          .otherwise(pl.col("movimiento").fill_null(0)))
            # Multiplica dirección por peso para obtener delta firmado.
            .with_columns(delta=pl.col("lado") * pl.col("peso"))
            # Acumula el delta firmado para formar Cumulative Volume Delta.
            .with_columns(cvd=pl.col("delta").cum_sum()))


# Proyecta el CVD irregular de ticks sobre los timestamps regulares de las barras mediante un join as-of hacia atrás.
def alinear_cvd(ticks_firmados: pl.DataFrame, base: pl.DataFrame) -> pl.DataFrame:
    # Conserva la grilla temporal base y la ordena antes del join as-of.
    return (base.select("timestamp").sort("timestamp")
            # Asocia a cada barra el último valor disponible cuyo timestamp no sea posterior.
            .join_asof(ticks_firmados.select("timestamp", "cvd").sort("timestamp"),
                       on="timestamp", strategy="backward")
            # Propaga el último CVD y usa cero antes del primer tick disponible.
            .with_columns(pl.col("cvd").forward_fill().fill_null(0.0)))


# Reduce cada vela a dirección: 1 alcista, -1 bajista y 0 neutral/doji.
def _direccion(df: pl.DataFrame, nombre: str) -> pl.DataFrame:
    # Ordena y selecciona solo timestamp junto con la dirección calculada.
    return df.sort("timestamp").select("timestamp", pl.when(pl.col("close") > pl.col("open")).then(1)
        .when(pl.col("close") < pl.col("open")).then(-1).otherwise(0).alias(nombre))


# Construye una matriz multitemporal usando cada barra M1 como grilla y asociando la última M15/H1 conocida.
def calcular_matriz(h1: pl.DataFrame, m15: pl.DataFrame, m1: pl.DataFrame) -> pl.DataFrame:
    """Usa todo M1 del dia como grilla, sin tail ni compresion arbitraria."""
    # La confluencia requiere las tres temporalidades; no intenta fabricar datos faltantes.
    if any(df.is_empty() for df in (h1, m15, m1)):
        raise ValueError("H1, M15 y M1 deben contener datos.")
    # Une M15 sobre la grilla M1 usando la última vela M15 disponible.
    matriz = _direccion(m1, "M1").join_asof(_direccion(m15, "M15"), on="timestamp", strategy="backward")
    # Agrega H1 y sustituye ausencias iniciales por dirección neutral 0.
    return matriz.join_asof(_direccion(h1, "H1"), on="timestamp", strategy="backward").with_columns(
        pl.col(["H1", "M15", "M1"]).fill_null(0))


# Filtra por la hora local contenida en timestamp. Ambos extremos son inclusivos por usar >= y <=.
def _ventana(df: pl.DataFrame, inicio: time, fin: time) -> pl.DataFrame:
    """Filtra [inicio, fin) y soporta ventanas que cruzan medianoche."""

    hora_local = pl.col("timestamp").dt.time()
    if inicio == fin:
        return df
    if inicio < fin:
        condicion = (hora_local >= inicio) & (hora_local < fin)
    else:
        condicion = (hora_local >= inicio) | (hora_local < fin)
    return df.filter(condicion)


def filtrar_sesion(df: pl.DataFrame, sesion: SessionWindow) -> pl.DataFrame:
    """Aplica el contrato de sesión a un DataFrame con timestamp COT."""

    if df.is_empty() or sesion.is_full_day:
        return df
    return _ventana(df, sesion.start, sesion.end)


def _intervalo_sesion(dia: date, sesion: SessionWindow) -> tuple[datetime, datetime]:
    """Construye límites COT para Plotly, incluyendo cruce de medianoche."""

    inicio = datetime.combine(dia, sesion.start, TZ_COT)
    if sesion.is_full_day:
        return inicio, inicio + timedelta(days=1)
    fin = datetime.combine(dia, sesion.end, TZ_COT)
    if sesion.crosses_midnight:
        fin += timedelta(days=1)
    return inicio, fin


# Agrupa ticks de 07:00 a 10:00 COT por niveles de precio discretizados y clasifica nodos de alto/bajo volumen.
# Devuelve Pandas porque el resultado terminará convertido a una tabla HTML.
def clusters_volumen(ticks: pl.DataFrame, sesion: SessionWindow, paso: float = 0.50) -> pd.DataFrame:
    # Restringe el perfil de volumen a la sesión de interés 07:00-10:00 COT.
    t = filtrar_sesion(ticks, sesion)
    # Devuelve una tabla vacía con columnas estables para que el renderizado no falle.
    if t.is_empty():
        return pd.DataFrame(columns=["Nivel", "Volumen", "Delta neto", "Clasificacion"])
    # Redondea cada precio al múltiplo de `paso`, suma volumen/delta por nivel y ordena por volumen.
    agrupado = (t.with_columns(nivel=(pl.col("precio") / paso).round() * paso)
                .group_by("nivel").agg(pl.col("peso").sum().alias("volumen"),
                                       pl.col("delta").sum().alias("delta_neto"))
                .sort("volumen", descending=True))
    # Convierte el resultado pequeño a Pandas para etiquetado y salida HTML.
    pdf = agrupado.to_pandas()
    # Inicializa todos los niveles como neutrales antes de aplicar reglas HVN y LVN.
    pdf["clasificacion"] = "Neutral"
    # Marca hasta tres niveles con mayor volumen como High Volume Nodes o puntos de interés.
    pdf.loc[pdf.nlargest(min(3, len(pdf)), "volumen").index, "clasificacion"] = "HVN / POI"
    # Excluye los HVN para que un mismo nivel no reciba dos clasificaciones.
    restantes = pdf[pdf["clasificacion"] == "Neutral"]
    # Marca hasta dos niveles restantes con menor volumen como Low Volume Nodes.
    pdf.loc[restantes.nsmallest(min(2, len(restantes)), "volumen").index, "clasificacion"] = "LVN"
    # Normaliza encabezados para mostrarlos directamente al usuario.
    return pdf.rename(columns={"nivel": "Nivel", "volumen": "Volumen",
                               "delta_neto": "Delta neto", "clasificacion": "Clasificacion"})


# Calcula métricas de dos rangos de apertura: extremos, expansión posterior, Z-score de volumen y dispersión respecto a VWAP.
def metricas_opening_range(
    m1: pl.DataFrame,
    base_vwap: pl.DataFrame,
    sesion: SessionWindow,
) -> pd.DataFrame:
    """Calcula OR15 y OR30 relativos al inicio de la sesión seleccionada."""

    if sesion.is_full_day:
        inicio_sesion = time(0)
        fin_sesion = time(0)
    else:
        inicio_sesion = sesion.start
        fin_sesion = sesion.end

    sesion_m1 = filtrar_sesion(m1, sesion)
    if sesion_m1.is_empty():
        return pd.DataFrame(
            columns=["Rango", "Maximo", "Minimo", "Z-Score volumen", "Std precio-VWAP", "Expansion max. puntos"]
        )

    volumenes = sesion_m1["volume"].to_numpy()
    media = float(pd.Series(volumenes).mean())
    std = float(pd.Series(volumenes).std(ddof=0))
    fecha_base = sesion_m1["timestamp"].min().date()
    inicio_dt = datetime.combine(fecha_base, inicio_sesion, TZ_COT)

    filas: list[dict[str, object]] = []
    for minutos in (15, 30):
        fin_or_dt = inicio_dt + timedelta(minutes=minutos)
        or_df = sesion_m1.filter(
            (pl.col("timestamp") >= inicio_dt) & (pl.col("timestamp") < fin_or_dt)
        )
        if or_df.is_empty():
            continue

        alto = float(or_df["high"].max())
        bajo = float(or_df["low"].min())
        posterior = sesion_m1.filter(pl.col("timestamp") >= fin_or_dt)
        expansion = 0.0 if posterior.is_empty() else max(
            float(posterior["high"].max()) - alto,
            bajo - float(posterior["low"].min()),
            0.0,
        )
        z = 0.0 if std == 0 else (float(or_df["volume"].mean()) - media) / std
        v = filtrar_sesion(base_vwap, sesion).filter(
            (pl.col("timestamp") >= inicio_dt) & (pl.col("timestamp") < fin_or_dt)
        )
        valor_desv = None if v.is_empty() else (v["close"] - v["vwap"]).std()
        desv = 0.0 if valor_desv is None else float(valor_desv)
        filas.append(
            {
                "Rango": f"OR{minutos} desde {inicio_sesion:%H:%M}",
                "Maximo": alto,
                "Minimo": bajo,
                "Z-Score volumen": z,
                "Std precio-VWAP": desv,
                "Expansion max. puntos": expansion,
            }
        )
    return pd.DataFrame(filas)


# Busca falsos rompimientos de máximos/mínimos recientes confirmados por delta de ticks opuesto al movimiento.
def detectar_barridos(velas: pl.DataFrame, ticks: pl.DataFrame, sesion: SessionWindow, lookback: int = 5) -> pd.DataFrame:
    """Sweep: rompe extremo previo, cierra dentro y el delta de ticks se opone al rompimiento."""
    # Limita las velas a la sesión y garantiza orden temporal.
    v = filtrar_sesion(velas, sesion).sort("timestamp")
    if v.is_empty():
        return pd.DataFrame(columns=["Timestamp COT", "Tipo", "Precio", "Divergencia"])
    # Agrupa el delta de ticks en cubetas de un minuto para compararlo con cada vela M1.
    delta_barra = (ticks.with_columns(bucket=pl.col("timestamp").dt.truncate("1m"))
                   .group_by("bucket").agg(pl.col("delta").sum().alias("delta_barra")).sort("bucket"))
    # Calcula extremos de las `lookback` velas anteriores, excluyendo la vela actual mediante shift(1).
    v = (v.with_columns(prev_high=pl.col("high").shift(1).rolling_max(lookback),
                        prev_low=pl.col("low").shift(1).rolling_min(lookback))
         # Asocia a cada barra el último valor disponible cuyo timestamp no sea posterior.
         .join_asof(delta_barra, left_on="timestamp", right_on="bucket", strategy="backward")
         .with_columns(pl.col("delta_barra").fill_null(0.0)))
    # Filtra barridos alcistas y bajistas: rompe el extremo, cierra dentro y presenta delta contrario.
    eventos = v.filter(((pl.col("high") > pl.col("prev_high")) & (pl.col("close") < pl.col("prev_high")) & (pl.col("delta_barra") < 0)) |
                       ((pl.col("low") < pl.col("prev_low")) & (pl.col("close") > pl.col("prev_low")) & (pl.col("delta_barra") > 0)))
    if eventos.is_empty():
        return pd.DataFrame(columns=["Timestamp COT", "Tipo", "Precio", "Divergencia"])
    # Selecciona y formatea únicamente las columnas que verá el usuario.
    return (eventos.select(pl.col("timestamp").dt.strftime("%Y-%m-%d %H:%M:%S").alias("Timestamp COT"),
        pl.when(pl.col("high") > pl.col("prev_high")).then(pl.lit("Barrido de maximo"))
          .otherwise(pl.lit("Barrido de minimo")).alias("Tipo"),
        pl.when(pl.col("high") > pl.col("prev_high")).then(pl.col("high"))
          .otherwise(pl.col("low")).alias("Precio"),
        pl.col("delta_barra").abs().alias("Divergencia")).to_pandas())


# Ensambla los tres paneles del dashboard: precio/VWAP, CVD y confluencia direccional H1-M15-M1.
def construir_figura(
    base: pl.DataFrame,
    cvd: pl.DataFrame,
    matriz: pl.DataFrame,
    tf: str,
    dia: date,
    sesion: SessionWindow,
) -> go.Figure:
    # Crea tres filas con alturas relativas y un eje X temporal compartido.
    fig = make_subplots(rows=3, cols=1, shared_xaxes=True, row_heights=[.55, .25, .20],
                        vertical_spacing=.04, subplot_titles=(f"Precio y VWAP {tf.upper()}",
                        "Cumulative Volume Delta", "Confluencia H1 / M15 / M1"))
    # Añade velas OHLC al panel superior.
    fig.add_trace(go.Candlestick(x=base["timestamp"], open=base["open"], high=base["high"],
        low=base["low"], close=base["close"], name=tf.upper()), row=1, col=1)
    # Superpone la línea VWAP en el panel de precio.
    fig.add_trace(go.Scatter(x=base["timestamp"], y=base["vwap"], name="VWAP",
                             line=dict(color="#58a6ff")), row=1, col=1)
    # Dibuja el CVD como área respecto a cero en el segundo panel.
    fig.add_trace(go.Scatter(x=cvd["timestamp"], y=cvd["cvd"], name="CVD", fill="tozeroy",
                             line=dict(color="#d29922")), row=2, col=1)
    # Representa -1, 0 y 1 con rojo, gris y verde para cada temporalidad.
    fig.add_trace(go.Heatmap(x=matriz["timestamp"], y=["H1", "M15", "M1"],
        z=[matriz[x].to_list() for x in ("H1", "M15", "M1")], zmin=-1, zmax=1,
        colorscale=[[0, "#f85149"], [.5, "#21262d"], [1, "#3fb950"]], showscale=False), row=3, col=1)
    # Construye límites zonificados de 07:00 a 10:00 COT para la vista inicial.
    rango = list(_intervalo_sesion(dia, sesion))
    # Formatea horas, textos emergentes y rango visible de todos los ejes X.
    fig.update_xaxes(tickformat="%H:%M", hoverformat="%Y-%m-%d %H:%M:%S", range=rango)
    # Aplica tema oscuro, dimensiones, márgenes y botones para alternar sesión/día completo.
    fig.update_layout(template="plotly_dark", height=900, paper_bgcolor="#0d1117",
        plot_bgcolor="#161b22", margin=dict(l=50, r=20, t=65, b=35), xaxis_rangeslider_visible=False,
        updatemenus=[dict(type="buttons", direction="right", x=.01, y=1.08, showactive=False,
            buttons=[dict(label=sesion.label, method="relayout",
                          args=[{"xaxis.range": rango, "xaxis2.range": rango, "xaxis3.range": rango}]),
                     dict(label="Dia completo", method="relayout",
                          args=[{"xaxis.autorange": True, "xaxis2.autorange": True, "xaxis3.autorange": True}])])])
    # Devuelve el objeto Figure; todavía no se ha convertido a HTML.
    return fig


# Compara las 07:00 COT con la hora del broker en Atenas para la fecha elegida, respetando DST.
def tabla_zonas(dia: date, sesion: SessionWindow) -> str:
    """Contrasta el inicio de la sesión COT con la zona del broker."""

    referencia_cot = datetime.combine(dia, sesion.start, TZ_COT)
    broker = referencia_cot.astimezone(TZ_BROKER)
    diferencia = int(
        (broker.utcoffset().total_seconds() - referencia_cot.utcoffset().total_seconds()) / 3600
    )
    verano = broker.dst() is not None and broker.dst().total_seconds() != 0
    return f"""<div class='tz'><h3>Contraste horario de la sesión seleccionada</h3><table><thead><tr>
<th>Sesión</th><th>Hora servidor MT5 (EET/EEST)</th><th>Hora Colombia (COT)</th><th>Diferencial</th>
</tr></thead><tbody><tr><td>{html.escape(sesion.label)}</td><td>{broker:%Y-%m-%d %H:%M:%S %Z}</td>
<td>{referencia_cot:%Y-%m-%d %H:%M:%S %Z}</td><td>{'Verano' if verano else 'Invierno'}: +{diferencia} horas</td>
</tr></tbody></table></div>"""


# Convierte un DataFrame Pandas en una tarjeta HTML. El título se escapa; el cuerpo proviene de datos calculados internamente.
def _tabla(pdf: pd.DataFrame, titulo: str) -> str:
    # Si no hay filas muestra un mensaje; si existen, redondea y produce una tabla HTML.
    cuerpo = "<p>Sin eventos para los filtros seleccionados.</p>" if pdf.empty else pdf.round(4).to_html(index=False, classes="data")
    # Envuelve título y tabla en una tarjeta visual.
    return f"<section class='card'><h3>{html.escape(titulo)}</h3>{cuerpo}</section>"


# Genera una página HTML completa mediante una f-string y la devuelve como respuesta de FastAPI.
# Los valores controlados por el usuario se escapan antes de insertarse; `grafico` y `tarjetas` contienen HTML generado por la aplicación.
def render(
    fecha: str,
    tf: str,
    mensaje: str = "",
    grafico: str = "",
    tarjetas: str = "",
    session_code: str = DEFAULT_SESSION_CODE,
    session_start: str = "07:00",
    session_end: str = "10:00",
) -> HTMLResponse:
    # Genera las opciones H1/M15/M1 y marca la temporalidad actualmente seleccionada.
    opciones = "".join(f'<option value="{x}" {"selected" if x == tf else ""}>{x.upper()}</option>' for x in TIMEFRAMES)
    # Escapa el mensaje antes de incorporarlo al HTML para impedir que se interprete como etiquetas.
    aviso = f'<div class="msg">{html.escape(mensaje)}</div>' if mensaje else ""
    # Intenta crear el contraste horario solo si la fecha tiene formato ISO válido.
    try:
        sesion = resolver_sesion(session_code, session_start, session_end)
        zona = tabla_zonas(date.fromisoformat(fecha), sesion)
    # Una fecha inválida no rompe el render básico; simplemente omite la tabla horaria.
    except ValueError:
        sesion = SESSION_PRESETS[DEFAULT_SESSION_CODE]
        zona = ""
    # Devuelve un documento HTML completo con estilos embebidos, formularios, gráfico y tarjetas.
    return HTMLResponse(
    f"""<!doctype html>
<html lang="es">
<head>
    <meta charset="utf-8">
    <meta
        name="viewport"
        content="width=device-width, initial-scale=1"
    >

    <title>DPMT5 Dashboard</title>

    <link rel="icon" type="image/x-icon" href="/static/favicon.ico?v=2">

    <style>
        * {{
            box-sizing: border-box;
        }}

        body {{
            background: #0a0a0a;
            color: #ededed;
            font-family: system-ui, -apple-system, 'Segoe UI', sans-serif;
            margin: 24px;
            line-height: 1.5;
        }}

        h2 {{
            font-weight: 600;
            letter-spacing: -.01em;
            margin: 0 0 20px;
        }}

        .control-panel {{
            display: flex;
            flex-direction: column;
            gap: 16px;
            background: #111111;
            padding: 18px;
            border: 1px solid #30363d;
            border-radius: 6px;
        }}

        .panel {{
            background: #0d1117;
            border: 1px solid #21262d;
            border-radius: 6px;
            padding: 14px 16px;
        }}

        .panel-title {{
            margin: 0 0 12px;
            font-size: 11px;
            font-weight: 600;
            letter-spacing: .05em;
            text-transform: uppercase;
            color: #6e7681;
        }}

        .field-row {{
            display: flex;
            gap: 12px;
            align-items: end;
            flex-wrap: wrap;
        }}

        .panel-row {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
            gap: 16px;
        }}

        .nav-links {{
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
        }}

        form {{
            display: flex;
            gap: 10px;
            align-items: end;
            flex-wrap: wrap;
            margin: 0;
        }}

        label {{
            display: grid;
            gap: 6px;
            font-size: 13px;
            color: #a1a1aa;
        }}

        input,
        select {{
            background: #000000;
            color: #ededed;
            border: 1px solid #30363d;
            padding: 9px 12px;
            border-radius: 6px;
            font-family: inherit;
            font-size: 14px;
            transition: border-color .15s ease;
        }}

        input:hover,
        select:hover {{
            border-color: #484f58;
        }}

        input:focus,
        select:focus {{
            outline: none;
            border-color: #58a6ff;
        }}

        button {{
            background: #161b22;
            color: #ededed;
            border: 1px solid #30363d;
            padding: 9px 16px;
            border-radius: 6px;
            font-family: inherit;
            font-size: 14px;
            cursor: pointer;
            transition: background .15s ease, border-color .15s ease;
        }}

        button:hover {{
            background: #1c2128;
            border-color: #484f58;
        }}

        .primary {{
            background: #238636;
            border-color: #2ea043;
        }}

        .primary:hover {{
            background: #2ea043;
            border-color: #3fb950;
        }}

        .msg {{
            margin: 16px 0;
            padding: 12px 14px;
            border: 1px solid #d29922;
            border-radius: 6px;
            background: #111111;
            color: #ededed;
            font-size: 14px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }}

        th,
        td {{
            border: 1px solid #30363d;
            padding: 9px 10px;
            text-align: left;
        }}

        th {{
            color: #a1a1aa;
            font-weight: 600;
            background: #0a0a0a;
        }}

        td {{
            color: #ededed;
        }}

        .tz,
        .card {{
            margin-top: 16px;
            background: #111111;
            padding: 16px;
            border: 1px solid #30363d;
            border-radius: 6px;
            box-shadow: 0 1px 2px rgba(0, 0, 0, .4);
        }}

        .tz h3,
        .card h3 {{
            margin: 0 0 12px;
            font-size: 14px;
            font-weight: 600;
            color: #a1a1aa;
            text-transform: uppercase;
            letter-spacing: .03em;
        }}

        .svg-container {{
            margin-top: 16px;
        }}

        .cards {{
            display: grid;
            grid-template-columns:
                repeat(auto-fit, minmax(360px, 1fr));
            gap: 16px;
        }}

        .module-link {{
            display: inline-flex;
            align-items: center;
            justify-content: center;

            min-height: 36px;
            padding: 0 13px;

            color: #c9d1d9;
            text-decoration: none;

            background: #21262d;
            border: 1px solid #30363d;
            border-radius: 5px;

            box-sizing: border-box;
            cursor: pointer;
        }}

        .module-link:hover {{
            background: #30363d;
        }}

        .module-link.war-room {{
            border-color: #388bfd;
        }}

        .module-link.research {{
            background: #6e40c9;
            border-color: #8957e5;
        }}

        .module-link.research:hover {{
            background: #8957e5;
        }}

        .session-panel {{
            width: 100%;
            display: grid;
            gap: 10px;
            padding-top: 14px;
            border-top: 1px solid #21262d;
        }}

        .session-title {{
            font-size: 11px;
            font-weight: 600;
            letter-spacing: .05em;
            text-transform: uppercase;
            color: #6e7681;
        }}

        .session-buttons {{ display: flex; gap: 8px; flex-wrap: wrap; }}
        .session-button.active {{ background: #1f6feb; border-color: #58a6ff; }}
        .session-times {{ display: flex; gap: 10px; flex-wrap: wrap; }}

        .topbar {{
            position: sticky;
            top: 0;
            z-index: 100;
            margin: -24px -24px 20px -24px;
            padding: 16px 24px;
            background: #0a0a0a;
            border-bottom: 1px solid #30363d;
        }}

        .topbar h2 {{
            font-weight: 600;
            letter-spacing: -.01em;
            margin: 0;
        }}
    </style>
</head>

<body>
    <div class="topbar">
        <h2>Dentour Protocol MT5 Alpha version</h2>
    </div>

    <div class="control-panel">
        <section class="panel panel-analysis">
            <p class="panel-title">Análisis</p>

            <form method="post" action="/analizar">
                <div class="field-row">
                    <label>
                        Fecha análisis

                        <input
                            type="date"
                            name="fecha"
                            value="{html.escape(fecha)}"
                            required
                        >
                    </label>

                    <label>
                        Temporalidad

                        <select name="temporalidad_base">
                            {opciones}
                        </select>
                    </label>

                    <button type="submit">
                        Analizar
                    </button>
                </div>

                <div class="session-panel">
                    <span class="session-title">Sesión COT</span>
                    <div class="session-buttons">
                        <button type="submit" name="session_code" value="asia" class="session-button {'active' if session_code == 'asia' else ''}">Asia</button>
                        <button type="submit" name="session_code" value="london" class="session-button {'active' if session_code == 'london' else ''}">Londres</button>
                        <button type="submit" name="session_code" value="new_york" class="session-button {'active' if session_code == 'new_york' else ''}">Nueva York</button>
                        <button type="submit" name="session_code" value="full_day" class="session-button {'active' if session_code == 'full_day' else ''}">Día completo</button>
                        <button type="submit" name="session_code" value="custom" class="session-button {'active' if session_code == 'custom' else ''}">Personalizada</button>
                    </div>
                    <div class="session-times">
                        <label>Inicio COT<input id="session-start" type="time" name="session_start" value="{html.escape(session_start)}" required></label>
                        <label>Fin COT<input id="session-end" type="time" name="session_end" value="{html.escape(session_end)}" required></label>
                    </div>
                </div>
            </form>
        </section>

        <div class="panel-row">
            <section class="panel panel-ingesta">
                <p class="panel-title">Ingesta</p>

                <form method="post" action="/ejecutar_ingesta">
                    <div class="field-row">
                        <label>
                            Fecha ingesta

                            <input
                                type="date"
                                name="fecha_ingesta"
                                value="{html.escape(fecha)}"
                            >
                        </label>

                        <button type="submit" class="primary">
                            Ejecutar Ingesta
                        </button>
                    </div>
                </form>
            </section>

            <section class="panel panel-nav">
                <p class="panel-title">Módulos</p>

                <div class="nav-links">
                    <a href="/war-room/" class="module-link war-room">
                        War Room
                    </a>
                    <a href="/research/" class="module-link research">
                        Laboratorio de Investigación
                    </a>
                </div>
            </section>
        </div>
    </div>

    {aviso}
    {zona}

    <div class="svg-container">
        {grafico}
    </div>

    <div class="cards">
        {tarjetas}
    </div>
</body>
</html>"""
)

#methods get y post segun la funcion ---------------------------------------------------------------------------------------------------------------

# Decorador FastAPI: registra una solicitud GET a la raíz y documenta que responde HTML.
@app.get("/", response_class=HTMLResponse)
# Ruta GET inicial. Muestra el día actual de Colombia y selecciona M15 como temporalidad predeterminada.
def home() -> HTMLResponse:
    return render(datetime.now(TZ_COT).date().isoformat(), "m15")


# Registra el envío POST del formulario de ingesta.
@app.post("/ejecutar_ingesta", response_class=HTMLResponse)
# Ruta POST que recibe una fecha del formulario, ejecuta el pipeline de ingest.py y redirige al resultado.
# Aquí se activa indirectamente MetaTrader 5: `ejecutar_pipeline` es quien debe inicializar, consultar y cerrar MT5.
def ejecutar_ingesta_ui(fecha_ingesta: str | None = Form(None)):
    try:
        # Interpreta la fecha enviada o usa el día actual en COT si el campo llegó vacío.
        seleccionada = date.fromisoformat(fecha_ingesta) if fecha_ingesta else datetime.now(TZ_COT).date()
        # Llama al pipeline externo que interactúa con MT5 y escribe los Parquet del día.
        ejecutar_pipeline(fecha=seleccionada)
        # Empaqueta fecha, temporalidad y mensaje en la URL de resultado.
        query = urlencode({"fecha": seleccionada.isoformat(), "tf": "m15", "mensaje": "Ingesta completada."})
        # Responde 303 See Other para que el navegador haga un GET y no repita el POST al refrescar.
        return RedirectResponse(f"/resultado?{query}", status_code=303)
    # Captura fallos operativos para mostrar una respuesta útil; el detalle completo también se registra.
    except Exception as exc:
        # Registra mensaje y traceback de la excepción de ingesta.
        logger.exception("Fallo de ingesta")
        # Vuelve al dashboard con el error visible y valores predeterminados seguros.
        return render(fecha_ingesta or date.today().isoformat(), "m15", f"Fallo de ingesta: {exc}")


# Registra la página GET de resultados utilizada tras la redirección.
@app.get("/resultado", response_class=HTMLResponse)
# Ruta GET usada después de la redirección POST/Redirect/GET para evitar repetir una ingesta al refrescar el navegador.
def resultado(fecha: str, tf: str = "m15", mensaje: str = "") -> HTMLResponse:
    # Delega todo el procesamiento en la función orquestadora.
    return analizar(fecha, tf, mensaje)


# Registra el envío POST del formulario de análisis.
@app.post("/analizar", response_class=HTMLResponse)
# Ruta POST del formulario de análisis; adapta los nombres de campos HTML a la función interna `analizar`.
def analizar_post(
    fecha: str = Form(...),
    temporalidad_base: str = Form(...),
    session_code: str = Form(DEFAULT_SESSION_CODE),
    session_start: str = Form("07:00"),
    session_end: str = Form("10:00"),
) -> HTMLResponse:
    # Pasa la fecha y temporalidad recibidas por formulario a la lógica común.
    return analizar(
        fecha, temporalidad_base, session_code=session_code,
        session_start=session_start, session_end=session_end,
    )

# modulo de analisis ---------------------------------------------------------------------

# Función orquestadora: valida entrada, consulta Parquet, transforma datos, crea visualizaciones y renderiza la respuesta.
def analizar(
    fecha: str,
    tf: str,
    mensaje: str = "",
    session_code: str = DEFAULT_SESSION_CODE,
    session_start: str = "07:00",
    session_end: str = "10:00",
) -> HTMLResponse:
    """Orquesta consulta, transformación, analítica y renderizado.

    Args:
        fecha: Día COT con formato ISO ``YYYY-MM-DD``.
        tf: Temporalidad principal: ``h1``, ``m15`` o ``m1``.
        mensaje: Mensaje opcional mostrado con escape HTML.

    Returns:
        Respuesta HTML con figura Plotly y tablas POI.

    Flow:
        ```mermaid
        flowchart LR
          A[Validar request] --> B[DuckDB: leer particiones]
          B --> C[Polars: VWAP/CVD/matriz]
          C --> D[Pandas: tablas POI]
          D --> E[Plotly + HTML]
        ```
    """
    # Lista blanca: rechaza cualquier temporalidad que no sea h1, m15 o m1.
    if tf not in TIMEFRAMES:
        return render(fecha, tf, "Temporalidad invalida.")
    try:
        sesion = resolver_sesion(session_code, session_start, session_end)
        # Valida y convierte YYYY-MM-DD a un objeto date.
        dia = date.fromisoformat(fecha)
        # Abre DuckDB después de validar entradas.
        con = conexion()
        try:
            # Consulta H1, M15 y M1 y las guarda en un diccionario indexado por temporalidad.
            barras = {x: consultar_barras(con, x, dia) for x in TIMEFRAMES}
            # Carga los ticks del mismo día operativo.
            ticks = consultar_ticks(con, dia)
        # El bloque finally se ejecuta tanto si las consultas funcionan como si lanzan una excepción.
        finally:
            # Cierra la conexión DuckDB de manera garantizada y libera recursos.
            con.close()
        # Desempaqueta los DataFrames respetando el orden definido en TIMEFRAMES.
        h1, m15, m1 = (barras[x] for x in TIMEFRAMES)
        # Selecciona la temporalidad elegida por el usuario como serie principal.
        base_raw = barras[tf]
        # Enriquece las barras principales con VWAP y sigma.
        base = calcular_vwap(base_raw)
        # Clasifica y pondera ticks para obtener delta y CVD.
        firmados = calcular_ticks_firmados(ticks)
        # Alinea el indicador de ticks con las barras de la temporalidad base.
        cvd = alinear_cvd(firmados, base_raw)
        # Calcula la confluencia direccional entre H1, M15 y M1.
        matriz = calcular_matriz(h1, m15, m1)
        # Construye Plotly y lo serializa como fragmento HTML; JavaScript se carga desde CDN.
        figura = construir_figura(base, cvd, matriz, tf, dia, sesion).to_html(full_html=False, include_plotlyjs="cdn")
        # Concatena tres tarjetas: perfil de volumen, Opening Range y barridos de liquidez.
        tarjetas = (_tabla(clusters_volumen(firmados, sesion), f"POI: Clusters HVN/LVN · {sesion.label}") +
                     _tabla(metricas_opening_range(m1, base, sesion), "Opening Range y volatilidad") +
                     _tabla(detectar_barridos(m1, firmados, sesion), "Barridos de liquidez y divergencia CVD"))
        # Entrega la página completa cuando todo el análisis termina correctamente.
        return render(
            fecha, tf, mensaje, figura, tarjetas, session_code, session_start, session_end
        )
    # Captura fallos operativos para mostrar una respuesta útil; el detalle completo también se registra.
    except Exception as exc:
        # Registra el traceback completo del fallo analítico.
        logger.exception("Error analitico")
        # Muestra el error dentro del dashboard en vez de devolver una página de excepción sin formato.
        return render(
            fecha, tf, f"Error: {exc}", session_code=session_code,
            session_start=session_start, session_end=session_end,
        )

# Este bloque solo se ejecuta al lanzar `python app.py`; no se ejecuta cuando Uvicorn importa el módulo.
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)

# 349876.34 proximas consolidaciones, sistema robusto de correlacionamiento de movimientos
# futuros bugfixes e implemenacion de calculos manuales, asi 
# #como modelos predictivos en base a correlaciones globales
