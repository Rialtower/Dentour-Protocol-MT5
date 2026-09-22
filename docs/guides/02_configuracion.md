# Configuración

## Variables de entorno

Se recomienda crear `.env` a partir de `.env.example`.

```env
DATA_LAKE_DIR=./data_lake
DB_PATH=./local_analytics.duckdb
MT5_SYMBOL=XAUUSDm
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
OPERATING_TIMEZONE=America/Bogota
BROKER_TIMEZONE=Europe/Athens
```

## Datos sensibles

No deben publicarse:

- login MT5;
- contraseña;
- servidor real;
- tokens;
- rutas privadas;
- `.env`.

## Rutas

`DATA_LAKE_DIR` debe apuntar a la carpeta que contiene `m1`, `m15`, `h1` y `ticks`.

## Configuración Research

`research/contracts.py` define:

- símbolo;
- horizonte;
- ATR;
- umbrales;
- sesión predeterminada;
- versiones;
- división temporal.

Los cambios en contratos deben versionarse y no aplicarse silenciosamente a experimentos anteriores.
