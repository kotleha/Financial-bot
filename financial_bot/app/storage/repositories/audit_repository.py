from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.storage.models import OperationAuditLogModel


class AuditRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, audit_log: OperationAuditLogModel) -> OperationAuditLogModel:
        self._session.add(audit_log)
        await self._session.flush()
        return audit_log

    async def list_for_transaction(self, transaction_id: int) -> list[OperationAuditLogModel]:
        result = await self._session.execute(
            select(OperationAuditLogModel)
            .where(OperationAuditLogModel.transaction_id == transaction_id)
            .order_by(OperationAuditLogModel.changed_at, OperationAuditLogModel.id)
        )
        return list(result.scalars())
