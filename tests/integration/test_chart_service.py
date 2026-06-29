from collections.abc import AsyncIterator
from datetime import datetime
from os import utime
from pathlib import Path
from time import time
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.services.chart_service import (
    CHART_FILE_PREFIX,
    DASHBOARD_COLORS,
    ChartResult,
    ChartService,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.may_2026 import seed_may_2026_transactions


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    pytest.importorskip("matplotlib")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/charts.sqlite3"
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
async def test_chart_service_generates_non_empty_pngs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        service = ChartService(session, settings)

        chart_results = [
            await service.create_period_dashboard_chart(
                PeriodKind.WEEK,
                now=datetime(2026, 5, 5, 12, tzinfo=ZoneInfo(settings.timezone)),
            ),
            await service.create_period_dashboard_chart(PeriodKind.MONTH, now=now),
            await service.create_period_dashboard_chart(PeriodKind.QUARTER, now=now),
            await service.create_period_dashboard_chart(PeriodKind.HALFYEAR, now=now),
            await service.create_period_dashboard_chart(PeriodKind.YEAR, now=now),
            await service.create_month_dashboard_chart(now=now),
            await service.create_cashflow_dashboard_chart(PeriodKind.MONTH, now=now),
            await service.create_payer_report_chart(PeriodKind.MONTH, now=now),
            await service.create_categories_chart(PeriodKind.MONTH, now=now),
            await service.create_categories_chart(
                PeriodKind.WEEK,
                now=datetime(2026, 5, 5, 12, tzinfo=ZoneInfo(settings.timezone)),
            ),
            await service.create_categories_chart(PeriodKind.QUARTER, now=now),
            await service.create_categories_chart(PeriodKind.YEAR, now=now),
            await service.create_cumulative_chart(now=now),
            await service.create_compare_months_chart(["may"], now=now),
            await service.create_trend_chart(6, now=now),
        ]
        await session.commit()

    for result in chart_results:
        _assert_png(result)


@pytest.mark.asyncio
async def test_chart_service_returns_none_for_empty_period(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        result = await ChartService(session, settings).create_categories_chart(
            PeriodKind.MONTH,
            now=now,
        )
        dashboard = await ChartService(session, settings).create_period_dashboard_chart(
            PeriodKind.MONTH,
            now=now,
        )
        week_dashboard = await ChartService(session, settings).create_period_dashboard_chart(
            PeriodKind.WEEK,
            now=now,
        )
        cashflow = await ChartService(session, settings).create_cashflow_dashboard_chart(
            PeriodKind.MONTH,
            now=now,
        )
        payer_report = await ChartService(session, settings).create_payer_report_chart(
            PeriodKind.MONTH,
            now=now,
        )
        await session.commit()

    assert result is None
    assert dashboard is None
    assert week_dashboard is None
    assert cashflow is None
    assert payer_report is None


@pytest.mark.asyncio
async def test_chart_service_generates_png_with_corrections(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 5, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        groceries = next(
            category
            for category in await transactions.list_category_options()
            if category.code == "groceries"
        )
        expense = await transactions.create_from_category_selection(
            amount=100_000,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="1000",
        )
        correction = await transactions.create_correction_from_category_selection(
            amount=30_000,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="bank_refund_event:1",
        )
        for transaction in (expense, correction):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 5, 5, 12, tzinfo=timezone),
            )
        service = ChartService(session, settings)
        categories = await service.create_categories_chart(PeriodKind.MONTH, now=now)
        cumulative = await service.create_cumulative_chart(now=now)
        await session.commit()

    _assert_png(categories)
    _assert_png(cumulative)


@pytest.mark.asyncio
async def test_cashflow_dashboard_handles_large_totals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    timezone = ZoneInfo(settings.timezone)
    now = datetime(2026, 6, 20, 12, tzinfo=timezone)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        transactions = TransactionService(session, settings)
        salary = await transactions.create_income(
            amount=125_000_000_00,
            recipient_telegram_id=1001,
            raw_text="manual_income:income_salary",
            category_code="income_salary",
            comment="зарплата",
        )
        business = await transactions.create_income(
            amount=80_000_000_00,
            recipient_telegram_id=1002,
            raw_text="manual_income:income_business",
            category_code="income_business",
            comment="проект",
        )
        for transaction in (salary, business):
            await transactions.update_transaction(
                transaction_id=transaction.id,
                changed_by_telegram_id=1001,
                occurred_at=datetime(2026, 6, 10, 12, tzinfo=timezone),
            )
        result = await ChartService(session, settings).create_cashflow_dashboard_chart(
            PeriodKind.MONTH,
            now=now,
        )
        await session.commit()

    _assert_png(result)


@pytest.mark.asyncio
async def test_chart_service_removes_stale_generated_pngs(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))
    old_file = tmp_path / f"{CHART_FILE_PREFIX}old.png"
    recent_file = tmp_path / f"{CHART_FILE_PREFIX}recent.png"
    unrelated_file = tmp_path / "other.png"
    for path in (old_file, recent_file, unrelated_file):
        path.write_bytes(b"stale")
    old_timestamp = time() - 25 * 60 * 60
    utime(old_file, (old_timestamp, old_timestamp))

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        result = await ChartService(
            session,
            settings,
            chart_temp_dir=tmp_path,
        ).create_period_dashboard_chart(PeriodKind.MONTH, now=now)
        await session.commit()

    assert not old_file.exists()
    assert recent_file.exists()
    assert unrelated_file.exists()
    assert result is not None
    assert result.path.parent == tmp_path
    _assert_png(result)


def _assert_png(result: ChartResult | None) -> None:
    assert result is not None
    try:
        image_bytes = result.path.read_bytes()
        assert image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(image_bytes) > 1000
    finally:
        result.path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_chart_png_uses_dark_canvas(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))
    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        result = await ChartService(session, settings).create_period_dashboard_chart(
            PeriodKind.MONTH,
            now=now,
        )
        await session.commit()

    assert result is not None
    try:
        with Image.open(result.path) as image:
            assert image.convert("RGB").getpixel((0, 0)) == _hex_to_rgb(DASHBOARD_COLORS["bg"])
    finally:
        result.path.unlink(missing_ok=True)


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    normalized = value.removeprefix("#")
    return (
        int(normalized[0:2], 16),
        int(normalized[2:4], 16),
        int(normalized[4:6], 16),
    )
