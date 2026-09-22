# Publicación en GitHub

## Versionar

- código fuente;
- plantillas;
- documentación;
- requirements;
- pruebas;
- configuración de ejemplo.

## No versionar

```text
.env
.venv/
data_lake/
*.parquet
*.duckdb
logs/
backups/
*.joblib
credenciales
```

## Revisión previa

```powershell
git status
git diff --cached --name-only
git diff --cached
```

## Repositorio privado

Se recomienda iniciar como privado mientras se revisan licencias, secretos y términos de los datos del broker.

## Datos reales

No publicar históricos sin revisar las condiciones del proveedor. Para ejemplos públicos, utilizar fixtures sintéticos claramente identificados.
