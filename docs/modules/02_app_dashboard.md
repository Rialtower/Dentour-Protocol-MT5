# Dashboard diario

## Propósito

`app.py` contiene la aplicación FastAPI y el análisis intradiario principal.

## Flujo

```text
Formulario
→ fecha, temporalidad y sesión
→ consulta DuckDB
→ transformación Polars
→ tablas Pandas pequeñas
→ figura Plotly
→ HTML
```

## Cálculos

- VWAP y bandas.
- Ticks firmados.
- CVD.
- Confluencia H1/M15/M1.
- Clusters de volumen.
- Opening Range relativo al inicio de sesión.
- Barridos de liquidez.

## Sesiones

Las funciones analíticas deben recibir `SessionWindow`. No deben conservar horarios fijos internos.

## Frontend

Actualmente puede combinar HTML incrustado y navegación hacia otros módulos. A medida que crezca, conviene separar:

```text
static/css/
static/js/
templates/
```

## Rendimiento

- limitar puntos enviados a Plotly;
- usar Scattergl cuando corresponda;
- seleccionar columnas explícitas;
- filtrar antes de transformar.
