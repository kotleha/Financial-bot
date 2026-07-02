from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Any


class LimitRuleKind(StrEnum):
    MONTHLY_LIMIT = "monthly_limit"
    SEASONAL_LIMIT = "seasonal_limit"
    SAVINGS_TARGET = "savings_target"
    NO_LIMIT = "no_limit"


@dataclass(frozen=True, slots=True)
class MonthlyLimitRule:
    amount: int
    kind: LimitRuleKind = LimitRuleKind.MONTHLY_LIMIT


@dataclass(frozen=True, slots=True)
class SeasonalLimit:
    months: tuple[int, ...]
    amount: int


@dataclass(frozen=True, slots=True)
class SeasonalLimitRule:
    limits: tuple[SeasonalLimit, ...]
    kind: LimitRuleKind = LimitRuleKind.SEASONAL_LIMIT


@dataclass(frozen=True, slots=True)
class SavingsTargetRule:
    amount: int
    kind: LimitRuleKind = LimitRuleKind.SAVINGS_TARGET


@dataclass(frozen=True, slots=True)
class NoLimitRule:
    kind: LimitRuleKind = LimitRuleKind.NO_LIMIT


type LimitRule = MonthlyLimitRule | SeasonalLimitRule | SavingsTargetRule | NoLimitRule


@dataclass(frozen=True, slots=True)
class SpendingLimitConfig:
    schema_version: int
    currency: str
    thresholds: tuple[int, ...]
    categories: Mapping[str, LimitRule]


@dataclass(frozen=True, slots=True)
class ResolvedCategoryLimit:
    category_code: str
    kind: LimitRuleKind
    amount: int | None

    @property
    def has_spending_limit(self) -> bool:
        return self.kind in {LimitRuleKind.MONTHLY_LIMIT, LimitRuleKind.SEASONAL_LIMIT}

    @property
    def is_savings_target(self) -> bool:
        return self.kind == LimitRuleKind.SAVINGS_TARGET

    @property
    def has_no_limit(self) -> bool:
        return self.kind == LimitRuleKind.NO_LIMIT


def default_spending_limit_config() -> SpendingLimitConfig:
    return SpendingLimitConfig(
        schema_version=1,
        currency="RUB",
        thresholds=(50, 80, 100),
        categories=MappingProxyType(
            {
                "utilities": SeasonalLimitRule(
                    limits=(
                        SeasonalLimit(months=(4, 5, 6, 7, 8, 9), amount=800_000),
                        SeasonalLimit(months=(10, 11, 12, 1, 2, 3), amount=1_500_000),
                    )
                ),
                "groceries": MonthlyLimitRule(amount=7_000_000),
                "subscriptions_communications": MonthlyLimitRule(amount=2_500_000),
                "auto": MonthlyLimitRule(amount=1_500_000),
                "pets": MonthlyLimitRule(amount=1_100_000),
                "restaurants_cafes": MonthlyLimitRule(amount=4_000_000),
                "kids_education_sport": MonthlyLimitRule(amount=1_500_000),
                "cosmetology_medicine": MonthlyLimitRule(amount=1_000_000),
                "clothing_shoes": MonthlyLimitRule(amount=2_000_000),
                "fitness_sport": MonthlyLimitRule(amount=1_500_000),
                "hobbies": MonthlyLimitRule(amount=1_000_000),
                "home_land": MonthlyLimitRule(amount=2_000_000),
                "gifts_entertainment_holidays": MonthlyLimitRule(amount=1_500_000),
                "travel_vacation": MonthlyLimitRule(amount=7_000_000),
                "investments_savings": SavingsTargetRule(amount=3_000_000),
                "help_reserve": MonthlyLimitRule(amount=1_000_000),
                "taxes": NoLimitRule(),
                "stationery_supplies": NoLimitRule(),
            }
        ),
    )


