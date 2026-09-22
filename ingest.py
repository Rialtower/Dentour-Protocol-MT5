"""
Pipeline MT5 -> Parquet para un día operativo de Colombia, edición didáctica.

Flujo general:
1. Interpreta el día en America/Bogota y lo convierte al intervalo UTC [inicio, fin).
2. Evita ejecuciones concurrentes con un lock en memoria y otro archivo de lock.
3. Conecta Python con el terminal MetaTrader 5 y selecciona el símbolo.
4. Descarga barras M1, M15, H1 y/o ticks.
5. Normaliza y valida los datos con Pandas.
6. Impone contratos de tipos con esquemas PyArrow.
7. Escribe Parquet ZSTD de manera atómica en particiones Hive.
8. Reabre y audita cada archivo.
9. Cierra MT5 y libera todos los locks incluso cuando ocurre un error.

Esta versión conserva la lógica ejecutable del archivo original y añade comentarios de estudio.

GUÍA DIDÁCTICA AMPLIADA
========================

RESPONSABILIDAD DEL ARCHIVO
---------------------------
ingest.py es la única frontera entre DPMT5 y el terminal MetaTrader 5. Convierte
un día operativo colombiano en límites UTC, descarga barras o ticks, normaliza
los datos, impone esquemas Arrow, escribe Parquet ZSTD de forma atómica y audita
el archivo resultante.

FLUJO PRINCIPAL
---------------
1. Validar tipos y fecha solicitados.
2. Adquirir lock interno y lock de archivo.
3. Convertir el día COT a [inicio_utc, fin_utc).
4. Inicializar MetaTrader 5 y seleccionar el símbolo.
5. Descargar M1, M15, H1 y/o ticks.
6. Normalizar arrays estructurados con Pandas.
7. Aplicar de nuevo el filtro semiabierto para proteger fronteras.
8. Convertir a PyArrow con esquema explícito.
9. Escribir un archivo temporal comprimido con ZSTD.
10. Reemplazar atómicamente el destino.
11. Reabrir y auditar filas, esquema, codec y estadísticas.
12. Cerrar MT5 y liberar locks en finally.

CONTRATOS IMPORTANTES
---------------------
- Almacenamiento temporal en UTC.
- Calendario de selección en America/Bogota.
- Particiones Hive tipo/year=YYYY/month=MM/day=DD.
- Archivos deterministas por símbolo, tipo y fecha.
- Barras y ticks no pueden contener nulos según el esquema Arrow.
- Bid y ask no se inventan si están ausentes.
- El final del rango siempre es exclusivo.

LECTURA RECOMENDADA
-------------------
1. Constantes y esquemas Arrow.
2. Conversión temporal COT a UTC.
3. Inicialización MT5.
4. Normalización de barras y ticks.
5. Construcción de rutas.
6. Escritura atómica y auditoría.
7. Orquestación y locks.
8. Interfaz de línea de comandos.

DEUDA TÉCNICA DOCUMENTADA
-------------------------
- En la versión recibida, ejecutar_pipeline normaliza el mismo lote dos veces:
  existe una asignación compacta y otra asignación multilinea inmediatamente
  después. El resultado funcional suele ser el mismo, pero duplica cómputo.
  Esta copia comentada conserva el comportamiento original para que el ejercicio
  sea documental. El refactor correcto debe eliminar una de las dos asignaciones.
- El filtro [inicio, fin) aplicado después de normalizar es correcto y debe
  conservarse para evitar fronteras repetidas entre particiones diarias.
- La auditoría comprueba metadatos Parquet, pero una futura ampliación puede
  verificar también orden, unicidad temporal y consistencia OHLC.

SEGURIDAD OPERATIVA
-------------------
- Nunca publicar credenciales MT5.
- No retirar finally de shutdown o liberación de locks.
- No reemplazar os.replace por una escritura directa al destino.
- No convertir timestamps ingenuos sin zona.
- No rellenar bid y ask faltantes con valores fabricados.
"""
# Pospone la evaluación de anotaciones de tipo y facilita usar sintaxis moderna sin resolver todos los tipos al importar.
from __future__ import annotations

