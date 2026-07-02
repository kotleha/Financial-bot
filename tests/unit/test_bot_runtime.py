import asyncio
from datetime import datetime

import pytest

pytest.importorskip("aiogram")

from aiogram import Dispatcher
from financial_bot.app.bot.keyboards.auto_accounting_menu import (
    AUTO_ACCOUNTING_MENU_ROWS,
    build_auto_accounting_menu,
)
from financial_bot.app.bot.keyboards.bank_events import (
    BankEventAction,
    BankEventActionCallback,
    BankEventCategoryCallback,
    build_bank_autosaved_actions_keyboard,
    build_bank_event_actions_keyboard,
    build_bank_event_category_keyboard,
    build_bank_income_actions_keyboard,
    build_bank_refund_actions_keyboard,
)
from financial_bot.app.bot.keyboards.bank_learning import (
    BankLearningAction,
    BankLearningActionCallback,
    BankLearningCategoryCallback,
    BankLearningRuleCallback,
    build_bank_learning_category_keyboard,
    build_bank_learning_rule_actions_keyboard,
    build_bank_learning_rules_keyboard,
)
from financial_bot.app.bot.keyboards.budget_menu import BUDGET_MENU_ROWS, build_budget_menu
from financial_bot.app.bot.keyboards.categories import (
    CATEGORY_CANCEL_CALLBACK,
    build_category_keyboard,
    parse_category_callback_data,
)
from financial_bot.app.bot.keyboards.category_settings import (
    CategorySettingsAction,
    CategorySettingsActionCallback,
    CategorySettingsCategoryCallback,
    CategorySettingsConfirmAction,
    CategorySettingsConfirmCallback,
    build_category_settings_action_keyboard,
    build_category_settings_confirm_keyboard,
    build_category_settings_keyboard,
)
from financial_bot.app.bot.keyboards.main_menu import MAIN_MENU_ROWS, build_main_menu
from financial_bot.app.bot.keyboards.reports_menu import REPORTS_MENU_ROWS, build_reports_menu
from financial_bot.app.bot.keyboards.settings_menu import SETTINGS_MENU_ROWS, build_settings_menu
from financial_bot.app.bot.keyboards.spending_limits import (
    LimitActionCallback,
    LimitCategoryCallback,
    LimitConfirmCallback,
    LimitWizardAction,
    LimitWizardConfirmAction,
    build_limit_action_keyboard,
    build_limit_category_keyboard,
    build_limit_confirm_keyboard,
)
from financial_bot.app.bot.main import create_bot, create_dispatcher
from financial_bot.app.bot.routers.auto_accounting_health import (
    AUTO_ACCOUNTING_HEALTH_ALIASES,
    AUTO_ACCOUNTING_RETRY_ALIASES,
)
from financial_bot.app.bot.routers.bank_events import _command_payload, _is_pending_command_payload
from financial_bot.app.bot.routers.bank_learning import BANK_LEARNING_RULES_ALIASES
from financial_bot.app.bot.routers.cashflow import CASHFLOW_ALIASES, _cashflow_kind_from_text_alias
from financial_bot.app.bot.routers.category_settings import CATEGORY_SETTINGS_ALIASES
from financial_bot.app.bot.routers.charts import (
    CATEGORY_CHART_MENU_ALIASES,
    COMPARE_MENU_ALIASES,
    DASHBOARD_MENU_ALIASES,
    TREND_MENU_ALIASES,
    _category_chart_period_from_menu_text,
    _category_chart_period_from_tokens,
    _default_compare_month_tokens,
    _empty_chart_message,
)
from financial_bot.app.bot.routers.expense_entry import _is_add_expense_menu_text
from financial_bot.app.bot.routers.income_entry import (
    _income_payload_from_text,
    _is_add_income_menu_text,
    _looks_like_bank_notification,
    _manual_income_raw_text,
)
from financial_bot.app.bot.routers.reports import (
    MONTH_REPORT_ALIASES,
    PAYER_REPORT_ALIASES,
    PERIOD_REPORT_ALIASES,
    _period_kind_from_text_alias,
)
from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import PeriodKind
from financial_bot.app.domain.spending_limits import LimitRuleKind
from financial_bot.app.domain.types import BankCategoryRuleMode
from financial_bot.app.services.bank_learning_rule_service import BankLearningRuleLine
from financial_bot.app.services.category_settings_service import CategorySettingsLine
from financial_bot.app.services.spending_limit_service import LimitOverviewLine
from financial_bot.app.services.transaction_service import CategoryOption


