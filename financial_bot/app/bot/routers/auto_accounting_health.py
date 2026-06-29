from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.auto_accounting_health import (
    format_auto_accounting_health,
)
from financial_bot.app.bot.routers.bank_events import answer_pending_bank_events
from financial_bot.app.config import Settings
from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealthService,
)

router = Router(name=__name__)

AUTO_ACCOUNTING_HEALTH_ALIASES = {
    "🩺 состояние автоучёта",
    "🩺 состояние автоучета",
    "состояние автоучёта",
    "состояние автоучета",
    "🔎 проверить источники",
    "проверить источники",
    "здоровье автоучёта",
    "здоровье автоучета",
}
AUTO_ACCOUNTING_RETRY_ALIASES = {
    "🔁 повторить ожидающие",
    "🔁 повторить отправку ожидающих",
    "повторить ожидающие",
    "повторить отправку ожидающих",
}


@router.message(F.text.func(lambda text: text.strip().lower() in AUTO_ACCOUNTING_HEALTH_ALIASES))
async def auto_accounting_health_selected(
    message: Message,
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    try:
        health = await AutoAccountingHealthService(session).get_health(
            telegram_user_id=telegram_user_id
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return
    await message.answer(format_auto_accounting_health(health))


@router.message(F.text.func(lambda text: text.strip().lower() in AUTO_ACCOUNTING_RETRY_ALIASES))
async def auto_accounting_retry_selected(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    await answer_pending_bank_events(message, session, settings, telegram_user_id)
