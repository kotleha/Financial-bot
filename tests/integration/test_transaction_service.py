from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    AuditAction,
    TransactionScope,
    TransactionSource,
    TransactionType,
)
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.services.transaction_service import TransactionService
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import Base, CategoryAliasModel, CategoryModel
from financial_bot.app.storage.repositories.audit_repository import AuditRepository
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    pytest.importorskip("aiosqlite")
    database_url = f"sqlite+aiosqlite:///{tmp_path}/transactions.sqlite3"
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
async def test_create_transaction_from_category_selection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)
        categories = await service.list_category_options()
        groceries = next(category for category in categories if category.code == "groceries")

        summary = await service.create_from_category_selection(
            amount=350000,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="3500",
        )
        await session.commit()

    async with session_factory() as session:
        transactions = TransactionRepository(session)
        audit = AuditRepository(session)
        saved = await transactions.get(summary.id)
        audit_logs = await audit.list_for_transaction(summary.id)

        assert saved is not None
        assert saved.amount == 350000
        assert saved.type == TransactionType.EXPENSE.value
        assert saved.scope == TransactionScope.HOUSEHOLD.value
        assert saved.included_in_reports
        assert summary.payer_role == "husband"
        assert summary.category_code == "groceries"
        assert [log.action for log in audit_logs] == [AuditAction.CREATE.value]
        assert audit_logs[0].old_value is None
        assert audit_logs[0].new_value is not None
        assert audit_logs[0].new_value["amount"] == 350000


@pytest.mark.asyncio
async def test_create_correction_transaction_and_repeat_does_not_turn_it_into_expense(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)
        groceries = next(
            category
            for category in await service.list_category_options()
            if category.code == "groceries"
        )

        correction = await service.create_correction_from_category_selection(
            amount=50_000,
            category_id=groceries.id,
            payer_telegram_id=1001,
            raw_text="bank_refund_event:1",
            comment="refund",
            source=TransactionSource.CARD,
        )
        repeated = await service.repeat_last_transaction(changed_by_telegram_id=1001)
        await service.update_transaction(
            transaction_id=correction.id,
            changed_by_telegram_id=1001,
            category_id=groceries.id,
        )
        await session.commit()

    async with session_factory() as session:
        saved = await TransactionRepository(session).get(correction.id)

    assert saved is not None
    assert saved.amount == 50_000
    assert saved.type == TransactionType.CORRECTION.value
    assert saved.included_in_reports
    assert repeated is None


@pytest.mark.asyncio
async def test_create_income_transaction_and_repeat_does_not_turn_it_into_transfer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        income = await service.create_income(
            amount=100_000_00,
            recipient_telegram_id=1001,
            raw_text="bank_income_event:1",
            category_code="income_salary",
            comment="salary",
            source=TransactionSource.CARD,
        )
        repeated = await service.repeat_last_transaction(changed_by_telegram_id=1001)
        await service.update_transaction(
            transaction_id=income.id,
            changed_by_telegram_id=1001,
            amount=110_000_00,
            comment="salary updated",
        )
        await session.commit()

    async with session_factory() as session:
        saved = await TransactionRepository(session).get(income.id)

    assert saved is not None
    assert saved.amount == 110_000_00
    assert saved.type == TransactionType.INCOME.value
    assert income.category_code == "income_salary"
    assert saved.raw_text == "bank_income_event:1"
    assert saved.comment == "salary updated"
    assert not saved.included_in_reports
    assert repeated is None


@pytest.mark.asyncio
async def test_income_category_cannot_be_changed_through_expense_editing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)
        groceries = next(
            category
            for category in await service.list_category_options()
            if category.code == "groceries"
        )
        income = await service.create_income(
            amount=100_000_00,
            recipient_telegram_id=1001,
            raw_text="bank_income_event:1",
        )

        with pytest.raises(ValueError, match="Income category cannot be changed"):
            await service.update_transaction(
                transaction_id=income.id,
                changed_by_telegram_id=1001,
                category_id=groceries.id,
            )


