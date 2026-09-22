# Ejecución local

## Iniciar aplicación

```powershell
python -m uvicorn app:app --reload
```

## Rutas

```text
/              Dashboard diario
/war-room/     Análisis mensual
/research/     Research Lab
/docs          OpenAPI
/openapi.json  Esquema OpenAPI
```

## Ejecutar ingesta

La sintaxis exacta depende de la interfaz vigente de `ingest.py`. La ejecución debe realizarse con MT5 abierto y configurado.

## Diagnóstico inicial

Si la aplicación no inicia:

1. leer la última excepción;
2. comprobar el entorno virtual;
3. validar dependencias;
4. compilar el archivo afectado;
5. revisar rutas y plantillas.

## Compilación general

```powershell
python -m py_compile app.py ingest.py warroom.py sessions.py research\api.py research\contracts.py research\data_access.py research\features.py research\targets.py research\dataset.py research\baselines.py research\validation.py research\models.py research\evaluation.py
```
