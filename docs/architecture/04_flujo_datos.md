# Flujo de datos

## Flujo de ingesta

```text
Fecha COT
→ intervalo UTC
→ MetaTrader 5
→ Pandas
→ validación
→ PyArrow
→ Parquet ZSTD
→ auditoría
```

## Flujo diario

```text
Parquet del día
→ DuckDB
→ Polars
→ VWAP, CVD y contexto
→ Plotly
→ HTML
```

## Flujo War Room

```text
Mes cerrado
→ DuckDB filtra y agrega
→ Polars calcula contexto mensual
→ tablas y gráficos
```

## Flujo Research

```text
M1/M15/H1
→ data_access
→ features
→ targets
→ dataset
→ baselines
→ validation
→ models
→ evaluation
```

## Transformaciones

### DuckDB

Se usa para minimizar transferencia:

- selección explícita de columnas;
- filtros UTC;
- lectura de múltiples Parquet;
- agregaciones previas.

### Polars

Se usa para:

- rolling windows;
- join_asof;
- variables temporales;
- MFE y MAE;
- agrupaciones y validaciones.

## Persistencia

Actualmente se persiste el Data Lake original. Los resultados de Research se construyen en memoria mientras no exista un registro formal de experimentos y modelos.
