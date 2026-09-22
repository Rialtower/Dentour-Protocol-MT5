"""Contrato compartido de sesiones para app.py, warroom.py y research/.

Este módulo centraliza la definición de las ventanas horarias utilizadas por
las distintas capas de Dentour Protocol MT5. El objetivo es que el dashboard
diario, War Room y Research interpreten una sesión exactamente de la misma
manera.

Convenciones principales:
- Las horas se expresan inicialmente en America/Bogota.
- Los intervalos son semiabiertos: [inicio, fin).
- Una sesión puede finalizar el mismo día o cruzar medianoche.
- La fecha lógica de una sesión nocturna corresponde al día en que comenzó.
"""

# Pospone la evaluación de anotaciones. Permite usar tipos modernos sin que
# Python tenga que resolverlos inmediatamente al importar el módulo.
from __future__ import annotations

# dataclass reduce código repetitivo al crear el contrato SessionWindow.
from dataclasses import dataclass
# date identifica el día lógico de sesión; datetime representa límites exactos;
# time representa horas sin fecha y timedelta permite avanzar al día siguiente.
from datetime import date, datetime, time, timedelta
# Final documenta constantes que no deberían reasignarse durante la ejecución.
from typing import Final
# ZoneInfo utiliza zonas horarias IANA y evita trabajar con offsets manuales.
from zoneinfo import ZoneInfo

# Polars realiza filtros y agrega columnas de sesión a DataFrames columnares.
import polars as pl


# Nombre IANA del calendario operativo principal de DPMT5.
# Colombia no aplica horario de verano, por lo que normalmente corresponde a UTC-5.
TZ_COT_NAME: Final[str] = "America/Bogota"


@dataclass(frozen=True, slots=True)
class SessionWindow:
    """Describe una ventana operativa reutilizable.

    ``frozen=True`` impide cambiar una sesión después de crearla. Esto evita que
    una función modifique accidentalmente los horarios utilizados por otra.

    ``slots=True`` reduce memoria y bloquea atributos creados por error.

    Attributes
    ----------
    code:
        Identificador interno estable, por ejemplo ``new_york``.
    name:
        Nombre legible presentado al usuario.
    start:
        Hora local incluida en la ventana.
    end:
        Hora local excluida de la ventana.
    timezone_name:
        Zona IANA en la que se interpretan start y end.
    """

    code: str
    name: str
    start: time
    end: time
    timezone_name: str = TZ_COT_NAME

    @property
    def is_full_day(self) -> bool:
        """Indica si el contrato representa el día operativo completo.

        ``00:00-00:00`` normalmente sería ambiguo. DPMT5 evita interpretar
        cualquier sesión con horas iguales como día completo y utiliza el código
        explícito ``full_day``.
        """

        return self.code == "full_day"

    @property
    def crosses_midnight(self) -> bool:
        """Indica si la sesión termina durante el día calendario siguiente.

        Ejemplo: 22:00-02:00. Se excluye full_day porque ese caso posee una
        semántica especial de 24 horas completas.
        """

        return not self.is_full_day and self.end <= self.start

    @property
    def duration_minutes(self) -> int:
        """Calcula la duración total de la sesión en minutos.

        El operador módulo permite resolver tanto sesiones normales como
        sesiones nocturnas sin condicionales adicionales.
        """

        if self.is_full_day:
            return 1440

        start_minutes = self.start.hour * 60 + self.start.minute
        end_minutes = self.end.hour * 60 + self.end.minute
        return (end_minutes - start_minutes) % 1440

    @property
    def label(self) -> str:
        """Genera la etiqueta presentada en formularios, tablas y reportes."""

        if self.is_full_day:
            return "Dia completo COT"

        return (
            f"{self.name} "
            f"({self.start:%H:%M}-{self.end:%H:%M} COT)"
        )

    def bounds(
        self,
        session_date: date,
    ) -> tuple[datetime, datetime]:
        """Construye los límites con zona horaria para una fecha de sesión.

        Parameters
        ----------
        session_date:
            Día lógico en que comienza la sesión.

        Returns
        -------
        tuple[datetime, datetime]
            Par ``(inicio, fin)`` consciente de zona horaria. El final conserva
            la convención exclusiva del proyecto.
        """

        timezone = ZoneInfo(self.timezone_name)
        start = datetime.combine(session_date, self.start, timezone)

        if self.is_full_day:
            return start, start + timedelta(days=1)

        end = datetime.combine(session_date, self.end, timezone)

        # En una sesión nocturna, una hora final menor o igual a la inicial
        # pertenece al día siguiente.
        if self.crosses_midnight:
            end += timedelta(days=1)

        return start, end


# Catálogo oficial de sesiones predefinidas. Todas están expresadas actualmente
# en COT. Los horarios internacionales pueden variar respecto a sus plazas por
# horario de verano, por lo que deben entenderse como presets operativos DPMT5.
SESSION_PRESETS: Final[dict[str, SessionWindow]] = {
    "asia": SessionWindow(
        "asia",
        "Asia",
        time(19),
        time(23),
    ),
    "london": SessionWindow(
        "london",
        "Londres",
        time(2),
        time(5),
    ),
    "new_york": SessionWindow(
        "new_york",
        "Nueva York",
        time(7),
        time(10),
    ),
    "full_day": SessionWindow(
        "full_day",
        "Dia completo",
        time(0),
        time(0),
    ),
}