# argparse construye la interfaz de línea de comandos para aceptar --tipos y --fecha.
import argparse
# logging registra información operativa y errores sin depender de print().
import logging
# os aporta variables de entorno, PID, creación exclusiva de archivos, reemplazo atómico y otras operaciones del sistema.
import os
# threading proporciona un lock en memoria para impedir dos ingestas simultáneas dentro del mismo proceso Python.
import threading
# contextlib.suppress permite ignorar de manera explícita un FileNotFoundError durante la limpieza del lock.
import contextlib
# dataclass genera automáticamente constructor, representación y comparación para el registro de resultados.
from dataclasses import dataclass
# Tipos temporales usados para representar el día COT, límites horarios, duración de un día y UTC.
from datetime import date, datetime, time, timedelta, timezone
# Path permite construir carpetas y archivos de forma portable y legible.
from pathlib import Path
# Final marca constantes para análisis estático; Sequence acepta listas, tuplas y otras secuencias de tipos.
from typing import Final, Sequence
# ZoneInfo usa la base IANA para conversiones horarias correctas.
from zoneinfo import ZoneInfo

# API oficial de Python para comunicarse con el terminal MetaTrader 5 instalado y abierto en la máquina.
import MetaTrader5 as mt5
# Pandas normaliza los arrays estructurados que devuelve MetaTrader 5.
import pandas as pd
# PyArrow define esquemas estrictos y transforma DataFrames en tablas columnares.
import pyarrow as pa
# Módulo de PyArrow que escribe, abre y audita archivos Parquet.
import pyarrow.parquet as pq

# Logger específico del módulo. La configuración visible se establece en _main() o por la aplicación que lo importe.
logger = logging.getLogger("ingest")
# Raíz del Data Lake, configurable mediante DATA_LAKE_DIR. La ruta predeterminada es relativa al directorio desde el que se ejecuta Python.
DATA_LAKE_DIR: Final[Path] = Path(os.getenv("DATA_LAKE_DIR", "./data_lake"))
# Símbolo exacto del broker. El sufijo m depende del broker y puede cambiar mediante MT5_SYMBOL.
SYMBOL: Final[str] = os.getenv("MT5_SYMBOL", "XAUUSDm")
# Zona usada para interpretar el día operativo solicitado por el usuario.
TZ_COT: Final[ZoneInfo] = ZoneInfo("America/Bogota")
# Zona UTC fija usada para consultar MT5 y almacenar timestamps.
TZ_UTC: Final[timezone] = timezone.utc
# Lista blanca y orden predeterminado de datasets que puede ingerir el pipeline.
TIPOS_DISPONIBLES: Final[tuple[str, ...]] = ("m1", "m15", "h1", "ticks")
# Bloqueo interno del proceso. No protege contra otro proceso distinto, por eso también existe LOCK_FILE.
_LOCK = threading.Lock()
# Lock persistente en el sistema de archivos para detectar otra instancia del pipeline usando el mismo Data Lake.
LOCK_FILE: Final[Path] = DATA_LAKE_DIR / ".ingest.lock"

# Esquema contractual de barras OHLCV. Obliga tipos, orden de columnas, timezone UTC y ausencia de nulos.
SCHEMA_BARRAS: Final[pa.Schema] = pa.schema([
    pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("open", pa.float64(), nullable=False), pa.field("high", pa.float64(), nullable=False),
    pa.field("low", pa.float64(), nullable=False), pa.field("close", pa.float64(), nullable=False),
    pa.field("volume", pa.int64(), nullable=False), pa.field("spread", pa.int32(), nullable=False),
    pa.field("real_volume", pa.int64(), nullable=False),
])
# Esquema contractual de ticks. Conserva precios, volúmenes y flags devueltos por MT5.
SCHEMA_TICKS: Final[pa.Schema] = pa.schema([
    pa.field("timestamp", pa.timestamp("us", tz="UTC"), nullable=False),
    pa.field("bid", pa.float64(), nullable=False), pa.field("ask", pa.float64(), nullable=False),
    pa.field("last", pa.float64(), nullable=False), pa.field("volume", pa.float64(), nullable=False),
    pa.field("volume_real", pa.float64(), nullable=False), pa.field("flags", pa.uint32(), nullable=False),
])
# Relaciona cada dataset con el esquema Arrow que debe cumplir antes y después de escribirlo.
SCHEMAS: Final[dict[str, pa.Schema]] = {"m1": SCHEMA_BARRAS, "m15": SCHEMA_BARRAS,
                                        "h1": SCHEMA_BARRAS, "ticks": SCHEMA_TICKS}
