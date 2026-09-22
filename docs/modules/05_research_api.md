# Interfaz web de Research

## Archivos

```text
research/api.py
research/templates/research_home.html
```

## Rutas

```text
GET /research/
GET /research/analyze
```

## Controles

- año;
- mes;
- sesión;
- inicio COT;
- fin COT.

## Pipeline ejecutado

```text
Carga histórica
→ features
→ targets
→ dataset
→ baselines
→ división temporal provisional
```

## Jinja2

FastAPI prepara un diccionario `context`. Jinja2 inserta esos valores dentro de la plantilla HTML.

## Entrenamiento

La interfaz no debe entrenar modelos como efecto normal de una solicitud. El entrenamiento formal requerirá registro de configuración, artefactos y métricas.
