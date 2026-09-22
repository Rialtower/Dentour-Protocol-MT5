# Dentour Protocol MT5

<p align="center">
  <img src="https://img.shields.io/badge/estado-en%20desarrollo-informational?style=flat-square" alt="Estado: en desarrollo">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-009688?style=flat-square&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/DuckDB-FFF000?style=flat-square&logo=duckdb&logoColor=black" alt="DuckDB">
  <img src="https://img.shields.io/badge/Polars-CD792C?style=flat-square&logo=polars&logoColor=white" alt="Polars">
  <img src="https://img.shields.io/badge/scikit--learn-F7931E?style=flat-square&logo=scikitlearn&logoColor=white" alt="scikit-learn">
</p>

**Dentour Protocol MT5**, abreviado **DPMT5**, es una plataforma local de ingeniería de datos, análisis de mercado e investigación cuantitativa construida alrededor de MetaTrader 5.

El proyecto transforma información histórica de mercado en un flujo reproducible y auditable: extrae datos desde MetaTrader 5, los organiza en un Data Lake basado en Parquet, ejecuta análisis diarios y mensuales, y construye experimentos probabilísticos orientados al estudio de expansiones futuras.

> **Aviso importante:** DPMT5 es un proyecto exclusivamente educativo e investigativo. No ejecuta operaciones, no administra capital, no garantiza resultados y no debe interpretarse como asesoría financiera ni como un sistema de señales.

---

## Índice