# Traduce nombres internos a las constantes numéricas que requiere copy_rates_range().
TIMEFRAMES: Final[dict[str, int]] = {"m1": mt5.TIMEFRAME_M1, "m15": mt5.TIMEFRAME_M15,
                                     "h1": mt5.TIMEFRAME_H1}

# Crea objetos inmutables y compactos: frozen evita reasignar campos y slots evita un diccionario por instancia.
@dataclass(frozen=True, slots=True)
# Resumen estructurado de cada archivo creado correctamente por el pipeline.
class RegistroIngesta:
    tipo_dato: str
    ruta: Path
    filas: int
    desde_utc: datetime
    hasta_utc: datetime


# Convierte un día civil colombiano en un intervalo absoluto UTC semiabierto [inicio, fin).
# Para el día actual, el final es el instante presente y no la medianoche futura.
def rango_dia_cot_en_utc(fecha_cot: date | None = None) -> tuple[datetime, datetime]:
    """Convierte el dia civil COT seleccionado al intervalo UTC [inicio, fin)."""
    # Obtiene el instante actual directamente en la zona de Colombia.
    ahora_cot = datetime.now(TZ_COT)
    # Usa la fecha indicada o, si es None, el día colombiano actual.
    objetivo = fecha_cot or ahora_cot.date()
    # Rechaza fechas futuras porque MT5 no puede devolver mercado que todavía no ocurrió.
    if objetivo > ahora_cot.date():
        raise ValueError("No se puede ingerir una fecha futura.")
    # Establece la medianoche inicial 00:00:00 con zona America/Bogota.
    inicio_cot = datetime.combine(objetivo, time.min, tzinfo=TZ_COT)
    # Para hoy evita consultar el futuro; para días terminados usa la siguiente medianoche.
    fin_cot = ahora_cot if objetivo == ahora_cot.date() else inicio_cot + timedelta(days=1)
    # Convierte ambos límites al mismo instante expresado en UTC.
    return inicio_cot.astimezone(TZ_UTC), fin_cot.astimezone(TZ_UTC)


# Inicializa el puente Python-terminal MT5 y hace visible/selecciona el símbolo configurado.
# Esta función no inicia sesión por sí sola; usa la cuenta y terminal configurados en MetaTrader 5.
def _inicializar_mt5() -> None:
    # initialize() conecta Python con el terminal MT5; False indica que no pudo establecerse el enlace.
    if not mt5.initialize():
        # Recupera el código y descripción del último error reportado por la API MT5.
        codigo, descripcion = mt5.last_error()
        raise RuntimeError(f"Fallo al inicializar MT5 [{codigo}]: {descripcion}")
    # symbol_select(symbol, True) agrega o activa el símbolo en Observación del Mercado.
    if not mt5.symbol_select(SYMBOL, True):
        raise RuntimeError(f"MT5 no pudo seleccionar {SYMBOL!r}: {mt5.last_error()}")


# Transforma el array estructurado de copy_rates_range() en un DataFrame con el contrato SCHEMA_BARRAS.
def _normalizar_barras(datos: object) -> pd.DataFrame:
    # Convierte el ndarray estructurado de MT5 en columnas Pandas.
    df = pd.DataFrame(datos)
    # Devuelve temprano si MT5 no entregó registros; el pipeline decidirá si esto constituye un error.
    if df.empty:
        return df
    # Adapta los nombres MT5 al esquema interno común.
    df = df.rename(columns={"time": "timestamp", "tick_volume": "volume"})
    # MT5 entrega barras con epoch Unix en segundos; se convierten a timestamps UTC conscientes de zona.
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s", utc=True)
    # Selecciona y ordena exactamente las columnas definidas por el esquema de barras.
    return df.loc[:, SCHEMA_BARRAS.names]


