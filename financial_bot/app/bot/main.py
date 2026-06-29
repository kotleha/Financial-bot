from __future__ import annotations

import asyncio
import logging
from contextlib import suppress

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from financial_bot.app.bot.middlewares.auth import AuthMiddleware
from financial_bot.app.bot.middlewares.context import SettingsMiddleware
from financial_bot.app.bot.middlewares.db import DbSessionMiddleware
from financial_bot.app.bot.routers import get_routers
from financial_bot.app.bot.telegram_client import create_telegram_bot
from financial_bot.app.config import Settings, load_settings
from financial_bot.app.services.auth_service import TelegramAuthPolicy
from financial_bot.app.services.reminder_scheduler import ReminderScheduler
from financial_bot.app.storage.db import create_engine, create_session_factory

logger = logging.getLogger(__name__)


def create_bot(settings: Settings) -> Bot:
    return create_telegram_bot(settings)


def create_dispatcher(settings: Settings) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    auth_policy = TelegramAuthPolicy(settings.allowed_telegram_ids)
    auth_middleware = AuthMiddleware(auth_policy, denial_message="Доступ запрещён.")
    settings_middleware = SettingsMiddleware(settings)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    db_middleware = DbSessionMiddleware(session_factory)

    for observer in (dispatcher.message, dispatcher.callback_query):
        observer.middleware(auth_middleware)
        observer.middleware(settings_middleware)
        observer.middleware(db_middleware)

    for router in get_routers():
        dispatcher.include_router(router)

    dispatcher.workflow_data["db_engine"] = engine
    dispatcher.workflow_data["db_session_factory"] = session_factory
    return dispatcher


async def run_polling(settings: Settings | None = None) -> None:
    loaded_settings = settings or load_settings()
    bot = create_bot(loaded_settings)
    dispatcher = create_dispatcher(loaded_settings)
    engine = dispatcher.workflow_data["db_engine"]
    session_factory = dispatcher.workflow_data["db_session_factory"]
    reminder_scheduler = ReminderScheduler(
        bot=bot,
        session_factory=session_factory,
        settings=loaded_settings,
    )
    reminder_task = asyncio.create_task(
        reminder_scheduler.run_forever(),
        name="money-bot-reminder-scheduler",
    )

    logger.info("Starting Family Finance Telegram Bot polling.")
    try:
        await dispatcher.start_polling(bot)
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task
        await engine.dispose()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_polling())


if __name__ == "__main__":
    main()
