# Evaluación probabilística

## Archivo

`research/evaluation.py`

## Métricas

- Brier score;
- log loss;
- Average Precision;
- ROC-AUC;
- precision;
- recall;
- F1;
- matriz de confusión;
- calibración.

## Comparación

Modelo y baseline deben evaluarse sobre los mismos `observation_id`.

## Brier y log loss

Menor es mejor. Un delta negativo frente al baseline representa mejora en esa evaluación.

## Umbrales

El análisis 0.30-0.70 es descriptivo. El umbral no debe elegirse mirando el test final.

## Consistencia

Se determina comparando varias rondas temporales, sesiones y regímenes. Un único mes no basta.
