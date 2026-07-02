from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    BankEventBank,
    BankEventChannel,
    BankEventOperationKind,
    BankEventParseStatus,
)
from financial_bot.app.services.month_close_service import (
    MonthCloseItemStatus,
    MonthCloseService,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
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
    database_url = f"sqlite+aiosqlite:///{tmp_path}/month-close.sqlite3"
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
async def test_month_close_report_blocks_on_pending_bank_events_without_raw_payload(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 7, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        expense = await transactions.create_from_category_sort_order(
            amount=50_000_00,
            category_sort_order=6,
            payer_telegram_id=1001,
            raw_text="50000 6 SHABBA",
        )
        await transactions.update_transaction(
            transaction_id=expense.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 7, 10, 12, tzinfo=timezone),
        )
        await transactions.create_income(
            amount=120_000_00,
            recipient_telegram_id=1001,
            raw_text="manual_income:income_salary",
            category_code="income_salary",
            occurred_at=datetime(2026, 7, 10, 13, tzinfo=timezone),
        )
        await _seed_pending_bank_event(session)

        report = await MonthCloseService(session, settings).build_report(
            now=now,
            telegram_user_id=1001,
        )
        await session.commit()

    items_by_code = {item.code: item for item in report.checklist}
    assert report.summary.report.period.label == "Июль 2026"
    assert report.summary.report.total_amount == 50_000_00
    assert report.summary.report.income_total == 120_000_00
    assert items_by_code["bank_auto_accounting"].status == MonthCloseItemStatus.BLOCKED
    assert report.blocked_count == 1
    assert "ожидает подтверждения" in items_by_code["bank_auto_accounting"].message

    checklist_text = "\n".join(item.message for item in report.checklist)
    assert "SHABBA" not in checklist_text
    assert "raw bank payload" not in checklist_text
    assert "secret-token" not in checklist_text


async def _seed_pending_bank_event(session: AsyncSession) -> None:
    bank_events = BankEventRepository(session)
    husband = await UserRepository(session).get_by_telegram_id(1001)
    assert husband is not None
    source = await bank_events.add_source(
        BankEventSourceModel(
            code="husband-sber-ios",
            bank=BankEventBank.SBER.value,
            channel=BankEventChannel.IOS_SHORTCUT.value,
            owner_user_id=husband.id,
            token_hash=hash_bank_event_source_token("husband-source-token"),
            last_seen_at=datetime(2026, 7, 19, 12, tzinfo=UTC),
        )
    )
    await bank_events.add_event(
        BankEventModel(
            source_id=source.id,
            bank=BankEventBank.SBER.value,
            channel=BankEventChannel.IOS_SHORTCUT.value,
            received_at=datetime(2026, 7, 19, 12, 1, tzinfo=UTC),
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE.value,
            parse_status=BankEventParseStatus.NEEDS_CONFIRMATION.value,
            amount=10_000,
            currency="RUB",
            merchant="SHABBA",
            redacted_text="raw bank payload should stay internal",
            normalized_text_hash="pending-shabba",
            dedupe_key="pending-shabba",
        )
    )
