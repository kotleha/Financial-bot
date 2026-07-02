from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.domain.types import TransactionScope

if TYPE_CHECKING:
    from financial_bot.app.services.month_report_service import MonthReport


class MonthInsightSeverity(StrEnum):
    CRITICAL = "critical"
    ATTENTION = "attention"
    POSITIVE = "positive"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class MonthInsight:
    severity: MonthInsightSeverity
    code: str
    title: str
    message: str
    amount: int | None = None
    category_code: str | None = None
    sort_order: int = 0


@dataclass(frozen=True, slots=True)
class MonthConclusion:
    headline: str
    details: str | None
    insights: tuple[MonthInsight, ...]


@dataclass(frozen=True, slots=True)
class ScopeSnapshot:
    scope: TransactionScope
    expenses: int
    income: int
    net_after_expenses: int
    top_category_title: str | None = None

    @property
    def has_activity(self) -> bool:
        return self.expenses > 0 or self.income > 0


@dataclass(frozen=True, slots=True)
class CategoryChange:
    code: str
    title: str
    current_amount: int
    previous_amount: int
    delta_amount: int
    delta_percent: float


@dataclass(frozen=True, slots=True)
class AutoAccountingQuality:
    pending_confirmation_count: int = 0
    unknown_event_count: int = 0
    failed_telegram_notification_count: int = 0
    unsent_pending_count: int = 0

    @property
    def has_issues(self) -> bool:
        return (
            self.pending_confirmation_count > 0
            or self.unknown_event_count > 0
            or self.failed_telegram_notification_count > 0
            or self.unsent_pending_count > 0
        )


def build_month_conclusion(
    report: MonthReport,
    *,
    scope_snapshots: tuple[ScopeSnapshot, ...] = (),
    category_changes: tuple[CategoryChange, ...] = (),
    auto_accounting_quality: AutoAccountingQuality | None = None,
    max_insights: int = 5,
) -> MonthConclusion:
    if max_insights <= 0:
        msg = "max_insights must be positive"
        raise ValueError(msg)

    insights: list[MonthInsight] = []
    insights.extend(_auto_accounting_insights(auto_accounting_quality))
    insights.extend(_cashflow_insights(report))
    insights.extend(_limit_insights(report))
    insights.extend(_savings_insights(report))
    insights.extend(_category_change_insights(category_changes, report.currency))
    insights.extend(_scope_snapshot_insights(scope_snapshots, report.currency))
    insights.extend(_spending_mix_insights(report))

    if not report.has_activity and not insights:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.INFO,
                code="empty_month",
                title="Нет данных",
                message="За месяц пока нет расходов или доходов.",
                sort_order=900,
            )
        )

    return MonthConclusion(
        headline=_headline(report),
        details=_details(report),
        insights=_prioritize(insights, limit=max_insights),
    )


def _auto_accounting_insights(
    quality: AutoAccountingQuality | None,
) -> list[MonthInsight]:
    if quality is None or not quality.has_issues:
        return []

    insights: list[MonthInsight] = []
    if quality.failed_telegram_notification_count > 0:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.CRITICAL,
                code="bank_delivery_failed",
                title="Автоучёт",
                message=(
                    "Есть банковские события, которые не удалось отправить в Telegram: "
                    f"{quality.failed_telegram_notification_count}."
                ),
                sort_order=10,
            )
        )
    if quality.pending_confirmation_count > 0:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.ATTENTION,
                code="bank_pending_confirmations",
                title="Автоучёт",
                message=(
                    f"Ждут подтверждения банковские операции: {quality.pending_confirmation_count}."
                ),
                sort_order=20,
            )
        )
    if quality.unknown_event_count > 0:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.ATTENTION,
                code="bank_unknown_events",
                title="Автоучёт",
                message=f"Есть SMS неизвестного формата: {quality.unknown_event_count}.",
                sort_order=30,
            )
        )
    if quality.unsent_pending_count > 0:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.ATTENTION,
                code="bank_unsent_pending",
                title="Автоучёт",
                message=(
                    "Есть операции, которые ещё не были показаны в Telegram: "
                    f"{quality.unsent_pending_count}."
                ),
                sort_order=40,
            )
        )
    return insights


