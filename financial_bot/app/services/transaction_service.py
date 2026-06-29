from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.expense_input import (
    AMOUNT_WITH_CATEGORY_NUMBER_RE,
    is_internal_transfer_tail,
    parse_amount_with_category_number,
    parse_free_text_expense,
)
from financial_bot.app.domain.types import AuditAction, TransactionSource, TransactionType
from financial_bot.app.services.alias_service import AliasService
from financial_bot.app.storage.models import (
    CategoryModel,
    OperationAuditLogModel,
    TransactionModel,
    UserModel,
)
from financial_bot.app.storage.repositories.audit_repository import AuditRepository
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository

_UNSET: Final = object()


@dataclass(frozen=True, slots=True)
class CategoryOption:
    id: int
    code: str
    title: str
    sort_order: int
    owner_role: str
    is_expense: bool


@dataclass(frozen=True, slots=True)
class CreatedTransactionSummary:
    id: int
    amount: int
    currency: str
    category_code: str
    category_title: str
    payer_role: str
    occurred_at: datetime
    included_in_reports: bool


@dataclass(frozen=True, slots=True)
class BatchLineError:
    line_number: int
    raw_line: str
    message: str


@dataclass(frozen=True, slots=True)
class BatchCreateResult:
    created: tuple[CreatedTransactionSummary, ...]
    errors: tuple[BatchLineError, ...]

    @property
    def total_amount(self) -> int:
        return sum(item.amount for item in self.created)