# Mantiene Nueva York como comportamiento predeterminado compatible con la
# ventana histórica 07:00-10:00 utilizada inicialmente por el proyecto.
DEFAULT_SESSION_CODE: Final[str] = "new_york"


def parse_time(value: str) -> time:
    """Convierte una cadena ISO ``HH:MM`` en ``datetime.time``.

    Se transforma cualquier error de tipo o formato en un mensaje perteneciente
    al dominio de la aplicación, más comprensible para API y formularios.
    """

    try:
        return time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "La hora debe usar el formato HH:MM."
        ) from exc


def resolve_session(
    code: str,
    start: str = "07:00",
    end: str = "10:00",
) -> SessionWindow:
    """Resuelve un preset o construye una sesión personalizada.

    Para presets, start y end no alteran el contrato almacenado. Para ``custom``,
    ambos valores se validan y se convierten a horas.
    """

    if code == "custom":
        parsed_start = parse_time(start)
        parsed_end = parse_time(end)

        # Las horas iguales no se interpretan como día completo en una sesión
        # personalizada. El usuario debe seleccionar el preset full_day.
        if parsed_start == parsed_end:
            raise ValueError(
                "Una sesion personalizada no puede tener inicio y fin iguales."
            )

        return SessionWindow(
            "custom",
            "Personalizada",
            parsed_start,
            parsed_end,
        )

    try:
        return SESSION_PRESETS[code]
    except KeyError as exc:
        # Se conserva la excepción original como causa mediante ``from exc``.
        raise ValueError(
            f"Sesion desconocida: {code}"
        ) from exc


def add_session_columns(
    dataframe: pl.DataFrame,
    session: SessionWindow,
    *,
    timestamp_column: str = "timestamp_cot",
) -> pl.DataFrame:
    """Agrega identidad y posición relativa dentro de una sesión.

    Columnas generadas
    ------------------
    session_code:
        Código de la sesión aplicada.
    session_date:
        Fecha lógica de inicio de sesión.
    minute_of_session:
        Minutos transcurridos desde el inicio.
    session_progress:
        Fracción de avance respecto a la duración total.

    La función agrega metadatos, pero no filtra filas. El filtrado corresponde a
    ``filter_session`` o a una regla más específica del módulo consumidor.
    """

    if timestamp_column not in dataframe.columns:
        raise ValueError(
            f"No existe la columna {timestamp_column!r}."
        )

    timestamp = pl.col(timestamp_column)

    # hour() y minute() pueden producir enteros pequeños. El cast debe ocurrir
    # antes de multiplicar; de lo contrario 08:15 podría desbordarse y generar
    # un valor negativo en implementaciones con Int8.
    local_minutes = (
        timestamp.dt.hour().cast(pl.Int32) * 60
        + timestamp.dt.minute().cast(pl.Int32)
    )

    start_minutes = (
        session.start.hour * 60
        + session.start.minute
    )

    if session.is_full_day:
        # En día completo, la fecha calendario es también la fecha de sesión y
        # los minutos se cuentan desde medianoche.
        session_date = timestamp.dt.date()
        minute_of_session = local_minutes

    elif session.crosses_midnight:
        # Después de medianoche y antes del final, la observación pertenece a la
        # sesión iniciada el día anterior.
        session_date = (
            pl.when(timestamp.dt.time() < session.end)
            .then(
                timestamp.dt.date()
                - pl.duration(days=1)
            )
            .otherwise(timestamp.dt.date())
        )

        # El módulo 1440 convierte, por ejemplo, 00:30 dentro de una sesión
        # 22:00-02:00 en 150 minutos desde el inicio.
        minute_of_session = (
            local_minutes - start_minutes
        ) % 1440

    else:
        # Una sesión normal comienza y termina el mismo día calendario.
        session_date = timestamp.dt.date()
        minute_of_session = local_minutes - start_minutes

    return dataframe.with_columns(
        pl.lit(session.code).alias("session_code"),
        session_date.alias("session_date"),
        minute_of_session.cast(pl.Int16).alias(
            "minute_of_session"
        ),
        (
            minute_of_session
            / session.duration_minutes
        )
        .cast(pl.Float64)
        .alias("session_progress"),
    )


def filter_session(
    dataframe: pl.DataFrame,
    session: SessionWindow,
    *,
    timestamp_column: str = "timestamp_cot",
) -> pl.DataFrame:
    """Filtra ``[inicio, fin)`` y agrega columnas de sesión.

    Una sesión normal utiliza AND. Una sesión nocturna utiliza OR porque los
    horarios válidos quedan a ambos lados de medianoche.
    """

    # Un DataFrame vacío conserva su esquema y recibe las columnas derivadas.
    # Full day no necesita eliminar ninguna fila.
    if dataframe.is_empty() or session.is_full_day:
        return add_session_columns(
            dataframe,
            session,
            timestamp_column=timestamp_column,
        )

    local_time = pl.col(timestamp_column).dt.time()

    if session.crosses_midnight:
        condition = (
            (local_time >= session.start)
            | (local_time < session.end)
        )
    else:
        condition = (
            (local_time >= session.start)
            & (local_time < session.end)
        )

    # Primero reduce las filas y después calcula metadatos sobre el resultado.
    return add_session_columns(
        dataframe.filter(condition),
        session,
        timestamp_column=timestamp_column,
    )
