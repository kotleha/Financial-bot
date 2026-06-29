import re
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import CategoryModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository


@dataclass(frozen=True, slots=True)
class AliasMatch:
    alias: str
    category: CategoryModel


class AliasService:
    def __init__(self, session: AsyncSession) -> None:
        self._categories = CategoryRepository(session)

    async def resolve_category(self, text: str) -> AliasMatch | None:
        text_tokens = _tokenize_alias_text(text)
        if not text_tokens:
            return None

        aliases = await self._categories.list_aliases()
        for alias in sorted(aliases, key=lambda item: len(item.alias), reverse=True):
            alias_tokens = _tokenize_alias_text(alias.alias)
            if not _is_safe_alias_tokens(alias_tokens):
                continue
            if _contains_token_phrase(text_tokens, alias_tokens):
                category = await self._categories.get(alias.category_id)
                if category is None:
                    continue
                return AliasMatch(alias=alias.alias, category=category)
        return None


TOKEN_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)
MIN_ALIAS_TOKEN_CHARS = 3


def _tokenize_alias_text(text: str) -> tuple[str, ...]:
    normalized = text.strip().lower().replace("ё", "е")
    return tuple(TOKEN_RE.findall(normalized))


def _is_safe_alias_tokens(tokens: tuple[str, ...]) -> bool:
    if not tokens:
        return False
    return len("".join(tokens)) >= MIN_ALIAS_TOKEN_CHARS


def _contains_token_phrase(text_tokens: tuple[str, ...], alias_tokens: tuple[str, ...]) -> bool:
    if not alias_tokens or len(alias_tokens) > len(text_tokens):
        return False
    alias_length = len(alias_tokens)
    return any(
        text_tokens[index : index + alias_length] == alias_tokens
        for index in range(len(text_tokens) - alias_length + 1)
    )
