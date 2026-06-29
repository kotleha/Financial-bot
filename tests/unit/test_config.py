from pathlib import Path

import pytest
from financial_bot.app.config import Settings, SettingsLoadError, load_settings
from pydantic import ValidationError

SETTINGS_ENV_VARS = (
    "BOT_TOKEN",
    "DATABASE_URL",
    "ALLOWED_TELEGRAM_IDS",
    "DEFAULT_CURRENCY",
    "TIMEZONE",
    "HUSBAND_TELEGRAM_ID",
    "WIFE_TELEGRAM_ID",
    "BANK_SELF_COUNTERPARTY_ALIASES",
    "TELEGRAM_ROUTE_URL",
)


def make_settings(**overrides: object) -> Settings:
    values = {
        "bot_token": "123456:secret-token",
        "database_url": "sqlite+aiosqlite:///./data/test.sqlite3",
        "allowed_telegram_ids": "1001,1002",
        "default_currency": "rub",
        "timezone": "Asia/Barnaul",
        "husband_telegram_id": 1001,
        "wife_telegram_id": 1002,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def clear_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable_name in SETTINGS_ENV_VARS:
        monkeypatch.delenv(variable_name, raising=False)


def write_env_file(path: Path, values: dict[str, object]) -> None:
    lines = [f"{key}={value}" for key, value in values.items()]
    path.write_text("\n".join(lines), encoding="utf-8")


def test_settings_parse_and_normalize_values() -> None:
    settings = make_settings()

    assert settings.default_currency == "RUB"
    assert settings.allowed_telegram_ids == frozenset({1001, 1002})
    assert settings.is_telegram_id_allowed(1001)
    assert not settings.is_telegram_id_allowed(9999)


def test_settings_load_from_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clear_settings_environment(monkeypatch)
    env_file = tmp_path / ".env"
    write_env_file(
        env_file,
        {
            "BOT_TOKEN": "123456:secret-token",
            "DATABASE_URL": "sqlite+aiosqlite:///./data/test.sqlite3",
            "ALLOWED_TELEGRAM_IDS": "1001,1002",
            "DEFAULT_CURRENCY": "RUB",
            "TIMEZONE": "Asia/Barnaul",
            "HUSBAND_TELEGRAM_ID": 1001,
            "WIFE_TELEGRAM_ID": 1002,
        },
    )

    settings = load_settings(env_file)

    assert settings.get_bot_token() == "123456:secret-token"
    assert settings.allowed_telegram_ids == frozenset({1001, 1002})


def test_telegram_route_url_is_loaded_and_masked() -> None:
    settings = make_settings(telegram_route_url="http://10.255.78.2:18080")

    assert settings.telegram_route_url == "http://10.255.78.2:18080"
    assert settings.safe_log_dict()["telegram_route_url"] == "**********"
    assert "10.255.78.2" not in str(settings.safe_log_dict())


def test_missing_bot_token_fails_with_clear_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_settings_environment(monkeypatch)
    env_file = tmp_path / ".env"
    write_env_file(
        env_file,
        {
            "DATABASE_URL": "sqlite+aiosqlite:///./data/test.sqlite3",
            "ALLOWED_TELEGRAM_IDS": "1001,1002",
            "DEFAULT_CURRENCY": "RUB",
            "TIMEZONE": "Asia/Barnaul",
            "HUSBAND_TELEGRAM_ID": 1001,
            "WIFE_TELEGRAM_ID": 1002,
        },
    )

    with pytest.raises(SettingsLoadError, match="bot_token"):
        load_settings(env_file)


def test_malformed_allowed_telegram_ids_fail() -> None:
    with pytest.raises(ValidationError, match="Telegram ID must be a positive integer"):
        make_settings(allowed_telegram_ids="1001,not-an-id")


def test_family_users_must_be_in_allowed_telegram_ids() -> None:
    with pytest.raises(ValidationError, match="Family Telegram IDs"):
        make_settings(allowed_telegram_ids="1001,3003")


def test_family_users_must_be_distinct() -> None:
    with pytest.raises(ValidationError, match="must be different"):
        make_settings(
            allowed_telegram_ids="1001",
            husband_telegram_id=1001,
            wife_telegram_id=1001,
        )


def test_timezone_must_be_valid() -> None:
    with pytest.raises(ValidationError, match="valid IANA timezone"):
        make_settings(timezone="Not/AZone")


def test_bot_token_is_masked_in_repr_and_safe_log_dict() -> None:
    settings = make_settings()

    assert "secret-token" not in repr(settings)
    assert settings.safe_log_dict()["bot_token"] == "**********"
    assert settings.safe_log_dict()["bank_self_counterparty_aliases"] == "**********"
    assert "secret-token" not in str(settings.safe_log_dict())


def test_bank_self_counterparty_aliases_are_optional_and_parsed() -> None:
    settings = make_settings(bank_self_counterparty_aliases="SELF PERSON, FAMILY ACCOUNT")

    assert settings.bank_self_counterparty_aliases == frozenset({"SELF PERSON", "FAMILY ACCOUNT"})
