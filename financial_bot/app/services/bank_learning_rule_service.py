from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.services.transaction_service import CategoryOption
from financial_bot.app.storage.models import BankCategoryRuleModel, CategoryModel
from financial_bot.app.storage.repositories.bank_category_rule_repository import (
    BankCategoryRuleRepository,
)
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class BankLearningRuleLine:
    id: int
    bank: str
    merchant_display: str
    category_title: str
    hit_count: int
    is_active: bool
    last_confirmed_at: datetime | None


@dataclass(frozen=True, slots=True)
class BankLearningRuleDetails:
    id: int
    bank: str
    merchant_display: str
    merchant_key: str
    category_id: int
    category_title: str
    hit_count: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    last_confirmed_at: datetime | None
    last_used_at: datetime | None


@dataclass(frozen=True, slots=True)
class BankLearningRuleUpdateResult:
    rule_id: int
    bank: str
    merchant_display: str
    old_category_title: str
    new_category_title: str
    is_active: bool


@dataclass(frozen=True, slots=True)
class BankLearningRuleStatusResult:
    rule_id: int
    bank: str
    merchant_display: str
    category_title: str
    is_active: bool


class BankLearningRuleService:
    def __init__(self, session: AsyncSession) -> None:
        self._users = UserRepository(session)
        self._categories = CategoryRepository(session)
        self._rules = BankCategoryRuleRepository(session)

    async def list_rules(
        self,
        *,
        telegram_user_id: int,
        limit: int = 20,
    ) -> tuple[BankLearningRuleLine, ...]:
        user = await self._resolve_user(telegram_user_id)
        rules = await self._rules.list_by_owner(owner_user_id=user.id, limit=limit)
        return tuple([await self._to_line(rule) for rule in rules])

    async def get_rule_details(
        self,
        *,
        rule_id: int,
        telegram_user_id: int,
    ) -> BankLearningRuleDetails:
        rule = await self._get_owned_rule(rule_id=rule_id, telegram_user_id=telegram_user_id)
        category = await self._categories.get(rule.category_id)
        return _to_details(rule, category)

    async def list_expense_categories(self) -> tuple[CategoryOption, ...]:
        categories = await self._categories.list_active()
        return tuple(
            CategoryOption(
                id=category.id,
                code=category.code,
                title=category.title,
                sort_order=category.sort_order,
                owner_role="system",
                is_expense=category.is_expense,
            )
            for category in categories
            if category.is_expense and category.sort_order <= 17
        )

    async def update_rule_category(
        self,
        *,
        rule_id: int,
        category_id: int,
        telegram_user_id: int,
    ) -> BankLearningRuleUpdateResult:
        rule = await self._get_owned_rule(rule_id=rule_id, telegram_user_id=telegram_user_id)
        old_category = await self._categories.get(rule.category_id)
        new_category = await self._categories.get(category_id)
        if new_category is None or not new_category.is_active or not new_category.is_expense:
            raise ValueError("Категория недоступна для банковского правила.")
        if new_category.sort_order > 17:
            raise ValueError("Служебную категорию нельзя назначить банковскому правилу.")

        old_title = _category_title(old_category)
        rule.category_id = new_category.id
        rule.is_active = True
        return BankLearningRuleUpdateResult(
            rule_id=rule.id,
            bank=rule.bank,
            merchant_display=rule.merchant_display,
            old_category_title=old_title,
            new_category_title=new_category.title,
            is_active=rule.is_active,
        )

    async def set_rule_active(
        self,
        *,
        rule_id: int,
        telegram_user_id: int,
        is_active: bool,
    ) -> BankLearningRuleStatusResult:
        rule = await self._get_owned_rule(rule_id=rule_id, telegram_user_id=telegram_user_id)
        category = await self._categories.get(rule.category_id)
        rule.is_active = is_active
        return BankLearningRuleStatusResult(
            rule_id=rule.id,
            bank=rule.bank,
            merchant_display=rule.merchant_display,
            category_title=_category_title(category),
            is_active=rule.is_active,
        )

    async def _resolve_user(self, telegram_user_id: int):
        user = await self._users.get_by_telegram_id(telegram_user_id)
        if user is None or not user.is_active:
            raise ValueError("Пользователь не найден.")
        return user

    async def _get_owned_rule(
        self,
        *,
        rule_id: int,
        telegram_user_id: int,
    ) -> BankCategoryRuleModel:
        user = await self._resolve_user(telegram_user_id)
        rule = await self._rules.get_for_owner(rule_id=rule_id, owner_user_id=user.id)
        if rule is None:
            raise ValueError("Правило не найдено.")
        return rule

    async def _to_line(self, rule: BankCategoryRuleModel) -> BankLearningRuleLine:
        category = await self._categories.get(rule.category_id)
        return BankLearningRuleLine(
            id=rule.id,
            bank=rule.bank,
            merchant_display=rule.merchant_display,
            category_title=_category_title(category),
            hit_count=rule.hit_count,
            is_active=rule.is_active,
            last_confirmed_at=rule.last_confirmed_at,
        )


def _to_details(
    rule: BankCategoryRuleModel,
    category: CategoryModel | None,
) -> BankLearningRuleDetails:
    return BankLearningRuleDetails(
        id=rule.id,
        bank=rule.bank,
        merchant_display=rule.merchant_display,
        merchant_key=rule.merchant_key,
        category_id=rule.category_id,
        category_title=_category_title(category),
        hit_count=rule.hit_count,
        is_active=rule.is_active,
        created_at=rule.created_at,
        updated_at=rule.updated_at,
        last_confirmed_at=rule.last_confirmed_at,
        last_used_at=rule.last_used_at,
    )


def _category_title(category: CategoryModel | None) -> str:
    if category is None:
        return "категория недоступна"
    return category.title
