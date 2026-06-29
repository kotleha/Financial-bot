from dataclasses import dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import Period
from financial_bot.app.domain.types import TransactionType
from financial_bot.app.services.cashflow_service import CashflowService
from financial_bot.app.services.report_service import ReportService
from financial_bot.app.storage.models import TransactionModel
from financial_bot.app.storage.repositories.category_repository import CategoryRepository
from financial_bot.app.storage.repositories.transaction_repository import TransactionRepository
from financial_bot.app.storage.repositories.user_repository import UserRepository


@dataclass(frozen=True, slots=True)
class ExportResult:
    path: Path
    filename: str
    caption: str


@dataclass(frozen=True, slots=True)
class ExportTables:
    transactions: list[dict[str, object]]
    by_category: list[dict[str, object]]
    by_payer: list[dict[str, object]]
    income_transactions: list[dict[str, object]]
    by_income_recipient: list[dict[str, object]]
    by_income_category: list[dict[str, object]]
    cashflow: list[dict[str, object]]

    @property
    def has_operation_rows(self) -> bool:
        return bool(self.transactions or self.income_transactions)


class ExportService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings
        self._transactions = TransactionRepository(session)
        self._categories = CategoryRepository(session)
        self._users = UserRepository(session)
        self._reports = ReportService(session, settings)

    async def create_csv_export(self, period: Period) -> ExportResult | None:
        tables = await self.build_tables(period)
        transaction_rows = [*tables.transactions, *tables.income_transactions]
        if not transaction_rows:
            return None

        pd = _pandas()
        dataframe = pd.DataFrame(transaction_rows)
        path = _temporary_path(".csv")
        dataframe.to_csv(path, index=False, sep=";", encoding="utf-8-sig")
        return ExportResult(
            path=path,
            filename=_filename(period, "csv"),
            caption=f"CSV экспорт за {period.label}",
        )

    async def create_xlsx_export(self, period: Period) -> ExportResult | None:
        tables = await self.build_tables(period)
        if not tables.has_operation_rows:
            return None

        path = _temporary_path(".xlsx")
        pd = _pandas()
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            pd.DataFrame(tables.transactions).to_excel(
                writer,
                sheet_name="transactions",
                index=False,
            )
            pd.DataFrame(tables.by_category).to_excel(
                writer,
                sheet_name="by_category",
                index=False,
            )
            pd.DataFrame(tables.by_payer).to_excel(writer, sheet_name="by_payer", index=False)
            pd.DataFrame(tables.income_transactions).to_excel(
                writer,
                sheet_name="income_transactions",
                index=False,
            )
            pd.DataFrame(tables.by_income_recipient).to_excel(
                writer,
                sheet_name="by_income_recipient",
                index=False,
            )
            pd.DataFrame(tables.by_income_category).to_excel(
                writer,
                sheet_name="by_income_category",
                index=False,
            )
            pd.DataFrame(tables.cashflow).to_excel(writer, sheet_name="cashflow", index=False)

        return ExportResult(
            path=path,
            filename=_filename(period, "xlsx"),
            caption=f"XLSX экспорт за {period.label}",
        )

    async def build_tables(self, period: Period) -> ExportTables:
        transactions = await self._transaction_rows(period)
        income_transactions = await self._income_transaction_rows(period)
        report = await self._reports.build_period_report(period.kind, now=period.start_at)
        cashflow_report = await CashflowService(self._session, self._settings).build_report(
            period.kind,
            now=period.start_at,
        )
        return ExportTables(
            transactions=transactions,
            by_category=[
                {
                    "category_code": line.code,
                    "category_title": line.title,
                    "amount_rub": _rub(line.amount),
                    "share_percent": line.share_percent,
                }
                for line in report.by_category
            ],
            by_payer=[
                {
                    "payer_role": line.role,
                    "amount_rub": _rub(line.amount),
                    "share_percent": line.share_percent,
                }
                for line in report.by_payer
            ],
            income_transactions=income_transactions,
            by_income_recipient=[
                {
                    "recipient_role": line.role,
                    "amount_rub": _rub(line.amount),
                    "share_percent": line.share_percent,
                }
                for line in cashflow_report.income_by_recipient
            ],
            by_income_category=[
                {
                    "category_code": line.code,
                    "category_title": line.title,
                    "amount_rub": _rub(line.amount),
                    "share_percent": line.share_percent,
                }
                for line in cashflow_report.income_by_category
            ],
            cashflow=[
                {
                    "period": cashflow_report.period.label,
                    "income_total_rub": _rub(cashflow_report.income_total),
                    "expense_total_rub": _rub(cashflow_report.expense_total),
                    "net_after_expenses_rub": _rub(cashflow_report.net_after_expenses),
                    "budget_net_savings_rub": (
                        _rub(cashflow_report.budget_net_savings)
                        if cashflow_report.budget_net_savings is not None
                        else ""
                    ),
                }
            ],
        )

    async def _transaction_rows(self, period: Period) -> list[dict[str, object]]:
        transactions = await self._transactions.list_report_effective_for_period(
            period.start_at,
            period.end_at,
        )
        rows = []
        for transaction in transactions:
            rows.append(await self._transaction_row(transaction))
        return rows

    async def _income_transaction_rows(self, period: Period) -> list[dict[str, object]]:
        transactions = await self._transactions.list_for_period(period.start_at, period.end_at)
        rows = []
        for transaction in transactions:
            if transaction.type == TransactionType.INCOME.value:
                rows.append(await self._transaction_row(transaction))
        return rows

    async def _transaction_row(self, transaction: TransactionModel) -> dict[str, object]:
        category = await self._categories.get(transaction.category_id)
        payer = await self._users.get(transaction.payer_user_id)
        creator = await self._users.get(transaction.created_by_user_id)
        if category is None or payer is None or creator is None:
            msg = f"Transaction dependencies are missing: {transaction.id}"
            raise ValueError(msg)

        return {
            "id": transaction.id,
            "amount_rub": _rub(transaction.amount),
            "report_amount_rub": _rub(_report_amount(transaction)),
            "currency": transaction.currency,
            "occurred_at": transaction.occurred_at.isoformat(),
            "payer_role": payer.role,
            "category_code": category.code,
            "category_title": category.title,
            "type": transaction.type,
            "source": transaction.source,
            "included_in_reports": transaction.included_in_reports,
            "comment": transaction.comment,
            "raw_text": transaction.raw_text,
            "created_by_role": creator.role,
        }


def _temporary_path(suffix: str) -> Path:
    with NamedTemporaryFile(suffix=suffix, delete=False) as temporary_file:
        return Path(temporary_file.name)


def _filename(period: Period, extension: str) -> str:
    if period.kind.value == "year":
        marker = f"{period.start_at.year}"
    else:
        marker = f"{period.start_at.year}-{period.start_at.month:02d}"
    return f"family-finance-{marker}.{extension}"


def _rub(amount_minor: int) -> float:
    return amount_minor / 100


def _report_amount(transaction: TransactionModel) -> int:
    if transaction.type == "correction":
        return -transaction.amount
    return transaction.amount


def _pandas():
    import pandas as pd

    return pd
