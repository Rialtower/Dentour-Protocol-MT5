# Solución de problemas

## `ModuleNotFoundError`

Verificar entorno virtual y usar:

```powershell
python -m pip install -r requirements.txt
```

## `TemplateNotFound`

Confirmar:

```text
research/templates/research_home.html
```

## `ParserException` cerca de `#`

Existe un comentario Python dentro de SQL. Retirarlo o usar sintaxis SQL.

## Timestamps duplicados

Distinguir duplicados idénticos de conflictivos. Los idénticos pueden consolidarse; los conflictivos deben investigarse.

## Data Lake vacío

Verificar `DATA_LAKE_DIR`, particiones y mes solicitado.

## `ColumnNotFound`

Rastrear dónde debía generarse la columna y revisar el orden del pipeline.

## Error Polars

Inspeccionar tipos, zonas horarias, orden y nulos.

## HTTP 404

Comprobar router, prefijo, slash final y registro en `app.py`.

## HTTP 500

Leer la última excepción del traceback. La causa raíz suele estar al final.