@pytest.mark.asyncio
async def test_income_categories_are_not_accepted_by_expense_free_text_parser(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        income_salary = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "income_salary")
        )
        assert income_salary is not None
        session.add(CategoryAliasModel(alias="зарплата", category_id=income_salary.id))
        await session.flush()

        service = TransactionService(session, settings)
        with pytest.raises(ValueError, match="не является расходом"):
            await service.create_from_free_text(
                text="5000 зарплата",
                current_payer_telegram_id=1001,
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_expense_update_rejects_income_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)
        created = await service.create_from_category_sort_order(
            amount=350000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="3500 2",
        )
        income_salary = await session.scalar(
            select(CategoryModel).where(CategoryModel.code == "income_salary")
        )
        assert income_salary is not None

        with pytest.raises(ValueError, match="Expense category must be"):
            await service.update_transaction(
                transaction_id=created.id,
                changed_by_telegram_id=1001,
                category_id=income_salary.id,
            )
        await session.rollback()


@pytest.mark.asyncio
async def test_list_income_category_options_returns_only_income_categories(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        options = await service.list_income_category_options()

    assert [option.code for option in options] == [
        "income_general",
        "income_salary",
        "income_advance",
        "income_bonus",
        "income_business",
        "income_debt_return",
        "income_other",
    ]
    assert all(not option.is_expense for option in options)


@pytest.mark.asyncio
async def test_create_transaction_from_category_sort_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_from_category_sort_order(
            amount=350000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="3500 2",
        )
        await session.commit()

        assert summary.amount == 350000
        assert summary.category_code == "groceries"
        assert summary.payer_role == "husband"


@pytest.mark.asyncio
async def test_create_transaction_from_scoped_category_sort_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_from_category_sort_order(
            amount=350000,
            category_sort_order=18,
            payer_telegram_id=1001,
            raw_text="салон 3500 18 бумага",
            comment="бумага",
            payer_role="wife",
            scope=TransactionScope.SALON,
        )
        await session.commit()

    async with session_factory() as session:
        saved = await TransactionRepository(session).get(summary.id)

    assert saved is not None
    assert saved.scope == TransactionScope.SALON.value
    assert summary.scope == TransactionScope.SALON.value
    assert summary.category_code == "stationery_supplies"
    assert summary.payer_role == "wife"


@pytest.mark.asyncio
async def test_create_internal_transfer_from_category_sort_order_99(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_from_category_sort_order(
            amount=2000000,
            category_sort_order=99,
            payer_telegram_id=1001,
            raw_text="20000 99",
        )
        await session.commit()

        assert summary.amount == 2000000
        assert summary.category_code == "internal_transfer"
        assert not summary.included_in_reports


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("text", "category_code", "included"),
    [
        ("3500 продукты магнит", "groceries", True),
        ("1200 кафе", "restaurants_cafes", True),
        ("18500 перевод внешний чаевые", "help_reserve", True),
        ("6800 жкх свет", "utilities", True),
        ("110000 отпуск наличные", "travel_vacation", True),
        ("3600 цветы", "gifts_entertainment_holidays", True),
        ("4200 налоги", "taxes", True),
        ("100000 сам себе", "internal_transfer", False),
        ("5000 жене", "internal_transfer", False),
        ("5000 перевод жене", "internal_transfer", False),
        ("5000 мужу перевёл", "internal_transfer", False),
    ],
)
async def test_create_transaction_from_free_text_examples(
    session_factory: async_sessionmaker[AsyncSession],
    text: str,
    category_code: str,
    included: bool,
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_from_free_text(
            text=text,
            current_payer_telegram_id=1001,
        )
        await session.commit()

        assert summary.category_code == category_code
        assert summary.included_in_reports is included


@pytest.mark.asyncio
async def test_create_transaction_from_scoped_free_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_from_free_text(
            text="салон 900 канцелярия бумага",
            current_payer_telegram_id=1001,
        )
        await session.commit()

    async with session_factory() as session:
        saved = await TransactionRepository(session).get(summary.id)

    assert saved is not None
    assert saved.scope == TransactionScope.SALON.value
    assert summary.category_code == "stationery_supplies"


@pytest.mark.asyncio
async def test_create_scoped_income_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_income(
            amount=70_000_00,
            recipient_telegram_id=1002,
            raw_text="income",
            category_code="income_business",
            scope=TransactionScope.SALON,
        )
        await session.commit()

    async with session_factory() as session:
        saved = await TransactionRepository(session).get(summary.id)

    assert saved is not None
    assert saved.type == TransactionType.INCOME.value
    assert saved.scope == TransactionScope.SALON.value
    assert summary.scope == TransactionScope.SALON.value


@pytest.mark.asyncio
async def test_create_transaction_from_free_text_rejects_unknown_category(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        with pytest.raises(ValueError, match="Не удалось определить категорию"):
            await service.create_from_free_text(
                text="4200 непонятная покупка",
                current_payer_telegram_id=1001,
            )
        await session.commit()


@pytest.mark.asyncio
async def test_create_transaction_from_free_text_does_not_treat_gift_to_self_as_transfer(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        summary = await TransactionService(session, settings).create_from_free_text(
            text="2500 подарок себе",
            current_payer_telegram_id=1001,
        )
        await session.commit()

    assert summary.category_code == "gifts_entertainment_holidays"
    assert summary.included_in_reports


@pytest.mark.asyncio
async def test_create_transaction_from_free_text_with_cents(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        summary = await service.create_from_free_text(
            text="3500,50 продукты магнит",
            current_payer_telegram_id=1001,
        )
        await session.commit()

        assert summary.amount == 350050
        assert summary.category_code == "groceries"
        assert summary.included_in_reports


@pytest.mark.asyncio
async def test_create_batch_from_text_with_partial_failures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        result = await service.create_batch_from_text(
            text="\n".join(
                [
                    "3500 2 магнит",
                    "1200,50 6 кафе",
                    "bad line",
                    "3600 13 цветы",
                    "18500 16 внешний ремонт",
                    "20000 99",
                ]
            ),
            current_payer_telegram_id=1001,
        )
        await session.commit()

        assert len(result.created) == 5
        assert len(result.errors) == 1
        assert result.total_amount == 4680050
        assert [item.category_code for item in result.created] == [
            "groceries",
            "restaurants_cafes",
            "gifts_entertainment_holidays",
            "help_reserve",
            "internal_transfer",
        ]
        assert not result.created[-1].included_in_reports


@pytest.mark.asyncio
async def test_cancel_batch_soft_deletes_transactions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        result = await service.create_batch_from_text(
            text="3500 2 магнит\n1200 6 кафе",
            current_payer_telegram_id=1001,
        )
        transaction_ids = [summary.id for summary in result.created]
        deleted_count = await service.cancel_transactions(
            transaction_ids,
            changed_by_telegram_id=1001,
        )
        await session.commit()

    async with session_factory() as session:
        transactions = TransactionRepository(session)
        audit = AuditRepository(session)
        saved_transactions = [
            await transactions.get(transaction_id) for transaction_id in transaction_ids
        ]
        audit_actions = [
            [log.action for log in await audit.list_for_transaction(transaction_id)]
            for transaction_id in transaction_ids
        ]

        assert deleted_count == 2
        assert all(transaction is not None for transaction in saved_transactions)
        assert all(transaction.deleted_at is not None for transaction in saved_transactions)
        assert audit_actions == [
            [AuditAction.CREATE.value, AuditAction.DELETE.value],
            [AuditAction.CREATE.value, AuditAction.DELETE.value],
        ]


@pytest.mark.asyncio
async def test_update_transaction_changes_category_and_writes_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        created = await service.create_from_category_sort_order(
            amount=350000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="3500 2",
        )
        updated = await service.update_transaction(
            transaction_id=created.id,
            changed_by_telegram_id=1001,
            amount=420000,
            category_sort_order=13,
            payer_role="wife",
            comment="букет",
        )
        await session.commit()

    async with session_factory() as session:
        transactions = TransactionRepository(session)
        audit = AuditRepository(session)
        saved = await transactions.get(created.id)
        audit_logs = await audit.list_for_transaction(created.id)

        assert saved is not None
        assert saved.amount == 420000
        assert saved.comment == "букет"
        assert updated.category_code == "gifts_entertainment_holidays"
        assert updated.payer_role == "wife"
        assert [log.action for log in audit_logs] == [
            AuditAction.CREATE.value,
            AuditAction.UPDATE.value,
        ]
        update_log = audit_logs[1]
        assert update_log.old_value is not None
        assert update_log.new_value is not None
        assert update_log.old_value["amount"] == 350000
        assert update_log.new_value["amount"] == 420000
        assert update_log.old_value["category_id"] != update_log.new_value["category_id"]


@pytest.mark.asyncio
async def test_delete_transaction_soft_deletes_and_writes_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        created = await service.create_from_category_sort_order(
            amount=120000,
            category_sort_order=6,
            payer_telegram_id=1001,
            raw_text="1200 6",
        )
        deleted = await service.delete_transaction(
            transaction_id=created.id,
            changed_by_telegram_id=1001,
        )
        await session.commit()

    async with session_factory() as session:
        transactions = TransactionRepository(session)
        audit = AuditRepository(session)
        saved = await transactions.get(created.id)
        audit_logs = await audit.list_for_transaction(created.id)

        assert deleted.id == created.id
        assert saved is not None
        assert saved.deleted_at is not None
        assert [log.action for log in audit_logs] == [
            AuditAction.CREATE.value,
            AuditAction.DELETE.value,
        ]
        assert audit_logs[1].new_value is not None
        assert audit_logs[1].new_value["deleted_at"] is not None


@pytest.mark.asyncio
async def test_undo_and_repeat_use_latest_user_transaction(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    settings = make_settings()

    async with session_factory() as session:
        await seed_initial_data(session, settings)
        service = TransactionService(session, settings)

        first = await service.create_from_category_sort_order(
            amount=350000,
            category_sort_order=2,
            payer_telegram_id=1001,
            raw_text="3500 2",
        )
        second = await service.create_from_category_sort_order(
            amount=120000,
            category_sort_order=6,
            payer_telegram_id=1001,
            raw_text="1200 6",
        )
        undone = await service.undo_last_transaction(changed_by_telegram_id=1001)
        repeated = await service.repeat_last_transaction(changed_by_telegram_id=1001)
        await session.commit()

    async with session_factory() as session:
        transactions = TransactionRepository(session)
        audit = AuditRepository(session)
        first_saved = await transactions.get(first.id)
        second_saved = await transactions.get(second.id)
        repeated_saved = await transactions.get(repeated.id if repeated else -1)
        second_audit = await audit.list_for_transaction(second.id)
        repeated_audit = await audit.list_for_transaction(repeated.id if repeated else -1)

        assert undone is not None
        assert undone.id == second.id
        assert repeated is not None
        assert repeated.amount == first.amount
        assert repeated.category_code == first.category_code
        assert first_saved is not None
        assert first_saved.deleted_at is None
        assert second_saved is not None
        assert second_saved.deleted_at is not None
        assert repeated_saved is not None
        assert repeated_saved.deleted_at is None
        assert [log.action for log in second_audit] == [
            AuditAction.CREATE.value,
            AuditAction.DELETE.value,
        ]
        assert [log.action for log in repeated_audit] == [AuditAction.CREATE.value]
