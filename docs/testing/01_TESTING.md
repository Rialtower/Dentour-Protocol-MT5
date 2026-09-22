# Estrategia de pruebas de Dentour Protocol MT5

## 1. Propósito

La suite de pruebas de **Dentour Protocol MT5 (DPMT5)** tiene como objetivo comprobar que los contratos técnicos, temporales y cuantitativos del proyecto continúen funcionando después de correcciones, refactorizaciones o nuevas implementaciones.

La suite no pretende demostrar que un modelo financiero sea rentable ni que un patrón histórico continúe en el futuro. Las pruebas verifican principalmente que:

- el código pueda importarse y ejecutarse;
- los módulos respeten sus responsabilidades;
- los datos cumplan los esquemas esperados;
- las sesiones se calculen correctamente;
- las features no utilicen información futura;
- los targets respeten el horizonte y la sesión;
- el dataset separe correctamente X e y;
- la validación conserve el orden temporal;
- el modelo y el baseline evalúen las mismas observaciones;
- las rutas web principales respondan correctamente;
- los errores produzcan diagnósticos localizables.

La filosofía principal es:

```text
Un fallo debe indicar qué contrato se rompió,
en qué módulo ocurrió y cuál fue la excepción real.
```

---

## 2. Alcance

La estrategia cubre cuatro niveles:

```text
Pruebas unitarias
Pruebas de integración sintética
Pruebas de humo
Pruebas de integración con datos reales
```

Cada nivel responde una pregunta diferente.

### Pruebas unitarias

Comprueban funciones o contratos aislados con entradas pequeñas y controladas.

Ejemplos:

- duración de una sesión;
- asignación de `session_date`;
- rechazo de umbrales ATR desordenados;
- detección de timestamps duplicados;
- protección contra data leakage;
- separación cronológica de train, validation y test.

### Integración sintética

Ejecuta varios módulos consecutivos con datos deterministas generados en memoria.

```text
M1, M15 y H1 sintéticos
→ features
→ targets
→ dataset
→ baselines
```

No necesita MetaTrader 5 ni archivos Parquet.

### Pruebas de humo

Comprueban rápidamente que la aplicación sea importable y que sus componentes principales estén disponibles.

Ejemplos:

- archivos requeridos;
- imports;
- plantilla Jinja2;
- rutas FastAPI;
- OpenAPI.

### Integración con datos reales

Ejecuta el pipeline contra el Data Lake real de agosto de 2026.

Estas pruebas están deshabilitadas por defecto porque:

- leen Parquet reales;
- consumen más memoria;
- tardan más;
- dependen de la configuración local;
- pueden fallar si el Data Lake no está disponible.

---

## 3. Estructura recomendada

```text
Dentour Protocol MT5/
├── run_tests.py
├── reports/
│   └── .gitkeep
├── tests/
│   ├── __init__.py
│   ├── helpers.py
│   ├── unit/
│   │   ├── __init__.py
│   │   ├── test_sessions.py
│   │   ├── test_contracts.py
│   │   ├── test_data_access_validation.py
│   │   ├── test_dataset_leakage.py
│   │   └── test_validation_models_evaluation.py
│   ├── integration/
│   │   ├── __init__.py
│   │   ├── test_research_pipeline_synthetic.py
│   │   └── test_august_2026_real_data.py
│   └── smoke/
│       ├── __init__.py
│       └── test_structure_imports_web.py
└── docs/
    └── TESTING.md
```

---

## 4. Convenciones de nombres

Todos los archivos deben comenzar con:

```text
test_
```

Ejemplos:

```text
test_sessions.py
test_contracts.py
test_research_pipeline_synthetic.py
```

Los métodos también deben comenzar con:

```text
test_
```

Ejemplo:

```python
def test_custom_session_crosses_midnight(self) -> None:
    ...
```

La convención permite que `unittest` descubra las pruebas automáticamente.

Los nombres deben describir comportamiento, no implementación interna.

Preferible:

```python
test_target_horizon_stays_inside_session
```