def _cashflow_insights(report: MonthReport) -> list[MonthInsight]:
    if not report.has_activity:
        return [
            MonthInsight(
                severity=MonthInsightSeverity.INFO,
                code="empty_month",
                title="Нет данных",
                message="За месяц пока нет расходов или доходов.",
                sort_order=900,
            )
        ]

    subject = _subject(report.scope)
    if report.has_income and report.has_expenses and report.net_after_expenses < 0:
        return [
            MonthInsight(
                severity=MonthInsightSeverity.CRITICAL,
                code="negative_cashflow",
                title="Денежный поток",
                message=(
                    f"{subject}: расходы выше внесённых доходов на "
                    f"{_money(abs(report.net_after_expenses), report.currency)}."
                ),
                amount=abs(report.net_after_expenses),
                sort_order=100,
            )
        ]

    if report.has_expenses and not report.has_income:
        return [
            MonthInsight(
                severity=MonthInsightSeverity.ATTENTION,
                code="income_missing",
                title="Доходы",
                message="Расходы уже есть, но доходы за месяц ещё не внесены.",
                sort_order=110,
            )
        ]

    if report.has_income and not report.has_expenses:
        return [
            MonthInsight(
                severity=MonthInsightSeverity.POSITIVE,
                code="income_only",
                title="Доходы",
                message=f"Доходы внесены: {_money(report.income_total, report.currency)}.",
                amount=report.income_total,
                sort_order=500,
            )
        ]

    if report.has_income and report.net_after_expenses >= 0:
        return [
            MonthInsight(
                severity=MonthInsightSeverity.POSITIVE,
                code="positive_cashflow",
                title="Денежный поток",
                message=(
                    f"{subject}: после расходов плюс "
                    f"{_money(report.net_after_expenses, report.currency)}."
                ),
                amount=report.net_after_expenses,
                sort_order=510,
            )
        ]

    return []


def _limit_insights(report: MonthReport) -> list[MonthInsight]:
    if report.scope is not None or not report.has_expenses:
        return []

    insights: list[MonthInsight] = []
    is_early_month = report.pace.elapsed_days <= max(report.pace.day_count // 2, 1)
    for line in report.budget_risks:
        if line.overrun_amount > 0:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.CRITICAL,
                    code=f"limit_overrun:{line.code}",
                    title=line.title,
                    message=(
                        f"{line.title} превысил лимит на "
                        f"{_money(line.overrun_amount, report.currency)}."
                    ),
                    amount=line.overrun_amount,
                    category_code=line.code,
                    sort_order=200 + line.sort_order,
                )
            )
        elif line.usage_percent >= 100:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.ATTENTION,
                    code=f"limit_reached:{line.code}",
                    title=line.title,
                    message=f"{line.title} достиг лимита; новые расходы уменьшат резерв.",
                    amount=line.remaining_amount,
                    category_code=line.code,
                    sort_order=240 + line.sort_order,
                )
            )
        elif line.usage_percent >= 80:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.ATTENTION,
                    code=f"limit_80:{line.code}",
                    title=line.title,
                    message=(
                        f"{line.title} уже {_percent(line.usage_percent)} лимита; "
                        f"осталось {_money(line.remaining_amount, report.currency)}."
                    ),
                    amount=line.remaining_amount,
                    category_code=line.code,
                    sort_order=250 + line.sort_order,
                )
            )
        elif line.usage_percent >= 50 and is_early_month:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.ATTENTION,
                    code=f"limit_50_early:{line.code}",
                    title=line.title,
                    message=(
                        f"{line.title} уже {_percent(line.usage_percent)} лимита "
                        f"на {report.pace.elapsed_days} день месяца."
                    ),
                    amount=line.spent_amount,
                    category_code=line.code,
                    sort_order=300 + line.sort_order,
                )
            )
    return insights


def _savings_insights(report: MonthReport) -> list[MonthInsight]:
    if report.scope is not None or not report.has_expenses:
        return []

    insights: list[MonthInsight] = []
    if report.net_savings < 0:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.CRITICAL,
                code="savings_negative",
                title="Резерв",
                message=(
                    "Превышения больше свободных лимитов; нужно компенсировать "
                    f"{_money(abs(report.net_savings), report.currency)}."
                ),
                amount=abs(report.net_savings),
                sort_order=400,
            )
        )
    elif report.net_savings > 0:
        has_negative_real_cashflow = report.has_income and report.net_after_expenses < 0
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.ATTENTION
                if has_negative_real_cashflow
                else MonthInsightSeverity.POSITIVE,
                code="savings_available",
                title="Резерв",
                message=(
                    f"По лимитам можно отложить до {_money(report.net_savings, report.currency)}."
                    if not has_negative_real_cashflow
                    else "По лимитам есть свободный резерв, но реальный cashflow сейчас в минусе."
                ),
                amount=report.net_savings,
                sort_order=520,
            )
        )

    for line in report.savings_target_lines:
        if line.delta_amount < 0:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.ATTENTION,
                    code=f"savings_target_gap:{line.code}",
                    title=line.title,
                    message=(
                        f"{line.title}: до цели не хватает "
                        f"{_money(abs(line.delta_amount), report.currency)}."
                    ),
                    amount=abs(line.delta_amount),
                    category_code=line.code,
                    sort_order=450 + line.sort_order,
                )
            )
        elif line.delta_amount > 0:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.POSITIVE,
                    code=f"savings_target_above:{line.code}",
                    title=line.title,
                    message=(
                        f"{line.title}: выше цели на {_money(line.delta_amount, report.currency)}."
                    ),
                    amount=line.delta_amount,
                    category_code=line.code,
                    sort_order=560 + line.sort_order,
                )
            )
    return insights


