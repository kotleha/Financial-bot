from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.domain.types import TransactionScope, UserRole
from financial_bot.app.services.report_service import ReportService
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.storage.repositories.cashflow_repository import CashflowRepository


@dataclass(frozen=True, slots=True)
class IncomeRecipientLine:
    role: str
    amount: int
    share_percent: float


@dataclass(frozen=True, slots=True)
class IncomeCategoryLine:
    code: str
    title: str
    amount: int
    share_percent: float


@dataclass(frozen=True, slots=True)
class CashflowReport:
    period: Period
    currency: str
    scope: TransactionScope | None
    income_total: int
    expense_total: int
    net_after_expenses: int
    income_by_recipient: tuple[IncomeRecipientLine, ...]
    income_by_category: tuple[IncomeCategoryLine, ...]
    budget_net_savings: int | None


class CashflowService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._cashflow = CashflowRepository(session)
        self._reports = ReportService(session, settings)
        self._limits = SpendingLimitService(session, settings)

    async def build_report(
        self,
        kind: PeriodKind = PeriodKind.MONTH,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> CashflowReport:
        report_now = _local_now(now, self._settings.timezone)
        expense_report = await self._reports.build_period_report(
            kind,
            now=report_now,
            scope=scope,
        )
        income_total = await self._cashflow.total_income(
            expense_report.period.start_at,
            expense_report.period.end_at,
            scope=scope,
        )
        income_rows = await self._cashflow.income_by_recipient(
            expense_report.period.start_at,
            expense_report.period.end_at,
            scope=scope,
        )
        income_category_rows = await self._cashflow.income_by_category(
            expense_report.period.start_at,
            expense_report.period.end_at,
            scope=scope,
        )
        income_amounts = {row.role: row.amount for row in income_rows}
        budget_net_savings = None
        if kind == PeriodKind.MONTH and scope is None:
            budget = await self._limits.build_monthly_report(now=report_now)
            budget_net_savings = budget.net_savings

        return CashflowReport(
            period=expense_report.period,
            currency=expense_report.currency,
            scope=scope,
            income_total=income_total,
            expense_total=expense_report.total_amount,
            net_after_expenses=income_total - expense_report.total_amount,
            income_by_recipient=tuple(
                IncomeRecipientLine(
                    role=role.value,
                    amount=income_amounts.get(role.value, 0),
                    share_percent=_share(income_amounts.get(role.value, 0), income_total),
                )
                for role in (UserRole.HUSBAND, UserRole.WIFE)
            ),
            income_by_category=tuple(
                IncomeCategoryLine(
                    code=row.code,
                    title=row.title,
                    amount=row.amount,
                    share_percent=_share(row.amount, income_total),
                )
                for row in income_category_rows
            ),
            budget_net_savings=budget_net_savings,
        )


def _share(amount: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return round(amount / total * 100, 1)


def _local_now(now: datetime | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    value = now or datetime.now(tz)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)
