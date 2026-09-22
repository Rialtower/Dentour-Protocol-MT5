"""Validación temporal para Dentour Protocol MT5 Research.

Implementa:
- descubrimiento de meses completos presentes en un ResearchDataset;
- ventanas walk-forward mensuales;
- separación train/validation/test sin shuffle;
- purga por solapamiento del horizonte futuro;
- embargo adicional alrededor de cada frontera;
- validación de orden, separación y contratos.

No entrena modelos, no calcula features y no escribe resultados.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Final, Iterable

import polars as pl

from research.contracts import DEFAULT_SPLIT, DatasetSplitConfig
from research.dataset import ResearchDataset


MONTH_KEY_COLUMN: Final[str] = "observation_month"


@dataclass(frozen=True, slots=True, order=True)
class MonthKey:
    """Identificador cronológico de un mes calendario COT."""

    year: int
    month: int

    def __post_init__(self) -> None:
        if self.year < 1970 or self.year > 9998:
            raise ValueError("year debe estar entre 1970 y 9998.")
        if self.month < 1 or self.month > 12:
            raise ValueError("month debe estar entre 1 y 12.")

    @property
    def label(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"

    @classmethod
    def from_date(cls, value: date) -> "MonthKey":
        return cls(value.year, value.month)


@dataclass(frozen=True, slots=True)
class WalkForwardFold:
    """Contrato mensual de una ronda walk-forward."""

    fold_index: int
    train_months: tuple[MonthKey, ...]
    validation_months: tuple[MonthKey, ...]
    test_months: tuple[MonthKey, ...]

    @property
    def label(self) -> str:
        train = f"{self.train_months[0].label}..{self.train_months[-1].label}"
        validation = ",".join(month.label for month in self.validation_months)
        test = ",".join(month.label for month in self.test_months)
        return f"fold-{self.fold_index}: train={train}; val={validation}; test={test}"


@dataclass(frozen=True, slots=True)
class TemporalSplit:
    """DataFrames purgados y embargados de una ronda."""

    fold: WalkForwardFold
    train: pl.DataFrame
    validation: pl.DataFrame
    test: pl.DataFrame
    train_rows_before_purge: int
    validation_rows_before_purge: int
    test_rows_before_purge: int
    purged_train_rows: int
    purged_validation_rows: int
    embargo_minutes: int


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Resumen global de la construcción walk-forward."""

    months_available: tuple[MonthKey, ...]
    folds: tuple[WalkForwardFold, ...]
    splits: tuple[TemporalSplit, ...]
    total_rows: int
    session_codes: tuple[str, ...]


def _with_month_key(dataframe: pl.DataFrame) -> pl.DataFrame:
    """Agrega YYYY-MM derivado del calendario operativo session_date."""

    if "session_date" not in dataframe.columns:
        raise ValueError("El dataset no contiene session_date.")

    return dataframe.with_columns(
        pl.concat_str(
            [
                pl.col("session_date").dt.year().cast(pl.String),
                pl.col("session_date")
                .dt.month()
                .cast(pl.String)
                .str.pad_start(2, "0"),
            ],
            separator="-",
        ).alias(MONTH_KEY_COLUMN)
    )


def available_months(dataset: ResearchDataset) -> tuple[MonthKey, ...]:
    """Devuelve meses COT ordenados sin inferirlos desde UTC."""

    rows = (
        dataset.data
        .select(
            pl.col("session_date").dt.year().alias("year"),
            pl.col("session_date").dt.month().alias("month"),
        )
        .unique()
        .sort(["year", "month"])
        .iter_rows()
    )
    return tuple(MonthKey(int(year), int(month)) for year, month in rows)


def build_walk_forward_folds(
    months: Iterable[MonthKey],
    *,
    config: DatasetSplitConfig = DEFAULT_SPLIT,
    expanding_train: bool = True,
) -> tuple[WalkForwardFold, ...]:
    """Construye rondas mensuales en orden estrictamente cronológico.

    expanding_train=True:
        train crece desde el primer mes disponible.

    expanding_train=False:
        train usa una ventana rodante de minimum_train_months.
    """

    ordered = tuple(sorted(set(months)))
    required = (
        config.minimum_train_months
        + config.validation_months
        + config.test_months
    )
    if len(ordered) < required:
        raise ValueError(
            "Histórico mensual insuficiente para walk-forward: "
            f"disponibles={len(ordered)}, requeridos={required}."
        )

    folds: list[WalkForwardFold] = []
    first_validation_index = config.minimum_train_months
    final_start = len(ordered) - config.validation_months - config.test_months

    for fold_number, validation_start in enumerate(
        range(first_validation_index, final_start + 1),
        start=1,
    ):
        validation_end = validation_start + config.validation_months
        test_end = validation_end + config.test_months

        if expanding_train:
            train_start = 0
        else:
            train_start = validation_start - config.minimum_train_months

        folds.append(
            WalkForwardFold(
                fold_index=fold_number,
                train_months=ordered[train_start:validation_start],
                validation_months=ordered[validation_start:validation_end],
                test_months=ordered[validation_end:test_end],
            )
        )

    return tuple(folds)


