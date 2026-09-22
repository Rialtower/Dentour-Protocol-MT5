# Dataset final

## Archivo

`research/dataset.py`

## Separación

```text
Identificadores
Contexto auditable
Features
Targets
Calidad
Versiones
```

## Protección

El módulo rechaza features con prefijos `target_` o `future_`, además de MFE, MAE y triple barrera.

## Identidad

`observation_id` combina símbolo, sesión, timestamp y versión del experimento.

## Fingerprint

El esquema de features y targets genera un hash corto. Datasets incompatibles no deben combinarse.

## Uso

```python
X = dataset.feature_frame()
y = dataset.target_frame("target_peak_075_atr")
```
