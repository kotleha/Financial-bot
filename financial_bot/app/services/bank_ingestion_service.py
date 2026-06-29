from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from hashlib import sha256
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.bank_learning import normalize_bank_merchant_key
from financial_bot.app.domain.bank_sms import ParsedBankSms, parse_bank_sms
from financial_bot.app.domain.types import (
    BankCategoryRuleMode,
    BankEventBank,
    BankEventChannel,
    BankEventOperationKind,
    BankEventParseStatus,
    BankEventSuggestionSource,
    TransactionSource,
)
from financial_bot.app.services.bank_learning_service import (
    BankLearningRuleFeedback,
    BankLearningService,
    BankLearningSuggestion,
)
from financial_bot.app.services.transaction_service import (
    CreatedTransactionSummary,
    TransactionService,
)
from financial_bot.app.storage.models import (
    BankEventModel,
    BankEventSourceModel,
    CategoryModel,
    TransactionModel,
    UserModel,
)
from financial_bot.app.storage.repositories.bank_category_rule_repository import (
    BankCategoryRuleRepository,
)
from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    hash_bank_event_source_token,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class BankImportResult:
    event_id: int
    is_duplicate: bool
    bank: BankEventBank
    operation_kind: BankEventOperationKind
    parse_status: BankEventParseStatus
    amount: int | None
    fee_amount: int | None
    currency: str
    merchant: str
    counterparty: str
    suggested_category_code: str | None
    suggested_category_title: str | None
    suggested_category_source: BankEventSuggestionSource
    requires_confirmation: bool
    ignore_reason: str
    redacted_text: str
    occurred_at: datetime | None = None
    telegram_notification_attempts: int = 0
    telegram_notification_sent_at: datetime | None = None
    telegram_notification_failed_at: datetime | None = None
    suggestion_conflict: bool = False

    @property
    def creates_expense_candidate(self) -> bool:
        return self.operation_kind == BankEventOperationKind.EXPENSE_CANDIDATE


@dataclass(frozen=True, slots=True)
class BankEventUpdateResult:
    event_id: int
    operation_kind: BankEventOperationKind
    parse_status: BankEventParseStatus
    amount: int | None
    currency: str
    merchant: str
    counterparty: str
    suggested_category_code: str | None
    suggested_category_title: str | None
    suggested_category_source: BankEventSuggestionSource


@dataclass(frozen=True, slots=True)
class BankEventConfirmationResult:
    event_id: int
    transaction: CreatedTransactionSummary | None
    learning_rule: BankLearningRuleFeedback | None = None
    already_confirmed: bool = False


class BankIngestionAuthError(PermissionError):
    """Raised when a bank ingestion source token is missing or invalid."""


class BankIngestionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._categories = CategoryRepository(session)
        self._bank_events = BankEventRepository(session)
        self._transactions = TransactionService(session, settings)

    async def import_manual_sms(
        self,
        *,
        text: str,
        telegram_user_id: int,
        received_at: datetime | None = None,
    ) -> BankImportResult:
        normalized_text = text.strip()
        if not normalized_text:
            msg = "Bank SMS text must not be empty"
            raise ValueError(msg)

        user = await self._users.get_by_telegram_id(telegram_user_id)
        if user is None:
            msg = f"Telegram user is not seeded: {telegram_user_id}"
            raise ValueError(msg)

        parsed = parse_bank_sms(
            normalized_text,
            self_counterparty_aliases=self._settings.bank_self_counterparty_aliases,
        )
        received_at = received_at or datetime.now(ZoneInfo(self._settings.timezone))
        source = await self._get_or_create_manual_source(
            user_id=user.id,
            bank=parsed.bank,
        )
        return await self._store_parsed_event(
            source=source,
            channel=BankEventChannel.MANUAL_TELEGRAM,
            parsed=parsed,
            received_at=received_at,
        )

    async def import_sms_from_source_token(
        self,
        *,
        text: str,
        source_token: str,
        sender: str = "",
        received_at: datetime | None = None,
    ) -> BankImportResult:
        normalized_text = text.strip()
        if not normalized_text:
            msg = "Bank SMS text must not be empty"
            raise ValueError(msg)

        source = await self._bank_events.get_active_source_by_token(source_token)
        if source is None:
            msg = "Bank ingestion source token is invalid"
            raise BankIngestionAuthError(msg)

        source_bank = BankEventBank(source.bank)
        parsed = parse_bank_sms(
            normalized_text,
            sender=sender or _sender_from_source_bank(source_bank),
            self_counterparty_aliases=self._settings.bank_self_counterparty_aliases,
        )
        parsed = _ignore_bank_source_mismatch(parsed, expected_bank=source_bank)
        received_at = received_at or datetime.now(ZoneInfo(self._settings.timezone))
        return await self._store_parsed_event(
            source=source,
            channel=BankEventChannel(source.channel),
            parsed=parsed,
            received_at=received_at,
        )

    async def confirm_event(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventConfirmationResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if await self._has_active_linked_transaction(
            event,
            reopen_status=BankEventParseStatus.NEEDS_CONFIRMATION,
        ):
            return BankEventConfirmationResult(
                event_id=event.id,
                transaction=None,
                already_confirmed=True,
            )
        _ensure_event_is_actionable(event)
        if event.operation_kind != BankEventOperationKind.EXPENSE_CANDIDATE.value:
            msg = "Только расход-кандидат можно подтвердить как расход"
            raise ValueError(msg)
        if event.amount is None:
            msg = "У банковского события нет суммы"
            raise ValueError(msg)
        if event.suggested_category_id is None:
            msg = "Сначала выберите категорию"
            raise ValueError(msg)

        summary = await self._transactions.create_from_category_selection(
            amount=event.amount,
            category_id=event.suggested_category_id,
            payer_telegram_id=telegram_user_id,
            raw_text=f"bank_event:{event.id}",
            comment=_event_comment(event),
            source=_event_transaction_source(event),
            occurred_at=event.occurred_at,
        )
        linked = await self._bank_events.try_link_transaction(
            event_id=event.id,
            transaction_id=summary.id,
            status=BankEventParseStatus.CONFIRMED,
            allowed_statuses=(BankEventParseStatus.NEEDS_CONFIRMATION,),
        )
        if not linked:
            return await self._cleanup_unlinked_transaction(
                event_id=event.id,
                transaction_id=summary.id,
                telegram_user_id=telegram_user_id,
            )

        event.transaction_id = summary.id
        event.parse_status = BankEventParseStatus.CONFIRMED.value
        learning_rule = None
        source = await self._bank_events.get_source(event.source_id)
        if source is not None:
            learning_rule = await BankLearningService(self._session).learn_from_confirmed_event(
                event=event,
                source=source,
                confirmed_at=datetime.now(ZoneInfo(self._settings.timezone)),
            )
        return BankEventConfirmationResult(
            event_id=event.id,
            transaction=summary,
            learning_rule=learning_rule,
        )

    async def create_refund_correction(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventConfirmationResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if await self._has_active_linked_transaction(
            event,
            reopen_status=BankEventParseStatus.PARSED,
        ):
            return BankEventConfirmationResult(
                event_id=event.id,
                transaction=None,
                already_confirmed=True,
            )
        _ensure_event_is_actionable(event)
        if event.operation_kind != BankEventOperationKind.REFUND.value:
            msg = "Только возврат можно учесть как корректировку"
            raise ValueError(msg)
        if event.parse_status == BankEventParseStatus.CONFIRMED.value:
            msg = "Возврат уже учтён"
            raise ValueError(msg)
        if event.amount is None:
            msg = "У банковского события нет суммы"
            raise ValueError(msg)
        if event.suggested_category_id is None:
            msg = "Сначала выберите категорию"
            raise ValueError(msg)

        category = await self._categories.get(event.suggested_category_id)
        if category is None or not category.is_active or not category.is_expense:
            msg = "Категория недоступна для корректировки"
            raise ValueError(msg)

        summary = await self._transactions.create_correction_from_category_selection(
            amount=event.amount,
            category_id=event.suggested_category_id,
            payer_telegram_id=telegram_user_id,
            raw_text=f"bank_refund_event:{event.id}",
            comment=_event_comment(event),
            source=_event_transaction_source(event),
            occurred_at=event.occurred_at,
        )
        linked = await self._bank_events.try_link_transaction(
            event_id=event.id,
            transaction_id=summary.id,
            status=BankEventParseStatus.CONFIRMED,
            allowed_statuses=(BankEventParseStatus.PARSED,),
        )
        if not linked:
            return await self._cleanup_unlinked_transaction(
                event_id=event.id,
                transaction_id=summary.id,
                telegram_user_id=telegram_user_id,
            )

        event.transaction_id = summary.id
        event.parse_status = BankEventParseStatus.CONFIRMED.value
        return BankEventConfirmationResult(event_id=event.id, transaction=summary)

    async def confirm_income_event(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventConfirmationResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if await self._has_active_linked_transaction(
            event,
            reopen_status=BankEventParseStatus.PARSED,
        ):
            return BankEventConfirmationResult(
                event_id=event.id,
                transaction=None,
                already_confirmed=True,
            )
        _ensure_event_is_actionable(event)
        if event.operation_kind != BankEventOperationKind.INCOME.value:
            msg = "Только поступление можно учесть как доход"
            raise ValueError(msg)
        if event.amount is None:
            msg = "У банковского события нет суммы"
            raise ValueError(msg)

        summary = await self._transactions.create_income(
            amount=event.amount,
            recipient_telegram_id=telegram_user_id,
            raw_text=f"bank_income_event:{event.id}",
            comment=_event_comment(event),
            source=_event_transaction_source(event),
            occurred_at=event.occurred_at,
        )
        linked = await self._bank_events.try_link_transaction(
            event_id=event.id,
            transaction_id=summary.id,
            status=BankEventParseStatus.CONFIRMED,
            allowed_statuses=(BankEventParseStatus.PARSED,),
        )
        if not linked:
            return await self._cleanup_unlinked_transaction(
                event_id=event.id,
                transaction_id=summary.id,
                telegram_user_id=telegram_user_id,
            )

        event.transaction_id = summary.id
        event.parse_status = BankEventParseStatus.CONFIRMED.value
        return BankEventConfirmationResult(event_id=event.id, transaction=summary)

    async def reject_event(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventUpdateResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if _is_autosaved_linked_event(event):
            return await self._delete_autosaved_event(
                event=event,
                telegram_user_id=telegram_user_id,
                next_status=BankEventParseStatus.REJECTED,
            )

        _ensure_not_linked(event)
        updated = await self._bank_events.try_update_unlinked_event(
            event_id=event.id,
            values={"parse_status": BankEventParseStatus.REJECTED.value},
            allowed_statuses=(
                BankEventParseStatus.NEEDS_CONFIRMATION,
                BankEventParseStatus.PARSED,
            ),
        )
        if not updated:
            await self._raise_event_changed_or_linked(event)
        await self._session.refresh(event)
        return await self._event_update_result(event)

    async def mark_event_internal_transfer(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventUpdateResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if _is_autosaved_linked_event(event):
            return await self._mark_autosaved_event_internal_transfer(
                event=event,
                telegram_user_id=telegram_user_id,
            )

        _ensure_not_linked(event)
        _ensure_event_is_actionable(event)
        category = await self._categories.get_by_code("internal_transfer")
        if category is None:
            msg = "Internal transfer category is not seeded"
            raise ValueError(msg)

        updated = await self._bank_events.try_update_unlinked_event(
            event_id=event.id,
            values={
                "operation_kind": BankEventOperationKind.INTERNAL_TRANSFER.value,
                "parse_status": BankEventParseStatus.PARSED.value,
                "suggested_category_id": category.id,
                "suggested_category_source": BankEventSuggestionSource.MANUAL.value,
                "counterparty": "self",
            },
            allowed_statuses=(
                BankEventParseStatus.NEEDS_CONFIRMATION,
                BankEventParseStatus.PARSED,
            ),
        )
        if not updated:
            await self._raise_event_changed_or_linked(event)
        await self._session.refresh(event)
        return await self._event_update_result(event)

    async def update_event_category(
        self,
        *,
        event_id: int,
        category_id: int,
        telegram_user_id: int,
    ) -> BankEventUpdateResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if _is_autosaved_linked_event(event):
            return await self._update_autosaved_event_category(
                event=event,
                category_id=category_id,
                telegram_user_id=telegram_user_id,
            )

        _ensure_not_linked(event)
        _ensure_event_is_actionable(event)
        if event.operation_kind not in {
            BankEventOperationKind.EXPENSE_CANDIDATE.value,
            BankEventOperationKind.REFUND.value,
        }:
            msg = "Категорию можно выбрать только для расхода-кандидата или возврата"
            raise ValueError(msg)

        category = await self._categories.get(category_id)
        if category is None or not category.is_active or not category.is_expense:
            msg = "Категория недоступна для расхода"
            raise ValueError(msg)

        next_status = (
            BankEventParseStatus.NEEDS_CONFIRMATION
            if event.operation_kind == BankEventOperationKind.EXPENSE_CANDIDATE.value
            else BankEventParseStatus.PARSED
        )
        updated = await self._bank_events.try_update_unlinked_event(
            event_id=event.id,
            values={
                "suggested_category_id": category.id,
                "suggested_category_source": BankEventSuggestionSource.MANUAL.value,
                "parse_status": next_status.value,
            },
            allowed_statuses=(BankEventParseStatus(event.parse_status),),
        )
        if not updated:
            await self._raise_event_changed_or_linked(event)
        await self._session.refresh(event)
        return await self._event_update_result(event)

    async def disable_autosave_rule_for_event(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventUpdateResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if event.parse_status != BankEventParseStatus.AUTOSAVED.value:
            msg = "Правило можно отключить только из автозаписанного банковского события"
            raise ValueError(msg)
        if not event.merchant:
            msg = "У банковского события нет продавца для правила"
            raise ValueError(msg)

        source = await self._bank_events.get_source(event.source_id)
        if source is None:
            msg = "Источник банковского события не найден"
            raise ValueError(msg)

        merchant_key = normalize_bank_merchant_key(event.merchant)
        if not merchant_key:
            msg = "У банковского события нет стабильного ключа продавца"
            raise ValueError(msg)

        rule = await BankCategoryRuleRepository(self._session).get_rule(
            owner_user_id=source.owner_user_id,
            bank=event.bank,
            merchant_key=merchant_key,
        )
        if rule is None:
            msg = "Правило автоучёта не найдено"
            raise ValueError(msg)

        rule.mode = BankCategoryRuleMode.DISABLED.value
        rule.is_active = False
        await self._session.flush()
        return await self._event_update_result(event)

    async def list_expense_categories(self) -> list:
        return await self._transactions.list_category_options()

    async def list_pending_confirmation_events(
        self,
        *,
        telegram_user_id: int,
        limit: int = 10,
    ) -> list[BankImportResult]:
        user = await self._users.get_by_telegram_id(telegram_user_id)
        if user is None:
            msg = f"Telegram user is not seeded: {telegram_user_id}"
            raise ValueError(msg)

        events = await self._bank_events.list_pending_confirmation_events_for_owner(
            owner_user_id=user.id,
            limit=limit,
        )
        results: list[BankImportResult] = []
        for event in events:
            category = (
                await self._categories.get(event.suggested_category_id)
                if event.suggested_category_id is not None
                else None
            )
            results.append(_result_from_event(event, category, is_duplicate=False))
        return results

    async def get_pending_confirmation_event(
        self,
        *,
        event_id: int,
        telegram_user_id: int,
    ) -> BankImportResult:
        event = await self._resolve_owned_event(event_id, telegram_user_id)
        if event.parse_status != BankEventParseStatus.NEEDS_CONFIRMATION.value:
            msg = "Банковское событие не ожидает подтверждения"
            raise ValueError(msg)
        if event.transaction_id is not None:
            msg = "Банковское событие уже связано с расходом"
            raise ValueError(msg)

        category = (
            await self._categories.get(event.suggested_category_id)
            if event.suggested_category_id is not None
            else None
        )
        return _result_from_event(event, category, is_duplicate=False)

    async def mark_telegram_notification_sent(
        self,
        *,
        event_id: int,
        sent_at: datetime | None = None,
    ) -> None:
        event = await self._bank_events.get_event(event_id)
        if event is None:
            msg = f"Bank event does not exist: {event_id}"
            raise ValueError(msg)
        await self._bank_events.mark_telegram_notification_sent(
            event,
            sent_at=sent_at or datetime.now(ZoneInfo(self._settings.timezone)),
        )

    async def mark_telegram_notification_failed(
        self,
        *,
        event_id: int,
        failed_at: datetime | None = None,
    ) -> None:
        event = await self._bank_events.get_event(event_id)
        if event is None:
            msg = f"Bank event does not exist: {event_id}"
            raise ValueError(msg)
        await self._bank_events.mark_telegram_notification_failed(
            event,
            failed_at=failed_at or datetime.now(ZoneInfo(self._settings.timezone)),
        )

    async def _update_autosaved_event_category(
        self,
        *,
        event: BankEventModel,
        category_id: int,
        telegram_user_id: int,
    ) -> BankEventUpdateResult:
        _ensure_event_is_actionable(event)
        transaction = await self._active_autosaved_transaction(event)

        category = await self._categories.get(category_id)
        if category is None or not category.is_active or not category.is_expense:
            msg = "Категория недоступна для расхода"
            raise ValueError(msg)

        await self._transactions.update_transaction(
            transaction_id=transaction.id,
            changed_by_telegram_id=telegram_user_id,
            category_id=category.id,
        )
        event.suggested_category_id = category.id
        event.suggested_category_source = BankEventSuggestionSource.MANUAL.value
        await self._session.flush()

        source = await self._bank_events.get_source(event.source_id)
        if source is not None:
            await BankLearningService(self._session).learn_from_confirmed_event(
                event=event,
                source=source,
                confirmed_at=datetime.now(ZoneInfo(self._settings.timezone)),
            )
        return await self._event_update_result(event)

    async def _mark_autosaved_event_internal_transfer(
        self,
        *,
        event: BankEventModel,
        telegram_user_id: int,
    ) -> BankEventUpdateResult:
        _ensure_event_is_actionable(event)
        category = await self._categories.get_by_code("internal_transfer")
        if category is None:
            msg = "Internal transfer category is not seeded"
            raise ValueError(msg)

        return await self._delete_autosaved_event(
            event=event,
            telegram_user_id=telegram_user_id,
            next_status=BankEventParseStatus.PARSED,
            values={
                "operation_kind": BankEventOperationKind.INTERNAL_TRANSFER.value,
                "suggested_category_id": category.id,
                "suggested_category_source": BankEventSuggestionSource.MANUAL.value,
                "counterparty": "self",
            },
        )

    async def _delete_autosaved_event(
        self,
        *,
        event: BankEventModel,
        telegram_user_id: int,
        next_status: BankEventParseStatus,
        values: dict[str, object] | None = None,
    ) -> BankEventUpdateResult:
        _ensure_event_is_actionable(event)
        transaction = await self._active_autosaved_transaction(event)
        await self._transactions.delete_transaction(
            transaction_id=transaction.id,
            changed_by_telegram_id=telegram_user_id,
        )

        event.transaction_id = None
        event.parse_status = next_status.value
        for key, value in (values or {}).items():
            setattr(event, key, value)
        await self._session.flush()
        return await self._event_update_result(event)

    async def _active_autosaved_transaction(self, event: BankEventModel) -> TransactionModel:
        if event.parse_status != BankEventParseStatus.AUTOSAVED.value:
            msg = "Банковское событие не является автозаписанным расходом"
            raise ValueError(msg)
        if event.transaction_id is None:
            msg = "Автозаписанный расход уже изменён"
            raise ValueError(msg)

        transaction = await self._session.get(TransactionModel, event.transaction_id)
        if transaction is None or transaction.deleted_at is not None:
            event.transaction_id = None
            event.parse_status = BankEventParseStatus.NEEDS_CONFIRMATION.value
            await self._session.flush()
            msg = "Автозаписанный расход уже изменён"
            raise ValueError(msg)
        return transaction

    async def _cleanup_unlinked_transaction(
        self,
        *,
        event_id: int,
        transaction_id: int,
        telegram_user_id: int,
    ) -> BankEventConfirmationResult:
        await self._transactions.delete_transaction(
            transaction_id=transaction_id,
            changed_by_telegram_id=telegram_user_id,
        )
        event = await self._bank_events.get_event(event_id)
        if event is not None:
            await self._session.refresh(event)
            if event.transaction_id is not None:
                return BankEventConfirmationResult(
                    event_id=event.id,
                    transaction=None,
                    already_confirmed=True,
                )

        msg = "Банковское событие уже изменилось. Откройте актуальную карточку."
        raise ValueError(msg)

    async def _has_active_linked_transaction(
        self,
        event: BankEventModel,
        *,
        reopen_status: BankEventParseStatus,
    ) -> bool:
        if event.transaction_id is None:
            return False

        transaction = await self._session.get(TransactionModel, event.transaction_id)
        if transaction is not None and transaction.deleted_at is None:
            return True

        event.transaction_id = None
        event.parse_status = reopen_status.value
        await self._session.flush()
        return False

    async def _raise_event_changed_or_linked(self, event: BankEventModel) -> None:
        await self._session.refresh(event)
        if event.transaction_id is not None:
            msg = "Банковское событие уже учтено."
            raise ValueError(msg)
        msg = "Банковское событие уже изменилось. Откройте актуальную карточку."
        raise ValueError(msg)

    async def _get_or_create_manual_source(
        self,
        *,
        user_id: int,
        bank: BankEventBank,
    ) -> BankEventSourceModel:
        code = f"manual-telegram:{user_id}:{bank.value}"
        existing_source = await self._bank_events.get_source_by_code(code)
        if existing_source is not None:
            return existing_source

        return await self._bank_events.add_source(
            BankEventSourceModel(
                code=code,
                bank=bank.value,
                channel=BankEventChannel.MANUAL_TELEGRAM.value,
                owner_user_id=user_id,
                token_hash=hash_bank_event_source_token(f"{code}:manual-source"),
            )
        )

    async def _resolve_suggested_category(self, category_code: str | None) -> CategoryModel | None:
        if category_code is None:
            return None
        return await self._categories.get_by_code(category_code)

    async def _store_parsed_event(
        self,
        *,
        source: BankEventSourceModel,
        channel: BankEventChannel,
        parsed: ParsedBankSms,
        received_at: datetime,
    ) -> BankImportResult:
        await self._bank_events.touch_source(source, seen_at=received_at)

        status = _initial_parse_status(parsed)
        normalized_text_hash = _hash_normalized_text(parsed.redacted_text)
        occurred_at = _infer_occurred_at(
            operation_time=parsed.operation_time,
            received_at=received_at,
            timezone_name=self._settings.timezone,
        )
        dedupe_key = _build_dedupe_key(
            source_code=source.code,
            bank=parsed.bank,
            operation_kind=parsed.operation_kind,
            amount=parsed.amount,
            fee_amount=parsed.fee_amount,
            occurred_at=occurred_at,
            received_at=received_at,
            timezone_name=self._settings.timezone,
            merchant=parsed.merchant,
            counterparty=parsed.counterparty,
            normalized_text_hash=normalized_text_hash,
        )
        category, suggestion_source, learning_suggestion = await self._resolve_category_suggestion(
            source=source,
            parsed=parsed,
            received_at=received_at,
        )
        suggestion_conflict = (
            learning_suggestion.has_parser_conflict if learning_suggestion is not None else False
        )

        event, is_created = await self._bank_events.add_event_if_new(
            BankEventModel(
                source_id=source.id,
                bank=parsed.bank.value,
                channel=channel.value,
                received_at=received_at,
                occurred_at=occurred_at,
                operation_kind=parsed.operation_kind.value,
                parse_status=status.value,
                amount=parsed.amount,
                fee_amount=parsed.fee_amount,
                source=parsed.source.value,
                currency=parsed.currency,
                merchant=_stored_merchant(parsed),
                counterparty=_stored_counterparty(parsed),
                redacted_text=parsed.redacted_text,
                normalized_text_hash=normalized_text_hash,
                dedupe_key=dedupe_key,
                suggestion_conflict=suggestion_conflict,
                suggested_category_id=category.id if category is not None else None,
                suggested_category_source=suggestion_source.value,
            )
        )

        if is_created:
            autosaved_transaction = await self._autosave_event_if_eligible(
                event=event,
                source=source,
                category=category,
                suggestion_source=suggestion_source,
                learning_suggestion=learning_suggestion,
            )
            return _result_from_parsed(
                event=event,
                parsed=parsed,
                status=(
                    BankEventParseStatus.AUTOSAVED if autosaved_transaction is not None else status
                ),
                category=category,
                suggestion_conflict=event.suggestion_conflict,
                is_duplicate=False,
            )

        existing_category = (
            await self._categories.get(event.suggested_category_id)
            if event.suggested_category_id is not None
            else None
        )
        return _result_from_event(event, existing_category, is_duplicate=True)

    async def _autosave_event_if_eligible(
        self,
        *,
        event: BankEventModel,
        source: BankEventSourceModel,
        category: CategoryModel | None,
        suggestion_source: BankEventSuggestionSource,
        learning_suggestion: BankLearningSuggestion | None,
    ) -> CreatedTransactionSummary | None:
        if event.operation_kind != BankEventOperationKind.EXPENSE_CANDIDATE.value:
            return None
        if event.parse_status != BankEventParseStatus.NEEDS_CONFIRMATION.value:
            return None
        if event.amount is None or category is None or not category.is_expense:
            return None
        if suggestion_source != BankEventSuggestionSource.LEARNED_RULE:
            return None
        if learning_suggestion is None or learning_suggestion.hit_count < 2:
            return None
        if learning_suggestion.mode != BankCategoryRuleMode.AUTOSAVE:
            return None
        if learning_suggestion.has_parser_conflict:
            return None

        owner = await self._session.get(UserModel, source.owner_user_id)
        if owner is None or not owner.is_active:
            return None

        summary = await self._transactions.create_from_category_selection(
            amount=event.amount,
            category_id=category.id,
            payer_telegram_id=owner.telegram_id,
            raw_text=f"bank_event_autosaved:{event.id}",
            comment=_event_comment(event),
            source=_event_transaction_source(event),
            occurred_at=event.occurred_at,
        )
        linked = await self._bank_events.try_link_transaction(
            event_id=event.id,
            transaction_id=summary.id,
            status=BankEventParseStatus.AUTOSAVED,
            allowed_statuses=(BankEventParseStatus.NEEDS_CONFIRMATION,),
        )
        if linked:
            event.transaction_id = summary.id
            event.parse_status = BankEventParseStatus.AUTOSAVED.value
            return summary

        await self._transactions.delete_transaction(
            transaction_id=summary.id,
            changed_by_telegram_id=owner.telegram_id,
        )
        return None

    async def _resolve_owned_event(
        self,
        event_id: int,
        telegram_user_id: int,
    ) -> BankEventModel:
        event = await self._bank_events.get_event(event_id)
        if event is None:
            msg = f"Bank event does not exist: {event_id}"
            raise ValueError(msg)

        source = await self._bank_events.get_source(event.source_id)
        user = await self._users.get_by_telegram_id(telegram_user_id)
        if source is None or user is None or source.owner_user_id != user.id:
            msg = "Bank event is not available for this user"
            raise ValueError(msg)
        return event

    async def _event_update_result(self, event: BankEventModel) -> BankEventUpdateResult:
        category = (
            await self._categories.get(event.suggested_category_id)
            if event.suggested_category_id is not None
            else None
        )
        return BankEventUpdateResult(
            event_id=event.id,
            operation_kind=BankEventOperationKind(event.operation_kind),
            parse_status=BankEventParseStatus(event.parse_status),
            amount=event.amount,
            currency=event.currency,
            merchant=event.merchant or "",
            counterparty=event.counterparty or "",
            suggested_category_code=category.code if category is not None else None,
            suggested_category_title=category.title if category is not None else None,
            suggested_category_source=_event_suggestion_source(event),
        )

    async def _resolve_category_suggestion(
        self,
        *,
        source: BankEventSourceModel,
        parsed: ParsedBankSms,
        received_at: datetime,
    ) -> tuple[CategoryModel | None, BankEventSuggestionSource, BankLearningSuggestion | None]:
        if parsed.operation_kind == BankEventOperationKind.EXPENSE_CANDIDATE and parsed.merchant:
            learned = await BankLearningService(self._session).find_suggestion(
                owner_user_id=source.owner_user_id,
                bank=parsed.bank.value,
                merchant=parsed.merchant,
                used_at=received_at,
            )
            if learned is not None:
                category = await self._categories.get(learned.category_id)
                if category is not None:
                    parser_category = await self._resolve_suggested_category(
                        parsed.suggested_category_code
                    )
                    learned = replace(
                        learned,
                        has_parser_conflict=(
                            parser_category is not None and parser_category.id != category.id
                        ),
                    )
                    return category, BankEventSuggestionSource.LEARNED_RULE, learned

        category = await self._resolve_suggested_category(parsed.suggested_category_code)
        if category is not None:
            return category, BankEventSuggestionSource.PARSER_HINT, None
        return None, BankEventSuggestionSource.NONE, None


def _initial_parse_status(parsed: ParsedBankSms) -> BankEventParseStatus:
    if parsed.operation_kind == BankEventOperationKind.IGNORED:
        return BankEventParseStatus.IGNORED
    if parsed.operation_kind in {
        BankEventOperationKind.INCOME,
        BankEventOperationKind.INTERNAL_TRANSFER,
        BankEventOperationKind.REFUND,
    }:
        return BankEventParseStatus.PARSED
    return BankEventParseStatus.NEEDS_CONFIRMATION


def _ignore_bank_source_mismatch(
    parsed: ParsedBankSms,
    *,
    expected_bank: BankEventBank,
) -> ParsedBankSms:
    if parsed.operation_kind == BankEventOperationKind.IGNORED:
        return parsed
    if expected_bank == BankEventBank.UNKNOWN:
        return parsed
    if parsed.bank in {expected_bank, BankEventBank.UNKNOWN}:
        return parsed
    return replace(
        parsed,
        operation_kind=BankEventOperationKind.IGNORED,
        amount=None,
        fee_amount=None,
        merchant="",
        counterparty="",
        suggested_category_code=None,
        requires_confirmation=False,
        redacted_text=f"<source_bank_mismatch:{parsed.bank.value}>",
        ignore_reason="source_bank_mismatch",
    )


def _hash_normalized_text(text: str) -> str:
    normalized = " ".join(text.lower().split())
    return sha256(normalized.encode("utf-8")).hexdigest()


def _build_dedupe_key(
    *,
    source_code: str,
    bank: BankEventBank,
    operation_kind: BankEventOperationKind,
    amount: int | None,
    fee_amount: int | None,
    occurred_at: datetime | None,
    received_at: datetime,
    timezone_name: str,
    merchant: str,
    counterparty: str,
    normalized_text_hash: str,
) -> str:
    occurred_at_part = (
        occurred_at.isoformat(timespec="minutes")
        if occurred_at is not None
        else f"received-date:{_local_date_token(received_at, timezone_name)}"
    )
    signature = "|".join(
        (
            source_code,
            bank.value,
            operation_kind.value,
            str(amount or ""),
            str(fee_amount or ""),
            occurred_at_part,
            _normalize_dedupe_text(merchant),
            _normalize_dedupe_text(counterparty),
            normalized_text_hash,
        )
    )
    digest = sha256(signature.encode("utf-8")).hexdigest()
    return f"{source_code}:{bank.value}:{operation_kind.value}:v2:{digest}"


def _local_date_token(value: datetime, timezone_name: str) -> str:
    timezone = ZoneInfo(timezone_name)
    if value.tzinfo is None:
        local_value = value.replace(tzinfo=timezone)
    else:
        local_value = value.astimezone(timezone)
    return local_value.date().isoformat()


def _infer_occurred_at(
    *,
    operation_time: time | None,
    received_at: datetime,
    timezone_name: str,
) -> datetime | None:
    if operation_time is None:
        return None

    timezone = ZoneInfo(timezone_name)
    local_received_at = (
        received_at.replace(tzinfo=timezone)
        if received_at.tzinfo is None
        else received_at.astimezone(timezone)
    )
    occurred_at = datetime.combine(
        local_received_at.date(),
        operation_time,
        tzinfo=timezone,
    )
    if occurred_at - local_received_at > timedelta(hours=12):
        occurred_at -= timedelta(days=1)
    return occurred_at


def _normalize_dedupe_text(value: str) -> str:
    return " ".join(value.lower().split())


def _sender_from_source_bank(bank: BankEventBank) -> str:
    if bank == BankEventBank.SBER:
        return "900"
    if bank == BankEventBank.VTB:
        return "VTB"
    if bank == BankEventBank.TBANK:
        return "T-Bank"
    return ""


def _stored_merchant(parsed: ParsedBankSms) -> str | None:
    return parsed.merchant or None


def _stored_counterparty(parsed: ParsedBankSms) -> str | None:
    if not parsed.counterparty:
        return None
    if parsed.operation_kind == BankEventOperationKind.INTERNAL_TRANSFER:
        return "self"
    return None


def _is_autosaved_linked_event(event: BankEventModel) -> bool:
    return (
        event.parse_status == BankEventParseStatus.AUTOSAVED.value
        and event.transaction_id is not None
    )


def _ensure_not_linked(event: BankEventModel) -> None:
    if event.transaction_id is not None:
        msg = "Bank event is already linked to a transaction"
        raise ValueError(msg)


def _ensure_event_is_actionable(event: BankEventModel) -> None:
    if event.parse_status == BankEventParseStatus.REJECTED.value:
        msg = "Банковское событие уже отмечено как не требующее действий"
        raise ValueError(msg)


def _event_comment(event: BankEventModel) -> str | None:
    if event.merchant:
        return event.merchant
    return f"bank_event:{event.id}"


def _event_transaction_source(event: BankEventModel) -> TransactionSource:
    try:
        return TransactionSource(event.source)
    except ValueError:
        return TransactionSource.UNKNOWN


def _result_from_parsed(
    *,
    event: BankEventModel,
    parsed: ParsedBankSms,
    status: BankEventParseStatus,
    category: CategoryModel | None,
    is_duplicate: bool,
    suggestion_conflict: bool = False,
) -> BankImportResult:
    return BankImportResult(
        event_id=event.id,
        is_duplicate=is_duplicate,
        bank=parsed.bank,
        operation_kind=parsed.operation_kind,
        parse_status=status,
        amount=parsed.amount,
        fee_amount=parsed.fee_amount,
        currency=parsed.currency,
        merchant=parsed.merchant,
        counterparty=parsed.counterparty,
        suggested_category_code=category.code if category is not None else None,
        suggested_category_title=category.title if category is not None else None,
        suggested_category_source=_event_suggestion_source(event),
        requires_confirmation=status == BankEventParseStatus.NEEDS_CONFIRMATION,
        ignore_reason=parsed.ignore_reason,
        redacted_text=parsed.redacted_text,
        occurred_at=event.occurred_at,
        telegram_notification_attempts=event.telegram_notification_attempts,
        telegram_notification_sent_at=event.telegram_notification_sent_at,
        telegram_notification_failed_at=event.telegram_notification_failed_at,
        suggestion_conflict=suggestion_conflict,
    )


def _result_from_event(
    event: BankEventModel,
    category: CategoryModel | None,
    *,
    is_duplicate: bool,
) -> BankImportResult:
    return BankImportResult(
        event_id=event.id,
        is_duplicate=is_duplicate,
        bank=BankEventBank(event.bank),
        operation_kind=BankEventOperationKind(event.operation_kind),
        parse_status=BankEventParseStatus(event.parse_status),
        amount=event.amount,
        fee_amount=event.fee_amount,
        currency=event.currency,
        merchant=event.merchant or "",
        counterparty=event.counterparty or "",
        suggested_category_code=category.code if category is not None else None,
        suggested_category_title=category.title if category is not None else None,
        suggested_category_source=_event_suggestion_source(event),
        requires_confirmation=event.parse_status == BankEventParseStatus.NEEDS_CONFIRMATION.value,
        ignore_reason="",
        redacted_text=event.redacted_text,
        occurred_at=event.occurred_at,
        telegram_notification_attempts=event.telegram_notification_attempts,
        telegram_notification_sent_at=event.telegram_notification_sent_at,
        telegram_notification_failed_at=event.telegram_notification_failed_at,
        suggestion_conflict=event.suggestion_conflict,
    )


def _event_suggestion_source(event: BankEventModel) -> BankEventSuggestionSource:
    if event.suggested_category_source:
        try:
            return BankEventSuggestionSource(event.suggested_category_source)
        except ValueError:
            return BankEventSuggestionSource.NONE
    if event.suggested_category_id is not None:
        return BankEventSuggestionSource.PARSER_HINT
    return BankEventSuggestionSource.NONE