def _filter_months(
    dataframe: pl.DataFrame,
    months: tuple[MonthKey, ...],
) -> pl.DataFrame:
    labels = [month.label for month in months]
    return dataframe.filter(pl.col(MONTH_KEY_COLUMN).is_in(labels))


def _assert_time_contract(dataframe: pl.DataFrame) -> None:
    required = {
        "observation_id",
        "observation_time_utc",
        "target_horizon_end_utc",
        "session_date",
        "session_code",
    }
    missing = required - set(dataframe.columns)
    if missing:
        raise ValueError(
            f"Faltan columnas temporales para validación: {sorted(missing)}"
        )
    if not dataframe["observation_time_utc"].is_sorted():
        raise ValueError("El dataset debe estar ordenado por observation_time_utc.")


def _purge_before_boundary(
    dataframe: pl.DataFrame,
    boundary: datetime,
    *,
    embargo: timedelta,
) -> tuple[pl.DataFrame, int]:
    """Elimina filas cuyo target alcanza la frontera o su embargo."""

    cutoff = boundary - embargo
    cleaned = dataframe.filter(pl.col("target_horizon_end_utc") <= cutoff)
    return cleaned, dataframe.height - cleaned.height


def _embargo_after_boundary(
    dataframe: pl.DataFrame,
    boundary: datetime,
    *,
    embargo: timedelta,
) -> pl.DataFrame:
    """Elimina observaciones inmediatamente posteriores a una frontera."""

    cutoff = boundary + embargo
    return dataframe.filter(pl.col("observation_time_utc") >= cutoff)


def build_temporal_split(
    dataset: ResearchDataset,
    fold: WalkForwardFold,
    *,
    config: DatasetSplitConfig = DEFAULT_SPLIT,
) -> TemporalSplit:
    """Materializa una ronda con purga y embargo en ambas fronteras."""

    _assert_time_contract(dataset.data)
    prepared = _with_month_key(dataset.data).sort("observation_time_utc")

    train = _filter_months(prepared, fold.train_months)
    validation = _filter_months(prepared, fold.validation_months)
    test = _filter_months(prepared, fold.test_months)

    if train.is_empty() or validation.is_empty() or test.is_empty():
        raise ValueError(
            f"{fold.label} produjo un bloque vacío. Revise cobertura por mes."
        )

    train_before = train.height
    validation_before = validation.height
    test_before = test.height
    embargo = timedelta(minutes=config.embargo_minutes)

    validation_boundary = validation["observation_time_utc"].min()
    test_boundary = test["observation_time_utc"].min()

    train, purged_train = _purge_before_boundary(
        train,
        validation_boundary,
        embargo=embargo,
    )
    validation = _embargo_after_boundary(
        validation,
        validation_boundary,
        embargo=embargo,
    )
    validation, purged_validation = _purge_before_boundary(
        validation,
        test_boundary,
        embargo=embargo,
    )
    test = _embargo_after_boundary(
        test,
        test_boundary,
        embargo=embargo,
    )

    for name, frame in (
        ("train", train),
        ("validation", validation),
        ("test", test),
    ):
        if frame.is_empty():
            raise ValueError(
                f"{fold.label}: {name} quedó vacío tras purga/embargo."
            )

    if train["target_horizon_end_utc"].max() > validation["observation_time_utc"].min():
        raise AssertionError("Train se solapa con validation después de la purga.")
    if validation["target_horizon_end_utc"].max() > test["observation_time_utc"].min():
        raise AssertionError("Validation se solapa con test después de la purga.")

    return TemporalSplit(
        fold=fold,
        train=train.drop(MONTH_KEY_COLUMN),
        validation=validation.drop(MONTH_KEY_COLUMN),
        test=test.drop(MONTH_KEY_COLUMN),
        train_rows_before_purge=train_before,
        validation_rows_before_purge=validation_before,
        test_rows_before_purge=test_before,
        purged_train_rows=purged_train,
        purged_validation_rows=purged_validation,
        embargo_minutes=config.embargo_minutes,
    )


