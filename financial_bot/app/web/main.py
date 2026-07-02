import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Protocol

import uvicorn
from aiogram import Bot
from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from financial_bot.app.bot.formatters.bank_events import format_bank_import_result
from financial_bot.app.bot.keyboards.bank_events import (
    build_bank_autosaved_actions_keyboard,
    build_bank_event_actions_keyboard,
    build_bank_income_actions_keyboard,
    build_bank_refund_actions_keyboard,
)
from financial_bot.app.bot.telegram_client import create_telegram_bot
from financial_bot.app.config import Settings, load_settings
from financial_bot.app.domain.types import BankEventOperationKind, BankEventParseStatus
from financial_bot.app.services.bank_ingestion_service import (
    BankImportResult,
    BankIngestionAuthError,
    BankIngestionService,
)
from financial_bot.app.storage.db import create_engine, create_session_factory
from financial_bot.app.storage.models import UserModel
from financial_bot.app.storage.repositories.bank_event_repository import BankEventRepository

logger = logging.getLogger(__name__)


class BankEventIngestRequest(BaseModel):
    text: Any = Field()
    sender: Any | None = None
    received_at: datetime | None = None


class BankEventIngestResponse(BaseModel):
    event_id: int
    duplicate: bool
    bank: str
    operation_kind: str
    parse_status: str
    amount_minor: int | None
    fee_amount_minor: int | None
    currency: str
    merchant: str | None
    suggested_category_code: str | None
    suggested_category_title: str | None
    suggested_category_source: str
    scope: str
    suggestion_conflict: bool
    requires_confirmation: bool
    telegram_notification_sent: bool


class BankEventNotifier(Protocol):
    async def notify_new_event(
        self,
        *,
        session: AsyncSession,
        source_token: str,
        result: BankImportResult,
    ) -> bool: ...

    async def close(self) -> None: ...


class NullBankEventNotifier:
    async def notify_new_event(
        self,
        *,
        session: AsyncSession,
        source_token: str,
        result: BankImportResult,
    ) -> bool:
        return False

    async def close(self) -> None:
        return None


class TelegramBankEventNotifier:
    def __init__(self, bot: Bot) -> None:
        self._bot = bot

    async def notify_new_event(
        self,
        *,
        session: AsyncSession,
        source_token: str,
        result: BankImportResult,
    ) -> bool:
        if not _should_send_bank_event_notification(result):
            return False

        source = await BankEventRepository(session).get_active_source_by_token(source_token)
        if source is None:
            return False

        owner = await session.get(UserModel, source.owner_user_id)
        if owner is None or not owner.is_active:
            return False

        await self._bot.send_message(
            chat_id=owner.telegram_id,
            text=format_bank_import_result(result),
            reply_markup=_bank_event_notification_keyboard(result),
        )
        return True

    async def close(self) -> None:
        await self._bot.session.close()


@dataclass(slots=True)
class WebAppState:
    settings: Settings
    session_factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine | None
    notifier: BankEventNotifier


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    notifier: BankEventNotifier | None = None,
    send_telegram_notifications: bool = True,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        resolved_settings = settings or load_settings()
        engine: AsyncEngine | None = None
        resolved_session_factory = session_factory
        if resolved_session_factory is None:
            engine = create_engine(resolved_settings.database_url)
            resolved_session_factory = create_session_factory(engine)

        resolved_notifier = notifier
        if resolved_notifier is None:
            resolved_notifier = (
                TelegramBankEventNotifier(create_telegram_bot(resolved_settings))
                if send_telegram_notifications
                else NullBankEventNotifier()
            )

        app.state.money_bot = WebAppState(
            settings=resolved_settings,
            session_factory=resolved_session_factory,
            engine=engine,
            notifier=resolved_notifier,
        )
        try:
            yield
        finally:
            await resolved_notifier.close()
            if engine is not None:
                await engine.dispose()

    app = FastAPI(
        title="Money Bot Bank Ingestion",
        version="0.1.0",
        lifespan=lifespan,
    )

    async def get_session() -> AsyncIterator[AsyncSession]:
        app_state: WebAppState = app.state.money_bot
        async with app_state.session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    def get_app_state() -> WebAppState:
        return app.state.money_bot

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/bank-events", response_model=BankEventIngestResponse)
    async def ingest_bank_event(
        payload: BankEventIngestRequest,
        session: Annotated[AsyncSession, Depends(get_session)],
        app_state: Annotated[WebAppState, Depends(get_app_state)],
        authorization: Annotated[str | None, Header()] = None,
    ) -> BankEventIngestResponse:
        source_token = _extract_bearer_token(authorization)
        service = BankIngestionService(session, app_state.settings)
        try:
            sms_text = _extract_text_payload(payload.text, max_length=2000)
            result = await service.import_sms_from_source_token(
                text=sms_text,
                source_token=source_token,
                sender=_extract_sender_payload(payload.sender),
                received_at=payload.received_at,
            )
        except BankIngestionAuthError as exc:
            raise _unauthorized() from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc

        await session.commit()
        notification_sent = False
        if _should_send_bank_event_notification(result):
            try:
                notification_sent = await app_state.notifier.notify_new_event(
                    session=session,
                    source_token=source_token,
                    result=result,
                )
            except Exception:
                logger.warning(
                    "Bank event %s was stored but Telegram notification failed",
                    result.event_id,
                    exc_info=True,
                )

            if notification_sent:
                await service.mark_telegram_notification_sent(event_id=result.event_id)
            else:
                await service.mark_telegram_notification_failed(event_id=result.event_id)
            await session.commit()
        return _response_from_result(result, notification_sent=notification_sent)

    return app


def main() -> None:
    settings = load_settings()
    uvicorn.run(
        create_app(settings=settings),
        host=settings.bank_ingest_host,
        port=settings.bank_ingest_port,
    )


