from datetime import date, datetime, timezone

import pytest

from ingest import rango_dia_cot_en_utc

def test_rango_dia_cot_se_convierte_a_utc() -> None:
    inicio, fin = rango_dia_cot_en_utc(date(2026, 8, 27))

    assert inicio == datetime(
        2026,
        8,
        27,
        5,
        0,
        tzinfo=timezone.utc,
    )

    assert fin == datetime(
        2026,
        8,
        28,
        5,
        0,
        tzinfo=timezone.utc,
    )

    assert fin > inicio

def test_rango_dura_exactamente_24_horas() -> None:
    inicio, fin = rango_dia_cot_en_utc(date(2026, 8, 27))

    assert (fin - inicio).total_seconds() == 86400

def test_rango_devuelve_fechas_utc() -> None:
    inicio, fin = rango_dia_cot_en_utc(date(2026, 8, 27))

    assert inicio.tzinfo == timezone.utc
    assert fin.tzinfo == timezone.utc

def test_rango_dia_cot_rechaza_fecha_futura() -> None:
    with pytest.raises(ValueError, match="fecha futura"):
        rango_dia_cot_en_utc(date(2999, 1, 1))