Evitar:

```python
test_function_3
```

---

## 5. Ejecutor principal

El archivo `run_tests.py` es el punto de entrada recomendado.

Responsabilidades:

1. Descubrir todos los archivos `test_*.py`.
2. Ejecutar la suite.
3. Medir duración total e individual.
4. Capturar PASS, FAIL, ERROR y SKIP.
5. Registrar versiones del entorno.
6. Guardar tracebacks completos.
7. Generar reportes TXT y JSON.
8. Retornar código de salida `0` o `1`.

Ejecución:

```powershell
python run_tests.py
```

Código de salida:

```text
0 = todas las pruebas ejecutadas finalizaron correctamente
1 = existe al menos un FAIL o ERROR
```

Esto permite integrar la suite con GitHub Actions u otros sistemas de automatización.

---

## 6. Estados posibles

### PASS

La prueba se ejecutó y el contrato esperado se cumplió.

Ejemplo:

```text
08:15 COT produce minute_of_session = 495
```

PASS no significa que todo el proyecto esté libre de errores. Solo confirma el escenario cubierto por esa prueba.

### FAIL

La prueba terminó, pero una aserción no se cumplió.

Ejemplo:

```text
Esperado: 495
Recibido: -17
```

Un FAIL suele indicar:

- regresión;
- resultado diferente al contrato;
- valor incorrecto;
- estructura inesperada.

### ERROR

Una excepción impidió completar la prueba.

Ejemplos:

```text
ModuleNotFoundError
TemplateNotFound
ParserException
ColumnNotFoundError
FileNotFoundError
```

Un ERROR suele indicar que la prueba no llegó a la aserción principal.

### SKIP

La prueba fue omitida deliberadamente.

Ejemplo:

```text
Integración real deshabilitada.
```

SKIP no representa un fallo.

---

## 7. Fixtures sintéticos

El archivo `tests/helpers.py` genera datos deterministas.

### Por qué no usar datos aleatorios

Los datos aleatorios pueden producir resultados diferentes entre ejecuciones y dificultar la reproducción de fallos.

Las fixtures sintéticas utilizan funciones deterministas:

```text
tendencia pequeña
+ oscilaciones periódicas
+ volumen entero controlado
```

### `make_bar_frame()`

Construye un DataFrame OHLCV con:

```text
timestamp_utc
timestamp_cot
open
high
low
close
volume
spread
real_volume
```

Garantiza inicialmente:

- orden temporal;
- ausencia de duplicados;
- `high >= open`;
- `high >= close`;
- `low <= open`;
- `low <= close`;
- volumen positivo.

### `make_market_context()`

Genera:

```text
M1
M15
H1
```

Se inicia antes del periodo analítico para proporcionar warmup suficiente a:

- ATR;
- volatilidad;
- volumen relativo;
- contexto H1.

### `make_binary_model_frame()`

Genera un dataset pequeño con:

- tres features numéricas;
- un target binario;
- identificadores;
- timestamps;
- session_date;
- horizonte futuro.

Permite probar modelos y evaluación sin utilizar resultados reales.

---

# 8. Pruebas unitarias

## 8.1 Sesiones

Archivo:

```text
tests/unit/test_sessions.py
```

Valida:

- presets disponibles;
- duración positiva;
- full day de 1,440 minutos;
- sesión personalizada;
- cruce de medianoche;
- rechazo de código desconocido;
- rechazo de inicio igual a fin;
- asignación de session_date;
- cálculo de minute_of_session;
- session_progress;
- prevención del overflow entero.

### Caso histórico protegido

Durante el desarrollo, una operación con enteros pequeños produjo:

```text
08:15 → -17
```

La prueba exige:

```text
08:15 → 495
```

Si el error reaparece, la suite lo detectará inmediatamente.

---

## 8.2 Contratos de Research

Archivo:

```text
tests/unit/test_contracts.py
```

Valida:

```text
observation_timeframe = M15
path_timeframe = M1
horizon_minutes = 60
horizon_observation_bars = 4
session predeterminada = new_york
scope = single_session
```

