# Arquitectura del sistema

## Componentes principales

```text
app.py
├── instancia FastAPI
├── dashboard diario
├── navegación
├── routers War Room y Research
└── recursos estáticos

ingest.py
├── conexión MT5
├── extracción
├── normalización
├── esquema Arrow
└── escritura Parquet

warroom.py
└── análisis mensual cerrado

sessions.py
└── contrato horario compartido

research/
├── api.py
├── contracts.py
├── data_access.py
├── features.py
├── targets.py
├── dataset.py
├── baselines.py
├── validation.py
├── models.py
└── evaluation.py
```

## Responsabilidades y fronteras

### `ingest.py`

Es la única frontera con MetaTrader 5. Ningún módulo analítico debe descargar directamente desde el terminal.

### Data Lake

Es la única fuente histórica de verdad. Research no mantiene copias de Parquet dentro de su paquete.

### DuckDB

Lee, filtra, ordena y agrega antes de transferir grandes resultados.

### Polars

Ejecuta transformaciones columnares, features, targets y datasets.

### Pandas

Se limita a normalización puntual y tablas pequeñas para HTML.

### FastAPI

Administra rutas y solicitudes. No debe ejecutar entrenamientos extensos como efecto accidental de actualizar una página.

## Dependencias entre módulos

```text
sessions.py
  ↑        ↑        ↑
app.py  warroom.py  research/

research/contracts.py
      ↓
data_access.py
      ↓
features.py
      ↓
targets.py
      ↓
dataset.py
      ├── baselines.py
      ├── validation.py
      └── models.py
               ↓
          evaluation.py
```

## Principio de dirección única

Los módulos inferiores no deben importar componentes de interfaz. Por ejemplo, `features.py` no debe importar FastAPI ni plantillas HTML.
