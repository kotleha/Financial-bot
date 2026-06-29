from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import SpendingLimitAlertModel


class SpendingLimitAlertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, alert: SpendingLimitAlertModel) -> SpendingLimitAlertModel:
        self._session.add(alert)
        await self._session.flush()
        return alert

    async def list_sent_thresholds(
        self,
        *,
        period_start: datetime,
        category_id: int,
        sent_to_user_id: int,
    ) -> set[int]:
        result = await self._session.execute(
            select(SpendingLimitAlertModel.threshold_percent)
            .where(SpendingLimitAlertModel.period_start == period_start)
            .where(SpendingLimitAlertModel.category_id == category_id)
            .where(SpendingLimitAlertModel.sent_to_user_id == sent_to_user_id)
            .order_by(SpendingLimitAlertModel.threshold_percent)
        )
        return {int(item) for item in result.scalars()}

    async def has_sent_threshold(
        self,
        *,
        period_start: datetime,
        category_id: int,
        threshold_percent: int,
        sent_to_user_id: int,
    ) -> bool:
        result = await self._session.execute(
            select(SpendingLimitAlertModel.id)
            .where(SpendingLimitAlertModel.period_start == period_start)
            .where(SpendingLimitAlertModel.category_id == category_id)
            .where(SpendingLimitAlertModel.threshold_percent == threshold_percent)
            .where(SpendingLimitAlertModel.sent_to_user_id == sent_to_user_id)
            .limit(1)
        )
        return result.scalar_one_or_none() is not None
