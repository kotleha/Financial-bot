from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.accounting_scope import scope_label
from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealth,
    AutoAccountingHealthService,
)
from financial_bot.app.services.month_report_service import MonthReport
from financial_bot.app.services.smart_month_summary_service import (
    SmartMonthSummary,
    SmartMonthSummaryService,
)


class MonthCloseItemStatus(StrEnum):
    OK = "ok"
    ATTENTION = "attention"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class MonthCloseChecklistItem:
    code: str
    status: MonthCloseItemStatus
    title: str
    message: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class MonthCloseReport:
    summary: SmartMonthSummary
    auto_accounting_health: AutoAccountingHealth | None
    checklist: tuple[MonthCloseChecklistItem, ...]
    blocked_count: int
    attention_count: int

    @property
    def is_clean(self) -> bool:
        return self.blocked_count == 0 and self.attention_count == 0

    @property
    def has_blockers(self) -> bool:
        return self.blocked_count > 0


class MonthCloseService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._smart_summary = SmartMonthSummaryService(session, settings)
        self._auto_accounting_health = AutoAccountingHealthService(session)

    async def build_report(
        self,
        *,
        now: datetime | None = None,
        telegram_user_id: int | None = None,
    ) -> MonthCloseReport:
        report_now = _local_now(now, self._settings.timezone)
        summary = await self._smart_summary.build_summary(
            now=report_now,
            telegram_user_id=telegram_user_id,
            max_insights=6,
        )
        health = await self._build_auto_accounting_health(
            now=report_now,
            telegram_user_id=telegram_user_id,
        )
        checklist = tuple(
            sorted(
                _build_checklist(summary=summary, health=health),
                key=lambda item: item.sort_order,
            )
        )
        return MonthCloseReport(
            summary=summary,
            auto_accounting_health=health,
            checklist=checklist,
            blocked_count=sum(
                1 for item in checklist if item.status == MonthCloseItemStatus.BLOCKED
            ),
            attention_count=sum(
                1 for item in checklist if item.status == MonthCloseItemStatus.ATTENTION
            ),
        )

    async def _build_auto_accounting_health(
        self,
        *,
        now: datetime,
        telegram_user_id: int | None,
    ) -> AutoAccountingHealth | None:
        if telegram_user_id is None:
            return None
        return await self._auto_accounting_health.get_health(
            telegram_user_id=telegram_user_id,
            now=now,
        )


def _build_checklist(
    *,
    summary: SmartMonthSummary,
    health: AutoAccountingHealth | None,
) -> list[MonthCloseChecklistItem]:
    report = summary.report
    return [
        _bank_auto_accounting_item(health),
        _income_item(report),
        _expenses_item(report),
        _cashflow_item(report),
        _limits_item(report),
        _scope_item(summary),
    ]


def _bank_auto_accounting_item(
    health: AutoAccountingHealth | None,
) -> MonthCloseChecklistItem:
    if health is None:
        return MonthCloseChecklistItem(
            code="bank_auto_accounting",
            status=MonthCloseItemStatus.ATTENTION,
            title="Автоучёт",
            message="Не удалось проверить банковские источники для текущего пользователя.",
            sort_order=10,
        )

    blocking_count = (
        health.pending_confirmation_count
        + health.failed_telegram_notification_count
        + health.unsent_pending_count
    )
    if blocking_count > 0:
        details = _join_non_empty(
            (
                _count_phrase(health.pending_confirmation_count, "ожидает подтверждения"),
                _count_phrase(
                    health.failed_telegram_notification_count,
                    "не доставлено в Telegram",
                ),
                _count_phrase(health.unsent_pending_count, "ожидает отправки карточки"),
            )
        )
        return MonthCloseChecklistItem(
            code="bank_auto_accounting",
            status=MonthCloseItemStatus.BLOCKED,
            title="Автоучёт",
            message=f"Сначала разберите банковские события: {details}.",
            sort_order=10,
        )

    if health.unknown_event_count > 0:
        return MonthCloseChecklistItem(
            code="bank_auto_accounting",
            status=MonthCloseItemStatus.ATTENTION,
            title="Автоучёт",
            message=(
                f"Есть неизвестные банковские сообщения: {health.unknown_event_count}. "
                "Проверьте, не пропущены ли расходы."
            ),
            sort_order=10,
        )

    if health.active_source_count <= 0:
        return MonthCloseChecklistItem(
            code="bank_auto_accounting",
            status=MonthCloseItemStatus.ATTENTION,
            title="Автоучёт",
            message="Активные банковские источники не найдены. Проверьте расходы вручную.",
            sort_order=10,
        )

    saved = health.saved_expense_count
    income = health.income_event_count
    return MonthCloseChecklistItem(
        code="bank_auto_accounting",
        status=MonthCloseItemStatus.OK,
        title="Автоучёт",
        message=(
            f"Ожидающих действий нет. За {health.period_days} дней сохранено расходов: "
            f"{saved}, доходных событий: {income}."
        ),
        sort_order=10,
    )


def _income_item(report: MonthReport) -> MonthCloseChecklistItem:
    if report.has_income:
        return MonthCloseChecklistItem(
            code="income",
            status=MonthCloseItemStatus.OK,
            title="Доходы",
            message=f"Внесено доходов: {_money(report.income_total, report.currency)}.",
            sort_order=20,
        )
    return MonthCloseChecklistItem(
        code="income",
        status=MonthCloseItemStatus.ATTENTION,
        title="Доходы",
        message="Доходов за месяц пока нет. Если они были, внесите их до финального итога.",
        sort_order=20,
    )


