# Convenciones de código

## Tipado

Usar anotaciones modernas y dataclasses inmutables para contratos.

## SQL

- parámetros `?`;
- columnas explícitas;
- sin concatenación de entrada;
- sin comentarios Python `#` dentro de SQL.

## Recursos

Cerrar conexiones en `finally` o context managers.

## DataFrames

- DuckDB reduce;
- Polars transforma;
- Pandas presenta resultados pequeños.

## Tiempo

Conservar apertura y disponibilidad por separado.

## Errores

No ocultar excepciones de calidad. Los fallos deben indicar módulo, regla y cantidad afectada.

## Nombres

Los nombres de versiones y columnas forman parte del contrato; no deben modificarse silenciosamente.
