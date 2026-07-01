from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.bank_sms import classify_bank_sms_shape
from financial_bot.app.domain.types import BankCategoryRuleMode
from financial_bot.app.storage.repositories.bank_category_rule_repository import (
    BankCategoryRuleRepository,
)
from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    BankEventSourceStats,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository

DEFAULT_AUTO_ACCOUNTING_HEALTH_PERIOD_DAYS = 30


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
    total_event_count: int = 0
    expense_candidate_count: int = 0
    autosaved_expense_count: int = 0
    confirmed_expense_count: int = 0
    income_event_count: int = 0
    refund_event_count: int = 0
    internal_transfer_event_count: int = 0
    conflict_event_count: int = 0

    @property
    def saved_expense_count(self) -> int:
        return self.autosaved_expense_count + self.confirmed_expense_count


@dataclass(frozen=True, slots=True)
class AutoAccountingRuleHealth:
    id: int
    bank: str
    merchant_display: str
    category_title: str
    hit_count: int
    mode: BankCategoryRuleMode
    last_confirmed_at: datetime | None
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class AutoAccountingUnknownShapeHealth:
    source_code: str
    bank: str
    owner_role: str
    count: int
    last_received_at: datetime
    operation_markers: tuple[str, ...]
    amount_count: int
    has_balance_marker: bool
    has_instrument_marker: bool
    ignored_reason: str
    has_security_marker: bool


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
    period_days: int = DEFAULT_AUTO_ACCOUNTING_HEALTH_PERIOD_DAYS
    total_event_count: int = 0
    expense_candidate_count: int = 0
    autosaved_expense_count: int = 0
    confirmed_expense_count: int = 0
    income_event_count: int = 0
    refund_event_count: int = 0
    internal_transfer_event_count: int = 0
    conflict_event_count: int = 0
    autosave_rule_count: int = 0
    suggest_rule_count: int = 0
    disabled_rule_count: int = 0
    top_rules: tuple[AutoAccountingRuleHealth, ...] = ()
    unknown_shapes: tuple[AutoAccountingUnknownShapeHealth, ...] = ()

    @property
    def saved_expense_count(self) -> int:
        return self.autosaved_expense_count + self.confirmed_expense_count


