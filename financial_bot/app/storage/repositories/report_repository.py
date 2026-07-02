from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.types import TransactionScope, TransactionType
from financial_bot.app.storage.models import CategoryModel, TransactionModel, UserModel


@dataclass(frozen=True, slots=True)
class PayerTotalRow:
    role: str
    amount: int


@dataclass(frozen=True, slots=True)
class CategoryTotalRow:
    code: str
    title: str
    owner_role: str
    sort_order: int
    amount: int


class ReportRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def total_expenses(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        scope: TransactionScope | None = None,
    ) -> int:
        result = await self._session.execute(
            select(func.coalesce(func.sum(_signed_report_amount()), 0)).where(
                *_report_effective_filters(start_at, end_at, scope=scope)
            )
        )
        return int(result.scalar_one())

    async def totals_by_payer(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        scope: TransactionScope | None = None,
    ) -> list[PayerTotalRow]:
        result = await self._session.execute(
            select(UserModel.role, func.coalesce(func.sum(_signed_report_amount()), 0))
            .join(UserModel, TransactionModel.payer_user_id == UserModel.id)
            .where(*_report_effective_filters(start_at, end_at, scope=scope))
            .group_by(UserModel.role)
            .order_by(UserModel.role)
        )
        return [
            PayerTotalRow(role=row[0], amount=amount)
            for row in result.all()
            if (amount := int(row[1])) != 0
        ]

    async def totals_by_category(
        self,
        start_at: datetime,
        end_at: datetime,
        *,
        scope: TransactionScope | None = None,
    ) -> list[CategoryTotalRow]:
        result = await self._session.execute(
            select(
                CategoryModel.code,
                CategoryModel.title,
                CategoryModel.owner_role,
                CategoryModel.sort_order,
                func.coalesce(func.sum(_signed_report_amount()), 0),
            )
            .join(CategoryModel, TransactionModel.category_id == CategoryModel.id)
            .where(*_report_effective_filters(start_at, end_at, scope=scope))
            .group_by(
                CategoryModel.code,
                CategoryModel.title,
                CategoryModel.owner_role,
                CategoryModel.sort_order,
            )
            .order_by(func.sum(_signed_report_amount()).desc(), CategoryModel.sort_order)
        )
        return [
            CategoryTotalRow(
                code=row[0],
                title=row[1],
                owner_role=row[2],
                sort_order=int(row[3]),
                amount=amount,
            )
            for row in result.all()
            if (amount := int(row[4])) != 0
        ]


def _report_effective_filters(
    start_at: datetime,
    end_at: datetime,
    *,
    scope: TransactionScope | None = None,
):
    filters = [
        TransactionModel.type.in_(
            (TransactionType.EXPENSE.value, TransactionType.CORRECTION.value)
        ),
        TransactionModel.included_in_reports.is_(True),
        TransactionModel.deleted_at.is_(None),
        TransactionModel.occurred_at >= start_at,
        TransactionModel.occurred_at < end_at,
    ]
    if scope is not None:
        filters.append(TransactionModel.scope == scope.value)
    return tuple(filters)


def _signed_report_amount():
    return case(
        (TransactionModel.type == TransactionType.CORRECTION.value, -TransactionModel.amount),
        else_=TransactionModel.amount,
    )
