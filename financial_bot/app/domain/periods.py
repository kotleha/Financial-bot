from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo


class PeriodKind(StrEnum):
    WEEK = "week"
    MONTH = "month"
    QUARTER = "quarter"
    HALFYEAR = "halfyear"
    YEAR = "year"


@dataclass(frozen=True, slots=True)
class Period:
    kind: PeriodKind
    start_at: datetime
    end_at: datetime
    label: str


PERIOD_ALIASES = {
    "week": PeriodKind.WEEK,
    "неделя": PeriodKind.WEEK,
    "month": PeriodKind.MONTH,
    "месяц": PeriodKind.MONTH,
    "quarter": PeriodKind.QUARTER,
    "квартал": PeriodKind.QUARTER,
    "halfyear": PeriodKind.HALFYEAR,
    "half-year": PeriodKind.HALFYEAR,
    "полгода": PeriodKind.HALFYEAR,
    "полугодие": PeriodKind.HALFYEAR,
    "year": PeriodKind.YEAR,
    "год": PeriodKind.YEAR,
}

MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}


def parse_period_kind(text: str) -> PeriodKind | None:
    normalized = text.strip().lower().removeprefix("/")
    return PERIOD_ALIASES.get(normalized)


def resolve_period(
    kind: PeriodKind,
    *,
    now: datetime | None = None,
    timezone: str,
) -> Period:
    tz = ZoneInfo(timezone)
    local_now = _to_local_datetime(now or datetime.now(tz), tz)

    match kind:
        case PeriodKind.WEEK:
            start_date = local_now.date() - timedelta(days=local_now.weekday())
            start_at = datetime.combine(start_date, time.min, tzinfo=tz)
            end_at = start_at + timedelta(days=7)
            label = f"Неделя {start_at:%d.%m.%Y}-{(end_at - timedelta(days=1)):%d.%m.%Y}"
        case PeriodKind.MONTH:
            start_at = datetime(local_now.year, local_now.month, 1, tzinfo=tz)
            end_at = _add_months(start_at, 1)
            label = f"{MONTH_NAMES[local_now.month]} {local_now.year}"
        case PeriodKind.QUARTER:
            start_month = ((local_now.month - 1) // 3) * 3 + 1
            start_at = datetime(local_now.year, start_month, 1, tzinfo=tz)
            end_at = _add_months(start_at, 3)
            quarter_number = ((local_now.month - 1) // 3) + 1
            label = f"{quarter_number} квартал {local_now.year}"
        case PeriodKind.HALFYEAR:
            start_month = 1 if local_now.month <= 6 else 7
            start_at = datetime(local_now.year, start_month, 1, tzinfo=tz)
            end_at = _add_months(start_at, 6)
            halfyear_number = 1 if start_month == 1 else 2
            label = f"{halfyear_number} полугодие {local_now.year}"
        case PeriodKind.YEAR:
            start_at = datetime(local_now.year, 1, 1, tzinfo=tz)
            end_at = datetime(local_now.year + 1, 1, 1, tzinfo=tz)
            label = f"{local_now.year} год"

    return Period(kind=kind, start_at=start_at, end_at=end_at, label=label)


def resolve_month_period(
    *,
    year: int,
    month: int,
    timezone: str,
) -> Period:
    if month < 1 or month > 12:
        msg = f"Month must be in 1..12: {month}"
        raise ValueError(msg)

    tz = ZoneInfo(timezone)
    start_at = datetime(year, month, 1, tzinfo=tz)
    end_at = _add_months(start_at, 1)
    return Period(
        kind=PeriodKind.MONTH,
        start_at=start_at,
        end_at=end_at,
        label=f"{MONTH_NAMES[month]} {year}",
    )


def _to_local_datetime(value: datetime, timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def _add_months(value: datetime, months: int) -> datetime:
    target_month_index = value.month - 1 + months
    target_year = value.year + target_month_index // 12
    target_month = target_month_index % 12 + 1
    return value.replace(year=target_year, month=target_month)
