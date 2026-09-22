# Modelos experimentales

## Archivo

`research/models.py`

## Primer modelo

```text
StandardScaler
+
LogisticRegression L2
```

## Target predeterminado

```text
target_peak_075_atr
```

## Regularización

Validation compara valores de `C`. Test no participa en la selección.

## Salida

El modelo produce probabilidades entre cero y uno.

## Restricciones

- no usar timestamps;
- no usar targets como features;
- no entrenar en HTTP;
- no interpretar coeficientes como causalidad;
- no guardar un modelo activo sin evaluación multimensual.
