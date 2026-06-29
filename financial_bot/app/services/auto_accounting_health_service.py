from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    BankEventSourceStats,
)
from financial_bot.app.storage.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class AutoAccountingSourceHealth:
    source_id: int
    code: str
    bank: str
    channel: str
    owner_role: str
    owner_name: str
    is_active: bool
    last_seen_at: datetime | None
    last_event_received_at: datetime | None
    pending_confirmation_count: int
    failed_telegram_notification_count: int
    unsent_pending_count: int
    unknown_event_count: int
    ignored_event_count: int


@dataclass(frozen=True, slots=True)
class AutoAccountingHealth:
    sources: tuple[AutoAccountingSourceHealth, ...]
    active_source_count: int
    inactive_source_count: int
    pending_confirmation_count: int
    failed_telegram_notification_count: int
    unsent_pending_count: int
    unknown_event_count: int
    ignored_event_count: int


class AutoAccountingHealthService:
    def __init__(self, session: AsyncSession) -> None:
        self._bank_events = BankEventRepository(session)
        self._users = UserRepository(session)

    async def get_health(self, *, telegram_user_id: int) -> AutoAccountingHealth:
        requester = await self._users.get_by_telegram_id(telegram_user_id)
        if requester is None or not requester.is_active:
            raise ValueError("Пользователь не найден.")

        sources = await self._bank_events.list_sources()
        stats_by_source = await self._bank_events.get_source_stats()
        lines: list[AutoAccountingSourceHealth] = []
        for source in sources:
            owner = await self._users.get(source.owner_user_id)
            stats = stats_by_source.get(source.id, _empty_stats(source.id))
            lines.append(
                AutoAccountingSourceHealth(
                    source_id=source.id,
                    code=source.code,
                    bank=source.bank,
                    channel=source.channel,
                    owner_role=owner.role if owner is not None else "unknown",
                    owner_name=owner.name if owner is not None else "unknown",
                    is_active=source.is_active,
                    last_seen_at=source.last_seen_at,
                    last_event_received_at=stats.last_event_received_at,
                    pending_confirmation_count=stats.pending_confirmation_count,
                    failed_telegram_notification_count=stats.failed_telegram_notification_count,
                    unsent_pending_count=stats.unsent_pending_count,
                    unknown_event_count=stats.unknown_event_count,
                    ignored_event_count=stats.ignored_event_count,
                )
            )

        return AutoAccountingHealth(
            sources=tuple(lines),
            active_source_count=sum(1 for source in lines if source.is_active),
            inactive_source_count=sum(1 for source in lines if not source.is_active),
            pending_confirmation_count=sum(source.pending_confirmation_count for source in lines),
            failed_telegram_notification_count=sum(
                source.failed_telegram_notification_count for source in lines
            ),
            unsent_pending_count=sum(source.unsent_pending_count for source in lines),
            unknown_event_count=sum(source.unknown_event_count for source in lines),
            ignored_event_count=sum(source.ignored_event_count for source in lines),
        )


def _empty_stats(source_id: int) -> BankEventSourceStats:
    return BankEventSourceStats(
        source_id=source_id,
        last_event_received_at=None,
        pending_confirmation_count=0,
        failed_telegram_notification_count=0,
        unsent_pending_count=0,
        unknown_event_count=0,
        ignored_event_count=0,
    )
