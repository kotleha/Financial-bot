from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import UserModel


class UserRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, user: UserModel) -> UserModel:
        self._session.add(user)
        await self._session.flush()
        return user

    async def get(self, user_id: int) -> UserModel | None:
        return await self._session.get(UserModel, user_id)

    async def get_by_telegram_id(self, telegram_id: int) -> UserModel | None:
        result = await self._session.execute(
            select(UserModel).where(UserModel.telegram_id == telegram_id)
        )
        return result.scalar_one_or_none()

    async def get_by_role(self, role: str) -> UserModel | None:
        result = await self._session.execute(select(UserModel).where(UserModel.role == role))
        return result.scalar_one_or_none()

    async def list_active(self) -> list[UserModel]:
        result = await self._session.execute(
            select(UserModel).where(UserModel.is_active.is_(True)).order_by(UserModel.id)
        )
        return list(result.scalars())