def parse_spending_limit_config(value: Mapping[str, Any]) -> SpendingLimitConfig:
    schema_version = _parse_schema_version(value.get("schema_version"))
    currency = _parse_currency(value.get("currency"))
    thresholds = _parse_thresholds(value.get("thresholds"))
    categories = value.get("categories")
    if not isinstance(categories, Mapping) or not categories:
        msg = "spending_limits.categories must be a non-empty object"
        raise ValueError(msg)

    parsed_categories: dict[str, LimitRule] = {}
    for raw_code, raw_rule in categories.items():
        if not isinstance(raw_code, str) or not raw_code.strip():
            msg = "spending_limits category code must be a non-empty string"
            raise ValueError(msg)
        parsed_categories[raw_code] = _parse_rule(raw_rule)

    return SpendingLimitConfig(
        schema_version=schema_version,
        currency=currency,
        thresholds=thresholds,
        categories=MappingProxyType(parsed_categories),
    )


def spending_limit_config_to_dict(config: SpendingLimitConfig) -> dict[str, Any]:
    return {
        "schema_version": config.schema_version,
        "currency": config.currency,
        "thresholds": list(config.thresholds),
        "categories": {
            category_code: _rule_to_dict(rule) for category_code, rule in config.categories.items()
        },
    }


def resolve_category_limit(
    config: SpendingLimitConfig,
    *,
    category_code: str,
    month: int,
) -> ResolvedCategoryLimit:
    _validate_month(month)
    try:
        rule = config.categories[category_code]
    except KeyError as exc:
        msg = f"Spending limit rule is not configured for category: {category_code}"
        raise ValueError(msg) from exc

    return ResolvedCategoryLimit(
        category_code=category_code,
        kind=rule.kind,
        amount=resolve_rule_amount(rule, month=month),
    )


def resolve_rule_amount(rule: LimitRule, *, month: int) -> int | None:
    _validate_month(month)
    match rule:
        case MonthlyLimitRule(amount=amount):
            return amount
        case SavingsTargetRule(amount=amount):
            return amount
        case NoLimitRule():
            return None
        case SeasonalLimitRule(limits=limits):
            for limit in limits:
                if month in limit.months:
                    return limit.amount
            msg = f"Seasonal limit is not configured for month: {month}"
            raise ValueError(msg)


def usage_percent(amount: int, limit_amount: int) -> float:
    if amount < 0:
        msg = "amount must be non-negative"
        raise ValueError(msg)
    if limit_amount <= 0:
        msg = "limit_amount must be positive"
        raise ValueError(msg)
    return round(amount / limit_amount * 100, 1)


def crossed_thresholds(
    *,
    previous_amount: int,
    current_amount: int,
    limit_amount: int,
    thresholds: Sequence[int],
) -> tuple[int, ...]:
    if previous_amount < 0 or current_amount < 0:
        msg = "amounts must be non-negative"
        raise ValueError(msg)
    if current_amount < previous_amount:
        msg = "current_amount must be greater than or equal to previous_amount"
        raise ValueError(msg)
    if limit_amount <= 0:
        msg = "limit_amount must be positive"
        raise ValueError(msg)

    return tuple(
        threshold
        for threshold in thresholds
        if previous_amount * 100 < limit_amount * threshold
        and current_amount * 100 >= limit_amount * threshold
    )


def highest_crossed_threshold(
    *,
    previous_amount: int,
    current_amount: int,
    limit_amount: int,
    thresholds: Sequence[int],
) -> int | None:
    crossed = crossed_thresholds(
        previous_amount=previous_amount,
        current_amount=current_amount,
        limit_amount=limit_amount,
        thresholds=thresholds,
    )
    return max(crossed) if crossed else None


def _parse_schema_version(value: Any) -> int:
    if value != 1:
        msg = "spending_limits.schema_version must be 1"
        raise ValueError(msg)
    return 1


