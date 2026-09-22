# Arquitectura de Dentour Protocol MT5

## Flujo actual

MetaTrader 5
→ normalización
→ validación PyArrow
→ escritura Parquet
→ consulta DuckDB
→ transformación Polars/Pandas
→ analítica
→ Plotly
→ FastAPI

## Módulos actuales

### ingest.py

Responsable de extracción, normalización, validación, persistencia y auditoría.

### app.py

Responsable de consulta, cálculos analíticos, gráficos y presentación web.

## Problema actual

`app.py` concentra demasiadas responsabilidades y debe repararse antes de dividirse.

## Objetivo incremental

Separar gradualmente:

1. Configuración.
2. Contratos de datos.
3. Ingesta.
4. Acceso a datos.
5. Analítica.
6. Visualización.
7. Aplicación web.