# Instalación y entorno

## Requisitos

- Windows 64 bits.
- Python 3.14 compatible con las versiones fijadas.
- MetaTrader 5 instalado.
- Terminal MT5 configurada.
- Acceso a históricos del símbolo.

## Crear entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la activación:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

## Instalar dependencias

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

## Dependencias clave

- FastAPI y Uvicorn.
- DuckDB, Polars, Pandas y PyArrow.
- Plotly y Jinja2.
- NumPy y scikit-learn.
- MetaTrader5.

## Verificar intérprete

```powershell
python -c "import sys; print(sys.executable)"
```

Debe apuntar a `.venv\Scripts\python.exe`.

## Verificar imports

```powershell
python -c "import fastapi, duckdb, polars, pandas, pyarrow, plotly, jinja2, sklearn, numpy, MetaTrader5; print('DPMT5 OK')"
```