def _parse_currency(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        msg = "spending_limits.currency must be a non-empty string"
        raise ValueError(msg)
    return value.strip().upper()


def _parse_thresholds(value: Any) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        msg = "spending_limits.thresholds must be a non-empty array"
        raise ValueError(msg)

    thresholds = tuple(sorted(_parse_int(item, label="threshold") for item in value))
    if len(set(thresholds)) != len(thresholds):
        msg = "spending_limits.thresholds must not contain duplicates"
        raise ValueError(msg)
    if any(threshold <= 0 or threshold > 100 for threshold in thresholds):
        msg = "spending_limits.thresholds must be within 1..100"
        raise ValueError(msg)
    return thresholds


def _parse_rule(value: Any) -> LimitRule:
    if not isinstance(value, Mapping):
        msg = "spending_limits category rule must be an object"
        raise ValueError(msg)

    try:
        kind = LimitRuleKind(str(value.get("kind")))
    except ValueError as exc:
        msg = f"Unknown spending limit rule kind: {value.get('kind')}"
        raise ValueError(msg) from exc

    match kind:
        case LimitRuleKind.MONTHLY_LIMIT:
            return MonthlyLimitRule(amount=_parse_positive_amount(value.get("amount")))
        case LimitRuleKind.SEASONAL_LIMIT:
            return SeasonalLimitRule(limits=_parse_seasonal_limits(value.get("limits")))
        case LimitRuleKind.SAVINGS_TARGET:
            return SavingsTargetRule(amount=_parse_positive_amount(value.get("amount")))
        case LimitRuleKind.NO_LIMIT:
            return NoLimitRule()


def _parse_seasonal_limits(value: Any) -> tuple[SeasonalLimit, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        msg = "seasonal_limit.limits must be a non-empty array"
        raise ValueError(msg)

    parsed: list[SeasonalLimit] = []
    used_months: set[int] = set()
    for raw_limit in value:
        if not isinstance(raw_limit, Mapping):
            msg = "seasonal_limit item must be an object"
            raise ValueError(msg)
        months = _parse_months(raw_limit.get("months"))
        duplicate_months = used_months.intersection(months)
        if duplicate_months:
            msg = f"seasonal_limit contains duplicate months: {sorted(duplicate_months)}"
            raise ValueError(msg)
        used_months.update(months)
        parsed.append(
            SeasonalLimit(
                months=months,
                amount=_parse_positive_amount(raw_limit.get("amount")),
            )
        )

    return tuple(parsed)


def _parse_months(value: Any) -> tuple[int, ...]:
    if not isinstance(value, Sequence) or isinstance(value, str) or not value:
        msg = "seasonal_limit.months must be a non-empty array"
        raise ValueError(msg)

    months = tuple(_parse_int(item, label="month") for item in value)
    for month in months:
        _validate_month(month)
    if len(set(months)) != len(months):
        msg = "seasonal_limit.months must not contain duplicates"
        raise ValueError(msg)
    return months


def _parse_positive_amount(value: Any) -> int:
    amount = _parse_int(value, label="amount")
    if amount <= 0:
        msg = "amount must be positive"
        raise ValueError(msg)
    return amount


def _parse_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        msg = f"{label} must be an integer"
        raise ValueError(msg)
    return value


def _validate_month(month: int) -> None:
    if month < 1 or month > 12:
        msg = f"month must be within 1..12: {month}"
        raise ValueError(msg)


def _rule_to_dict(rule: LimitRule) -> dict[str, Any]:
    match rule:
        case MonthlyLimitRule(amount=amount):
            return {"kind": rule.kind.value, "amount": amount}
        case SavingsTargetRule(amount=amount):
            return {"kind": rule.kind.value, "amount": amount}
        case NoLimitRule():
            return {"kind": rule.kind.value}
        case SeasonalLimitRule(limits=limits):
            return {
                "kind": rule.kind.value,
                "limits": [
                    {"months": list(limit.months), "amount": limit.amount} for limit in limits
                ],
            }
