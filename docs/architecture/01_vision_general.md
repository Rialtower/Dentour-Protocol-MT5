# Visión general de DPMT5

## Propósito

Dentour Protocol MT5 convierte datos históricos de MetaTrader 5 en información reproducible para análisis y experimentación cuantitativa.

La plataforma se construye alrededor de una pregunta central:

> ¿Cómo transformar datos históricos del broker en observaciones auditables, sin mezclar información futura y sin confundir descripción con predicción?

## Capas del sistema

```text
MetaTrader 5
    ↓
Ingesta y normalización
    ↓
Data Lake Parquet
    ↓
Análisis diario y mensual
    ↓
Research Lab
    ↓
Validación temporal y evaluación
```

## Filosofía

DPMT5 no intenta producir certeza. El sistema busca:

- formular eventos medibles;
- preservar la causalidad temporal;
- comparar modelos contra referencias simples;
- registrar exclusiones y fallos;
- evitar conclusiones basadas en un único periodo;
- mantener separado el análisis de cualquier futura inferencia.

## Dominios funcionales

### Ingesta

Extrae barras y ticks, normaliza columnas, impone esquemas y escribe Parquet.

### Dashboard

Permite analizar una fecha y una sesión mediante gráficos, VWAP, CVD, clusters y contexto multitemporal.

### War Room

Resume un mes calendario cerrado mediante niveles, perfiles y contexto agregado.

### Research Lab

Convierte observaciones históricas en features causales, targets futuros, datasets, baselines y experimentos probabilísticos.

## Limitación conceptual

Un resultado histórico no representa una garantía futura. Una métrica positiva en agosto de 2026 solo describe esa evaluación concreta hasta que otros meses confirmen o contradigan el comportamiento.