def _category_change_insights(
    category_changes: tuple[CategoryChange, ...],
    currency: str,
) -> list[MonthInsight]:
    return [
        MonthInsight(
            severity=MonthInsightSeverity.ATTENTION,
            code=f"category_growth:{change.code}",
            title=change.title,
            message=(
                f"{change.title} выше прошлого месяца на "
                f"{_money(change.delta_amount, currency)} ({_percent(change.delta_percent)})."
            ),
            amount=change.delta_amount,
            category_code=change.code,
            sort_order=350 + index,
        )
        for index, change in enumerate(category_changes)
    ]


def _scope_snapshot_insights(
    snapshots: tuple[ScopeSnapshot, ...],
    currency: str,
) -> list[MonthInsight]:
    insights: list[MonthInsight] = []
    for snapshot in snapshots:
        if not snapshot.has_activity:
            continue
        if snapshot.scope == TransactionScope.SALON and snapshot.net_after_expenses < 0:
            insights.append(
                MonthInsight(
                    severity=MonthInsightSeverity.ATTENTION,
                    code="salon_negative_cashflow",
                    title="Салон",
                    message=(
                        "Салон пока в минусе на "
                        f"{_money(abs(snapshot.net_after_expenses), currency)}."
                    ),
                    amount=abs(snapshot.net_after_expenses),
                    sort_order=360,
                )
            )
    return insights


def _spending_mix_insights(report: MonthReport) -> list[MonthInsight]:
    if not report.has_expenses:
        return []

    insights: list[MonthInsight] = []
    top_category = report.top_categories[0] if report.top_categories else None
    if top_category is not None and top_category.share_percent >= 35:
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.INFO,
                code=f"top_category_concentration:{top_category.code}",
                title=top_category.title,
                message=(
                    f"Самая крупная категория: {top_category.title}, "
                    f"{_percent(top_category.share_percent)} расходов."
                ),
                amount=top_category.amount,
                category_code=top_category.code,
                sort_order=700 + top_category.sort_order,
            )
        )

    if report.scope is None and report.no_limit_lines:
        line = max(report.no_limit_lines, key=lambda item: item.spent_amount)
        insights.append(
            MonthInsight(
                severity=MonthInsightSeverity.INFO,
                code=f"no_limit_spend:{line.code}",
                title=line.title,
                message=(
                    f"{line.title} без лимита; за месяц уже "
                    f"{_money(line.spent_amount, report.currency)}."
                ),
                amount=line.spent_amount,
                category_code=line.code,
                sort_order=750 + line.sort_order,
            )
        )
    return insights


def _headline(report: MonthReport) -> str:
    if not report.has_activity:
        return "За месяц пока нет данных для финансового вывода."

    subject = _subject(report.scope)
    if report.has_income and report.has_expenses and report.net_after_expenses < 0:
        return f"{subject} сейчас в минусе после расходов."
    if report.has_income and report.has_expenses:
        return f"{subject} сейчас в плюсе после расходов."
    if report.has_expenses:
        return f"{subject}: расходы есть, доходы ещё не внесены."
    return f"{subject}: доходы внесены, расходов пока нет."


def _details(report: MonthReport) -> str | None:
    if report.scope is not None and report.has_activity:
        return "Лимиты и копилка считаются только в общем отчёте по всем контурам."
    if not report.has_expenses:
        return None
    if report.has_income and report.net_after_expenses < 0:
        return (
            "Перед решением о резерве стоит закрыть минус "
            f"{_money(abs(report.net_after_expenses), report.currency)}."
        )
    if report.net_savings < 0:
        return (
            "Превышения уже съели свободные лимиты: нужно компенсировать "
            f"{_money(abs(report.net_savings), report.currency)}."
        )
    if report.net_savings > 0:
        if report.has_income:
            return (
                "По лимитам можно отложить до "
                f"{_money(report.net_savings, report.currency)}, если не будет новых превышений."
            )
        return (
            "По лимитам есть свободный резерв "
            f"{_money(report.net_savings, report.currency)}, но доходы ещё не внесены."
        )
    return None


def _prioritize(insights: list[MonthInsight], *, limit: int) -> tuple[MonthInsight, ...]:
    severity_rank = {
        MonthInsightSeverity.CRITICAL: 0,
        MonthInsightSeverity.ATTENTION: 1,
        MonthInsightSeverity.POSITIVE: 2,
        MonthInsightSeverity.INFO: 3,
    }
    deduplicated = {insight.code: insight for insight in insights}
    return tuple(
        sorted(
            deduplicated.values(),
            key=lambda insight: (
                severity_rank[insight.severity],
                insight.sort_order,
                insight.code,
            ),
        )[:limit]
    )


def _subject(scope: TransactionScope | None) -> str:
    if scope == TransactionScope.HOUSEHOLD:
        return "Дом"
    if scope == TransactionScope.SALON:
        return "Салон"
    return "Месяц"


def _money(amount_minor: int, currency: str) -> str:
    return format_money_minor(round_minor_to_whole_units_minor(amount_minor), currency)


def _percent(value: float) -> str:
    return f"{value:.1f}%".replace(".", ",")
