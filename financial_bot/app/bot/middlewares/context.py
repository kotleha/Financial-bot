from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from financial_bot.app.config import Settings

Handler = Callable[[Any, MutableMapping[str, Any]], Awaitable[Any]]


class SettingsMiddleware:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def __call__(
        self,
        handler: Handler,
        event: Any,
        data: MutableMapping[str, Any],
    ) -> Any:
        data["settings"] = self._settings
        return await handler(event, data)
