"""Contrato compartido de sesiones para app.py, warroom.py y research/."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Final
from zoneinfo import ZoneInfo

import polars as pl


TZ_COT_NAME: Final[str] = "America/Bogota"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    code: str
    name: str
    start: time
    end: time
    timezone_name: str = TZ_COT_NAME

    @property
    def is_full_day(self) -> bool:
        return self.code == "full_day"

    @property
    def crosses_midnight(self) -> bool:
        return not self.is_full_day and self.end <= self.start

    @property
    def duration_minutes(self) -> int:
        if self.is_full_day:
            return 1440
        start_minutes = self.start.hour * 60 + self.start.minute
        end_minutes = self.end.hour * 60 + self.end.minute
        return (end_minutes - start_minutes) % 1440

    @property
    def label(self) -> str:
        if self.is_full_day:
            return "Dia completo COT"
        return f"{self.name} ({self.start:%H:%M}-{self.end:%H:%M} COT)"

    def bounds(self, session_date: date) -> tuple[datetime, datetime]:
        timezone = ZoneInfo(self.timezone_name)
        start = datetime.combine(session_date, self.start, timezone)
        if self.is_full_day:
            return start, start + timedelta(days=1)
        end = datetime.combine(session_date, self.end, timezone)
        if self.crosses_midnight:
            end += timedelta(days=1)
        return start, end


SESSION_PRESETS: Final[dict[str, SessionWindow]] = {
    "asia": SessionWindow("asia", "Asia", time(19), time(23)),
    "london": SessionWindow("london", "Londres", time(2), time(5)),
    "new_york": SessionWindow("new_york", "Nueva York", time(7), time(10)),
    "full_day": SessionWindow("full_day", "Dia completo", time(0), time(0)),
}
DEFAULT_SESSION_CODE: Final[str] = "new_york"


def parse_time(value: str) -> time:
    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("La hora debe usar el formato HH:MM.") from exc


def resolve_session(
    code: str,
    start: str = "07:00",
    end: str = "10:00",
) -> SessionWindow:
    if code == "custom":
        parsed_start = parse_time(start)
        parsed_end = parse_time(end)
        if parsed_start == parsed_end:
            raise ValueError(
                "Una sesion personalizada no puede tener inicio y fin iguales."
            )
        return SessionWindow("custom", "Personalizada", parsed_start, parsed_end)
    try:
        return SESSION_PRESETS[code]
    except KeyError as exc:
        raise ValueError(f"Sesion desconocida: {code}") from exc


def add_session_columns(
    dataframe: pl.DataFrame,
    session: SessionWindow,
    *,
    timestamp_column: str = "timestamp_cot",
) -> pl.DataFrame:
    """Agrega identidad y posicion relativa dentro de la sesion."""

    if timestamp_column not in dataframe.columns:
        raise ValueError(f"No existe la columna {timestamp_column!r}.")

    timestamp = pl.col(timestamp_column)

    # hour() y minute() pueden producir enteros pequeños.
    # Convertimos antes de multiplicar para impedir overflow.
    local_minutes = (
        timestamp.dt.hour().cast(pl.Int32) * 60
        + timestamp.dt.minute().cast(pl.Int32)
    )

    start_minutes = (
        session.start.hour * 60
        + session.start.minute
    )

    if session.is_full_day:
        session_date = timestamp.dt.date()
        minute_of_session = local_minutes
    elif session.crosses_midnight:
        session_date = (
            pl.when(timestamp.dt.time() < session.end)
            .then(timestamp.dt.date() - pl.duration(days=1))
            .otherwise(timestamp.dt.date())
        )
        minute_of_session = (local_minutes - start_minutes) % 1440
    else:
        session_date = timestamp.dt.date()
        minute_of_session = local_minutes - start_minutes

    return dataframe.with_columns(
        pl.lit(session.code).alias("session_code"),
        session_date.alias("session_date"),
        minute_of_session.cast(pl.Int16).alias("minute_of_session"),
        (minute_of_session / session.duration_minutes)
        .cast(pl.Float64)
        .alias("session_progress"),
    )


def filter_session(
    dataframe: pl.DataFrame,
    session: SessionWindow,
    *,
    timestamp_column: str = "timestamp_cot",
) -> pl.DataFrame:
    """Filtra [inicio, fin) y soporta ventanas que cruzan medianoche."""

    if dataframe.is_empty() or session.is_full_day:
        return add_session_columns(
            dataframe, session, timestamp_column=timestamp_column
        )

    local_time = pl.col(timestamp_column).dt.time()
    if session.crosses_midnight:
        condition = (local_time >= session.start) | (local_time < session.end)
    else:
        condition = (local_time >= session.start) & (local_time < session.end)

    return add_session_columns(
        dataframe.filter(condition),
        session,
        timestamp_column=timestamp_column,
    )
