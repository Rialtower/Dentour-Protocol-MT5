# Decisiones arquitectónicas

## Data Lake en lugar de una base transaccional

Parquet permite conservar datos históricos columnares, comprimidos y consultables directamente por DuckDB.

## Cómputo on-the-fly

War Room y Research recalculan resultados desde el Data Lake para evitar vistas analíticas desactualizadas y duplicación silenciosa.

## Sesiones compartidas

`sessions.py` evita que cada módulo interprete Asia, Londres o Nueva York de forma diferente.

## Primer modelo simple

La regresión logística regularizada es interpretable, rápida y adecuada como primera referencia. Un modelo más complejo no debe introducirse antes de comprobar que las variables aportan información fuera de muestra.

## Entrenamiento fuera de HTTP

El navegador puede validar datos y mostrar resultados. El entrenamiento formal debe ejecutarse mediante un proceso controlado que registre configuración, versiones y métricas.

## Meses cerrados

War Room y la validación mensual utilizan meses cerrados para impedir resultados parciales o cambiantes.

## Exclusión antes que fabricación

DPMT5 excluye observaciones ambiguas, incompletas o con gaps en lugar de rellenar o inventar el orden de eventos.
