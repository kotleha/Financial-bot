from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile, gettempdir
from textwrap import wrap
from time import time
from zoneinfo import ZoneInfo

import matplotlib
from sqlalchemy.ext.asyncio import AsyncSession

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter, MaxNLocator

from financial_bot.app.config import Settings
from financial_bot.app.domain.accounting_scope import scope_filter_label
from financial_bot.app.domain.money import format_money_minor, round_minor_to_whole_units_minor
from financial_bot.app.domain.months import parse_month_token
from financial_bot.app.domain.periods import (
    MONTH_NAMES,
    Period,
    PeriodKind,
    resolve_month_period,
    resolve_period,
)
from financial_bot.app.domain.types import TransactionScope
from financial_bot.app.services.cashflow_service import CashflowReport, CashflowService
from financial_bot.app.services.month_report_service import MonthReport, MonthReportService
from financial_bot.app.services.report_service import ReportService
from financial_bot.app.services.spending_limit_service import BudgetLimitLine, BudgetReport
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository

CATEGORY_CHART_COLORS = (
    "#14b8a6",
    "#60a5fa",
    "#f59e0b",
    "#a78bfa",
    "#34d399",
    "#f87171",
    "#94a3b8",
    "#22d3ee",
)
DASHBOARD_COLORS = {
    "ink": "#f8fafc",
    "muted": "#9fb3c8",
    "line": "#2b3b4f",
    "grid": "#314256",
    "bg": "#0e1621",
    "panel": "#182533",
    "green": "#059669",
    "blue": "#60a5fa",
    "amber": "#f59e0b",
    "red": "#f87171",
    "violet": "#a78bfa",
    "cyan": "#0891b2",
}
CHART_FILE_PREFIX = "money-bot-chart-"
CHART_MAX_AGE_SECONDS = 24 * 60 * 60
DEFAULT_CHART_TEMP_DIR = Path(gettempdir()) / "money-bot-charts"


@dataclass(frozen=True, slots=True)
class ChartResult:
    path: Path
    caption: str


