from collections.abc import Awaitable, Callable, MutableMapping
from inspect import isawaitable
from typing import Any, Protocol

from financial_bot.app.services.auth_service import TelegramAuthPolicy


class TelegramUserLike(Protocol):
    id: int


class TelegramEventLike(Protocol):
    from_user: TelegramUserLike | None


Handler = Callable[[Any, MutableMapping[str, Any]], Awaitable[Any]]


class AuthMiddleware:
    """Reject updates from Telegram users outside the whitelist."""

    def __init__(
        self,
        auth_policy: TelegramAuthPolicy,
        denial_message: str = "Access denied.",
    ) -> None:
        self._auth_policy = auth_policy
        self._denial_message = denial_message

    async def __call__(
        self,
        handler: Handler,
        event: TelegramEventLike,
        data: MutableMapping[str, Any],
    ) -> Any:
        telegram_id = getattr(getattr(event, "from_user", None), "id", None)
        auth_result = self._auth_policy.authorize(telegram_id)
        if auth_result.allowed:
            data["telegram_user_id"] = telegram_id
            return await handler(event, data)

        await self._reply_with_denial(event)
        return None

    async def _reply_with_denial(self, event: TelegramEventLike) -> None:
        answer = getattr(event, "answer", None)
        if answer is None:
            return

        result = answer(self._denial_message)
        if isawaitable(result):
            await result
