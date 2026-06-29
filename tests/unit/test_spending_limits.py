import pytest
from financial_bot.app.domain.spending_limits import (
    LimitRuleKind,
    crossed_thresholds,
    default_spending_limit_config,
    highest_crossed_threshold,
    parse_spending_limit_config,
    resolve_category_limit,
    spending_limit_config_to_dict,
    usage_percent,
)


def test_default_config_resolves_monthly_and_seasonal_limits() -> None:
    config = default_spending_limit_config()

    assert resolve_category_limit(config, category_code="utilities", month=4).amount == 800_000
    assert resolve_category_limit(config, category_code="utilities", month=9).amount == 800_000
    assert resolve_category_limit(config, category_code="utilities", month=10).amount == 1_500_000
    assert resolve_category_limit(config, category_code="utilities", month=3).amount == 1_500_000
    assert resolve_category_limit(config, category_code="groceries", month=6).amount == 7_000_000


def test_default_config_resolves_target_and_no_limit_categories() -> None:
    config = default_spending_limit_config()

    investments = resolve_category_limit(
        config,
        category_code="investments_savings",
        month=6,
    )
    taxes = resolve_category_limit(config, category_code="taxes", month=6)

    assert investments.kind == LimitRuleKind.SAVINGS_TARGET
    assert investments.amount == 3_000_000
    assert investments.is_savings_target
    assert taxes.kind == LimitRuleKind.NO_LIMIT
    assert taxes.amount is None
    assert taxes.has_no_limit


def test_config_round_trip_through_json_shape() -> None:
    config = default_spending_limit_config()
    parsed = parse_spending_limit_config(spending_limit_config_to_dict(config))

    assert parsed.schema_version == 1
    assert parsed.currency == "RUB"
    assert parsed.thresholds == (50, 80, 100)
    assert resolve_category_limit(parsed, category_code="auto", month=6).amount == 1_500_000
    assert resolve_category_limit(parsed, category_code="taxes", month=6).has_no_limit


@pytest.mark.parametrize(
    "raw_config",
    [
        {},
        {"schema_version": 2, "currency": "RUB", "thresholds": [50], "categories": {}},
        {"schema_version": 1, "currency": "", "thresholds": [50], "categories": {}},
        {"schema_version": 1, "currency": "RUB", "thresholds": [0], "categories": {}},
        {
            "schema_version": 1,
            "currency": "RUB",
            "thresholds": [50],
            "categories": {"groceries": {"kind": "monthly_limit", "amount": -1}},
        },
        {
            "schema_version": 1,
            "currency": "RUB",
            "thresholds": [50],
            "categories": {"groceries": {"kind": "unknown", "amount": 1}},
        },
        {
            "schema_version": 1,
            "currency": "RUB",
            "thresholds": [50],
            "categories": {
                "utilities": {
                    "kind": "seasonal_limit",
                    "limits": [
                        {"months": [1, 2], "amount": 100},
                        {"months": [2, 3], "amount": 200},
                    ],
                }
            },
        },
        {
            "schema_version": 1,
            "currency": "RUB",
            "thresholds": [50],
            "categories": {
                "utilities": {
                    "kind": "seasonal_limit",
                    "limits": [{"months": [13], "amount": 100}],
                }
            },
        },
    ],
)
def test_parse_config_rejects_invalid_shapes(raw_config: dict) -> None:
    with pytest.raises(ValueError):
        parse_spending_limit_config(raw_config)


def test_resolve_category_limit_rejects_unknown_category_and_invalid_month() -> None:
    config = default_spending_limit_config()

    with pytest.raises(ValueError, match="not configured"):
        resolve_category_limit(config, category_code="unknown", month=6)

    with pytest.raises(ValueError, match="month"):
        resolve_category_limit(config, category_code="groceries", month=13)


def test_usage_percent() -> None:
    assert usage_percent(3_500_000, 7_000_000) == 50.0
    assert usage_percent(5_950_000, 7_000_000) == 85.0


def test_crossed_thresholds() -> None:
    assert crossed_thresholds(
        previous_amount=3_400_000,
        current_amount=3_500_000,
        limit_amount=7_000_000,
        thresholds=(50, 80, 100),
    ) == (50,)
    assert crossed_thresholds(
        previous_amount=3_400_000,
        current_amount=5_700_000,
        limit_amount=7_000_000,
        thresholds=(50, 80, 100),
    ) == (50, 80)
    assert (
        crossed_thresholds(
            previous_amount=7_000_000,
            current_amount=7_500_000,
            limit_amount=7_000_000,
            thresholds=(50, 80, 100),
        )
        == ()
    )


def test_highest_crossed_threshold() -> None:
    assert (
        highest_crossed_threshold(
            previous_amount=3_400_000,
            current_amount=7_500_000,
            limit_amount=7_000_000,
            thresholds=(50, 80, 100),
        )
        == 100
    )
    assert (
        highest_crossed_threshold(
            previous_amount=7_000_000,
            current_amount=7_500_000,
            limit_amount=7_000_000,
            thresholds=(50, 80, 100),
        )
        is None
    )
