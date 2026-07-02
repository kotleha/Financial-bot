from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.types import TransactionScope, TransactionType
from financial_bot.app.storage.models import CategoryModel, TransactionModel, UserModel


@dataclass(frozen=True, slots=True)
class CashflowPayerRow:
    role: str
    amount: int


@dataclass(frozen=True, slots=True)
class CashflowCategoryRow:
    code: str
    title: str
    amount: int


class CashflowRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def total_income(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        scope: TransactionScope | None = None,
    ) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.sum(TransactionModel.amount), 0)).where(
                *_income_filters(start_at, end_at, scope=scope)
            )
        )
        return int(result.scalar_one())

    async def income_by_recipient(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        scope: TransactionScope | None = None,
    ) -> list[CashflowPayerRow]:
        result = await self._session.execute(
            select(UserModel.role, func.coalesce(func.sum(TransactionModel.amount), 0))
            .join(UserModel, TransactionModel.payer_user_id == UserModel.id)
            .where(*_income_filters(start_at, end_at, scope=scope))
            .group_by(UserModel.role)
            .order_by(UserModel.role)
        )
        return [
            CashflowPayerRow(role=row[0], amount=amount)
            for row in result.all()
            if (amount := int(row[1])) != 0
        ]

    async def income_by_category(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        scope: TransactionScope | None = None,
    ) -> list[CashflowCategoryRow]:
        result = await self._session.execute(
            select(
                CategoryModel.code,
                CategoryModel.title,
                func.coalesce(func.sum(TransactionModel.amount), 0),
            )
            .join(CategoryModel, TransactionModel.category_id == CategoryModel.id)
            .where(*_income_filters(start_at, end_at, scope=scope))
            .group_by(CategoryModel.code, CategoryModel.title, CategoryModel.sort_order)
            .order_by(
                func.coalesce(func.sum(TransactionModel.amount), 0).desc(),
                CategoryModel.sort_order,
            )
        )
        return [
            CashflowCategoryRow(code=row[0], title=row[1], amount=amount)
            for row in result.all()
            if (amount := int(row[2])) != 0
        ]


def _income_filters(
    start_at: datetime,
    end_at: datetime,
    *,
    scope: TransactionScope | None = None,
):
    filters = [
        TransactionModel.type == TransactionType.INCOME.value,
        TransactionModel.deleted_at.is_(None),
        TransactionModel.occurred_at >= start_at,
        TransactionModel.occurred_at < end_at,
    ]
    if scope is not None:
        filters.append(TransactionModel.scope == scope.value)
    return tuple(filters)
