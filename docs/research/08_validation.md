# Validación temporal

## Archivo

`research/validation.py`

## Bloques

- train aprende;
- validation selecciona configuración;
- test evalúa una sola vez.

## Purga

Elimina filas cuyo horizonte futuro invade el siguiente bloque.

## Embargo

Introduce una separación temporal adicional alrededor de la frontera.

## Walk-forward

Configuración inicial:

```text
6 meses train
1 mes validation
1 mes test
```

## División provisional

Con un solo mes puede dividirse por días completos para probar el pipeline. No constituye evidencia multimensual.
