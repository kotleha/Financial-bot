from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.bot.routers.bank_events import _confirm_bank_event
from financial_bot.app.bot.routers.expense_entry import (
    _answer_threshold_alerts as answer_expense_threshold_alerts,
)
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import BankEventBank, BankEventParseStatus
from financial_bot.app.services.bank_ingestion_service import BankIngestionService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import (
    BankEventModel,
    BankEventSourceModel,
    Base,
    CategoryModel,
    TransactionModel,
)
from financial_bot.app.storage.repositories.bank_event_repository import (
    hash_bank_event_source_token,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/bot-commit-safety.sqlite3"
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


class _FailingBot:
    async def send_message(self, *args, **kwargs) -> None:
        raise RuntimeError("telegram send failed")


class _MessageWithFailingBot:
    bot = _FailingBot()


class _EditFailMessage:
    bot = _FailingBot()

    async def edit_text(self, *args, **kwargs) -> None:
        raise RuntimeError("telegram edit failed")


class _CallbackStub:
    def __init__(self) -> None:
        self.message = _EditFailMessage()
        self.answers: list[tuple[str | None, bool | None]] = []

    async def answer(self, text: str | None = None, *, show_alert: bool | None = None) -> None:
        self.answers.append((text, show_alert))


@pytest.mark.asyncio
async def test_expense_stays_saved_when_threshold_alert_delivery_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        summary = await TransactionService(session, settings).create_from_category_sort_order(
            amount=35_000 * 100,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="35000 2",
        )
        await session.commit()

        await answer_expense_threshold_alerts(
            _MessageWithFailingBot(),
            session,
            settings,
            [summary.id],
        )

    async with session_factory() as session:
        transaction_count = await session.scalar(select(func.count(TransactionModel.id)))

    assert transaction_count == 1


@pytest.mark.asyncio
async def test_bank_confirmation_stays_saved_when_telegram_edit_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    source_token = "husband-sber-token"

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        source = BankEventSourceModel(
            code="husband-sber-ios",
            bank=BankEventBank.SBER.value,
            channel="ios_shortcut",
            owner_user_id=1,
            token_hash=hash_bank_event_source_token(source_token),
        )
        session.add(source)
        await session.flush()

        result = await BankIngestionService(session, settings).import_sms_from_source_token(
            text="Счёт карты MIR-3079 09:50 Покупка по СБП 199р VK Баланс: 60.11р",
            source_token=source_token,
            sender="900",
        )
        event = await session.get(BankEventModel, result.event_id)
        category = await CategoryRepository(session).get_by_sort_order(2)
        assert event is not None
        assert category is not None
        event.suggested_category_id = category.id
        await session.flush()

        callback = _CallbackStub()
        with pytest.raises(RuntimeError, match="telegram edit failed"):
            await _confirm_bank_event(
                callback,
                BankIngestionService(session, settings),
                session,
                settings,
                1001,
                result.event_id,
            )
        await session.rollback()

    async with session_factory() as session:
        transaction_count = await session.scalar(select(func.count(TransactionModel.id)))
        stored_event = await session.get(BankEventModel, result.event_id)
        stored_transaction = await session.scalar(select(TransactionModel))
        stored_category = await session.scalar(
            select(CategoryModel).where(CategoryModel.sort_order == 2)
        )

    assert callback.answers == [("Подтверждено", None)]
    assert transaction_count == 1
    assert stored_event is not None
    assert stored_event.parse_status == BankEventParseStatus.CONFIRMED.value
    assert stored_event.transaction_id is not None
    assert stored_transaction is not None
    assert stored_category is not None
    assert stored_transaction.category_id == stored_category.id