class ChartService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        chart_temp_dir: Path | None = None,
    ) -> None:
        self._settings = settings
        self._chart_temp_dir = chart_temp_dir or DEFAULT_CHART_TEMP_DIR
        self._cashflow = CashflowService(session, settings)
        self._month_reports = MonthReportService(session, settings)
        self._reports = ReportService(session, settings)
        self._transactions = TransactionRepository(session)

    async def create_period_dashboard_chart(
        self,
        kind: PeriodKind,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        if kind == PeriodKind.MONTH:
            return await self.create_month_dashboard_chart(now=now, scope=scope)

        report = await self._reports.build_period_report(kind, now=now, scope=scope)
        if report.total_amount <= 0:
            return None

        cumulative = await self._cumulative_values(report.period, scope=scope)
        day_count = _elapsed_period_days(
            report.period,
            now=now,
            timezone=self._settings.timezone,
        )
        average_per_day = round_minor_to_whole_units_minor(
            Decimal(report.total_amount) / Decimal(day_count)
        )
        top_categories = report.by_category[:8]

        fig = plt.figure(figsize=(13, 9.5), facecolor=DASHBOARD_COLORS["bg"])
        grid = fig.add_gridspec(
            4,
            6,
            height_ratios=[0.72, 1.05, 2.25, 1.5],
            hspace=0.58,
            wspace=0.42,
        )

        title_ax = fig.add_subplot(grid[0, :])
        title_ax.axis("off")
        title_ax.text(
            0,
            0.72,
            "Финансовый дашборд",
            fontsize=22,
            fontweight="bold",
            color=DASHBOARD_COLORS["ink"],
        )
        title_ax.text(
            0,
            0.24,
            _period_subtitle(report.period.label, report.scope),
            fontsize=11,
            color=DASHBOARD_COLORS["muted"],
        )

        metric_axes = (
            fig.add_subplot(grid[1, 0:2]),
            fig.add_subplot(grid[1, 2:4]),
            fig.add_subplot(grid[1, 4:6]),
        )
        _draw_metric_panel(
            metric_axes[0],
            label="Расходы",
            value=report.total_amount,
            currency=report.currency,
            color=DASHBOARD_COLORS["blue"],
        )
        _draw_metric_panel(
            metric_axes[1],
            label="Средний день",
            value=average_per_day,
            currency=report.currency,
            color=DASHBOARD_COLORS["amber"],
        )
        _draw_text_metric_panel(
            metric_axes[2],
            label="Категорий",
            value=f"{len(report.by_category)}",
            color=DASHBOARD_COLORS["violet"],
        )

        category_ax = fig.add_subplot(grid[2, :3])
        _draw_top_categories(category_ax, top_categories, report.currency)

        cumulative_ax = fig.add_subplot(grid[2, 3:])
        _draw_period_cumulative(cumulative_ax, cumulative, report.period)

        payer_ax = fig.add_subplot(grid[3, :3])
        _draw_payer_split(payer_ax, report.by_payer, report.currency)

        summary_ax = fig.add_subplot(grid[3, 3:])
        _draw_period_summary(summary_ax, report.by_category, report.currency)

        return _save_figure(
            fig,
            _caption_with_scope(f"Дашборд за {report.period.label}", report.scope),
            temp_dir=self._chart_temp_dir,
            tight_layout=False,
        )

    async def create_month_dashboard_chart(
        self,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        report = await self._month_reports.build_month_report(
            now=now,
            top_category_limit=7,
            budget_risk_limit=7,
            scope=scope,
        )
        if report.total_amount <= 0:
            return None

        budget = report.budget

        fig = plt.figure(figsize=(13, 9.5), facecolor=DASHBOARD_COLORS["bg"])
        grid = fig.add_gridspec(
            4,
            6,
            height_ratios=[0.72, 1.05, 2.2, 1.55],
            hspace=0.55,
            wspace=0.42,
        )

        title_ax = fig.add_subplot(grid[0, :])
        title_ax.axis("off")
        title_ax.text(
            0,
            0.72,
            "Финансовый дашборд месяца",
            fontsize=22,
            fontweight="bold",
            color=DASHBOARD_COLORS["ink"],
        )
        title_ax.text(
            0,
            0.24,
            _period_subtitle(
                f"{report.period.label} · день {report.pace.elapsed_days} из "
                f"{report.pace.day_count}",
                report.scope,
            ),
            fontsize=11,
            color=DASHBOARD_COLORS["muted"],
        )

        metrics = _month_dashboard_metrics(report)
        for index, (label, value, color) in enumerate(metrics):
            ax = fig.add_subplot(grid[1, index * 2 : index * 2 + 2])
            if isinstance(value, int):
                _draw_metric_panel(
                    ax,
                    label=label,
                    value=value,
                    currency=report.currency,
                    color=color,
                )
            else:
                _draw_text_metric_panel(ax, label=label, value=value, color=color)

        category_ax = fig.add_subplot(grid[2, :3])
        _draw_top_categories(category_ax, report.top_categories, report.currency)

        budget_ax = fig.add_subplot(grid[2, 3:])
        if report.scope is None:
            _draw_budget_risks(budget_ax, report.budget_risks)
        else:
            _draw_scope_budget_note(budget_ax, report.scope)

        payer_ax = fig.add_subplot(grid[3, :3])
        _draw_payer_split(payer_ax, report.by_payer, report.currency)

        note_ax = fig.add_subplot(grid[3, 3:])
        if report.scope is None:
            _draw_budget_note(note_ax, budget)
        else:
            _draw_payer_report_summary(note_ax, report.by_payer, report.currency)

        return _save_figure(
            fig,
            _caption_with_scope(f"Дашборд за {report.period.label}", report.scope),
            temp_dir=self._chart_temp_dir,
            tight_layout=False,
        )

    async def create_cashflow_dashboard_chart(
        self,
        kind: PeriodKind = PeriodKind.MONTH,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        report = await self._cashflow.build_report(kind, now=now, scope=scope)
        if report.income_total <= 0 and report.expense_total <= 0:
            return None

        fig = plt.figure(figsize=(13, 9.5), facecolor=DASHBOARD_COLORS["bg"])
        grid = fig.add_gridspec(
            4,
            6,
            height_ratios=[0.72, 1.05, 2.25, 1.5],
            hspace=0.58,
            wspace=0.42,
        )

        title_ax = fig.add_subplot(grid[0, :])
        title_ax.axis("off")
        title_ax.text(
            0,
            0.72,
            "Денежный поток",
            fontsize=22,
            fontweight="bold",
            color=DASHBOARD_COLORS["ink"],
        )
        title_ax.text(
            0,
            0.24,
            _period_subtitle(report.period.label, report.scope),
            fontsize=11,
            color=DASHBOARD_COLORS["muted"],
        )

        metric_axes = (
            fig.add_subplot(grid[1, 0:2]),
            fig.add_subplot(grid[1, 2:4]),
            fig.add_subplot(grid[1, 4:6]),
        )
        _draw_metric_panel(
            metric_axes[0],
            label="Доходы",
            value=report.income_total,
            currency=report.currency,
            color=DASHBOARD_COLORS["green"],
        )
        _draw_metric_panel(
            metric_axes[1],
            label="Расходы",
            value=report.expense_total,
            currency=report.currency,
            color=DASHBOARD_COLORS["blue"],
        )
        _draw_metric_panel(
            metric_axes[2],
            label="Итог после расходов",
            value=report.net_after_expenses,
            currency=report.currency,
            color=_savings_color(report.net_after_expenses),
        )

        category_ax = fig.add_subplot(grid[2, :3])
        _draw_income_categories(category_ax, report)

        summary_ax = fig.add_subplot(grid[2, 3:])
        _draw_cashflow_summary(summary_ax, report)

        recipient_ax = fig.add_subplot(grid[3, :3])
        _draw_recipient_split(recipient_ax, report)

        note_ax = fig.add_subplot(grid[3, 3:])
        _draw_cashflow_note(note_ax, report)

        return _save_figure(
            fig,
            _caption_with_scope(f"Денежный поток за {report.period.label}", report.scope),
            temp_dir=self._chart_temp_dir,
            tight_layout=False,
        )

    async def create_payer_report_chart(
        self,
        kind: PeriodKind = PeriodKind.MONTH,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        report = await self._reports.build_period_report(kind, now=now, scope=scope)
        if report.total_amount <= 0:
            return None

        fig = plt.figure(figsize=(11, 6.5), facecolor=DASHBOARD_COLORS["bg"])
        grid = fig.add_gridspec(
            3,
            4,
            height_ratios=[0.72, 1.05, 2.6],
            hspace=0.55,
            wspace=0.42,
        )

        title_ax = fig.add_subplot(grid[0, :])
        title_ax.axis("off")
        title_ax.text(
            0,
            0.72,
            "Кто платил",
            fontsize=22,
            fontweight="bold",
            color=DASHBOARD_COLORS["ink"],
        )
        title_ax.text(
            0,
            0.24,
            _period_subtitle(report.period.label, report.scope),
            fontsize=11,
            color=DASHBOARD_COLORS["muted"],
        )

        payer_amounts = {line.role: line.amount for line in report.by_payer}
        metrics = (
            ("Всего", report.total_amount, DASHBOARD_COLORS["blue"]),
            ("Муж", payer_amounts.get("husband", 0), DASHBOARD_COLORS["cyan"]),
            ("Жена", payer_amounts.get("wife", 0), DASHBOARD_COLORS["violet"]),
        )
        for index, (label, value, color) in enumerate(metrics):
            ax = fig.add_subplot(grid[1, index * 4 // 3 : (index + 1) * 4 // 3])
            _draw_metric_panel(ax, label=label, value=value, currency=report.currency, color=color)

        payer_ax = fig.add_subplot(grid[2, :2])
        _draw_payer_split(payer_ax, report.by_payer, report.currency)

        summary_ax = fig.add_subplot(grid[2, 2:])
        _draw_payer_report_summary(summary_ax, report.by_payer, report.currency)

        return _save_figure(
            fig,
            _caption_with_scope(f"Кто платил за {report.period.label}", report.scope),
            temp_dir=self._chart_temp_dir,
            tight_layout=False,
        )

    async def create_categories_chart(
        self,
        kind: PeriodKind = PeriodKind.MONTH,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        report = await self._reports.build_period_report(kind, now=now, scope=scope)
        if report.total_amount <= 0 or not report.by_category:
            return None

        labels = [_wrap_category_label(line.title) for line in report.by_category]
        values = [_rub(line.amount) for line in report.by_category]
        labels_for_plot = list(reversed(labels))
        values_for_plot = list(reversed(values))
        colors = [
            CATEGORY_CHART_COLORS[index % len(CATEGORY_CHART_COLORS)]
            for index in range(len(values_for_plot))
        ]

        fig, ax = plt.subplots(
            figsize=(11, max(5.0, len(labels) * 0.58 + 1.4)),
            facecolor=DASHBOARD_COLORS["bg"],
        )
        ax.set_facecolor(DASHBOARD_COLORS["bg"])
        bars = ax.barh(labels_for_plot, values_for_plot, color=colors, height=0.62)

        max_value = max(values_for_plot)
        right_padding = max(max_value * 0.18, 1)
        ax.set_xlim(0, max_value + right_padding)
        for bar, value in zip(bars, values_for_plot, strict=True):
            ax.text(
                value + right_padding * 0.08,
                bar.get_y() + bar.get_height() / 2,
                _format_rub_value(value),
                va="center",
                fontsize=9,
                color=DASHBOARD_COLORS["muted"],
            )

        ax.set_title(
            "Расходы по категориям",
            loc="left",
            fontsize=15,
            fontweight="bold",
            pad=22,
            color=DASHBOARD_COLORS["ink"],
        )
        ax.text(
            0,
            1.015,
            f"{_period_subtitle(report.period.label, report.scope)} · всего "
            f"{_format_rub_value(_rub(report.total_amount))}",
            transform=ax.transAxes,
            fontsize=10,
            color=DASHBOARD_COLORS["muted"],
        )
        ax.set_xlabel("Рубли", color=DASHBOARD_COLORS["muted"])
        ax.grid(axis="x", alpha=0.42, color=DASHBOARD_COLORS["grid"])
        ax.tick_params(axis="x", colors=DASHBOARD_COLORS["muted"], labelsize=9)
        ax.tick_params(axis="y", colors=DASHBOARD_COLORS["ink"], labelsize=9)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color(DASHBOARD_COLORS["line"])
        _format_number_axis(ax)
        return _save_figure(
            fig,
            _caption_with_scope(f"Категории за {report.period.label}", report.scope),
            temp_dir=self._chart_temp_dir,
        )

    async def create_cumulative_chart(
        self,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        period = resolve_period(PeriodKind.MONTH, now=now, timezone=self._settings.timezone)
        cumulative = await self._cumulative_values(period, scope=scope)
        if not cumulative or cumulative[-1] <= 0:
            return None

        days = list(range(1, len(cumulative) + 1))
        fig, ax = _create_dark_axes(figsize=(10, 5))
        ax.plot(days, cumulative, linewidth=2.5, color="#059669")
        ax.set_title(
            f"Накопительные расходы: {_period_subtitle(period.label, scope)}",
            color=DASHBOARD_COLORS["ink"],
        )
        ax.set_xlabel("День месяца", color=DASHBOARD_COLORS["muted"])
        ax.set_ylabel("₽", color=DASHBOARD_COLORS["muted"])
        ax.grid(alpha=0.42, color=DASHBOARD_COLORS["grid"])
        _format_number_axis(ax, axis="y")
        return _save_figure(
            fig,
            _caption_with_scope(f"Накопительные расходы за {period.label}", scope),
            temp_dir=self._chart_temp_dir,
        )

    async def create_compare_months_chart(
        self,
        month_tokens: Sequence[str],
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        if not month_tokens:
            msg = "At least one month is required"
            raise ValueError(msg)

        local_now = _local_now(now, self._settings.timezone)
        periods = [
            resolve_month_period(
                year=local_now.year,
                month=parse_month_token(token),
                timezone=self._settings.timezone,
            )
            for token in month_tokens
        ]
        series = [
            (period, await self._cumulative_values(period, scope=scope)) for period in periods
        ]
        if not any(values and values[-1] > 0 for _, values in series):
            return None

        fig, ax = _create_dark_axes(figsize=(10, 5))
        for period, values in series:
            ax.plot(range(1, len(values) + 1), values, linewidth=2, label=period.label)
        ax.set_title(
            _caption_with_scope("Наложение месяцев", scope),
            color=DASHBOARD_COLORS["ink"],
        )
        ax.set_xlabel("День месяца", color=DASHBOARD_COLORS["muted"])
        ax.set_ylabel("₽", color=DASHBOARD_COLORS["muted"])
        ax.grid(alpha=0.42, color=DASHBOARD_COLORS["grid"])
        legend = ax.legend(
            facecolor=DASHBOARD_COLORS["panel"],
            edgecolor=DASHBOARD_COLORS["line"],
        )
        for text in legend.get_texts():
            text.set_color(DASHBOARD_COLORS["ink"])
        _format_number_axis(ax, axis="y")
        return _save_figure(
            fig,
            _caption_with_scope("Сравнение месяцев", scope),
            temp_dir=self._chart_temp_dir,
        )

    async def create_trend_chart(
        self,
        month_count: int,
        *,
        now: datetime | None = None,
        scope: TransactionScope | None = None,
    ) -> ChartResult | None:
        if month_count <= 0 or month_count > 24:
            msg = "Trend month count must be in 1..24"
            raise ValueError(msg)

        local_now = _local_now(now, self._settings.timezone)
        periods = [
            resolve_month_period(year=year, month=month, timezone=self._settings.timezone)
            for year, month in _previous_months(
                year=local_now.year,
                month=local_now.month,
                count=month_count,
            )
        ]
        reports = [
            await self._reports.build_period_report(
                PeriodKind.MONTH,
                now=period.start_at,
                scope=scope,
            )
            for period in periods
        ]
        values = [_rub(report.total_amount) for report in reports]
        if not any(value > 0 for value in values):
            return None

        labels = [
            f"{MONTH_NAMES[period.start_at.month][:3]} {period.start_at.year}" for period in periods
        ]
        fig, ax = _create_dark_axes(figsize=(max(8, month_count * 0.7), 5))
        ax.bar(labels, values, color="#7c3aed")
        ax.set_title(
            _caption_with_scope(f"Тренд расходов за {month_count} мес.", scope),
            color=DASHBOARD_COLORS["ink"],
        )
        ax.set_ylabel("₽", color=DASHBOARD_COLORS["muted"])
        ax.grid(axis="y", alpha=0.42, color=DASHBOARD_COLORS["grid"])
        ax.tick_params(axis="x", rotation=35, colors=DASHBOARD_COLORS["muted"])
        _format_number_axis(ax, axis="y")
        return _save_figure(
            fig,
            _caption_with_scope(f"Тренд за {month_count} мес.", scope),
            temp_dir=self._chart_temp_dir,
        )

    async def _cumulative_values(
        self,
        period: Period,
        *,
        scope: TransactionScope | None = None,
    ) -> list[float]:
        timezone = ZoneInfo(self._settings.timezone)
        transactions = await self._transactions.list_report_effective_for_period(
            period.start_at,
            period.end_at,
            scope=scope,
        )
        day_count = (period.end_at.date() - period.start_at.date()).days
        amounts_by_day = {day: 0 for day in range(1, day_count + 1)}
        for transaction in transactions:
            local_date = _to_local_datetime(transaction.occurred_at, timezone).date()
            day_index = (local_date - period.start_at.date()).days + 1
            if 1 <= day_index <= day_count:
                amounts_by_day[day_index] += _report_amount(transaction)

        cumulative: list[float] = []
        running_amount = 0
        for day_index in range(1, day_count + 1):
            running_amount += amounts_by_day[day_index]
            cumulative.append(_rub(running_amount))
        return cumulative


def _save_figure(
    fig,
    caption: str,
    *,
    temp_dir: Path = DEFAULT_CHART_TEMP_DIR,
    tight_layout: bool = True,
) -> ChartResult:
    temp_dir.mkdir(parents=True, exist_ok=True)
    _cleanup_old_chart_files(temp_dir)
    with NamedTemporaryFile(
        prefix=CHART_FILE_PREFIX,
        suffix=".png",
        dir=temp_dir,
        delete=False,
    ) as temporary_file:
        path = Path(temporary_file.name)
    try:
        if tight_layout:
            fig.tight_layout()
        fig.savefig(path, format="png", dpi=160, bbox_inches="tight")
    finally:
        plt.close(fig)
    return ChartResult(path=path, caption=caption)


def _create_dark_axes(*, figsize: tuple[float, float]):
    fig, ax = plt.subplots(figsize=figsize, facecolor=DASHBOARD_COLORS["bg"])
    ax.set_facecolor(DASHBOARD_COLORS["panel"])
    ax.tick_params(axis="x", colors=DASHBOARD_COLORS["muted"], labelsize=9)
    ax.tick_params(axis="y", colors=DASHBOARD_COLORS["muted"], labelsize=9)
    for spine in ax.spines.values():
        spine.set_color(DASHBOARD_COLORS["line"])
    return fig, ax


def _month_dashboard_metrics(report: MonthReport) -> tuple[tuple[str, int | str, str], ...]:
    if report.scope is not None:
        return (
            ("Потрачено", report.total_amount, DASHBOARD_COLORS["blue"]),
            ("Прогноз месяца", report.pace.forecast_amount, DASHBOARD_COLORS["amber"]),
            ("Категорий", str(len(report.top_categories)), DASHBOARD_COLORS["violet"]),
        )
    return (
        ("Потрачено", report.total_amount, DASHBOARD_COLORS["blue"]),
        ("Прогноз месяца", report.pace.forecast_amount, DASHBOARD_COLORS["amber"]),
        (
            "Копилка по лимитам",
            report.budget.net_savings,
            _savings_color(report.budget.net_savings),
        ),
    )


def _period_subtitle(label: str, scope: TransactionScope | None) -> str:
    return f"{label} · {scope_filter_label(scope)}"


def _caption_with_scope(caption: str, scope: TransactionScope | None) -> str:
    return f"{caption} · {scope_filter_label(scope)}"


def _draw_metric_panel(ax, *, label: str, value: int, currency: str, color: str) -> None:
    _style_panel(ax)
    ax.text(0.06, 0.72, label, transform=ax.transAxes, fontsize=10, color=DASHBOARD_COLORS["muted"])
    ax.text(
        0.06,
        0.32,
        _format_dashboard_money(value, currency),
        transform=ax.transAxes,
        fontsize=19,
        fontweight="bold",
        color=color,
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_text_metric_panel(ax, *, label: str, value: str, color: str) -> None:
    _style_panel(ax)
    ax.text(0.06, 0.72, label, transform=ax.transAxes, fontsize=10, color=DASHBOARD_COLORS["muted"])
    ax.text(
        0.06,
        0.32,
        value,
        transform=ax.transAxes,
        fontsize=19,
        fontweight="bold",
        color=color,
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_top_categories(ax, categories, currency: str) -> None:
    _style_panel(ax)
    ax.set_title(
        "Куда ушли деньги",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if not categories:
        _draw_empty_panel_text(ax, "Нет расходов по категориям")
        return

    labels = [_wrap_category_label(category.title) for category in reversed(categories)]
    values = [_rub(category.amount) for category in reversed(categories)]
    colors = [
        CATEGORY_CHART_COLORS[index % len(CATEGORY_CHART_COLORS)] for index in range(len(values))
    ]
    bars = ax.barh(labels, values, color=colors, height=0.58)
    max_value = max(values)
    right_padding = max(max_value * 0.28, 1)
    ax.set_xlim(0, max_value + right_padding)
    for bar, category in zip(bars, reversed(categories), strict=True):
        ax.text(
            bar.get_width() + right_padding * 0.05,
            bar.get_y() + bar.get_height() / 2,
            _format_dashboard_money(category.amount, currency),
            va="center",
            fontsize=8.5,
            color=DASHBOARD_COLORS["muted"],
        )
    ax.tick_params(axis="y", labelsize=8.5, colors=DASHBOARD_COLORS["ink"])
    ax.tick_params(axis="x", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.grid(axis="x", alpha=0.42, color=DASHBOARD_COLORS["grid"])
    _format_number_axis(ax, compact=True, max_ticks=4)


def _draw_period_cumulative(ax, cumulative: Sequence[float], period: Period) -> None:
    _style_panel(ax)
    ax.set_title(
        "Динамика периода",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if not cumulative or cumulative[-1] <= 0:
        _draw_empty_panel_text(ax, "Нет расходов для динамики")
        return

    days = list(range(1, len(cumulative) + 1))
    ax.plot(days, cumulative, linewidth=2.2, color=DASHBOARD_COLORS["green"])
    ax.fill_between(days, cumulative, color=DASHBOARD_COLORS["green"], alpha=0.10)
    ax.set_xlim(1, max(days))
    ax.set_xlabel("День периода", fontsize=8.5, color=DASHBOARD_COLORS["muted"])
    ax.tick_params(axis="x", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.tick_params(axis="y", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.grid(alpha=0.42, color=DASHBOARD_COLORS["grid"])
    _format_number_axis(ax, axis="y")

    if period.kind == PeriodKind.WEEK:
        ax.set_xticks(days)
    elif period.kind in {PeriodKind.QUARTER, PeriodKind.HALFYEAR, PeriodKind.YEAR}:
        tick_count = 6 if period.kind != PeriodKind.YEAR else 7
        tick_step = max(len(days) // tick_count, 1)
        ax.set_xticks([1, *range(tick_step, len(days) + 1, tick_step)])


def _draw_budget_risks(ax, risk_lines: Sequence[BudgetLimitLine]) -> None:
    _style_panel(ax)
    ax.set_title(
        "Лимиты под вниманием",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if not risk_lines:
        _draw_empty_panel_text(ax, "Нет лимитов выше 50%")
        return

    labels = [_wrap_category_label(line.title) for line in reversed(risk_lines)]
    values = [min(line.usage_percent, 110.0) for line in reversed(risk_lines)]
    colors = [_usage_color(line.usage_percent) for line in reversed(risk_lines)]
    bars = ax.barh(labels, values, color=colors, height=0.58)
    ax.set_xlim(0, 112)
    ax.axvline(50, color="#94a3b8", linewidth=0.8, alpha=0.45)
    ax.axvline(80, color="#f59e0b", linewidth=0.8, alpha=0.55)
    ax.axvline(100, color="#dc2626", linewidth=1.0, alpha=0.65)
    for bar, line in zip(bars, reversed(risk_lines), strict=True):
        ax.text(
            min(bar.get_width() + 2, 104),
            bar.get_y() + bar.get_height() / 2,
            f"{line.usage_percent:.0f}%",
            va="center",
            fontsize=8.5,
            color=DASHBOARD_COLORS["ink"],
        )
    ax.tick_params(axis="y", labelsize=8.5, colors=DASHBOARD_COLORS["ink"])
    ax.tick_params(axis="x", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.grid(axis="x", alpha=0.42, color=DASHBOARD_COLORS["grid"])


def _draw_scope_budget_note(ax, scope: TransactionScope) -> None:
    _style_panel(ax)
    ax.set_title(
        "Контур отчёта",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    rows = [
        ("Показан контур", scope_filter_label(scope), DASHBOARD_COLORS["cyan"]),
        ("Лимиты", "в общем отчёте", DASHBOARD_COLORS["muted"]),
        ("Копилка", "в общем отчёте", DASHBOARD_COLORS["muted"]),
    ]
    y = 0.72
    for label, value, color in rows:
        ax.text(
            0.06,
            y,
            label,
            transform=ax.transAxes,
            fontsize=10,
            color=DASHBOARD_COLORS["muted"],
        )
        ax.text(
            0.94,
            y,
            value,
            transform=ax.transAxes,
            fontsize=12,
            fontweight="bold",
            color=color,
            ha="right",
        )
        y -= 0.22
    ax.text(
        0.06,
        0.08,
        "Бюджетные лимиты не дробятся между контурами.",
        transform=ax.transAxes,
        fontsize=9,
        color=DASHBOARD_COLORS["muted"],
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_payer_split(ax, payer_lines, currency: str) -> None:
    _style_panel(ax)
    ax.set_title(
        "Кто оплатил",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    labels = ["Муж" if line.role == "husband" else "Жена" for line in payer_lines]
    amounts = [line.amount for line in payer_lines]
    values = [_rub(amount) for amount in amounts]
    if not any(amounts):
        _draw_empty_panel_text(ax, "Нет оплат за период")
        return
    colors = (DASHBOARD_COLORS["blue"], DASHBOARD_COLORS["violet"])
    bars = ax.barh(labels, values, color=colors, height=0.42)
    max_value = max(values)
    right_padding = max(max_value * 0.42, 1)
    ax.set_xlim(0, max_value + right_padding)
    for bar, line in zip(bars, payer_lines, strict=True):
        ax.text(
            bar.get_width() + right_padding * 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"{line.share_percent:.0f}% · {format_money_minor(line.amount, currency)}",
            va="center",
            fontsize=9.5,
            color=DASHBOARD_COLORS["ink"],
        )
    ax.tick_params(axis="y", labelsize=10, colors=DASHBOARD_COLORS["ink"])
    ax.tick_params(axis="x", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.grid(axis="x", alpha=0.42, color=DASHBOARD_COLORS["grid"])
    _format_number_axis(ax, compact=True, max_ticks=4)


def _draw_payer_report_summary(ax, payer_lines, currency: str) -> None:
    _style_panel(ax)
    ax.set_title(
        "Сводка",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if not payer_lines:
        _draw_empty_panel_text(ax, "Нет данных по плательщикам")
        return

    y = 0.78
    for line in payer_lines:
        role = "Муж" if line.role == "husband" else "Жена"
        color = DASHBOARD_COLORS["blue"] if line.role == "husband" else DASHBOARD_COLORS["violet"]
        ax.text(0.06, y, role, transform=ax.transAxes, fontsize=11, color=DASHBOARD_COLORS["ink"])
        ax.text(
            0.06,
            y - 0.12,
            f"{format_money_minor(line.amount, currency)} · {line.share_percent:.1f}%",
            transform=ax.transAxes,
            fontsize=13,
            fontweight="bold",
            color=color,
        )
        y -= 0.32
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_budget_note(ax, budget: BudgetReport) -> None:
    _style_panel(ax)
    ax.set_title(
        "Итог по бюджету",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    rows = [
        ("Запас по лимитам", budget.under_budget_pool, DASHBOARD_COLORS["green"]),
        ("Перерасход", budget.overrun_total, DASHBOARD_COLORS["red"]),
        ("Оценка копилки", budget.net_savings, _savings_color(budget.net_savings)),
    ]
    y = 0.72
    for label, amount, color in rows:
        ax.text(
            0.06, y, label, transform=ax.transAxes, fontsize=10, color=DASHBOARD_COLORS["muted"]
        )
        ax.text(
            0.62,
            y,
            _format_dashboard_money(amount, budget.currency),
            transform=ax.transAxes,
            fontsize=12,
            fontweight="bold",
            color=color,
            ha="right",
        )
        y -= 0.22
    if budget.savings_target_lines:
        target = budget.savings_target_lines[0]
        ax.text(
            0.06,
            0.08,
            f"Накопления: {format_money_minor(target.actual_amount, budget.currency)} "
            f"из {format_money_minor(target.target_amount, budget.currency)}",
            transform=ax.transAxes,
            fontsize=9,
            color=DASHBOARD_COLORS["muted"],
        )
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_income_categories(ax, report: CashflowReport) -> None:
    _style_panel(ax)
    ax.set_title(
        "Доходы по источникам",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if not report.income_by_category:
        _draw_empty_panel_text(ax, "Нет доходов за период")
        return

    rows = report.income_by_category[:7]
    labels = [_wrap_category_label(line.title) for line in reversed(rows)]
    values = [_rub(line.amount) for line in reversed(rows)]
    colors = [
        CATEGORY_CHART_COLORS[index % len(CATEGORY_CHART_COLORS)] for index in range(len(values))
    ]
    bars = ax.barh(labels, values, color=colors, height=0.58)
    max_value = max(values)
    right_padding = max(max_value * 0.28, 1)
    ax.set_xlim(0, max_value + right_padding)
    for bar, line in zip(bars, reversed(rows), strict=True):
        ax.text(
            bar.get_width() + right_padding * 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"{line.share_percent:.0f}% · {format_money_minor(line.amount, report.currency)}",
            va="center",
            fontsize=8.5,
            color=DASHBOARD_COLORS["muted"],
        )
    ax.tick_params(axis="y", labelsize=8.5, colors=DASHBOARD_COLORS["ink"])
    ax.tick_params(axis="x", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.grid(axis="x", alpha=0.42, color=DASHBOARD_COLORS["grid"])
    _format_number_axis(ax, compact=True, max_ticks=4)


def _draw_cashflow_summary(ax, report: CashflowReport) -> None:
    _style_panel(ax)
    ax.set_title(
        "Сводка движения",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    rows = [
        ("Доходы", report.income_total, DASHBOARD_COLORS["green"]),
        ("Расходы", -report.expense_total, DASHBOARD_COLORS["red"]),
        ("Итог", report.net_after_expenses, _savings_color(report.net_after_expenses)),
    ]
    y = 0.72
    for label, amount, color in rows:
        ax.text(
            0.06, y, label, transform=ax.transAxes, fontsize=11, color=DASHBOARD_COLORS["muted"]
        )
        ax.text(
            0.94,
            y,
            _format_signed_dashboard_money(amount, report.currency),
            transform=ax.transAxes,
            fontsize=13,
            fontweight="bold",
            color=color,
            ha="right",
        )
        y -= 0.22
    ax.text(
        0.06,
        0.08,
        "Доходы не входят в расходные лимиты и графики категорий.",
        transform=ax.transAxes,
        fontsize=9,
        color=DASHBOARD_COLORS["muted"],
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_recipient_split(ax, report: CashflowReport) -> None:
    _style_panel(ax)
    ax.set_title(
        "Кто получил",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if report.income_total <= 0:
        _draw_empty_panel_text(ax, "Нет доходов по получателям")
        return

    labels = ["Муж" if line.role == "husband" else "Жена" for line in report.income_by_recipient]
    values = [_rub(line.amount) for line in report.income_by_recipient]
    colors = (DASHBOARD_COLORS["blue"], DASHBOARD_COLORS["violet"])
    bars = ax.barh(labels, values, color=colors, height=0.42)
    max_value = max(values)
    right_padding = max(max_value * 0.42, 1)
    ax.set_xlim(0, max_value + right_padding)
    for bar, line in zip(bars, report.income_by_recipient, strict=True):
        ax.text(
            bar.get_width() + right_padding * 0.05,
            bar.get_y() + bar.get_height() / 2,
            f"{line.share_percent:.0f}% · {format_money_minor(line.amount, report.currency)}",
            va="center",
            fontsize=9.5,
            color=DASHBOARD_COLORS["ink"],
        )
    ax.tick_params(axis="y", labelsize=10, colors=DASHBOARD_COLORS["ink"])
    ax.tick_params(axis="x", labelsize=8, colors=DASHBOARD_COLORS["muted"])
    ax.grid(axis="x", alpha=0.42, color=DASHBOARD_COLORS["grid"])
    _format_number_axis(ax, compact=True, max_ticks=4)


def _draw_cashflow_note(ax, report: CashflowReport) -> None:
    _style_panel(ax)
    ax.set_title(
        "Контекст",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    rows = [
        (
            "Копилка по лимитам",
            report.budget_net_savings,
            _savings_color(report.budget_net_savings or 0),
        ),
        ("Категорий дохода", len(report.income_by_category), DASHBOARD_COLORS["cyan"]),
    ]
    y = 0.72
    for label, value, color in rows:
        ax.text(
            0.06, y, label, transform=ax.transAxes, fontsize=10, color=DASHBOARD_COLORS["muted"]
        )
        if report.scope is not None and label == "Копилка по лимитам":
            text_value = "В общем отчёте"
        elif isinstance(value, int) and label == "Категорий дохода":
            text_value = str(value)
        elif isinstance(value, int):
            text_value = _format_dashboard_money(value, report.currency)
        else:
            text_value = "Только для месяца"
        ax.text(
            0.94,
            y,
            text_value,
            transform=ax.transAxes,
            fontsize=12,
            fontweight="bold",
            color=color,
            ha="right",
        )
        y -= 0.22
    ax.text(
        0.06,
        0.14,
        "Расходы учитывают возвраты как корректировки.",
        transform=ax.transAxes,
        fontsize=9,
        color=DASHBOARD_COLORS["muted"],
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _draw_period_summary(ax, categories, currency: str) -> None:
    _style_panel(ax)
    ax.set_title(
        "Состав расходов",
        loc="left",
        fontsize=13,
        fontweight="bold",
        pad=14,
        color=DASHBOARD_COLORS["ink"],
    )
    if not categories:
        _draw_empty_panel_text(ax, "Нет категорий за период")
        return

    top_rows = categories[:5]
    other_count = max(len(categories) - len(top_rows), 0)
    other_amount = sum(line.amount for line in categories[len(top_rows) :])
    y = 0.76
    for line in top_rows:
        label = _truncate_text(line.title, 31)
        ax.text(
            0.06,
            y,
            label,
            transform=ax.transAxes,
            fontsize=9.5,
            color=DASHBOARD_COLORS["ink"],
        )
        ax.text(
            0.94,
            y,
            format_money_minor(line.amount, currency),
            transform=ax.transAxes,
            fontsize=9.5,
            fontweight="bold",
            color=DASHBOARD_COLORS["ink"],
            ha="right",
        )
        y -= 0.13

    if other_count:
        ax.text(
            0.06,
            y,
            f"Остальные категории: {other_count}",
            transform=ax.transAxes,
            fontsize=9.5,
            color=DASHBOARD_COLORS["muted"],
        )
        ax.text(
            0.94,
            y,
            format_money_minor(other_amount, currency),
            transform=ax.transAxes,
            fontsize=9.5,
            fontweight="bold",
            color=DASHBOARD_COLORS["muted"],
            ha="right",
        )
    ax.set_xticks([])
    ax.set_yticks([])


def _style_panel(ax) -> None:
    ax.set_facecolor(DASHBOARD_COLORS["panel"])
    for spine in ax.spines.values():
        spine.set_visible(True)
        spine.set_color(DASHBOARD_COLORS["line"])
    ax.tick_params(left=False, bottom=False)


def _draw_empty_panel_text(ax, text: str) -> None:
    ax.text(
        0.5,
        0.5,
        text,
        transform=ax.transAxes,
        ha="center",
        va="center",
        fontsize=10,
        color=DASHBOARD_COLORS["muted"],
    )
    ax.set_xticks([])
    ax.set_yticks([])


def _usage_color(usage: float) -> str:
    if usage >= 100:
        return DASHBOARD_COLORS["red"]
    if usage >= 80:
        return DASHBOARD_COLORS["amber"]
    if usage >= 50:
        return DASHBOARD_COLORS["blue"]
    return DASHBOARD_COLORS["green"]


def _savings_color(amount: int) -> str:
    if amount < 0:
        return DASHBOARD_COLORS["red"]
    return DASHBOARD_COLORS["green"]


def _format_dashboard_money(amount: int, currency: str) -> str:
    if amount < 0:
        return f"-{format_money_minor(abs(amount), currency)}"
    return format_money_minor(amount, currency)


def _format_signed_dashboard_money(amount: int, currency: str) -> str:
    if amount < 0:
        return f"-{format_money_minor(abs(amount), currency)}"
    return f"+{format_money_minor(amount, currency)}"


def _rub(amount_minor: int) -> float:
    return amount_minor / 100


def _format_rub_value(value: float) -> str:
    if value.is_integer():
        return f"{int(value):,} ₽".replace(",", " ")
    return f"{value:,.2f} ₽".replace(",", " ").replace(".", ",")


def _wrap_category_label(value: str) -> str:
    return "\n".join(wrap(value, width=25, break_long_words=False, break_on_hyphens=False))


def _truncate_text(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 1].rstrip() + "…"


def _format_number_axis(
    ax,
    *,
    axis: str = "x",
    compact: bool = False,
    max_ticks: int | None = None,
) -> None:
    def formatter(value, _position):
        if compact:
            return _format_compact_number(value)
        return f"{int(value):,}".replace(",", " ")

    if axis == "x":
        if max_ticks is not None:
            ax.xaxis.set_major_locator(MaxNLocator(nbins=max_ticks))
        ax.xaxis.set_major_formatter(FuncFormatter(formatter))
    else:
        if max_ticks is not None:
            ax.yaxis.set_major_locator(MaxNLocator(nbins=max_ticks))
        ax.yaxis.set_major_formatter(FuncFormatter(formatter))


def _format_compact_number(value: float) -> str:
    absolute = abs(value)
    if absolute >= 1_000_000:
        return f"{value / 1_000_000:.1f} млн".replace(".", ",")
    if absolute >= 1_000:
        return f"{value / 1_000:.0f} тыс"
    return f"{int(value):,}".replace(",", " ")


def _local_now(now: datetime | None, timezone: str) -> datetime:
    tz = ZoneInfo(timezone)
    value = now or datetime.now(tz)
    return _to_local_datetime(value, tz)


def _to_local_datetime(value: datetime, timezone: ZoneInfo) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)


def _elapsed_period_days(period: Period, *, now: datetime | None, timezone: str) -> int:
    day_count = max((period.end_at.date() - period.start_at.date()).days, 1)
    local_now = _local_now(now, timezone)
    if local_now < period.start_at:
        return day_count
    if local_now >= period.end_at:
        return day_count
    return min(max((local_now.date() - period.start_at.date()).days + 1, 1), day_count)


def _report_amount(transaction) -> int:
    if transaction.type == "correction":
        return -transaction.amount
    return transaction.amount


def _cleanup_old_chart_files(temp_dir: Path) -> None:
    threshold = time() - CHART_MAX_AGE_SECONDS
    try:
        candidates = temp_dir.glob(f"{CHART_FILE_PREFIX}*.png")
    except OSError:
        return

    for path in candidates:
        try:
            if path.stat().st_mtime < threshold:
                path.unlink(missing_ok=True)
        except OSError:
            continue


def _previous_months(*, year: int, month: int, count: int) -> list[tuple[int, int]]:
    months = []
    current_year = year
    current_month = month
    for _ in range(count):
        months.append((current_year, current_month))
        current_month -= 1
        if current_month == 0:
            current_month = 12
            current_year -= 1
    return list(reversed(months))
