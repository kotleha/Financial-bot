from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    BankEventOperationKind,
    BankEventParseStatus,
    BankEventSuggestionSource,
    TransactionSource,
    TransactionType,
)
from financial_bot.app.services.bank_ingestion_service import BankImportResult, BankIngestionService
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import (
    BankCategoryRuleModel,
    BankEventModel,
    BankEventSourceModel,
    Base,
    TransactionModel,
)
from financial_bot.app.storage.repositories.bank_event_repository import BankEventRepository
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/bank-ingestion.sqlite3"
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
        bank_self_counterparty_aliases="SELF PERSON",
    )


@pytest.mark.asyncio
async def test_manual_bank_sms_import_stores_redacted_event_and_deduplicates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    received_at = datetime(2026, 6, 26, 12, 0, tzinfo=UTC)
    sms_text = "Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р"

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        first_result = await service.import_manual_sms(
            text=sms_text,
            telegram_user_id=1001,
            received_at=received_at,
        )
        duplicate_result = await service.import_manual_sms(
            text=sms_text,
            telegram_user_id=1001,
            received_at=received_at,
        )

        assert first_result.event_id == duplicate_result.event_id
        assert not first_result.is_duplicate
        assert duplicate_result.is_duplicate
        assert first_result.operation_kind == BankEventOperationKind.EXPENSE_CANDIDATE
        assert first_result.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION
        assert first_result.suggested_category_code == "cosmetology_medicine"
        assert first_result.suggested_category_source == BankEventSuggestionSource.PARSER_HINT

        event = await session.get(BankEventModel, first_result.event_id)
        assert event is not None
        assert event.redacted_text == first_result.redacted_text
        assert "MIR-1111" not in event.redacted_text
        assert "924.14" not in event.redacted_text
        assert event.merchant == "APTEKA TEST"
        assert event.counterparty is None
        assert event.source == TransactionSource.CARD.value
        assert event.occurred_at == datetime(2026, 6, 26, 11, 9)

        sources = list((await session.scalars(select(BankEventSourceModel))).all())
        assert len(sources) == 1
        assert sources[0].code.startswith("manual-telegram:")
        assert sources[0].last_seen_at == received_at.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_manual_bank_sms_import_marks_self_counterparty_as_internal_transfer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)

        result = await BankIngestionService(session, settings).import_manual_sms(
            text="Списание 16910р Счет*1111 SELF PERSON Баланс 999р 20:53",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        assert result.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER
        assert result.parse_status == BankEventParseStatus.PARSED
        assert result.suggested_category_code == "internal_transfer"

        event = await session.get(BankEventModel, result.event_id)
        assert event is not None
        assert event.counterparty == "self"
        assert "SELF PERSON" not in event.redacted_text


@pytest.mark.asyncio
async def test_manual_bank_sms_import_ignores_service_messages(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)

        result = await BankIngestionService(session, settings).import_manual_sms(
            text="Никому не сообщайте этот код для подтверждения: 123456. ВТБ",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        assert result.operation_kind == BankEventOperationKind.IGNORED
        assert result.parse_status == BankEventParseStatus.IGNORED
        assert "123456" not in result.redacted_text


@pytest.mark.asyncio
async def test_manual_bank_income_can_create_idempotent_income_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        result = await service.import_manual_sms(
            text="СЧЁТ1111 05:37 Зачисление 1471,20р Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        pending = await service.list_pending_confirmation_events(telegram_user_id=1001)
        confirmed = await service.confirm_income_event(
            event_id=result.event_id,
            telegram_user_id=1001,
        )
        confirmed_again = await service.confirm_income_event(
            event_id=result.event_id,
            telegram_user_id=1001,
        )

        assert result.operation_kind == BankEventOperationKind.INCOME
        assert result.parse_status == BankEventParseStatus.PARSED
        assert not result.requires_confirmation
        assert result.suggested_category_code is None
        assert pending == []
        assert confirmed.transaction is not None
        assert confirmed.transaction.amount == 147_120
        assert confirmed.transaction.category_code == "income_general"
        assert not confirmed.transaction.included_in_reports
        assert confirmed_again.already_confirmed
        assert confirmed_again.transaction is None

        event = await session.get(BankEventModel, result.event_id)
        assert event is not None
        assert event.operation_kind == BankEventOperationKind.INCOME.value
        assert event.parse_status == BankEventParseStatus.CONFIRMED.value
        assert event.transaction_id == confirmed.transaction.id

        saved_transaction = await session.get(TransactionModel, confirmed.transaction.id)
        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        assert saved_transaction is not None
        assert saved_transaction.type == TransactionType.INCOME.value
        assert saved_transaction.raw_text == f"bank_income_event:{result.event_id}"
        assert saved_transaction.comment == f"bank_event:{result.event_id}"
        assert "СЧЁТ1111" not in (saved_transaction.raw_text or "")
        assert "999" not in (saved_transaction.raw_text or "")
        assert not saved_transaction.included_in_reports
        assert saved_transaction.source == TransactionSource.TRANSFER.value
        assert transaction_count == 1


@pytest.mark.asyncio
async def test_tbank_events_without_operation_time_dedupe_within_received_date_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()
    sms_text = 'Оплата СБП, счет RUB. 1855 RUB. ООО "SOLNE". Доступно 26638,34 RUB'

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        first = await service.import_manual_sms(
            text=sms_text,
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 3, 0, tzinfo=UTC),
        )
        duplicate_same_day = await service.import_manual_sms(
            text=sms_text,
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 6, 0, tzinfo=UTC),
        )
        next_day = await service.import_manual_sms(
            text=sms_text,
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 27, 3, 0, tzinfo=UTC),
        )

        first_event = await session.get(BankEventModel, first.event_id)
        next_day_event = await session.get(BankEventModel, next_day.event_id)
        categories = await service.list_expense_categories()
        restaurants = next(
            category for category in categories if category.code == "restaurants_cafes"
        )
        await service.update_event_category(
            event_id=first.event_id,
            category_id=restaurants.id,
            telegram_user_id=1001,
        )
        confirmed = await service.confirm_event(event_id=first.event_id, telegram_user_id=1001)
        assert confirmed.transaction is not None
        confirmed_transaction = await session.get(TransactionModel, confirmed.transaction.id)

        assert not first.is_duplicate
        assert duplicate_same_day.is_duplicate
        assert duplicate_same_day.event_id == first.event_id
        assert not next_day.is_duplicate
        assert next_day.event_id != first.event_id
        assert first_event is not None
        assert next_day_event is not None
        assert first_event.occurred_at is None
        assert next_day_event.occurred_at is None
        assert first_event.source == TransactionSource.TRANSFER.value
        assert confirmed_transaction is not None
        assert confirmed_transaction.source == TransactionSource.TRANSFER.value