class TransactionService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._users = UserRepository(session)
        self._categories = CategoryRepository(session)
        self._transactions = TransactionRepository(session)
        self._audit = AuditRepository(session)

    async def list_category_options(self) -> list[CategoryOption]:
        categories = await self._categories.list_active()
        return [
            _to_category_option(category)
            for category in categories
            if category.is_expense and category.sort_order <= 17
        ]

    async def list_income_category_options(self) -> list[CategoryOption]:
        categories = await self._categories.list_active()
        return [
            _to_category_option(category)
            for category in categories
            if _is_selectable_income_category(category)
        ]

    async def create_from_free_text(
        self,
        *,
        text: str,
        current_payer_telegram_id: int,
    ) -> CreatedTransactionSummary:
        parsed = parse_free_text_expense(text)
        creator = await self._resolve_current_user(current_payer_telegram_id)
        payer = await self._resolve_payer(
            current_payer_telegram_id=current_payer_telegram_id,
            explicit_payer_role=parsed.payer_role.value if parsed.payer_role is not None else None,
        )

        if is_internal_transfer_tail(parsed.tail):
            category = await self._resolve_internal_transfer_category()
        else:
            alias_match = await AliasService(self._session).resolve_category(parsed.tail)
            if alias_match is None:
                msg = "Не удалось определить категорию. Укажите номер категории или знакомый алиас."
                raise ValueError(msg)
            category = alias_match.category
            if not _is_selectable_transaction_category(category):
                msg = "Эта категория не является расходом. Для дохода используйте /income."
                raise ValueError(msg)

        return await self._create_transaction(
            amount=parsed.amount,
            category=category,
            payer=payer,
            created_by_user_id=creator.id,
            changed_by_user_id=creator.id,
            raw_text=text,
            source=parsed.source,
            comment=parsed.tail or None,
        )

    async def create_batch_from_text(
        self,
        *,
        text: str,
        current_payer_telegram_id: int,
    ) -> BatchCreateResult:
        created: list[CreatedTransactionSummary] = []
        errors: list[BatchLineError] = []

        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines, start=1):
            try:
                if AMOUNT_WITH_CATEGORY_NUMBER_RE.fullmatch(line):
                    parsed = parse_amount_with_category_number(line)
                    summary = await self.create_from_category_sort_order(
                        amount=parsed.amount,
                        category_sort_order=parsed.category_sort_order,
                        payer_telegram_id=current_payer_telegram_id,
                        raw_text=line,
                        comment=parsed.comment or None,
                    )
                else:
                    summary = await self.create_from_free_text(
                        text=line,
                        current_payer_telegram_id=current_payer_telegram_id,
                    )
                created.append(summary)
            except ValueError as exc:
                errors.append(BatchLineError(index, line, str(exc)))

        return BatchCreateResult(created=tuple(created), errors=tuple(errors))

    async def cancel_transactions(
        self,
        transaction_ids: list[int],
        *,
        changed_by_telegram_id: int,
    ) -> int:
        changed_by = await self._resolve_current_user(changed_by_telegram_id)
        deleted_at = self._now()
        transactions = await self._transactions.list_active_by_ids(transaction_ids)
        for transaction in transactions:
            await self._soft_delete_transaction(
                transaction=transaction,
                changed_by_user_id=changed_by.id,
                deleted_at=deleted_at,
            )
        return len(transactions)

    async def create_from_category_selection(
        self,
        *,
        amount: int,
        category_id: int,
        payer_telegram_id: int,
        raw_text: str | None,
        comment: str | None = None,
        source: TransactionSource = TransactionSource.UNKNOWN,
        occurred_at: datetime | None = None,
    ) -> CreatedTransactionSummary:
        creator = await self._resolve_current_user(payer_telegram_id)
        payer = await self._resolve_payer(
            current_payer_telegram_id=payer_telegram_id,
            explicit_payer_role=None,
        )

        category = await self._categories.get(category_id)
        if category is None:
            msg = f"Category does not exist: {category_id}"
            raise ValueError(msg)
        if not _is_selectable_transaction_category(category):
            msg = f"Category cannot be selected as an expense: {category_id}"
            raise ValueError(msg)

        return await self._create_transaction(
            amount=amount,
            category=category,
            payer=payer,
            created_by_user_id=creator.id,
            changed_by_user_id=creator.id,
            raw_text=raw_text,
            source=source,
            comment=comment,
            occurred_at=occurred_at,
        )

    async def create_correction_from_category_selection(
        self,
        *,
        amount: int,
        category_id: int,
        payer_telegram_id: int,
        raw_text: str | None,
        comment: str | None = None,
        source: TransactionSource = TransactionSource.UNKNOWN,
        occurred_at: datetime | None = None,
    ) -> CreatedTransactionSummary:
        creator = await self._resolve_current_user(payer_telegram_id)
        payer = await self._resolve_payer(
            current_payer_telegram_id=payer_telegram_id,
            explicit_payer_role=None,
        )

        category = await self._categories.get(category_id)
        if category is None:
            msg = f"Category does not exist: {category_id}"
            raise ValueError(msg)
        if not category.is_active or not category.is_expense:
            msg = f"Category cannot be selected for a correction: {category_id}"
            raise ValueError(msg)

        return await self._create_transaction(
            amount=amount,
            category=category,
            payer=payer,
            created_by_user_id=creator.id,
            changed_by_user_id=creator.id,
            raw_text=raw_text,
            source=source,
            comment=comment,
            occurred_at=occurred_at,
            transaction_type=TransactionType.CORRECTION,
        )

    async def create_income(
        self,
        *,
        amount: int,
        recipient_telegram_id: int,
        raw_text: str | None,
        category_code: str = "income_general",
        comment: str | None = None,
        source: TransactionSource = TransactionSource.UNKNOWN,
        occurred_at: datetime | None = None,
    ) -> CreatedTransactionSummary:
        creator = await self._resolve_current_user(recipient_telegram_id)
        recipient = await self._resolve_payer(
            current_payer_telegram_id=recipient_telegram_id,
            explicit_payer_role=None,
        )
        category = await self._resolve_income_category(category_code)

        return await self._create_transaction(
            amount=amount,
            category=category,
            payer=recipient,
            created_by_user_id=creator.id,
            changed_by_user_id=creator.id,
            raw_text=raw_text,
            source=source,
            comment=comment,
            occurred_at=occurred_at,
            transaction_type=TransactionType.INCOME,
        )

    async def create_from_category_sort_order(
        self,
        *,
        amount: int,
        category_sort_order: int,
        payer_telegram_id: int,
        raw_text: str | None,
        comment: str | None = None,
    ) -> CreatedTransactionSummary:
        category = await self._categories.get_by_sort_order(category_sort_order)
        if category is None:
            msg = f"Category sort order does not exist: {category_sort_order}"
            raise ValueError(msg)
        return await self.create_from_category_selection(
            amount=amount,
            category_id=category.id,
            payer_telegram_id=payer_telegram_id,
            raw_text=raw_text,
            comment=comment,
        )

    async def update_transaction(
        self,
        *,
        transaction_id: int,
        changed_by_telegram_id: int,
        amount: int | None = None,
        category_id: int | None = None,
        category_sort_order: int | None = None,
        occurred_at: datetime | None = None,
        payer_telegram_id: int | None = None,
        payer_role: str | None = None,
        comment: str | None | object = _UNSET,
        source: TransactionSource | None = None,
    ) -> CreatedTransactionSummary:
        if category_id is not None and category_sort_order is not None:
            msg = "Use either category_id or category_sort_order, not both"
            raise ValueError(msg)
        if payer_telegram_id is not None and payer_role is not None:
            msg = "Use either payer_telegram_id or payer_role, not both"
            raise ValueError(msg)
        if amount is not None and amount <= 0:
            msg = "Transaction amount must be positive"
            raise ValueError(msg)

        changed_by = await self._resolve_current_user(changed_by_telegram_id)
        transaction = await self._transactions.get_active(transaction_id)
        if transaction is None:
            msg = f"Transaction does not exist or is deleted: {transaction_id}"
            raise ValueError(msg)

        old_value = _transaction_snapshot(transaction)
        changed = False

        if amount is not None and transaction.amount != amount:
            transaction.amount = amount
            changed = True

        category = await self._resolve_update_category(
            category_id=category_id,
            category_sort_order=category_sort_order,
        )
        if category is not None and transaction.category_id != category.id:
            if transaction.type == TransactionType.INCOME.value:
                msg = "Income category cannot be changed through expense editing"
                raise ValueError(msg)
            if transaction.type == TransactionType.CORRECTION.value and (
                not category.is_active or not category.is_expense
            ):
                msg = "Correction category must be an active expense category"
                raise ValueError(msg)
            if transaction.type == TransactionType.EXPENSE.value and not (
                category.is_active and (category.is_expense or category.code == "internal_transfer")
            ):
                msg = "Expense category must be an active expense category or internal transfer"
                raise ValueError(msg)
            transaction.category_id = category.id
            if transaction.type == TransactionType.CORRECTION.value:
                transaction.included_in_reports = True
            else:
                transaction.type = _transaction_type_for_category(category).value
                transaction.included_in_reports = category.is_expense
            changed = True

        if occurred_at is not None and transaction.occurred_at != occurred_at:
            transaction.occurred_at = occurred_at
            changed = True

        payer = await self._resolve_update_payer(
            payer_telegram_id=payer_telegram_id,
            payer_role=payer_role,
        )
        if payer is not None and transaction.payer_user_id != payer.id:
            transaction.payer_user_id = payer.id
            changed = True

        if comment is not _UNSET:
            normalized_comment = _normalize_comment(comment)
            if transaction.comment != normalized_comment:
                transaction.comment = normalized_comment
                changed = True

        if source is not None and transaction.source != source.value:
            transaction.source = source.value
            changed = True

        if changed:
            await self._session.flush()
            await self._write_audit(
                transaction_id=transaction.id,
                action=AuditAction.UPDATE,
                old_value=old_value,
                new_value=_transaction_snapshot(transaction),
                changed_by_user_id=changed_by.id,
            )

        return await self._to_summary(transaction)

    async def delete_transaction(
        self,
        *,
        transaction_id: int,
        changed_by_telegram_id: int,
    ) -> CreatedTransactionSummary:
        changed_by = await self._resolve_current_user(changed_by_telegram_id)
        transaction = await self._transactions.get_active(transaction_id)
        if transaction is None:
            msg = f"Transaction does not exist or is deleted: {transaction_id}"
            raise ValueError(msg)

        await self._soft_delete_transaction(
            transaction=transaction,
            changed_by_user_id=changed_by.id,
            deleted_at=self._now(),
        )
        return await self._to_summary(transaction)

    async def undo_last_transaction(
        self,
        *,
        changed_by_telegram_id: int,
    ) -> CreatedTransactionSummary | None:
        changed_by = await self._resolve_current_user(changed_by_telegram_id)
        transaction = await self._transactions.get_latest_active_by_creator(changed_by.id)
        if transaction is None:
            return None

        await self._soft_delete_transaction(
            transaction=transaction,
            changed_by_user_id=changed_by.id,
            deleted_at=self._now(),
        )
        return await self._to_summary(transaction)

    async def repeat_last_transaction(
        self,
        *,
        changed_by_telegram_id: int,
    ) -> CreatedTransactionSummary | None:
        creator = await self._resolve_current_user(changed_by_telegram_id)
        previous = await self._transactions.get_latest_active_by_creator(creator.id)
        if previous is None:
            return None

        category = await self._categories.get(previous.category_id)
        payer = await self._users.get(previous.payer_user_id)
        if category is None or payer is None:
            msg = f"Transaction dependencies are missing: {previous.id}"
            raise ValueError(msg)
        if not category.is_active:
            return None
        if previous.type != TransactionType.EXPENSE.value:
            return None

        return await self._create_transaction(
            amount=previous.amount,
            category=category,
            payer=payer,
            created_by_user_id=creator.id,
            changed_by_user_id=creator.id,
            raw_text=previous.raw_text,
            source=TransactionSource(previous.source),
            comment=previous.comment,
        )

    async def get_latest_transaction_for_user(
        self,
        *,
        telegram_id: int,
    ) -> CreatedTransactionSummary | None:
        user = await self._resolve_current_user(telegram_id)
        transaction = await self._transactions.get_latest_active_by_creator(user.id)
        if transaction is None:
            return None
        return await self._to_summary(transaction)

    async def _resolve_current_user(self, telegram_id: int) -> UserModel:
        user = await self._users.get_by_telegram_id(telegram_id)
        if user is None:
            msg = f"Telegram user is not seeded: {telegram_id}"
            raise ValueError(msg)
        return user

    async def _resolve_payer(
        self,
        *,
        current_payer_telegram_id: int,
        explicit_payer_role: str | None,
    ) -> UserModel:
        if explicit_payer_role is not None:
            payer = await self._users.get_by_role(explicit_payer_role)
        else:
            payer = await self._users.get_by_telegram_id(current_payer_telegram_id)
        if payer is None:
            msg = f"Telegram user is not seeded: {current_payer_telegram_id}"
            raise ValueError(msg)
        return payer

    async def _resolve_update_category(
        self,
        *,
        category_id: int | None,
        category_sort_order: int | None,
    ) -> CategoryModel | None:
        if category_id is not None:
            category = await self._categories.get(category_id)
            label = category_id
        elif category_sort_order is not None:
            category = await self._categories.get_by_sort_order(category_sort_order)
            label = category_sort_order
        else:
            return None

        if category is None:
            msg = f"Category does not exist: {label}"
            raise ValueError(msg)
        return category

    async def _resolve_internal_transfer_category(self) -> CategoryModel:
        category = await self._categories.get_by_code("internal_transfer")
        if category is None:
            msg = "Internal transfer category is not seeded"
            raise ValueError(msg)
        return category

    async def _resolve_income_category(self, category_code: str) -> CategoryModel:
        category = await self._categories.get_by_code(category_code)
        if category is None:
            msg = f"Income category is not seeded: {category_code}"
            raise ValueError(msg)
        if not _is_selectable_income_category(category):
            msg = "Income category must not be an expense category"
            raise ValueError(msg)
        return category

    async def _resolve_update_payer(
        self,
        *,
        payer_telegram_id: int | None,
        payer_role: str | None,
    ) -> UserModel | None:
        if payer_telegram_id is not None:
            payer = await self._users.get_by_telegram_id(payer_telegram_id)
            label: int | str = payer_telegram_id
        elif payer_role is not None:
            payer = await self._users.get_by_role(payer_role)
            label = payer_role
        else:
            return None

        if payer is None:
            msg = f"Payer does not exist: {label}"
            raise ValueError(msg)
        return payer

    async def _create_transaction(
        self,
        *,
        amount: int,
        category: CategoryModel,
        payer: UserModel,
        created_by_user_id: int,
        changed_by_user_id: int,
        raw_text: str | None,
        source: TransactionSource,
        comment: str | None,
        occurred_at: datetime | None = None,
        transaction_type: TransactionType | None = None,
    ) -> CreatedTransactionSummary:
        if amount <= 0:
            msg = "Transaction amount must be positive"
            raise ValueError(msg)

        resolved_transaction_type = transaction_type or _transaction_type_for_category(category)
        included_in_reports = (
            True if resolved_transaction_type == TransactionType.CORRECTION else category.is_expense
        )
        transaction_occurred_at = occurred_at or self._now()

        transaction = await self._transactions.add(
            TransactionModel(
                amount=amount,
                currency=self._settings.default_currency,
                occurred_at=transaction_occurred_at,
                payer_user_id=payer.id,
                category_id=category.id,
                type=resolved_transaction_type.value,
                source=source.value,
                comment=_normalize_comment(comment),
                raw_text=raw_text,
                included_in_reports=included_in_reports,
                created_by_user_id=created_by_user_id,
            )
        )
        await self._write_audit(
            transaction_id=transaction.id,
            action=AuditAction.CREATE,
            old_value=None,
            new_value=_transaction_snapshot(transaction),
            changed_by_user_id=changed_by_user_id,
        )

        return await self._to_summary(transaction)

    async def _soft_delete_transaction(
        self,
        *,
        transaction: TransactionModel,
        changed_by_user_id: int,
        deleted_at: datetime,
    ) -> None:
        old_value = _transaction_snapshot(transaction)
        await self._transactions.soft_delete(transaction, deleted_at)
        await self._write_audit(
            transaction_id=transaction.id,
            action=AuditAction.DELETE,
            old_value=old_value,
            new_value=_transaction_snapshot(transaction),
            changed_by_user_id=changed_by_user_id,
        )

    async def _write_audit(
        self,
        *,
        transaction_id: int,
        action: AuditAction,
        old_value: dict[str, Any] | None,
        new_value: dict[str, Any] | None,
        changed_by_user_id: int,
    ) -> None:
        await self._audit.add(
            OperationAuditLogModel(
                transaction_id=transaction_id,
                action=action.value,
                old_value=old_value,
                new_value=new_value,
                changed_by_user_id=changed_by_user_id,
                changed_at=self._now(),
            )
        )

    async def _to_summary(self, transaction: TransactionModel) -> CreatedTransactionSummary:
        category = await self._categories.get(transaction.category_id)
        payer = await self._users.get(transaction.payer_user_id)
        if category is None or payer is None:
            msg = f"Transaction dependencies are missing: {transaction.id}"
            raise ValueError(msg)

        return CreatedTransactionSummary(
            id=transaction.id,
            amount=transaction.amount,
            currency=transaction.currency,
            category_code=category.code,
            category_title=category.title,
            payer_role=payer.role,
            occurred_at=transaction.occurred_at,
            included_in_reports=transaction.included_in_reports,
        )

    def _now(self) -> datetime:
        return datetime.now(ZoneInfo(self._settings.timezone))


