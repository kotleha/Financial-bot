from collections.abc import Collection
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuthResult:
    allowed: bool
    reason: str | None = None


class TelegramAuthPolicy:
    """Whitelist policy for Telegram users."""

    def __init__(self, allowed_telegram_ids: Collection[int]) -> None:
        self._allowed_telegram_ids = frozenset(allowed_telegram_ids)
        if not self._allowed_telegram_ids:
            msg = "allowed_telegram_ids must contain at least one Telegram ID"
            raise ValueError(msg)

    def authorize(self, telegram_id: int | None) -> AuthResult:
        if telegram_id is None:
            return AuthResult(allowed=False, reason="missing_telegram_user")
        if telegram_id in self._allowed_telegram_ids:
            return AuthResult(allowed=True)
        return AuthResult(allowed=False, reason="telegram_id_not_allowed")

    def is_allowed(self, telegram_id: int | None) -> bool:
        return self.authorize(telegram_id).allowed
