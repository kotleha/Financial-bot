import re

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.context_hints import BUDGET_RULE_HINT
from financial_bot.app.bot.formatters.spending_limits import (
    format_budget_report,
    format_limits_overview,
    format_savings_report,
)
from financial_bot.app.bot.keyboards.main_menu import build_main_menu
from financial_bot.app.bot.keyboards.spending_limits import (
    LimitActionCallback,
    LimitCategoryCallback,
    LimitConfirmCallback,
    LimitWizardAction,
    LimitWizardConfirmAction,
    build_limit_action_keyboard,
    build_limit_category_keyboard,
    build_limit_confirm_keyboard,
)
from financial_bot.app.config import Settings
from financial_bot.app.domain.money import format_money_minor, parse_amount_to_minor_units
from financial_bot.app.domain.spending_limits import (
    MonthlyLimitRule,
    NoLimitRule,
    SavingsTargetRule,
    SeasonalLimitRule,
)
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.storage.models import CategoryModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository

router = Router(name=__name__)

LIMITS_ALIASES = {
    "лимиты",
    "🧾 лимиты",
}
BUDGET_ALIASES = {
    "бюджет",
    "💰 бюджет",
    "📋 сводка бюджета",
}
SAVINGS_ALIASES = {
    "копилка",
    "🏦 копилка",
}
LIMIT_WIZARD_ALIASES = {
    "настроить лимиты",
    "⚙️ настроить лимиты",
}
LIMIT_WIZARD_CANCEL_ALIASES = {
    "отмена",
    "отменить",
    "cancel",
    "назад",
    "главное меню",
    "↩️ главное меню",
}
SET_LIMIT_RE = re.compile(r"^set\s+(?P<sort_order>\d+)\s+(?P<amount>.+)$", re.IGNORECASE)
OFF_LIMIT_RE = re.compile(r"^off\s+(?P<sort_order>\d+)$", re.IGNORECASE)
TARGET_LIMIT_RE = re.compile(
    r"^target\s+(?P<sort_order>\d+)\s+(?P<amount>.+)$",
    re.IGNORECASE,
)
UTILITIES_SEASONAL_RE = re.compile(
    r"^(?:utilities|жкх)\s+(?:summer|лето)\s+(?P<summer>.+?)\s+"
    r"(?:winter|зима)\s+(?P<winter>.+)$",
    re.IGNORECASE,
)
SEASONAL_LIMIT_CATEGORY_CODE = "utilities"


class LimitWizardState(StatesGroup):
    waiting_amount = State()
    waiting_seasonal_summer = State()
    waiting_seasonal_winter = State()
    confirming = State()


@router.message(Command("limits", "budget", "savings"))
async def budget_report_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    bot: Bot,
    telegram_user_id: int,
) -> None:
    try:
        if await _try_answer_config_command(message, session, settings, bot, telegram_user_id):
            return
    except ValueError as exc:
        await message.answer(f"Не смог обновить лимит: {exc}")
        return
    command = _command_name(message.text or "")
    if command == "limits":
        await _answer_limits_overview(message, session, settings)
    elif command == "savings":
        await _answer_savings_report(message, session, settings)
    else:
        await _answer_budget_report(message, session, settings)