También verifica:

- ATR mínimo;
- umbrales positivos;
- umbrales ordenados;
- ausencia de duplicados;
- sesión custom inyectada explícitamente;
- configuración inicial de ocho meses.

---

## 8.3 Calidad histórica

Archivo:

```text
tests/unit/test_data_access_validation.py
```

Valida:

- periodo semiabierto;
- conversión COT a UTC;
- rechazo de periodo vacío;
- orden temporal;
- unicidad de timestamps;
- columnas obligatorias;
- consistencia OHLC.

Un ejemplo de OHLC inválido es:

```text
high < open
```

El DataFrame debe rechazarse antes de construir features.

---

## 8.4 Protección contra data leakage

Archivo:

```text
tests/unit/test_dataset_leakage.py
```

Comprueba que las columnas futuras no puedan declararse como features.

Columnas prohibidas:

```text
mfe_atr
future_high
target_peak_075_atr
triple_barrier_label
```

La prueba también rechaza features duplicadas.

Esta capa es crítica porque un modelo con leakage puede aparentar una precisión irreal.

---

## 8.5 Validación, modelo y evaluación

Archivo:

```text
tests/unit/test_validation_models_evaluation.py
```

Valida:

- días separados entre bloques;
- purga de horizontes solapados;
- orden de meses walk-forward;
- selección de regularización;
- generación de probabilidades;
- baseline calculado desde train;
- modelo y baseline sobre los mismos IDs;
- tabla de coeficientes;
- calibración;
- análisis de umbrales.

---

# 9. Integración sintética

Archivo:

```text
tests/integration/test_research_pipeline_synthetic.py
```

Ejecuta:

```text
M1/M15/H1
→ build_m15_feature_frame
→ build_peak_targets
→ build_research_dataset
→ build_baseline_report
→ combine_research_datasets
```

Sesiones cubiertas:

```text
Asia
Londres
Nueva York
```

Contratos comprobados:

- las aperturas pertenecen a la sesión;
- el horizonte termina dentro de la sesión;
- los targets ATR son monotónicos;
- el dataset no contiene IDs duplicados;
- MFE no entra dentro de features;
- los baselines no quedan vacíos;
- los esquemas son compatibles al combinar sesiones.

---

# 10. Integración con agosto real

Archivo:

```text
tests/integration/test_august_2026_real_data.py
```

Está deshabilitado por defecto.

Activación:

```powershell
$env:DPMT5_RUN_REAL_DATA_TESTS="1"
python run_tests.py
```

Desactivación posterior:

```powershell
Remove-Item Env:DPMT5_RUN_REAL_DATA_TESTS
```

Valida:

- carga M1;
- carga M15;
- carga H1;
- Asia;
- Londres;
- Nueva York;
- features no vacías;
- targets no vacíos;
- dataset no vacío;
- IDs únicos.

### Requisitos

- `DATA_LAKE_DIR` correcto;
- agosto de 2026 disponible;
- estructura Hive válida;
- dependencias instaladas.

---

# 11. Pruebas de humo

Archivo:

```text
tests/smoke/test_structure_imports_web.py
```

## Estructura

Comprueba archivos requeridos:

```text
app.py
ingest.py
warroom.py
sessions.py
research/api.py
research/contracts.py
research/data_access.py
research/features.py
research/targets.py
research/dataset.py
research/baselines.py
research/validation.py
research/models.py
research/evaluation.py
research/templates/research_home.html
```

## Imports

Importa cada módulo para detectar:

- dependencias faltantes;
- importaciones circulares;
- errores ejecutados durante import;
- nombres incorrectos.

## Plantilla Jinja2

Comprueba que `research_home.html`:

- exista;
- no esté vacío;
- contenga `Research Lab`;
- contenga `session_code`.

Esto protege contra los errores previos:

```text
TemplateNotFound
página HTML vacía
```

## FastAPI

Comprueba:

```text
GET /
GET /research/
GET /openapi.json
```