# Transforma y valida el array de copy_ticks_range() sin fabricar bid ni ask.
def _normalizar_ticks(datos: object) -> pd.DataFrame:
    """Normaliza ticks MT5 sin inventar precios ausentes.

    Args:
        datos: Array estructurado devuelto por ``copy_ticks_range``.

    Returns:
        DataFrame de forma ``(n_ticks, 7)`` compatible con ``SCHEMA_TICKS``.

    Raises:
        ValueError: Si faltan timestamp, bid o ask, o existen precios inválidos.
    """
    # Convierte el ndarray estructurado de MT5 en columnas Pandas.
    df = pd.DataFrame(datos)
    # Devuelve temprano si MT5 no entregó registros; el pipeline decidirá si esto constituye un error.
    if df.empty:
        return df
    # Prefiere time_msc para conservar milisegundos; cae a time en segundos si la columna no existe.
    origen, unidad = ("time_msc", "ms") if "time_msc" in df.columns else ("time", "s")
    # Define el mínimo imprescindible para considerar válido un tick.
    requeridas = {origen, "bid", "ask"}
    # Calcula por diferencia de conjuntos qué columnas críticas no llegaron.
    faltantes = requeridas - set(df.columns)
    if faltantes:
        raise ValueError(f"Ticks MT5 sin columnas críticas: {sorted(faltantes)}")
    # Convierte epoch a UTC y hace que valores temporales inválidos generen una excepción.
    df["timestamp"] = pd.to_datetime(df[origen], unit=unidad, utc=True, errors="raise")
    # Recorre campos que algunas fuentes o estados de mercado podrían omitir.
    for columna in ("last", "volume", "volume_real", "flags"):
        if columna not in df.columns:
            # Completa solo campos auxiliares ausentes con cero; nunca inventa bid ni ask.
            df[columna] = 0
    # Lista de campos que obligatoriamente deben poder convertirse a números.
    numericas = ["bid", "ask", "last", "volume", "volume_real", "flags"]
    # Convierte tipos y falla inmediatamente ante texto u otro contenido inválido.
    df[numericas] = df[numericas].apply(pd.to_numeric, errors="raise")
    # Impide almacenar cotizaciones nulas, cero o negativas.
    if df[["bid", "ask"]].isna().any().any() or (df["bid"] <= 0).any() or (df["ask"] <= 0).any():
        raise ValueError("Ticks MT5 contienen bid/ask nulos o no positivos.")
    # Valida que el spread ask - bid no sea negativo.
    if (df["ask"] < df["bid"]).any():
        raise ValueError("Ticks MT5 contienen spread negativo (ask < bid).")
    # Devuelve únicamente las siete columnas del contrato y en el orden correcto.
    return df.loc[:, SCHEMA_TICKS.names]


# Construye la partición Hive del día y el nombre determinista del archivo Parquet.
def _ruta(tipo: str, fecha_cot: date) -> Path:
    # Usa particiones Hive year=YYYY/month=MM/day=DD para permitir pruning eficiente en DuckDB.
    carpeta = DATA_LAKE_DIR / tipo / f"year={fecha_cot:%Y}" / f"month={fecha_cot:%m}" / f"day={fecha_cot:%d}"
    # Crea toda la jerarquía necesaria y no falla si ya existe.
    carpeta.mkdir(parents=True, exist_ok=True)
    # El nombre incluye símbolo, dataset y fecha para ser legible y determinista.
    return carpeta / f"{SYMBOL}_{tipo}_{fecha_cot:%Y%m%d}.parquet"


# Escribe primero un archivo temporal y solo después reemplaza el destino definitivo.
# Así se reduce la posibilidad de dejar un Parquet parcial si el proceso falla durante la escritura.
def escribir_parquet_atomico(tabla: pa.Table, ruta: Path) -> None:
    # Crea el nombre temporal en la misma carpeta para que os.replace opere dentro del mismo sistema de archivos.
    temporal = ruta.with_name(f"{ruta.stem}_temp.parquet")
    try:
        # Serializa la tabla con ZSTD, estadísticas, Parquet 2.6 y diccionarios cuando sean apropiados.
        pq.write_table(tabla, temporal, compression="ZSTD", write_statistics=True,
                       version="2.6", use_dictionary=True)
        # Reemplaza atómicamente el destino en sistemas compatibles; los lectores ven el archivo anterior o el nuevo, no uno parcial.
        os.replace(temporal, ruta)
    finally:
        # Limpia restos temporales incluso si write_table u os.replace fallan.
        temporal.unlink(missing_ok=True)


