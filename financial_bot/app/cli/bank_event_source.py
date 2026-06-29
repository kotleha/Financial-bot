import argparse
import asyncio
from collections.abc import Sequence

from financial_bot.app.config import SettingsLoadError, load_settings
from financial_bot.app.domain.types import BankEventBank, BankEventChannel, UserRole
from financial_bot.app.services.bank_event_source_service import (
    BankEventSourceProvisionResult,
    BankEventSourceService,
)
from financial_bot.app.storage.db import create_engine, create_session_factory, session_scope


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv)
    asyncio.run(_async_main(args))


async def _async_main(args: argparse.Namespace) -> None:
    try:
        settings = load_settings(args.env_file)
    except SettingsLoadError as exc:
        raise SystemExit(str(exc)) from exc

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_scope(session_factory) as session:
            result = await BankEventSourceService(session).provision_source(
                code=args.code,
                bank=BankEventBank(args.bank),
                channel=BankEventChannel(args.channel),
                owner_role=UserRole(args.owner_role),
                token=args.token,
                rotate=args.rotate,
            )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
    finally:
        await engine.dispose()

    print(_format_result(result))


def _parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or rotate a bank event ingestion source token.",
    )
    parser.add_argument("--env-file", default=".env", help="Path to env file. Default: .env")
    parser.add_argument("--code", required=True, help="Unique source code, e.g. husband-sber-ios")
    parser.add_argument(
        "--bank",
        required=True,
        choices=[item.value for item in BankEventBank],
        help="Bank parser/source family.",
    )
    parser.add_argument(
        "--channel",
        default=BankEventChannel.IOS_SHORTCUT.value,
        choices=[item.value for item in BankEventChannel],
        help="Ingestion channel. Default: ios_shortcut",
    )
    parser.add_argument(
        "--owner-role",
        required=True,
        choices=[item.value for item in UserRole],
        help="Seeded Money Bot user that owns this phone/source.",
    )
    parser.add_argument(
        "--token",
        default=None,
        help="Optional explicit token. Omit to generate a random one.",
    )
    parser.add_argument(
        "--rotate",
        action="store_true",
        help="Replace token and metadata for an existing source code.",
    )
    return parser.parse_args(argv)


def _format_result(source: BankEventSourceProvisionResult) -> str:
    lines = [
        "Bank event source provisioned.",
        f"Status: {_status_label(source.created, source.rotated)}",
        f"Source ID: {source.source_id}",
        f"Code: {source.code}",
        f"Bank: {source.bank.value}",
        f"Channel: {source.channel.value}",
        f"Owner role: {source.owner_role.value}",
    ]
    if source.token is None:
        lines.extend(
            [
                "",
                "Token was not printed because this source already existed.",
                "Use --rotate when you intentionally need a new token.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "Source token, show-once:",
                source.token,
                "",
                "Store it only in the private iPhone Shortcut or server-side secret storage.",
            ]
        )
    return "\n".join(lines)


def _status_label(created: bool, rotated: bool) -> str:
    if created:
        return "created"
    if rotated:
        return "rotated"
    return "exists"
