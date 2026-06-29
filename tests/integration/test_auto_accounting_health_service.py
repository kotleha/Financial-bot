from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    BankEventBank,
    BankEventChannel,
    BankEventOperationKind,
    BankEventParseStatus,
)
from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealthService,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import BankEventModel, BankEventSourceModel, Base
from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    hash_bank_event_source_token,
)
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/auto-accounting-health.sqlite3"
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


@pytest.mark.asyncio
async def test_auto_accounting_health_aggregates_source_status(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())
        bank_events = BankEventRepository(session)
        husband = await UserRepository(session).get_by_telegram_id(1001)
        wife = await UserRepository(session).get_by_telegram_id(1002)
        assert husband is not None
        assert wife is not None

        husband_source = await bank_events.add_source(
            BankEventSourceModel(
                code="husband-sber-ios",
                bank=BankEventBank.SBER.value,
                channel=BankEventChannel.IOS_SHORTCUT.value,
                owner_user_id=husband.id,
                token_hash=hash_bank_event_source_token("husband-source-token"),
                last_seen_at=datetime(2026, 6, 28, 10, 0, tzinfo=UTC),
            )
        )
        wife_source = await bank_events.add_source(
            BankEventSourceModel(
                code="wife-vtb-ios",
                bank=BankEventBank.VTB.value,
                channel=BankEventChannel.IOS_SHORTCUT.value,
                owner_user_id=wife.id,
                token_hash=hash_bank_event_source_token("wife-source-token"),
                is_active=False,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 1, tzinfo=UTC),
                dedupe_key="pending-failed",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
                failed_at=datetime(2026, 6, 28, 10, 2, tzinfo=UTC),
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 3, tzinfo=UTC),
                dedupe_key="pending-unsent",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, tzinfo=UTC),
                dedupe_key="confirmed",
                parse_status=BankEventParseStatus.CONFIRMED,
                transaction_id=123,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 30, tzinfo=UTC),
                dedupe_key="unknown",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
                operation_kind=BankEventOperationKind.UNKNOWN,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 45, tzinfo=UTC),
                dedupe_key="ignored",
                parse_status=BankEventParseStatus.IGNORED,
                operation_kind=BankEventOperationKind.IGNORED,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=wife_source.id,
                received_at=datetime(2026, 6, 28, 10, 5, tzinfo=UTC),
                dedupe_key="wife-pending",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
            )
        )

        health = await AutoAccountingHealthService(session).get_health(telegram_user_id=1001)

    assert health.active_source_count == 1
    assert health.inactive_source_count == 1
    assert health.pending_confirmation_count == 3
    assert health.failed_telegram_notification_count == 1
    assert health.unsent_pending_count == 3
    assert health.unknown_event_count == 1
    assert health.ignored_event_count == 1

    husband_line = next(source for source in health.sources if source.code == "husband-sber-ios")
    wife_line = next(source for source in health.sources if source.code == "wife-vtb-ios")
    assert husband_line.pending_confirmation_count == 2
    assert husband_line.failed_telegram_notification_count == 1
    assert husband_line.unsent_pending_count == 2
    assert husband_line.unknown_event_count == 1
    assert husband_line.ignored_event_count == 1
    assert husband_line.last_event_received_at == datetime(2026, 6, 28, 10, 4, 45)
    assert wife_line.pending_confirmation_count == 1
    assert not wife_line.is_active


@pytest.mark.asyncio
async def test_auto_accounting_health_rejects_unseeded_allowed_user(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, make_settings())

        with pytest.raises(ValueError, match="Пользователь не найден"):
            await AutoAccountingHealthService(session).get_health(telegram_user_id=9999)


def _event(
    *,
    source_id: int,
    received_at: datetime,
    dedupe_key: str,
    parse_status: BankEventParseStatus,
    operation_kind: BankEventOperationKind = BankEventOperationKind.EXPENSE_CANDIDATE,
    failed_at: datetime | None = None,
    transaction_id: int | None = None,
) -> BankEventModel:
    return BankEventModel(
        source_id=source_id,
        bank=BankEventBank.SBER.value,
        channel=BankEventChannel.IOS_SHORTCUT.value,
        received_at=received_at,
        operation_kind=operation_kind.value,
        parse_status=parse_status.value,
        amount=10_000,
        currency="RUB",
        merchant="TEST MERCHANT",
        redacted_text="redacted bank payload",
        normalized_text_hash=dedupe_key,
        dedupe_key=dedupe_key,
        telegram_notification_failed_at=failed_at,
        transaction_id=transaction_id,
    )
