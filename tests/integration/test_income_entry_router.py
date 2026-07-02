from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.bot.routers.income_entry import _create_income_from_payload
from financial_bot.app.config import Settings
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base, OperationAuditLogModel, TransactionModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


class _UserStub:
    id = 1001


class _MessageStub:
    def __init__(self, text: str) -> None:
        self.text = text
        self.from_user = _UserStub()
        self.answers: list[str] = []

    async def answer(self, text: str, *args, **kwargs) -> None:
        self.answers.append(text)


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/income-entry.sqlite3"
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
async def test_manual_income_entry_stores_safe_raw_marker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    message = _MessageStub("/income 100000 зарплата")

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await _create_income_from_payload(message, session, settings, "100000 зарплата")

        transaction = await session.scalar(select(TransactionModel))
        audit = await session.scalar(select(OperationAuditLogModel))

    assert len(message.answers) == 1
    answer_lines = message.answers[0].splitlines()
    assert answer_lines[:3] == ["Учёл доход:", "100 000 ₽ — Зарплата", "Получатель: Муж"]
    assert answer_lines[3] == "Контур: Дом"
    assert answer_lines[4].startswith("Дата: ")
    assert transaction is not None
    assert transaction.raw_text == "manual_income:income_salary"
    assert transaction.comment == "зарплата"
    assert audit is not None
    assert audit.new_value is not None
    assert audit.new_value["raw_text"] == "manual_income:income_salary"
    assert "/income 100000 зарплата" not in str(audit.new_value)


@pytest.mark.asyncio
async def test_manual_income_entry_rejects_bank_like_payload_without_storing_raw_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    raw_text = "/income 100р Счет*0155 Баланс 999р"
    message = _MessageStub(raw_text)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        await _create_income_from_payload(
            message,
            session,
            settings,
            "100р Счет*0155 Баланс 999р",
        )

        transaction_count = await session.scalar(select(func.count(TransactionModel.id)))
        audit_count = await session.scalar(select(func.count(OperationAuditLogModel.id)))

    assert message.answers == ["Похоже на банковское SMS. Для таких сообщений используйте /bank."]
    assert transaction_count == 0
    assert audit_count == 0
