from datetime import datetime

from financial_bot.app.domain.types import BankCategoryRuleMode
from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealth,
    AutoAccountingRuleHealth,
    AutoAccountingSourceHealth,
    AutoAccountingUnknownShapeHealth,
)


def format_auto_accounting_health(health: AutoAccountingHealth) -> str:
    if not health.sources:
        return (
            "Состояние автоучёта\n\n"
            "Банковские источники ещё не заведены.\n"
            "Когда появится iPhone Shortcut или другой источник, он будет виден здесь."
        )

    autosave_share = _percent(health.autosaved_expense_count, health.expense_candidate_count)
    lines = [
        f"Состояние автоучёта за {health.period_days} дней",
        "",
        "Поток SMS",
        (
            f"Источники: {health.active_source_count} активных, "
            f"{health.inactive_source_count} выключенных"
        ),
        f"Всего событий: {health.total_event_count}",
        f"Расходы-кандидаты: {health.expense_candidate_count}",
        (
            "Сохранено в расходы: "
            f"{health.saved_expense_count} "
            f"(авто {health.autosaved_expense_count}, вручную {health.confirmed_expense_count})"
        ),
        f"Ждут подтверждения: {health.pending_confirmation_count}",
        (
            "Не расходы: "
            f"доходы {health.income_event_count}, "
            f"возвраты {health.refund_event_count}, "
            f"переводы себе {health.internal_transfer_event_count}"
        ),
        f"Служебные/реклама: {health.ignored_event_count}",
        f"Неизвестный формат: {health.unknown_event_count}",
        "",
        "Качество",
        f"Автосохранение расходов: {autosave_share}",
        f"Спорные подсказки категорий: {health.conflict_event_count}",
        f"Ошибки доставки в Telegram: {health.failed_telegram_notification_count}",
        f"Ещё не отправлены в Telegram: {health.unsent_pending_count}",
        "",
        "Источники:",
    ]
    for source in health.sources:
        lines.extend(["", *_format_source_block(source)])

    lines.extend(
        [
            "",
            *_format_unknown_shapes_block(health),
            "",
            *_format_rules_block(health),
            "",
            *_format_action_block(health),
        ]
    )
    return "\n".join(lines)


def _format_unknown_shapes_block(health: AutoAccountingHealth) -> list[str]:
    if health.unknown_event_count <= 0:
        return ["Неизвестные форматы:", "Нет неизвестных форматов за период."]
    if not health.unknown_shapes:
        return [
            "Неизвестные форматы:",
            "Есть неизвестные события, но безопасных признаков для группировки нет.",
        ]

    lines = ["Неизвестные форматы:"]
    for index, shape in enumerate(health.unknown_shapes, start=1):
        lines.append(f"{index}. {_format_unknown_shape_line(shape)}")
    return lines


def _format_unknown_shape_line(shape: AutoAccountingUnknownShapeHealth) -> str:
    markers = ", ".join(_operation_marker_label(marker) for marker in shape.operation_markers)
    if not markers:
        markers = "нет"
    return (
        f"{shape.bank.upper()} · {_owner_label(shape.owner_role)} · {shape.source_code}: "
        f"{shape.count} шт., последнее {_format_datetime(shape.last_received_at)}; "
        f"операции: {markers}; суммы: {shape.amount_count}; "
        f"баланс: {_yes_no(shape.has_balance_marker)}; "
        f"счёт/карта: {_yes_no(shape.has_instrument_marker)}"
    )


def _format_rules_block(health: AutoAccountingHealth) -> list[str]:
    lines = [
        "Правила категорий:",
        (
            f"авто {health.autosave_rule_count}, "
            f"подсказки {health.suggest_rule_count}, "
            f"выключены {health.disabled_rule_count}"
        ),
    ]
    if not health.top_rules:
        lines.append("Топ правил: пока нет подтверждённых продавцов.")
        return lines

    lines.append("Топ правил:")
    for index, rule in enumerate(health.top_rules, start=1):
        lines.append(f"{index}. {_format_rule_line(rule)}")
    return lines


