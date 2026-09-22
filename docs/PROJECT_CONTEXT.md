# Dentour Protocol MT5

## Propósito

Dentour Protocol MT5 es una plataforma local de ingeniería de datos y analítica para MetaTrader 5.

Su objetivo es extraer barras y ticks, validar su calidad, almacenarlos en Parquet y analizarlos mediante herramientas de Python.

El proyecto no ejecuta operaciones automáticamente y sus indicadores no representan garantías financieras.

## Estado actual

El proyecto comienza con dos módulos principales:

### ingest.py

Responsable de:

- Conexión con MetaTrader 5.
- Selección del símbolo.
- Extracción de M1, M15, H1 y ticks.
- Conversión del día de Colombia a UTC.
- Normalización de datos.
- Validación de bid, ask y spread.
- Aplicación de esquemas PyArrow.
- Escritura atómica de Parquet ZSTD.
- Auditoría de archivos.
- Control de concurrencia mediante locks.
- Cierre y limpieza de recursos.

### app.py

Responsable o proyectado para:

- Aplicación FastAPI.
- Consultas DuckDB sobre Parquet.
- Transformaciones con Polars y Pandas.
- Cálculo de VWAP y CVD.
- Análisis de opening ranges.
- Clusters de volumen.
- Detección de barridos.
- Matriz de confluencia H1, M15 y M1.
- Gráficos Plotly.
- Interfaz HTML.

app.py se encuentra en desarrollo y puede incluir contenido incompleto o errores estructurales. Debe ser auditado antes de considerarlo ejecutable.

## Tecnologías

- Python.
- MetaTrader5.
- FastAPI.
- DuckDB.
- Polars.
- Pandas.
- PyArrow.
- Parquet.
- Plotly.
- Pytest.

## Zonas horarias

- Almacenamiento: UTC.
- Día operativo: America/Bogota.
- Zona configurada del broker: Europe/Athens.

Los intervalos de consulta deben seguir la forma [inicio, fin).

## Contrato de barras

- timestamp
- open
- high
- low
- close
- volume
- spread
- real_volume

## Contrato de ticks

- timestamp
- bid
- ask
- last
- volume
- volume_real
- flags

## Principios técnicos

- Cambios pequeños y comprobables.
- Esquemas explícitos.
- Escrituras atómicas.
- Protección contra concurrencia.
- Conversión temporal correcta.
- Pruebas sin depender de MT5 real.
- SQL parametrizado.
- Separación de responsabilidades.
- Ausencia de secretos en el repositorio.
- Ausencia de data leakage y look-ahead bias.
- Diferenciación entre volumen real y tick volume.
- Indicadores descritos con sus limitaciones.

## Prioridad actual

1. Auditar y reparar app.py.
2. Crear pruebas para ingest.py.
3. Consolidar configuración y dependencias.
4. Separar analítica, acceso a datos y presentación.
5. Añadir logging y observabilidad.
6. Documentar ejecución local.