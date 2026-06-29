from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.categories import DEFAULT_CATEGORIES, DEFAULT_CATEGORY_ALIASES
from financial_bot.app.domain.types import CategoryOwnerRole, UserRole
from financial_bot.app.services.spending_limit_service import SpendingLimitService
from financial_bot.app.storage.models import CategoryAliasModel, CategoryModel, UserModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class SeedResult:
    users_created: int = 0
    users_updated: int = 0
    categories_created: int = 0
    categories_updated: int = 0
    aliases_created: int = 0
    aliases_updated: int = 0

    def merge(self, other: "SeedResult") -> "SeedResult":
        return SeedResult(
            users_created=self.users_created + other.users_created,
            users_updated=self.users_updated + other.users_updated,
            categories_created=self.categories_created + other.categories_created,
            categories_updated=self.categories_updated + other.categories_updated,
            aliases_created=self.aliases_created + other.aliases_created,
            aliases_updated=self.aliases_updated + other.aliases_updated,
        )


async def seed_initial_data(session: AsyncSession, settings: Settings) -> SeedResult:
    users = UserRepository(session)
    categories = CategoryRepository(session)

    husband_result, husband = await _ensure_user(
        users,
        role=UserRole.HUSBAND,
        telegram_id=settings.husband_telegram_id,
        name="Husband",
    )
    wife_result, wife = await _ensure_user(
        users,
        role=UserRole.WIFE,
        telegram_id=settings.wife_telegram_id,
        name="Wife",
    )
    result = husband_result.merge(wife_result)

    owner_ids = {
        CategoryOwnerRole.HUSBAND: husband.id,
        CategoryOwnerRole.WIFE: wife.id,
        CategoryOwnerRole.SYSTEM: None,
    }

    category_by_code: dict[str, CategoryModel] = {}
    for category_seed in DEFAULT_CATEGORIES:
        category_result, category = await _ensure_category(
            categories,
            code=category_seed.code,
            title=category_seed.title,
            owner_user_id=owner_ids[category_seed.owner_role],
            owner_role=category_seed.owner_role,
            sort_order=category_seed.sort_order,
            is_expense=category_seed.is_expense,
            is_active=category_seed.is_active,
        )
        result = result.merge(category_result)
        category_by_code[category.code] = category

    for alias_seed in DEFAULT_CATEGORY_ALIASES:
        category = category_by_code[alias_seed.category_code]
        alias_result = await _ensure_alias(categories, alias_seed.alias, category.id)
        result = result.merge(alias_result)

    await SpendingLimitService(session, settings).ensure_default_config()

    return result


async def _ensure_user(
    users: UserRepository,
    *,
    role: UserRole,
    telegram_id: int,
    name: str,
) -> tuple[SeedResult, UserModel]:
    existing_user = await users.get_by_role(role.value)
    if existing_user is None:
        user_with_same_telegram_id = await users.get_by_telegram_id(telegram_id)
        if user_with_same_telegram_id is not None:
            assigned_role = user_with_same_telegram_id.role
            msg = f"Telegram ID {telegram_id} is already assigned to role {assigned_role}"
            raise ValueError(msg)
        user = await users.add(
            UserModel(
                telegram_id=telegram_id,
                name=name,
                role=role.value,
                is_active=True,
            )
        )
        return SeedResult(users_created=1), user

    existing_user.telegram_id = telegram_id
    existing_user.name = name
    existing_user.is_active = True
    return SeedResult(users_updated=1), existing_user


async def _ensure_category(
    categories: CategoryRepository,
    *,
    code: str,
    title: str,
    owner_user_id: int | None,
    owner_role: CategoryOwnerRole,
    sort_order: int,
    is_expense: bool,
    is_active: bool,
) -> tuple[SeedResult, CategoryModel]:
    existing_category = await categories.get_by_code(code)
    if existing_category is None:
        category = await categories.add(
            CategoryModel(
                code=code,
                title=title,
                owner_user_id=owner_user_id,
                owner_role=owner_role.value,
                sort_order=sort_order,
                is_expense=is_expense,
                is_active=is_active,
            )
        )
        return SeedResult(categories_created=1), category

    # Category titles are user-facing settings and may be renamed from the bot.
    # Keep the stored title stable across repeated seeds.
    existing_category.owner_user_id = owner_user_id
    existing_category.owner_role = owner_role.value
    existing_category.sort_order = sort_order
    existing_category.is_expense = is_expense
    existing_category.is_active = is_active
    return SeedResult(categories_updated=1), existing_category


async def _ensure_alias(
    categories: CategoryRepository,
    alias: str,
    category_id: int,
) -> SeedResult:
    normalized_alias = alias.strip().lower()
    existing_alias = await categories.get_alias(normalized_alias)
    if existing_alias is None:
        await categories.add_alias(
            CategoryAliasModel(alias=normalized_alias, category_id=category_id)
        )
        return SeedResult(aliases_created=1)

    existing_alias.category_id = category_id
    return SeedResult(aliases_updated=1)
