from dataclasses import dataclass
from secrets import token_urlsafe

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.domain.types import BankEventBank, BankEventChannel, UserRole
from financial_bot.app.storage.models import BankEventSourceModel, UserModel
from financial_bot.app.storage.repositories.bank_event_repository import (
    BankEventRepository,
    hash_bank_event_source_token,
)
from financial_bot.app.storage.repositories.user_repository import UserRepository

SOURCE_TOKEN_BYTES = 32


@dataclass(frozen=True, slots=True)
class BankEventSourceProvisionResult:
    source_id: int
    code: str
    bank: BankEventBank
    channel: BankEventChannel
    owner_role: UserRole
    owner_telegram_id: int
    token: str | None
    created: bool
    rotated: bool


class BankEventSourceService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._bank_events = BankEventRepository(session)
        self._users = UserRepository(session)

    async def provision_source(
        self,
        *,
        code: str,
        bank: BankEventBank,
        channel: BankEventChannel,
        owner_role: UserRole,
        token: str | None = None,
        rotate: bool = False,
    ) -> BankEventSourceProvisionResult:
        normalized_code = _normalize_source_code(code)
        owner = await self._resolve_owner(owner_role)
        existing = await self._bank_events.get_source_by_code(normalized_code)

        if existing is not None:
            return await self._handle_existing_source(
                existing,
                bank=bank,
                channel=channel,
                owner=owner,
                token=token,
                rotate=rotate,
            )

        generated_token = token or generate_bank_event_source_token()
        source = await self._bank_events.add_source(
            BankEventSourceModel(
                code=normalized_code,
                bank=bank.value,
                channel=channel.value,
                owner_user_id=owner.id,
                token_hash=hash_bank_event_source_token(generated_token),
            )
        )
        return _result_from_source(
            source,
            owner=owner,
            token=generated_token,
            created=True,
            rotated=False,
        )

    async def _handle_existing_source(
        self,
        source: BankEventSourceModel,
        *,
        bank: BankEventBank,
        channel: BankEventChannel,
        owner: UserModel,
        token: str | None,
        rotate: bool,
    ) -> BankEventSourceProvisionResult:
        if not rotate:
            if token is not None:
                msg = "Use rotate=True to replace a token for an existing bank event source"
                raise ValueError(msg)
            if (
                source.bank != bank.value
                or source.channel != channel.value
                or source.owner_user_id != owner.id
            ):
                msg = "Bank event source already exists with different bank, channel, or owner"
                raise ValueError(msg)
            return _result_from_source(
                source,
                owner=owner,
                token=None,
                created=False,
                rotated=False,
            )

        generated_token = token or generate_bank_event_source_token()
        source.bank = bank.value
        source.channel = channel.value
        source.owner_user_id = owner.id
        source.token_hash = hash_bank_event_source_token(generated_token)
        source.is_active = True
        await self._session.flush()
        return _result_from_source(
            source,
            owner=owner,
            token=generated_token,
            created=False,
            rotated=True,
        )

    async def _resolve_owner(self, owner_role: UserRole) -> UserModel:
        owner = await self._users.get_by_role(owner_role.value)
        if owner is None:
            msg = f"User with role {owner_role.value!r} is not seeded"
            raise ValueError(msg)
        if not owner.is_active:
            msg = f"User with role {owner_role.value!r} is inactive"
            raise ValueError(msg)
        return owner


def generate_bank_event_source_token() -> str:
    return token_urlsafe(SOURCE_TOKEN_BYTES)


def _normalize_source_code(code: str) -> str:
    normalized_code = code.strip()
    if not normalized_code:
        msg = "Bank event source code must not be empty"
        raise ValueError(msg)
    if len(normalized_code) > 120:
        msg = "Bank event source code must be 120 characters or shorter"
        raise ValueError(msg)
    return normalized_code


def _result_from_source(
    source: BankEventSourceModel,
    *,
    owner: UserModel,
    token: str | None,
    created: bool,
    rotated: bool,
) -> BankEventSourceProvisionResult:
    return BankEventSourceProvisionResult(
        source_id=source.id,
        code=source.code,
        bank=BankEventBank(source.bank),
        channel=BankEventChannel(source.channel),
        owner_role=UserRole(owner.role),
        owner_telegram_id=owner.telegram_id,
        token=token,
        created=created,
        rotated=rotated,
    )
