from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime

from aiogram import Bot
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from financial_bot.app.config import Settings
from financial_bot.app.services.reminder_service import ReminderService
from financial_bot.app.storage.db import session_scope

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ReminderSchedulerRunResult:
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    skipped: bool = False


class ReminderScheduler:
    def __init__(
        self,
        *,
        bot: Bot,
        session_factory: async_sessionmaker[AsyncSession],
        settings: Settings,
        interval_seconds: float = 60.0,
    ) -> None:
        self._bot = bot
        self._session_factory = session_factory
        self._settings = settings
        self._interval_seconds = interval_seconds

    async def run_forever(self) -> None:
        try:
            while True:
                try:
                    await self.run_once()
                except Exception:
                    logger.exception("Reminder scheduler tick failed")
                await asyncio.sleep(self._interval_seconds)
        except asyncio.CancelledError:
            logger.info("Reminder scheduler stopped.")
            raise

    async def run_once(self, now: datetime | None = None) -> ReminderSchedulerRunResult:
        async with session_scope(self._session_factory) as session:
            service = ReminderService(session, self._settings)
            due = await service.due_daily_reminder(now=now)
            if due is None:
                return ReminderSchedulerRunResult(skipped=True)

            sent = 0
            failed = 0
            for recipient in due.recipients:
                try:
                    await self._bot.send_message(recipient.telegram_id, due.text)
                    sent += 1
                except Exception:
                    failed += 1
                    logger.warning(
                        "Daily reminder delivery failed for telegram_id=%s",
                        recipient.telegram_id,
                        exc_info=True,
                    )

            await service.mark_daily_sent(due.local_date)
            return ReminderSchedulerRunResult(
                attempted=len(due.recipients),
                sent=sent,
                failed=failed,
            )
