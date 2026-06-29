from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/spending-limit-report.sqlite3"
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
async def test_monthly_budget_report_calculates_limits_overruns_and_net_savings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    report_now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "groceries"
        )

        rows = [
            (72_000, 2, "72000 2", "Продукты с превышением"),
            (20_000, 6, "20000 6", "Рестораны"),
            (4_000, 1, "4000 1", "ЖКХ летний лимит"),
            (30_000, 15, "30000 15", "Инвестиции"),
            (4_200, 17, "4200 17", "Налоги без лимита"),
        ]
        for index, (amount_rub, sort_order, raw_text, comment) in enumerate(rows, start=1):
            summary = await transactions.create_from_category_sort_order(
                amount=amount_rub * 100,
                category_sort_order=sort_order,
                payer_telegram_id=1001,
                raw_text=raw_text,
                comment=comment,
            )
            await transactions.update_transaction(
                transaction_id=summary.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, index, 12, tzinfo=timezone),
            )
        refund = await transactions.create_correction_from_category_selection(
            amount=2_000 * 100,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="bank_refund_event:1",
            comment="refund",
        )
        await transactions.update_transaction(
            transaction_id=refund.id,
            changed_by_telegram_id=1001,
            occurred_at=datetime(2026, 6, 10, 12, tzinfo=timezone),
        )

        report = await SpendingLimitService(session, settings).build_monthly_report(now=report_now)
        await session.commit()

    limit_lines = {line.code: line for line in report.limit_lines}
    no_limit_lines = {line.code: line for line in report.no_limit_lines}
    target_lines = {line.code: line for line in report.savings_target_lines}

    assert report.period.label == "Июнь 2026"
    assert len(report.limit_lines) == 15
    assert limit_lines["utilities"].limit_amount == 800_000
    assert limit_lines["utilities"].remaining_amount == 400_000
    assert limit_lines["groceries"].spent_amount == 7_000_000
    assert limit_lines["groceries"].remaining_amount == 0
    assert limit_lines["groceries"].overrun_amount == 0
    assert no_limit_lines["taxes"].spent_amount == 420_000
    assert target_lines["investments_savings"].actual_amount == 3_000_000
    assert target_lines["investments_savings"].target_amount == 3_000_000
    assert target_lines["investments_savings"].delta_amount == 0
    assert report.overrun_total == 0
    assert report.under_budget_pool == sum(
        max(line.remaining_amount, 0) for line in report.limit_lines
    )
    assert report.net_savings == report.under_budget_pool - report.overrun_total


@pytest.mark.asyncio
async def test_empty_monthly_budget_report_keeps_limits_and_target(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        report = await SpendingLimitService(session, settings).build_monthly_report(
            now=datetime(2026, 1, 20, 12, tzinfo=timezone)
        )
        await session.commit()

    limit_lines = {line.code: line for line in report.limit_lines}
    target_lines = {line.code: line for line in report.savings_target_lines}

    assert len(report.limit_lines) == 15
    assert limit_lines["utilities"].limit_amount == 1_500_000
    assert report.no_limit_lines == ()
    assert target_lines["investments_savings"].actual_amount == 0
    assert target_lines["investments_savings"].delta_amount == -3_000_000
    assert report.net_savings == sum(line.limit_amount for line in report.limit_lines)


@pytest.mark.asyncio
async def test_limits_overview_shows_config_without_spending_totals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        overview = await SpendingLimitService(session, settings).build_limits_overview(
            now=datetime(2026, 6, 20, 12, tzinfo=timezone)
        )
        await session.commit()

    lines = {line.code: line for line in overview.lines}

    assert overview.period.label == "Июнь 2026"
    assert len(overview.lines) == 17
    assert lines["utilities"].amount == 800_000
    assert lines["groceries"].amount == 7_000_000
    assert lines["investments_savings"].amount == 3_000_000
    assert lines["taxes"].amount is None