def make_settings() -> Settings:
    return Settings(
        _env_file=None,
        bot_token="123456:secret-token",
        database_url="sqlite+aiosqlite:///unused.sqlite3",
        allowed_telegram_ids="1001,1002",
        default_currency="RUB",
        timezone="Asia/Barnaul",
        husband_telegram_id=1001,
        wife_telegram_id=1002,
    )


def test_create_bot_uses_telegram_route_proxy() -> None:
    bot = create_bot(
        Settings(
            _env_file=None,
            bot_token="123456:secret-token",
            database_url="sqlite+aiosqlite:///unused.sqlite3",
            allowed_telegram_ids="1001,1002",
            default_currency="RUB",
            timezone="Asia/Barnaul",
            husband_telegram_id=1001,
            wife_telegram_id=1002,
            telegram_route_url="http://10.255.78.2:18080",
        )
    )
    try:
        assert bot.session.proxy == "http://10.255.78.2:18080"
    finally:
        asyncio.run(bot.session.close())


def test_main_menu_contains_expected_buttons() -> None:
    keyboard = build_main_menu()
    button_texts = [[button.text for button in row] for row in keyboard.keyboard]

    assert button_texts == [list(row) for row in MAIN_MENU_ROWS]
    assert button_texts == [
        ["➕ Расход", "➕ Доход"],
        ["🏦 Автоучёт", "📊 Отчёты"],
        ["💰 Бюджет", "⚙️ Настройки"],
    ]
    assert sum(button.text == "➕ Доход" for row in keyboard.keyboard for button in row) == 1


def test_reports_menu_contains_expected_buttons() -> None:
    keyboard = build_reports_menu()
    button_texts = [[button.text for button in row] for row in keyboard.keyboard]

    assert button_texts == [list(row) for row in REPORTS_MENU_ROWS]
    assert button_texts[0] == ["🧾 Итог месяца", "📊 Месяц"]
    assert button_texts[1] == ["📊 Неделя", "📊 Квартал"]
    assert ["📈 Категории", "👥 Кто платил"] in button_texts
    assert ["💸 Денежный поток", "📉 Динамика месяца"] in button_texts
    assert ["📆 Сравнить", "📈 Тренд"] in button_texts
    assert button_texts[-1] == ["↩️ Главное меню"]


def test_secondary_menus_contain_expected_buttons() -> None:
    assert [[button.text for button in row] for row in build_budget_menu().keyboard] == [
        list(row) for row in BUDGET_MENU_ROWS
    ]
    assert [[button.text for button in row] for row in build_auto_accounting_menu().keyboard] == [
        list(row) for row in AUTO_ACCOUNTING_MENU_ROWS
    ]
    assert [[button.text for button in row] for row in build_settings_menu().keyboard] == [
        list(row) for row in SETTINGS_MENU_ROWS
    ]
    auto_accounting_buttons = [
        [button.text for button in row] for row in build_auto_accounting_menu().keyboard
    ]
    assert ["🩺 Состояние автоучёта"] in auto_accounting_buttons
    assert ["🔎 Проверить источники"] in auto_accounting_buttons
    assert ["🔁 Повторить отправку ожидающих"] in auto_accounting_buttons
    assert ["🧠 Правила категорий"] in auto_accounting_buttons


def test_income_button_is_only_in_main_menu() -> None:
    keyboards = (
        build_budget_menu(),
        build_auto_accounting_menu(),
        build_settings_menu(),
    )

    for keyboard in keyboards:
        for row in keyboard.keyboard:
            for button in row:
                normalized = button.text.lower()
                assert "➕ доход" not in normalized