def build_validation_report(
    dataset: ResearchDataset,
    *,
    config: DatasetSplitConfig = DEFAULT_SPLIT,
    expanding_train: bool = True,
) -> ValidationReport:
    """Construye todas las rondas disponibles y valida cada una."""

    months = available_months(dataset)
    folds = build_walk_forward_folds(
        months,
        config=config,
        expanding_train=expanding_train,
    )
    splits = tuple(
        build_temporal_split(dataset, fold, config=config)
        for fold in folds
    )

    return ValidationReport(
        months_available=months,
        folds=folds,
        splits=splits,
        total_rows=dataset.data.height,
        session_codes=tuple(
            sorted(dataset.data["session_code"].unique().to_list())
        ),
    )


def split_summary(report: ValidationReport) -> pl.DataFrame:
    """Tabla pequeña para inspección y futura interfaz Research."""

    rows: list[dict[str, object]] = []
    for split in report.splits:
        rows.append(
            {
                "fold": split.fold.fold_index,
                "train_months": ",".join(
                    month.label for month in split.fold.train_months
                ),
                "validation_months": ",".join(
                    month.label for month in split.fold.validation_months
                ),
                "test_months": ",".join(
                    month.label for month in split.fold.test_months
                ),
                "train_rows": split.train.height,
                "validation_rows": split.validation.height,
                "test_rows": split.test.height,
                "purged_train_rows": split.purged_train_rows,
                "purged_validation_rows": split.purged_validation_rows,
                "embargo_minutes": split.embargo_minutes,
            }
        )
    return pl.DataFrame(rows)


def build_single_month_development_split(
    dataset: ResearchDataset,
    *,
    train_fraction: float = 0.60,
    validation_fraction: float = 0.20,
    embargo_minutes: int = 60,
) -> TemporalSplit:
    """Prueba mecánica para un solo mes, NO evaluación estadística final.

    Divide por session_date completa para impedir que un mismo día aparezca en
    más de un bloque. Sirve para probar baselines/modelos mientras solo existe
    agosto, pero no sustituye walk-forward mensual.
    """

    if not 0.0 < train_fraction < 1.0:
        raise ValueError("train_fraction debe estar entre 0 y 1.")
    if not 0.0 < validation_fraction < 1.0:
        raise ValueError("validation_fraction debe estar entre 0 y 1.")
    if train_fraction + validation_fraction >= 1.0:
        raise ValueError("Debe quedar una fracción positiva para test.")

    _assert_time_contract(dataset.data)
    days = (
        dataset.data
        .select("session_date")
        .unique()
        .sort("session_date")["session_date"]
        .to_list()
    )
    if len(days) < 5:
        raise ValueError("Se requieren al menos 5 session_date distintas.")

    train_end = max(1, int(len(days) * train_fraction))
    validation_end = max(
        train_end + 1,
        int(len(days) * (train_fraction + validation_fraction)),
    )
    if validation_end >= len(days):
        validation_end = len(days) - 1

    train_days = days[:train_end]
    validation_days = days[train_end:validation_end]
    test_days = days[validation_end:]

    train = dataset.data.filter(pl.col("session_date").is_in(train_days))
    validation = dataset.data.filter(
        pl.col("session_date").is_in(validation_days)
    )
    test = dataset.data.filter(pl.col("session_date").is_in(test_days))

    config = DatasetSplitConfig(
        minimum_train_months=3,
        validation_months=1,
        test_months=1,
        embargo_minutes=embargo_minutes,
    )
    synthetic_month = MonthKey.from_date(days[0])
    fold = WalkForwardFold(
        fold_index=0,
        train_months=(synthetic_month,),
        validation_months=(synthetic_month,),
        test_months=(synthetic_month,),
    )

    train_before = train.height
    validation_before = validation.height
    test_before = test.height
    embargo = timedelta(minutes=config.embargo_minutes)
    validation_boundary = validation["observation_time_utc"].min()
    test_boundary = test["observation_time_utc"].min()

    train, purged_train = _purge_before_boundary(
        train, validation_boundary, embargo=embargo
    )
    validation = _embargo_after_boundary(
        validation, validation_boundary, embargo=embargo
    )
    validation, purged_validation = _purge_before_boundary(
        validation, test_boundary, embargo=embargo
    )
    test = _embargo_after_boundary(test, test_boundary, embargo=embargo)

    if train.is_empty() or validation.is_empty() or test.is_empty():
        raise ValueError("La división de desarrollo quedó vacía tras purga/embargo.")

    return TemporalSplit(
        fold=fold,
        train=train,
        validation=validation,
        test=test,
        train_rows_before_purge=train_before,
        validation_rows_before_purge=validation_before,
        test_rows_before_purge=test_before,
        purged_train_rows=purged_train,
        purged_validation_rows=purged_validation,
        embargo_minutes=embargo_minutes,
    )
