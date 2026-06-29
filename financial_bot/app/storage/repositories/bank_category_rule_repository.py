from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import BankCategoryRuleModel


class BankCategoryRuleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, rule: BankCategoryRuleModel) -> BankCategoryRuleModel:
        self._session.add(rule)
        await self._session.flush()
        return rule

    async def get(self, rule_id: int) -> BankCategoryRuleModel | None:
        return await self._session.get(BankCategoryRuleModel, rule_id)

    async def get_for_owner(
        self,
        *,
        rule_id: int,
        owner_user_id: int,
    ) -> BankCategoryRuleModel | None:
        result = await self._session.execute(
            select(BankCategoryRuleModel)
            .where(BankCategoryRuleModel.id == rule_id)
            .where(BankCategoryRuleModel.owner_user_id == owner_user_id)
        )
        return result.scalar_one_or_none()

    async def list_by_owner(
        self,
        *,
        owner_user_id: int,
        limit: int = 20,
    ) -> list[BankCategoryRuleModel]:
        result = await self._session.execute(
            select(BankCategoryRuleModel)
            .where(BankCategoryRuleModel.owner_user_id == owner_user_id)
            .order_by(
                BankCategoryRuleModel.is_active.desc(),
                BankCategoryRuleModel.last_confirmed_at.desc(),
                BankCategoryRuleModel.id.desc(),
            )
            .limit(limit)
        )
        return list(result.scalars())

    async def get_active_rule(
        self,
        *,
        owner_user_id: int,
        bank: str,
        merchant_key: str,
    ) -> BankCategoryRuleModel | None:
        result = await self._session.execute(
            select(BankCategoryRuleModel)
            .where(BankCategoryRuleModel.owner_user_id == owner_user_id)
            .where(BankCategoryRuleModel.bank == bank)
            .where(BankCategoryRuleModel.merchant_key == merchant_key)
            .where(BankCategoryRuleModel.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_rule(
        self,
        *,
        owner_user_id: int,
        bank: str,
        merchant_key: str,
    ) -> BankCategoryRuleModel | None:
        result = await self._session.execute(
            select(BankCategoryRuleModel)
            .where(BankCategoryRuleModel.owner_user_id == owner_user_id)
            .where(BankCategoryRuleModel.bank == bank)
            .where(BankCategoryRuleModel.merchant_key == merchant_key)
        )
        return result.scalar_one_or_none()

    async def upsert_rule(
        self,
        *,
        owner_user_id: int,
        bank: str,
        merchant_key: str,
        merchant_display: str,
        category_id: int,
        confirmed_at: datetime,
    ) -> BankCategoryRuleModel:
        rule = await self.get_rule(
            owner_user_id=owner_user_id,
            bank=bank,
            merchant_key=merchant_key,
        )
        if rule is None:
            return await self.add(
                BankCategoryRuleModel(
                    owner_user_id=owner_user_id,
                    bank=bank,
                    merchant_key=merchant_key,
                    merchant_display=merchant_display,
                    category_id=category_id,
                    hit_count=1,
                    is_active=True,
                    last_confirmed_at=confirmed_at,
                )
            )

        if rule.category_id == category_id:
            rule.hit_count += 1
        else:
            rule.hit_count = 1
        rule.category_id = category_id
        rule.merchant_display = merchant_display
        rule.is_active = True
        rule.last_confirmed_at = confirmed_at
        await self._session.flush()
        return rule

    async def mark_used(
        self,
        rule: BankCategoryRuleModel,
        *,
        used_at: datetime,
    ) -> BankCategoryRuleModel:
        rule.last_used_at = used_at
        await self._session.flush()
        return rule
