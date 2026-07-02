from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.categories import VISIBLE_EXPENSE_SORT_ORDER_MAX
from financial_bot.app.storage.models import CategoryAliasModel, CategoryModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository

MAX_CATEGORY_TITLE_LENGTH = 80
MAX_CATEGORY_ALIAS_LENGTH = 120
MIN_CATEGORY_ALIAS_LENGTH = 2


@dataclass(frozen=True, slots=True)
class CategorySettingsLine:
    code: str
    title: str
    sort_order: int
    alias_count: int


@dataclass(frozen=True, slots=True)
class CategorySettingsDetails:
    code: str
    title: str
    sort_order: int
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CategoryRenameResult:
    code: str
    old_title: str
    new_title: str
    sort_order: int


@dataclass(frozen=True, slots=True)
class CategoryAliasAddResult:
    category_code: str
    category_title: str
    alias: str
    sort_order: int


class CategorySettingsService:
    def __init__(self, session: AsyncSession) -> None:
        self._categories = CategoryRepository(session)

    async def list_categories(self) -> tuple[CategorySettingsLine, ...]:
        categories = await self._list_editable_categories()
        aliases = await self._categories.list_aliases()
        alias_counts: dict[int, int] = {}
        for alias in aliases:
            alias_counts[alias.category_id] = alias_counts.get(alias.category_id, 0) + 1

        return tuple(
            CategorySettingsLine(
                code=category.code,
                title=category.title,
                sort_order=category.sort_order,
                alias_count=alias_counts.get(category.id, 0),
            )
            for category in categories
        )

    async def get_category_details(self, category_code: str) -> CategorySettingsDetails | None:
        category = await self._get_editable_category(category_code)
        if category is None:
            return None
        aliases = await self._categories.list_aliases_by_category_id(category.id)
        return CategorySettingsDetails(
            code=category.code,
            title=category.title,
            sort_order=category.sort_order,
            aliases=tuple(alias.alias for alias in aliases),
        )

    async def rename_category(
        self,
        *,
        category_code: str,
        new_title: str,
    ) -> CategoryRenameResult:
        category = await self._get_editable_category(category_code)
        if category is None:
            raise ValueError("Категория недоступна для изменения.")

        normalized_title = normalize_category_title(new_title)
        validate_category_title(normalized_title)

        old_title = category.title
        category.title = normalized_title
        return CategoryRenameResult(
            code=category.code,
            old_title=old_title,
            new_title=category.title,
            sort_order=category.sort_order,
        )

    async def add_alias(
        self,
        *,
        category_code: str,
        alias: str,
    ) -> CategoryAliasAddResult:
        category = await self._get_editable_category(category_code)
        if category is None:
            raise ValueError("Категория недоступна для изменения.")

        normalized_alias = normalize_category_alias(alias)
        validate_category_alias(normalized_alias)
        await self._ensure_alias_available(normalized_alias, category)
        await self._categories.add_alias(
            CategoryAliasModel(alias=normalized_alias, category_id=category.id)
        )
        return CategoryAliasAddResult(
            category_code=category.code,
            category_title=category.title,
            alias=normalized_alias,
            sort_order=category.sort_order,
        )

    async def validate_alias_for_category(self, *, category_code: str, alias: str) -> str:
        category = await self._get_editable_category(category_code)
        if category is None:
            raise ValueError("Категория недоступна для изменения.")

        normalized_alias = normalize_category_alias(alias)
        validate_category_alias(normalized_alias)
        await self._ensure_alias_available(normalized_alias, category)
        return normalized_alias

    async def _list_editable_categories(self) -> list[CategoryModel]:
        return [
            category
            for category in await self._categories.list_active()
            if _is_editable_expense_category(category)
        ]

    async def _get_editable_category(self, category_code: str) -> CategoryModel | None:
        category = await self._categories.get_by_code(category_code)
        if category is None or not _is_editable_expense_category(category):
            return None
        return category

    async def _ensure_alias_available(
        self,
        alias: str,
        category: CategoryModel,
    ) -> None:
        existing_alias = await self._categories.get_alias(alias)
        if existing_alias is None:
            return

        if existing_alias.category_id == category.id:
            raise ValueError("Такой алиас уже есть у этой категории.")

        existing_category = await self._categories.get(existing_alias.category_id)
        existing_title = existing_category.title if existing_category is not None else "другой"
        raise ValueError(f"Алиас уже занят категорией «{existing_title}».")


def normalize_category_title(title: str | None) -> str:
    return " ".join((title or "").split())


def validate_category_title(title: str) -> None:
    if not title:
        raise ValueError("Название категории не может быть пустым.")
    if len(title) > MAX_CATEGORY_TITLE_LENGTH:
        raise ValueError(f"Название категории должно быть не длиннее {MAX_CATEGORY_TITLE_LENGTH}.")


def normalize_category_alias(alias: str | None) -> str:
    return " ".join((alias or "").lower().split())


def validate_category_alias(alias: str) -> None:
    if not alias:
        raise ValueError("Алиас не может быть пустым.")
    if len(alias) < MIN_CATEGORY_ALIAS_LENGTH:
        raise ValueError("Алиас должен быть не короче двух символов.")
    if len(alias) > MAX_CATEGORY_ALIAS_LENGTH:
        raise ValueError(f"Алиас должен быть не длиннее {MAX_CATEGORY_ALIAS_LENGTH}.")
    if alias.replace(" ", "").isdecimal():
        raise ValueError("Числовой алиас опасен: он может конфликтовать с номерами категорий.")
    if not any(char.isalnum() for char in alias):
        raise ValueError("Алиас должен содержать хотя бы одну букву или цифру.")


def _is_editable_expense_category(category: CategoryModel) -> bool:
    return (
        category.is_active
        and category.is_expense
        and category.sort_order <= VISIBLE_EXPENSE_SORT_ORDER_MAX
    )