def _to_category_option(category: CategoryModel) -> CategoryOption:
    return CategoryOption(
        id=category.id,
        code=category.code,
        title=category.title,
        sort_order=category.sort_order,
        owner_role=category.owner_role,
        is_expense=category.is_expense,
    )


def _transaction_type_for_category(category: CategoryModel) -> TransactionType:
    return TransactionType.EXPENSE if category.is_expense else TransactionType.INTERNAL_TRANSFER


def _is_selectable_transaction_category(category: CategoryModel) -> bool:
    return category.is_active and (category.is_expense or category.code == "internal_transfer")


def _is_selectable_income_category(category: CategoryModel) -> bool:
    return (
        category.is_active
        and not category.is_expense
        and (category.code == "income_general" or category.code.startswith("income_"))
    )


def _normalize_comment(comment: str | None | object) -> str | None:
    if comment is None or comment is _UNSET:
        return None
    if not isinstance(comment, str):
        msg = "Comment must be a string or None"
        raise ValueError(msg)
    return comment.strip() or None


def _transaction_snapshot(transaction: TransactionModel) -> dict[str, Any]:
    return {
        "id": transaction.id,
        "amount": transaction.amount,
        "currency": transaction.currency,
        "occurred_at": _datetime_to_iso(transaction.occurred_at),
        "payer_user_id": transaction.payer_user_id,
        "category_id": transaction.category_id,
        "type": transaction.type,
        "source": transaction.source,
        "comment": transaction.comment,
        "raw_text": transaction.raw_text,
        "included_in_reports": transaction.included_in_reports,
        "created_by_user_id": transaction.created_by_user_id,
        "deleted_at": _datetime_to_iso(transaction.deleted_at),
    }


def _datetime_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()
