from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.types import BankEventParseStatus
from financial_bot.app.storage.models import BankEventModel, BankEventSourceModel


@dataclass(frozen=True, slots=True)
class BankEventSourceStats:
    source_id: int
    last_event_received_at: datetime | None
    total_event_count: int
    expense_candidate_count: int
    autosaved_expense_count: int
    confirmed_expense_count: int
    income_event_count: int
    refund_event_count: int
    internal_transfer_event_count: int
    conflict_event_count: int
    pending_confirmation_count: int
    failed_telegram_notification_count: int
    unsent_pending_count: int
    unknown_event_count: int
    ignored_event_count: int


def hash_bank_event_source_token(token: str) -> str:
    normalized_token = token.strip()
    if not normalized_token:
        msg = "Bank event source token must not be empty"
        raise ValueError(msg)
    return sha256(normalized_token.encode("utf-8")).hexdigest()


class BankEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add_source(self, source: BankEventSourceModel) -> BankEventSourceModel:
        self._session.add(source)
        await self._session.flush()
        return source

    async def get_source(self, source_id: int) -> BankEventSourceModel | None:
        return await self._session.get(BankEventSourceModel, source_id)

    async def get_source_by_code(self, code: str) -> BankEventSourceModel | None:
        result = await self._session.execute(
            select(BankEventSourceModel).where(BankEventSourceModel.code == code)
        )
        return result.scalar_one_or_none()

    async def list_sources(self) -> list[BankEventSourceModel]:
        result = await self._session.execute(
            select(BankEventSourceModel).order_by(
                BankEventSourceModel.owner_user_id,
                BankEventSourceModel.bank,
                BankEventSourceModel.code,
            )
        )
        return list(result.scalars())

    async def get_source_by_token(self, token: str) -> BankEventSourceModel | None:
        token_hash = hash_bank_event_source_token(token)
        result = await self._session.execute(
            select(BankEventSourceModel).where(BankEventSourceModel.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def get_active_source_by_token(self, token: str) -> BankEventSourceModel | None:
        token_hash = hash_bank_event_source_token(token)
        result = await self._session.execute(
            select(BankEventSourceModel)
            .where(BankEventSourceModel.token_hash == token_hash)
            .where(BankEventSourceModel.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def touch_source(
        self,
        source: BankEventSourceModel,
        *,
        seen_at: datetime,
    ) -> BankEventSourceModel:
        source.last_seen_at = seen_at
        await self._session.flush()
        return source

    async def add_event(self, event: BankEventModel) -> BankEventModel:
        self._session.add(event)
        await self._session.flush()
        return event

    async def add_event_if_new(self, event: BankEventModel) -> tuple[BankEventModel, bool]:
        existing_event = await self.get_event_by_dedupe_key(event.dedupe_key)
        if existing_event is not None:
            return existing_event, False

        try:
            async with self._session.begin_nested():
                self._session.add(event)
                await self._session.flush()
        except IntegrityError:
            existing_event = await self.get_event_by_dedupe_key(event.dedupe_key)
            if existing_event is not None:
                return existing_event, False
            raise

        return event, True

    async def get_event(self, event_id: int) -> BankEventModel | None:
        return await self._session.get(BankEventModel, event_id)

    async def get_event_by_dedupe_key(self, dedupe_key: str) -> BankEventModel | None:
        result = await self._session.execute(
            select(BankEventModel).where(BankEventModel.dedupe_key == dedupe_key)
        )
        return result.scalar_one_or_none()

    async def list_events_by_status(
        self,
        status: BankEventParseStatus | str,
    ) -> list[BankEventModel]:
        status_value = status.value if isinstance(status, BankEventParseStatus) else status
        result = await self._session.execute(
            select(BankEventModel)
            .where(BankEventModel.parse_status == status_value)
            .order_by(BankEventModel.received_at, BankEventModel.id)
        )
        return list(result.scalars())

    async def list_pending_confirmation_events_for_owner(
        self,
        *,
        owner_user_id: int,
        limit: int = 10,
    ) -> list[BankEventModel]:
        result = await self._session.execute(
            select(BankEventModel)
            .join(BankEventSourceModel, BankEventSourceModel.id == BankEventModel.source_id)
            .where(BankEventSourceModel.owner_user_id == owner_user_id)
            .where(BankEventModel.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION.value)
            .where(BankEventModel.operation_kind == "expense_candidate")
            .where(BankEventModel.transaction_id.is_(None))
            .order_by(BankEventModel.received_at.desc(), BankEventModel.id.desc())
            .limit(limit)
        )
        return list(result.scalars())

    async def get_source_stats(
        self,
        *,
        since: datetime | None = None,
    ) -> dict[int, BankEventSourceStats]:
        last_event_rows = await self._session.execute(
            select(
                BankEventModel.source_id,
                func.max(BankEventModel.received_at),
            ).group_by(BankEventModel.source_id)
        )
        last_event_by_source = {
            source_id: last_event_received_at
            for source_id, last_event_received_at in last_event_rows.all()
        }

        total_counts = await self._count_events_by_source(since=since)
        expense_counts = await self._count_events_by_source(
            since=since,
            operation_kind="expense_candidate",
        )
        autosaved_counts = await self._count_events_by_source(
            since=since,
            operation_kind="expense_candidate",
            parse_status=BankEventParseStatus.AUTOSAVED.value,
            linked_to_transaction=True,
        )
        confirmed_counts = await self._count_events_by_source(
            since=since,
            operation_kind="expense_candidate",
            parse_status=BankEventParseStatus.CONFIRMED.value,
            linked_to_transaction=True,
        )
        income_counts = await self._count_events_by_source(since=since, operation_kind="income")
        refund_counts = await self._count_events_by_source(since=since, operation_kind="refund")
        internal_transfer_counts = await self._count_events_by_source(
            since=since,
            operation_kind="internal_transfer",
        )
        conflict_counts = await self._count_events_by_source(
            since=since,
            operation_kind="expense_candidate",
            suggestion_conflict=True,
        )
        pending_counts = await self._count_pending_events_by_source(since=since)
        failed_counts = await self._count_pending_events_by_source(
            since=since, failed_telegram_notification=True
        )
        unsent_counts = await self._count_pending_events_by_source(
            since=since, unsent_telegram_notification=True
        )
        unknown_counts = await self._count_unknown_events_by_source(since=since)
        ignored_counts = await self._count_ignored_events_by_source(since=since)

        source_ids = (
            set(last_event_by_source)
            | set(total_counts)
            | set(expense_counts)
            | set(autosaved_counts)
            | set(confirmed_counts)
            | set(income_counts)
            | set(refund_counts)
            | set(internal_transfer_counts)
            | set(conflict_counts)
            | set(pending_counts)
            | set(failed_counts)
            | set(unsent_counts)
            | set(unknown_counts)
            | set(ignored_counts)
        )
        return {
            source_id: BankEventSourceStats(
                source_id=source_id,
                last_event_received_at=last_event_by_source.get(source_id),
                total_event_count=total_counts.get(source_id, 0),
                expense_candidate_count=expense_counts.get(source_id, 0),
                autosaved_expense_count=autosaved_counts.get(source_id, 0),
                confirmed_expense_count=confirmed_counts.get(source_id, 0),
                income_event_count=income_counts.get(source_id, 0),
                refund_event_count=refund_counts.get(source_id, 0),
                internal_transfer_event_count=internal_transfer_counts.get(source_id, 0),
                conflict_event_count=conflict_counts.get(source_id, 0),
                pending_confirmation_count=pending_counts.get(source_id, 0),
                failed_telegram_notification_count=failed_counts.get(source_id, 0),
                unsent_pending_count=unsent_counts.get(source_id, 0),
                unknown_event_count=unknown_counts.get(source_id, 0),
                ignored_event_count=ignored_counts.get(source_id, 0),
            )
            for source_id in source_ids
        }

    async def _count_pending_events_by_source(
        self,
        *,
        since: datetime | None = None,
        failed_telegram_notification: bool = False,
        unsent_telegram_notification: bool = False,
    ) -> dict[int, int]:
        query = (
            select(BankEventModel.source_id, func.count(BankEventModel.id))
            .where(BankEventModel.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION.value)
            .where(BankEventModel.operation_kind == "expense_candidate")
            .where(BankEventModel.transaction_id.is_(None))
            .group_by(BankEventModel.source_id)
        )
        if since is not None:
            query = query.where(BankEventModel.received_at >= since)
        if failed_telegram_notification:
            query = query.where(BankEventModel.telegram_notification_failed_at.is_not(None))
        if unsent_telegram_notification:
            query = query.where(BankEventModel.telegram_notification_sent_at.is_(None))

        result = await self._session.execute(query)
        return {source_id: count for source_id, count in result.all()}

    async def _count_unknown_events_by_source(
        self,
        *,
        since: datetime | None,
    ) -> dict[int, int]:
        return await self._count_events_by_source(
            since=since,
            operation_kind="unknown",
            unlinked=True,
        )

    async def _count_ignored_events_by_source(
        self,
        *,
        since: datetime | None,
    ) -> dict[int, int]:
        return await self._count_events_by_source(
            since=since,
            parse_status=BankEventParseStatus.IGNORED.value,
        )

    async def _count_events_by_source(
        self,
        *,
        since: datetime | None,
        operation_kind: str | None = None,
        parse_status: str | None = None,
        linked_to_transaction: bool = False,
        unlinked: bool = False,
        suggestion_conflict: bool = False,
    ) -> dict[int, int]:
        query = select(BankEventModel.source_id, func.count(BankEventModel.id))
        if since is not None:
            query = query.where(BankEventModel.received_at >= since)
        if operation_kind is not None:
            query = query.where(BankEventModel.operation_kind == operation_kind)
        if parse_status is not None:
            query = query.where(BankEventModel.parse_status == parse_status)
        if linked_to_transaction:
            query = query.where(BankEventModel.transaction_id.is_not(None))
        if unlinked:
            query = query.where(BankEventModel.transaction_id.is_(None))
        if suggestion_conflict:
            query = query.where(BankEventModel.suggestion_conflict.is_(True))

        result = await self._session.execute(query.group_by(BankEventModel.source_id))
        return {source_id: count for source_id, count in result.all()}

    async def set_parse_status(
        self,
        event: BankEventModel,
        status: BankEventParseStatus | str,
    ) -> BankEventModel:
        event.parse_status = status.value if isinstance(status, BankEventParseStatus) else status
        await self._session.flush()
        return event

    async def link_transaction(
        self,
        event: BankEventModel,
        *,
        transaction_id: int,
        status: BankEventParseStatus | str = BankEventParseStatus.CONFIRMED,
    ) -> BankEventModel:
        event.transaction_id = transaction_id
        event.parse_status = status.value if isinstance(status, BankEventParseStatus) else status
        await self._session.flush()
        return event

    async def try_link_transaction(
        self,
        *,
        event_id: int,
        transaction_id: int,
        status: BankEventParseStatus | str = BankEventParseStatus.CONFIRMED,
        allowed_statuses: tuple[BankEventParseStatus | str, ...],
    ) -> bool:
        status_value = status.value if isinstance(status, BankEventParseStatus) else status
        allowed_status_values = tuple(
            item.value if isinstance(item, BankEventParseStatus) else item
            for item in allowed_statuses
        )
        result = await self._session.execute(
            update(BankEventModel)
            .where(BankEventModel.id == event_id)
            .where(BankEventModel.transaction_id.is_(None))
            .where(BankEventModel.parse_status.in_(allowed_status_values))
            .values(transaction_id=transaction_id, parse_status=status_value)
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return result.rowcount == 1

    async def try_update_unlinked_event(
        self,
        *,
        event_id: int,
        values: dict[str, object],
        allowed_statuses: tuple[BankEventParseStatus | str, ...],
    ) -> bool:
        allowed_status_values = tuple(
            item.value if isinstance(item, BankEventParseStatus) else item
            for item in allowed_statuses
        )
        result = await self._session.execute(
            update(BankEventModel)
            .where(BankEventModel.id == event_id)
            .where(BankEventModel.transaction_id.is_(None))
            .where(BankEventModel.parse_status.in_(allowed_status_values))
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        await self._session.flush()
        return result.rowcount == 1

    async def mark_telegram_notification_sent(
        self,
        event: BankEventModel,
        *,
        sent_at: datetime,
    ) -> BankEventModel:
        event.telegram_notification_sent_at = sent_at
        event.telegram_notification_failed_at = None
        event.telegram_notification_attempts += 1
        await self._session.flush()
        return event

    async def mark_telegram_notification_failed(
        self,
        event: BankEventModel,
        *,
        failed_at: datetime,
    ) -> BankEventModel:
        event.telegram_notification_failed_at = failed_at
        event.telegram_notification_attempts += 1
        await self._session.flush()
        return event
