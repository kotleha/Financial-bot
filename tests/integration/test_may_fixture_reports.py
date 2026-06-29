from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.services.report_service import ReportService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.may_2026 import (
    EXPECTED_MAY_CATEGORY_TOTALS_RUB,
    EXPECTED_MAY_REPORT_RUB,
    seed_may_2026_transactions,
)


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/may-reports.sqlite3"
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
async def test_may_fixture_preserves_payer_totals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)

        report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=now,
        )
        await session.commit()

    assert _rub(report.total_amount) == EXPECTED_MAY_REPORT_RUB["total"]
    assert {line.role: _rub(line.amount) for line in report.by_payer} == {
        "husband": EXPECTED_MAY_REPORT_RUB["husband_paid"],
        "wife": EXPECTED_MAY_REPORT_RUB["wife_paid"],
    }
    assert {line.role: line.share_percent for line in report.by_payer} == {
        "husband": EXPECTED_MAY_REPORT_RUB["husband_share"],
        "wife": EXPECTED_MAY_REPORT_RUB["wife_share"],
    }


@pytest.mark.asyncio
async def test_may_fixture_preserves_category_totals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    now = datetime(2026, 5, 20, 12, tzinfo=ZoneInfo(settings.timezone))

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)

        report = await ReportService(session, settings).build_period_report(
            PeriodKind.MONTH,
            now=now,
        )
        await session.commit()

    assert {line.code: _rub(line.amount) for line in report.by_category} == (
        EXPECTED_MAY_CATEGORY_TOTALS_RUB
    )


def _rub(amount_minor: int) -> int:
    return amount_minor // 100
