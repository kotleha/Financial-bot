from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.month_reports import format_month_report
from financial_bot.app.bot.formatters.reports import format_period_report
from financial_bot.app.config import Settings
from financial_bot.app.domain.accounting_scope import extract_scope_filter
from financial_bot.app.domain.periods import PeriodKind, parse_period_kind
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.chart_service import ChartResult, ChartService
from financial_bot.app.services.month_report_service import MonthReportService
from financial_bot.app.services.report_service import ReportService

router = Router(name=__name__)

PERIOD_COMMANDS = ("week", "month", "quarter", "halfyear", "year")
MONTH_REPORT_ALIASES = {
    "итог месяца",
    "месячный итог",
    "сводка месяца",
    "месячная сводка",
    "умный отчет",
    "умный отчёт",
    "🧾 итог месяца",
    "отчет за месяц",
    "отчёт за месяц",
    "📊 отчет за месяц",
    "📊 отчёт за месяц",
    "📄 месяц",
    "📄 отчет за месяц",
    "📄 отчёт за месяц",
    "📄 отчет: месяц",
    "📄 отчёт: месяц",
    "📄 итог месяца",
}
PERIOD_REPORT_ALIASES = {
    "📄 неделя": PeriodKind.WEEK,
    "📄 отчет: неделя": PeriodKind.WEEK,
    "📄 отчёт: неделя": PeriodKind.WEEK,
    "📄 квартал": PeriodKind.QUARTER,
    "📄 отчет: квартал": PeriodKind.QUARTER,
    "📄 отчёт: квартал": PeriodKind.QUARTER,
    "📄 полгода": PeriodKind.HALFYEAR,
    "📄 отчет: полгода": PeriodKind.HALFYEAR,
    "📄 отчёт: полгода": PeriodKind.HALFYEAR,
    "📄 год": PeriodKind.YEAR,
    "📄 отчет: год": PeriodKind.YEAR,
    "📄 отчёт: год": PeriodKind.YEAR,
}
PAYER_REPORT_ALIASES = {
    "кто платил",
    "👥 кто платил",
    "⚖️ кто платил",
    "плательщики",
}
_TEXT_ALIAS_NO_MATCH = object()


@router.message(Command("payers"))
async def payer_report_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    _, scope = _command_args_without_scope(message)
    await _answer_payer_report(message, session, settings, scope)


@router.message(Command("summary", "month_summary"))
async def month_summary_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    _, scope = _command_args_without_scope(message)
    await _answer_month_summary(message, session, settings, scope)


@router.message(Command("owners"))
async def legacy_owners_command(message: Message) -> None:
    await message.answer(
        "Команда больше не используется. Категории: /categories. Кто платил: /payers."
    )


@router.message(
    F.text.func(lambda text: _payer_scope_from_text_alias(text) is not _TEXT_ALIAS_NO_MATCH)
)
async def payer_report_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    scope = _scope_or_none(_payer_scope_from_text_alias(message.text or ""))
    await _answer_payer_report(message, session, settings, scope)


@router.message(
    F.text.func(lambda text: _month_scope_from_text_alias(text) is not _TEXT_ALIAS_NO_MATCH)
)
async def month_report_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    scope = _scope_or_none(_month_scope_from_text_alias(message.text or ""))
    await _answer_month_summary(message, session, settings, scope)


@router.message(F.text.func(lambda text: _period_report_menu_payload(text) is not None))
async def period_report_menu_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payload = _period_report_menu_payload(message.text or "")
    if payload is None:
        await message.answer("Не понял период отчёта.")
        return
    kind, scope = payload
    await _answer_period_text_report(message, session, settings, kind, scope)


@router.message(Command("report"))
async def explicit_report_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens, scope = _command_args_without_scope(message)
    if not tokens:
        await message.answer("Используйте: /report month или /report text month")
        return

    output = tokens[0].strip().lower()
    if output in {"text", "txt", "текст"}:
        if len(tokens) < 2:
            await message.answer("Укажите период: /report text month")
            return
        kind = parse_period_kind(tokens[1])
        if kind is None:
            await message.answer("Период отчёта: week, month, quarter, halfyear или year")
            return
        if kind == PeriodKind.MONTH:
            await _answer_month_summary(message, session, settings, scope)
            return
        await _answer_period_text_report(message, session, settings, kind, scope)
        return

    kind = parse_period_kind(output)
    if kind is None:
        await message.answer("Период отчёта: week, month, quarter, halfyear или year")
        return
    await _answer_period_report(message, session, settings, kind, scope)


