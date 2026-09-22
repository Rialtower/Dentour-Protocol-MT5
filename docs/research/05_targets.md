# Targets futuros

## Archivo

`research/targets.py`

## Trayectoria

Cada observación utiliza barras M1 en:

```text
[observation_time, observation_time + 60 min)
```

## Targets

- `mfe_points` y `mfe_atr`;
- `mae_points` y `mae_atr`;
- adverse excursion previa al pico;
- tiempo al máximo y mínimo;
- umbrales 0.50, 0.75 y 1.00 ATR;
- triple barrera.

## Exclusiones

- horizonte fuera de sesión;
- horizonte incompleto;
- gap M1;
- ATR inválido;
- barrera ambigua.

## Ambigüedad

Si una barra M1 toca ambas barreras, OHLC no revela el orden intrabarra. La política predeterminada excluye el caso.
