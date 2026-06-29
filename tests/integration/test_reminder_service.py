from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.reminder_scheduler import ReminderScheduler
from financial_bot.app.services.reminder_service import ReminderService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/reminders.sqlite3"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123456:secret-token",
        database_url="sqlite+aiosqlite:///unused.sqlite3",
        allowed_telegram_ids="1001,1002",
        default_currency="RUB",
        timezone="Asia/Barnaul",
        husband_telegram_id=1001,
        wife_telegram_id=1002,
    )


class FakeBot:
    def __init__(self, *, fail_for: set[int] | None = None) -> None:
        self.sent: list[tuple[int, str]] = []
        self.fail_for = fail_for or set()

    async def send_message(self, chat_id: int, text: str) -> None:
        if chat_id in self.fail_for:
            raise RuntimeError("telegram delivery failed")
        self.sent.append((chat_id, text))


@pytest.mark.asyncio
async def test_reminder_settings_are_persisted(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = ReminderService(session, settings)

        default_settings = await service.get_settings()
        enabled_settings = await service.set_enabled(True)
        updated_time_settings = await service.set_daily_time("20:30")
        await session.commit()

        assert not default_settings.enabled
        assert enabled_settings.enabled
        assert updated_time_settings.enabled
        assert updated_time_settings.daily_time == "20:30"

    async with session_factory() as session:
        stored_settings = await ReminderService(session, settings).get_settings()

        assert stored_settings.enabled
        assert stored_settings.daily_time == "20:30"
        assert stored_settings.last_sent_date is None


@pytest.mark.asyncio
async def test_reminder_recipients_include_only_active_users(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        users = UserRepository(session)
        wife = await users.get_by_telegram_id(1002)
        assert wife is not None
        wife.is_active = False

        recipients = await ReminderService(session, settings).active_recipients()
        await session.commit()

        assert [recipient.telegram_id for recipient in recipients] == [1001]


@pytest.mark.asyncio
async def test_due_daily_reminder_uses_timezone_and_last_sent_date(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = ReminderService(session, settings)
        await service.set_enabled(True)
        await service.set_daily_time("21:00")

        before_time = await service.due_daily_reminder(
            now=datetime(2026, 6, 29, 13, 59, tzinfo=UTC),
        )
        due = await service.due_daily_reminder(
            now=datetime(2026, 6, 29, 14, 0, tzinfo=UTC),
        )
        assert before_time is None
        assert due is not None
        assert due.local_date == "2026-06-29"
        assert [recipient.telegram_id for recipient in due.recipients] == [1001, 1002]

        await service.mark_daily_sent("2026-06-29")
        duplicate = await service.due_daily_reminder(
            now=datetime(2026, 6, 29, 14, 30, tzinfo=UTC),
        )

        assert duplicate is None


@pytest.mark.asyncio
async def test_reminder_scheduler_sends_once_and_marks_sent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    bot = FakeBot()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = ReminderService(session, settings)
        await service.set_enabled(True)
        await service.set_daily_time("21:00")
        await session.commit()

    scheduler = ReminderScheduler(
        bot=bot,  # type: ignore[arg-type]
        session_factory=session_factory,
        settings=settings,
    )
    first = await scheduler.run_once(now=datetime(2026, 6, 29, 14, 0, tzinfo=UTC))
    second = await scheduler.run_once(now=datetime(2026, 6, 29, 14, 5, tzinfo=UTC))

    assert first.attempted == 2
    assert first.sent == 2
    assert first.failed == 0
    assert not first.skipped
    assert second.skipped
    assert [chat_id for chat_id, _ in bot.sent] == [1001, 1002]

    async with session_factory() as session:
        stored_settings = await ReminderService(session, settings).get_settings()

    assert stored_settings.last_sent_date == "2026-06-29"


@pytest.mark.asyncio
async def test_reminder_scheduler_attempts_all_recipients_and_avoids_spam_after_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    bot = FakeBot(fail_for={1002})

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = ReminderService(session, settings)
        await service.set_enabled(True)
        await service.set_daily_time("21:00")
        await session.commit()

    scheduler = ReminderScheduler(
        bot=bot,  # type: ignore[arg-type]
        session_factory=session_factory,
        settings=settings,
    )

    result = await scheduler.run_once(now=datetime(2026, 6, 29, 14, 0, tzinfo=UTC))
    retry = await scheduler.run_once(now=datetime(2026, 6, 29, 14, 5, tzinfo=UTC))

    assert result.attempted == 2
    assert result.sent == 1
    assert result.failed == 1
    assert retry.skipped
    assert [chat_id for chat_id, _ in bot.sent] == [1001]
