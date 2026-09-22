# Introducción a Research Lab

## Objetivo

Research estudia expansiones futuras condicionadas al estado observable del mercado.

## Pregunta inicial

> Al cierre confirmado de una M15, ¿qué expansión alcista aparece durante los siguientes 60 minutos?

## Configuración inicial

```text
Observación: M15 cerrada
Trayectoria: M1
Contexto: M1, M15, H1
Horizonte: 60 minutos
ATR: 14
Umbrales: 0.50, 0.75 y 1.00 ATR
Barrera adversa: 0.50 ATR
```

## Separación conceptual

- Features: presente y pasado.
- Targets: futuro histórico.
- Dataset: contrato entre ambos.
- Baselines: referencia mínima.
- Modelos: aproximación probabilística.
- Evaluación: comparación honesta.