# Reabre el Parquet y verifica filas, esquema, compresión ZSTD y estadísticas en cada columna.
def auditar_parquet(ruta: str | Path, esquema: pa.Schema) -> None:
    # Abre solo la estructura Parquet necesaria para inspeccionar metadatos y esquema.
    archivo = pq.ParquetFile(Path(ruta))
    # Obtiene filas, grupos de filas y metadatos por columna.
    meta = archivo.metadata
    # Un archivo vacío se considera una ingesta inválida.
    if meta.num_rows <= 0:
        raise AssertionError(f"Parquet sin filas: {ruta}")
    # Compara el esquema lógico Arrow ignorando metadatos accesorios de Pandas.
    if not archivo.schema_arrow.equals(esquema, check_metadata=False):
        raise AssertionError(f"Esquema Arrow inesperado: {ruta}")
    # Recorre todos los row groups, no solo el primero.
    for rg in range(meta.num_row_groups):
        # Inspecciona cada columna física de cada row group.
        for c in range(meta.row_group(rg).num_columns):
            col = meta.row_group(rg).column(c)
            # Exige tanto el codec solicitado como estadísticas disponibles para futuras consultas eficientes.
            if col.compression.upper() != "ZSTD" or col.statistics is None:
                raise AssertionError(f"Codec/estadisticas invalidos en {ruta}: {col.path_in_schema}")


