from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.money import round_minor_to_whole_units_minor
from financial_bot.app.domain.periods import Period, PeriodKind
from financial_bot.app.domain.types import UserRole
from financial_bot.app.services.cashflow_service import IncomeCategoryLine, IncomeRecipientLine
from financial_bot.app.services.report_service import (
    CategoryReportLine,
    PayerReportLine,
    ReportService,
)
from financial_bot.app.services.spending_limit_service import (
    BudgetLimitLine,
    BudgetNoLimitLine,
    BudgetReport,
    BudgetSavingsTargetLine,
    SpendingLimitService,
)
from financial_bot.app.storage.repositories.cashflow_repository import CashflowRepository


@dataclass(frozen=True, slots=True)
class MonthPace:
    elapsed_days: int
    day_count: int
    average_per_day: int
    forecast_amount: int


@dataclass(frozen=True, slots=True)
class MonthReport:
    period: Period
    currency: str
    total_amount: int
    income_total: int
    net_after_expenses: int
    pace: MonthPace
    by_payer: tuple[PayerReportLine, ...]
    top_categories: tuple[CategoryReportLine, ...]
    other_categories_count: int
    other_categories_amount: int
    income_by_recipient: tuple[IncomeRecipientLine, ...]
    top_income_categories: tuple[IncomeCategoryLine, ...]
    other_income_categories_count: int
    other_income_categories_amount: int
    budget_risks: tuple[BudgetLimitLine, ...]
    no_limit_lines: tuple[BudgetNoLimitLine, ...]
    savings_target_lines: tuple[BudgetSavingsTargetLine, ...]
    under_budget_pool: int
    overrun_total: int
    net_savings: int
    budget: BudgetReport

    @property
    def has_expenses(self) -> bool:
        return self.total_amount > 0

    @property
    def has_income(self) -> bool:
        return self.income_total > 0

    @property
    def has_activity(self) -> bool:
        return self.has_expenses or self.has_income


class MonthReportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._cashflow = CashflowRepository(session)
        self._reports = ReportService(session, settings)
        self._limits = SpendingLimitService(session, settings)

    async def build_month_report(
        self,
        *,
        now: datetime | None = None,
        top_category_limit: int = 5,
        top_income_category_limit: int = 3,
        budget_risk_limit: int = 4,
    ) -> MonthReport:
        if top_category_limit <= 0:
            msg = "top_category_limit must be positive"
            raise ValueError(msg)
        if top_income_category_limit <= 0:
            msg = "top_income_category_limit must be positive"
            raise ValueError(msg)
        if budget_risk_limit <= 0:
            msg = "budget_risk_limit must be positive"
            raise ValueError(msg)

        report_now = _local_now(now, self._settings.timezone)
        period_report = await self._reports.build_period_report(PeriodKind.MONTH, now=report_now)
        income_total = await self._cashflow.total_income(
            period_report.period.start_at,
            period_report.period.end_at,
        )
        income_rows = await self._cashflow.income_by_recipient(
            period_report.period.start_at,
            period_report.period.end_at,
        )
        income_category_rows = await self._cashflow.income_by_category(
            period_report.period.start_at,
            period_report.period.end_at,
        )
        income_amounts = {row.role: row.amount for row in income_rows}
        income_by_recipient = tuple(
            IncomeRecipientLine(
                role=role.value,
                amount=income_amounts.get(role.value, 0),
                share_percent=_share(income_amounts.get(role.value, 0), income_total),
            )
            for role in (UserRole.HUSBAND, UserRole.WIFE)
        )
        income_categories = tuple(
            IncomeCategoryLine(
                code=row.code,
                title=row.title,
                amount=row.amount,
                share_percent=_share(row.amount, income_total),
            )
            for row in income_category_rows
        )
        top_income_categories = income_categories[:top_income_category_limit]
        other_income_categories = income_categories[top_income_category_limit:]
        budget = await self._limits.build_monthly_report(now=report_now)
        special_category_codes = {
            *(line.code for line in budget.no_limit_lines),
            *(line.code for line in budget.savings_target_lines),
        }
        regular_categories = tuple(
            line for line in period_report.by_category if line.code not in special_category_codes
        )
        top_categories = regular_categories[:top_category_limit]
        other_categories = regular_categories[top_category_limit:]
        pace = _build_pace(
            period=period_report.period,
            total_amount=period_report.total_amount,
            now=report_now,
            timezone=self._settings.timezone,
        )

        return MonthReport(
            period=period_report.period,
            currency=period_report.currency,
            total_amount=period_report.total_amount,
            income_total=income_total,
            net_after_expenses=income_total - period_report.total_amount,
            pace=pace,
            by_payer=period_report.by_payer,
            top_categories=top_categories,
            other_categories_count=len(other_categories),
            other_categories_amount=sum(line.amount for line in other_categories),
            income_by_recipient=income_by_recipient,
            top_income_categories=top_income_categories,
            other_income_categories_count=len(other_income_categories),
            other_income_categories_amount=sum(line.amount for line in other_income_categories),
            budget_risks=_top_budget_risks(budget, limit=budget_risk_limit),
            no_limit_lines=budget.no_limit_lines,
            savings_target_lines=budget.savings_target_lines,
            under_budget_pool=budget.under_budget_pool,
            overrun_total=budget.overrun_total,
            net_savings=budget.net_savings,
            budget=budget,
        )


def _build_pace(
    *,
    period: Period,
    total_amount: int,
    now: datetime | None,
    timezone: str,
) -> MonthPace:
    day_count = (period.end_at.date() - period.start_at.date()).days
    local_now = _local_now(now, timezone)
    elapsed_days = min(max((local_now.date() - period.start_at.date()).days + 1, 1), day_count)
    if total_amount <= 0:
        return MonthPace(
            elapsed_days=elapsed_days,
            day_count=day_count,
            average_per_day=0,
            forecast_amount=0,
        )

    average_per_day = round_minor_to_whole_units_minor(
        Decimal(total_amount) / Decimal(elapsed_days)
    )
    forecast_amount = round_minor_to_whole_units_minor(
        Decimal(total_amount) * Decimal(day_count) / Decimal(elapsed_days)
    )
    return MonthPace(
        elapsed_days=elapsed_days,
        day_count=day_count,
        average_per_day=average_per_day,
        forecast_amount=forecast_amount,
    )


def _top_budget_risks(budget: BudgetReport, *, limit: int) -> tuple[BudgetLimitLine, ...]:
    candidates = [
        line for line in budget.limit_lines if line.spent_amount > 0 and line.usage_percent >= 50
    ]
    return tuple(
        sorted(
            candidates,
            key=lambda line: (line.overrun_amount > 0, line.usage_percent, line.spent_amount),
            reverse=True,
        )[:limit]
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
