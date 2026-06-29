from enum import StrEnum

from aiogram import Bot, F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

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
from financial_bot.app.bot.keyboards.main_menu import build_main_menu
from financial_bot.app.config import Settings
from financial_bot.app.services.category_settings_service import (
    CategorySettingsDetails,
    CategorySettingsService,
    normalize_category_title,
    validate_category_title,
)

router = Router(name=__name__)

CATEGORY_SETTINGS_ALIASES = {
    "🏷 категории",
    "настроить категории",
    "управление категориями",
}
ALIAS_SETTINGS_ALIASES = {
    "🔤 алиасы",
    "алиасы",
    "настроить алиасы",
}
CATEGORY_SETTINGS_CANCEL_ALIASES = {
    "отмена",
    "отменить",
    "cancel",
    "назад",
    "главное меню",
    "↩️ главное меню",
}


class CategorySettingsPendingAction(StrEnum):
    RENAME = "rename"
    ADD_ALIAS = "alias"


class CategorySettingsState(StatesGroup):
    waiting_title = State()
    waiting_alias = State()
    confirming = State()


@router.message(F.text.func(lambda text: text.strip().lower() in CATEGORY_SETTINGS_ALIASES))
async def category_settings_start(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await _answer_category_settings_list(
        message,
        session,
        "Выберите категорию, которую нужно настроить.",
    )


@router.message(F.text.func(lambda text: text.strip().lower() in ALIAS_SETTINGS_ALIASES))
async def alias_settings_start(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    await _answer_category_settings_list(
        message,
        session,
        "Выберите категорию, к которой нужно добавить алиас.",
    )


@router.callback_query(CategorySettingsCategoryCallback.filter())
async def category_settings_category_selected(
    callback: CallbackQuery,
    callback_data: CategorySettingsCategoryCallback,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    service = CategorySettingsService(session)
    details = await service.get_category_details(callback_data.category_code)
    if details is None:
        await callback.answer("Категория недоступна", show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            _format_category_settings_card(details),
            reply_markup=build_category_settings_action_keyboard(details.code),
        )


@router.callback_query(CategorySettingsActionCallback.filter())
async def category_settings_action_selected(
    callback: CallbackQuery,
    callback_data: CategorySettingsActionCallback,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    service = CategorySettingsService(session)
    details = await service.get_category_details(callback_data.category_code)
    if details is None:
        await callback.answer("Категория недоступна", show_alert=True)
        return

    if callback_data.action == CategorySettingsAction.BACK:
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await _answer_category_settings_list(
                callback.message,
                session,
                "Выберите категорию, которую нужно настроить.",
            )
        return

    if callback_data.action == CategorySettingsAction.RENAME:
        await state.update_data(category_code=details.code)
        await state.set_state(CategorySettingsState.waiting_title)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                f"{details.sort_order}. {details.title}\n\nВведите новое название категории."
            )
        return

    if callback_data.action == CategorySettingsAction.ADD_ALIAS:
        await state.update_data(category_code=details.code)
        await state.set_state(CategorySettingsState.waiting_alias)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                f"{details.sort_order}. {details.title}\n\n"
                "Введите новый алиас: магазин, сервис или слово, по которому бот должен "
                "узнавать эту категорию."
            )


@router.message(CategorySettingsState.waiting_title)
async def category_settings_title_entered(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if await _try_cancel_category_settings(message, state):
        return

    data = await state.get_data()
    details = await _details_from_state_data(session, data)
    if details is None:
        await state.clear()
        await message.answer("Диалог настройки категорий устарел. Начните заново.")
        return

    try:
        title = normalize_category_title(message.text)
        validate_category_title(title)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    if title == details.title:
        await message.answer("Название не изменилось. Введите другое название или отмените.")
        return

    await state.update_data(
        action=CategorySettingsPendingAction.RENAME.value,
        new_title=title,
    )
    await state.set_state(CategorySettingsState.confirming)
    await message.answer(
        _format_category_rename_preview(details, title),
        reply_markup=build_category_settings_confirm_keyboard(),
    )


@router.message(CategorySettingsState.waiting_alias)
async def category_settings_alias_entered(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if await _try_cancel_category_settings(message, state):
        return

    data = await state.get_data()
    details = await _details_from_state_data(session, data)
    if details is None:
        await state.clear()
        await message.answer("Диалог настройки категорий устарел. Начните заново.")
        return

    try:
        alias = await CategorySettingsService(session).validate_alias_for_category(
            category_code=details.code,
            alias=message.text or "",
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.update_data(
        action=CategorySettingsPendingAction.ADD_ALIAS.value,
        alias=alias,
    )
    await state.set_state(CategorySettingsState.confirming)
    await message.answer(
        _format_category_alias_preview(details, alias),
        reply_markup=build_category_settings_confirm_keyboard(),
    )


@router.callback_query(CategorySettingsConfirmCallback.filter())
async def category_settings_confirmation_selected(
    callback: CallbackQuery,
    callback_data: CategorySettingsConfirmCallback,
    session: AsyncSession,
    state: FSMContext,
    bot: Bot,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if callback_data.action == CategorySettingsConfirmAction.CANCEL:
        await state.clear()
        await callback.answer("Отменено")
        if callback.message is not None:
            await callback.message.answer("Настройка категории отменена.")
        return

    data = await state.get_data()
    action = _pending_action_from_state_data(data)
    category_code = _category_code_from_state_data(data)
    if action is None or category_code is None:
        await state.clear()
        await callback.answer("Диалог устарел", show_alert=True)
        return

    try:
        summary = await _apply_category_settings_change(
            session,
            category_code=category_code,
            action=action,
            data=data,
        )
        await session.commit()
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await state.clear()
    await callback.answer("Обновлено")
    if callback.message is not None:
        await callback.message.answer(summary)
    await _notify_family_category_change(bot, settings, telegram_user_id, summary)


@router.message(CategorySettingsState.confirming)
async def category_settings_confirmation_text_entered(
    message: Message,
    state: FSMContext,
) -> None:
    if await _try_cancel_category_settings(message, state):
        return
    await message.answer("Нажмите «Подтвердить» или «Отмена» под сообщением с изменением.")


async def _answer_category_settings_list(
    message: Message,
    session: AsyncSession,
    intro: str,
) -> None:
    lines = await CategorySettingsService(session).list_categories()
    await message.answer(intro, reply_markup=build_category_settings_keyboard(lines))


def _format_category_settings_card(details: CategorySettingsDetails) -> str:
    return "\n".join(
        [
            f"{details.sort_order}. {details.title}",
            "",
            _format_aliases(details.aliases),
            "",
            "Что сделать?",
        ]
    )


def _format_aliases(aliases: tuple[str, ...]) -> str:
    if not aliases:
        return "Алиасов пока нет."
    visible_aliases = aliases[:20]
    text = "Алиасы: " + ", ".join(visible_aliases)
    hidden_count = len(aliases) - len(visible_aliases)
    if hidden_count > 0:
        text += f" и ещё {hidden_count}"
    return text


def _format_category_rename_preview(details: CategorySettingsDetails, new_title: str) -> str:
    return "\n".join(
        [
            "Проверьте изменение категории:",
            "",
            f"Было: {details.title}",
            f"Будет: {new_title}",
            "",
            f"Номер {details.sort_order} и история расходов сохранятся.",
        ]
    )


def _format_category_alias_preview(details: CategorySettingsDetails, alias: str) -> str:
    return "\n".join(
        [
            "Проверьте новый алиас:",
            "",
            f"Категория: {details.sort_order}. {details.title}",
            f"Алиас: {alias}",
        ]
    )


async def _details_from_state_data(
    session: AsyncSession,
    data: dict,
) -> CategorySettingsDetails | None:
    category_code = _category_code_from_state_data(data)
    if category_code is None:
        return None
    return await CategorySettingsService(session).get_category_details(category_code)


def _category_code_from_state_data(data: dict) -> str | None:
    category_code = data.get("category_code")
    if not isinstance(category_code, str) or not category_code:
        return None
    return category_code


def _pending_action_from_state_data(data: dict) -> CategorySettingsPendingAction | None:
    raw_action = data.get("action")
    if not isinstance(raw_action, str):
        return None
    try:
        return CategorySettingsPendingAction(raw_action)
    except ValueError:
        return None


async def _apply_category_settings_change(
    session: AsyncSession,
    *,
    category_code: str,
    action: CategorySettingsPendingAction,
    data: dict,
) -> str:
    service = CategorySettingsService(session)
    if action == CategorySettingsPendingAction.RENAME:
        new_title = data.get("new_title")
        if not isinstance(new_title, str):
            raise ValueError("Диалог настройки категорий устарел. Начните заново.")
        result = await service.rename_category(category_code=category_code, new_title=new_title)
        return "\n".join(
            [
                "Обновил категорию:",
                "",
                f"{result.sort_order}. {result.old_title} → {result.new_title}",
            ]
        )

    alias = data.get("alias")
    if not isinstance(alias, str):
        raise ValueError("Диалог настройки категорий устарел. Начните заново.")
    result = await service.add_alias(category_code=category_code, alias=alias)
    return "\n".join(
        [
            "Добавил алиас:",
            "",
            f"{result.alias} → {result.sort_order}. {result.category_title}",
        ]
    )


async def _try_cancel_category_settings(message: Message, state: FSMContext) -> bool:
    if (message.text or "").strip().lower() not in CATEGORY_SETTINGS_CANCEL_ALIASES:
        return False
    await state.clear()
    await message.answer("Настройка категории отменена.", reply_markup=build_main_menu())
    return True


async def _notify_family_category_change(
    bot: Bot,
    settings: Settings,
    initiator_telegram_id: int,
    text: str,
) -> None:
    for telegram_id in (settings.husband_telegram_id, settings.wife_telegram_id):
        if telegram_id == initiator_telegram_id:
            continue
        try:
            await bot.send_message(telegram_id, text)
        except Exception:
            # Telegram delivery can fail if a user blocked the bot; the change is already saved.
            continue