@pytest.mark.asyncio
async def test_income_confirmation_cleans_up_transaction_when_atomic_link_loses_race(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()

    async def fail_link(
        self: BankEventRepository,
        *,
        event_id: int,
        transaction_id: int,
        status: BankEventParseStatus,
        allowed_statuses: tuple[BankEventParseStatus, ...],
    ) -> bool:
        return False

    monkeypatch.setattr(BankEventRepository, "try_link_transaction", fail_link)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        imported = await service.import_manual_sms(
            text="СЧЁТ1111 05:37 Зачисление 1471,20р Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="уже изменилось"):
            await service.confirm_income_event(
                event_id=imported.event_id,
                telegram_user_id=1001,
            )

        transactions = list((await session.scalars(select(TransactionModel))).all())
        event = await session.get(BankEventModel, imported.event_id)

        assert len(transactions) == 1
        assert transactions[0].type == TransactionType.INCOME.value
        assert transactions[0].deleted_at is not None
        assert event is not None
        assert event.transaction_id is None
        assert event.parse_status == BankEventParseStatus.PARSED.value


@pytest.mark.asyncio
async def test_deleted_income_link_can_be_confirmed_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        transactions = TransactionService(session, settings)
        imported = await service.import_manual_sms(
            text="СЧЁТ1111 05:37 Зачисление 1471,20р Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        first = await service.confirm_income_event(
            event_id=imported.event_id,
            telegram_user_id=1001,
        )
        assert first.transaction is not None

        undone = await transactions.undo_last_transaction(changed_by_telegram_id=1001)
        second = await service.confirm_income_event(
            event_id=imported.event_id,
            telegram_user_id=1001,
        )

        event = await session.get(BankEventModel, imported.event_id)
        saved_first = await session.get(TransactionModel, first.transaction.id)
        saved_second = await session.get(TransactionModel, second.transaction.id)
        all_transactions = list((await session.scalars(select(TransactionModel))).all())

    assert undone is not None
    assert undone.id == first.transaction.id
    assert second.transaction is not None
    assert second.transaction.id != first.transaction.id
    assert event is not None
    assert event.transaction_id == second.transaction.id
    assert event.parse_status == BankEventParseStatus.CONFIRMED.value
    assert saved_first is not None
    assert saved_first.deleted_at is not None
    assert saved_second is not None
    assert saved_second.type == TransactionType.INCOME.value
    assert saved_second.deleted_at is None
    assert len(all_transactions) == 2


@pytest.mark.asyncio
async def test_manual_bank_refund_is_stored_as_event_without_transaction_or_pending_card(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        result = await service.import_manual_sms(
            text=(
                "Счёт карты MIR-1111 09:38 Возврат покупки по СБП 1794р Gloria Jeans Баланс: 999р"
            ),
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        pending = await service.list_pending_confirmation_events(telegram_user_id=1001)

        assert result.operation_kind == BankEventOperationKind.REFUND
        assert result.parse_status == BankEventParseStatus.PARSED
        assert not result.requires_confirmation
        assert pending == []

        event = await session.get(BankEventModel, result.event_id)
        assert event is not None
        assert event.operation_kind == BankEventOperationKind.REFUND.value
        assert event.parse_status == BankEventParseStatus.PARSED.value
        assert event.transaction_id is None

        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        assert transaction_count == 0


@pytest.mark.asyncio
async def test_bank_refund_can_create_idempotent_correction_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 09:38 Возврат покупки по СБП 300р APTEKA TEST Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        corrected = await service.create_refund_correction(
            event_id=imported.event_id,
            telegram_user_id=1001,
        )
        corrected_again = await service.create_refund_correction(
            event_id=imported.event_id,
            telegram_user_id=1001,
        )

        assert imported.operation_kind == BankEventOperationKind.REFUND
        assert imported.parse_status == BankEventParseStatus.PARSED
        assert imported.suggested_category_code == "cosmetology_medicine"
        assert corrected.transaction is not None
        assert corrected.transaction.amount == 30_000
        assert corrected.transaction.category_code == "cosmetology_medicine"
        assert corrected_again.already_confirmed
        assert corrected_again.transaction is None

        event = await session.get(BankEventModel, imported.event_id)
        assert event is not None
        assert event.transaction_id == corrected.transaction.id
        assert event.parse_status == BankEventParseStatus.CONFIRMED.value

        saved_transaction = await session.get(TransactionModel, corrected.transaction.id)
        assert saved_transaction is not None
        assert saved_transaction.type == TransactionType.CORRECTION.value
        assert saved_transaction.amount == 30_000
        assert saved_transaction.included_in_reports

        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        assert transaction_count == 1


@pytest.mark.asyncio
async def test_rejected_bank_refund_cannot_create_correction_from_stale_callback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 09:38 Возврат покупки по СБП 300р APTEKA TEST Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        await service.reject_event(event_id=imported.event_id, telegram_user_id=1001)

        with pytest.raises(ValueError, match="не требующее действий"):
            await service.create_refund_correction(
                event_id=imported.event_id,
                telegram_user_id=1001,
            )

        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        event = await session.get(BankEventModel, imported.event_id)
        assert transaction_count == 0
        assert event is not None
        assert event.parse_status == BankEventParseStatus.REJECTED.value
        assert event.transaction_id is None


@pytest.mark.asyncio
async def test_rejected_bank_refund_cannot_be_reopened_by_category_stale_callback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        category = next(
            category
            for category in await service.list_expense_categories()
            if category.code == "cosmetology_medicine"
        )

        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 09:38 Возврат покупки по СБП 300р APTEKA TEST Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        await service.reject_event(event_id=imported.event_id, telegram_user_id=1001)

        with pytest.raises(ValueError, match="не требующее действий"):
            await service.update_event_category(
                event_id=imported.event_id,
                category_id=category.id,
                telegram_user_id=1001,
            )

        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        event = await session.get(BankEventModel, imported.event_id)
        assert transaction_count == 0
        assert event is not None
        assert event.parse_status == BankEventParseStatus.REJECTED.value
        assert event.transaction_id is None


@pytest.mark.asyncio
async def test_rejected_expense_candidate_cannot_be_confirmed_from_stale_callback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)

        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        await service.reject_event(event_id=imported.event_id, telegram_user_id=1001)

        with pytest.raises(ValueError, match="не требующее действий"):
            await service.confirm_event(event_id=imported.event_id, telegram_user_id=1001)

        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        event = await session.get(BankEventModel, imported.event_id)
        assert transaction_count == 0
        assert event is not None
        assert event.parse_status == BankEventParseStatus.REJECTED.value
        assert event.transaction_id is None


@pytest.mark.asyncio
async def test_confirm_bank_event_creates_transaction_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        confirmed = await service.confirm_event(event_id=imported.event_id, telegram_user_id=1001)
        confirmed_again = await service.confirm_event(
            event_id=imported.event_id,
            telegram_user_id=1001,
        )

        assert confirmed.transaction is not None
        assert confirmed.transaction.amount == 29_000
        assert confirmed.transaction.category_code == "cosmetology_medicine"
        assert confirmed_again.already_confirmed
        assert confirmed_again.transaction is None

        event = await session.get(BankEventModel, imported.event_id)
        assert event is not None
        assert event.transaction_id == confirmed.transaction.id
        assert event.parse_status == BankEventParseStatus.CONFIRMED.value
        assert event.occurred_at == datetime(2026, 6, 26, 11, 9)
        assert confirmed.transaction.occurred_at == datetime(2026, 6, 26, 11, 9)

        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        assert transaction_count == 1


@pytest.mark.asyncio
async def test_confirm_bank_event_cleans_up_transaction_when_atomic_link_loses_race(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()

    async def fail_link(
        self: BankEventRepository,
        *,
        event_id: int,
        transaction_id: int,
        status: BankEventParseStatus,
        allowed_statuses: tuple[BankEventParseStatus, ...],
    ) -> bool:
        return False

    monkeypatch.setattr(BankEventRepository, "try_link_transaction", fail_link)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="уже изменилось"):
            await service.confirm_event(event_id=imported.event_id, telegram_user_id=1001)

        transactions = list((await session.scalars(select(TransactionModel))).all())
        rules_count = await session.scalar(select(func.count()).select_from(BankCategoryRuleModel))
        event = await session.get(BankEventModel, imported.event_id)

        assert len(transactions) == 1
        assert transactions[0].deleted_at is not None
        assert rules_count == 0
        assert event is not None
        assert event.transaction_id is None
        assert event.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION.value


@pytest.mark.asyncio
async def test_refund_correction_cleans_up_transaction_when_atomic_link_loses_race(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = make_settings()

    async def fail_link(
        self: BankEventRepository,
        *,
        event_id: int,
        transaction_id: int,
        status: BankEventParseStatus,
        allowed_statuses: tuple[BankEventParseStatus, ...],
    ) -> bool:
        return False

    monkeypatch.setattr(BankEventRepository, "try_link_transaction", fail_link)

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 09:38 Возврат покупки по СБП 300р APTEKA TEST Баланс: 999р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="уже изменилось"):
            await service.create_refund_correction(
                event_id=imported.event_id,
                telegram_user_id=1001,
            )

        transactions = list((await session.scalars(select(TransactionModel))).all())
        event = await session.get(BankEventModel, imported.event_id)

        assert len(transactions) == 1
        assert transactions[0].type == TransactionType.CORRECTION.value
        assert transactions[0].deleted_at is not None
        assert event is not None
        assert event.transaction_id is None
        assert event.parse_status == BankEventParseStatus.PARSED.value


@pytest.mark.asyncio
async def test_bank_event_near_midnight_uses_previous_day_when_sms_is_delayed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        imported = await BankIngestionService(session, settings).import_manual_sms(
            text="Оплата 100р Карта*1111 GAZPROMNEFT AZS Баланс 999р 23:58",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 27, 0, 2, tzinfo=UTC),
        )

        event = await session.get(BankEventModel, imported.event_id)

    assert event is not None
    assert event.occurred_at == datetime(2026, 6, 26, 23, 58)


@pytest.mark.asyncio
async def test_bank_event_dedupe_v2_ignores_balance_and_card_suffix_variants(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        first = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        duplicate = await service.import_manual_sms(
            text="Счёт карты MIR-2222 11:09 Покупка 290р APTEKA TEST Баланс: 1000.00р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 5, tzinfo=UTC),
        )

        event_count = await session.scalar(select(func.count()).select_from(BankEventModel))

    assert first.event_id == duplicate.event_id
    assert not first.is_duplicate
    assert duplicate.is_duplicate
    assert event_count == 1


@pytest.mark.asyncio
async def test_bank_event_category_can_be_selected_before_confirm(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р UNKNOWN SHOP Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        with pytest.raises(ValueError, match="Сначала выберите категорию"):
            await service.confirm_event(event_id=imported.event_id, telegram_user_id=1001)

        categories = await service.list_expense_categories()
        groceries = next(category for category in categories if category.code == "groceries")
        updated = await service.update_event_category(
            event_id=imported.event_id,
            category_id=groceries.id,
            telegram_user_id=1001,
        )
        confirmed = await service.confirm_event(event_id=imported.event_id, telegram_user_id=1001)

        assert updated.suggested_category_code == "groceries"
        assert updated.suggested_category_source == BankEventSuggestionSource.MANUAL
        assert confirmed.transaction is not None
        assert confirmed.transaction.category_code == "groceries"


@pytest.mark.asyncio
async def test_confirmed_bank_event_autosaves_after_second_confirmation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        first = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р UNKNOWN SHOP Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        categories = await service.list_expense_categories()
        groceries = next(category for category in categories if category.code == "groceries")
        await service.update_event_category(
            event_id=first.event_id,
            category_id=groceries.id,
            telegram_user_id=1001,
        )
        confirmed = await service.confirm_event(event_id=first.event_id, telegram_user_id=1001)

        second = await service.import_manual_sms(
            text="Счёт карты MIR-2222 11:10 Покупка 150р UNKNOWN SHOP Баланс: 774.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 2, tzinfo=UTC),
        )
        second_confirmed = await service.confirm_event(
            event_id=second.event_id,
            telegram_user_id=1001,
        )
        third = await service.import_manual_sms(
            text="Счёт карты MIR-3333 11:11 Покупка 120р UNKNOWN SHOP Баланс: 654.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 4, tzinfo=UTC),
        )
        rules = list((await session.scalars(select(BankCategoryRuleModel))).all())

        assert second.suggested_category_code == "groceries"
        assert second.suggested_category_source == BankEventSuggestionSource.LEARNED_RULE
        assert second.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION
        assert second.requires_confirmation
        assert third.suggested_category_code == "groceries"
        assert third.suggested_category_source == BankEventSuggestionSource.LEARNED_RULE
        assert third.parse_status == BankEventParseStatus.AUTOSAVED
        assert not third.requires_confirmation
        assert confirmed.learning_rule is not None
        assert confirmed.learning_rule.action == "created"
        assert confirmed.learning_rule.merchant_display == "UNKNOWN SHOP"
        assert confirmed.learning_rule.category_title == "Продукты"
        assert confirmed.learning_rule.hit_count == 1
        assert second_confirmed.learning_rule is not None
        assert second_confirmed.learning_rule.action == "reinforced"
        assert second_confirmed.learning_rule.hit_count == 2
        assert len(rules) == 1
        assert rules[0].merchant_key == "unknown shop"
        assert rules[0].hit_count == 2
        assert rules[0].last_used_at == datetime(2026, 6, 26, 12, 4)

        event = await session.get(BankEventModel, third.event_id)
        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))
        autosaved_transaction = (
            await session.scalars(
                select(TransactionModel).where(
                    TransactionModel.raw_text == f"bank_event_autosaved:{third.event_id}"
                )
            )
        ).one()
        pending = await service.list_pending_confirmation_events(telegram_user_id=1001)

        assert event is not None
        assert event.transaction_id == autosaved_transaction.id
        assert event.parse_status == BankEventParseStatus.AUTOSAVED.value
        assert autosaved_transaction.type == TransactionType.EXPENSE.value
        assert autosaved_transaction.amount == 12_000
        assert transaction_count == 3
        assert pending == []


@pytest.mark.asyncio
async def test_autosaved_bank_event_is_idempotent_and_cannot_be_reconfirmed(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        categories = await service.list_expense_categories()
        groceries = next(category for category in categories if category.code == "groceries")

        first = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р UNKNOWN SHOP Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        await service.update_event_category(
            event_id=first.event_id,
            category_id=groceries.id,
            telegram_user_id=1001,
        )
        first_confirmed = await service.confirm_event(
            event_id=first.event_id,
            telegram_user_id=1001,
        )

        second = await service.import_manual_sms(
            text="Счёт карты MIR-2222 11:10 Покупка 150р UNKNOWN SHOP Баланс: 774.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 2, tzinfo=UTC),
        )
        second_confirmed = await service.confirm_event(
            event_id=second.event_id,
            telegram_user_id=1001,
        )
        third = await service.import_manual_sms(
            text="Счёт карты MIR-3333 11:11 Покупка 120р UNKNOWN SHOP Баланс: 654.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 4, tzinfo=UTC),
        )
        duplicate = await service.import_manual_sms(
            text="Счёт карты MIR-3333 11:11 Покупка 120р UNKNOWN SHOP Баланс: 654.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 4, tzinfo=UTC),
        )
        rule = (await session.scalars(select(BankCategoryRuleModel))).one()
        transaction_count = await session.scalar(select(func.count()).select_from(TransactionModel))

        assert second.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION
        assert third.parse_status == BankEventParseStatus.AUTOSAVED
        assert duplicate.is_duplicate
        assert duplicate.event_id == third.event_id
        assert duplicate.parse_status == BankEventParseStatus.AUTOSAVED
        assert first_confirmed.learning_rule is not None
        assert first_confirmed.learning_rule.action == "created"
        assert second_confirmed.learning_rule is not None
        assert second_confirmed.learning_rule.action == "reinforced"
        assert rule.hit_count == 2
        assert transaction_count == 3

        repeated = await service.confirm_event(event_id=third.event_id, telegram_user_id=1001)
        assert repeated.already_confirmed
        assert repeated.transaction is None


@pytest.mark.asyncio
async def test_autosaved_bank_event_category_update_changes_transaction_and_rule(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        third = await _create_autosaved_unknown_shop_event(service)
        categories = await service.list_expense_categories()
        restaurants = next(
            category for category in categories if category.code == "restaurants_cafes"
        )

        updated = await service.update_event_category(
            event_id=third.event_id,
            category_id=restaurants.id,
            telegram_user_id=1001,
        )

        event = await session.get(BankEventModel, third.event_id)
        transaction = (
            await session.scalars(
                select(TransactionModel).where(
                    TransactionModel.raw_text == f"bank_event_autosaved:{third.event_id}"
                )
            )
        ).one()
        rule = (await session.scalars(select(BankCategoryRuleModel))).one()

        assert updated.parse_status == BankEventParseStatus.AUTOSAVED
        assert updated.suggested_category_code == "restaurants_cafes"
        assert updated.suggested_category_source == BankEventSuggestionSource.MANUAL
        assert event is not None
        assert event.transaction_id == transaction.id
        assert event.parse_status == BankEventParseStatus.AUTOSAVED.value
        assert transaction.category_id == restaurants.id
        assert transaction.deleted_at is None
        assert rule.category_id == restaurants.id
        assert rule.hit_count == 1


@pytest.mark.asyncio
async def test_autosaved_bank_event_can_be_marked_internal_transfer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        third = await _create_autosaved_unknown_shop_event(service)
        event = await session.get(BankEventModel, third.event_id)
        assert event is not None
        transaction_id = event.transaction_id
        assert transaction_id is not None

        updated = await service.mark_event_internal_transfer(
            event_id=third.event_id,
            telegram_user_id=1001,
        )

        transaction = await session.get(TransactionModel, transaction_id)
        refreshed_event = await session.get(BankEventModel, third.event_id)

        assert updated.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER
        assert updated.parse_status == BankEventParseStatus.PARSED
        assert updated.suggested_category_code == "internal_transfer"
        assert transaction is not None
        assert transaction.deleted_at is not None
        assert refreshed_event is not None
        assert refreshed_event.transaction_id is None
        assert refreshed_event.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER.value


@pytest.mark.asyncio
async def test_autosaved_bank_event_can_be_deleted_without_disabling_rule(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        third = await _create_autosaved_unknown_shop_event(service)
        event = await session.get(BankEventModel, third.event_id)
        assert event is not None
        transaction_id = event.transaction_id
        assert transaction_id is not None

        rejected = await service.reject_event(event_id=third.event_id, telegram_user_id=1001)

        transaction = await session.get(TransactionModel, transaction_id)
        refreshed_event = await session.get(BankEventModel, third.event_id)
        rule = (await session.scalars(select(BankCategoryRuleModel))).one()

        assert rejected.parse_status == BankEventParseStatus.REJECTED
        assert transaction is not None
        assert transaction.deleted_at is not None
        assert refreshed_event is not None
        assert refreshed_event.transaction_id is None
        assert refreshed_event.parse_status == BankEventParseStatus.REJECTED.value
        assert rule.is_active


@pytest.mark.asyncio
async def test_autosaved_bank_event_rule_can_be_disabled_from_event_card(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        third = await _create_autosaved_unknown_shop_event(service)
        event = await session.get(BankEventModel, third.event_id)
        assert event is not None
        transaction_id = event.transaction_id
        assert transaction_id is not None

        disabled = await service.disable_autosave_rule_for_event(
            event_id=third.event_id,
            telegram_user_id=1001,
        )

        transaction = await session.get(TransactionModel, transaction_id)
        rule = (await session.scalars(select(BankCategoryRuleModel))).one()

        assert disabled.parse_status == BankEventParseStatus.AUTOSAVED
        assert rule.is_active is False
        assert transaction is not None
        assert transaction.deleted_at is None


@pytest.mark.asyncio
async def test_pending_confirmation_events_are_owned_and_retryable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )

        pending = await service.list_pending_confirmation_events(telegram_user_id=1001)
        pending_for_wife = await service.list_pending_confirmation_events(telegram_user_id=1002)
        retry_payload = await service.get_pending_confirmation_event(
            event_id=imported.event_id,
            telegram_user_id=1001,
        )

        assert [event.event_id for event in pending] == [imported.event_id]
        assert pending_for_wife == []
        assert retry_payload.event_id == imported.event_id
        assert retry_payload.suggested_category_code == "cosmetology_medicine"

        await service.mark_telegram_notification_sent(
            event_id=imported.event_id,
            sent_at=datetime(2026, 6, 26, 12, 1, tzinfo=UTC),
        )
        event = await session.get(BankEventModel, imported.event_id)
        assert event is not None
        assert event.telegram_notification_attempts == 1
        assert event.telegram_notification_sent_at == datetime(2026, 6, 26, 12, 1)

        await service.confirm_event(event_id=imported.event_id, telegram_user_id=1001)
        assert await service.list_pending_confirmation_events(telegram_user_id=1001) == []
        with pytest.raises(ValueError, match="не ожидает подтверждения"):
            await service.get_pending_confirmation_event(
                event_id=imported.event_id,
                telegram_user_id=1001,
            )
        with pytest.raises(ValueError, match="not available"):
            await service.get_pending_confirmation_event(
                event_id=imported.event_id,
                telegram_user_id=1002,
            )


@pytest.mark.asyncio
async def test_reject_and_internal_transfer_actions_do_not_create_transactions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = BankIngestionService(session, settings)
        expense = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        transfer = await service.import_manual_sms(
            text="Списание 16910р Счет*1111 EXTERNAL PERSON Баланс 999р 20:53",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 1, tzinfo=UTC),
        )

        rejected = await service.reject_event(event_id=expense.event_id, telegram_user_id=1001)
        internal = await service.mark_event_internal_transfer(
            event_id=transfer.event_id,
            telegram_user_id=1001,
        )

        assert rejected.parse_status == BankEventParseStatus.REJECTED
        assert internal.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER
        assert internal.parse_status == BankEventParseStatus.PARSED
        assert internal.suggested_category_code == "internal_transfer"


@pytest.mark.asyncio
async def test_stale_reject_cannot_overwrite_confirmed_bank_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as setup_session:
        await seed_initial_data(setup_session, settings)
        service = BankIngestionService(setup_session, settings)
        imported = await service.import_manual_sms(
            text="Счёт карты MIR-1111 11:09 Покупка 290р APTEKA TEST Баланс: 924.14р",
            telegram_user_id=1001,
            received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
        )
        await setup_session.commit()

    async with session_factory() as stale_session:
        stale_service = BankIngestionService(stale_session, settings)
        stale_event = await stale_session.get(BankEventModel, imported.event_id)
        assert stale_event is not None
        assert stale_event.transaction_id is None

        async with session_factory() as confirm_session:
            confirmed = await BankIngestionService(confirm_session, settings).confirm_event(
                event_id=imported.event_id,
                telegram_user_id=1001,
            )
            assert confirmed.transaction is not None
            await confirm_session.commit()

        with pytest.raises(ValueError, match="уже учтено"):
            await stale_service.reject_event(event_id=imported.event_id, telegram_user_id=1001)
        await stale_session.rollback()

    async with session_factory() as check_session:
        event = await check_session.get(BankEventModel, imported.event_id)
        assert event is not None
        assert event.parse_status == BankEventParseStatus.CONFIRMED.value
        assert event.transaction_id is not None


async def _create_autosaved_unknown_shop_event(
    service: BankIngestionService,
) -> BankImportResult:
    categories = await service.list_expense_categories()
    groceries = next(category for category in categories if category.code == "groceries")

    first = await service.import_manual_sms(
        text="Счёт карты MIR-1111 11:09 Покупка 290р UNKNOWN SHOP Баланс: 924.14р",
        telegram_user_id=1001,
        received_at=datetime(2026, 6, 26, 12, 0, tzinfo=UTC),
    )
    await service.update_event_category(
        event_id=first.event_id,
        category_id=groceries.id,
        telegram_user_id=1001,
    )
    await service.confirm_event(event_id=first.event_id, telegram_user_id=1001)

    second = await service.import_manual_sms(
        text="Счёт карты MIR-2222 11:10 Покупка 150р UNKNOWN SHOP Баланс: 774.14р",
        telegram_user_id=1001,
        received_at=datetime(2026, 6, 26, 12, 2, tzinfo=UTC),
    )
    await service.confirm_event(event_id=second.event_id, telegram_user_id=1001)

    third = await service.import_manual_sms(
        text="Счёт карты MIR-3333 11:11 Покупка 120р UNKNOWN SHOP Баланс: 654.14р",
        telegram_user_id=1001,
        received_at=datetime(2026, 6, 26, 12, 4, tzinfo=UTC),
    )
    assert third.parse_status == BankEventParseStatus.AUTOSAVED
    return third
