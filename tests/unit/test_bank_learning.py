from datetime import UTC, datetime

from financial_bot.app.bot.formatters.bank_learning import (
    format_bank_learning_rule_category_updated,
    format_bank_learning_rule_details,
    format_bank_learning_rule_status_updated,
    format_bank_learning_rules_list,
)
from financial_bot.app.domain.bank_learning import normalize_bank_merchant_key
from financial_bot.app.services.bank_learning_rule_service import (
    BankLearningRuleDetails,
    BankLearningRuleLine,
    BankLearningRuleStatusResult,
    BankLearningRuleUpdateResult,
)


def test_normalize_bank_merchant_key() -> None:
    assert normalize_bank_merchant_key("  BAHETLE_P_QR  ") == "bahetle p qr"
    assert normalize_bank_merchant_key("SBERCHAEVYE") == "sberchaevye"
    assert normalize_bank_merchant_key("Аптека № 7") == "аптека 7"
    assert normalize_bank_merchant_key("qr") == ""
    assert normalize_bank_merchant_key("   ") == ""


def test_bank_learning_rules_list_explains_management_path() -> None:
    text = format_bank_learning_rules_list(
        (
            BankLearningRuleLine(
                id=1,
                bank="sber",
                merchant_display="BAHETLE_P_QR",
                category_title="Продукты",
                hit_count=2,
                is_active=True,
                last_confirmed_at=None,
            ),
        )
    )

    assert "Выученные правила категорий" in text
    assert "Активные: 1" in text
    assert "Правило можно отключить или изменить в «🧠 Правила категорий»." in text


def test_bank_learning_rule_details_explain_scope_and_autosave() -> None:
    text = format_bank_learning_rule_details(
        BankLearningRuleDetails(
            id=1,
            bank="sber",
            merchant_display="BAHETLE_P_QR",
            merchant_key="bahetle p qr",
            category_id=2,
            category_title="Продукты",
            hit_count=2,
            is_active=True,
            created_at=datetime(2026, 6, 1, tzinfo=UTC),
            updated_at=datetime(2026, 6, 2, tzinfo=UTC),
            last_confirmed_at=datetime(2026, 6, 2, 10, tzinfo=UTC),
            last_used_at=None,
        )
    )

    assert "Активное правило может записывать похожие расходы автоматически." in text
    assert "Правило работает только для похожего продавца в этом банке." in text


def test_bank_learning_rule_updates_keep_management_hint() -> None:
    category_text = format_bank_learning_rule_category_updated(
        BankLearningRuleUpdateResult(
            rule_id=1,
            bank="sber",
            merchant_display="BAHETLE_P_QR",
            old_category_title="Продукты",
            new_category_title="Рестораны/Кафе",
            is_active=True,
        )
    )
    status_text = format_bank_learning_rule_status_updated(
        BankLearningRuleStatusResult(
            rule_id=1,
            bank="sber",
            merchant_display="BAHETLE_P_QR",
            category_title="Продукты",
            is_active=False,
        )
    )

    assert "Правило включено и будет использоваться для следующих похожих SMS." in category_text
    assert "Правило можно отключить или изменить в «🧠 Правила категорий»." in category_text
    assert "Бот больше не будет автоматически применять это правило." in status_text
