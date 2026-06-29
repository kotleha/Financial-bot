from collections.abc import MutableMapping
from dataclasses import dataclass
from typing import Any

import pytest
from financial_bot.app.bot.middlewares.auth import AuthMiddleware
from financial_bot.app.services.auth_service import TelegramAuthPolicy


@dataclass(frozen=True)
class FakeUser:
    id: int


class FakeEvent:
    def __init__(self, user_id: int | None) -> None:
        self.from_user = FakeUser(user_id) if user_id is not None else None
        self.answers: list[str] = []

    async def answer(self, text: str) -> None:
        self.answers.append(text)


def test_auth_policy_allows_whitelisted_user() -> None:
    policy = TelegramAuthPolicy({1001, 1002})

    assert policy.is_allowed(1001)


def test_auth_policy_rejects_unknown_or_missing_user() -> None:
    policy = TelegramAuthPolicy({1001, 1002})

    assert not policy.is_allowed(9999)
    assert not policy.is_allowed(None)


@pytest.mark.asyncio
async def test_auth_middleware_calls_handler_for_allowed_user() -> None:
    policy = TelegramAuthPolicy({1001})
    middleware = AuthMiddleware(policy)
    event = FakeEvent(1001)
    handler_called = False

    async def handler(_event: FakeEvent, data: MutableMapping[str, Any]) -> str:
        nonlocal handler_called
        handler_called = True
        assert data["telegram_user_id"] == 1001
        return "ok"

    result = await middleware(handler, event, {})

    assert result == "ok"
    assert handler_called
    assert event.answers == []


@pytest.mark.asyncio
async def test_auth_middleware_replies_with_denial_for_unknown_user() -> None:
    policy = TelegramAuthPolicy({1001})
    middleware = AuthMiddleware(policy, denial_message="Denied")
    event = FakeEvent(9999)
    handler_called = False

    async def handler(_event: FakeEvent, _data: MutableMapping[str, Any]) -> str:
        nonlocal handler_called
        handler_called = True
        return "ok"

    result = await middleware(handler, event, {})

    assert result is None
    assert not handler_called
    assert event.answers == ["Denied"]