def _expenses_item(report: MonthReport) -> MonthCloseChecklistItem:
    if report.has_expenses:
        return MonthCloseChecklistItem(
            code="expenses",
            status=MonthCloseItemStatus.OK,
            title="Расходы",
            message=f"Внесено расходов: {_money(report.total_amount, report.currency)}.",
            sort_order=30,
        )
    return MonthCloseChecklistItem(
        code="expenses",
        status=MonthCloseItemStatus.ATTENTION,
        title="Расходы",
        message=(
            "Расходов за месяц пока нет. Проверьте, что банк и ручной ввод ничего не пропустили."
        ),
        sort_order=30,
    )


def _cashflow_item(report: MonthReport) -> MonthCloseChecklistItem:
    if not report.has_activity:
        return MonthCloseChecklistItem(
            code="cashflow",
            status=MonthCloseItemStatus.ATTENTION,
            title="Денежный поток",
            message="Денежный поток пока пустой: нет доходов и расходов.",
            sort_order=40,
        )
    if not report.has_income or not report.has_expenses:
        return MonthCloseChecklistItem(
            code="cashflow",
            status=MonthCloseItemStatus.ATTENTION,
            title="Денежный поток",
            message=("Денежный поток неполный: для финального итога нужны и доходы, и расходы."),
            sort_order=40,
        )
    if report.net_after_expenses < 0:
        return MonthCloseChecklistItem(
            code="cashflow",
            status=MonthCloseItemStatus.ATTENTION,
            title="Денежный поток",
            message=(
                "После расходов месяц в минусе: "
                f"-{_money(abs(report.net_after_expenses), report.currency)}."
            ),
            sort_order=40,
        )
    return MonthCloseChecklistItem(
        code="cashflow",
        status=MonthCloseItemStatus.OK,
        title="Денежный поток",
        message=(
            f"После расходов остаётся: +{_money(report.net_after_expenses, report.currency)}."
        ),
        sort_order=40,
    )


def _limits_item(report: MonthReport) -> MonthCloseChecklistItem:
    if not report.has_expenses:
        return MonthCloseChecklistItem(
            code="limits",
            status=MonthCloseItemStatus.ATTENTION,
            title="Лимиты и резерв",
            message="Оценка лимитов появится после расходов.",
            sort_order=50,
        )
    if report.net_savings < 0:
        return MonthCloseChecklistItem(
            code="limits",
            status=MonthCloseItemStatus.ATTENTION,
            title="Лимиты и резерв",
            message=(
                f"По лимитам есть перерасход: {_money(abs(report.net_savings), report.currency)}."
            ),
            sort_order=50,
        )
    if report.has_income and report.net_after_expenses < 0:
        return MonthCloseChecklistItem(
            code="limits",
            status=MonthCloseItemStatus.ATTENTION,
            title="Лимиты и резерв",
            message=(
                "По лимитам есть свободный резерв, но реальный денежный поток сейчас в минусе."
            ),
            sort_order=50,
        )
    return MonthCloseChecklistItem(
        code="limits",
        status=MonthCloseItemStatus.OK,
        title="Лимиты и резерв",
        message=f"Можно отложить по лимитам: {_money(report.net_savings, report.currency)}.",
        sort_order=50,
    )


def _scope_item(summary: SmartMonthSummary) -> MonthCloseChecklistItem:
    snapshots = summary.scope_snapshots
    if not snapshots:
        return MonthCloseChecklistItem(
            code="scopes",
            status=MonthCloseItemStatus.ATTENTION,
            title="Дом и Салон",
            message="Разбивка по контурам недоступна для этого отчёта.",
            sort_order=60,
        )

    active_snapshots = [snapshot for snapshot in snapshots if snapshot.has_activity]
    if not active_snapshots:
        return MonthCloseChecklistItem(
            code="scopes",
            status=MonthCloseItemStatus.ATTENTION,
            title="Дом и Салон",
            message="По контурам пока нет доходов или расходов.",
            sort_order=60,
        )

    negative = [snapshot for snapshot in active_snapshots if snapshot.net_after_expenses < 0]
    if negative:
        details = ", ".join(
            f"{scope_label(snapshot.scope)}: "
            f"-{_money(abs(snapshot.net_after_expenses), summary.report.currency)}"
            for snapshot in negative
        )
        return MonthCloseChecklistItem(
            code="scopes",
            status=MonthCloseItemStatus.ATTENTION,
            title="Дом и Салон",
            message=f"Есть контуры в минусе после расходов: {details}.",
            sort_order=60,
        )

    details = ", ".join(
        f"{scope_label(snapshot.scope)}: "
        f"+{_money(snapshot.net_after_expenses, summary.report.currency)}"
        for snapshot in active_snapshots
    )
    return MonthCloseChecklistItem(
        code="scopes",
        status=MonthCloseItemStatus.OK,
        title="Дом и Салон",
        message=f"Контуры выглядят ровно: {details}.",
        sort_order=60,
    )


def _count_phrase(count: int, label: str) -> str:
    if count <= 0:
        return ""
    return f"{count} {label}"


def _join_non_empty(parts: tuple[str, ...]) -> str:
    return ", ".join(part for part in parts if part)


def _money(amount_minor: int, currency: str) -> str:
    return format_money_minor(round_minor_to_whole_units_minor(amount_minor), currency)


def _local_now(now: datetime | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    value = now or datetime.now(tz)
    if value.tzinfo is None:
        return value.replace(tzinfo=tz)
    return value.astimezone(tz)
