# Contratos del experimento

## Archivo

`research/contracts.py`

## Objetos

- `Timeframe`;
- `ReferencePrice`;
- `AmbiguousBarrierPolicy`;
- `ResearchScope`;
- `ExperimentConfig`;
- `DatasetSplitConfig`.

## Inmutabilidad

Las dataclasses congeladas impiden cambios accidentales durante una ejecución.

## Versiones

```text
feature_version
target_version
dataset_version
experiment_version
```

Las versiones permiten reconocer resultados producidos con contratos distintos.

## Alcances

- sesión individual;
- todos los presets separados;
- dataset combinado con identidad de sesión.
