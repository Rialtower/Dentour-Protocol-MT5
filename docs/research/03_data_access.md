# Acceso histórico de Research

## Archivo

`research/data_access.py`

## Funciones

- crea periodos COT/UTC;
- descubre archivos Parquet;
- abre DuckDB;
- consulta M1/M15/H1;
- normaliza timestamps;
- valida OHLCV;
- resume métricas.

## Duplicados

DPMT5 puede consolidar duplicados idénticos de frontera. Si un mismo timestamp contiene versiones OHLCV diferentes, debe fallar.

## DataFrames

La salida incluye:

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

## Responsabilidad excluida

No calcula features, targets ni modelos.
