from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import Period, PeriodKind, resolve_period
from financial_bot.app.domain.types import TransactionScope, UserRole
from financial_bot.app.storage.repositories.report_repository import ReportRepository


@dataclass(frozen=True, slots=True)
class PayerReportLine:
    role: str
    amount: int
    share_percent: float


@dataclass(frozen=True, slots=True)
class CategoryReportLine:
    code: str
    title: str
    owner_role: str
    sort_order: int
    amount: int
    share_percent: float


@dataclass(frozen=True, slots=True)
class PeriodReport:
    period: Period
    total_amount: int
    currency: str
    scope: TransactionScope | None
    by_payer: tuple[PayerReportLine, ...]
    by_category: tuple[CategoryReportLine, ...]


class ReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._reports = ReportRepository(session)

    async def build_period_report(
        self,
        kind: PeriodKind,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> PeriodReport:
        period = resolve_period(kind, now=now, timezone=self._settings.timezone)
        total_amount = await self._reports.total_expenses(
            period.start_at,
            period.end_at,
            scope=scope,
        )
        payer_rows = await self._reports.totals_by_payer(
            period.start_at,
            period.end_at,
            scope=scope,
        )
        category_rows = await self._reports.totals_by_category(
            period.start_at,
            period.end_at,
            scope=scope,
        )

        payer_amounts = {row.role: row.amount for row in payer_rows}
        by_payer = tuple(
            PayerReportLine(
                role=role.value,
                amount=payer_amounts.get(role.value, 0),
                share_percent=_share(payer_amounts.get(role.value, 0), total_amount),
            )
            for role in (UserRole.HUSBAND, UserRole.WIFE)
        )

        by_category = tuple(
            CategoryReportLine(
                code=row.code,
                title=row.title,
                owner_role=row.owner_role,
                sort_order=row.sort_order,
                amount=row.amount,
                share_percent=_share(row.amount, total_amount),
            )
            for row in category_rows
        )

        return PeriodReport(
            period=period,
            total_amount=total_amount,
            currency=self._settings.default_currency,
            scope=scope,
            by_payer=by_payer,
            by_category=by_category,
        )


def _share(amount: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(amount / total * 100, 1)
