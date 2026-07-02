from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.transactions import format_income_created
from financial_bot.app.config import Settings
from financial_bot.app.domain.income_input import parse_income_input
from financial_bot.app.domain.types import TransactionSource
from financial_bot.app.services.transaction_service import TransactionService

router = Router(name=__name__)

ADD_INCOME_ALIASES = {"➕ доход", "добавить доход", "новый доход", "доход"}
INCOME_TEXT_PREFIXES = ("доход ", "+")
BANK_NOTIFICATION_MARKERS = (
    "баланс",
    "карта*",
    "карта *",
    "счет*",
    "счёт*",
    "счет ",
    "счёт ",
    "счёт карты",
    "счет карты",
    "mir-",
    "мир-",
    "оплата ",
    "покупка ",
    "списание ",
    "зачисление ",
    "поступление ",
)


@router.message(Command("income"))
async def income_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payload = _command_payload(message)
    if not payload:
        await _answer_income_help(message)
        return
    await _create_income_from_payload(message, session, settings, payload)


@router.message(F.text.func(lambda text: _is_income_menu_or_entry_text(text)))
async def income_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    text = (message.text or "").strip()
    if _is_add_income_menu_text(text):
        await _answer_income_help(message)
        return

    payload = _income_payload_from_text(text)
    if payload is None:
        await _answer_income_help(message)
        return
    await _create_income_from_payload(message, session, settings, payload)


async def _create_income_from_payload(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    payload: str,
) -> None:
    if _looks_like_bank_notification(payload):
        await message.answer("Похоже на банковское SMS. Для таких сообщений используйте /bank.")
        return

    try:
        parsed = parse_income_input(payload)
        summary = await TransactionService(session, settings).create_income(
            amount=parsed.amount,
            recipient_telegram_id=message.from_user.id,
            raw_text=_manual_income_raw_text(parsed.category_code),
            category_code=parsed.category_code,
            comment=parsed.comment or None,
            source=TransactionSource.UNKNOWN,
            scope=parsed.scope,
        )
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        if str(exc) == "Invalid income input":
            await message.answer("Не смог учесть доход. Напишите сумму и источник дохода.")
        else:
            await message.answer(f"Не смог учесть доход: {exc}")
        return

    await message.answer(format_income_created(summary))


async def _answer_income_help(message: Message) -> None:
    await message.answer(
        "Введите доход одной строкой:\n"
        "/income 100000 зарплата\n"
        "/income салон 70000 бизнес\n"
        "доход 25000 аванс\n"
        "+15000 проект\n\n"
        "Категории: зарплата, аванс, премия/бонус, бизнес/проекты, возврат долга, прочий доход."
    )


def _command_payload(message: Message) -> str:
    if message.text is None:
        return ""
    parts = message.text.split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _is_income_menu_or_entry_text(text: str) -> bool:
    normalized = text.strip().lower()
    return _is_add_income_menu_text(normalized) or _income_payload_from_text(normalized) is not None


def _is_add_income_menu_text(text: str) -> bool:
    return text.strip().lower() in ADD_INCOME_ALIASES


def _income_payload_from_text(text: str) -> str | None:
    normalized = text.strip()
    lowered = normalized.lower()
    for prefix in INCOME_TEXT_PREFIXES:
        if lowered.startswith(prefix):
            return normalized[len(prefix) :].strip() if prefix != "+" else normalized
    return None


def _looks_like_bank_notification(text: str) -> bool:
    normalized = text.strip().lower().replace("ё", "е")
    if not normalized:
        return False
    if normalized.startswith(("счет", "счет карты", "счёт", "счёт карты")):
        return True
    return any(marker in normalized for marker in BANK_NOTIFICATION_MARKERS)


def _manual_income_raw_text(category_code: str) -> str:
    return f"manual_income:{category_code}"
