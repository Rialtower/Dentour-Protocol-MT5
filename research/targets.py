"""Objetivos futuros dinámicos por sesión para Research.

Responsabilidades:
- Recibir observaciones M15 generadas por research.features.
- Usar observation_time_utc/cot como instante real de decisión.
- Medir los siguientes H minutos con barras M1.
- Exigir que el horizonte completo permanezca dentro de la sesión.
- Calcular MFE, MAE, MAE previa al máximo y tiempos de excursión.
- Crear umbrales binarios ATR y etiqueta de triple barrera.
- Excluir horizontes incompletos, gaps y casos ambiguos.

No consulta archivos, no construye features, no entrena modelos y no escribe datos.
"""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Final

import numpy as np
import polars as pl

from research.contracts import (
    DEFAULT_EXPERIMENT,
    AmbiguousBarrierPolicy,
    ExperimentConfig,
)
from sessions import SessionWindow


M1_DURATION_MINUTES: Final[int] = 1
PRIMARY_THRESHOLD_ATR: Final[float] = 0.75
TARGET_PREFIX: Final[str] = "target_peak_"


@dataclass(frozen=True, slots=True)
class TargetBuildReport:
    """Resumen de construcción y exclusión de targets por sesión."""

    session_code: str
    session_label: str
    input_observations: int
    output_observations: int
    horizon_outside_session_rows: int
    incomplete_horizon_rows: int
    gap_rows: int
    invalid_atr_rows: int
    ambiguous_rows: int
    first_observation_time: datetime | None
    last_observation_time: datetime | None
    target_columns: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TargetBuildResult:
    data: pl.DataFrame
    report: TargetBuildReport


def _threshold_suffix(threshold: float) -> str:
    return f"{round(threshold * 100):03d}"


def _target_column(threshold: float) -> str:
    return f"{TARGET_PREFIX}{_threshold_suffix(threshold)}_atr"


def _validate_observations(observations: pl.DataFrame) -> None:
    """Valida el contrato producido por features.py."""

    required = {
        "timestamp_utc",
        "timestamp_cot",
        "observation_time_utc",
        "observation_time_cot",
        "session_code",
        "session_date",
        "minute_of_session",
        "close",
        "atr",
    }
    missing = required - set(observations.columns)
    if missing:
        raise ValueError(
            "Las observaciones no contienen columnas requeridas: "
            f"{sorted(missing)}"
        )
    if observations.is_empty():
        raise ValueError("El DataFrame de observaciones está vacío.")
    if not observations["observation_time_utc"].is_sorted():
        raise ValueError(
            "Las observaciones deben estar ordenadas por observation_time_utc."
        )

    duplicates = observations.select(
        pl.col("observation_time_utc").is_duplicated().sum()
    ).item()
    if duplicates:
        raise ValueError(
            "Las observaciones contienen "
            f"{duplicates} tiempos de decisión duplicados."
        )


def _validate_m1(m1: pl.DataFrame) -> None:
    """Valida la trayectoria M1 usada para medir el futuro."""

    required = {
        "timestamp_utc",
        "timestamp_cot",
        "high",
        "low",
        "close",
    }
    missing = required - set(m1.columns)
    if missing:
        raise ValueError(f"M1 no contiene columnas requeridas: {sorted(missing)}")
    if m1.is_empty():
        raise ValueError("El DataFrame M1 está vacío.")
    if not m1["timestamp_utc"].is_sorted():
        raise ValueError("M1 debe estar ordenado por timestamp_utc.")

    duplicates = m1.select(
        pl.col("timestamp_utc").is_duplicated().sum()
    ).item()
    if duplicates:
        raise ValueError(f"M1 contiene {duplicates} timestamps duplicados.")


