from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from financial_bot.app.config import Settings
from financial_bot.app.services.transaction_service import TransactionService
from sqlalchemy.ext.asyncio import AsyncSession

EXPECTED_MAY_REPORT_RUB = {
    "total": 523244,
    "husband_paid": 363170,
    "wife_paid": 160074,
    "husband_share": 69.4,
    "wife_share": 30.6,
}

EXPECTED_MAY_CATEGORY_TOTALS_RUB = {
    "utilities": 122184,
    "travel_vacation": 110000,
    "help_reserve": 98872,
    "groceries": 68400,
    "restaurants_cafes": 49842,
    "clothing_shoes": 49517,
    "auto": 11226,
    "cosmetology_medicine": 7181,
    "subscriptions_communications": 6022,
}


@dataclass(frozen=True, slots=True)
class MayTransactionFixtureRow:
    amount_rub: int
    category_sort_order: int
    payer_telegram_id: int
    comment: str


MAY_2026_TRANSACTION_ROWS: tuple[MayTransactionFixtureRow, ...] = (
    MayTransactionFixtureRow(122184, 1, 1001, "ЖКХ"),
    MayTransactionFixtureRow(98872, 16, 1001, "Помощь / резерв"),
    MayTransactionFixtureRow(110000, 14, 1001, "Путешествия / отдых"),
    MayTransactionFixtureRow(11226, 4, 1001, "Авто"),
    MayTransactionFixtureRow(6022, 3, 1001, "Подписки / связь / интернет"),
    MayTransactionFixtureRow(14866, 2, 1001, "Продукты, оплачено мужем"),
    MayTransactionFixtureRow(53534, 2, 1002, "Продукты, оплачено женой"),
    MayTransactionFixtureRow(49842, 6, 1002, "Рестораны / кафе"),
    MayTransactionFixtureRow(27048, 9, 1002, "Одежда / обувь"),
    MayTransactionFixtureRow(7181, 8, 1002, "Косметология / медицина"),
    MayTransactionFixtureRow(22469, 9, 1002, "Одежда / обувь"),
)


async def seed_may_2026_transactions(session: AsyncSession, settings: Settings) -> None:
    timezone = ZoneInfo(settings.timezone)
    service = TransactionService(session, settings)
    base_date = datetime(2026, 5, 1, 12, tzinfo=timezone)

    for index, row in enumerate(MAY_2026_TRANSACTION_ROWS):
        summary = await service.create_from_category_sort_order(
            amount=row.amount_rub * 100,
            category_sort_order=row.category_sort_order,
            payer_telegram_id=row.payer_telegram_id,
            raw_text=f"{row.amount_rub} {row.category_sort_order}",
            comment=row.comment,
        )
        await service.update_transaction(
            transaction_id=summary.id,
            changed_by_telegram_id=row.payer_telegram_id,
            occurred_at=base_date + timedelta(days=index),
        )

    internal_transfer = await service.create_from_free_text(
        text="100000 сам себе",
        current_payer_telegram_id=1001,
    )
    await service.update_transaction(
        transaction_id=internal_transfer.id,
        changed_by_telegram_id=1001,
        occurred_at=datetime(2026, 5, 20, 12, tzinfo=timezone),
    )
