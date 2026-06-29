from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.cashflow import format_cashflow_report
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind, parse_period_kind
from financial_bot.app.services.cashflow_service import CashflowService
from financial_bot.app.services.chart_service import ChartService

router = Router(name=__name__)

CASHFLOW_ALIASES = {
    "💸 денежный поток",
    "денежный поток",
    "кэшфлоу",
    "кешфлоу",
    "cashflow",
    "поступления",
}
CASHFLOW_PREFIXES = tuple(sorted(CASHFLOW_ALIASES, key=len, reverse=True))


@router.message(Command("cashflow"))
async def cashflow_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    kind = _period_kind_from_command_payload(message)
    if kind is None:
        await message.answer("Период: week/month/quarter/halfyear/year или неделя/месяц/год.")
        return
    await _answer_cashflow_report(message, session, settings, kind)


@router.message(F.text.func(lambda text: _cashflow_kind_from_text_alias(text) is not None))
async def cashflow_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    kind = _cashflow_kind_from_text_alias(message.text or "") or PeriodKind.MONTH
    await _answer_cashflow_report(message, session, settings, kind)


async def _answer_cashflow_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    kind: PeriodKind,
) -> None:
    result = await ChartService(session, settings).create_cashflow_dashboard_chart(kind)
    if result is None:
        report = await CashflowService(session, settings).build_report(kind)
        await message.answer(format_cashflow_report(report))
        return

    try:
        await message.answer_photo(FSInputFile(result.path), caption=result.caption)
    finally:
        _unlink(result.path)


def _period_kind_from_command_payload(message: Message) -> PeriodKind | None:
    if message.text is None:
        return PeriodKind.MONTH
    parts = message.text.split(maxsplit=1)
    if len(parts) == 1:
        return PeriodKind.MONTH
    return parse_period_kind(parts[1])


def _cashflow_kind_from_text_alias(text: str) -> PeriodKind | None:
    normalized = _normalize_cashflow_text(text)
    if normalized in CASHFLOW_ALIASES:
        return PeriodKind.MONTH
    for prefix in CASHFLOW_PREFIXES:
        if normalized.startswith(f"{prefix} "):
            period_text = normalized.removeprefix(prefix).strip()
            return parse_period_kind(period_text)
    return None


def _normalize_cashflow_text(text: str) -> str:
    normalized = text.strip().lower()
    if normalized.startswith("💸"):
        normalized = normalized.removeprefix("💸").strip()
    return normalized


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
