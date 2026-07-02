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
    TransactionScope,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.smart_month_summary_service import SmartMonthSummaryService
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
    database_url = f"sqlite+aiosqlite:///{tmp_path}/smart-month-summary.sqlite3"
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
async def test_smart_month_summary_builds_scope_snapshots_for_all_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 7, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await _seed_scope_rows(session, settings, timezone)

        summary = await SmartMonthSummaryService(session, settings).build_summary(now=now)
        await session.commit()

    assert summary.report.scope is None
    assert summary.report.total_amount == 130_000_00
    assert summary.report.income_total == 220_000_00
    assert [snapshot.scope for snapshot in summary.scope_snapshots] == [
        TransactionScope.HOUSEHOLD,
        TransactionScope.SALON,
    ]
    assert [
        (snapshot.expenses, snapshot.income, snapshot.net_after_expenses)
        for snapshot in summary.scope_snapshots
    ] == [
        (40_000_00, 120_000_00, 80_000_00),
        (90_000_00, 100_000_00, 10_000_00),
    ]
    assert summary.conclusion.headline == "Месяц сейчас в плюсе после расходов."
    assert "positive_cashflow" in [insight.code for insight in summary.conclusion.insights]


@pytest.mark.asyncio
async def test_scoped_smart_month_summary_keeps_global_budget_out(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 7, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await _seed_scope_rows(session, settings, timezone)

        summary = await SmartMonthSummaryService(session, settings).build_summary(
            now=now,
            scope=TransactionScope.SALON,
        )
        await session.commit()

    assert summary.report.scope == TransactionScope.SALON
    assert summary.scope_snapshots == ()
    assert summary.report.total_amount == 90_000_00
    assert summary.report.income_total == 100_000_00
    assert summary.report.net_savings == 0
    assert summary.conclusion.details == (
        "Лимиты и копилка считаются только в общем отчёте по всем контурам."
    )
    assert not any(
        insight.code.startswith(("limit_", "savings_")) for insight in summary.conclusion.insights
    )


@pytest.mark.asyncio
async def test_smart_month_summary_adds_material_previous_month_category_growth(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 7, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        await _create_expense_on(
            transactions,
            amount=10_000_00,
            category_sort_order=6,
            occurred_at=datetime(2026, 6, 10, 12, tzinfo=timezone),
        )
        await _create_expense_on(
            transactions,
            amount=30_000_00,
            category_sort_order=6,
            occurred_at=datetime(2026, 7, 10, 12, tzinfo=timezone),
        )
        await _create_expense_on(
            transactions,
            amount=100_000_00,
            category_sort_order=2,
            occurred_at=datetime(2026, 6, 10, 12, tzinfo=timezone),
        )
        await _create_expense_on(
            transactions,
            amount=110_000_00,
            category_sort_order=2,
            occurred_at=datetime(2026, 7, 10, 12, tzinfo=timezone),
        )

        summary = await SmartMonthSummaryService(session, settings).build_summary(
            now=now,
            max_insights=8,
        )
        await session.commit()

    assert [
        (line.code, line.delta_amount, line.delta_percent) for line in summary.category_changes
    ] == [("restaurants_cafes", 20_000_00, 200.0)]
    assert "category_growth:restaurants_cafes" in [
        insight.code for insight in summary.conclusion.insights
    ]


@pytest.mark.asyncio
async def test_smart_month_summary_adds_safe_auto_accounting_quality(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 7, 20, 12, tzinfo=UTC)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
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
            _bank_event(
                source_id=source.id,
                received_at=datetime(2026, 7, 19, 12, 1, tzinfo=UTC),
                dedupe_key="pending-failed",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
                failed_at=datetime(2026, 7, 19, 12, 2, tzinfo=UTC),
            )
        )
        await bank_events.add_event(
            _bank_event(
                source_id=source.id,
                received_at=datetime(2026, 7, 19, 12, 3, tzinfo=UTC),
                dedupe_key="pending-unsent",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
            )
        )
        await bank_events.add_event(
            _bank_event(
                source_id=source.id,
                received_at=datetime(2026, 7, 19, 12, 4, tzinfo=UTC),
                dedupe_key="unknown",
                parse_status=BankEventParseStatus.NEEDS_CONFIRMATION,
                operation_kind=BankEventOperationKind.UNKNOWN,
            )
        )

        summary = await SmartMonthSummaryService(session, settings).build_summary(
            now=now,
            telegram_user_id=1001,
            max_insights=8,
        )
        await session.commit()

    assert summary.auto_accounting_quality is not None
    assert summary.auto_accounting_quality.pending_confirmation_count == 2
    assert summary.auto_accounting_quality.failed_telegram_notification_count == 1
    assert summary.auto_accounting_quality.unsent_pending_count == 2
    assert summary.auto_accounting_quality.unknown_event_count == 1
    insight_codes = [insight.code for insight in summary.conclusion.insights]
    assert "bank_delivery_failed" in insight_codes
    assert "bank_pending_confirmations" in insight_codes
    assert "bank_unknown_events" in insight_codes
    assert "bank_unsent_pending" in insight_codes
    assert "TEST MERCHANT" not in "\n".join(
        f"{insight.title}\n{insight.message}" for insight in summary.conclusion.insights
    )


@pytest.mark.asyncio
async def test_smart_month_summary_anchors_now_when_omitted(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            value = cls(2026, 9, 5, 12, tzinfo=timezone)
            if tz is None:
                return value
            return value.astimezone(tz)

    monkeypatch.setattr(
        "financial_bot.app.services.smart_month_summary_service.datetime",
        FixedDateTime,
    )

    async with session_factory() as session:
        await seed_initial_data(session, settings)

        summary = await SmartMonthSummaryService(session, settings).build_summary()
        await session.commit()

    assert summary.report.period.label == "Сентябрь 2026"


async def _seed_scope_rows(
    session: AsyncSession,
    settings: Settings,
    timezone: ZoneInfo,
) -> None:
    transactions = TransactionService(session, settings)
    household_expense = await transactions.create_from_category_sort_order(
        amount=40_000_00,
        category_sort_order=2,
        payer_telegram_id=1001,
        raw_text="40000 2",
        scope=TransactionScope.HOUSEHOLD,
    )
    salon_expense = await transactions.create_from_category_sort_order(
        amount=90_000_00,
        category_sort_order=18,
        payer_telegram_id=1002,
        raw_text="салон 90000 канцелярия",
        scope=TransactionScope.SALON,
    )
    household_income = await transactions.create_income(
        amount=120_000_00,
        recipient_telegram_id=1001,
        raw_text="manual_income:income_salary",
        category_code="income_salary",
        scope=TransactionScope.HOUSEHOLD,
    )
    salon_income = await transactions.create_income(
        amount=100_000_00,
        recipient_telegram_id=1002,
        raw_text="manual_income:income_business",
        category_code="income_business",
        scope=TransactionScope.SALON,
    )

    for transaction in (
        household_expense,
        salon_expense,
        household_income,
        salon_income,
    ):
        await transactions.update_transaction(
            transaction_id=transaction.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 7, 10, 12, tzinfo=timezone),
        )


async def _create_expense_on(
    transactions: TransactionService,
    *,
    amount: int,
    category_sort_order: int,
    occurred_at: datetime,
    scope: TransactionScope = TransactionScope.HOUSEHOLD,
) -> None:
    created = await transactions.create_from_category_sort_order(
        amount=amount,
        category_sort_order=category_sort_order,
        payer_telegram_id=1001,
        raw_text=f"{amount // 100} {category_sort_order}",
        scope=scope,
    )
    await transactions.update_transaction(
        transaction_id=created.id,
        changed_by_telegram_id=1001,
        occurred_at=occurred_at,
    )


def _bank_event(
    *,
    source_id: int,
    received_at: datetime,
    dedupe_key: str,
    parse_status: BankEventParseStatus,
    operation_kind: BankEventOperationKind = BankEventOperationKind.EXPENSE_CANDIDATE,
    failed_at: datetime | None = None,
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
    )
