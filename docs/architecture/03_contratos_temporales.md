# Contratos temporales

## Zonas horarias

- Almacenamiento y uniones: UTC.
- Calendario operativo: `America/Bogota`.
- Referencia del servidor del broker: `Europe/Athens`.

## Intervalos semiabiertos

DPMT5 utiliza:

```text
[inicio, fin)
```

La frontera inicial se incluye y la final se excluye. Esto evita que una barra de medianoche aparezca simultáneamente en dos particiones.

## Apertura y disponibilidad

MetaTrader 5 identifica normalmente una barra por su apertura.

```text
M1  abre en t y queda cerrada en t + 1 minuto
M15 abre en t y queda cerrada en t + 15 minutos
H1  abre en t y queda cerrada en t + 60 minutos
```

DPMT5 conserva:

```text
timestamp_utc
observation_time_utc
```

El primero representa apertura. El segundo representa disponibilidad para Research.

## Sesiones

La apertura M15 determina si una barra pertenece a la sesión. El cierre confirmado determina `minute_of_session`.

Ejemplo Nueva York:

```text
Sesión:             07:00-10:00
Apertura M15:       07:00
Cierre confirmado:  07:15
minute_of_session:  15
```

## Targets y horizonte

Para una observación en `09:00` con horizonte de 60 minutos:

```text
09:00 + 60 = 10:00
```

El target cabe dentro de una sesión que termina a las 10:00. Una observación en 09:15 queda excluida porque su horizonte termina a las 10:15.

## Prevención de look-ahead

- Features usan información disponible hasta el instante de observación.
- H1 se une únicamente después de estar completamente cerrada.
- Targets pueden mirar al futuro, pero nunca formar parte de X.
- Train nunca puede utilizar resultados que invadan validation o test.
