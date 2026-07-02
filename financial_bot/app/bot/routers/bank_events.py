from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.bank_events import (
    format_bank_event_category_updated,
    format_bank_event_confirmed,
    format_bank_event_income_confirmed,
    format_bank_event_internal_transfer,
    format_bank_event_refund_corrected,
    format_bank_event_rejected,
    format_bank_event_rule_disabled,
    format_bank_event_scope_updated,
    format_bank_import_result,
)
from financial_bot.app.bot.formatters.spending_limits import format_threshold_alert
from financial_bot.app.bot.keyboards.bank_events import (
    BankEventAction,
    BankEventActionCallback,
    BankEventCategoryCallback,
    build_bank_autosaved_actions_keyboard,
    build_bank_event_actions_keyboard,
    build_bank_event_category_keyboard,
    build_bank_income_actions_keyboard,
    build_bank_refund_actions_keyboard,
)
from financial_bot.app.bot.session_safety import (
    commit_or_rollback,
    rollback_after_secondary_failure,
)
from financial_bot.app.config import Settings
from financial_bot.app.domain.types import (
    BankEventOperationKind,
    BankEventParseStatus,
    TransactionScope,
)
from financial_bot.app.services.bank_ingestion_service import BankIngestionService
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.storage.repositories.user_repository import UserRepository

router = Router(name=__name__)


