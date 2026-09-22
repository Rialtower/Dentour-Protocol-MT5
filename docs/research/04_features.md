# Features causales

## Archivo

`research/features.py`

## Regla central

Toda feature debe estar disponible en el instante de observación.

## Grupos

### Vela

- body;
- wick superior e inferior;
- rango;
- dirección;
- close location.

### Retornos y volatilidad

- 15 minutos;
- 30 minutos;
- 60 minutos;
- volatilidad 60 minutos;
- volatilidad 4 horas.

### ATR

True Range y media móvil causal de 14 periodos.

### Volumen

- suma corta;
- media previa;
- desviación previa;
- ratio;
- Z-score.

### VWAP

- diario desde 00:00 COT;
- de sesión desde el inicio de `session_date`.

### Contexto

- extremos anteriores;
- sweeps;
- hora cíclica;
- minuto de sesión;
- progreso de sesión;
- último H1 completamente cerrado.

## Orden de procesamiento

Se calcula historia antes de filtrar la sesión para no reiniciar ATR o retornos artificialmente.
