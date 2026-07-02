from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.month_close import format_month_close_report
from financial_bot.app.bot.formatters.month_reports import format_smart_month_summary
from financial_bot.app.bot.keyboards.month_close import (
    MonthCloseAction,
    MonthCloseActionCallback,
    build_month_close_actions_keyboard,
)
from financial_bot.app.bot.routers.bank_events import answer_pending_bank_events
from financial_bot.app.config import Settings
from financial_bot.app.domain.accounting_scope import scope_filter_label
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.services.chart_service import ChartResult, ChartService
from financial_bot.app.services.month_close_service import MonthCloseService
from financial_bot.app.services.smart_month_summary_service import SmartMonthSummaryService

router = Router(name=__name__)

MONTH_CLOSE_ALIASES = {
    "✅ закрыть месяц",
    "закрыть месяц",
    "закрытие месяца",
    "месячное закрытие",
    "финал месяца",
    "финальный итог месяца",
    "закрыть период",
    "month close",
}


@router.message(Command("close_month", "month_close"))
async def month_close_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await _answer_month_close(message, session, settings)


@router.message(F.text.func(lambda text: text.strip().lower() in MONTH_CLOSE_ALIASES))
async def month_close_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await _answer_month_close(message, session, settings)


@router.callback_query(MonthCloseActionCallback.filter())
async def month_close_action_selected(
    callback: CallbackQuery,
    callback_data: MonthCloseActionCallback,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if callback.message is None:
        await callback.answer("Не могу открыть действие из этого сообщения.", show_alert=True)
        return

    if callback_data.action == MonthCloseAction.DASHBOARD:
        await callback.answer("Открываю дашборд")
        result = await ChartService(session, settings).create_period_dashboard_chart(
            PeriodKind.MONTH,
        )
        await _send_chart_or_empty(callback.message, result)
        return

    if callback_data.action == MonthCloseAction.BANK_PENDING:
        await callback.answer("Проверяю банковские операции")
        await answer_pending_bank_events(callback.message, session, settings, telegram_user_id)
        return

    if callback_data.action == MonthCloseAction.SUMMARY:
        await callback.answer("Открываю итог месяца")
        summary = await SmartMonthSummaryService(session, settings).build_summary(
            telegram_user_id=telegram_user_id,
        )
        await callback.message.answer(format_smart_month_summary(summary))


async def _answer_month_close(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    telegram_user_id = message.from_user.id if message.from_user is not None else None
    try:
        report = await MonthCloseService(session, settings).build_report(
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(
        format_month_close_report(report),
        reply_markup=build_month_close_actions_keyboard(),
    )


async def _send_chart_or_empty(message: Message, result: ChartResult | None) -> None:
    if result is None:
        await message.answer(
            f"За месяц пока нет расходов для дашборда. Контур: {scope_filter_label(None)}."
        )
        return

    try:
        await message.answer_photo(FSInputFile(result.path), caption=result.caption)
    finally:
        _unlink(result.path)


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
