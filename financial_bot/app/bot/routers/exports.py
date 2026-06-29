from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.months import parse_month_token
from financial_bot.app.domain.periods import (
    Period,
    PeriodKind,
    resolve_month_period,
    resolve_period,
)
from financial_bot.app.services.export_service import ExportResult, ExportService

router = Router(name=__name__)


@router.message(Command("export"))
async def export_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    tokens = _command_args(message)
    if not tokens or tokens[0].lower() not in {"csv", "xlsx"}:
        await message.answer("Используйте: /export csv may или /export xlsx 2026")
        return

    export_format = tokens[0].lower()
    try:
        period = _parse_export_period(tokens[1:], settings)
        service = ExportService(session, settings)
        if export_format == "csv":
            result = await service.create_csv_export(period)
        else:
            result = await service.create_xlsx_export(period)
    except ValueError as exc:
        await message.answer(f"Не смог подготовить экспорт: {exc}")
        return

    await _send_export_or_empty(message, result)


async def _send_export_or_empty(message: Message, result: ExportResult | None) -> None:
    if result is None:
        await message.answer("За период нет операций для экспорта.")
        return

    try:
        await message.answer_document(
            FSInputFile(result.path, filename=result.filename),
            caption=result.caption,
        )
    finally:
        _unlink(result.path)


def _parse_export_period(tokens: list[str], settings: Settings) -> Period:
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


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
