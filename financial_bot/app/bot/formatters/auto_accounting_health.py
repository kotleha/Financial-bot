from datetime import datetime

from financial_bot.app.services.auto_accounting_health_service import (
    AutoAccountingHealth,
    AutoAccountingSourceHealth,
)


def format_auto_accounting_health(health: AutoAccountingHealth) -> str:
    if not health.sources:
        return (
            "Состояние автоучёта\n\n"
            "Банковские источники ещё не заведены.\n"
            "Когда появится iPhone Shortcut или другой источник, он будет виден здесь."
        )

    lines = [
        "Состояние автоучёта",
        "",
        (
            f"Источники: {health.active_source_count} активных, "
            f"{health.inactive_source_count} выключенных"
        ),
        f"Ожидают подтверждения: {health.pending_confirmation_count}",
        f"Ошибки отправки в Telegram: {health.failed_telegram_notification_count}",
        f"Ещё не отправлены в Telegram: {health.unsent_pending_count}",
        f"Не распознаны: {health.unknown_event_count}",
        f"Игнорированы как служебные: {health.ignored_event_count}",
        "",
        "Источники:",
    ]
    for source in health.sources:
        lines.extend(["", *_format_source_block(source)])

    lines.extend(
        [
            "",
            "Если SMS пришла на iPhone, но карточки нет в Telegram: откройте Shortcuts, "
            "проверьте VPN/интернет и нажмите «Повторить ожидающие».",
        ]
    )
    return "\n".join(lines)


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
        f"Ожидают: {source.pending_confirmation_count}",
        f"Ошибки отправки: {source.failed_telegram_notification_count}",
        f"Не распознаны: {source.unknown_event_count}",
        f"Служебные/игнор: {source.ignored_event_count}",
    ]


def _status_icon(source: AutoAccountingSourceHealth) -> str:
    if not source.is_active:
        return "⏸"
    if source.failed_telegram_notification_count > 0:
        return "⚠️"
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


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "не было"
    return value.strftime("%d.%m.%Y %H:%M")
