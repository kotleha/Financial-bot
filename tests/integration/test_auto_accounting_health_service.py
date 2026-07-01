from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    BankCategoryRuleMode,
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
from financial_bot.app.storage.models import (
    BankCategoryRuleModel,
    BankEventModel,
    BankEventSourceModel,
    Base,
)
from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    hash_bank_event_source_token,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
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
                received_at=datetime(2026, 6, 28, 10, 4, 15, tzinfo=UTC),
                dedupe_key="autosaved",
                parse_status=BankEventParseStatus.AUTOSAVED,
                transaction_id=124,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 30, tzinfo=UTC),
                dedupe_key="unknown",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
                operation_kind=BankEventOperationKind.UNKNOWN,
                redacted_text=("СЧЁТ<redacted> 10:20 Покупка 120р TEST SHOP Баланс: <redacted>"),
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 35, tzinfo=UTC),
                dedupe_key="income",
                parse_status=BankEventParseStatus.PARSED,
                operation_kind=BankEventOperationKind.INCOME,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 40, tzinfo=UTC),
                dedupe_key="refund",
                parse_status=BankEventParseStatus.PARSED,
                operation_kind=BankEventOperationKind.REFUND,
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
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 50, tzinfo=UTC),
                dedupe_key="internal-transfer",
                parse_status=BankEventParseStatus.PARSED,
                operation_kind=BankEventOperationKind.INTERNAL_TRANSFER,
            )
        )
        await bank_events.add_event(
            _event(
                source_id=husband_source.id,
                received_at=datetime(2026, 6, 28, 10, 4, 55, tzinfo=UTC),
                dedupe_key="conflict",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
                suggestion_conflict=True,
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
        category = await CategoryRepository(session).get_by_code("groceries")
        assert category is not None
        session.add_all(
            [
                BankCategoryRuleModel(
                    owner_user_id=husband.id,
                    bank=BankEventBank.SBER.value,
                    merchant_key="magnit",
                    merchant_display="MAGNIT",
                    category_id=category.id,
                    hit_count=3,
                    mode=BankCategoryRuleMode.AUTOSAVE.value,
                    is_active=True,
                    last_confirmed_at=datetime(2026, 6, 28, 10, 0, tzinfo=UTC),
                    last_used_at=datetime(2026, 6, 28, 10, 4, tzinfo=UTC),
                ),
                BankCategoryRuleModel(
                    owner_user_id=wife.id,
                    bank=BankEventBank.VTB.value,
                    merchant_key="apteka",
                    merchant_display="APTEKA",
                    category_id=category.id,
                    hit_count=1,
                    mode=BankCategoryRuleMode.SUGGEST.value,
                    is_active=True,
                    last_confirmed_at=datetime(2026, 6, 28, 11, 0, tzinfo=UTC),
                ),
                BankCategoryRuleModel(
                    owner_user_id=wife.id,
                    bank=BankEventBank.TBANK.value,
                    merchant_key="old",
                    merchant_display="OLD",
                    category_id=category.id,
                    hit_count=2,
                    mode=BankCategoryRuleMode.DISABLED.value,
                    is_active=False,
                    last_confirmed_at=datetime(2026, 6, 27, 11, 0, tzinfo=UTC),
                ),
            ]
        )
        await session.flush()

        health = await AutoAccountingHealthService(session).get_health(
            telegram_user_id=1001,
            now=datetime(2026, 6, 29, 12, 0, tzinfo=UTC),
        )

    assert health.active_source_count == 1
    assert health.inactive_source_count == 1
    assert health.total_event_count == 11
    assert health.expense_candidate_count == 6
    assert health.autosaved_expense_count == 1
    assert health.confirmed_expense_count == 1
    assert health.saved_expense_count == 2
    assert health.income_event_count == 1
    assert health.refund_event_count == 1
    assert health.internal_transfer_event_count == 1
    assert health.pending_confirmation_count == 4
    assert health.failed_telegram_notification_count == 1
    assert health.unsent_pending_count == 4
    assert health.unknown_event_count == 1
    assert health.ignored_event_count == 1
    assert health.conflict_event_count == 1
    assert health.autosave_rule_count == 1
    assert health.suggest_rule_count == 1
    assert health.disabled_rule_count == 1
    assert health.top_rules[0].merchant_display == "MAGNIT"
    assert health.top_rules[0].category_title == "Продукты"
    assert len(health.unknown_shapes) == 1
    assert health.unknown_shapes[0].source_code == "husband-sber-ios"
    assert health.unknown_shapes[0].bank == "sber"
    assert health.unknown_shapes[0].count == 1
    assert health.unknown_shapes[0].operation_markers == ("purchase",)
    assert health.unknown_shapes[0].amount_count == 1
    assert health.unknown_shapes[0].has_balance_marker
    assert health.unknown_shapes[0].has_instrument_marker

    husband_line = next(source for source in health.sources if source.code == "husband-sber-ios")
    wife_line = next(source for source in health.sources if source.code == "wife-vtb-ios")
    assert husband_line.total_event_count == 10
    assert husband_line.expense_candidate_count == 5
    assert husband_line.saved_expense_count == 2
    assert husband_line.pending_confirmation_count == 3
    assert husband_line.failed_telegram_notification_count == 1
    assert husband_line.unsent_pending_count == 3
    assert husband_line.unknown_event_count == 1
    assert husband_line.ignored_event_count == 1
    assert husband_line.conflict_event_count == 1
    assert husband_line.last_event_received_at == datetime(2026, 6, 28, 10, 4, 55)
    assert wife_line.total_event_count == 1
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
    suggestion_conflict: bool = False,
    redacted_text: str = "redacted bank payload",
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
        redacted_text=redacted_text,
        normalized_text_hash=dedupe_key,
        dedupe_key=dedupe_key,
        suggestion_conflict=suggestion_conflict,
        telegram_notification_failed_at=failed_at,
        transaction_id=transaction_id,
    )
