from financial_bot.app.domain.money import format_money_minor
from financial_bot.app.domain.types import (
    BankEventOperationKind,
    BankEventParseStatus,
    BankEventSuggestionSource,
)
from financial_bot.app.services.bank_ingestion_service import (
    BankEventConfirmationResult,
    BankEventUpdateResult,
    BankImportResult,
)
from financial_bot.app.services.bank_learning_service import BankLearningRuleFeedback

OPERATION_LABELS = {
    BankEventOperationKind.EXPENSE_CANDIDATE: "расход-кандидат",
    BankEventOperationKind.INCOME: "поступление",
    BankEventOperationKind.INTERNAL_TRANSFER: "внутренний перевод, не расход",
    BankEventOperationKind.REFUND: "возврат",
    BankEventOperationKind.IGNORED: "служебное сообщение",
    BankEventOperationKind.UNKNOWN: "неизвестный формат",
}
STATUS_LABELS = {
    BankEventParseStatus.IGNORED: "проигнорировано",
    BankEventParseStatus.PARSED: "разобрано",
    BankEventParseStatus.NEEDS_CONFIRMATION: "нужно подтверждение",
    BankEventParseStatus.CONFIRMED: "подтверждено",
    BankEventParseStatus.REJECTED: "отклонено",
    BankEventParseStatus.AUTOSAVED: "сохранено автоматически",
}
SUGGESTION_SOURCE_LABELS = {
    BankEventSuggestionSource.PARSER_HINT: "по SMS-подсказке",
    BankEventSuggestionSource.LEARNED_RULE: "по прошлым подтверждениям",
    BankEventSuggestionSource.MANUAL: "выбрана вручную",
    BankEventSuggestionSource.NONE: "",
}
AUTOSAVE_AFTER_NEXT_CONFIRMATION_TEXT = (
    "Если подтвердите похожее SMS ещё раз, начну записывать такие расходы автоматически."
)


def format_bank_import_result(result: BankImportResult) -> str:
    if result.parse_status == BankEventParseStatus.AUTOSAVED:
        return format_bank_event_autosaved(result)

    header = "Уже видел это SMS:" if result.is_duplicate else "Разобрал банковское SMS:"
    lines = [
        header,
        f"Событие: #{result.event_id}",
        f"Банк: {result.bank.value}",
        f"Тип: {OPERATION_LABELS[result.operation_kind]}",
        f"Статус: {STATUS_LABELS[result.parse_status]}",
    ]

    if result.amount is not None:
        lines.append(f"Сумма: {format_money_minor(result.amount, result.currency)}")
    if result.fee_amount:
        lines.append(f"Комиссия: {format_money_minor(result.fee_amount, result.currency)}")
    if result.merchant:
        lines.append(f"Мерчант: {result.merchant}")
    if result.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER:
        lines.append("Контрагент: свой счёт")
    if result.suggested_category_title:
        category_line = f"Категория-кандидат: {result.suggested_category_title}"
        source_label = SUGGESTION_SOURCE_LABELS[result.suggested_category_source]
        if source_label:
            category_line += f" ({source_label})"
        lines.append(category_line)
    if result.ignore_reason:
        lines.append(f"Причина: {result.ignore_reason}")

    if result.operation_kind == BankEventOperationKind.INCOME:
        lines.extend(
            [
                "",
                "Это поступление. Пока не записываю его в доходы.",
                "Если это семейный доход, нажмите «Учесть доход». "
                "В расходные лимиты и графики категорий он не попадёт.",
            ]
        )
    elif result.operation_kind == BankEventOperationKind.REFUND:
        lines.extend(
            [
                "",
                "Это возврат, не новый доход и не расход. Без подтверждения расходы не меняю. "
                "Можно учесть возврат как корректировку выбранной категории.",
            ]
        )

    if result.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION:
        lines.append("")
        lines.append("Пока не записываю в расходы. Нажмите кнопку ниже.")

    return "\n".join(lines)


def format_bank_event_confirmed(result: BankEventConfirmationResult) -> str:
    if result.already_confirmed:
        return "✅ Этот расход уже был учтён."
    if result.transaction is None:
        return "✅ Банковское SMS обработано."

    lines = [
        "✅ Записал расход:",
        (
            f"{format_money_minor(result.transaction.amount, result.transaction.currency)} — "
            f"{result.transaction.category_title}"
        ),
        "Статус: подтверждено",
    ]
    if result.learning_rule is not None:
        lines.extend(("", *_format_learning_rule_feedback(result.learning_rule)))
    return "\n".join(lines)


