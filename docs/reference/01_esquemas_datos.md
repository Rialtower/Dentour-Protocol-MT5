# Esquemas de datos

## Barras

```text
timestamp
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

Los nombres exactos pueden variar entre la capa persistida y la capa normalizada. Research trabaja con `timestamp_utc` y `timestamp_cot`.

## Ticks

```text
timestamp
bid
ask
last
volume
volume_real
```

## Dataset Research

### Identificadores

```text
observation_id
observation_time_utc
session_code
session_date
minute_of_session
```

### Features

Listado versionado en `FeatureBuildReport`.

### Targets

Listado versionado en `TargetBuildReport`.
