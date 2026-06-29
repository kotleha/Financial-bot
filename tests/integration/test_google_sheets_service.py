from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import resolve_month_period
from financial_bot.app.services.google_sheets_service import (
    GoogleSheetsNotConfigured,
    GoogleSheetsService,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.fixtures.may_2026 import MAY_2026_TRANSACTION_ROWS, seed_may_2026_transactions


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/sheets.sqlite3"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


def make_settings(*, spreadsheet_id: str | None = None) -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123456:secret-token",
        database_url="sqlite+aiosqlite:///unused.sqlite3",
        allowed_telegram_ids="1001,1002",
        default_currency="RUB",
        timezone="Asia/Barnaul",
        husband_telegram_id=1001,
        wife_telegram_id=1002,
        google_spreadsheet_id=spreadsheet_id,
    )


@pytest.mark.asyncio
async def test_google_sheets_export_disabled_without_spreadsheet_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    period = resolve_month_period(year=2026, month=5, timezone=settings.timezone)

    async with session_factory() as session:
        with pytest.raises(GoogleSheetsNotConfigured):
            await GoogleSheetsService(session, settings).export_period(period)


@pytest.mark.asyncio
async def test_google_sheets_export_appends_required_tables(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings(spreadsheet_id="spreadsheet-123")
    period = resolve_month_period(year=2026, month=5, timezone=settings.timezone)
    fake_client = FakeSheetsClient()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        summary = await GoogleSheetsService(
            session,
            settings,
            sheets_client=fake_client,
        ).export_period(period)
        await session.commit()

    assert summary is not None
    assert summary.spreadsheet_id == "spreadsheet-123"
    assert summary.rows_by_sheet["transactions"] == len(MAY_2026_TRANSACTION_ROWS)
    assert set(summary.rows_by_sheet) == {
        "transactions",
        "by_category",
        "by_payer",
        "income_transactions",
        "by_income_recipient",
        "by_income_category",
        "cashflow",
    }
    assert len(fake_client.append_calls) == 5
    assert fake_client.created_sheets == [
        "by_payer",
        "income_transactions",
        "by_income_recipient",
        "by_income_category",
        "cashflow",
    ]
    first_call = fake_client.calls[0]
    assert first_call["spreadsheetId"] == "spreadsheet-123"
    assert first_call["range"] == "transactions!A1"
    assert first_call["valueInputOption"] == "USER_ENTERED"
    assert first_call["insertDataOption"] == "INSERT_ROWS"
    assert first_call["body"]["values"][0][0] == "id"
    assert len(first_call["body"]["values"]) == len(MAY_2026_TRANSACTION_ROWS) + 1


@pytest.mark.asyncio
async def test_google_sheets_export_does_not_duplicate_headers_on_second_export(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings(spreadsheet_id="spreadsheet-123")
    period = resolve_month_period(year=2026, month=5, timezone=settings.timezone)
    fake_client = FakeSheetsClient(
        existing_sheets={
            "transactions",
            "by_category",
            "by_payer",
            "income_transactions",
            "by_income_recipient",
            "by_income_category",
            "cashflow",
        }
    )

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await seed_may_2026_transactions(session, settings)
        service = GoogleSheetsService(session, settings, sheets_client=fake_client)
        first = await service.export_period(period)
        second = await service.export_period(period)
        await session.commit()

    assert first is not None
    assert second is not None
    transaction_appends = [
        call for call in fake_client.append_calls if call["range"] == "transactions!A1"
    ]
    assert len(transaction_appends) == 2
    assert transaction_appends[0]["body"]["values"][0][0] == "id"
    assert transaction_appends[1]["body"]["values"][0][0] != "id"


class FakeSheetsClient:
    def __init__(self, *, existing_sheets: set[str] | None = None) -> None:
        self.calls: list[dict] = []
        self.append_calls: list[dict] = self.calls
        self.existing_sheets = set(existing_sheets or {"transactions", "by_category"})
        self.sheet_values: dict[str, list[list[object]]] = {}
        self.created_sheets: list[str] = []
        self._pending: tuple[str, dict] | None = None

    def spreadsheets(self):
        return self

    def values(self):
        return self

    def get(self, **kwargs):
        if "fields" in kwargs:
            self._pending = ("spreadsheet_get", kwargs)
        else:
            self._pending = ("values_get", kwargs)
        return self

    def batchUpdate(self, **kwargs):
        self._pending = ("batch_update", kwargs)
        return self

    def append(self, **kwargs):
        self._pending = ("append", kwargs)
        return self

    def execute(self):
        if self._pending is None:
            return {"ok": True, "updated_at": datetime.now(ZoneInfo("UTC")).isoformat()}

        operation, kwargs = self._pending
        self._pending = None
        if operation == "spreadsheet_get":
            return {
                "sheets": [
                    {"properties": {"title": sheet_name}}
                    for sheet_name in sorted(self.existing_sheets)
                ]
            }
        if operation == "batch_update":
            for request in kwargs["body"]["requests"]:
                sheet_name = request["addSheet"]["properties"]["title"]
                self.existing_sheets.add(sheet_name)
                self.created_sheets.append(sheet_name)
            return {"ok": True}
        if operation == "values_get":
            sheet_name = kwargs["range"].split("!", maxsplit=1)[0]
            return {"values": self.sheet_values.get(sheet_name, [])}
        if operation == "append":
            self.append_calls.append(kwargs)
            sheet_name = kwargs["range"].split("!", maxsplit=1)[0]
            self.sheet_values.setdefault(sheet_name, []).extend(kwargs["body"]["values"])
            return {"ok": True, "updated_at": datetime.now(ZoneInfo("UTC")).isoformat()}
        return {"ok": True}
