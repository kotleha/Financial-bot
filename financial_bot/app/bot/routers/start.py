from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message

from financial_bot.app.bot.keyboards.main_menu import build_main_menu

router = Router(name=__name__)


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "Готов вести семейные финансы. Введите сумму расхода или выберите действие.",
        reply_markup=build_main_menu(),
    )
