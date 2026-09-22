# Documentación técnica de Dentour Protocol MT5

Esta carpeta contiene la documentación operativa, arquitectónica y académica de **Dentour Protocol MT5 (DPMT5)**.

DPMT5 es una plataforma local que integra ingeniería de datos de mercado, análisis descriptivo e investigación cuantitativa sobre información obtenida desde MetaTrader 5. La documentación describe el sistema tal como está diseñado actualmente y evita presentar resultados experimentales como señales o garantías financieras.

## Mapa de documentación

### Introducción y arquitectura

- [Visión general](architecture/01_vision_general.md)
- [Arquitectura del sistema](architecture/02_arquitectura_sistema.md)
- [Contratos temporales](architecture/03_contratos_temporales.md)
- [Flujo de datos](architecture/04_flujo_datos.md)
- [Decisiones arquitectónicas](architecture/05_decisiones_arquitectonicas.md)

### Instalación y operación

- [Instalación y entorno](guides/01_instalacion_entorno.md)
- [Configuración](guides/02_configuracion.md)
- [Ejecución local](guides/03_ejecucion_local.md)
- [Flujo de trabajo del aprendiz](guides/04_flujo_aprendiz.md)
- [Publicación en GitHub](guides/05_publicacion_github.md)

### Módulos productivos

- [Ingesta y MetaTrader 5](modules/01_ingest.md)
- [Dashboard diario](modules/02_app_dashboard.md)
- [Sesiones dinámicas](modules/03_sessions.md)
- [War Room](modules/04_warroom.md)
- [Interfaz Research](modules/05_research_api.md)

### Research Lab

- [Introducción a Research](research/01_introduccion.md)
- [Contratos del experimento](research/02_contracts.md)
- [Acceso histórico](research/03_data_access.md)
- [Features causales](research/04_features.md)
- [Targets futuros](research/05_targets.md)
- [Dataset final](research/06_dataset.md)
- [Baselines](research/07_baselines.md)
- [Validación temporal](research/08_validation.md)
- [Modelos](research/09_models.md)
- [Evaluación](research/10_evaluation.md)
- [Glosario cuantitativo](research/11_glosario_cuantitativo.md)

### Referencia

- [Esquemas de datos](reference/01_esquemas_datos.md)
- [Dependencias](reference/02_dependencias.md)
- [Rutas web](reference/03_rutas_web.md)
- [Convenciones de código](reference/04_convenciones_codigo.md)
- [Glosario técnico](reference/05_glosario_tecnico.md)

### Operación y mantenimiento

- [Solución de problemas](operations/01_solucion_problemas.md)
- [Rendimiento y memoria](operations/02_rendimiento_memoria.md)
- [Seguridad y datos sensibles](operations/03_seguridad.md)
- [Backups y recuperación](operations/04_backups_recuperacion.md)
- [Estado actual y roadmap](operations/05_estado_roadmap.md)

## Alcance

Esta documentación cubre:

- adquisición desde MetaTrader 5;
- Data Lake Parquet;
- consultas DuckDB;
- transformaciones Polars;
- dashboard FastAPI;
- sesiones dinámicas;
- War Room mensual;
- Research Lab;
- baselines, validación, modelos y evaluación.

La documentación de la suite automatizada de pruebas se mantiene por separado y no forma parte de esta carpeta.

## Advertencia

DPMT5 es un proyecto educativo e investigativo. No ejecuta operaciones, no administra capital, no garantiza rentabilidad y no constituye asesoría financiera.
