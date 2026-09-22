# Baselines

## Propósito

Establecer referencias simples antes de interpretar un modelo.

## Tipos

- global;
- por sesión;
- por minuto de sesión;
- por día de semana;
- por régimen ATR;
- probabilidad constante aprendida en train.

## Regla

El baseline para test se calcula únicamente con train.

## Interpretación

Si el modelo no mejora Brier o log loss frente al baseline fuera de muestra, las features no demostraron valor adicional en esa evaluación.
