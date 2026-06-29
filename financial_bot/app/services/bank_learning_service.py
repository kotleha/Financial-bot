from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.bank_learning import normalize_bank_merchant_key
from financial_bot.app.domain.types import BankEventOperationKind
from financial_bot.app.storage.models import BankEventModel, BankEventSourceModel
from financial_bot.app.storage.repositories.bank_category_rule_repository import (
    BankCategoryRuleRepository,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository


@dataclass(frozen=True, slots=True)
class BankLearningSuggestion:
    rule_id: int
    category_id: int
    category_code: str
    category_title: str
    merchant_key: str
    hit_count: int


@dataclass(frozen=True, slots=True)
class BankLearningRuleFeedback:
    rule_id: int
    action: str
    merchant_display: str
    category_title: str
    hit_count: int


class BankLearningService:
    def __init__(self, session: AsyncSession) -> None:
        self._categories = CategoryRepository(session)
        self._rules = BankCategoryRuleRepository(session)

    async def find_suggestion(
        self,
        *,
        owner_user_id: int,
        bank: str,
        merchant: str,
        used_at: datetime,
    ) -> BankLearningSuggestion | None:
        merchant_key = normalize_bank_merchant_key(merchant)
        if not merchant_key:
            return None

        rule = await self._rules.get_active_rule(
            owner_user_id=owner_user_id,
            bank=bank,
            merchant_key=merchant_key,
        )
        if rule is None:
            return None

        category = await self._categories.get(rule.category_id)
        if category is None or not category.is_active or not category.is_expense:
            return None

        await self._rules.mark_used(rule, used_at=used_at)
        return BankLearningSuggestion(
            rule_id=rule.id,
            category_id=category.id,
            category_code=category.code,
            category_title=category.title,
            merchant_key=rule.merchant_key,
            hit_count=rule.hit_count,
        )

    async def learn_from_confirmed_event(
        self,
        *,
        event: BankEventModel,
        source: BankEventSourceModel,
        confirmed_at: datetime,
    ) -> BankLearningRuleFeedback | None:
        if event.operation_kind != BankEventOperationKind.EXPENSE_CANDIDATE.value:
            return None
        if event.suggested_category_id is None or not event.merchant:
            return None

        merchant_key = normalize_bank_merchant_key(event.merchant)
        if not merchant_key:
            return None

        category = await self._categories.get(event.suggested_category_id)
        if category is None or not category.is_active or not category.is_expense:
            return None

        existing_rule = await self._rules.get_rule(
            owner_user_id=source.owner_user_id,
            bank=event.bank,
            merchant_key=merchant_key,
        )
        if existing_rule is None:
            action = "created"
        elif existing_rule.category_id == category.id:
            action = "reinforced"
        else:
            action = "updated"

        rule = await self._rules.upsert_rule(
            owner_user_id=source.owner_user_id,
            bank=event.bank,
            merchant_key=merchant_key,
            merchant_display=event.merchant,
            category_id=category.id,
            confirmed_at=confirmed_at,
        )
        return BankLearningRuleFeedback(
            rule_id=rule.id,
            action=action,
            merchant_display=rule.merchant_display,
            category_title=category.title,
            hit_count=rule.hit_count,
        )
