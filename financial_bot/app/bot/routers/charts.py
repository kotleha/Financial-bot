from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind, parse_period_kind
from financial_bot.app.services.chart_service import ChartResult, ChartService

router = Router(name=__name__)

CATEGORY_CHART_MENU_ALIASES = {
    "категории": PeriodKind.MONTH,
    "📈 категории": PeriodKind.MONTH,
    "📈 график категорий": PeriodKind.MONTH,
    "📊 категории": PeriodKind.MONTH,
    "📊 категории: месяц": PeriodKind.MONTH,
    "📊 категории: неделя": PeriodKind.WEEK,
    "📊 категории: квартал": PeriodKind.QUARTER,
    "📊 категории: полгода": PeriodKind.HALFYEAR,
    "📊 категории: год": PeriodKind.YEAR,
}
DASHBOARD_MENU_ALIASES = {
    "📊 дашборд",
    "📊 дашборд месяца",
    "дашборд",
    "dashboard",
    "статус",
}
COMPARE_MENU_ALIASES = {"📆 сравнить", "сравнить"}
TREND_MENU_ALIASES = {"📈 тренд", "тренд"}


@router.message(Command("chart"))
async def chart_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    chart_type = tokens[0].lower() if tokens else "categories"
    service = ChartService(session, settings)

    try:
        if chart_type == "dashboard":
            result = await service.create_period_dashboard_chart(
                _dashboard_period_from_tokens(tokens)
            )
        elif chart_type == "cashflow":
            result = await service.create_cashflow_dashboard_chart(
                _cashflow_period_from_tokens(tokens)
            )
            await _send_chart_or_empty(
                message,
                result,
                empty_text=_empty_chart_message(chart_type),
            )
            return
        elif chart_type == "cumulative":
            result = await service.create_cumulative_chart()
        elif (period_kind := _category_chart_period_from_tokens(tokens)) is not None:
            result = await service.create_categories_chart(period_kind)
        else:
            await message.answer(
                "Не понял график. Доступно: dashboard, cashflow, categories <period>, "
                "<period>, cumulative."
            )
            return
    except ValueError as exc:
        await message.answer(f"Не смог построить график: {exc}")
        return

    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message(chart_type))


@router.message(Command("dashboard", "status"))
async def dashboard_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    try:
        result = await ChartService(session, settings).create_period_dashboard_chart(
            _dashboard_period_from_tokens(tokens)
        )
    except ValueError as exc:
        await message.answer(f"Не смог построить дашборд: {exc}")
        return
    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("dashboard"))


@router.message(Command("categories"))
async def categories_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    period_kind = parse_period_kind(tokens[0]) if tokens else PeriodKind.MONTH
    if period_kind is None:
        await message.answer("Период графика категорий: week, month, quarter, halfyear или year")
        return

    result = await ChartService(session, settings).create_categories_chart(period_kind)
    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("categories"))


@router.message(F.text.func(lambda text: text.strip().lower() in DASHBOARD_MENU_ALIASES))
async def dashboard_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    result = await ChartService(session, settings).create_month_dashboard_chart()
    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("dashboard"))


@router.message(F.text.func(lambda text: _category_chart_period_from_menu_text(text) is not None))
async def categories_chart_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    period_kind = _category_chart_period_from_menu_text(message.text or "") or PeriodKind.MONTH
    result = await ChartService(session, settings).create_categories_chart(period_kind)
    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("categories"))


@router.message(
    F.text.func(lambda text: text.strip().lower() in {"📈 динамика месяца", "📉 динамика"})
)
async def cumulative_chart_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    result = await ChartService(session, settings).create_cumulative_chart()
    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("cumulative"))


@router.message(Command("compare"))
async def compare_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    if not tokens:
        await message.answer("Укажите месяцы, например: /compare apr may jun")
        return

    try:
        result = await ChartService(session, settings).create_compare_months_chart(tokens)
    except ValueError as exc:
        await message.answer(f"Не смог сравнить месяцы: {exc}")
        return

    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("compare"))


@router.message(F.text.func(lambda text: text.strip().lower() in COMPARE_MENU_ALIASES))
async def compare_menu_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _default_compare_month_tokens(settings)
    try:
        result = await ChartService(session, settings).create_compare_months_chart(tokens)
    except ValueError as exc:
        await message.answer(f"Не смог сравнить месяцы: {exc}")
        return

    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("compare"))


@router.message(Command("trend"))
async def trend_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    try:
        month_count = _parse_month_count(tokens[0]) if tokens else 6
        result = await ChartService(session, settings).create_trend_chart(month_count)
    except ValueError as exc:
        await message.answer(f"Не смог построить тренд: {exc}")
        return

    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("trend"))


@router.message(F.text.func(lambda text: text.strip().lower() in TREND_MENU_ALIASES))
async def trend_menu_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    result = await ChartService(session, settings).create_trend_chart(6)
    await _send_chart_or_empty(message, result, empty_text=_empty_chart_message("trend"))


async def _send_chart_or_empty(
    message: Message,
    result: ChartResult | None,
    *,
    empty_text: str,
) -> None:
    if result is None:
        await message.answer(empty_text)
        return

    try:
        await message.answer_photo(FSInputFile(result.path), caption=result.caption)
    finally:
        _unlink(result.path)


def _command_args(message: Message) -> list[str]:
    if message.text is None:
        return []
    return message.text.split()[1:]


def _empty_chart_message(chart_type: str) -> str:
    if chart_type == "cashflow":
        return "За период нет доходов и расходов для денежного потока."
    return "За период нет расходов для графика."


def _category_chart_period_from_tokens(tokens: list[str]) -> PeriodKind | None:
    if not tokens:
        return PeriodKind.MONTH

    chart_type = tokens[0].strip().lower()
    if kind := parse_period_kind(chart_type):
        return kind

    if chart_type not in {"categories", "category"}:
        return None

    if len(tokens) == 1:
        return PeriodKind.MONTH
    return parse_period_kind(tokens[1])


def _category_chart_period_from_menu_text(text: str) -> PeriodKind | None:
    return CATEGORY_CHART_MENU_ALIASES.get(text.strip().lower())


def _parse_month_count(token: str) -> int:
    normalized = token.strip().lower().removesuffix("m").removesuffix("м")
    if not normalized.isdigit():
        msg = "Период тренда должен быть 6m или 12m"
        raise ValueError(msg)
    return int(normalized)


def _default_compare_month_tokens(settings: Settings, now: datetime | None = None) -> list[str]:
    local_now = now or datetime.now(ZoneInfo(settings.timezone))
    month = local_now.month
    if month == 1:
        return ["1"]
    return [str(month - 1), str(month)]


def _dashboard_period_from_tokens(tokens: list[str]) -> PeriodKind:
    if not tokens:
        return PeriodKind.MONTH
    if tokens[0].strip().lower() == "dashboard":
        if len(tokens) == 1:
            return PeriodKind.MONTH
        tokens = tokens[1:]
    kind = parse_period_kind(tokens[0])
    if kind is None:
        msg = "Период дашборда: week, month, quarter, halfyear или year"
        raise ValueError(msg)
    return kind


def _cashflow_period_from_tokens(tokens: list[str]) -> PeriodKind:
    if len(tokens) <= 1:
        return PeriodKind.MONTH
    kind = parse_period_kind(tokens[1])
    if kind is None:
        msg = "Период cashflow: week, month, quarter, halfyear или year"
        raise ValueError(msg)
    return kind


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