def _extract_bearer_token(authorization: str | None) -> str:
    if authorization is None:
        raise _unauthorized()

    scheme, separator, token = authorization.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not token.strip():
        raise _unauthorized()
    return token.strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid bank ingestion source token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _extract_text_payload(value: Any, *, max_length: int) -> str:
    text = _find_text_candidate(value)
    if text is None or not text.strip():
        msg = "Bank SMS text must not be empty"
        raise ValueError(msg)

    normalized = text.strip()
    if len(normalized) > max_length:
        msg = f"Bank SMS text must be at most {max_length} characters"
        raise ValueError(msg)
    return normalized


def _extract_sender_payload(value: Any) -> str:
    if value is None:
        return ""

    sender = _find_text_candidate(value)
    if sender is None:
        return ""

    normalized = sender.strip()
    if normalized.replace("-", "") == "900":
        return "900"
    if len(normalized) > 64:
        return ""
    return normalized


TEXT_PAYLOAD_KEYS = (
    "text",
    "body",
    "content",
    "contents",
    "message",
    "sms",
    "value",
    "string",
    "plain_text",
)
TEXT_PAYLOAD_KEY_SET = {key.lower() for key in TEXT_PAYLOAD_KEYS}
SMS_AMOUNT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*(?:р|rub|₽)", re.IGNORECASE)
SMS_KEYWORDS = (
    "покупка",
    "оплата",
    "списание",
    "перевод",
    "зачисление",
    "поступление",
    "баланс",
    "счёт",
    "счет",
    "карта",
    "комиссия",
    "rub",
)


def _find_text_candidate(value: Any) -> str | None:
    return _find_text_candidate_inner(value, depth=0)


def _find_text_candidate_inner(value: Any, *, depth: int) -> str | None:
    if depth > 6:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return _find_text_candidate_in_mapping(value, depth=depth)
    if isinstance(value, list | tuple):
        return _best_text_candidate(
            _find_text_candidate_inner(item, depth=depth + 1) for item in value
        )
    return None


def _find_text_candidate_in_mapping(value: dict[Any, Any], *, depth: int) -> str | None:
    for key in TEXT_PAYLOAD_KEYS:
        if key in value:
            candidate = _find_text_candidate_inner(value[key], depth=depth + 1)
            if candidate:
                return candidate

    keyed_candidates: list[str] = []
    fallback_candidates: list[str] = []
    for raw_key, raw_item in value.items():
        candidate = _find_text_candidate_inner(raw_item, depth=depth + 1)
        if not candidate:
            continue
        if str(raw_key).strip().lower() in TEXT_PAYLOAD_KEY_SET:
            keyed_candidates.append(candidate)
        else:
            fallback_candidates.append(candidate)

    return _best_text_candidate(keyed_candidates) or _best_text_candidate(fallback_candidates)


def _best_text_candidate(candidates: Any) -> str | None:
    clean_candidates = [
        candidate.strip() for candidate in candidates if candidate and candidate.strip()
    ]
    if not clean_candidates:
        return None
    return max(clean_candidates, key=_text_candidate_score)


def _text_candidate_score(value: str) -> tuple[int, int]:
    normalized = value.lower()
    keyword_score = sum(1 for keyword in SMS_KEYWORDS if keyword in normalized)
    amount_score = 1 if SMS_AMOUNT_RE.search(value) else 0
    return (keyword_score * 10 + amount_score * 5, min(len(value), 2000))


def _response_from_result(
    result: BankImportResult,
    *,
    notification_sent: bool,
) -> BankEventIngestResponse:
    return BankEventIngestResponse(
        event_id=result.event_id,
        duplicate=result.is_duplicate,
        bank=result.bank.value,
        operation_kind=result.operation_kind.value,
        parse_status=result.parse_status.value,
        amount_minor=result.amount,
        fee_amount_minor=result.fee_amount,
        currency=result.currency,
        merchant=result.merchant or None,
        suggested_category_code=result.suggested_category_code,
        suggested_category_title=result.suggested_category_title,
        suggested_category_source=result.suggested_category_source.value,
        scope=result.scope.value,
        suggestion_conflict=result.suggestion_conflict,
        requires_confirmation=result.requires_confirmation,
        telegram_notification_sent=notification_sent,
    )


def _should_send_bank_event_notification(result: BankImportResult) -> bool:
    if result.is_duplicate and not _should_retry_failed_notification(result):
        return False
    if result.creates_expense_candidate:
        return result.parse_status in {
            BankEventParseStatus.NEEDS_CONFIRMATION,
            BankEventParseStatus.AUTOSAVED,
        }
    if result.operation_kind == BankEventOperationKind.INCOME:
        return result.parse_status == BankEventParseStatus.PARSED
    return (
        result.operation_kind == BankEventOperationKind.REFUND
        and result.parse_status == BankEventParseStatus.PARSED
    )


def _should_retry_failed_notification(result: BankImportResult) -> bool:
    return (
        result.telegram_notification_sent_at is None
        and result.telegram_notification_failed_at is not None
    )


def _bank_event_notification_keyboard(result: BankImportResult):
    if result.parse_status == BankEventParseStatus.AUTOSAVED:
        return build_bank_autosaved_actions_keyboard(result.event_id)
    if result.operation_kind == BankEventOperationKind.INCOME:
        return build_bank_income_actions_keyboard(result.event_id)
    if result.operation_kind == BankEventOperationKind.REFUND:
        return build_bank_refund_actions_keyboard(
            result.event_id,
            can_confirm=result.suggested_category_code is not None,
        )
    return build_bank_event_actions_keyboard(
        result.event_id,
        can_confirm=(
            result.creates_expense_candidate and result.suggested_category_code is not None
        ),
    )
