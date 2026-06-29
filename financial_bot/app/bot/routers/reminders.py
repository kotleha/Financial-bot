from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.services.reminder_service import ReminderService, ReminderSettings

router = Router(name=__name__)


@router.message(Command("reminders"))
async def reminders_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    service = ReminderService(session, settings)
    tokens = _command_args(message)

    try:
        if not tokens:
            reminder_settings = await service.get_settings()
        elif tokens[0].lower() == "on":
            reminder_settings = await service.set_enabled(True)
        elif tokens[0].lower() == "off":
            reminder_settings = await service.set_enabled(False)
        elif tokens[0].lower() == "time" and len(tokens) >= 2:
            reminder_settings = await service.set_daily_time(tokens[1])
        else:
            await message.answer(
                "Используйте: /reminders, /reminders on, /reminders off, /reminders time 21:00"
            )
            return
    except ValueError as exc:
        await message.answer(f"Не смог изменить напоминания: {exc}")
        return

    recipients = await service.active_recipients()
    await message.answer(_format_reminder_status(reminder_settings, settings, len(recipients)))


@router.message(F.text.func(lambda text: text.strip().lower() in {"⏰ напоминания", "напоминания"}))
async def reminders_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await _answer_reminder_status(message, session, settings)


async def _answer_reminder_status(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    service = ReminderService(session, settings)
    reminder_settings = await service.get_settings()
    recipients = await service.active_recipients()
    await message.answer(_format_reminder_status(reminder_settings, settings, len(recipients)))


def _format_reminder_status(
    reminder_settings: ReminderSettings,
    settings: Settings,
    recipient_count: int,
) -> str:
    enabled_label = "включены" if reminder_settings.enabled else "выключены"
    return "\n".join(
        [
            f"Напоминания: {enabled_label}",
            f"Ежедневное время: {reminder_settings.daily_time} ({settings.timezone})",
            f"Последняя отправка: {reminder_settings.last_sent_date or 'ещё не было'}",
            f"Активных получателей: {recipient_count}",
        ]
    )


def _command_args(message: Message) -> list[str]:
    if message.text is None:
        return []
    return message.text.split()[1:]