@router.message(Command(*PERIOD_COMMANDS))
async def period_report_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    kind = _period_kind_from_message(message)
    if kind is None:
        await message.answer("Не понял период отчёта.")
        return

    _, scope = _command_args_without_scope(message)
    await _answer_period_report(message, session, settings, kind, scope)


@router.message(F.text.func(lambda text: _period_text_payload(text) is not None))
async def period_report_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payload = _period_text_payload(message.text or "")
    if payload is None:
        await message.answer("Не понял период отчёта.")
        return
    kind, scope = payload

    await _answer_period_report(message, session, settings, kind, scope)


async def _answer_period_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    kind: PeriodKind,
    scope: TransactionScope | None,
) -> None:
    result = await ChartService(session, settings).create_period_dashboard_chart(
        kind,
        scope=scope,
    )
    await _send_report_chart_or_empty(message, result)


async def _answer_period_text_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    kind: PeriodKind,
    scope: TransactionScope | None,
) -> None:
    report = await ReportService(session, settings).build_period_report(kind, scope=scope)
    await message.answer(format_period_report(report))


async def _answer_month_summary(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    scope: TransactionScope | None,
) -> None:
    report = await MonthReportService(session, settings).build_month_report(scope=scope)
    await message.answer(format_month_report(report))


async def _answer_payer_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    scope: TransactionScope | None,
) -> None:
    result = await ChartService(session, settings).create_payer_report_chart(
        PeriodKind.MONTH,
        scope=scope,
    )
    await _send_report_chart_or_empty(message, result)


def _command_args(message: Message) -> list[str]:
    if message.text is None:
        return []
    return message.text.split()[1:]


def _command_args_without_scope(message: Message) -> tuple[list[str], TransactionScope | None]:
    return extract_scope_filter(_command_args(message))


def _period_kind_from_message(message: Message) -> PeriodKind | None:
    if message.text is None:
        return None
    command = message.text.split(maxsplit=1)[0]
    return parse_period_kind(command)


def _payer_scope_from_text_alias(text: str) -> TransactionScope | None | object:
    normalized, scope = _normalize_report_text_with_scope(text)
    if normalized in PAYER_REPORT_ALIASES:
        return scope
    return _TEXT_ALIAS_NO_MATCH


def _month_scope_from_text_alias(text: str) -> TransactionScope | None | object:
    normalized, scope = _normalize_report_text_with_scope(text)
    if normalized in MONTH_REPORT_ALIASES:
        return scope
    return _TEXT_ALIAS_NO_MATCH


def _period_report_menu_payload(text: str) -> tuple[PeriodKind, TransactionScope | None] | None:
    normalized, scope = _normalize_report_text_with_scope(text)
    kind = PERIOD_REPORT_ALIASES.get(normalized)
    if kind is None:
        return None
    return kind, scope


def _period_text_payload(text: str) -> tuple[PeriodKind, TransactionScope | None] | None:
    normalized, scope = _normalize_report_text_with_scope(text)
    if normalized.startswith("📊"):
        normalized = normalized.removeprefix("📊").strip()
    kind = parse_period_kind(normalized)
    if kind is None:
        return None
    return kind, scope


def _period_kind_from_text_alias(text: str) -> PeriodKind | None:
    payload = _period_text_payload(text)
    if payload is None:
        return None
    return payload[0]


def _normalize_report_text_with_scope(text: str) -> tuple[str, TransactionScope | None]:
    tokens, scope = extract_scope_filter(text.strip().lower().split())
    return " ".join(tokens), scope


def _scope_or_none(value: TransactionScope | None | object) -> TransactionScope | None:
    if isinstance(value, TransactionScope):
        return value
    return None


async def _send_report_chart_or_empty(message: Message, result: ChartResult | None) -> None:
    if result is None:
        await message.answer("За период нет расходов для отчёта.")
        return

    try:
        await message.answer_photo(FSInputFile(result.path), caption=result.caption)
    finally:
        _unlink(result.path)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