@router.message(F.text.func(lambda text: text.strip().lower() in LIMIT_WIZARD_ALIASES))
async def limit_wizard_start(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    await state.clear()
    await _answer_limit_category_list(message, session, settings)


@router.callback_query(LimitCategoryCallback.filter())
async def limit_category_selected(
    callback: CallbackQuery,
    callback_data: LimitCategoryCallback,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    await state.clear()
    category = await _resolve_editable_category_by_code(session, callback_data.category_code)
    if category is None:
        await callback.answer("Категория недоступна", show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            await _format_category_limit_card(category, session, settings),
            reply_markup=build_limit_action_keyboard(
                category_code=category.code,
                allow_seasonal=category.code == SEASONAL_LIMIT_CATEGORY_CODE,
            ),
        )


@router.callback_query(LimitActionCallback.filter())
async def limit_action_selected(
    callback: CallbackQuery,
    callback_data: LimitActionCallback,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    category = await _resolve_editable_category_by_code(session, callback_data.category_code)
    if category is None:
        await callback.answer("Категория недоступна", show_alert=True)
        return

    if callback_data.action == LimitWizardAction.BACK:
        await state.clear()
        await callback.answer()
        if callback.message is not None:
            await _answer_limit_category_list(callback.message, session, settings)
        return

    if callback_data.action == LimitWizardAction.NO_LIMIT:
        await _prepare_confirmation(
            callback,
            state,
            category=category,
            action=callback_data.action,
            settings=settings,
        )
        return

    if callback_data.action == LimitWizardAction.SEASONAL:
        if category.code != SEASONAL_LIMIT_CATEGORY_CODE:
            await callback.answer("Сезонный лимит доступен только для ЖКХ", show_alert=True)
            return
        await state.update_data(category_code=category.code, action=callback_data.action.value)
        await state.set_state(LimitWizardState.waiting_seasonal_summer)
        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(f"{category.title}: введите летний лимит, например 8000.")
        return

    await state.update_data(category_code=category.code, action=callback_data.action.value)
    await state.set_state(LimitWizardState.waiting_amount)
    await callback.answer()
    if callback.message is not None:
        if callback_data.action == LimitWizardAction.SAVINGS_TARGET:
            await callback.message.answer(
                f"{category.title}: введите цель накопления за месяц, например 30000."
            )
        else:
            await callback.message.answer(
                f"{category.title}: введите месячный лимит, например 70000."
            )


@router.message(LimitWizardState.waiting_amount)
async def limit_amount_entered(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    if await _try_cancel_limit_wizard(message, state):
        return
    data = await state.get_data()
    category = await _category_from_state_data(session, data)
    action = _action_from_state_data(data)
    if category is None or action is None:
        await state.clear()
        await message.answer("Диалог настройки лимитов устарел. Начните заново.")
        return

    try:
        amount = _parse_limit_amount(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await _prepare_confirmation(
        message,
        state,
        category=category,
        action=action,
        settings=settings,
        amount=amount,
    )


@router.message(LimitWizardState.waiting_seasonal_summer)
async def limit_seasonal_summer_entered(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if await _try_cancel_limit_wizard(message, state):
        return
    data = await state.get_data()
    category = await _category_from_state_data(session, data)
    if category is None:
        await state.clear()
        await message.answer("Диалог настройки лимитов устарел. Начните заново.")
        return

    try:
        summer_amount = _parse_limit_amount(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await state.update_data(summer_amount=summer_amount)
    await state.set_state(LimitWizardState.waiting_seasonal_winter)
    await message.answer(f"{category.title}: теперь введите зимний лимит, например 15000.")


@router.message(LimitWizardState.waiting_seasonal_winter)
async def limit_seasonal_winter_entered(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    if await _try_cancel_limit_wizard(message, state):
        return
    data = await state.get_data()
    category = await _category_from_state_data(session, data)
    if category is None:
        await state.clear()
        await message.answer("Диалог настройки лимитов устарел. Начните заново.")
        return

    try:
        winter_amount = _parse_limit_amount(message.text)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await _prepare_confirmation(
        message,
        state,
        category=category,
        action=LimitWizardAction.SEASONAL,
        settings=settings,
        summer_amount=_required_int(data, "summer_amount"),
        winter_amount=winter_amount,
    )


@router.callback_query(LimitConfirmCallback.filter())
async def limit_confirmation_selected(
    callback: CallbackQuery,
    callback_data: LimitConfirmCallback,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
    bot: Bot,
    telegram_user_id: int,
) -> None:
    if callback_data.action == LimitWizardConfirmAction.CANCEL:
        await state.clear()
        await callback.answer("Отменено")
        if callback.message is not None:
            await callback.message.answer("Настройка лимита отменена.")
        return

    data = await state.get_data()
    category = await _category_from_state_data(session, data)
    action = _action_from_state_data(data)
    if category is None or action is None:
        await state.clear()
        await callback.answer("Диалог устарел", show_alert=True)
        return

    try:
        summary = await _apply_limit_change(
            session,
            settings,
            category=category,
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
    await _notify_family_limit_change(bot, settings, telegram_user_id, summary)


@router.message(LimitWizardState.confirming)
async def limit_confirmation_text_entered(message: Message, state: FSMContext) -> None:
    if await _try_cancel_limit_wizard(message, state):
        return
    await message.answer("Нажмите «Подтвердить» или «Отмена» под сообщением с изменением лимита.")


@router.message(F.text.func(lambda text: text.strip().lower() in LIMITS_ALIASES))
async def limits_overview_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await _answer_limits_overview(message, session, settings)


@router.message(F.text.func(lambda text: text.strip().lower() in BUDGET_ALIASES))
async def budget_report_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await _answer_budget_report(message, session, settings)


@router.message(F.text.func(lambda text: text.strip().lower() in SAVINGS_ALIASES))
async def savings_report_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    await _answer_savings_report(message, session, settings)


async def _answer_limits_overview(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    overview = await SpendingLimitService(session, settings).build_limits_overview()
    await message.answer(format_limits_overview(overview))


async def _answer_budget_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    report = await SpendingLimitService(session, settings).build_monthly_report()
    await message.answer(format_budget_report(report))


async def _answer_savings_report(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    report = await SpendingLimitService(session, settings).build_monthly_report()
    await message.answer(format_savings_report(report))


async def _try_answer_config_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    bot: Bot,
    telegram_user_id: int,
) -> bool:
    payload = _command_payload(message.text or "")
    if not payload:
        return False

    service = SpendingLimitService(session, settings)
    categories = CategoryRepository(session)

    if match := SET_LIMIT_RE.fullmatch(payload):
        category = await _resolve_editable_category(categories, match.group("sort_order"))
        if category is None:
            await message.answer("Не нашёл активную категорию с таким номером.")
            return True
        amount = parse_amount_to_minor_units(match.group("amount"))
        await service.set_monthly_limit(category_code=category.code, amount=amount)
        await session.commit()
        summary = _format_limit_change_summary(
            category.title,
            LimitWizardAction.MONTHLY,
            settings.default_currency,
            amount=amount,
        )
        await message.answer(summary)
        await _notify_family_limit_change(bot, settings, telegram_user_id, summary)
        return True

    if match := OFF_LIMIT_RE.fullmatch(payload):
        category = await _resolve_editable_category(categories, match.group("sort_order"))
        if category is None:
            await message.answer("Не нашёл активную категорию с таким номером.")
            return True
        await service.set_no_limit(category_code=category.code)
        await session.commit()
        summary = _format_limit_change_summary(
            category.title,
            LimitWizardAction.NO_LIMIT,
            settings.default_currency,
        )
        await message.answer(summary)
        await _notify_family_limit_change(bot, settings, telegram_user_id, summary)
        return True

    if match := TARGET_LIMIT_RE.fullmatch(payload):
        category = await _resolve_editable_category(categories, match.group("sort_order"))
        if category is None:
            await message.answer("Не нашёл активную категорию с таким номером.")
            return True
        amount = parse_amount_to_minor_units(match.group("amount"))
        await service.set_savings_target(category_code=category.code, amount=amount)
        await session.commit()
        summary = _format_limit_change_summary(
            category.title,
            LimitWizardAction.SAVINGS_TARGET,
            settings.default_currency,
            amount=amount,
        )
        await message.answer(summary)
        await _notify_family_limit_change(bot, settings, telegram_user_id, summary)
        return True

    if match := UTILITIES_SEASONAL_RE.fullmatch(payload):
        summer_amount = parse_amount_to_minor_units(match.group("summer"))
        winter_amount = parse_amount_to_minor_units(match.group("winter"))
        await service.set_utilities_seasonal_limits(
            summer_amount=summer_amount,
            winter_amount=winter_amount,
        )
        await session.commit()
        category = await categories.get_by_code(SEASONAL_LIMIT_CATEGORY_CODE)
        category_title = category.title if category is not None else "ЖКХ"
        summary = _format_limit_change_summary(
            category_title,
            LimitWizardAction.SEASONAL,
            settings.default_currency,
            summer_amount=summer_amount,
            winter_amount=winter_amount,
        )
        await message.answer(summary)
        await _notify_family_limit_change(bot, settings, telegram_user_id, summary)
        return True

    await message.answer(
        "Не понял команду лимитов. Примеры:\n"
        "/limits set 2 70000\n"
        "/limits off 17\n"
        "/limits target 15 30000\n"
        "/limits utilities summer 8000 winter 15000"
    )
    return True


def _command_payload(text: str) -> str:
    parts = text.strip().split(maxsplit=1)
    return parts[1].strip() if len(parts) > 1 else ""


def _command_name(text: str) -> str:
    command = text.strip().split(maxsplit=1)[0].removeprefix("/")
    return command.split("@", maxsplit=1)[0].lower()


async def _resolve_editable_category(
    categories: CategoryRepository,
    raw_sort_order: str,
) -> CategoryModel | None:
    if not raw_sort_order.isdecimal():
        return None
    category = await categories.get_by_sort_order(int(raw_sort_order))
    if category is None or not category.is_active or not category.is_expense:
        return None
    return category


async def _answer_limit_category_list(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    overview = await SpendingLimitService(session, settings).build_limits_overview()
    await message.answer(
        f"Выберите категорию, для которой нужно настроить лимит.\n\n{BUDGET_RULE_HINT}",
        reply_markup=build_limit_category_keyboard(overview.lines, currency=overview.currency),
    )


async def _format_category_limit_card(
    category: CategoryModel,
    session: AsyncSession,
    settings: Settings,
) -> str:
    service = SpendingLimitService(session, settings)
    config = await service.get_config()
    rule = config.categories.get(category.code)
    if rule is None:
        return f"{category.title}\n\nДля этой категории лимит пока не настроен."

    return "\n".join(
        [
            category.title,
            "",
            f"Текущее правило: {_format_detailed_rule(rule, settings.default_currency)}",
            BUDGET_RULE_HINT,
            "",
            "Что сделать?",
        ]
    )


def _format_detailed_rule(
    rule: MonthlyLimitRule | SeasonalLimitRule | SavingsTargetRule | NoLimitRule,
    currency: str,
) -> str:
    match rule:
        case MonthlyLimitRule(amount=amount):
            return f"лимит {format_money_minor(amount, currency)} в месяц"
        case SavingsTargetRule(amount=amount):
            return f"цель накопления {format_money_minor(amount, currency)} в месяц"
        case NoLimitRule():
            return "без лимита"
        case SeasonalLimitRule(limits=limits):
            formatted_limits = []
            for limit in limits:
                label = "лето" if set(limit.months) == {4, 5, 6, 7, 8, 9} else "зима"
                formatted_limits.append(f"{label} {format_money_minor(limit.amount, currency)}")
            return "сезонный лимит: " + ", ".join(formatted_limits)


async def _prepare_confirmation(
    target: Message | CallbackQuery,
    state: FSMContext,
    *,
    category: CategoryModel,
    action: LimitWizardAction,
    settings: Settings,
    amount: int | None = None,
    summer_amount: int | None = None,
    winter_amount: int | None = None,
) -> None:
    await state.update_data(
        category_code=category.code,
        action=action.value,
        amount=amount,
        summer_amount=summer_amount,
        winter_amount=winter_amount,
    )
    await state.set_state(LimitWizardState.confirming)
    text = _format_limit_change_preview(
        category.title,
        action,
        settings.default_currency,
        amount=amount,
        summer_amount=summer_amount,
        winter_amount=winter_amount,
    )

    if isinstance(target, CallbackQuery):
        await target.answer()
        if target.message is not None:
            await target.message.answer(text, reply_markup=build_limit_confirm_keyboard())
        return

    await target.answer(text, reply_markup=build_limit_confirm_keyboard())


def _format_limit_change_preview(
    category_title: str,
    action: LimitWizardAction,
    currency: str,
    *,
    amount: int | None = None,
    summer_amount: int | None = None,
    winter_amount: int | None = None,
) -> str:
    return "\n".join(
        [
            "Проверьте изменение лимита:",
            "",
            _format_limit_change_body(
                category_title,
                action,
                currency,
                amount=amount,
                summer_amount=summer_amount,
                winter_amount=winter_amount,
            ),
        ]
    )


def _format_limit_change_summary(
    category_title: str,
    action: LimitWizardAction,
    currency: str,
    *,
    amount: int | None = None,
    summer_amount: int | None = None,
    winter_amount: int | None = None,
) -> str:
    return "\n".join(
        [
            "Обновил семейный лимит:",
            "",
            _format_limit_change_body(
                category_title,
                action,
                currency,
                amount=amount,
                summer_amount=summer_amount,
                winter_amount=winter_amount,
            ),
        ]
    )


def _format_limit_change_body(
    category_title: str,
    action: LimitWizardAction,
    currency: str,
    *,
    amount: int | None = None,
    summer_amount: int | None = None,
    winter_amount: int | None = None,
) -> str:
    match action:
        case LimitWizardAction.MONTHLY:
            if amount is None:
                raise ValueError("Не указана сумма лимита")
            return f"{category_title} — лимит {format_money_minor(amount, currency)} в месяц"
        case LimitWizardAction.SAVINGS_TARGET:
            if amount is None:
                raise ValueError("Не указана сумма цели")
            return (
                f"{category_title} — цель накопления {format_money_minor(amount, currency)} в месяц"
            )
        case LimitWizardAction.SEASONAL:
            if summer_amount is None or winter_amount is None:
                raise ValueError("Не указаны сезонные лимиты")
            return (
                f"{category_title} — лето {format_money_minor(summer_amount, currency)}, "
                f"зима {format_money_minor(winter_amount, currency)}"
            )
        case LimitWizardAction.NO_LIMIT:
            return f"{category_title} — без лимита"
        case LimitWizardAction.BACK:
            raise ValueError("Некорректное действие лимита")


async def _apply_limit_change(
    session: AsyncSession,
    settings: Settings,
    *,
    category: CategoryModel,
    action: LimitWizardAction,
    data: dict,
) -> str:
    service = SpendingLimitService(session, settings)
    match action:
        case LimitWizardAction.MONTHLY:
            amount = _required_int(data, "amount")
            await service.set_monthly_limit(category_code=category.code, amount=amount)
            return _format_limit_change_summary(
                category.title,
                action,
                settings.default_currency,
                amount=amount,
            )
        case LimitWizardAction.SAVINGS_TARGET:
            amount = _required_int(data, "amount")
            await service.set_savings_target(category_code=category.code, amount=amount)
            return _format_limit_change_summary(
                category.title,
                action,
                settings.default_currency,
                amount=amount,
            )
        case LimitWizardAction.SEASONAL:
            if category.code != SEASONAL_LIMIT_CATEGORY_CODE:
                raise ValueError("Сезонный лимит доступен только для ЖКХ")
            summer_amount = _required_int(data, "summer_amount")
            winter_amount = _required_int(data, "winter_amount")
            await service.set_seasonal_limits(
                category_code=category.code,
                summer_amount=summer_amount,
                winter_amount=winter_amount,
            )
            return _format_limit_change_summary(
                category.title,
                action,
                settings.default_currency,
                summer_amount=summer_amount,
                winter_amount=winter_amount,
            )
        case LimitWizardAction.NO_LIMIT:
            await service.set_no_limit(category_code=category.code)
            return _format_limit_change_summary(
                category.title,
                action,
                settings.default_currency,
            )
        case LimitWizardAction.BACK:
            raise ValueError("Некорректное действие лимита")


async def _resolve_editable_category_by_code(
    session: AsyncSession,
    category_code: str,
) -> CategoryModel | None:
    category = await CategoryRepository(session).get_by_code(category_code)
    if category is None or not category.is_active or not category.is_expense:
        return None
    return category


async def _category_from_state_data(
    session: AsyncSession,
    data: dict,
) -> CategoryModel | None:
    category_code = data.get("category_code")
    if not isinstance(category_code, str) or not category_code:
        return None
    return await _resolve_editable_category_by_code(session, category_code)


def _action_from_state_data(data: dict) -> LimitWizardAction | None:
    raw_action = data.get("action")
    if not isinstance(raw_action, str):
        return None
    try:
        return LimitWizardAction(raw_action)
    except ValueError:
        return None


def _parse_limit_amount(text: str | None) -> int:
    if text is None:
        raise ValueError("Введите сумму числом, например 70000.")
    try:
        return parse_amount_to_minor_units(text)
    except ValueError as exc:
        raise ValueError("Не понял сумму. Введите число, например 70000.") from exc


def _required_int(data: dict, key: str) -> int:
    value = data.get(key)
    if not isinstance(value, int):
        raise ValueError("Диалог настройки лимитов устарел. Начните заново.")
    return value


async def _try_cancel_limit_wizard(message: Message, state: FSMContext) -> bool:
    if (message.text or "").strip().lower() not in LIMIT_WIZARD_CANCEL_ALIASES:
        return False
    await state.clear()
    await message.answer("Настройка лимитов отменена.", reply_markup=build_main_menu())
    return True


async def _notify_family_limit_change(
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
            # Telegram delivery can fail if a user blocked the bot; the setting is already saved.
            continue