# Orquesta validación, exclusión mutua, conexión MT5, descarga, normalización, escritura y auditoría.
def ejecutar_pipeline(tipos: Sequence[str] = TIPOS_DISPONIBLES,
                       fecha: date | None = None) -> list[RegistroIngesta]:
    """Orquesta extracción, validación, escritura atómica y auditoría.

    Args:
        tipos: Subconjunto único de ``m1``, ``m15``, ``h1`` y ``ticks``.
        fecha: Día civil colombiano. ``None`` selecciona el día COT actual.

    Returns:
        Un registro por dataset escrito y auditado.

    Raises:
        ValueError: Fecha futura, tipo inválido o esquema/datos inválidos.
        RuntimeError: MT5 no disponible, ingesta concurrente o lote vacío.
        OSError: Fallo de escritura o reemplazo atómico.

    Flow:
        ```mermaid
        flowchart LR
          A[Validar parámetros] --> B[Adquirir locks]
          B --> C[Calcular día COT en UTC]
          C --> D[Inicializar MT5]
          D --> E[Extraer rangos absolutos]
          E --> F[Normalizar y coercionar Arrow]
          F --> G[Escribir ZSTD temporal]
          G --> H[os.replace]
          H --> I[Auditar metadatos]
          I --> J[Cerrar MT5 y liberar locks]
        ```
    """
    # Normaliza a minúsculas, elimina duplicados y conserva el orden original.
    solicitados = tuple(dict.fromkeys(x.lower() for x in tipos))
    # Detecta cualquier nombre fuera de la lista blanca.
    invalidos = set(solicitados) - set(TIPOS_DISPONIBLES)
    if invalidos:
        raise ValueError(f"Tipos no soportados: {sorted(invalidos)}")
    # Intenta adquirir el lock sin esperar; si está ocupado, falla de inmediato.
    if not _LOCK.acquire(blocking=False):
        raise RuntimeError("Ya existe una ingesta en este proceso.")

    # Guardará el descriptor del archivo lock para poder cerrarlo con seguridad.
    lock_fd: int | None = None
    # Bandera que evita llamar shutdown() si initialize() nunca tuvo éxito.
    mt5_inicializado = False
    try:
        # Resuelve el día operativo antes de iniciar la descarga.
        fecha_cot = fecha or datetime.now(TZ_COT).date()
        # Obtiene límites UTC compatibles con los métodos range de MT5.
        inicio, fin = rango_dia_cot_en_utc(fecha_cot)
        # Asegura que exista la raíz antes de intentar crear el lock externo.
        DATA_LAKE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            # O_EXCL junto con O_CREAT hace que solo un proceso pueda crear el lock inexistente.
            lock_fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            # Guarda el PID para facilitar diagnóstico manual de quién creó el lock.
            os.write(lock_fd, str(os.getpid()).encode("ascii"))
        # Interpreta un lock existente como otra ingesta activa o un lock huérfano.
        except FileExistsError as exc:
            raise RuntimeError(f"Ingesta concurrente detectada: {LOCK_FILE}") from exc

        # Conecta con el terminal y selecciona el símbolo después de obtener ambos locks.
        _inicializar_mt5()
        # Marca que shutdown() será obligatorio en finally.
        mt5_inicializado = True
        # Acumula un resumen por cada dataset terminado y auditado.
        resultados: list[RegistroIngesta] = []
        # Procesa secuencialmente cada temporalidad o ticks solicitados.
        for tipo in solicitados:
            # Para ticks solicita todos los cambios disponibles con COPY_TICKS_ALL; para barras usa el timeframe correspondiente.
            datos = (mt5.copy_ticks_range(SYMBOL, inicio, fin, mt5.COPY_TICKS_ALL)
                     # Expresión condicional que selecciona la llamada MT5 según el tipo de dataset.
                     if tipo == "ticks" else
                     # copy_rates_range devuelve barras cuyo tiempo de apertura cae dentro del intervalo solicitado.
                     mt5.copy_rates_range(SYMBOL, TIMEFRAMES[tipo], inicio, fin))
            # Aplica la normalización específica y las validaciones antes de Arrow.
            df = _normalizar_ticks(datos) if tipo == "ticks" else _normalizar_barras(datos)
            # Devuelve temprano si MT5 no entregó registros; el pipeline decidirá si esto constituye un error.
            df = (
                _normalizar_ticks(datos)
                if tipo == "ticks"
                else _normalizar_barras(datos)
            )
            df = df.loc[
                (df["timestamp"] >= inicio)
                & (df["timestamp"] < fin)
                ].copy()
            if df.empty:
                raise RuntimeError(f"MT5 no devolvió {tipo} entre {inicio} y {fin}: {mt5.last_error()}")
            # Coacciona al esquema explícito; safe=True evita conversiones potencialmente destructivas o fuera de rango.
            tabla = pa.Table.from_pandas(df, schema=SCHEMAS[tipo], preserve_index=False, safe=True)
            # Calcula y crea la partición donde se guardará el dataset.
            ruta = _ruta(tipo, fecha_cot)
            # Persiste la tabla sin exponer archivos incompletos al dashboard.
            escribir_parquet_atomico(tabla, ruta)
            # Verifica inmediatamente que lo escrito cumple el contrato esperado.
            auditar_parquet(ruta, SCHEMAS[tipo])
            # Registra tipo, ruta, número de filas y límites UTC consultados.
            resultados.append(RegistroIngesta(tipo, ruta, tabla.num_rows, inicio, fin))
        # Devuelve únicamente cuando todos los tipos solicitados terminaron correctamente.
        return resultados
    finally:
        # Cierra MT5 solo si la inicialización fue exitosa.
        if mt5_inicializado:
            # Libera la conexión entre Python y el terminal MetaTrader 5.
            mt5.shutdown()
        # Solo intenta cerrar/eliminar el lock externo si llegó a crearse.
        if lock_fd is not None:
            # Cierra el descriptor antes de eliminar el archivo de lock.
            os.close(lock_fd)
            # Tolera que el archivo ya haya sido eliminado durante la limpieza.
            with contextlib.suppress(FileNotFoundError):
                # Elimina el indicador de ingesta activa.
                LOCK_FILE.unlink()
        # Libera siempre el lock interno, incluso ante cualquier excepción.
        _LOCK.release()


# Define la interfaz de consola para ejecutar ingest.py sin pasar por FastAPI.
def _main() -> None:
    # Crea la ayuda y descripción del comando.
    parser = argparse.ArgumentParser(description="Ingesta MT5 por dia operativo COT")
    # Acepta una lista separada por comas; de forma predeterminada procesa todos los datasets.
    parser.add_argument("--tipos", default=",".join(TIPOS_DISPONIBLES))
    # Convierte automáticamente YYYY-MM-DD en date y muestra error de CLI si el formato es inválido.
    parser.add_argument("--fecha", type=date.fromisoformat, help="Fecha Colombia YYYY-MM-DD")
    # Lee y valida los argumentos enviados desde la terminal.
    args = parser.parse_args()
    # Configura nivel INFO y formato de logs cuando ingest.py se ejecuta directamente.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    # Separa --tipos por comas, elimina espacios/vacíos y llama al pipeline.
    ejecutar_pipeline([x.strip() for x in args.tipos.split(",") if x.strip()], args.fecha)

# Solo ejecuta la interfaz CLI cuando el archivo se lanza directamente; no al importarlo desde app.py.
if __name__ == "__main__":
    _main()