def _format_action_block(health: AutoAccountingHealth) -> list[str]:
    actions: list[str] = []
    if health.pending_confirmation_count > 0:
        actions.append("Нажмите «Повторить ожидающие», чтобы разобрать расходы без карточек.")
    if health.failed_telegram_notification_count > 0 or health.unsent_pending_count > 0:
        actions.append("Если SMS пришла, а карточки нет, проверьте VPN/интернет на iPhone.")
    if health.unknown_event_count > 0:
        actions.append("Неизвестные форматы лучше прислать скрином или текстом для донастройки.")
    if health.conflict_event_count > 0:
        actions.append("Спорные подсказки стоит подтвердить вручную, чтобы правило не ошиблось.")
    if not actions:
        actions.append(
            "Критичных проблем не видно. Автоучёт можно постепенно переводить в autosave."
        )

    return ["Что сделать:", *actions]


def _format_rule_line(rule: AutoAccountingRuleHealth) -> str:
    return (
        f"{rule.bank.upper()} · {rule.merchant_display} → {rule.category_title} "
        f"({_mode_label(rule.mode)}, {rule.hit_count} подтвержд.)"
    )


def _mode_label(mode: BankCategoryRuleMode) -> str:
    if mode == BankCategoryRuleMode.AUTOSAVE:
        return "авто"
    if mode == BankCategoryRuleMode.SUGGEST:
        return "подсказка"
    return "выключено"


def _percent(part: int, total: int) -> str:
    if total <= 0:
        return "нет данных"
    return f"{part / total:.0%}"


def _format_source_block(source: AutoAccountingSourceHealth) -> list[str]:
    source_title = (
        f"{_status_icon(source)} {source.bank.upper()} · "
        f"{_owner_label(source.owner_role)} · {_channel_label(source.channel)}"
    )
    return [
        source_title,
        f"Код: {source.code}",
        f"Статус: {_status_label(source)}",
        f"Последнее SMS: {_format_datetime(source.last_seen_at)}",
        f"Последнее событие: {_format_datetime(source.last_event_received_at)}",
        (
            f"За период: всего {source.total_event_count}, "
            f"расходы {source.expense_candidate_count}, "
            f"сохранены {source.saved_expense_count}, "
            f"ждут {source.pending_confirmation_count}"
        ),
        (
            f"Не расходы: доходы {source.income_event_count}, "
            f"возвраты {source.refund_event_count}, "
            f"себе {source.internal_transfer_event_count}"
        ),
        (
            f"Проблемы: доставка {source.failed_telegram_notification_count}, "
            f"неизвестно {source.unknown_event_count}, "
            f"споры {source.conflict_event_count}, "
            f"служебные {source.ignored_event_count}"
        ),
    ]


def _status_icon(source: AutoAccountingSourceHealth) -> str:
    if not source.is_active:
        return "⏸"
    if source.failed_telegram_notification_count > 0:
        return "⚠️"
    if source.pending_confirmation_count > 0:
        return "⏳"
    if source.unknown_event_count > 0:
        return "⚠️"
    if source.last_seen_at is None:
        return "○"
    return "✅"


def _status_label(source: AutoAccountingSourceHealth) -> str:
    if not source.is_active:
        return "выключен"
    if source.failed_telegram_notification_count > 0:
        return "есть ошибки доставки"
    if source.unknown_event_count > 0:
        return "есть нераспознанные SMS"
    if source.last_seen_at is None:
        return "ещё не получал SMS"
    if source.pending_confirmation_count > 0:
        return "есть ожидающие подтверждения"
    return "работает"


def _owner_label(role: str) -> str:
    if role == "husband":
        return "муж"
    if role == "wife":
        return "жена"
    return role


def _channel_label(channel: str) -> str:
    labels = {
        "ios_shortcut": "iPhone",
        "manual_telegram": "ручной ввод",
        "email": "email",
        "android_notification": "Android",
    }
    return labels.get(channel, channel)


def _operation_marker_label(marker: str) -> str:
    labels = {
        "refund": "возврат",
        "purchase": "покупка",
        "payment": "оплата",
        "debit": "списание",
        "income": "поступление",
        "topup": "пополнение",
        "credit": "зачисление",
        "transfer": "перевод",
    }
    return labels.get(marker, marker)


def _yes_no(value: bool) -> str:
    return "да" if value else "нет"


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "не было"
    return value.strftime("%d.%m.%Y %H:%M")
