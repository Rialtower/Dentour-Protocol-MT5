# Seguridad y datos sensibles

## Secretos

No versionar:

- login y contraseña MT5;
- servidor real;
- `.env`;
- tokens;
- credenciales personales.

## HTML

Jinja2 escapa variables de forma predeterminada. `|safe` solo debe aplicarse a HTML interno generado de forma controlada.

## SQL

Usar parámetros y no concatenar valores del usuario.

## Datos del broker

Revisar términos antes de publicar históricos. Los Parquet no deben formar parte del repositorio.

## Modelos

No activar un modelo sin metadatos, métricas, esquema y procedencia temporal.
