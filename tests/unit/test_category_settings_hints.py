from financial_bot.app.bot.routers.category_settings import (
    _format_category_alias_preview,
    _format_category_rename_preview,
    _format_category_settings_card,
)
from financial_bot.app.services.category_settings_service import CategorySettingsDetails


def test_category_settings_card_explains_safe_rename_and_aliases() -> None:
    text = _format_category_settings_card(
        CategorySettingsDetails(
            code="groceries",
            title="Продукты",
            sort_order=2,
            aliases=("бахетле", "sberchaevye"),
        )
    )

    assert "2. Продукты" in text
    assert "Алиасы: бахетле, sberchaevye" in text
    assert "название можно менять без потери истории" in text
    assert "Слишком короткие, чисто числовые и занятые алиасы не принимаются" in text


def test_category_rename_preview_explains_history_limits_and_reports_stay() -> None:
    text = _format_category_rename_preview(
        CategorySettingsDetails(
            code="groceries",
            title="Продукты",
            sort_order=2,
            aliases=(),
        ),
        "Еда домой",
    )

    assert "Было: Продукты" in text
    assert "Будет: Еда домой" in text
    assert "Номер 2 и история расходов сохранятся." in text
    assert "Лимиты, алиасы и прошлые отчёты останутся" in text


def test_category_alias_preview_explains_future_recognition() -> None:
    text = _format_category_alias_preview(
        CategorySettingsDetails(
            code="groceries",
            title="Продукты",
            sort_order=2,
            aliases=(),
        ),
        "бахетле",
    )

    assert "Категория: 2. Продукты" in text
    assert "Алиас: бахетле" in text
    assert "ручном вводе и банковских подсказках" in text
