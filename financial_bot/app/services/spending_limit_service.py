from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import Period, PeriodKind, resolve_period
from financial_bot.app.domain.spending_limits import (
    LimitRuleKind,
    SpendingLimitConfig,
    default_spending_limit_config,
    parse_spending_limit_config,
    resolve_category_limit,
    spending_limit_config_to_dict,
    usage_percent,
)
from financial_bot.app.domain.types import TransactionType
from financial_bot.app.storage.models import SpendingLimitAlertModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.report_repository import ReportRepository
from financial_bot.app.storage.repositories.setting_repository import SettingRepository
from financial_bot.app.storage.repositories.spending_limit_alert_repository import (
    SpendingLimitAlertRepository,
)
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository

SPENDING_LIMITS_SETTINGS_KEY = "spending_limits"


@dataclass(frozen=True, slots=True)
class BudgetLimitLine:
    code: str
    title: str
    sort_order: int
    spent_amount: int
    limit_amount: int
    usage_percent: float
    remaining_amount: int

    @property
    def overrun_amount(self) -> int:
        return max(-self.remaining_amount, 0)


@dataclass(frozen=True, slots=True)
class BudgetNoLimitLine:
    code: str
    title: str
    sort_order: int
    spent_amount: int


@dataclass(frozen=True, slots=True)
class BudgetSavingsTargetLine:
    code: str
    title: str
    sort_order: int
    actual_amount: int
    target_amount: int
    delta_amount: int
    usage_percent: float


@dataclass(frozen=True, slots=True)
class BudgetReport:
    period: Period
    currency: str
    limit_lines: tuple[BudgetLimitLine, ...]
    no_limit_lines: tuple[BudgetNoLimitLine, ...]
    savings_target_lines: tuple[BudgetSavingsTargetLine, ...]
    under_budget_pool: int
    overrun_total: int
    net_savings: int


@dataclass(frozen=True, slots=True)
class LimitOverviewLine:
    code: str
    title: str
    sort_order: int
    kind: LimitRuleKind
    amount: int | None


@dataclass(frozen=True, slots=True)
class LimitOverview:
    period: Period
    currency: str
    lines: tuple[LimitOverviewLine, ...]


@dataclass(frozen=True, slots=True)
class SpendingLimitThresholdAlert:
    category_code: str
    category_title: str
    threshold_percent: int
    spent_amount: int
    limit_amount: int
    usage_percent: float
    remaining_amount: int

    @property
    def overrun_amount(self) -> int:
        return max(-self.remaining_amount, 0)


