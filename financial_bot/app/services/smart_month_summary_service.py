from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.monthly_insights import (
    AutoAccountingQuality,
    CategoryChange,
    MonthConclusion,
    ScopeSnapshot,
    build_month_conclusion,
)
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.auto_accounting_health_service import AutoAccountingHealthService
from financial_bot.app.services.month_report_service import MonthReport, MonthReportService
from financial_bot.app.services.report_service import ReportService

CATEGORY_GROWTH_MIN_DELTA = 5_000_00
CATEGORY_GROWTH_MIN_PERCENT = 20.0
CATEGORY_GROWTH_LIMIT = 3


@dataclass(frozen=True, slots=True)
class SmartMonthSummary:
    report: MonthReport
    conclusion: MonthConclusion
    scope_snapshots: tuple[ScopeSnapshot, ...]
    category_changes: tuple[CategoryChange, ...] = ()
    auto_accounting_quality: AutoAccountingQuality | None = None


class SmartMonthSummaryService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._month_reports = MonthReportService(session, settings)
        self._reports = ReportService(session, settings)
        self._auto_accounting_health = AutoAccountingHealthService(session)

    async def build_summary(
        self,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
        max_insights: int = 5,
        telegram_user_id: int | None = None,
    ) -> SmartMonthSummary:
        report_now = _local_now(now, self._settings.timezone)
        report = await self._month_reports.build_month_report(now=report_now, scope=scope)
        scope_snapshots = await self._build_scope_snapshots(now=report_now) if scope is None else ()
        category_changes = await self._build_category_changes(
            report=report,
            now=report_now,
            scope=scope,
        )
        auto_accounting_quality = await self._build_auto_accounting_quality(
            now=report_now,
            scope=scope,
            telegram_user_id=telegram_user_id,
        )
        conclusion = build_month_conclusion(
            report,
            scope_snapshots=scope_snapshots,
            category_changes=category_changes,
            auto_accounting_quality=auto_accounting_quality,
            max_insights=max_insights,
        )
        return SmartMonthSummary(
            report=report,
            conclusion=conclusion,
            scope_snapshots=scope_snapshots,
            category_changes=category_changes,
            auto_accounting_quality=auto_accounting_quality,
        )

    async def _build_scope_snapshots(
        self,
        *,
        now: datetime | None,
    ) -> tuple[ScopeSnapshot, ...]:
        snapshots: list[ScopeSnapshot] = []
        for scope in (TransactionScope.HOUSEHOLD, TransactionScope.SALON):
            report = await self._month_reports.build_month_report(now=now, scope=scope)
            top_category = report.top_categories[0].title if report.top_categories else None
            snapshots.append(
                ScopeSnapshot(
                    scope=scope,
                    expenses=report.total_amount,
                    income=report.income_total,
                    net_after_expenses=report.net_after_expenses,
                    top_category_title=top_category,
                )
            )
        return tuple(snapshots)

    async def _build_category_changes(
        self,
        *,
        report: MonthReport,
        now: datetime | None,
        scope: TransactionScope | None,
    ) -> tuple[CategoryChange, ...]:
        if not report.has_expenses:
            return ()

        current = await self._reports.build_period_report(PeriodKind.MONTH, now=now, scope=scope)
        previous_reference = report.period.start_at - timedelta(seconds=1)
        previous = await self._reports.build_period_report(
            PeriodKind.MONTH,
            now=previous_reference,
            scope=scope,
        )
        if previous.total_amount <= 0:
            return ()

        excluded_codes = _excluded_category_change_codes(report)
        previous_by_code = {line.code: line.amount for line in previous.by_category}
        changes: list[CategoryChange] = []
        for line in current.by_category:
            if line.code in excluded_codes:
                continue
            previous_amount = previous_by_code.get(line.code, 0)
            if previous_amount <= 0:
                continue
            delta_amount = line.amount - previous_amount
            if delta_amount < CATEGORY_GROWTH_MIN_DELTA:
                continue
            delta_percent = round(delta_amount / previous_amount * 100, 1)
            if delta_percent < CATEGORY_GROWTH_MIN_PERCENT:
                continue
            changes.append(
                CategoryChange(
                    code=line.code,
                    title=line.title,
                    current_amount=line.amount,
                    previous_amount=previous_amount,
                    delta_amount=delta_amount,
                    delta_percent=delta_percent,
                )
            )

        return tuple(
            sorted(
                changes,
                key=lambda change: (change.delta_amount, change.delta_percent, change.title),
                reverse=True,
            )[:CATEGORY_GROWTH_LIMIT]
        )

    async def _build_auto_accounting_quality(
        self,
        *,
        now: datetime | None,
        scope: TransactionScope | None,
        telegram_user_id: int | None,
    ) -> AutoAccountingQuality | None:
        if scope is not None or telegram_user_id is None:
            return None

        health = await self._auto_accounting_health.get_health(
            telegram_user_id=telegram_user_id,
            now=now,
        )
        return AutoAccountingQuality(
            pending_confirmation_count=health.pending_confirmation_count,
            unknown_event_count=health.unknown_event_count,
            failed_telegram_notification_count=health.failed_telegram_notification_count,
            unsent_pending_count=health.unsent_pending_count,
        )


def _excluded_category_change_codes(report: MonthReport) -> set[str]:
    if report.scope is not None:
        return set()
    return {
        *(line.code for line in report.no_limit_lines),
        *(line.code for line in report.savings_target_lines),
    }


def _local_now(now: datetime | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    value = now or datetime.now(tz)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)