def test_category_chart_period_aliases() -> None:
    assert CATEGORY_CHART_MENU_ALIASES["категории"] == PeriodKind.MONTH
    assert _category_chart_period_from_menu_text("📈 Категории") == PeriodKind.MONTH
    assert _category_chart_period_from_menu_text("категории") == PeriodKind.MONTH
    assert _category_chart_period_from_menu_text("📊 Категории: неделя") == PeriodKind.WEEK
    assert _category_chart_period_from_menu_text("📊 Категории: квартал") == PeriodKind.QUARTER
    assert _category_chart_period_from_tokens(["categories", "year"]) == PeriodKind.YEAR
    assert _category_chart_period_from_tokens(["полгода"]) == PeriodKind.HALFYEAR
    assert _category_chart_period_from_tokens([]) == PeriodKind.MONTH
    assert _category_chart_period_from_tokens(["unknown"]) is None


def test_dashboard_menu_aliases() -> None:
    assert "📊 дашборд" in DASHBOARD_MENU_ALIASES
    assert "📊 дашборд месяца" in DASHBOARD_MENU_ALIASES
    assert "dashboard" in DASHBOARD_MENU_ALIASES
    assert "статус" in DASHBOARD_MENU_ALIASES


def test_compare_and_trend_menu_aliases() -> None:
    settings = make_settings()

    assert "📆 сравнить" in COMPARE_MENU_ALIASES
    assert "📈 тренд" in TREND_MENU_ALIASES
    assert _default_compare_month_tokens(settings, now=datetime(2026, 6, 29, 12)) == ["5", "6"]


def test_period_report_aliases() -> None:
    assert "итог месяца" in MONTH_REPORT_ALIASES
    assert "🧾 итог месяца" in MONTH_REPORT_ALIASES
    assert "📄 месяц" in MONTH_REPORT_ALIASES
    assert "📄 отчёт: месяц" in MONTH_REPORT_ALIASES
    assert PERIOD_REPORT_ALIASES["📄 неделя"] == PeriodKind.WEEK
    assert PERIOD_REPORT_ALIASES["📄 отчёт: неделя"] == PeriodKind.WEEK
    assert PERIOD_REPORT_ALIASES["📄 квартал"] == PeriodKind.QUARTER
    assert PERIOD_REPORT_ALIASES["📄 отчёт: квартал"] == PeriodKind.QUARTER
    assert PERIOD_REPORT_ALIASES["📄 год"] == PeriodKind.YEAR
    assert PERIOD_REPORT_ALIASES["📄 отчёт: год"] == PeriodKind.YEAR
    assert _period_kind_from_text_alias("полгода") == PeriodKind.HALFYEAR


def test_payer_report_aliases_do_not_include_legacy_category_owner_words() -> None:
    assert "кто платил" in PAYER_REPORT_ALIASES
    assert "плательщики" in PAYER_REPORT_ALIASES
    assert "категории" not in PAYER_REPORT_ALIASES
    assert "закреплённые" not in PAYER_REPORT_ALIASES
    assert "чьи категории" not in PAYER_REPORT_ALIASES


def test_cashflow_aliases() -> None:
    assert "💸 денежный поток" in CASHFLOW_ALIASES
    assert _cashflow_kind_from_text_alias("💸 Денежный поток") == PeriodKind.MONTH
    assert _cashflow_kind_from_text_alias("денежный поток неделя") == PeriodKind.WEEK
    assert _cashflow_kind_from_text_alias("cashflow year") == PeriodKind.YEAR
    assert _cashflow_kind_from_text_alias("доход") is None


def test_income_entry_aliases() -> None:
    assert _is_add_income_menu_text("➕ Доход")
    assert _is_add_income_menu_text("доход")
    assert _income_payload_from_text("доход 100000 зарплата") == "100000 зарплата"
    assert _income_payload_from_text("+15000 проект") == "+15000 проект"
    assert _income_payload_from_text("поступление 25000 аванс") is None
    assert _income_payload_from_text("денежный поток") is None
    assert _manual_income_raw_text("income_salary") == "manual_income:income_salary"


def test_income_entry_detects_bank_notifications() -> None:
    assert _looks_like_bank_notification("100р Счет*0155 Баланс 999р")
    assert _looks_like_bank_notification("СЧЁТ1111 05:37 Зачисление 1471.20р Баланс: 999р")
    assert _looks_like_bank_notification("Карта*1111 Покупка 290р APTEKA Баланс 999р")
    assert not _looks_like_bank_notification("100000 зарплата")


