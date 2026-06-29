from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.types import TransactionType
from financial_bot.app.storage.models import TransactionModel


class TransactionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, transaction: TransactionModel) -> TransactionModel:
        self._session.add(transaction)
        await self._session.flush()
        return transaction

    async def get(self, transaction_id: int) -> TransactionModel | None:
        return await self._session.get(TransactionModel, transaction_id)

    async def get_active(self, transaction_id: int) -> TransactionModel | None:
        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.id == transaction_id)
            .where(TransactionModel.deleted_at.is_(None))
        )
        return result.scalar_one_or_none()

    async def list_active_by_ids(self, transaction_ids: list[int]) -> list[TransactionModel]:
        if not transaction_ids:
            return []

        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.id.in_(transaction_ids))
            .where(TransactionModel.deleted_at.is_(None))
            .order_by(TransactionModel.id)
        )
        return list(result.scalars())

    async def list_for_period(self, start_at: datetime, end_at: datetime) -> list[TransactionModel]:
        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.occurred_at >= start_at)
            .where(TransactionModel.occurred_at < end_at)
            .where(TransactionModel.deleted_at.is_(None))
            .order_by(TransactionModel.occurred_at, TransactionModel.id)
        )
        return list(result.scalars())

    async def list_report_expenses_for_period(
        self,
        start_at: datetime,
        end_at: datetime,
    ) -> list[TransactionModel]:
        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.type == TransactionType.EXPENSE.value)
            .where(TransactionModel.included_in_reports.is_(True))
            .where(TransactionModel.deleted_at.is_(None))
            .where(TransactionModel.occurred_at >= start_at)
            .where(TransactionModel.occurred_at < end_at)
            .order_by(TransactionModel.occurred_at, TransactionModel.id)
        )
        return list(result.scalars())

    async def list_report_effective_for_period(
        self,
        start_at: datetime,
        end_at: datetime,
    ) -> list[TransactionModel]:
        result = await self._session.execute(
            select(TransactionModel)
            .where(
                TransactionModel.type.in_(
                    (TransactionType.EXPENSE.value, TransactionType.CORRECTION.value)
                )
            )
            .where(TransactionModel.included_in_reports.is_(True))
            .where(TransactionModel.deleted_at.is_(None))
            .where(TransactionModel.occurred_at >= start_at)
            .where(TransactionModel.occurred_at < end_at)
            .order_by(TransactionModel.occurred_at, TransactionModel.id)
        )
        return list(result.scalars())

    async def get_latest_active_by_creator(
        self,
        created_by_user_id: int,
    ) -> TransactionModel | None:
        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.created_by_user_id == created_by_user_id)
            .where(TransactionModel.deleted_at.is_(None))
            .order_by(TransactionModel.created_at.desc(), TransactionModel.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def soft_delete(self, transaction: TransactionModel, deleted_at: datetime) -> None:
        transaction.deleted_at = deleted_at
        await self._session.flush()

    async def soft_delete_many(self, transaction_ids: list[int], deleted_at: datetime) -> int:
        if not transaction_ids:
            return 0

        result = await self._session.execute(
            select(TransactionModel)
            .where(TransactionModel.id.in_(transaction_ids))
            .where(TransactionModel.deleted_at.is_(None))
        )
        transactions = list(result.scalars())
        for transaction in transactions:
            transaction.deleted_at = deleted_at
        await self._session.flush()
        return len(transactions)
