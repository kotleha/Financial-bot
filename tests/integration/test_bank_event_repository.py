from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.domain.types import (
    BankEventBank,
    BankEventChannel,
    BankEventOperationKind,
    BankEventParseStatus,
    CategoryOwnerRole,
    TransactionSource,
    TransactionType,
    UserRole,
)
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import (
    BankEventModel,
    BankEventSourceModel,
    Base,
    CategoryModel,
    TransactionModel,
    UserModel,
)
from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    hash_bank_event_source_token,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/bank-events.sqlite3"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


def test_hash_bank_event_source_token_is_stable_and_rejects_empty_tokens() -> None:
    token = "synthetic-source-token"

    token_hash = hash_bank_event_source_token(token)

    assert token_hash == hash_bank_event_source_token(f" {token} ")
    assert token_hash != token
    assert len(token_hash) == 64
    with pytest.raises(ValueError):
        hash_bank_event_source_token(" ")


@pytest.mark.asyncio
async def test_bank_event_repository_sources_dedupe_status_and_transaction_link(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    token = "synthetic-source-token"
    received_at = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)

    async with session_factory() as session:
        users = UserRepository(session)
        categories = CategoryRepository(session)
        transactions = TransactionRepository(session)
        bank_events = BankEventRepository(session)

        husband = await users.add(
            UserModel(
                telegram_id=1001,
                name="Husband",
                role=UserRole.HUSBAND.value,
            )
        )
        category = await categories.add(
            CategoryModel(
                code="cosmetology_medicine",
                title="Cosmetology/Medicine",
                owner_user_id=None,
                owner_role=CategoryOwnerRole.SYSTEM.value,
                sort_order=8,
            )
        )
        source = await bank_events.add_source(
            BankEventSourceModel(
                code="husband-iphone-sber",
                bank=BankEventBank.SBER.value,
                channel=BankEventChannel.IOS_SHORTCUT.value,
                owner_user_id=husband.id,
                token_hash=hash_bank_event_source_token(token),
            )
        )

        found_source = await bank_events.get_active_source_by_token(token)
        assert found_source is not None
        assert found_source.id == source.id
        assert found_source.token_hash != token

        await bank_events.touch_source(source, seen_at=received_at)
        assert source.last_seen_at == received_at

        event = BankEventModel(
            source_id=source.id,
            bank=BankEventBank.SBER.value,
            channel=BankEventChannel.IOS_SHORTCUT.value,
            received_at=received_at,
            occurred_at=received_at,
            operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE.value,
            parse_status=BankEventParseStatus.NEEDS_CONFIRMATION.value,
            amount=29_000,
            currency="RUB",
            merchant="APTEKA TEST",
            redacted_text="Счёт карты MIR-<redacted> Покупка 290р APTEKA TEST Баланс: <redacted>",
            normalized_text_hash="normalized-hash-1",
            dedupe_key="sber:husband-iphone-sber:normalized-hash-1",
            suggested_category_id=category.id,
        )
        created_event, is_created = await bank_events.add_event_if_new(event)

        assert is_created
        assert created_event.id is not None
        assert created_event.telegram_notification_attempts == 0

        duplicate_event, duplicate_created = await bank_events.add_event_if_new(
            BankEventModel(
                source_id=source.id,
                bank=BankEventBank.SBER.value,
                channel=BankEventChannel.IOS_SHORTCUT.value,
                received_at=received_at,
                operation_kind=BankEventOperationKind.EXPENSE_CANDIDATE.value,
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION.value,
                amount=29_000,
                currency="RUB",
                redacted_text="duplicate redacted text",
                normalized_text_hash="normalized-hash-1",
                dedupe_key="sber:husband-iphone-sber:normalized-hash-1",
            )
        )
        assert not duplicate_created
        assert duplicate_event.id == created_event.id

        pending_events = await bank_events.list_pending_confirmation_events_for_owner(
            owner_user_id=husband.id,
        )
        assert [event.id for event in pending_events] == [created_event.id]

        failed_at = datetime(2026, 6, 26, 12, 1, tzinfo=UTC)
        await bank_events.mark_telegram_notification_failed(created_event, failed_at=failed_at)
        assert created_event.telegram_notification_failed_at == failed_at
        assert created_event.telegram_notification_sent_at is None
        assert created_event.telegram_notification_attempts == 1

        sent_at = datetime(2026, 6, 26, 12, 2, tzinfo=UTC)
        await bank_events.mark_telegram_notification_sent(created_event, sent_at=sent_at)
        assert created_event.telegram_notification_sent_at == sent_at
        assert created_event.telegram_notification_failed_at is None
        assert created_event.telegram_notification_attempts == 2

        await bank_events.set_parse_status(created_event, BankEventParseStatus.PARSED)
        parsed_events = await bank_events.list_events_by_status(BankEventParseStatus.PARSED)
        assert [event.id for event in parsed_events] == [created_event.id]

        transaction = await transactions.add(
            TransactionModel(
                amount=29_000,
                currency="RUB",
                occurred_at=received_at,
                payer_user_id=husband.id,
                category_id=category.id,
                type=TransactionType.EXPENSE.value,
                source=TransactionSource.CARD.value,
                raw_text="bank event confirmation",
                included_in_reports=True,
                created_by_user_id=husband.id,
            )
        )
        await bank_events.link_transaction(
            created_event,
            transaction_id=transaction.id,
            status=BankEventParseStatus.CONFIRMED,
        )

        assert created_event.transaction_id == transaction.id
        assert created_event.parse_status == BankEventParseStatus.CONFIRMED.value