def test_chart_empty_messages_are_contextual() -> None:
    assert (
        _empty_chart_message("cashflow") == "За период нет доходов и расходов для денежного потока."
    )
    assert _empty_chart_message("categories") == "За период нет расходов для графика."


def test_add_expense_menu_text_accepts_current_and_old_button() -> None:
    assert _is_add_expense_menu_text("➕ Добавить расход")
    assert _is_add_expense_menu_text("➕ Расход")
    assert _is_add_expense_menu_text("добавить расход")


def test_category_keyboard_does_not_show_owner_labels() -> None:
    keyboard = build_category_keyboard(
        [
            CategoryOption(
                id=2,
                code="groceries",
                title="Продукты",
                sort_order=2,
                owner_role="system",
                is_expense=True,
            )
        ],
        draft_token="draft-token",
    )

    button_text = keyboard.inline_keyboard[0][0].text
    assert button_text == "2. Продукты"
    assert "жена" not in button_text.lower()
    assert "муж" not in button_text.lower()
    assert parse_category_callback_data(keyboard.inline_keyboard[0][0].callback_data) == (
        "draft-token",
        2,
    )
    assert keyboard.inline_keyboard[1][0].text == "↩️ Отменить ввод"
    assert keyboard.inline_keyboard[1][0].callback_data == CATEGORY_CANCEL_CALLBACK


def test_category_callback_parser_rejects_old_buttons_without_draft_token() -> None:
    assert parse_category_callback_data("exp_cat:7") is None


def test_bank_event_keyboards_pack_callback_data() -> None:
    actions_keyboard = build_bank_event_actions_keyboard(42, can_confirm=True)
    confirm_callback = BankEventActionCallback.unpack(
        actions_keyboard.inline_keyboard[0][0].callback_data
    )
    assert confirm_callback.event_id == 42
    assert confirm_callback.action == BankEventAction.CONFIRM

    categories_keyboard = build_bank_event_category_keyboard(
        event_id=42,
        categories=[
            CategoryOption(
                id=8,
                code="cosmetology_medicine",
                title="Косметология/Медицина",
                sort_order=8,
                owner_role="system",
                is_expense=True,
            )
        ],
    )
    category_callback = BankEventCategoryCallback.unpack(
        categories_keyboard.inline_keyboard[0][0].callback_data
    )
    assert category_callback.event_id == 42
    assert category_callback.category_id == 8

    refund_keyboard = build_bank_refund_actions_keyboard(46, can_confirm=True)
    refund_callback = BankEventActionCallback.unpack(
        refund_keyboard.inline_keyboard[0][0].callback_data
    )
    refund_texts = [button.text for row in refund_keyboard.inline_keyboard for button in row]
    assert refund_callback.event_id == 46
    assert refund_callback.action == BankEventAction.REFUND_CORRECTION
    assert "↩️ Учесть возврат" in refund_texts
    assert "🏠 Дом" in refund_texts
    assert "💼 Салон" in refund_texts
    assert "🏷 Изменить категорию" not in refund_texts
    assert "🔁 Это перевод себе" not in refund_texts

    income_keyboard = build_bank_income_actions_keyboard(45)
    income_callback = BankEventActionCallback.unpack(
        income_keyboard.inline_keyboard[0][0].callback_data
    )
    income_texts = [button.text for row in income_keyboard.inline_keyboard for button in row]
    assert income_callback.event_id == 45
    assert income_callback.action == BankEventAction.INCOME_CONFIRM
    assert "✅ Учесть доход" in income_texts
    assert "🏠 Дом" in income_texts
    assert "💼 Салон" in income_texts
    assert "🏷 Изменить категорию" not in income_texts

    autosaved_keyboard = build_bank_autosaved_actions_keyboard(47)
    autosaved_callbacks = [
        BankEventActionCallback.unpack(button.callback_data)
        for row in autosaved_keyboard.inline_keyboard
        for button in row
    ]
    autosaved_texts = [button.text for row in autosaved_keyboard.inline_keyboard for button in row]
    assert {callback.action for callback in autosaved_callbacks} == {
        BankEventAction.CHANGE_CATEGORY,
        BankEventAction.INTERNAL_TRANSFER,
        BankEventAction.IGNORE,
        BankEventAction.DISABLE_RULE,
        BankEventAction.SCOPE_HOUSEHOLD,
        BankEventAction.SCOPE_SALON,
    }
    assert {callback.event_id for callback in autosaved_callbacks} == {47}
    assert "✅ Подтвердить" not in autosaved_texts
    assert "🗑 Удалить автозапись" in autosaved_texts
    assert "🏠 Дом" in autosaved_texts
    assert "💼 Салон" in autosaved_texts


