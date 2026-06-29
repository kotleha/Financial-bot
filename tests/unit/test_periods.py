from datetime import datetime
from zoneinfo import ZoneInfo

from financial_bot.app.domain.periods import PeriodKind, parse_period_kind, resolve_period


def test_parse_period_kind_supports_russian_aliases() -> None:
    assert parse_period_kind("неделя") == PeriodKind.WEEK
    assert parse_period_kind("месяц") == PeriodKind.MONTH
    assert parse_period_kind("квартал") == PeriodKind.QUARTER
    assert parse_period_kind("полгода") == PeriodKind.HALFYEAR
    assert parse_period_kind("год") == PeriodKind.YEAR
    assert parse_period_kind("/month") == PeriodKind.MONTH


def test_resolve_week_period_uses_configured_timezone() -> None:
    now = datetime(2026, 6, 12, 15, 30, tzinfo=ZoneInfo("UTC"))

    period = resolve_period(PeriodKind.WEEK, now=now, timezone="Asia/Barnaul")

    assert period.start_at == datetime(2026, 6, 8, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert period.end_at == datetime(2026, 6, 15, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert period.label == "Неделя 08.06.2026-14.06.2026"


def test_resolve_month_quarter_halfyear_and_year_periods() -> None:
    now = datetime(2026, 6, 12, 15, 30, tzinfo=ZoneInfo("Asia/Barnaul"))

    month = resolve_period(PeriodKind.MONTH, now=now, timezone="Asia/Barnaul")
    quarter = resolve_period(PeriodKind.QUARTER, now=now, timezone="Asia/Barnaul")
    halfyear = resolve_period(PeriodKind.HALFYEAR, now=now, timezone="Asia/Barnaul")
    year = resolve_period(PeriodKind.YEAR, now=now, timezone="Asia/Barnaul")

    assert month.start_at == datetime(2026, 6, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert month.end_at == datetime(2026, 7, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert month.label == "Июнь 2026"

    assert quarter.start_at == datetime(2026, 4, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert quarter.end_at == datetime(2026, 7, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert quarter.label == "2 квартал 2026"

    assert halfyear.start_at == datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert halfyear.end_at == datetime(2026, 7, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert halfyear.label == "1 полугодие 2026"

    assert year.start_at == datetime(2026, 1, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert year.end_at == datetime(2027, 1, 1, tzinfo=ZoneInfo("Asia/Barnaul"))
    assert year.label == "2026 год"
