# Sesiones dinámicas

## Archivo

`sessions.py`

## Contrato

`SessionWindow` contiene:

- `code`;
- `name`;
- `start`;
- `end`;
- `timezone_name`.

## Propiedades

- `is_full_day`;
- `crosses_midnight`;
- `duration_minutes`;
- `label`;
- `bounds()`.

## Presets

```text
Asia        19:00-23:00 COT
Londres     02:00-05:00 COT
Nueva York  07:00-10:00 COT
Día completo
```

## Columnas derivadas

- `session_code`;
- `session_date`;
- `minute_of_session`;
- `session_progress`.

## Sesiones nocturnas

En `22:00-02:00`, una barra de 00:30 pertenece al `session_date` del día anterior.

## DST

Los presets actuales están expresados en COT. Una futura versión puede representar horas locales internacionales y convertirlas por fecha usando zonas IANA.