def format_bank_event_refund_corrected(result: BankEventConfirmationResult) -> str:
    if result.already_confirmed:
        return "↩️ Этот возврат уже был учтён."
    if result.transaction is None:
        return "↩️ Возврат обработан."

    return "\n".join(
        [
            "↩️ Учёл возврат:",
            (
                f"-{format_money_minor(result.transaction.amount, result.transaction.currency)} — "
                f"{result.transaction.category_title}"
            ),
            "Статус: подтверждено",
        ]
    )


def format_bank_event_income_confirmed(result: BankEventConfirmationResult) -> str:
    if result.already_confirmed:
        return "✅ Это поступление уже было учтено."
    if result.transaction is None:
        return "✅ Поступление обработано."

    return "\n".join(
        [
            "✅ Учёл доход:",
            (
                f"+{format_money_minor(result.transaction.amount, result.transaction.currency)} — "
                f"{result.transaction.category_title}"
            ),
            "В расходы, лимиты и графики категорий не входит.",
        ]
    )


def format_bank_event_autosaved(result: BankImportResult) -> str:
    amount_line = _money_category_line(
        amount=result.amount,
        currency=result.currency,
        category_title=result.suggested_category_title,
    )
    lines = [
        "✅ Записал автоматически:",
        amount_line,
        "Основание: правило по прошлым подтверждениям.",
        "Если это ошибка, исправьте кнопками ниже.",
    ]
    if result.merchant:
        lines.append(f"Мерчант: {result.merchant}")
    return "\n".join(lines)


def format_bank_event_rejected(result: BankEventUpdateResult) -> str:
    return "\n".join(["🚫 Не учитываю:", _event_update_amount_line(result)])


def format_bank_event_internal_transfer(result: BankEventUpdateResult) -> str:
    return "\n".join(
        [
            "🔁 Перевод себе:",
            _event_update_amount_line(result),
            "Статус: не входит в расходы.",
        ]
    )


def format_bank_event_category_updated(result: BankEventUpdateResult) -> str:
    category = result.suggested_category_title or "не выбрана"
    if result.parse_status == BankEventParseStatus.AUTOSAVED:
        next_step = "Автозаписанный расход уже исправлен."
    elif result.operation_kind == BankEventOperationKind.REFUND:
        next_step = "Теперь можно учесть возврат."
    else:
        next_step = "Теперь можно подтвердить расход."
    return "\n".join(
        [
            "🏷 Категория обновлена:",
            _money_category_line(
                amount=result.amount,
                currency=result.currency,
                category_title=category,
            ),
            next_step,
        ]
    )


def format_bank_event_rule_disabled(result: BankEventUpdateResult) -> str:
    return "\n".join(
        [
            "🚫 Правило автоучёта отключено:",
            _event_update_amount_line(result),
            "Записанный расход не изменил.",
        ]
    )


def _money_category_line(
    *,
    amount: int | None,
    currency: str,
    category_title: str | None,
) -> str:
    money = format_money_minor(amount, currency) if amount is not None else "сумма не указана"
    category = category_title or "категория не выбрана"
    return f"{money} — {category}"


def _event_update_amount_line(result: BankEventUpdateResult) -> str:
    if result.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER:
        return _money_category_line(
            amount=result.amount,
            currency=result.currency,
            category_title="перевод себе",
        )
    if result.suggested_category_title:
        return _money_category_line(
            amount=result.amount,
            currency=result.currency,
            category_title=result.suggested_category_title,
        )
    if result.merchant:
        return _money_category_line(
            amount=result.amount,
            currency=result.currency,
            category_title=result.merchant,
        )
    return _money_category_line(
        amount=result.amount,
        currency=result.currency,
        category_title="не записано",
    )


def _format_learning_rule_feedback(feedback: BankLearningRuleFeedback) -> tuple[str, str]:
    if feedback.action == "created":
        headline = (
            f"Запомнил для будущих SMS: {feedback.merchant_display} → {feedback.category_title}."
        )
        detail = AUTOSAVE_AFTER_NEXT_CONFIRMATION_TEXT
    elif feedback.action == "reinforced":
        headline = (
            "Укрепил правило: "
            f"{feedback.merchant_display} → {feedback.category_title}. "
            f"Подтверждений: {feedback.hit_count}."
        )
        detail = (
            "Следующие похожие SMS будут записываться автоматически."
            if feedback.hit_count >= 2
            else AUTOSAVE_AFTER_NEXT_CONFIRMATION_TEXT
        )
    else:
        headline = (
            "Обновил правило для будущих SMS: "
            f"{feedback.merchant_display} → {feedback.category_title}."
        )
        detail = AUTOSAVE_AFTER_NEXT_CONFIRMATION_TEXT
    return (headline, detail)
