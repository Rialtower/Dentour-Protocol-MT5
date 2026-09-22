# Flujo de trabajo del aprendiz

## Etapa 1. Comprender los datos

- Diferenciar M1, M15, H1 y ticks.
- Comprender UTC, COT y hora del broker.
- Revisar particiones Parquet.
- Confirmar que apertura no equivale a disponibilidad.

## Etapa 2. Validar Research desde HTML

1. Abrir `/research/`.
2. Seleccionar agosto de 2026.
3. Ejecutar Asia.
4. Ejecutar Londres.
5. Ejecutar Nueva York.
6. Revisar features, exclusiones, targets y baselines.

## Etapa 3. Entender el dataset

- X contiene únicamente información disponible.
- y contiene lo que ocurrió después.
- `observation_id` identifica cada caso.
- Los targets no pueden entrar como features.

## Etapa 4. Entender baseline

El baseline responde con frecuencias simples. El modelo debe superarlo en datos posteriores para aportar valor.

## Etapa 5. Validación provisional

Con un solo mes se divide por días para comprobar mecánicamente el pipeline. Esto no demuestra generalización.

## Etapa 6. Varios meses

Con ocho meses completos puede ejecutarse:

```text
6 meses train
1 mes validation
1 mes test
```

## Etapa 7. Conclusiones responsables

No afirmar consistencia con una única división. Registrar meses positivos y negativos.