Además verifica que OpenAPI registre:

```text
/research/
/research/analyze
```

---

# 12. Ejecución

## Suite rápida

```powershell
.\.venv\Scripts\Activate.ps1
python run_tests.py
```

## Solo una capa

### Sesiones

```powershell
python -m unittest tests.unit.test_sessions -v
```

### Contratos

```powershell
python -m unittest tests.unit.test_contracts -v
```

### Pipeline sintético

```powershell
python -m unittest tests.integration.test_research_pipeline_synthetic -v
```

### Web

```powershell
python -m unittest tests.smoke.test_structure_imports_web -v
```

### Agosto real

```powershell
$env:DPMT5_RUN_REAL_DATA_TESTS="1"
python -m unittest tests.integration.test_august_2026_real_data -v
```

---

# 13. Reportes

Cada ejecución crea:

```text
reports/dpmt5_test_report_YYYYMMDD_HHMMSS.txt
reports/dpmt5_test_report_YYYYMMDD_HHMMSS.json
```

## TXT

Pensado para revisión manual.

Contiene:

- fecha;
- intérprete;
- versión de Python;
- plataforma;
- Data Lake;
- dependencias;
- resumen;
- salida unittest;
- detalle por prueba;
- traceback.

## JSON

Pensado para automatización.

Ejemplo conceptual:

```json
{
  "summary": {
    "tests_run": 24,
    "passed": 22,
    "failed": 1,
    "errors": 0,
    "skipped": 1,
    "successful": false
  },
  "records": []
}
```

El JSON puede alimentar posteriormente:

- GitHub Actions;
- una ruta administrativa;
- un dashboard de calidad;
- comparación entre commits.

---

# 14. Cómo leer un fallo

## Paso 1. Revisar resumen

```text
PASS: 20
FAIL: 1
ERROR: 1
SKIP: 1
```

## Paso 2. Localizar el test

Ejemplo:

```text
test_minute_calculation_does_not_overflow
```

## Paso 3. Leer detalle

```text
AssertionError: -17 != 495
```

## Paso 4. Leer traceback

El traceback muestra:

- archivo;
- línea de prueba;
- función productiva involucrada;
- excepción final.

## Paso 5. Corregir causa raíz

No se debe modificar la prueba solo para que pase si la prueba representa un contrato válido.

## Paso 6. Ejecutar selectivamente

```powershell
python -m unittest tests.unit.test_sessions.SessionWindowTests.test_minute_calculation_does_not_overflow -v
```

## Paso 7. Ejecutar suite completa

Después del parche:

```powershell
python run_tests.py
```

---

# 15. Cuándo modificar una prueba

Modificar una prueba es correcto cuando:

- el contrato cambió deliberadamente;
- la prueba usa una API eliminada de forma consciente;
- la expectativa anterior estaba equivocada;
- se agregó una nueva versión documentada.

No debe modificarse para ocultar:

- una regresión;
- data leakage;
- timestamps incorrectos;
- un error de esquema;
- un resultado inesperado legítimo.

Si cambia un contrato, deben actualizarse juntos:

```text
código
pruebas
documentación
versiones del experimento
```

---

# 16. Datos reales y sintéticos

## Sintéticos

Ventajas:

- rápidos;
- repetibles;
- independientes del broker;
- permiten resultados esperados.

Limitaciones:

- no reproducen microestructura real;
- no validan peculiaridades del broker;
- no demuestran utilidad estadística.

## Reales

Ventajas:

- validan esquemas reales;
- muestran gaps y fronteras;
- prueban memoria y cobertura;
- detectan peculiaridades del símbolo.

Limitaciones:

- requieren Data Lake;
- consumen más recursos;
- pueden depender del entorno local;
- no deben publicarse automáticamente.

Ambos niveles son necesarios y no se sustituyen entre sí.

---

# 17. Incorporación de nuevas pruebas

Toda corrección importante debe añadir una prueba de regresión.

Ejemplos históricos:

### Comentarios Python dentro de SQL