def _positive_finite(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return bool(np.isfinite(numeric) and numeric > 0.0)


def _primary_threshold(config: ExperimentConfig) -> float:
    if PRIMARY_THRESHOLD_ATR in config.peak_thresholds_atr:
        return PRIMARY_THRESHOLD_ATR
    return config.peak_thresholds_atr[
        len(config.peak_thresholds_atr) // 2
    ]


def _timestamps_are_consecutive_minutes(
    timestamps: list[datetime],
) -> bool:
    one_minute = timedelta(minutes=1)
    return all(
        current - previous == one_minute
        for previous, current in zip(timestamps, timestamps[1:])
    )


def _session_bounds_utc(
    session: SessionWindow,
    session_date: date,
) -> tuple[datetime, datetime]:
    """Convierte los límites locales de una sesión a UTC."""

    start_cot, end_cot = session.bounds(session_date)
    return (
        start_cot.astimezone(timezone.utc),
        end_cot.astimezone(timezone.utc),
    )


def _resolve_triple_barrier(
    highs: np.ndarray,
    lows: np.ndarray,
    *,
    reference_price: float,
    atr: float,
    upper_threshold_atr: float,
    lower_threshold_atr: float,
    policy: AmbiguousBarrierPolicy,
) -> tuple[int | None, int | None, bool]:
    """Devuelve etiqueta, índice del primer toque y ambigüedad."""

    upper_price = reference_price + upper_threshold_atr * atr
    lower_price = reference_price - lower_threshold_atr * atr

    upper_hits = np.flatnonzero(highs >= upper_price)
    lower_hits = np.flatnonzero(lows <= lower_price)

    first_upper = int(upper_hits[0]) if upper_hits.size else None
    first_lower = int(lower_hits[0]) if lower_hits.size else None

    if first_upper is None and first_lower is None:
        return 0, None, False
    if first_lower is None:
        return 1, first_upper, False
    if first_upper is None:
        return -1, first_lower, False
    if first_upper < first_lower:
        return 1, first_upper, False
    if first_lower < first_upper:
        return -1, first_lower, False

    if policy is AmbiguousBarrierPolicy.EXCLUDE:
        return None, first_upper, True
    if policy is AmbiguousBarrierPolicy.CONSERVATIVE:
        return -1, first_lower, True
    if policy is AmbiguousBarrierPolicy.RESOLVE_WITH_TICKS:
        raise ValueError(
            "RESOLVE_WITH_TICKS requiere ticks y todavía no está implementado."
        )
    raise ValueError(f"Política ambigua no soportada: {policy}")


def build_peak_targets(
    observations: pl.DataFrame,
    m1: pl.DataFrame,
    *,
    session: SessionWindow | None = None,
    config: ExperimentConfig = DEFAULT_EXPERIMENT,
    drop_invalid_rows: bool = True,
) -> TargetBuildResult:
    """Calcula targets futuros dentro de la sesión seleccionada.

    La ventana M1 es [observation_time, observation_time + H). Una observación
    se excluye si el final del horizonte supera el cierre de su sesión.
    """

    _validate_observations(observations)
    _validate_m1(m1)

    selected_session = session or config.session
    expected_m1_rows = config.horizon_minutes // M1_DURATION_MINUTES
    horizon_delta = timedelta(minutes=config.horizon_minutes)
    primary_threshold = _primary_threshold(config)

    session_codes = set(observations["session_code"].unique().to_list())
    if session_codes != {selected_session.code}:
        raise ValueError(
            "Las observaciones no corresponden exclusivamente a la sesión "
            f"{selected_session.code!r}: {sorted(session_codes)}"
        )

    ordered_observations = observations.sort("observation_time_utc")
    ordered_m1 = m1.sort("timestamp_utc")

    m1_timestamps = ordered_m1["timestamp_utc"].to_list()
    m1_highs = ordered_m1["high"].to_numpy().astype(np.float64, copy=False)
    m1_lows = ordered_m1["low"].to_numpy().astype(np.float64, copy=False)

    records: list[dict[str, object]] = []
    horizon_outside_session_rows = 0
    incomplete_horizon_rows = 0
    gap_rows = 0
    invalid_atr_rows = 0
    ambiguous_rows = 0

    for row in ordered_observations.iter_rows(named=True):
        observation_time = row["observation_time_utc"]
        horizon_end = observation_time + horizon_delta
        reference_price = float(row["close"])
        atr_value = row["atr"]
        row_session_date = row["session_date"]

        session_start_utc, session_end_utc = _session_bounds_utc(
            selected_session,
            row_session_date,
        )

        record: dict[str, object] = {
            "target_horizon_end_utc": horizon_end,
            "session_start_utc": session_start_utc,
            "session_end_utc": session_end_utc,
            "reference_price": reference_price,
            "target_valid": True,
            "target_exclusion_reason": None,
            "target_ambiguous": False,
            "target_horizon_inside_session": True,
        }

        if observation_time < session_start_utc or horizon_end > session_end_utc:
            horizon_outside_session_rows += 1
            record["target_valid"] = False
            record["target_horizon_inside_session"] = False
            record["target_exclusion_reason"] = "horizon_outside_session"
            records.append(record)
            continue

        if not _positive_finite(atr_value):
            invalid_atr_rows += 1
            record["target_valid"] = False
            record["target_exclusion_reason"] = "invalid_atr"
            records.append(record)
            continue

        atr = float(atr_value)
        start_index = bisect_left(m1_timestamps, observation_time)
        end_index = bisect_left(m1_timestamps, horizon_end)

        if start_index >= len(m1_timestamps):
            incomplete_horizon_rows += 1
            record["target_valid"] = False
            record["target_exclusion_reason"] = "incomplete_horizon"
            records.append(record)
            continue

        window_timestamps = m1_timestamps[start_index:end_index]
        highs = m1_highs[start_index:end_index]
        lows = m1_lows[start_index:end_index]

        if len(window_timestamps) != expected_m1_rows:
            incomplete_horizon_rows += 1
            record["target_valid"] = False
            record["target_exclusion_reason"] = "incomplete_horizon"
            records.append(record)
            continue

        expected_last = horizon_end - timedelta(minutes=1)
        if (
            window_timestamps[0] != observation_time
            or window_timestamps[-1] != expected_last
            or not _timestamps_are_consecutive_minutes(window_timestamps)
        ):
            gap_rows += 1
            record["target_valid"] = False
            record["target_exclusion_reason"] = "m1_gap"
            records.append(record)
            continue

        peak_index = int(np.argmax(highs))
        trough_index = int(np.argmin(lows))
        future_high = float(highs[peak_index])
        future_low = float(lows[trough_index])

        mfe = max(future_high - reference_price, 0.0)
        mae = max(reference_price - future_low, 0.0)
        adverse_before_peak = max(
            reference_price - float(np.min(lows[: peak_index + 1])),
            0.0,
        )

        mfe_atr = mfe / atr
        record.update(
            {
                "future_high": future_high,
                "future_low": future_low,
                "mfe_points": mfe,
                "mae_points": mae,
                "adverse_before_peak_points": adverse_before_peak,
                "mfe_atr": mfe_atr,
                "mae_atr": mae / atr,
                "adverse_before_peak_atr": adverse_before_peak / atr,
                "time_to_peak_minutes": peak_index + 1,
                "time_to_trough_minutes": trough_index + 1,
                "peak_timestamp_utc": window_timestamps[peak_index],
                "trough_timestamp_utc": window_timestamps[trough_index],
            }
        )

        for threshold in config.peak_thresholds_atr:
            record[_target_column(threshold)] = int(mfe_atr >= threshold)

        label, touch_index, ambiguous = _resolve_triple_barrier(
            highs,
            lows,
            reference_price=reference_price,
            atr=atr,
            upper_threshold_atr=primary_threshold,
            lower_threshold_atr=config.adverse_barrier_atr,
            policy=config.ambiguous_barrier_policy,
        )
        record.update(
            {
                "triple_barrier_label": label,
                "triple_barrier_threshold_atr": primary_threshold,
                "adverse_barrier_threshold_atr": config.adverse_barrier_atr,
                "first_barrier_touch_minutes": (
                    touch_index + 1 if touch_index is not None else None
                ),
                "target_ambiguous": ambiguous,
            }
        )

        if ambiguous:
            ambiguous_rows += 1
        if label is None:
            record["target_valid"] = False
            record["target_exclusion_reason"] = "ambiguous_barrier"

        records.append(record)

    target_frame = pl.DataFrame(records)
    targets = ordered_observations.with_columns(
        pl.int_range(0, pl.len(), dtype=pl.UInt32).alias("_row_id")
    ).join(
        target_frame.with_columns(
            pl.int_range(0, pl.len(), dtype=pl.UInt32).alias("_row_id")
        ),
        on="_row_id",
        how="left",
        validate="1:1",
    ).drop("_row_id")

    target_columns = tuple(
        [_target_column(value) for value in config.peak_thresholds_atr]
        + [
            "mfe_atr",
            "mae_atr",
            "adverse_before_peak_atr",
            "time_to_peak_minutes",
            "triple_barrier_label",
        ]
    )

    if drop_invalid_rows:
        targets = targets.filter(pl.col("target_valid"))

    first_observation = None
    last_observation = None
    if not targets.is_empty():
        bounds = targets.select(
            pl.col("observation_time_utc").min().alias("first"),
            pl.col("observation_time_utc").max().alias("last"),
        ).row(0, named=True)
        first_observation = bounds["first"]
        last_observation = bounds["last"]

    report = TargetBuildReport(
        session_code=selected_session.code,
        session_label=selected_session.label,
        input_observations=observations.height,
        output_observations=targets.height,
        horizon_outside_session_rows=horizon_outside_session_rows,
        incomplete_horizon_rows=incomplete_horizon_rows,
        gap_rows=gap_rows,
        invalid_atr_rows=invalid_atr_rows,
        ambiguous_rows=ambiguous_rows,
        first_observation_time=first_observation,
        last_observation_time=last_observation,
        target_columns=target_columns,
    )

    return TargetBuildResult(data=targets, report=report)
