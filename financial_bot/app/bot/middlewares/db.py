from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from financial_bot.app.storage.db import session_scope

Handler = Callable[[Any, MutableMapping[str, Any]], Awaitable[Any]]


class DbSessionMiddleware:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def __call__(
        self,
        handler: Handler,
        event: Any,
        data: MutableMapping[str, Any],
    ) -> Any:
        async with session_scope(self._session_factory) as session:
            data["session"] = session
            return await handler(event, data)
