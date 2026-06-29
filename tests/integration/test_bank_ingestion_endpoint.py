from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    BankEventBank,
    BankEventChannel,
    BankEventParseStatus,
    TransactionType,
)
from financial_bot.app.services.bank_ingestion_service import BankImportResult
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import (
    BankCategoryRuleModel,
    BankEventModel,
    BankEventSourceModel,
    Base,
    CategoryModel,
    TransactionModel,
    UserModel,
)
from financial_bot.app.storage.repositories.bank_event_repository import (
    hash_bank_event_source_token,
)
from financial_bot.app.web.main import create_app
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/bank-endpoint.sqlite3"
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield create_session_factory(engine)
    finally:
        await engine.dispose()


class FakeBankEventNotifier:
    def __init__(self) -> None:
        self.sent_event_ids: list[int] = []
        self.closed = False

    async def notify_new_event(
        self,
        *,
        session: AsyncSession,
        source_token: str,
        result: BankImportResult,
    ) -> bool:
        if result.is_duplicate:
            return False
        self.sent_event_ids.append(result.event_id)
        return True

    async def close(self) -> None:
        self.closed = True


class FailingBankEventNotifier:
    def __init__(self) -> None:
        self.closed = False

    async def notify_new_event(
        self,
        *,
        session: AsyncSession,
        source_token: str,
        result: BankImportResult,
    ) -> bool:
        raise RuntimeError("Telegram timeout")

    async def close(self) -> None:
        self.closed = True


