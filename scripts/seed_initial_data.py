from __future__ import annotations

import argparse
import asyncio

from financial_bot.app.config import load_settings
from financial_bot.app.services.seed_service import seed_initial_data
from financial_bot.app.storage.db import create_engine, create_session_factory, session_scope


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Family Finance Bot initial data.")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to env file with application settings.",
    )
    return parser.parse_args()


async def run_seed(env_file: str) -> None:
    settings = load_settings(None if env_file.strip() == "" else env_file)
    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        async with session_scope(session_factory) as session:
            result = await seed_initial_data(session, settings)
    finally:
        await engine.dispose()

    print(result)


def main() -> None:
    args = parse_args()
    asyncio.run(run_seed(args.env_file))


if __name__ == "__main__":
    main()
