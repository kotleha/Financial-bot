from dataclasses import dataclass
from datetime import UTC, datetime, time
from uuid import uuid4
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.batch import format_batch_created
from financial_bot.app.bot.formatters.spending_limits import format_threshold_alert
from financial_bot.app.bot.formatters.transactions import (
    format_transaction_created,
    format_transaction_deleted,
    format_transaction_for_edit,
    format_transaction_repeated,
    format_transaction_updated,
)
from financial_bot.app.bot.keyboards.batch import BATCH_CANCEL_CALLBACK, build_batch_keyboard
from financial_bot.app.bot.keyboards.categories import (
    CATEGORY_CALLBACK_PREFIX,
    CATEGORY_CANCEL_CALLBACK,
    build_category_keyboard,
    parse_category_callback_data,
)
from financial_bot.app.bot.keyboards.transaction_actions import (
    TransactionAction,
    TransactionActionCallback,
    build_transaction_actions_keyboard,
)
from financial_bot.app.bot.session_safety import (
    commit_or_rollback,
    rollback_after_secondary_failure,
)
from financial_bot.app.config import Settings
from financial_bot.app.domain.accounting_scope import scope_label
from financial_bot.app.domain.expense_input import (
    CATEGORY_NUMBER_ONLY_RE,
    is_amount_draft_text,
    parse_amount_draft,
    parse_amount_with_category_number,
    parse_category_number,
)
from financial_bot.app.domain.money import (
    format_money_minor,
    parse_amount_to_minor_units,
)
from financial_bot.app.domain.types import TransactionScope, UserRole
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.services.transaction_service import (
    CategoryOption,
    CreatedTransactionSummary,
    TransactionService,
)
from financial_bot.app.storage.repositories.user_repository import UserRepository

router = Router(name=__name__)

ADD_EXPENSE_ALIASES = {
    "добавить расход",
    "новый расход",
    "расход",
}
CANCEL_ALIASES = {"отмена", "отменить", "cancel"}
EXPENSE_DRAFT_TTL_SECONDS = 15 * 60


@dataclass(frozen=True, slots=True)
class ExpenseDraft:
    amount: int
    raw_text: str | None
    token: str
    payer_role: str | None
    scope: TransactionScope


class ExpenseEntryState(StatesGroup):
    waiting_for_category = State()


class TransactionEditState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_category = State()
    waiting_for_date = State()
    waiting_for_payer = State()
    waiting_for_comment = State()


@router.message(F.text.func(lambda text: _is_add_expense_menu_text(text)))
async def add_expense_menu_selected(message: Message) -> None:
    await message.answer("Введите сумму расхода, например 3500. Можно сразу с категорией: 3500 2.")


def _is_add_expense_menu_text(text: str) -> bool:
    normalized = text.strip().lower()
    normalized = normalized.removeprefix("➕").strip()
    normalized = normalized.removeprefix("+").strip()
    return normalized in ADD_EXPENSE_ALIASES


