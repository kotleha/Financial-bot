from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.storage.repositories.setting_repository import SettingRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository

REMINDER_SETTINGS_KEY = "reminders"


@dataclass(frozen=True, slots=True)
class ReminderSettings:
    enabled: bool = False
    daily_time: str = "21:00"
    last_sent_date: str | None = None


@dataclass(frozen=True, slots=True)
class ReminderRecipient:
    telegram_id: int
    name: str
    role: str


@dataclass(frozen=True, slots=True)
class DueReminder:
    local_date: str
    text: str
    recipients: tuple[ReminderRecipient, ...]


class ReminderService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._settings = settings
        self._settings_repository = SettingRepository(session)
        self._users = UserRepository(session)

    async def get_settings(self) -> ReminderSettings:
        stored = await self._settings_repository.get_value(REMINDER_SETTINGS_KEY)
        if stored is None:
            return ReminderSettings()
        return _settings_from_dict(stored)

    async def set_enabled(self, enabled: bool) -> ReminderSettings:
        current = await self.get_settings()
        updated = ReminderSettings(
            enabled=enabled,
            daily_time=current.daily_time,
            last_sent_date=current.last_sent_date,
        )
        await self._save(updated)
        return updated

    async def set_daily_time(self, value: str) -> ReminderSettings:
        normalized = _parse_time(value)
        current = await self.get_settings()
        updated = ReminderSettings(
            enabled=current.enabled,
            daily_time=normalized,
            last_sent_date=current.last_sent_date,
        )
        await self._save(updated)
        return updated

    async def due_daily_reminder(self, now: datetime | None = None) -> DueReminder | None:
        reminder_settings = await self.get_settings()
        if not reminder_settings.enabled:
            return None

        local_now = _local_datetime(now, self._settings.timezone)
        if local_now.time() < time.fromisoformat(reminder_settings.daily_time):
            return None

        local_date = local_now.date().isoformat()
        if reminder_settings.last_sent_date == local_date:
            return None

        recipients = await self.active_recipients()
        if not recipients:
            return None

        return DueReminder(
            local_date=local_date,
            text=self.daily_reminder_text(),
            recipients=recipients,
        )

    async def mark_daily_sent(self, local_date: str) -> ReminderSettings:
        parsed_date = _parse_date(local_date)
        current = await self.get_settings()
        updated = ReminderSettings(
            enabled=current.enabled,
            daily_time=current.daily_time,
            last_sent_date=parsed_date,
        )
        await self._save(updated)
        return updated

    async def active_recipients(self) -> tuple[ReminderRecipient, ...]:
        users = await self._users.list_active()
        return tuple(
            ReminderRecipient(
                telegram_id=user.telegram_id,
                name=user.name,
                role=user.role,
            )
            for user in users
        )

    def daily_reminder_text(self) -> str:
        return "Вечернее напоминание: внесите расходы за день."

    async def _save(self, settings: ReminderSettings) -> None:
        await self._settings_repository.set_value(REMINDER_SETTINGS_KEY, asdict(settings))


def _settings_from_dict(value: dict) -> ReminderSettings:
    return ReminderSettings(
        enabled=bool(value.get("enabled", False)),
        daily_time=_parse_time(str(value.get("daily_time", "21:00"))),
        last_sent_date=_parse_optional_date(value.get("last_sent_date")),
    )


def _parse_time(value: str) -> str:
    try:
        parsed = time.fromisoformat(value.strip())
    except ValueError as exc:
        msg = "Time must be in HH:MM format"
        raise ValueError(msg) from exc
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def _parse_optional_date(value: object) -> str | None:
    if value is None:
        return None
    return _parse_date(str(value))


def _parse_date(value: str) -> str:
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        msg = "Date must be in YYYY-MM-DD format"
        raise ValueError(msg) from exc


def _local_datetime(value: datetime | None, timezone_name: str) -> datetime:
    timezone = ZoneInfo(timezone_name)
    if value is None:
        return datetime.now(timezone)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone)
    return value.astimezone(timezone)
