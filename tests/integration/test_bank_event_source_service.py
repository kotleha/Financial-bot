from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import BankEventBank, BankEventChannel, UserRole
from financial_bot.app.services.bank_event_source_service import (
    BankEventSourceService,
    generate_bank_event_source_token,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import BankEventSourceModel, Base
from financial_bot.app.storage.repositories.bank_event_repository import (
    hash_bank_event_source_token,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/bank-source.sqlite3"
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


def test_generated_bank_event_source_token_is_url_safe_and_nontrivial() -> None:
    token = generate_bank_event_source_token()

    assert len(token) >= 32
    assert " " not in token
    assert "\n" not in token


@pytest.mark.asyncio
async def test_bank_event_source_service_creates_idempotent_source_without_plain_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankEventSourceService(session)

        created = await service.provision_source(
            code="husband-sber-ios",
            bank=BankEventBank.SBER,
            channel=BankEventChannel.IOS_SHORTCUT,
            owner_role=UserRole.HUSBAND,
            token="source-token",
        )
        repeated = await service.provision_source(
            code="husband-sber-ios",
            bank=BankEventBank.SBER,
            channel=BankEventChannel.IOS_SHORTCUT,
            owner_role=UserRole.HUSBAND,
        )

        assert created.created
        assert not created.rotated
        assert created.token == "source-token"
        assert not repeated.created
        assert not repeated.rotated
        assert repeated.token is None
        assert repeated.source_id == created.source_id

        source = (await session.scalars(select(BankEventSourceModel))).one()
        assert source.token_hash == hash_bank_event_source_token("source-token")
        assert source.token_hash != "source-token"


@pytest.mark.asyncio
async def test_bank_event_source_service_rotates_existing_source_token(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankEventSourceService(session)
        created = await service.provision_source(
            code="wife-vtb-ios",
            bank=BankEventBank.VTB,
            channel=BankEventChannel.IOS_SHORTCUT,
            owner_role=UserRole.WIFE,
            token="old-token",
        )
        rotated = await service.provision_source(
            code="wife-vtb-ios",
            bank=BankEventBank.VTB,
            channel=BankEventChannel.IOS_SHORTCUT,
            owner_role=UserRole.WIFE,
            token="new-token",
            rotate=True,
        )

        assert rotated.source_id == created.source_id
        assert rotated.rotated
        assert rotated.token == "new-token"

        source = await session.get(BankEventSourceModel, created.source_id)
        assert source is not None
        assert source.token_hash == hash_bank_event_source_token("new-token")


@pytest.mark.asyncio
async def test_bank_event_source_service_creates_tbank_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankEventSourceService(session)

        created = await service.provision_source(
            code="wife-tbank-ios",
            bank=BankEventBank.TBANK,
            channel=BankEventChannel.IOS_SHORTCUT,
            owner_role=UserRole.WIFE,
            token="tbank-source-token",
        )

        assert created.created
        assert created.bank == BankEventBank.TBANK
        assert created.owner_role == UserRole.WIFE
        assert created.token == "tbank-source-token"

        source = (await session.scalars(select(BankEventSourceModel))).one()
        assert source.code == "wife-tbank-ios"
        assert source.bank == BankEventBank.TBANK.value
        assert source.token_hash == hash_bank_event_source_token("tbank-source-token")


@pytest.mark.asyncio
async def test_bank_event_source_service_rejects_existing_source_metadata_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankEventSourceService(session)
        await service.provision_source(
            code="phone-source",
            bank=BankEventBank.SBER,
            channel=BankEventChannel.IOS_SHORTCUT,
            owner_role=UserRole.HUSBAND,
            token="source-token",
        )

        with pytest.raises(ValueError, match="different bank, channel, or owner"):
            await service.provision_source(
                code="phone-source",
                bank=BankEventBank.VTB,
                channel=BankEventChannel.IOS_SHORTCUT,
                owner_role=UserRole.HUSBAND,
            )