def test_bank_learning_keyboards_pack_callback_data() -> None:
    rules_keyboard = build_bank_learning_rules_keyboard(
        (
            BankLearningRuleLine(
                id=11,
                bank="sber",
                merchant_display="BAHETLE_P_QR",
                category_title="Продукты",
                hit_count=2,
                is_active=True,
                mode=BankCategoryRuleMode.AUTOSAVE,
                last_confirmed_at=None,
            ),
        )
    )
    rule_callback = BankLearningRuleCallback.unpack(
        rules_keyboard.inline_keyboard[0][0].callback_data
    )
    assert rule_callback.rule_id == 11
    assert rules_keyboard.inline_keyboard[0][0].text == "🤖 SBER · BAHETLE_P_QR → Продукты"

    actions_keyboard = build_bank_learning_rule_actions_keyboard(
        rule_id=11,
        mode=BankCategoryRuleMode.AUTOSAVE,
    )
    category_action = BankLearningActionCallback.unpack(
        actions_keyboard.inline_keyboard[0][0].callback_data
    )
    suggest_action = BankLearningActionCallback.unpack(
        actions_keyboard.inline_keyboard[1][0].callback_data
    )
    disable_action = BankLearningActionCallback.unpack(
        actions_keyboard.inline_keyboard[2][0].callback_data
    )
    assert category_action.action == BankLearningAction.CHANGE_CATEGORY
    assert suggest_action.action == BankLearningAction.SET_SUGGEST
    assert disable_action.action == BankLearningAction.DISABLE

    categories_keyboard = build_bank_learning_category_keyboard(
        rule_id=11,
        categories=(
            CategoryOption(
                id=8,
                code="cosmetology_medicine",
                title="Косметология/Медицина",
                sort_order=8,
                owner_role="system",
                is_expense=True,
            ),
        ),
    )
    category_callback = BankLearningCategoryCallback.unpack(
        categories_keyboard.inline_keyboard[0][0].callback_data
    )
    assert category_callback.rule_id == 11
    assert category_callback.category_id == 8


def test_bank_learning_aliases_include_settings_buttons() -> None:
    assert "🧠 правила категорий" in BANK_LEARNING_RULES_ALIASES
    assert "🏦 банки" in BANK_LEARNING_RULES_ALIASES


def test_limit_wizard_keyboards_pack_callback_data() -> None:
    categories_keyboard = build_limit_category_keyboard(
        (
            LimitOverviewLine(
                code="groceries",
                title="Продукты",
                sort_order=2,
                kind=LimitRuleKind.MONTHLY_LIMIT,
                amount=7_000_000,
            ),
        ),
        currency="RUB",
    )

    category_callback = LimitCategoryCallback.unpack(
        categories_keyboard.inline_keyboard[0][0].callback_data
    )
    assert category_callback.category_code == "groceries"
    assert categories_keyboard.inline_keyboard[0][0].text == "2. Продукты — 70 000 ₽"

    actions_keyboard = build_limit_action_keyboard(
        category_code="utilities",
        allow_seasonal=True,
    )
    monthly_callback = LimitActionCallback.unpack(
        actions_keyboard.inline_keyboard[0][0].callback_data
    )
    seasonal_callback = LimitActionCallback.unpack(
        actions_keyboard.inline_keyboard[2][0].callback_data
    )
    assert monthly_callback.action == LimitWizardAction.MONTHLY
    assert monthly_callback.category_code == "utilities"
    assert seasonal_callback.action == LimitWizardAction.SEASONAL

    no_seasonal_keyboard = build_limit_action_keyboard(
        category_code="groceries",
        allow_seasonal=False,
    )
    assert all(
        "Лето/зима" not in button.text
        for row in no_seasonal_keyboard.inline_keyboard
        for button in row
    )

    confirm_keyboard = build_limit_confirm_keyboard()
    confirm_callback = LimitConfirmCallback.unpack(
        confirm_keyboard.inline_keyboard[0][0].callback_data
    )
    cancel_callback = LimitConfirmCallback.unpack(
        confirm_keyboard.inline_keyboard[0][1].callback_data
    )
    assert confirm_callback.action == LimitWizardConfirmAction.APPLY
    assert cancel_callback.action == LimitWizardConfirmAction.CANCEL