@router.message(Command("bank"))
async def bank_sms_import_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    sms_text = _command_payload(message)
    if not sms_text:
        await message.answer("Используйте: /bank текст банковского SMS или /bank pending")
        return
    if _is_pending_command_payload(sms_text):
        await answer_pending_bank_events(message, session, settings, telegram_user_id)
        return

    try:
        result = await BankIngestionService(session, settings).import_manual_sms(
            text=sms_text,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        await message.answer(f"Не смог разобрать банковское SMS: {exc}")
        return

    if not await _commit_or_answer_message(message, session, "Не смог сохранить банковское SMS."):
        return
    await message.answer(
        format_bank_import_result(result),
        reply_markup=_bank_result_reply_markup(result),
    )
    if result.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION:
        await _mark_notification_sent_safely(
            BankIngestionService(session, settings),
            session,
            event_id=result.event_id,
        )


@router.message(Command("bank_pending"))
async def bank_pending_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    await answer_pending_bank_events(message, session, settings, telegram_user_id)


@router.message(F.text.func(lambda text: _is_pending_command_payload(text)))
async def bank_pending_text_alias(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    await answer_pending_bank_events(message, session, settings, telegram_user_id)


@router.callback_query(BankEventActionCallback.filter())
async def bank_event_action_selected(
    callback: CallbackQuery,
    callback_data: BankEventActionCallback,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    service = BankIngestionService(session, settings)
    event_id = callback_data.event_id

    if callback_data.action == BankEventAction.CONFIRM:
        await _confirm_bank_event(callback, service, session, settings, telegram_user_id, event_id)
        return

    if callback_data.action == BankEventAction.REFUND_CORRECTION:
        await _create_refund_correction(callback, service, session, telegram_user_id, event_id)
        return

    if callback_data.action == BankEventAction.INCOME_CONFIRM:
        await _confirm_income_event(callback, service, session, telegram_user_id, event_id)
        return

    if callback_data.action == BankEventAction.CHANGE_CATEGORY:
        await _answer_category_selection(callback, service, event_id)
        return

    if callback_data.action in {
        BankEventAction.SCOPE_HOUSEHOLD,
        BankEventAction.SCOPE_SALON,
    }:
        scope = (
            TransactionScope.SALON
            if callback_data.action == BankEventAction.SCOPE_SALON
            else TransactionScope.HOUSEHOLD
        )
        try:
            result = await service.update_event_scope(
                event_id=event_id,
                scope=scope,
                telegram_user_id=telegram_user_id,
            )
        except ValueError as exc:
            await _clear_callback_keyboard(callback)
            await callback.answer(str(exc), show_alert=True)
            return

        if not await _commit_or_answer_callback(callback, session):
            return
        await callback.answer("Контур обновлён")
        if callback.message is not None:
            await _replace_callback_message(
                callback,
                format_bank_event_scope_updated(result),
                reply_markup=_bank_update_reply_markup(result),
            )
        return

    if callback_data.action == BankEventAction.IGNORE:
        try:
            result = await service.reject_event(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
            )
        except ValueError as exc:
            await _clear_callback_keyboard(callback)
            await callback.answer(str(exc), show_alert=True)
            return

        if not await _commit_or_answer_callback(callback, session):
            return
        await callback.answer("Не учитываю")
        if callback.message is not None:
            await _replace_callback_message(
                callback,
                format_bank_event_rejected(result),
            )
        return

    if callback_data.action == BankEventAction.INTERNAL_TRANSFER:
        try:
            result = await service.mark_event_internal_transfer(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
            )
        except ValueError as exc:
            await _clear_callback_keyboard(callback)
            await callback.answer(str(exc), show_alert=True)
            return

        if not await _commit_or_answer_callback(callback, session):
            return
        await callback.answer("Отмечено")
        if callback.message is not None:
            await _replace_callback_message(
                callback,
                format_bank_event_internal_transfer(result),
            )
        return

    if callback_data.action == BankEventAction.DISABLE_RULE:
        try:
            result = await service.disable_autosave_rule_for_event(
                event_id=event_id,
                telegram_user_id=telegram_user_id,
            )
        except ValueError as exc:
            await _clear_callback_keyboard(callback)
            await callback.answer(str(exc), show_alert=True)
            return

        if not await _commit_or_answer_callback(callback, session):
            return
        await callback.answer("Правило отключено")
        if callback.message is not None:
            await _replace_callback_message(
                callback,
                format_bank_event_rule_disabled(result),
                reply_markup=build_bank_autosaved_actions_keyboard(result.event_id),
            )


@router.callback_query(BankEventCategoryCallback.filter())
async def bank_event_category_selected(
    callback: CallbackQuery,
    callback_data: BankEventCategoryCallback,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    service = BankIngestionService(session, settings)
    try:
        result = await service.update_event_category(
            event_id=callback_data.event_id,
            category_id=callback_data.category_id,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        await _clear_callback_keyboard(callback)
        await callback.answer(str(exc), show_alert=True)
        return

    if not await _commit_or_answer_callback(callback, session):
        return
    await callback.answer("Категория обновлена")
    if callback.message is not None:
        await _replace_callback_message(
            callback,
            format_bank_event_category_updated(result),
            reply_markup=_bank_update_reply_markup(result),
        )


def _command_payload(message: Message) -> str:
    if message.text is None:
        return ""
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()


def _is_pending_command_payload(payload: str) -> bool:
    normalized = payload.strip().lower()
    return normalized in {
        "pending",
        "ожидающие",
        "очередь",
        "ожидают подтверждения",
        "⏳ ожидают подтверждения",
    }


async def answer_pending_bank_events(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
) -> None:
    service = BankIngestionService(session, settings)
    try:
        pending_events = await service.list_pending_confirmation_events(
            telegram_user_id=telegram_user_id,
            limit=10,
        )
    except ValueError as exc:
        await message.answer(str(exc))
        return

    if not pending_events:
        await message.answer("Ожидающих банковских событий нет.")
        return

    await message.answer(f"Ожидают подтверждения: {len(pending_events)}. Отправляю карточки ниже.")
    for result in pending_events:
        await message.answer(
            format_bank_import_result(result),
            reply_markup=build_bank_event_actions_keyboard(
                result.event_id,
                can_confirm=(
                    result.creates_expense_candidate and result.suggested_category_code is not None
                ),
            ),
        )
        await _mark_notification_sent_safely(service, session, event_id=result.event_id)


async def _confirm_bank_event(
    callback: CallbackQuery,
    service: BankIngestionService,
    session: AsyncSession,
    settings: Settings,
    telegram_user_id: int,
    event_id: int,
) -> None:
    try:
        result = await service.confirm_event(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        if str(exc) == "Сначала выберите категорию":
            await _answer_category_selection(
                callback,
                service,
                event_id,
                answer_text="Выберите категорию",
                show_alert=True,
            )
            return
        await _clear_callback_keyboard(callback)
        await callback.answer(str(exc), show_alert=True)
        return

    if not await _commit_or_answer_callback(callback, session):
        return
    await callback.answer("Подтверждено")
    if callback.message is not None:
        await _replace_callback_message(
            callback,
            format_bank_event_confirmed(result),
        )
        if result.transaction is not None:
            await _answer_threshold_alerts(
                callback.message,
                session,
                settings,
                [result.transaction.id],
            )


async def _create_refund_correction(
    callback: CallbackQuery,
    service: BankIngestionService,
    session: AsyncSession,
    telegram_user_id: int,
    event_id: int,
) -> None:
    try:
        result = await service.create_refund_correction(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        if str(exc) == "Сначала выберите категорию":
            await _answer_category_selection(
                callback,
                service,
                event_id,
                answer_text="Выберите категорию",
                show_alert=True,
            )
            return
        await _clear_callback_keyboard(callback)
        await callback.answer(str(exc), show_alert=True)
        return

    if not await _commit_or_answer_callback(callback, session):
        return
    await callback.answer("Возврат учтён")
    if callback.message is not None:
        await _replace_callback_message(callback, format_bank_event_refund_corrected(result))


async def _confirm_income_event(
    callback: CallbackQuery,
    service: BankIngestionService,
    session: AsyncSession,
    telegram_user_id: int,
    event_id: int,
) -> None:
    try:
        result = await service.confirm_income_event(
            event_id=event_id,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        await _clear_callback_keyboard(callback)
        await callback.answer(str(exc), show_alert=True)
        return

    if not await _commit_or_answer_callback(callback, session):
        return
    await callback.answer("Доход учтён")
    if callback.message is not None:
        await _replace_callback_message(callback, format_bank_event_income_confirmed(result))


async def _answer_category_selection(
    callback: CallbackQuery,
    service: BankIngestionService,
    event_id: int,
    *,
    answer_text: str | None = None,
    show_alert: bool = False,
) -> None:
    categories = await service.list_expense_categories()
    await callback.answer(answer_text, show_alert=show_alert)
    if callback.message is not None:
        await _replace_callback_message(
            callback,
            f"Выберите категорию для банковского события #{event_id}.",
            reply_markup=build_bank_event_category_keyboard(
                event_id=event_id, categories=categories
            ),
        )


def _bank_result_reply_markup(result):
    if result.parse_status == BankEventParseStatus.AUTOSAVED:
        return build_bank_autosaved_actions_keyboard(result.event_id)
    if result.operation_kind == BankEventOperationKind.INCOME:
        return build_bank_income_actions_keyboard(result.event_id)
    if result.operation_kind == BankEventOperationKind.REFUND:
        return build_bank_refund_actions_keyboard(
            result.event_id,
            can_confirm=result.suggested_category_code is not None,
        )
    if result.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION:
        return build_bank_event_actions_keyboard(
            result.event_id,
            can_confirm=(
                result.creates_expense_candidate and result.suggested_category_code is not None
            ),
        )
    return None


def _bank_update_reply_markup(result):
    if result.parse_status == BankEventParseStatus.AUTOSAVED:
        return build_bank_autosaved_actions_keyboard(result.event_id)
    if result.operation_kind == BankEventOperationKind.REFUND:
        return build_bank_refund_actions_keyboard(result.event_id, can_confirm=True)
    return build_bank_event_actions_keyboard(result.event_id, can_confirm=True)


async def _commit_or_answer_message(
    message: Message,
    session: AsyncSession,
    failure_text: str,
) -> bool:
    try:
        await commit_or_rollback(session, context="bank event message mutation")
    except Exception:
        await message.answer(failure_text)
        return False
    return True


async def _commit_or_answer_callback(callback: CallbackQuery, session: AsyncSession) -> bool:
    try:
        await commit_or_rollback(session, context="bank event callback mutation")
    except Exception:
        await callback.answer("Не смог сохранить изменения. Попробуйте ещё раз.", show_alert=True)
        return False
    return True


async def _mark_notification_sent_safely(
    service: BankIngestionService,
    session: AsyncSession,
    *,
    event_id: int,
) -> None:
    try:
        await service.mark_telegram_notification_sent(event_id=event_id)
        await commit_or_rollback(session, context="bank event notification sent marker")
    except Exception:
        await rollback_after_secondary_failure(
            session,
            context="bank event notification sent marker",
        )


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
        await commit_or_rollback(session, context="bank event threshold alerts")
    except Exception:
        await rollback_after_secondary_failure(session, context="bank event threshold alerts")


async def _replace_callback_message(
    callback: CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    message = callback.message
    if message is None or not hasattr(message, "edit_text"):
        return

    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramBadRequest:
        await _clear_callback_keyboard(callback)
        if hasattr(message, "answer"):
            await message.answer(text, reply_markup=reply_markup)


async def _clear_callback_keyboard(callback: CallbackQuery) -> None:
    message = callback.message
    if message is None or not hasattr(message, "edit_reply_markup"):
        return
    try:
        await message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        return