class AutoAccountingHealthService:
    def __init__(self, session: AsyncSession) -> None:
        self._bank_events = BankEventRepository(session)
        self._bank_rules = BankCategoryRuleRepository(session)
        self._categories = CategoryRepository(session)
        self._users = UserRepository(session)

    async def get_health(
        self,
        *,
        telegram_user_id: int,
        period_days: int = DEFAULT_AUTO_ACCOUNTING_HEALTH_PERIOD_DAYS,
        now: datetime | None = None,
    ) -> AutoAccountingHealth:
        requester = await self._users.get_by_telegram_id(telegram_user_id)
        if requester is None or not requester.is_active:
            raise ValueError("Пользователь не найден.")

        checked_at = now or datetime.now(UTC)
        since = checked_at - timedelta(days=period_days)
        sources = await self._bank_events.list_sources()
        stats_by_source = await self._bank_events.get_source_stats(since=since)
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
                    total_event_count=stats.total_event_count,
                    expense_candidate_count=stats.expense_candidate_count,
                    autosaved_expense_count=stats.autosaved_expense_count,
                    confirmed_expense_count=stats.confirmed_expense_count,
                    income_event_count=stats.income_event_count,
                    refund_event_count=stats.refund_event_count,
                    internal_transfer_event_count=stats.internal_transfer_event_count,
                    conflict_event_count=stats.conflict_event_count,
                )
            )

        rule_counts = await self._bank_rules.count_by_mode()
        top_rules = await self._get_top_rules()
        unknown_shapes = await self._get_unknown_shapes(
            sources_by_id={source.source_id: source for source in lines},
            since=since,
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
            period_days=period_days,
            total_event_count=sum(source.total_event_count for source in lines),
            expense_candidate_count=sum(source.expense_candidate_count for source in lines),
            autosaved_expense_count=sum(source.autosaved_expense_count for source in lines),
            confirmed_expense_count=sum(source.confirmed_expense_count for source in lines),
            income_event_count=sum(source.income_event_count for source in lines),
            refund_event_count=sum(source.refund_event_count for source in lines),
            internal_transfer_event_count=sum(
                source.internal_transfer_event_count for source in lines
            ),
            conflict_event_count=sum(source.conflict_event_count for source in lines),
            autosave_rule_count=rule_counts.get(BankCategoryRuleMode.AUTOSAVE.value, 0),
            suggest_rule_count=rule_counts.get(BankCategoryRuleMode.SUGGEST.value, 0),
            disabled_rule_count=rule_counts.get(BankCategoryRuleMode.DISABLED.value, 0),
            top_rules=top_rules,
            unknown_shapes=unknown_shapes,
        )

    async def _get_top_rules(self) -> tuple[AutoAccountingRuleHealth, ...]:
        lines: list[AutoAccountingRuleHealth] = []
        for rule in await self._bank_rules.list_top_rules(limit=5):
            category = await self._categories.get(rule.category_id)
            lines.append(
                AutoAccountingRuleHealth(
                    id=rule.id,
                    bank=rule.bank,
                    merchant_display=rule.merchant_display,
                    category_title=category.title if category is not None else "категория удалена",
                    hit_count=rule.hit_count,
                    mode=_rule_mode(rule.mode, is_active=rule.is_active),
                    last_confirmed_at=rule.last_confirmed_at,
                    last_used_at=rule.last_used_at,
                )
            )
        return tuple(lines)

    async def _get_unknown_shapes(
        self,
        *,
        sources_by_id: dict[int, AutoAccountingSourceHealth],
        since: datetime,
    ) -> tuple[AutoAccountingUnknownShapeHealth, ...]:
        grouped: dict[
            tuple[int, tuple[str, ...], int, bool, bool, str, bool],
            AutoAccountingUnknownShapeHealth,
        ] = {}
        for event in await self._bank_events.list_unknown_unlinked_events(since=since, limit=100):
            source = sources_by_id.get(event.source_id)
            if source is None:
                continue

            shape = classify_bank_sms_shape(
                event.redacted_text, sender=_sender_for_bank(event.bank)
            )
            key = (
                event.source_id,
                shape.operation_markers,
                shape.amount_count,
                shape.has_balance_marker,
                shape.has_instrument_marker,
                shape.ignored_reason,
                shape.has_security_marker,
            )
            previous = grouped.get(key)
            if previous is None:
                grouped[key] = AutoAccountingUnknownShapeHealth(
                    source_code=source.code,
                    bank=source.bank,
                    owner_role=source.owner_role,
                    count=1,
                    last_received_at=event.received_at,
                    operation_markers=shape.operation_markers,
                    amount_count=shape.amount_count,
                    has_balance_marker=shape.has_balance_marker,
                    has_instrument_marker=shape.has_instrument_marker,
                    ignored_reason=shape.ignored_reason,
                    has_security_marker=shape.has_security_marker,
                )
                continue

            grouped[key] = AutoAccountingUnknownShapeHealth(
                source_code=previous.source_code,
                bank=previous.bank,
                owner_role=previous.owner_role,
                count=previous.count + 1,
                last_received_at=max(previous.last_received_at, event.received_at),
                operation_markers=previous.operation_markers,
                amount_count=previous.amount_count,
                has_balance_marker=previous.has_balance_marker,
                has_instrument_marker=previous.has_instrument_marker,
                ignored_reason=previous.ignored_reason,
                has_security_marker=previous.has_security_marker,
            )

        return tuple(
            sorted(
                grouped.values(),
                key=lambda shape: (shape.count, shape.last_received_at),
                reverse=True,
            )[:5]
        )


def _empty_stats(source_id: int) -> BankEventSourceStats:
    return BankEventSourceStats(
        source_id=source_id,
        last_event_received_at=None,
        total_event_count=0,
        expense_candidate_count=0,
        autosaved_expense_count=0,
        confirmed_expense_count=0,
        income_event_count=0,
        refund_event_count=0,
        internal_transfer_event_count=0,
        conflict_event_count=0,
        pending_confirmation_count=0,
        failed_telegram_notification_count=0,
        unsent_pending_count=0,
        unknown_event_count=0,
        ignored_event_count=0,
    )


def _rule_mode(value: str, *, is_active: bool) -> BankCategoryRuleMode:
    try:
        return BankCategoryRuleMode(value)
    except ValueError:
        return BankCategoryRuleMode.SUGGEST if is_active else BankCategoryRuleMode.DISABLED


def _sender_for_bank(bank: str) -> str:
    if bank == "sber":
        return "900"
    if bank == "vtb":
        return "VTB"
    if bank == "tbank":
        return "T-Bank"
    return ""