class FailsThenSucceedsBankEventNotifier:
    def __init__(self) -> None:
        self.sent_event_ids: list[int] = []
        self.attempts = 0
        self.closed = False

    async def notify_new_event(
        self,
        *,
        session: AsyncSession,
        source_token: str,
        result: BankImportResult,
    ) -> bool:
        self.attempts += 1
        if self.attempts == 1:
            raise RuntimeError("Telegram timeout")
        self.sent_event_ids.append(result.event_id)
        return True

    async def close(self) -> None:
        self.closed = True


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
        bank_self_counterparty_aliases="SELF PERSON",
    )


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_rejects_missing_and_invalid_tokens(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        missing = await client.post("/bank-events", json={"text": _purchase_sms()})
        invalid = await client.post(
            "/bank-events",
            headers={"Authorization": "Bearer wrong-token"},
            json={"text": _purchase_sms()},
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert notifier.sent_event_ids == []

    async with session_factory() as session:
        event_count = await session.scalar(select(func.count()).select_from(BankEventModel))
    assert event_count == 0


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_stores_redacted_event_and_deduplicates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    received_at = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        first = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": _purchase_sms(),
                "sender": "900",
                "received_at": received_at.isoformat(),
            },
        )
        duplicate = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": _purchase_sms(),
                "sender": "900",
                "received_at": received_at.isoformat(),
            },
        )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    first_body = first.json()
    duplicate_body = duplicate.json()
    assert first_body["duplicate"] is False
    assert duplicate_body["duplicate"] is True
    assert duplicate_body["event_id"] == first_body["event_id"]
    assert first_body["operation_kind"] == "expense_candidate"
    assert first_body["parse_status"] == "needs_confirmation"
    assert first_body["amount_minor"] == 29_000
    assert first_body["suggested_category_code"] == "cosmetology_medicine"
    assert first_body["suggested_category_source"] == "parser_hint"
    assert first_body["telegram_notification_sent"] is True
    assert duplicate_body["telegram_notification_sent"] is False
    assert "text" not in first_body
    assert "redacted_text" not in first_body
    assert notifier.sent_event_ids == [first_body["event_id"]]
    assert notifier.closed

    async with session_factory() as session:
        events = list((await session.scalars(select(BankEventModel))).all())

    assert len(events) == 1
    event = events[0]
    assert event.channel == BankEventChannel.IOS_SHORTCUT.value
    assert event.redacted_text
    assert "MIR-1111" not in event.redacted_text
    assert "924.14" not in event.redacted_text
    assert token not in event.redacted_text
    assert event.telegram_notification_sent_at is not None
    assert event.telegram_notification_failed_at is None
    assert event.telegram_notification_attempts == 1


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_accepts_ios_shortcut_message_object(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": [
                    {
                        "sender": "9-00",
                        "body": _purchase_sms(),
                    }
                ],
                "sender": {"value": "9-00"},
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_kind"] == "expense_candidate"
    assert body["parse_status"] == "needs_confirmation"
    assert body["amount_minor"] == 29_000
    assert body["telegram_notification_sent"] is True


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_stores_event_when_notification_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FailingBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": _purchase_sms(), "sender": "900"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_kind"] == "expense_candidate"
    assert body["parse_status"] == "needs_confirmation"
    assert body["telegram_notification_sent"] is False
    assert notifier.closed

    async with session_factory() as session:
        event_count = await session.scalar(select(func.count()).select_from(BankEventModel))
        event = (await session.scalars(select(BankEventModel))).one()

    assert event_count == 1
    assert event.telegram_notification_sent_at is None
    assert event.telegram_notification_failed_at is not None
    assert event.telegram_notification_attempts == 1


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_retries_failed_notification_on_duplicate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FailsThenSucceedsBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)
    payload = {"text": _purchase_sms(), "sender": "900"}

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        first = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        retry = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

    assert first.status_code == 200
    assert retry.status_code == 200
    first_body = first.json()
    retry_body = retry.json()
    assert first_body["telegram_notification_sent"] is False
    assert retry_body["duplicate"] is True
    assert retry_body["event_id"] == first_body["event_id"]
    assert retry_body["telegram_notification_sent"] is True
    assert notifier.sent_event_ids == [first_body["event_id"]]
    assert notifier.attempts == 2

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.telegram_notification_sent_at is not None
    assert event.telegram_notification_failed_at is None
    assert event.telegram_notification_attempts == 2


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_sends_refund_correction_notification_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": (
                    "Счёт карты MIR-1111 09:38 Возврат покупки по СБП "
                    "1794р Gloria Jeans Баланс: 999р"
                ),
                "sender": "900",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_kind"] == "refund"
    assert body["parse_status"] == "parsed"
    assert body["requires_confirmation"] is False
    assert body["telegram_notification_sent"] is True
    assert notifier.sent_event_ids == [body["event_id"]]

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.operation_kind == "refund"
    assert event.parse_status == "parsed"
    assert event.telegram_notification_sent_at is not None
    assert event.telegram_notification_failed_at is None
    assert event.telegram_notification_attempts == 1


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_sends_income_notification_once_without_raw_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)
    payload = {
        "text": "СЧЁТ1111 05:37 Зачисление 1471.20р Баланс: 999р",
        "sender": "900",
    }

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        first = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        duplicate = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    first_body = first.json()
    duplicate_body = duplicate.json()
    assert first_body["operation_kind"] == "income"
    assert first_body["parse_status"] == "parsed"
    assert first_body["requires_confirmation"] is False
    assert first_body["telegram_notification_sent"] is True
    assert duplicate_body["duplicate"] is True
    assert duplicate_body["telegram_notification_sent"] is False
    assert "text" not in first_body
    assert "redacted_text" not in first_body
    assert "1111" not in str(first_body)
    assert "999" not in str(first_body)
    assert token not in str(first_body)
    assert notifier.sent_event_ids == [first_body["event_id"]]

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.operation_kind == "income"
    assert event.parse_status == "parsed"
    assert event.telegram_notification_sent_at is not None
    assert event.telegram_notification_failed_at is None
    assert event.telegram_notification_attempts == 1


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_accepts_tbank_expense_candidate(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "tbank-source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.TBANK)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": ("Оплата СБП, счет RUB. 50 RUB. RESTORAN TEST Доступно 8765,25 RUB"),
                "sender": "T-Bank",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == "tbank"
    assert body["operation_kind"] == "expense_candidate"
    assert body["parse_status"] == "needs_confirmation"
    assert body["amount_minor"] == 5_000
    assert body["suggested_category_code"] == "restaurants_cafes"
    assert body["telegram_notification_sent"] is True
    assert notifier.sent_event_ids == [body["event_id"]]
    assert "text" not in body
    assert "redacted_text" not in body
    assert "8765" not in str(body)
    assert token not in str(body)

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.bank == BankEventBank.TBANK.value
    assert event.amount == 5_000
    assert event.merchant == "RESTORAN TEST"
    assert "8765" not in event.redacted_text


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_accepts_tbank_income(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "tbank-source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.TBANK)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Пополнение, счет RUB. 1400 RUB. EXTERNAL PERSON Доступно 4532,34 RUB",
                "sender": "T-Bank",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == "tbank"
    assert body["operation_kind"] == "income"
    assert body["parse_status"] == "parsed"
    assert body["amount_minor"] == 140_000
    assert body["telegram_notification_sent"] is True
    assert notifier.sent_event_ids == [body["event_id"]]

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.bank == BankEventBank.TBANK.value
    assert event.operation_kind == "income"
    assert event.parse_status == "parsed"
    assert event.counterparty is None
    assert "EXTERNAL PERSON" not in event.redacted_text
    assert "4532" not in event.redacted_text


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_autosaves_learned_expense_and_notifies(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    await _seed_learning_rule(session_factory, settings, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": _purchase_sms(), "sender": "900"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_kind"] == "expense_candidate"
    assert body["parse_status"] == "autosaved"
    assert body["requires_confirmation"] is False
    assert body["suggested_category_code"] == "groceries"
    assert body["suggested_category_source"] == "learned_rule"
    assert body["telegram_notification_sent"] is True
    assert notifier.sent_event_ids == [body["event_id"]]

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()
        transaction = (await session.scalars(select(TransactionModel))).one()

    assert event.parse_status == BankEventParseStatus.AUTOSAVED.value
    assert event.transaction_id == transaction.id
    assert transaction.type == TransactionType.EXPENSE.value
    assert transaction.amount == 29_000
    assert transaction.raw_text == f"bank_event_autosaved:{event.id}"
    assert event.telegram_notification_sent_at is not None
    assert event.telegram_notification_attempts == 1


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_does_not_resend_duplicate_refund(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)
    payload = {
        "text": (
            "Счёт карты MIR-1111 09:38 Возврат покупки по СБП 1794р Gloria Jeans Баланс: 999р"
        ),
        "sender": "900",
    }

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        first = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        duplicate = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert first.json()["telegram_notification_sent"] is True
    assert duplicate.json()["duplicate"] is True
    assert duplicate.json()["telegram_notification_sent"] is False
    assert notifier.sent_event_ids == [first.json()["event_id"]]


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_ignores_bank_source_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "sber-source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Оплата 1234р Карта*1111 GAZPROMNEFT AZS Баланс 999р 10:20",
                "sender": "900",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == "vtb"
    assert body["operation_kind"] == "ignored"
    assert body["parse_status"] == "ignored"
    assert body["telegram_notification_sent"] is False
    assert notifier.sent_event_ids == []

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.bank == BankEventBank.VTB.value
    assert event.parse_status == BankEventParseStatus.IGNORED.value


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_ignores_tbank_source_mismatch(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "sber-source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.SBER)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Оплата СБП, счет RUB. 50 RUB. RESTORAN TEST Доступно 5000,25 RUB",
                "sender": "T-Bank",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == "tbank"
    assert body["operation_kind"] == "ignored"
    assert body["parse_status"] == "ignored"
    assert body["telegram_notification_sent"] is False
    assert notifier.sent_event_ids == []


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_ignores_other_bank_text_through_tbank_source(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "tbank-source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.TBANK)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={"text": _purchase_sms()},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == "sber"
    assert body["operation_kind"] == "ignored"
    assert body["parse_status"] == "ignored"
    assert body["telegram_notification_sent"] is False
    assert notifier.sent_event_ids == []

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.bank == BankEventBank.SBER.value
    assert event.parse_status == BankEventParseStatus.IGNORED.value
    assert event.redacted_text == "<source_bank_mismatch:sber>"


@pytest.mark.asyncio
async def test_bank_ingestion_endpoint_ignores_service_messages_without_raw_code_storage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    token = "vtb-source-token"
    await _seed_source(session_factory, settings, token=token, bank=BankEventBank.VTB)
    notifier = FakeBankEventNotifier()
    app = create_app(settings=settings, session_factory=session_factory, notifier=notifier)

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        response = await client.post(
            "/bank-events",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "text": "Никому не сообщайте этот код для подтверждения: 123456. ВТБ",
                "sender": "VTB",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operation_kind"] == "ignored"
    assert body["parse_status"] == "ignored"
    assert body["telegram_notification_sent"] is False
    assert notifier.sent_event_ids == []

    async with session_factory() as session:
        event = (await session.scalars(select(BankEventModel))).one()

    assert event.parse_status == BankEventParseStatus.IGNORED.value
    assert "123456" not in event.redacted_text


async def _seed_source(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    token: str,
    bank: BankEventBank,
) -> None:
    async with session_factory() as session:
        await seed_initial_data(session, settings)
        owner = await session.scalar(
            select(UserModel).where(UserModel.telegram_id == settings.husband_telegram_id)
        )
        assert owner is not None
        session.add(
            BankEventSourceModel(
                code=f"ios-shortcut:{bank.value}:test",
                bank=bank.value,
                channel=BankEventChannel.IOS_SHORTCUT.value,
                owner_user_id=owner.id,
                token_hash=hash_bank_event_source_token(token),
            )
        )
        await session.commit()


async def _seed_learning_rule(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    *,
    bank: BankEventBank,
) -> None:
    async with session_factory() as session:
        owner = await session.scalar(
            select(UserModel).where(UserModel.telegram_id == settings.husband_telegram_id)
        )
        category = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "groceries")
        )
        assert owner is not None
        assert category is not None
        session.add(
            BankCategoryRuleModel(
                owner_user_id=owner.id,
                bank=bank.value,
                merchant_key="apteka test",
                merchant_display="APTEKA TEST",
                category_id=category.id,
                hit_count=2,
                is_active=True,
                last_confirmed_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
            )
        )
        await session.commit()


def _purchase_sms() -> str:
    return "Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р"