@router.message(Command("cancel"))
async def cancel_command(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущий ввод отменён.")


@router.message(F.text.func(lambda text: _is_cancel_text(text)))
async def cancel_text_alias(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Текущий ввод отменён.")


def _is_cancel_text(text: str) -> bool:
    normalized = text.strip().lower()
    normalized = normalized.removeprefix("↩️").strip()
    return normalized in CANCEL_ALIASES


def _is_amount_category_number_text(text: str) -> bool:
    try:
        parse_amount_with_category_number(text)
    except ValueError:
        return False
    return True


@router.message(TransactionEditState.waiting_for_amount, F.text)
async def edit_amount_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    transaction_id = await _get_edit_transaction_id(state)
    if transaction_id is None or message.text is None:
        await state.clear()
        await message.answer("Черновик редактирования устарел.")
        return

    try:
        amount = parse_amount_to_minor_units(message.text)
        summary = await TransactionService(session, settings).update_transaction(
            transaction_id=transaction_id,
            changed_by_telegram_id=telegram_user_id,
            amount=amount,
        )
    except ValueError as exc:
        await message.answer(f"Не смог изменить сумму: {exc}")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await state.clear()
    await _answer_transaction_updated(message, summary)
    await _answer_threshold_alerts(message, session, settings, [summary.id])


@router.message(TransactionEditState.waiting_for_category, F.text)
async def edit_category_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    transaction_id = await _get_edit_transaction_id(state)
    if transaction_id is None or message.text is None:
        await state.clear()
        await message.answer("Черновик редактирования устарел.")
        return

    try:
        category_sort_order = parse_category_number(message.text)
        summary = await TransactionService(session, settings).update_transaction(
            transaction_id=transaction_id,
            changed_by_telegram_id=telegram_user_id,
            category_sort_order=category_sort_order,
        )
    except ValueError as exc:
        await message.answer(f"Не смог изменить категорию: {exc}")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await state.clear()
    await _answer_transaction_updated(message, summary)
    await _answer_threshold_alerts(message, session, settings, [summary.id])


@router.message(TransactionEditState.waiting_for_date, F.text)
async def edit_date_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    transaction_id = await _get_edit_transaction_id(state)
    if transaction_id is None or message.text is None:
        await state.clear()
        await message.answer("Черновик редактирования устарел.")
        return

    try:
        occurred_at = _parse_edit_date(message.text, settings.timezone)
        summary = await TransactionService(session, settings).update_transaction(
            transaction_id=transaction_id,
            changed_by_telegram_id=telegram_user_id,
            occurred_at=occurred_at,
        )
    except ValueError as exc:
        await message.answer(f"Не смог изменить дату: {exc}")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await state.clear()
    await _answer_transaction_updated(message, summary)
    await _answer_threshold_alerts(message, session, settings, [summary.id])


@router.message(TransactionEditState.waiting_for_payer, F.text)
async def edit_payer_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    transaction_id = await _get_edit_transaction_id(state)
    if transaction_id is None or message.text is None:
        await state.clear()
        await message.answer("Черновик редактирования устарел.")
        return

    try:
        payer_role = _parse_payer_role(message.text)
        summary = await TransactionService(session, settings).update_transaction(
            transaction_id=transaction_id,
            changed_by_telegram_id=telegram_user_id,
            payer_role=payer_role,
        )
    except ValueError as exc:
        await message.answer(f"Не смог изменить плательщика: {exc}")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await state.clear()
    await _answer_transaction_updated(message, summary)


@router.message(TransactionEditState.waiting_for_comment, F.text)
async def edit_comment_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    transaction_id = await _get_edit_transaction_id(state)
    if transaction_id is None or message.text is None:
        await state.clear()
        await message.answer("Черновик редактирования устарел.")
        return

    comment = None if message.text.strip() in {"-", "—"} else message.text
    try:
        summary = await TransactionService(session, settings).update_transaction(
            transaction_id=transaction_id,
            changed_by_telegram_id=telegram_user_id,
            comment=comment,
        )
    except ValueError as exc:
        await message.answer(f"Не смог изменить комментарий: {exc}")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await state.clear()
    await _answer_transaction_updated(message, summary)


@router.message(Command("undo"))
async def undo_last_transaction(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    summary = await TransactionService(session, settings).undo_last_transaction(
        changed_by_telegram_id=telegram_user_id
    )
    if summary is None:
        await message.answer("Нет операции для отмены.")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await message.answer(format_transaction_deleted(summary))


@router.message(Command("repeat"))
async def repeat_last_transaction(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    summary = await TransactionService(session, settings).repeat_last_transaction(
        changed_by_telegram_id=telegram_user_id
    )
    if summary is None:
        await message.answer("Нет операции для повтора.")
        return

    if not await _commit_or_answer_message(message, session):
        return
    await message.answer(
        format_transaction_repeated(summary),
        reply_markup=build_transaction_actions_keyboard(summary.id),
    )
    await _answer_threshold_alerts(message, session, settings, [summary.id])


@router.message(Command("edit"))
async def edit_last_transaction(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    summary = await TransactionService(session, settings).get_latest_transaction_for_user(
        telegram_id=telegram_user_id
    )
    if summary is None:
        await message.answer("Нет операции для редактирования.")
        return

    await message.answer(
        format_transaction_for_edit(summary),
        reply_markup=build_transaction_actions_keyboard(summary.id),
    )


@router.message(F.text.regexp(r"(?s).*\n.*"))
async def batch_expenses_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if message.text is None:
        return

    transaction_service = TransactionService(session, settings)
    result = await transaction_service.create_batch_from_text(
        text=message.text,
        current_payer_telegram_id=telegram_user_id,
    )
    transaction_ids = [summary.id for summary in result.created]
    if transaction_ids and not await _commit_or_answer_message(message, session):
        return
    if transaction_ids:
        await state.update_data(last_batch_transaction_ids=transaction_ids)

    await message.answer(
        format_batch_created(result, settings.default_currency),
        reply_markup=build_batch_keyboard() if transaction_ids else None,
    )
    await _answer_threshold_alerts(message, session, settings, transaction_ids)


@router.message(ExpenseEntryState.waiting_for_category, F.text.regexp(CATEGORY_NUMBER_ONLY_RE))
async def category_number_entered_for_draft(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if message.text is None:
        return

    state_data = await state.get_data()
    draft = await _expense_draft_from_state(state, state_data)
    if draft is None:
        await message.answer("Черновик устарел. Введите сумму заново.")
        return

    category_sort_order = parse_category_number(message.text)
    transaction_service = TransactionService(session, settings)
    summary = await transaction_service.create_from_category_sort_order(
        amount=draft.amount,
        category_sort_order=category_sort_order,
        payer_telegram_id=telegram_user_id,
        raw_text=draft.raw_text,
        payer_role=draft.payer_role,
        scope=draft.scope,
    )
    if not await _commit_or_answer_message(message, session):
        return
    await state.clear()
    await message.answer(
        format_transaction_created(summary),
        reply_markup=build_transaction_actions_keyboard(summary.id),
    )
    await _answer_threshold_alerts(message, session, settings, [summary.id])


@router.message(F.text.func(lambda text: _is_amount_category_number_text(text)))
async def amount_and_category_number_entered(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if message.text is None:
        return

    parsed_input = parse_amount_with_category_number(message.text)
    transaction_service = TransactionService(session, settings)
    summary = await transaction_service.create_from_category_sort_order(
        amount=parsed_input.amount,
        category_sort_order=parsed_input.category_sort_order,
        payer_telegram_id=telegram_user_id,
        raw_text=message.text,
        comment=parsed_input.comment or None,
        payer_role=parsed_input.payer_role.value if parsed_input.payer_role is not None else None,
        scope=parsed_input.scope,
    )
    if not await _commit_or_answer_message(message, session):
        return
    await message.answer(
        format_transaction_created(summary),
        reply_markup=build_transaction_actions_keyboard(summary.id),
    )
    await _answer_threshold_alerts(message, session, settings, [summary.id])


@router.message(F.text.regexp(CATEGORY_NUMBER_ONLY_RE))
async def category_number_without_draft(message: Message) -> None:
    await message.answer("Сначала введите сумму, например: 3500.")


@router.message(F.text.func(lambda text: is_amount_draft_text(text)))
async def amount_entered(
    message: Message,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
) -> None:
    if message.text is None:
        return

    parsed_amount = parse_amount_draft(message.text)
    amount = parsed_amount.amount
    transaction_service = TransactionService(session, settings)
    categories = await transaction_service.list_category_options()
    if not categories:
        await message.answer("Категории не найдены. Сначала выполните seed.")
        return

    draft_token = uuid4().hex
    await state.set_state(ExpenseEntryState.waiting_for_category)
    await state.update_data(
        amount=amount,
        raw_text=message.text,
        draft_token=draft_token,
        draft_created_at=_utc_timestamp(),
        draft_payer_role=parsed_amount.payer_role.value
        if parsed_amount.payer_role is not None
        else None,
        draft_scope=parsed_amount.scope.value,
    )
    context_lines = [
        format_money_minor(amount, settings.default_currency),
        f"Контур: {scope_label(parsed_amount.scope)}",
    ]
    if parsed_amount.payer_role is not None:
        context_lines.append(f"Плательщик: {_role_label(parsed_amount.payer_role.value)}")

    await message.answer(
        "\n".join([*context_lines, "", "Выберите категорию. Черновик будет действовать 15 минут."]),
        reply_markup=build_category_keyboard(categories, draft_token=draft_token),
    )


@router.callback_query(
    ExpenseEntryState.waiting_for_category,
    F.data.startswith(CATEGORY_CALLBACK_PREFIX),
)
async def category_selected(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if callback.data is None:
        await callback.answer("Не удалось прочитать категорию.")
        return

    parsed_callback = parse_category_callback_data(callback.data)
    if parsed_callback is None:
        await state.clear()
        await callback.answer("Кнопка устарела. Введите сумму заново.", show_alert=True)
        return
    callback_draft_token, category_id = parsed_callback

    state_data = await state.get_data()
    draft = await _expense_draft_from_state(state, state_data)
    if draft is None:
        await callback.answer("Черновик устарел. Введите сумму заново.", show_alert=True)
        return
    if draft.token != callback_draft_token:
        await callback.answer(
            "Эта кнопка от старого ввода. Используйте последнюю клавиатуру.",
            show_alert=True,
        )
        return

    transaction_service = TransactionService(session, settings)
    summary = await transaction_service.create_from_category_selection(
        amount=draft.amount,
        category_id=category_id,
        payer_telegram_id=telegram_user_id,
        raw_text=draft.raw_text,
        payer_role=draft.payer_role,
        scope=draft.scope,
    )
    if not await _commit_or_answer_callback(callback, session):
        return
    await state.clear()
    await callback.answer("Сохранено")

    if callback.message is not None:
        await callback.message.answer(
            format_transaction_created(summary),
            reply_markup=build_transaction_actions_keyboard(summary.id),
        )
        await _answer_threshold_alerts(
            callback.message,
            session,
            settings,
            [summary.id],
        )


@router.callback_query(ExpenseEntryState.waiting_for_category, F.data == CATEGORY_CANCEL_CALLBACK)
async def cancel_expense_draft_callback(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.answer("Отменено")
    if callback.message is not None:
        await callback.message.answer("Ввод расхода отменён.")


@router.callback_query(F.data.startswith(CATEGORY_CALLBACK_PREFIX))
async def category_selected_without_draft(callback: CallbackQuery) -> None:
    await callback.answer("Черновик не найден. Введите сумму заново.", show_alert=True)


@router.callback_query(F.data == CATEGORY_CANCEL_CALLBACK)
async def cancel_expense_draft_without_state(callback: CallbackQuery) -> None:
    await callback.answer("Черновик уже не активен.", show_alert=True)


@router.callback_query(F.data == BATCH_CANCEL_CALLBACK)
async def cancel_last_batch(
    callback: CallbackQuery,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    state_data = await state.get_data()
    transaction_ids = state_data.get("last_batch_transaction_ids")
    if not isinstance(transaction_ids, list) or not transaction_ids:
        await callback.answer("Нет операций для отмены.")
        return

    transaction_service = TransactionService(session, settings)
    deleted_count = await transaction_service.cancel_transactions(
        [item for item in transaction_ids if isinstance(item, int)],
        changed_by_telegram_id=telegram_user_id,
    )
    if not await _commit_or_answer_callback(callback, session):
        return
    await state.update_data(last_batch_transaction_ids=[])
    await callback.answer("Отменено")

    if callback.message is not None:
        await callback.message.answer(f"Отменил операций: {deleted_count}")


@router.callback_query(TransactionActionCallback.filter())
async def transaction_action_selected(
    callback: CallbackQuery,
    callback_data: TransactionActionCallback,
    state: FSMContext,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    transaction_id = callback_data.transaction_id
    action = callback_data.action
    if action == TransactionAction.DELETE:
        try:
            summary = await TransactionService(session, settings).delete_transaction(
                transaction_id=transaction_id,
                changed_by_telegram_id=telegram_user_id,
            )
        except ValueError as exc:
            await callback.answer(f"Не удалось удалить: {exc}", show_alert=True)
            return

        if not await _commit_or_answer_callback(callback, session):
            return
        await callback.answer("Удалено")
        if callback.message is not None:
            await callback.message.answer(format_transaction_deleted(summary))
        return

    await state.update_data(edit_transaction_id=transaction_id)
    await _set_edit_state(action, state)
    await callback.answer()

    if callback.message is not None:
        await callback.message.answer(
            await _edit_prompt(action, TransactionService(session, settings))
        )


@router.message(F.text, ~F.text.startswith("/"))
async def free_text_expense_entered(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    if message.text is None:
        return

    transaction_service = TransactionService(session, settings)
    try:
        summary = await transaction_service.create_from_free_text(
            text=message.text,
            current_payer_telegram_id=telegram_user_id,
        )
    except ValueError as exc:
        await message.answer(_format_free_text_expense_error(exc))
        return

    if not await _commit_or_answer_message(message, session):
        return
    await message.answer(
        format_transaction_created(summary),
        reply_markup=build_transaction_actions_keyboard(summary.id),
    )
    await _answer_threshold_alerts(message, session, settings, [summary.id])


async def _commit_or_answer_message(message: Message, session: AsyncSession) -> bool:
    try:
        await commit_or_rollback(session, context="expense mutation")
    except Exception:
        await message.answer("Не смог сохранить изменения. Попробуйте ещё раз.")
        return False
    return True


async def _commit_or_answer_callback(callback: CallbackQuery, session: AsyncSession) -> bool:
    try:
        await commit_or_rollback(session, context="expense callback mutation")
    except Exception:
        await callback.answer("Не смог сохранить изменения. Попробуйте ещё раз.", show_alert=True)
        return False
    return True


async def _answer_threshold_alerts(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    transaction_ids: list[int],
) -> None:
    if not transaction_ids:
        return

    try:
        service = SpendingLimitService(session, settings)
        recipients = await UserRepository(session).list_active()
        for transaction_id in transaction_ids:
            for recipient in recipients:
                alerts = await service.evaluate_transaction_threshold_alerts(
                    transaction_id=transaction_id,
                    recipient_telegram_id=recipient.telegram_id,
                )
                for alert in alerts:
                    await message.bot.send_message(
                        recipient.telegram_id,
                        format_threshold_alert(alert, settings.default_currency),
                    )
        await commit_or_rollback(session, context="expense threshold alerts")
    except Exception:
        await rollback_after_secondary_failure(session, context="expense threshold alerts")


async def _get_edit_transaction_id(state: FSMContext) -> int | None:
    state_data = await state.get_data()
    transaction_id = state_data.get("edit_transaction_id")
    return transaction_id if isinstance(transaction_id, int) else None


async def _answer_transaction_updated(
    message: Message,
    summary: CreatedTransactionSummary,
) -> None:
    await message.answer(
        format_transaction_updated(summary),
        reply_markup=build_transaction_actions_keyboard(summary.id),
    )


async def _set_edit_state(action: TransactionAction, state: FSMContext) -> None:
    match action:
        case TransactionAction.AMOUNT:
            await state.set_state(TransactionEditState.waiting_for_amount)
        case TransactionAction.CATEGORY:
            await state.set_state(TransactionEditState.waiting_for_category)
        case TransactionAction.DATE:
            await state.set_state(TransactionEditState.waiting_for_date)
        case TransactionAction.PAYER:
            await state.set_state(TransactionEditState.waiting_for_payer)
        case TransactionAction.COMMENT:
            await state.set_state(TransactionEditState.waiting_for_comment)
        case TransactionAction.DELETE:
            return


async def _edit_prompt(action: TransactionAction, service: TransactionService) -> str:
    match action:
        case TransactionAction.AMOUNT:
            return "Введите новую сумму."
        case TransactionAction.CATEGORY:
            categories = await service.list_category_options()
            return "\n".join(["Введите номер категории:", *_format_category_options(categories)])
        case TransactionAction.DATE:
            return "Введите дату: ДД.ММ.ГГГГ или YYYY-MM-DD."
        case TransactionAction.PAYER:
            return "Введите плательщика: м или ж."
        case TransactionAction.COMMENT:
            return "Введите комментарий. Чтобы очистить, отправьте -"
        case TransactionAction.DELETE:
            return "Удаление уже выполнено."


def _format_category_options(categories: list[CategoryOption]) -> list[str]:
    return [f"{category.sort_order}. {category.title}" for category in categories]


def _format_free_text_expense_error(error: ValueError) -> str:
    message = str(error)
    if message == "Invalid free-text expense input":
        return "Не смог разобрать расход. Напишите сумму и категорию."
    return f"Не смог разобрать расход: {message}"


async def _expense_draft_from_state(
    state: FSMContext,
    state_data: dict,
) -> ExpenseDraft | None:
    amount = state_data.get("amount")
    raw_text = state_data.get("raw_text")
    draft_token = state_data.get("draft_token")
    draft_created_at = state_data.get("draft_created_at")
    draft_payer_role = state_data.get("draft_payer_role")
    draft_scope = state_data.get("draft_scope")

    if (
        not isinstance(amount, int)
        or not isinstance(draft_token, str)
        or not isinstance(draft_created_at, int | float)
    ):
        await state.clear()
        return None

    if _utc_timestamp() - float(draft_created_at) > EXPENSE_DRAFT_TTL_SECONDS:
        await state.clear()
        return None

    try:
        scope = TransactionScope(draft_scope or TransactionScope.HOUSEHOLD.value)
    except ValueError:
        await state.clear()
        return None

    return ExpenseDraft(
        amount=amount,
        raw_text=raw_text if isinstance(raw_text, str) else None,
        token=draft_token,
        payer_role=draft_payer_role if isinstance(draft_payer_role, str) else None,
        scope=scope,
    )


def _utc_timestamp() -> int:
    return int(datetime.now(UTC).timestamp())


def _parse_edit_date(text: str, timezone: str) -> datetime:
    normalized = text.strip().lower()
    if normalized in {"сегодня", "today"}:
        current = datetime.now(ZoneInfo(timezone))
        return current.replace(hour=0, minute=0, second=0, microsecond=0)

    for date_format in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            parsed_date = datetime.strptime(normalized, date_format).date()
        except ValueError:
            continue
        return datetime.combine(parsed_date, time.min, tzinfo=ZoneInfo(timezone))

    msg = "дата должна быть в формате ДД.ММ.ГГГГ или YYYY-MM-DD"
    raise ValueError(msg)


def _parse_payer_role(text: str) -> str:
    normalized = text.strip().lower()
    aliases = {
        "м": UserRole.HUSBAND.value,
        "муж": UserRole.HUSBAND.value,
        "husband": UserRole.HUSBAND.value,
        "h": UserRole.HUSBAND.value,
        "ж": UserRole.WIFE.value,
        "жена": UserRole.WIFE.value,
        "wife": UserRole.WIFE.value,
        "w": UserRole.WIFE.value,
    }
    if normalized not in aliases:
        msg = "плательщик должен быть м или ж"
        raise ValueError(msg)
    return aliases[normalized]


def _role_label(role: str) -> str:
    labels = {
        UserRole.HUSBAND.value: "Муж",
        UserRole.WIFE.value: "Жена",
    }
    return labels.get(role, role)
