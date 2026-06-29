from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import SettingModel


class SettingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_value(self, key: str) -> dict[str, Any] | None:
        result = await self._session.execute(select(SettingModel).where(SettingModel.key == key))
        setting = result.scalar_one_or_none()
        return setting.value if setting is not None else None

    async def set_value(self, key: str, value: dict[str, Any]) -> None:
        result = await self._session.execute(select(SettingModel).where(SettingModel.key == key))
        setting = result.scalar_one_or_none()
        if setting is None:
            self._session.add(SettingModel(key=key, value=value))
        else:
            setting.value = value
            setting.updated_at = datetime.now(UTC)
        await self._session.flush()