Agregar una prueba sobre la función responsable o una consulta mínima reproducible.

### Overflow de minutos

Conservar `08:15 → 495`.

### Plantilla inexistente

Comprobar ruta y contenido mínimo.

### Duplicados idénticos

Probar consolidación segura.

### Duplicados conflictivos

Probar rechazo obligatorio.

### Horizon outside session

Asegurar exclusión de 09:15 en Nueva York con horizonte de 60 minutos.

### Triple barrera ambigua

Crear una trayectoria M1 cuyo high y low toquen ambas barreras en la misma barra.

---

# 18. GitHub

Versionar:

```text
tests/
run_tests.py
docs/TESTING.md
reports/.gitkeep
```

Ignorar:

```gitignore
reports/*.txt
reports/*.json
!reports/.gitkeep
```

No versionar fixtures derivados de datos reales del broker sin revisar sus condiciones.

---

# 19. Integración continua futura

Una ejecución básica en CI podrá hacer:

```text
instalar dependencias
compilar módulos
ejecutar pruebas rápidas
publicar reporte
bloquear merge si hay FAIL o ERROR
```

La integración real con Parquet no debe formar parte obligatoria de CI público porque el Data Lake no se versiona.

Las pruebas sintéticas y de humo deben ser la base de cada commit.

---

# 20. Matriz de cobertura

| Área | Unitarias | Sintéticas | Reales | Web |
|---|---:|---:|---:|---:|
| Sesiones | Sí | Sí | Sí | Sí |
| Contratos Research | Sí | Sí | Sí | No |
| Data access | Sí | Parcial | Sí | Indirecto |
| Features | Indirecto | Sí | Sí | Indirecto |
| Targets | Indirecto | Sí | Sí | Indirecto |
| Dataset | Sí | Sí | Sí | Indirecto |
| Baselines | Indirecto | Sí | Pendiente ampliación | Indirecto |
| Validation | Sí | Sí | Pendiente multimensual | No |
| Models | Sí | Sí | Pendiente | No |
| Evaluation | Sí | Sí | Pendiente | No |
| Jinja2 | No | No | No | Sí |
| FastAPI | No | No | No | Sí |
| Ingesta MT5 | Pendiente con mocks | No | Manual | Indirecto |
| War Room | Pendiente | Pendiente | Pendiente | Humo futuro |

---

# 21. Cobertura pendiente

La suite debe ampliar gradualmente:

- MetaTrader 5 simulado mediante mocks;
- escritura atómica de Parquet;
- locks;
- reconciliación de duplicados idénticos;
- duplicados conflictivos;
- cálculos VWAP y CVD de `app.py`;
- Opening Range;
- barridos;
- War Room mensual;
- rutas de error;
- sesión personalizada nocturna en Research;
- múltiples meses sintéticos;
- walk-forward repetido;
- calibración conocida;
- selección de umbral solo con validation.

---

# 22. Criterio de aprobación

Una versión de DPMT5 puede considerarse técnicamente estable para continuar desarrollo cuando:

```text
la compilación termina sin errores;
las pruebas rápidas no presentan FAIL ni ERROR;
los SKIP están documentados;
la integración real pasa cuando corresponde;
los reportes se conservan durante la revisión;
los cambios de contrato incluyen documentación;
no existen secretos o datos reales en los artefactos.
```

Esto no implica que los modelos sean predictivamente consistentes. La estabilidad de ingeniería y la consistencia cuantitativa son evaluaciones diferentes.

---

## Conclusión

La suite de pruebas de DPMT5 protege el sistema contra regresiones técnicas, errores temporales y fugas de información. La prioridad no es maximizar la cantidad de pruebas, sino cubrir contratos críticos con escenarios reproducibles y mensajes claros.

La pregunta que debe responder cada prueba es:

```text
¿Qué comportamiento esencial dejaría de ser confiable
si esta prueba fallara?
```

Cuando esa pregunta tiene una respuesta clara, la prueba aporta valor real al proyecto.
