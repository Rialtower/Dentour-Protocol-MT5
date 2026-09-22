# Backups y recuperación

## Código

Usar Git para historial y etiquetas de puntos estables.

## Data Lake

Respaldar por separado debido al tamaño y sensibilidad.

## Antes de refactorizar

- crear rama;
- conservar versión anterior;
- ejecutar validación sintáctica;
- documentar contratos afectados.

## Recuperación

1. restaurar código estable;
2. recrear `.venv` desde requirements;
3. configurar `.env`;
4. conectar Data Lake;
5. ejecutar verificaciones;
6. iniciar FastAPI.

## No mezclar

Los backups locales no deben quedar dentro del commit productivo.
