# Dentour Protocol MT5

Plataforma local de ingesta y analítica de datos procedentes de MetaTrader 5.

## Estado del proyecto

Proyecto en desarrollo.

- `ingest.py`: extracción, normalización, escritura y auditoría de datos.
- `app.py`: aplicación FastAPI y analítica. Actualmente requiere auditoría y reparación.
- `data_lake/`: almacenamiento local de archivos Parquet.
- `tests/`: pruebas automatizadas.
- `docs/`: documentación de arquitectura y decisiones técnicas.

## Tecnologías

- Python
- MetaTrader 5
- PyArrow y Parquet
- DuckDB
- Polars y Pandas
- FastAPI
- Plotly
- Pytest

## Zonas horarias

- Almacenamiento: UTC
- Día operativo: America/Bogota
- Broker configurado: Europe/Athens

## Advertencia

El proyecto realiza análisis de datos. No garantiza resultados financieros ni constituye asesoramiento financiero.