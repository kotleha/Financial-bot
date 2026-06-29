from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import CategoryAliasModel, CategoryModel


class CategoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, category: CategoryModel) -> CategoryModel:
        self._session.add(category)
        await self._session.flush()
        return category

    async def add_alias(self, alias: CategoryAliasModel) -> CategoryAliasModel:
        self._session.add(alias)
        await self._session.flush()
        return alias

    async def get(self, category_id: int) -> CategoryModel | None:
        return await self._session.get(CategoryModel, category_id)

    async def get_by_code(self, code: str) -> CategoryModel | None:
        result = await self._session.execute(
            select(CategoryModel).where(CategoryModel.code == code)
        )
        return result.scalar_one_or_none()

    async def get_by_sort_order(self, sort_order: int) -> CategoryModel | None:
        result = await self._session.execute(
            select(CategoryModel)
            .where(CategoryModel.sort_order == sort_order)
            .where(CategoryModel.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_alias(self, alias: str) -> CategoryModel | None:
        normalized_alias = alias.strip().lower()
        result = await self._session.execute(
            select(CategoryModel)
            .join(CategoryAliasModel)
            .where(CategoryAliasModel.alias == normalized_alias)
            .where(CategoryModel.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_alias(self, alias: str) -> CategoryAliasModel | None:
        normalized_alias = alias.strip().lower()
        result = await self._session.execute(
            select(CategoryAliasModel).where(CategoryAliasModel.alias == normalized_alias)
        )
        return result.scalar_one_or_none()

    async def list_aliases(self) -> list[CategoryAliasModel]:
        result = await self._session.execute(
            select(CategoryAliasModel).order_by(CategoryAliasModel.alias)
        )
        return list(result.scalars())

    async def list_aliases_by_category_id(self, category_id: int) -> list[CategoryAliasModel]:
        result = await self._session.execute(
            select(CategoryAliasModel)
            .where(CategoryAliasModel.category_id == category_id)
            .order_by(CategoryAliasModel.alias)
        )
        return list(result.scalars())

    async def list_active(self) -> list[CategoryModel]:
        result = await self._session.execute(
            select(CategoryModel)
            .where(CategoryModel.is_active.is_(True))
            .order_by(CategoryModel.sort_order)
        )
        return list(result.scalars())
