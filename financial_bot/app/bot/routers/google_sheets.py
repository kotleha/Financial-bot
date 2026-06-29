from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.months import parse_month_token
from financial_bot.app.domain.periods import (
    Period,
    PeriodKind,
    resolve_month_period,
    resolve_period,
)
from financial_bot.app.services.google_sheets_service import (
    GoogleSheetsExportError,
    GoogleSheetsNotConfigured,
    GoogleSheetsService,
)

router = Router(name=__name__)


@router.message(Command("sheets"))
async def sheets_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    if not tokens or tokens[0].lower() != "export":
        await message.answer("Используйте: /sheets export may")
        return

    try:
        period = _parse_period(tokens[1:], settings)
        summary = await GoogleSheetsService(session, settings).export_period(period)
    except GoogleSheetsNotConfigured:
        await message.answer("Google Sheets export не настроен.")
        return
    except (GoogleSheetsExportError, ValueError) as exc:
        await message.answer(f"Google Sheets export не выполнен: {exc}")
        return

    if summary is None:
        await message.answer("За период нет операций для выгрузки в Google Sheets.")
        return

    await message.answer(f"Выгрузил в Google Sheets: {summary.total_rows} строк за {period.label}.")


def _parse_period(tokens: list[str], settings: Settings) -> Period:
    timezone = ZoneInfo(settings.timezone)
    now = datetime.now(timezone)
    if not tokens:
        return resolve_month_period(year=now.year, month=now.month, timezone=settings.timezone)

    first = tokens[0].strip().lower()
    if first.isdigit() and len(first) == 4:
        year = int(first)
        return resolve_period(
            PeriodKind.YEAR,
            now=datetime(year, 6, 1, tzinfo=timezone),
            timezone=settings.timezone,
        )

    month = parse_month_token(first)
    year = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else now.year
    return resolve_month_period(year=year, month=month, timezone=settings.timezone)


def _command_args(message: Message) -> list[str]:
    if message.text is None:
        return []
    return message.text.split()[1:]