def test_category_settings_keyboards_pack_callback_data() -> None:
    categories_keyboard = build_category_settings_keyboard(
        (
            CategorySettingsLine(
                code="groceries",
                title="Продукты",
                sort_order=2,
                alias_count=7,
            ),
        )
    )
    category_callback = CategorySettingsCategoryCallback.unpack(
        categories_keyboard.inline_keyboard[0][0].callback_data
    )
    assert category_callback.category_code == "groceries"
    assert categories_keyboard.inline_keyboard[0][0].text == "2. Продукты · 7 алиасов"

    actions_keyboard = build_category_settings_action_keyboard("groceries")
    rename_callback = CategorySettingsActionCallback.unpack(
        actions_keyboard.inline_keyboard[0][0].callback_data
    )
    alias_callback = CategorySettingsActionCallback.unpack(
        actions_keyboard.inline_keyboard[0][1].callback_data
    )
    assert rename_callback.action == CategorySettingsAction.RENAME
    assert rename_callback.category_code == "groceries"
    assert alias_callback.action == CategorySettingsAction.ADD_ALIAS

    confirm_keyboard = build_category_settings_confirm_keyboard()
    confirm_callback = CategorySettingsConfirmCallback.unpack(
        confirm_keyboard.inline_keyboard[0][0].callback_data
    )
    cancel_callback = CategorySettingsConfirmCallback.unpack(
        confirm_keyboard.inline_keyboard[0][1].callback_data
    )
    assert confirm_callback.action == CategorySettingsConfirmAction.APPLY
    assert cancel_callback.action == CategorySettingsConfirmAction.CANCEL


def test_plain_categories_text_opens_chart_not_settings() -> None:
    assert "🏷 категории" in CATEGORY_SETTINGS_ALIASES
    assert "категории" not in CATEGORY_SETTINGS_ALIASES
    assert _category_chart_period_from_menu_text("категории") == PeriodKind.MONTH


def test_create_dispatcher_registers_message_updates() -> None:
    dispatcher = create_dispatcher(make_settings())

    assert isinstance(dispatcher, Dispatcher)
    assert "message" in dispatcher.resolve_used_update_types()
    assert "db_engine" in dispatcher.workflow_data
    assert "db_session_factory" in dispatcher.workflow_data


def test_bank_command_payload_parses_multiline_text() -> None:
    message = type("MessageStub", (), {"text": "/bank line 1\nline 2"})()

    assert _command_payload(message) == "line 1\nline 2"


def test_bank_pending_command_payload_aliases() -> None:
    assert _is_pending_command_payload("pending")
    assert _is_pending_command_payload("Ожидающие")
    assert _is_pending_command_payload(" очередь ")
    assert _is_pending_command_payload("⏳ Ожидают подтверждения")
    assert not _is_pending_command_payload("Счёт карты MIR-1111 Покупка 290р")


def test_auto_accounting_health_aliases() -> None:
    assert "🩺 состояние автоучёта" in AUTO_ACCOUNTING_HEALTH_ALIASES
    assert "состояние автоучета" in AUTO_ACCOUNTING_HEALTH_ALIASES
    assert "🔎 проверить источники" in AUTO_ACCOUNTING_HEALTH_ALIASES
    assert "🔁 повторить отправку ожидающих" in AUTO_ACCOUNTING_RETRY_ALIASES
    assert "повторить ожидающие" in AUTO_ACCOUNTING_RETRY_ALIASES


def test_create_bot_uses_secret_token() -> None:
    bot = create_bot(make_settings())

    assert bot.token == "123456:secret-token"
