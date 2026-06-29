from pathlib import Path
from typing import Annotated, Any, Self
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class SettingsLoadError(RuntimeError):
    """Raised when application settings cannot be loaded."""


class Settings(BaseSettings):
    """Typed application settings loaded from environment variables or `.env`."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_file=".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    bot_token: SecretStr
    database_url: str = Field(min_length=1)
    allowed_telegram_ids: Annotated[frozenset[int], NoDecode]
    default_currency: str = Field(min_length=3, max_length=3)
    timezone: str = Field(min_length=1)
    husband_telegram_id: int = Field(gt=0)
    wife_telegram_id: int = Field(gt=0)

    google_credentials_path: str | None = None
    google_spreadsheet_id: str | None = None
    bank_self_counterparty_aliases: Annotated[frozenset[str], NoDecode] = frozenset()
    bank_ingest_host: str = "127.0.0.1"
    bank_ingest_port: int = Field(default=8000, ge=1, le=65535)
    telegram_route_url: str | None = None

    @field_validator("bot_token")
    @classmethod
    def validate_bot_token(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            msg = "BOT_TOKEN must not be empty"
            raise ValueError(msg)
        return value

    @field_validator("allowed_telegram_ids", mode="before")
    @classmethod
    def parse_allowed_telegram_ids(cls, value: Any) -> frozenset[int]:
        if isinstance(value, str):
            raw_parts = [part.strip() for part in value.split(",") if part.strip()]
            if not raw_parts:
                msg = "ALLOWED_TELEGRAM_IDS must contain at least one Telegram ID"
                raise ValueError(msg)

            parsed_ids: list[int] = []
            for raw_part in raw_parts:
                if not raw_part.isdecimal():
                    msg = f"Telegram ID must be a positive integer: {raw_part!r}"
                    raise ValueError(msg)
                parsed_ids.append(int(raw_part))
            value = parsed_ids

        try:
            allowed_ids = frozenset(int(item) for item in value)
        except TypeError as exc:
            msg = "ALLOWED_TELEGRAM_IDS must be a comma-separated list of integers"
            raise ValueError(msg) from exc

        if not allowed_ids:
            msg = "ALLOWED_TELEGRAM_IDS must contain at least one Telegram ID"
            raise ValueError(msg)
        if any(item <= 0 for item in allowed_ids):
            msg = "Telegram IDs must be positive integers"
            raise ValueError(msg)

        return allowed_ids

    @field_validator("bank_self_counterparty_aliases", mode="before")
    @classmethod
    def parse_bank_self_counterparty_aliases(cls, value: Any) -> frozenset[str]:
        if value is None:
            return frozenset()
        if isinstance(value, str):
            return frozenset(part.strip() for part in value.split(",") if part.strip())
        try:
            return frozenset(str(item).strip() for item in value if str(item).strip())
        except TypeError as exc:
            msg = "BANK_SELF_COUNTERPARTY_ALIASES must be a comma-separated list"
            raise ValueError(msg) from exc

    @field_validator("default_currency")
    @classmethod
    def normalize_default_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            msg = "DEFAULT_CURRENCY must be a 3-letter currency code"
            raise ValueError(msg)
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: str) -> str:
        normalized = value.strip()
        try:
            ZoneInfo(normalized)
        except (ValueError, ZoneInfoNotFoundError) as exc:
            msg = f"TIMEZONE must be a valid IANA timezone name: {normalized!r}"
            raise ValueError(msg) from exc
        return normalized

    @model_validator(mode="after")
    def validate_family_users(self) -> Self:
        if self.husband_telegram_id == self.wife_telegram_id:
            msg = "HUSBAND_TELEGRAM_ID and WIFE_TELEGRAM_ID must be different"
            raise ValueError(msg)

        missing_ids = {
            self.husband_telegram_id,
            self.wife_telegram_id,
        } - self.allowed_telegram_ids
        if missing_ids:
            sorted_missing = ", ".join(str(item) for item in sorted(missing_ids))
            msg = f"Family Telegram IDs must be included in ALLOWED_TELEGRAM_IDS: {sorted_missing}"
            raise ValueError(msg)

        return self

    def is_telegram_id_allowed(self, telegram_id: int | None) -> bool:
        return telegram_id in self.allowed_telegram_ids if telegram_id is not None else False

    def get_bot_token(self) -> str:
        return self.bot_token.get_secret_value()

    def safe_log_dict(self) -> dict[str, Any]:
        values = self.model_dump()
        values["bot_token"] = "**********"
        values["bank_self_counterparty_aliases"] = "**********"
        values["telegram_route_url"] = "**********" if self.telegram_route_url else None
        return values


def load_settings(env_file: str | Path | None = ".env") -> Settings:
    try:
        return Settings(_env_file=env_file)
    except ValidationError as exc:
        msg = f"Invalid application settings: {exc}"
        raise SettingsLoadError(msg) from exc
