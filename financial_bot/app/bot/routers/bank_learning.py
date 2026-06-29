from aiogram import F, Router
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.bot.formatters.bank_learning import (
    format_bank_learning_rule_category_updated,
    format_bank_learning_rule_details,
    format_bank_learning_rule_status_updated,
    format_bank_learning_rules_list,
)
from financial_bot.app.bot.keyboards.bank_learning import (
    BankLearningAction,
    BankLearningActionCallback,
    BankLearningCategoryCallback,
    BankLearningRuleCallback,
    build_bank_learning_category_keyboard,
    build_bank_learning_rule_actions_keyboard,
    build_bank_learning_rules_keyboard,
)
from financial_bot.app.domain.types import BankCategoryRuleMode
from financial_bot.app.services.bank_learning_rule_service import BankLearningRuleService

router = Router(name=__name__)

BANK_LEARNING_RULES_ALIASES = {
    "🧠 правила категорий",
    "правила категорий",
    "правила автоучёта",
    "правила автоучета",
    "обучение",
    "🏦 банки",
    "банки",
}


@router.message(F.text.func(lambda text: text.strip().lower() in BANK_LEARNING_RULES_ALIASES))
async def bank_learning_rules_selected(
    message: Message,
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    await _answer_rules_list(message, session, telegram_user_id)


@router.callback_query(BankLearningRuleCallback.filter())
async def bank_learning_rule_selected(
    callback: CallbackQuery,
    callback_data: BankLearningRuleCallback,
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    await _answer_rule_card(callback, session, telegram_user_id, callback_data.rule_id)


@router.callback_query(BankLearningActionCallback.filter())
async def bank_learning_action_selected(
    callback: CallbackQuery,
    callback_data: BankLearningActionCallback,
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    service = BankLearningRuleService(session)

    if callback_data.action == BankLearningAction.BACK:
        await callback.answer()
        if callback.message is not None:
            await _answer_rules_list(callback.message, session, telegram_user_id)
        return

    if callback_data.action == BankLearningAction.CHANGE_CATEGORY:
        try:
            categories = await service.list_expense_categories()
            await service.get_rule_details(
                rule_id=callback_data.rule_id,
                telegram_user_id=telegram_user_id,
            )
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        await callback.answer()
        if callback.message is not None:
            await callback.message.answer(
                "Выберите новую категорию для правила автоучёта.",
                reply_markup=build_bank_learning_category_keyboard(
                    rule_id=callback_data.rule_id,
                    categories=categories,
                ),
            )
        return

    if callback_data.action in {
        BankLearningAction.SET_SUGGEST,
        BankLearningAction.SET_AUTOSAVE,
        BankLearningAction.DISABLE,
        BankLearningAction.ENABLE,
    }:
        mode = _mode_from_action(callback_data.action)
        try:
            result = await service.set_rule_mode(
                rule_id=callback_data.rule_id,
                telegram_user_id=telegram_user_id,
                mode=mode,
            )
            await session.commit()
        except ValueError as exc:
            await callback.answer(str(exc), show_alert=True)
            return

        await callback.answer("Готово")
        if callback.message is not None:
            await callback.message.answer(
                format_bank_learning_rule_status_updated(result),
                reply_markup=build_bank_learning_rule_actions_keyboard(
                    rule_id=result.rule_id,
                    mode=result.mode,
                ),
            )


@router.callback_query(BankLearningCategoryCallback.filter())
async def bank_learning_category_selected(
    callback: CallbackQuery,
    callback_data: BankLearningCategoryCallback,
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    try:
        result = await BankLearningRuleService(session).update_rule_category(
            rule_id=callback_data.rule_id,
            category_id=callback_data.category_id,
            telegram_user_id=telegram_user_id,
        )
        await session.commit()
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer("Категория обновлена")
    if callback.message is not None:
        await callback.message.answer(
            format_bank_learning_rule_category_updated(result),
            reply_markup=build_bank_learning_rule_actions_keyboard(
                rule_id=result.rule_id,
                mode=result.mode,
            ),
        )


async def _answer_rules_list(
    message: Message,
    session: AsyncSession,
    telegram_user_id: int,
) -> None:
    try:
        rules = await BankLearningRuleService(session).list_rules(telegram_user_id=telegram_user_id)
    except ValueError as exc:
        await message.answer(str(exc))
        return

    await message.answer(
        format_bank_learning_rules_list(rules),
        reply_markup=build_bank_learning_rules_keyboard(rules) if rules else None,
    )


async def _answer_rule_card(
    callback: CallbackQuery,
    session: AsyncSession,
    telegram_user_id: int,
    rule_id: int,
) -> None:
    try:
        details = await BankLearningRuleService(session).get_rule_details(
            rule_id=rule_id,
            telegram_user_id=telegram_user_id,
        )
    except ValueError as exc:
        await callback.answer(str(exc), show_alert=True)
        return

    await callback.answer()
    if callback.message is not None:
        await callback.message.answer(
            format_bank_learning_rule_details(details),
            reply_markup=build_bank_learning_rule_actions_keyboard(
                rule_id=details.id,
                mode=details.mode,
            ),
        )


def _mode_from_action(action: BankLearningAction) -> BankCategoryRuleMode:
    if action == BankLearningAction.SET_AUTOSAVE:
        return BankCategoryRuleMode.AUTOSAVE
    if action == BankLearningAction.DISABLE:
        return BankCategoryRuleMode.DISABLED
    return BankCategoryRuleMode.SUGGEST
