"""Contratos del laboratorio Research de Dentour Protocol MT5.

Mantiene compatibilidad con data_access.py, features.py y targets.py, y agrega
alcance dinamico por sesiones sin ejecutar consultas ni entrenar modelos.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sessions import (
    DEFAULT_SESSION_CODE,
    SESSION_PRESETS,
    SessionWindow,
)


class Timeframe(StrEnum):
    M1 = "m1"
    M15 = "m15"
    H1 = "h1"


class ReferencePrice(StrEnum):
    CLOSE = "close"


class AmbiguousBarrierPolicy(StrEnum):
    EXCLUDE = "exclude"
    CONSERVATIVE = "conservative"
    RESOLVE_WITH_TICKS = "resolve_with_ticks"


class ResearchScope(StrEnum):
    """Forma en que Research organiza las observaciones por sesion."""

    SINGLE_SESSION = "single_session"
    ALL_PRESETS = "all_presets"
    POOLED_WITH_SESSION_FEATURES = "pooled_with_session_features"


@dataclass(frozen=True, slots=True)
class ExperimentConfig:
    """Configuracion versionada del experimento de expansion alcista."""

    observation_timeframe: Timeframe = Timeframe.M15
    path_timeframe: Timeframe = Timeframe.M1
    context_timeframes: tuple[Timeframe, ...] = (
        Timeframe.M1,
        Timeframe.M15,
        Timeframe.H1,
    )
    horizon_minutes: int = 60
    atr_period: int = 14
    reference_price: ReferencePrice = ReferencePrice.CLOSE
    peak_thresholds_atr: tuple[float, ...] = (0.50, 0.75, 1.00)
    adverse_barrier_atr: float = 0.50
    sampling_interval_minutes: int = 15
    ambiguous_barrier_policy: AmbiguousBarrierPolicy = (
        AmbiguousBarrierPolicy.EXCLUDE
    )
    timezone_name: str = "America/Bogota"
    symbol: str = "XAUUSDm"

    # Configuracion dinamica de sesiones.
    scope: ResearchScope = ResearchScope.SINGLE_SESSION
    session_code: str = DEFAULT_SESSION_CODE

    feature_version: str = "features-session-v2"
    target_version: str = "targets-session-v2"
    dataset_version: str = "dataset-session-v2"
    experiment_version: str = "peak-m15-h60-session-v2"

    def __post_init__(self) -> None:
        if self.horizon_minutes <= 0:
            raise ValueError("horizon_minutes debe ser mayor que cero.")
        if self.atr_period < 2:
            raise ValueError("atr_period debe ser al menos 2.")
        if self.sampling_interval_minutes <= 0:
            raise ValueError("sampling_interval_minutes debe ser positivo.")
        if self.horizon_minutes % self.sampling_interval_minutes != 0:
            raise ValueError(
                "El horizonte debe ser multiplo del intervalo de muestreo."
            )
        if not self.peak_thresholds_atr:
            raise ValueError("Debe existir al menos un umbral ATR.")
        if any(value <= 0 for value in self.peak_thresholds_atr):
            raise ValueError("Todos los umbrales ATR deben ser positivos.")
        if tuple(sorted(set(self.peak_thresholds_atr))) != (
            self.peak_thresholds_atr
        ):
            raise ValueError(
                "peak_thresholds_atr debe estar ordenado y sin duplicados."
            )
        if self.adverse_barrier_atr <= 0:
            raise ValueError("adverse_barrier_atr debe ser positivo.")
        if not self.symbol.strip():
            raise ValueError("symbol no puede estar vacio.")
        if not self.timezone_name.strip():
            raise ValueError("timezone_name no puede estar vacio.")
        if (
            self.session_code not in SESSION_PRESETS
            and self.session_code != "custom"
        ):
            raise ValueError(f"Sesion desconocida: {self.session_code}")

    @property
    def horizon_observation_bars(self) -> int:
        return self.horizon_minutes // self.sampling_interval_minutes

    @property
    def session(self) -> SessionWindow:
        """Devuelve el preset; custom debe inyectarse explicitamente."""

        if self.session_code == "custom":
            raise ValueError(
                "La sesion personalizada debe proporcionarse al builder."
            )
        return SESSION_PRESETS[self.session_code]


@dataclass(frozen=True, slots=True)
class DatasetSplitConfig:
    minimum_train_months: int = 6
    validation_months: int = 1
    test_months: int = 1
    embargo_minutes: int = 60

    def __post_init__(self) -> None:
        if self.minimum_train_months < 3:
            raise ValueError("Se requieren al menos 3 meses de entrenamiento.")
        if self.validation_months < 1:
            raise ValueError("validation_months debe ser al menos 1.")
        if self.test_months < 1:
            raise ValueError("test_months debe ser al menos 1.")
        if self.embargo_minutes < 0:
            raise ValueError("embargo_minutes no puede ser negativo.")


DEFAULT_EXPERIMENT: Final[ExperimentConfig] = ExperimentConfig()
DEFAULT_SPLIT: Final[DatasetSplitConfig] = DatasetSplitConfig()
