# Módulo de ingesta

## Propósito

`ingest.py` es la única frontera entre DPMT5 y MetaTrader 5.

## Responsabilidades

- inicializar MT5;
- obtener barras y ticks;
- convertir días COT a UTC;
- normalizar columnas;
- validar intervalos;
- aplicar esquemas Arrow;
- escribir Parquet ZSTD;
- usar escritura atómica;
- auditar archivos;
- controlar concurrencia;
- cerrar MT5 en `finally`.

## Contrato diario

```text
Día COT
→ inicio UTC incluido
→ fin UTC excluido
```

Después de normalizar, deben conservarse únicamente filas:

```python
(timestamp >= inicio) & (timestamp < fin)
```

## Tipos

### Barras

M1, M15 y H1 con timestamp, OHLC, volumen, spread y volumen real.

### Ticks

Bid, ask, last, volumen y volumen real según disponibilidad del broker.

## Fallos esperados

- MT5 no inicializa;
- símbolo inexistente;
- histórico no descargado;
- día sin mercado;
- DataFrame vacío;
- archivo ya bloqueado;
- esquema incompatible.

## Regla arquitectónica

`app.py`, `warroom.py` y `research/` nunca deben llamar directamente a MetaTrader 5.