- [Visión del proyecto](#visión-del-proyecto)
- [Objetivos](#objetivos)
- [Principios de diseño](#principios-de-diseño)
- [Arquitectura general](#arquitectura-general)
- [Tecnologías principales](#tecnologías-principales)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Data Lake](#data-lake)
- [Módulos principales](#módulos-principales)
- [Sesiones dinámicas](#sesiones-dinámicas)
- [Research Lab](#research-lab)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Ejecución](#ejecución)
- [Validación sintáctica](#validación-sintáctica)
- [Flujo de trabajo académico](#flujo-de-trabajo-académico)
- [Estado actual](#estado-actual)
- [Limitaciones actuales](#limitaciones-actuales)
- [Seguridad y publicación](#seguridad-y-publicación)
- [Roadmap](#roadmap)
- [Filosofía final](#filosofía-final)

---

## Visión del proyecto

La esencia de DPMT5 es separar correctamente cuatro responsabilidades:

```text
Adquisición de datos
        ↓
Análisis descriptivo
        ↓
Investigación probabilística
        ↓
Evaluación temporal y estadística
```

El proyecto no comienza preguntando si el mercado debe comprarse o venderse. Comienza con preguntas medibles:

- ¿Qué ocurrió históricamente dentro de una sesión determinada?
- ¿Cómo se comportaron el precio, el volumen, la volatilidad y el VWAP?
- ¿Qué expansión máxima apareció durante un horizonte futuro definido?
- ¿Cuánto retroceso ocurrió antes de esa expansión?
- ¿Cuánto tiempo tardó en aparecer el máximo?
- ¿Las relaciones observadas se mantienen en periodos que el modelo no utilizó para aprender?
- ¿Un modelo probabilístico supera referencias estadísticas simples?

DPMT5 prioriza la trazabilidad, la separación temporal y la honestidad estadística por encima de resultados visualmente atractivos.

---

## Objetivos

### Objetivo general

Construir una plataforma local capaz de convertir datos históricos de MetaTrader 5 en análisis reproducibles y experimentos cuantitativos auditables.

### Objetivos específicos

- Extraer barras M1, M15, H1 y ticks desde MetaTrader 5.
- Convertir fechas operativas de Colombia en intervalos UTC consistentes.
- Persistir información original en archivos Parquet comprimidos.
- Mantener un Data Lake como única fuente de verdad.
- Ejecutar análisis intradiarios desde una interfaz FastAPI.
- Comparar sesiones de Asia, Londres y Nueva York.
- Analizar meses cerrados mediante War Room.
- Construir features causales sin información futura.
- Construir targets históricos como MFE, MAE y triple barrera.
- Crear datasets separados por sesión y versionados.
- Comparar modelos experimentales contra baselines simples.
- Validar cronológicamente mediante train, validation, test, purga, embargo y walk-forward.
- Documentar tanto los resultados positivos como los negativos.

---

## Principios de diseño

### 1. El Data Lake es la fuente de verdad

Los archivos Parquet originales representan el registro histórico base. Los módulos analíticos consultan ese origen y no mantienen copias redundantes dentro de `research/`.

### 2. UTC para almacenamiento, COT para operación

Los timestamps se almacenan y procesan internamente en UTC. El calendario operativo utiliza `America/Bogota`.

La zona `Europe/Athens` se utiliza para representar la configuración horaria del servidor del broker cuando es necesario contrastarla.

### 3. Intervalos semiabiertos

DPMT5 utiliza la convención:

```text
[inicio, fin)
```

El inicio se incluye y el final se excluye. Esta regla evita duplicar barras en fronteras diarias y mantiene consultas temporales consistentes.

### 4. Disponibilidad temporal explícita

MetaTrader 5 identifica normalmente una barra por su hora de apertura. DPMT5 distingue entre el momento de apertura y el momento en que la barra está completamente cerrada.

```text
M1  disponible en timestamp + 1 minuto
M15 disponible en timestamp + 15 minutos
H1  disponible en timestamp + 60 minutos
```

Esta separación es esencial para evitar `look-ahead bias` y `data leakage`.

### 5. Separación de responsabilidades

- `ingest.py` adquiere y persiste datos.
- `app.py` analiza una jornada o sesión.
- `warroom.py` analiza meses cerrados.
- `research/` construye y evalúa experimentos cuantitativos.
- El entrenamiento no se ejecuta dentro de solicitudes HTTP normales.
- Una futura inferencia utilizará modelos previamente evaluados y congelados.

### 6. Baselines antes que complejidad

Un modelo solo aporta valor si supera referencias simples fuera de muestra. Antes de usar algoritmos avanzados, DPMT5 calcula frecuencias históricas globales, por sesión, por horario y por régimen de volatilidad.

### 7. Resultados negativos también son resultados

El proyecto conserva fallos, exclusiones, meses desfavorables y configuraciones que no superan al baseline. No se seleccionan únicamente los resultados visualmente positivos.

---

## Arquitectura general

```text
MetaTrader 5
      │
      ▼
ingest.py
      │
      ▼
Data Lake Parquet
      │
      ├─────────────────────┐
      │                     │
      ▼                     ▼
app.py                 warroom.py
Análisis diario        Análisis mensual
      │
      └──────────────┐
                     ▼
                 research/
                     │
                     ├── data_access.py
                     ├── features.py
                     ├── targets.py
                     ├── dataset.py
                     ├── baselines.py
                     ├── validation.py
                     ├── models.py
                     └── evaluation.py
```

---

## Tecnologías principales

| Tecnología | Responsabilidad |
|---|---|
| Python | Lenguaje principal |
| MetaTrader5 | Frontera de adquisición del terminal MT5 |
| FastAPI | Aplicación web y API local |
| Uvicorn | Servidor ASGI |
| DuckDB | Consulta y reducción directa sobre Parquet |
| Polars | Transformaciones columnares y cálculos analíticos |
| Pandas | Normalización inicial y tablas pequeñas para HTML |
| PyArrow | Esquemas y persistencia Parquet |
| Plotly | Visualizaciones interactivas |
| Jinja2 | Plantillas HTML dinámicas |
| scikit-learn | Modelos y métricas experimentales |
| NumPy | Cálculos numéricos y arrays |

---

## Estructura del repositorio

```text
Dentour-Protocol-MT5/
├── app.py
├── ingest.py
├── warroom.py
├── sessions.py
├── requirements.txt
├── README.md
├── .gitignore
├── .env.example
├── static/
│   └── favicon.ico
├── research/
│   ├── __init__.py
│   ├── api.py
│   ├── contracts.py
│   ├── data_access.py
│   ├── features.py
│   ├── targets.py
│   ├── dataset.py
│   ├── baselines.py
│   ├── validation.py
│   ├── models.py
│   ├── evaluation.py
│   └── templates/
│       └── research_home.html
├── tests/
│   └── research/
└── data_lake/              # No se versiona en Git
```

---

## Data Lake

Los datos se organizan mediante particiones Hive:

```text
data_lake/
├── m1/
│   └── year=2026/
│       └── month=08/
│           └── day=03/
├── m15/
├── h1/
└── ticks/
```

Cada archivo conserva datos originales normalizados y comprimidos con ZSTD.

El Data Lake no debe subirse al repositorio. Puede contener grandes volúmenes de información y datos sujetos a las condiciones del proveedor o broker.

---

## Módulos principales

### `ingest.py`

Es la única frontera directa con MetaTrader 5.

Responsabilidades:

- Inicializar y cerrar la conexión con MT5.
- Descargar barras y ticks.
- Convertir fechas COT a intervalos UTC.
- Normalizar columnas con Pandas.
- Aplicar esquemas explícitos de PyArrow.
- Filtrar estrictamente mediante `[inicio, fin)`.
- Escribir Parquet de forma atómica.
- Comprimir mediante ZSTD.
- Auditar filas, esquema y estadísticas.
- Utilizar locks para evitar ejecuciones concurrentes incompatibles.
- Cerrar MT5 mediante `finally`.

Los módulos analíticos no deben conectarse directamente con MetaTrader 5.

---

### `app.py`

Es la aplicación FastAPI principal y el dashboard intradiario.

Incluye análisis de:

- Precio y velas.
- VWAP y desviaciones.
- CVD aproximado a partir de ticks.
- Confluencia M1, M15 y H1.
- Clusters de volumen.
- Opening Range.
- Barridos de liquidez.
- Conversión entre horario COT y horario del broker.

También permite seleccionar sesiones dinámicas:

```text
Asia
Londres
Nueva York
Día completo
Personalizada
```

Los cálculos reciben un `SessionWindow` compartido. Las sesiones pueden cruzar medianoche.

---

### `warroom.py`

War Room es el módulo descriptivo mensual.

Características:

- Solo acepta meses calendario cerrados.
- Consulta directamente archivos Parquet.
- Calcula resultados `on-the-fly`.
- Evita vistas materializadas y redundancia analítica.
- Utiliza M1 como proxy para Composite Volume Profile.
- Calcula AVWAP mensual y semanal.
- Analiza CVD, ATR y expansión.
- Identifica niveles PMH, PML, PWH y PWL.
- Estudia barridos y contexto de liquidez.
- Filtra y agrega con DuckDB antes de transferir grandes resultados a Polars.

War Room describe el pasado. No produce predicciones.

---

## Sesiones dinámicas

El archivo `sessions.py` centraliza las ventanas horarias utilizadas por `app.py`, `warroom.py` y `research/`.

Cada sesión contiene:

```text
code
name
start
end
timezone_name
duration_minutes
crosses_midnight
```

Además, agrega variables como:

```text
session_code
session_date
minute_of_session
session_progress
```

Una sesión nocturna como `22:00-02:00` conserva como `session_date` el día en que comenzó la sesión, incluso para observaciones posteriores a medianoche.

---

## Research Lab

Research Lab es el laboratorio experimental de DPMT5. Su objetivo no es emitir `BUY` o `SELL`, sino estudiar distribuciones futuras condicionadas al estado observable del mercado.

La pregunta inicial es:

> Dado el estado del mercado al cierre confirmado de una barra M15, ¿qué expansión alcista aparece durante los siguientes 60 minutos?

### Experimento inicial

```text
Observación:           cierre confirmado M15
Trayectoria futura:    M1
Contexto:              M1, M15 y H1
Horizonte:             60 minutos
ATR:                   14 periodos
Umbrales:              0.50, 0.75 y 1.00 ATR
Barrera adversa:       0.50 ATR
Modelo inicial:        regresión logística regularizada
```

---

### `research/contracts.py`

Define configuraciones inmutables y versionadas:

- Temporalidades.
- Horizonte.
- ATR.
- Umbrales.
- Política para barras ambiguas.
- Sesión.
- Versiones de features, targets y dataset.
- Configuración train, validation y test.

---

### `research/data_access.py`

Consulta M1, M15 y H1 desde Parquet mediante DuckDB.

Responsabilidades:

- Localizar particiones históricas.
- Filtrar por límites UTC.
- Devolver DataFrames Polars ordenados.
- Validar esquemas y OHLC.
- Detectar timestamps duplicados.
- Consolidar únicamente duplicados idénticos.
- Rechazar duplicados conflictivos.
- Medir filas, tamaño y duración de consulta.

---

### `research/features.py`

Construye variables causales. Ninguna feature puede utilizar información posterior al instante de observación.

Incluye:

- Geometría de velas.
- Retornos de 15, 30 y 60 minutos.
- Volatilidad realizada.
- True Range y ATR.
- Volumen relativo y Z-score.
- VWAP diario.
- VWAP de sesión.
- Distancia a extremos anteriores.
- Barridos previos.
- Variables temporales cíclicas.
- Posición dentro de la sesión.
- Contexto H1 completamente cerrado.

La pertenencia de una barra se determina por su apertura M15. La posición temporal se determina por el cierre confirmado.

---

### `research/targets.py`

Mide qué ocurrió después de cada observación.

Targets principales:

```text
MFE
MAE
MAE previa al máximo
Tiempo hasta el máximo
Tiempo hasta el mínimo
Expansión >= 0.50 ATR
Expansión >= 0.75 ATR
Expansión >= 1.00 ATR
Triple barrera
```

#### MFE

`Maximum Favorable Excursion` representa la máxima expansión favorable dentro del horizonte.

```text
MFE = máximo futuro - precio de referencia
```

#### MAE

`Maximum Adverse Excursion` representa el máximo desplazamiento adverso.

```text
MAE = precio de referencia - mínimo futuro
```

#### Triple barrera

Determina qué evento ocurrió primero:

```text
+1  barrera alcista primero
-1  barrera adversa primero
 0  ninguna antes del vencimiento
```

Una observación puede alcanzar posteriormente `1.00 ATR` y aun tener triple barrera `-1` si la barrera adversa fue tocada primero.

---

### `research/dataset.py`

Formaliza la tabla final de investigación.

Separa estrictamente:

```text
Identificadores
Features X
Targets y
Contexto auditable
Calidad
Versiones
```

También:

- Genera `observation_id` determinista.
- Impide introducir targets como features.
- Comprueba nulos, infinitos y duplicados.
- Verifica monotonía entre umbrales ATR.
- Genera un fingerprint del esquema.
- Permite combinar sesiones compatibles.

---

### `research/baselines.py`

Construye referencias simples que cualquier modelo debe superar.

Incluye frecuencias:

- Globales.
- Por sesión.
- Por minuto de sesión.
- Por día de semana.
- Por régimen ATR.

El baseline constante aprende una frecuencia en train y la aplica a datos posteriores.

Ejemplo:

```text
En train, 62 % de las observaciones alcanzó 0.75 ATR.
Baseline para test: probabilidad constante de 0.62.
```

---

### `research/validation.py`

Implementa validación temporal.

Incluye:

- Train, validation y test cronológicos.
- Walk-forward mensual.
- Ventana expansiva o rodante.
- Purga de targets solapados.
- Embargo temporal.
- División provisional por días cuando solo existe un mes.

Nunca se utiliza división aleatoria para series financieras.

Con un histórico suficiente, el esquema recomendado es:

```text
6 meses train
1 mes validation
1 mes test
```

---

### `research/models.py`

Contiene el primer modelo experimental:

```text
StandardScaler
+
LogisticRegression L2
```

El modelo estima la probabilidad del target:

```text
target_peak_075_atr
```

La regularización `C` se selecciona con validation. Test no participa en el ajuste.

El modelo no utiliza:

- Timestamps como features.
- MFE o MAE como entrada.
- Targets futuros.
- Identificadores.
- Información de test durante el entrenamiento.

---

### `research/evaluation.py`

Evalúa el modelo y el baseline sobre las mismas observaciones.

Métricas:

- Brier score.
- Log loss.
- Average Precision.
- ROC-AUC cuando existen ambas clases.
- Precision.
- Recall.
- F1.
- Matriz de confusión.
- Calibración.
- Resultados por sesión.
- Análisis descriptivo por umbral.

En Brier score y log loss:

```text
menor = mejor
```

Una mejora en un único mes no demuestra consistencia. La consistencia requiere varios meses fuera de muestra.

---

### Interfaz Research

La ruta:

```text
/research/
```

permite seleccionar:

- Año.
- Mes cerrado.
- Sesión.
- Hora inicial y final para sesiones personalizadas.

La interfaz ejecuta:

```text
Carga histórica
→ features
→ targets
→ dataset
→ baselines
→ validación temporal provisional
```

El entrenamiento de modelos está deliberadamente separado de solicitudes HTTP normales. Una futura capa de entrenamiento controlado y registro de modelos manejará artefactos versionados.

---

## Instalación

### Requisitos

- Windows de 64 bits.
- Python 3.14 compatible con las dependencias fijadas.
- MetaTrader 5 instalado.
- Terminal MT5 configurada.
- Datos históricos disponibles en el terminal.

### Crear entorno virtual

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la activación:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### Instalar dependencias

```powershell
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip check
```

### Verificar imports

```powershell
python -c "import fastapi, duckdb, polars, pandas, pyarrow, plotly, jinja2, sklearn, numpy, MetaTrader5; print('Dependencias DPMT5 OK')"
```

---

## Configuración

Crea un archivo `.env` local basado en `.env.example`:

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

No publiques `.env` ni credenciales reales.

---

## Ejecución

```powershell
python -m uvicorn app:app --reload
```

Rutas principales:

```text
http://127.0.0.1:8000/            Dashboard diario
http://127.0.0.1:8000/war-room/   War Room
http://127.0.0.1:8000/research/   Research Lab
http://127.0.0.1:8000/docs        OpenAPI
```

---

## Validación sintáctica

```powershell
python -m py_compile `
    app.py `
    ingest.py `
    warroom.py `
    sessions.py `
    research\api.py `
    research\contracts.py `
    research\data_access.py `
    research\features.py `
    research\targets.py `
    research\dataset.py `
    research\baselines.py `
    research\validation.py `
    research\models.py `
    research\evaluation.py
```

---

## Flujo de trabajo académico

### Fase 1. Adquisición

1. Configurar MetaTrader 5.
2. Ejecutar la ingesta por día.
3. Verificar Parquet M1, M15 y H1.
4. Auditar esquema y cantidad de filas.

### Fase 2. Validación descriptiva

1. Abrir Research Lab.
2. Seleccionar mes y sesión.
3. Revisar carga histórica.
4. Revisar exclusiones.
5. Comparar baselines.

### Fase 3. Experimento provisional

1. Construir train, validation y test por días completos.
2. Entrenar regresión logística.
3. Seleccionar regularización con validation.
4. Evaluar test.
5. Comparar contra baseline.
6. Documentar resultados positivos y negativos.

### Fase 4. Evidencia multimensual

1. Recopilar varios meses completos.
2. Ejecutar walk-forward mensual.
3. Medir cada mes por separado.
4. Evaluar calibración y estabilidad por sesión.
5. Rechazar modelos inestables.

### Fase 5. Modelos congelados

Solo después de demostrar estabilidad razonable se considerará:

- Registro de modelos.
- Persistencia `joblib`.
- Metadatos de entrenamiento.
- Inferencia experimental.
- Monitoreo de drift.
- Abstención ante condiciones desconocidas.

---

## Estado actual

- [x] Ingesta MetaTrader 5
- [x] Data Lake Parquet
- [x] Dashboard diario
- [x] Sesiones dinámicas
- [x] War Room
- [x] Research API
- [x] Features causales
- [x] Targets futuros
- [x] Dataset versionado
- [x] Baselines
- [x] Validación temporal
- [x] Regresión logística
- [x] Evaluación probabilística
- [ ] Pruebas automatizadas completas
- [ ] Walk-forward con varios meses
- [ ] Registro formal de modelos
- [ ] Inferencia experimental
- [ ] Monitoreo de drift

---

## Limitaciones actuales

- Un solo mes no demuestra generalización.
- Las observaciones M15 consecutivas comparten parte del horizonte futuro.
- M1 no resuelve el orden intrabarra cuando ambas barreras se tocan en el mismo minuto.
- El volumen de MetaTrader 5 puede ser tick volume y no volumen centralizado.
- El Composite Volume Profile con M1 es una aproximación.
- Los horarios internacionales pueden requerir tratamiento explícito de DST.
- Los resultados dependen del broker, símbolo, servidor y especificaciones contractuales.
- El modelo inicial solo captura relaciones lineales regularizadas.
- No existe ejecución financiera.

---

## Seguridad y publicación

No deben incluirse en Git:

```text
.env
.venv/
data_lake/
*.parquet
*.duckdb
logs/
backups/
model_registry/
*.joblib
credenciales MT5
```

Antes de publicar:

```powershell
git status
git diff --cached --name-only
git diff --cached
```

Se recomienda comenzar con un repositorio privado.

---

## Roadmap

### Corto plazo

- Estabilizar HTML y CSS.
- Completar pruebas unitarias y de integración.
- Documentar esquemas de datos.
- Mejorar manejo de warmup histórico.
- Ejecutar la primera evaluación provisional de agosto.

### Mediano plazo

- Incorporar varios meses completos.
- Ejecutar walk-forward mensual.
- Comparar modelos separados y combinados por sesión.
- Agregar calibración formal.
- Implementar regresión de cuantiles para MFE.

### Largo plazo

- Registro de modelos.
- Artefactos reproducibles.
- Inferencia experimental.
- Detección fuera de distribución.
- Abstención automática.
- Monitoreo de drift y degradación.
- Comparación controlada de modelos candidatos.

---

## Filosofía final

DPMT5 no busca presentar certeza donde solo existe incertidumbre. El proyecto busca transformar datos históricos en preguntas medibles, experimentos reproducibles y conclusiones limitadas por la evidencia disponible.

La prioridad no es producir una señal visualmente convincente. La prioridad es poder responder:

```text
Qué datos se utilizaron.
Qué información estaba disponible en cada instante.
Qué ocurrió después.
Cómo se separó el pasado del futuro.
Qué baseline debía superarse.
En qué meses funcionó.
En qué meses falló.
Qué tan calibradas estuvieron las probabilidades.
```

Ese enfoque convierte a Dentour Protocol MT5 en un laboratorio de aprendizaje técnico y cuantitativo, no en una promesa de predicción financiera.