class SpendingLimitService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._alerts = SpendingLimitAlertRepository(session)
        self._categories = CategoryRepository(session)
        self._reports = ReportRepository(session)
        self._settings_repository = SettingRepository(session)
        self._transactions = TransactionRepository(session)
        self._users = UserRepository(session)

    async def get_config(self) -> SpendingLimitConfig:
        stored = await self._settings_repository.get_value(SPENDING_LIMITS_SETTINGS_KEY)
        if stored is None:
            return default_spending_limit_config()
        return _with_default_missing_rules(parse_spending_limit_config(stored))

    async def set_config(self, config: SpendingLimitConfig) -> None:
        if config.currency != self._settings.default_currency:
            msg = (
                "Spending limit config currency must match default currency: "
                f"{self._settings.default_currency}"
            )
            raise ValueError(msg)
        await self._settings_repository.set_value(
            SPENDING_LIMITS_SETTINGS_KEY,
            spending_limit_config_to_dict(config),
        )

    async def ensure_default_config(self) -> bool:
        stored = await self._settings_repository.get_value(SPENDING_LIMITS_SETTINGS_KEY)
        if stored is not None:
            parse_spending_limit_config(stored)
            return False

        await self.set_config(default_spending_limit_config())
        return True

    async def set_monthly_limit(self, *, category_code: str, amount: int) -> SpendingLimitConfig:
        return await self._replace_category_rule(
            category_code=category_code,
            rule={"kind": LimitRuleKind.MONTHLY_LIMIT.value, "amount": amount},
        )

    async def set_no_limit(self, *, category_code: str) -> SpendingLimitConfig:
        return await self._replace_category_rule(
            category_code=category_code,
            rule={"kind": LimitRuleKind.NO_LIMIT.value},
        )

    async def set_savings_target(self, *, category_code: str, amount: int) -> SpendingLimitConfig:
        return await self._replace_category_rule(
            category_code=category_code,
            rule={"kind": LimitRuleKind.SAVINGS_TARGET.value, "amount": amount},
        )

    async def set_utilities_seasonal_limits(
        self,
        *,
        summer_amount: int,
        winter_amount: int,
    ) -> SpendingLimitConfig:
        return await self.set_seasonal_limits(
            category_code="utilities",
            summer_amount=summer_amount,
            winter_amount=winter_amount,
        )

    async def set_seasonal_limits(
        self,
        *,
        category_code: str,
        summer_amount: int,
        winter_amount: int,
    ) -> SpendingLimitConfig:
        return await self._replace_category_rule(
            category_code=category_code,
            rule={
                "kind": LimitRuleKind.SEASONAL_LIMIT.value,
                "limits": [
                    {"months": [4, 5, 6, 7, 8, 9], "amount": summer_amount},
                    {"months": [10, 11, 12, 1, 2, 3], "amount": winter_amount},
                ],
            },
        )

    async def build_monthly_report(self, *, now: datetime | None = None) -> BudgetReport:
        period = resolve_period(PeriodKind.MONTH, now=now, timezone=self._settings.timezone)
        config = await self.get_config()
        category_totals = {
            row.code: row.amount
            for row in await self._reports.totals_by_category(period.start_at, period.end_at)
        }
        active_categories = [
            category
            for category in await self._categories.list_active()
            if category.is_expense and category.code in config.categories
        ]

        limit_lines: list[BudgetLimitLine] = []
        no_limit_lines: list[BudgetNoLimitLine] = []
        savings_target_lines: list[BudgetSavingsTargetLine] = []
        under_budget_pool = 0
        overrun_total = 0

        for category in active_categories:
            spent_amount = category_totals.get(category.code, 0)
            resolved = resolve_category_limit(
                config,
                category_code=category.code,
                month=period.start_at.month,
            )
            if resolved.kind in {LimitRuleKind.MONTHLY_LIMIT, LimitRuleKind.SEASONAL_LIMIT}:
                if resolved.amount is None:
                    msg = f"Spending limit amount is missing for category: {category.code}"
                    raise ValueError(msg)
                remaining_amount = resolved.amount - spent_amount
                line = BudgetLimitLine(
                    code=category.code,
                    title=category.title,
                    sort_order=category.sort_order,
                    spent_amount=spent_amount,
                    limit_amount=resolved.amount,
                    usage_percent=usage_percent(spent_amount, resolved.amount),
                    remaining_amount=remaining_amount,
                )
                limit_lines.append(line)
                under_budget_pool += max(remaining_amount, 0)
                overrun_total += line.overrun_amount
            elif resolved.kind == LimitRuleKind.SAVINGS_TARGET:
                if resolved.amount is None:
                    msg = f"Savings target amount is missing for category: {category.code}"
                    raise ValueError(msg)
                savings_target_lines.append(
                    BudgetSavingsTargetLine(
                        code=category.code,
                        title=category.title,
                        sort_order=category.sort_order,
                        actual_amount=spent_amount,
                        target_amount=resolved.amount,
                        delta_amount=spent_amount - resolved.amount,
                        usage_percent=usage_percent(spent_amount, resolved.amount),
                    )
                )
            elif resolved.kind == LimitRuleKind.NO_LIMIT and spent_amount > 0:
                no_limit_lines.append(
                    BudgetNoLimitLine(
                        code=category.code,
                        title=category.title,
                        sort_order=category.sort_order,
                        spent_amount=spent_amount,
                    )
                )

        return BudgetReport(
            period=period,
            currency=config.currency,
            limit_lines=tuple(limit_lines),
            no_limit_lines=tuple(no_limit_lines),
            savings_target_lines=tuple(savings_target_lines),
            under_budget_pool=under_budget_pool,
            overrun_total=overrun_total,
            net_savings=under_budget_pool - overrun_total,
        )

    async def build_limits_overview(self, *, now: datetime | None = None) -> LimitOverview:
        period = resolve_period(PeriodKind.MONTH, now=now, timezone=self._settings.timezone)
        config = await self.get_config()
        active_categories = [
            category
            for category in await self._categories.list_active()
            if category.is_expense and category.code in config.categories
        ]
        lines = []
        for category in active_categories:
            resolved = resolve_category_limit(
                config,
                category_code=category.code,
                month=period.start_at.month,
            )
            lines.append(
                LimitOverviewLine(
                    code=category.code,
                    title=category.title,
                    sort_order=category.sort_order,
                    kind=resolved.kind,
                    amount=resolved.amount,
                )
            )

        return LimitOverview(
            period=period,
            currency=config.currency,
            lines=tuple(lines),
        )

    async def evaluate_transaction_threshold_alerts(
        self,
        *,
        transaction_id: int,
        recipient_telegram_id: int,
    ) -> tuple[SpendingLimitThresholdAlert, ...]:
        transaction = await self._transactions.get(transaction_id)
        if (
            transaction is None
            or transaction.deleted_at is not None
            or transaction.type != TransactionType.EXPENSE.value
            or not transaction.included_in_reports
        ):
            return ()

        category = await self._categories.get(transaction.category_id)
        recipient = await self._users.get_by_telegram_id(recipient_telegram_id)
        if (
            category is None
            or recipient is None
            or not category.is_active
            or not category.is_expense
        ):
            return ()

        config = await self.get_config()
        if category.code not in config.categories:
            return ()

        period = resolve_period(
            PeriodKind.MONTH,
            now=transaction.occurred_at,
            timezone=self._settings.timezone,
        )
        resolved = resolve_category_limit(
            config,
            category_code=category.code,
            month=period.start_at.month,
        )
        if not resolved.has_spending_limit or resolved.amount is None:
            return ()

        category_totals = {
            row.code: row.amount
            for row in await self._reports.totals_by_category(period.start_at, period.end_at)
        }
        spent_amount = category_totals.get(category.code, 0)
        sent_thresholds = await self._alerts.list_sent_thresholds(
            period_start=period.start_at,
            category_id=category.id,
            sent_to_user_id=recipient.id,
        )
        reached_thresholds = tuple(
            threshold
            for threshold in config.thresholds
            if threshold not in sent_thresholds
            and spent_amount * 100 >= resolved.amount * threshold
        )
        if not reached_thresholds:
            return ()

        for threshold in reached_thresholds:
            await self._alerts.add(
                SpendingLimitAlertModel(
                    period_start=period.start_at,
                    category_id=category.id,
                    threshold_percent=threshold,
                    transaction_id=transaction.id,
                    sent_to_user_id=recipient.id,
                )
            )

        remaining_amount = resolved.amount - spent_amount
        return (
            SpendingLimitThresholdAlert(
                category_code=category.code,
                category_title=category.title,
                threshold_percent=max(reached_thresholds),
                spent_amount=spent_amount,
                limit_amount=resolved.amount,
                usage_percent=usage_percent(spent_amount, resolved.amount),
                remaining_amount=remaining_amount,
            ),
        )

    async def _replace_category_rule(
        self,
        *,
        category_code: str,
        rule: dict,
    ) -> SpendingLimitConfig:
        config = await self.get_config()
        config_dict = spending_limit_config_to_dict(config)
        categories = config_dict["categories"]
        if category_code not in categories:
            msg = f"Spending limit rule is not configured for category: {category_code}"
            raise ValueError(msg)
        categories[category_code] = rule
        updated_config = parse_spending_limit_config(config_dict)
        await self.set_config(updated_config)
        return updated_config


def _with_default_missing_rules(config: SpendingLimitConfig) -> SpendingLimitConfig:
    default_config = default_spending_limit_config()
    missing = {
        category_code: rule
        for category_code, rule in default_config.categories.items()
        if category_code not in config.categories
    }
    if not missing:
        return config

    return SpendingLimitConfig(
        schema_version=config.schema_version,
        currency=config.currency,
        thresholds=config.thresholds,
        categories=MappingProxyType({**missing, **config.categories}),
    )
