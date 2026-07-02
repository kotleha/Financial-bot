from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.cashflow import format_cashflow_report
from financial_bot.app.config import Settings
from financial_bot.app.domain.accounting_scope import extract_scope_filter
from financial_bot.app.domain.periods import PeriodKind, parse_period_kind
from financial_bot.app.domain.types import TransactionScope
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
    kind, scope = _period_payload_from_command(message)
    if kind is None:
        await message.answer("Период: week/month/quarter/halfyear/year или неделя/месяц/год.")
        return
    await _answer_cashflow_report(message, session, settings, kind, scope)


@router.message(F.text.func(lambda text: _cashflow_payload_from_text_alias(text) is not None))
async def cashflow_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payload = _cashflow_payload_from_text_alias(message.text or "")
    if payload is None:
        await message.answer("Период: week/month/quarter/halfyear/year или неделя/месяц/год.")
        return
    kind, scope = payload
    await _answer_cashflow_report(message, session, settings, kind, scope)


async def _answer_cashflow_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    kind: PeriodKind,
    scope: TransactionScope | None,
) -> None:
    result = await ChartService(session, settings).create_cashflow_dashboard_chart(
        kind,
        scope=scope,
    )
    if result is None:
        report = await CashflowService(session, settings).build_report(kind, scope=scope)
        await message.answer(format_cashflow_report(report))
        return

    try:
        await message.answer_photo(FSInputFile(result.path), caption=result.caption)
    finally:
        _unlink(result.path)


def _period_payload_from_command(
    message: Message,
) -> tuple[PeriodKind | None, TransactionScope | None]:
    if message.text is None:
        return PeriodKind.MONTH, None
    tokens, scope = extract_scope_filter(message.text.split()[1:])
    if not tokens:
        return PeriodKind.MONTH, scope
    return parse_period_kind(tokens[0]), scope


def _cashflow_payload_from_text_alias(
    text: str,
) -> tuple[PeriodKind, TransactionScope | None] | None:
    normalized = _normalize_cashflow_text(text)
    if normalized in CASHFLOW_ALIASES:
        return PeriodKind.MONTH, None
    for prefix in CASHFLOW_PREFIXES:
        if normalized.startswith(f"{prefix} "):
            payload_text = normalized.removeprefix(prefix).strip()
            tokens, scope = extract_scope_filter(payload_text.split())
            if not tokens:
                return PeriodKind.MONTH, scope
            kind = parse_period_kind(tokens[0])
            if kind is None:
                return None
            return kind, scope
    return None


def _cashflow_kind_from_text_alias(text: str) -> PeriodKind | None:
    payload = _cashflow_payload_from_text_alias(text)
    if payload is None:
        return None
    return payload[0]


def _normalize_cashflow_text(text: str) -> str:
    normalized = text.strip().lower()
    if normalized.startswith("💸"):
        normalized = normalized.removeprefix("💸").strip()
    return normalized


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
