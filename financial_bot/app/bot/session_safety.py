import logging

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def commit_or_rollback(session: AsyncSession, *, context: str) -> None:
    try:
        await session.commit()
    except Exception:
        logger.exception("Database commit failed: %s", context)
        await rollback_safely(session, context=context)
        raise


async def rollback_safely(session: AsyncSession, *, context: str) -> None:
    try:
        await session.rollback()
    except Exception:
        logger.exception("Database rollback failed: %s", context)


async def rollback_after_secondary_failure(session: AsyncSession, *, context: str) -> None:
    logger.warning("Secondary side effect failed: %s", context, exc_info=True)
    await rollback_safely(session, context=context)
