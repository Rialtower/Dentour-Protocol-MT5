# Rendimiento y memoria

## Principios

- filtrar antes de transferir;
- seleccionar columnas explícitas;
- agregar ticks en DuckDB;
- evitar Pandas para históricos grandes;
- ordenar solo cuando sea necesario;
- evitar copias repetidas;
- medir tamaños y filas.

## DuckDB

Adecuado para escanear Parquet, filtrar UTC y reducir datos.

## Polars

Adecuado para rolling windows, joins y agregaciones columnares.

## Plotly

Reducir puntos enviados al navegador. Usar Scattergl para series grandes.

## Research

Un mes es pequeño, pero varios meses y sesiones aumentarán memoria. El acceso deberá cargar períodos controlados y warmup explícito.
