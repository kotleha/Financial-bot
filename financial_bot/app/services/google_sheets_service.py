from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from financial_bot.app.config import Settings
from financial_bot.app.domain.periods import Period
from financial_bot.app.services.export_service import ExportService, ExportTables

GOOGLE_SHEETS_SCOPES = ("https://www.googleapis.com/auth/spreadsheets",)
GOOGLE_SHEETS_TABLES = {
    "transactions": "transactions!A1",
    "by_category": "by_category!A1",
    "by_payer": "by_payer!A1",
    "income_transactions": "income_transactions!A1",
    "by_income_recipient": "by_income_recipient!A1",
    "by_income_category": "by_income_category!A1",
    "cashflow": "cashflow!A1",
}


class GoogleSheetsNotConfigured(RuntimeError):
    """Raised when Google Sheets export is not configured."""


class GoogleSheetsExportError(RuntimeError):
    """Raised when Google Sheets API export fails."""


@dataclass(frozen=True, slots=True)
class GoogleSheetsExportSummary:
    spreadsheet_id: str
    rows_by_sheet: dict[str, int]

    @property
    def total_rows(self) -> int:
        return sum(self.rows_by_sheet.values())


class GoogleSheetsService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        sheets_client: Any | None = None,
    ) -> None:
        self._settings = settings
        self._exports = ExportService(session, settings)
        self._sheets_client = sheets_client

    def is_configured(self) -> bool:
        return bool(self._settings.google_spreadsheet_id)

    async def export_period(self, period: Period) -> GoogleSheetsExportSummary | None:
        spreadsheet_id = self._settings.google_spreadsheet_id
        if not spreadsheet_id:
            raise GoogleSheetsNotConfigured("Google Sheets spreadsheet ID is not configured")

        tables = await self._exports.build_tables(period)
        if not tables.has_operation_rows:
            return None

        client = self._sheets_client or _build_google_sheets_client(self._settings)
        _ensure_sheets(
            client=client,
            spreadsheet_id=spreadsheet_id,
            sheet_names=tuple(GOOGLE_SHEETS_TABLES),
        )
        rows_by_sheet = _append_tables(
            client=client,
            spreadsheet_id=spreadsheet_id,
            tables=tables,
        )
        return GoogleSheetsExportSummary(spreadsheet_id=spreadsheet_id, rows_by_sheet=rows_by_sheet)


def _append_tables(
    *,
    client: Any,
    spreadsheet_id: str,
    tables: ExportTables,
) -> dict[str, int]:
    rows_by_sheet: dict[str, int] = {}
    table_rows = {
        "transactions": tables.transactions,
        "by_category": tables.by_category,
        "by_payer": tables.by_payer,
        "income_transactions": tables.income_transactions,
        "by_income_recipient": tables.by_income_recipient,
        "by_income_category": tables.by_income_category,
        "cashflow": tables.cashflow,
    }
    for sheet_name, rows in table_rows.items():
        include_headers = not _sheet_has_values(
            client=client,
            spreadsheet_id=spreadsheet_id,
            sheet_name=sheet_name,
        )
        values = _table_values(rows, include_headers=include_headers)
        if not values:
            rows_by_sheet[sheet_name] = 0
            continue

        try:
            (
                client.spreadsheets()
                .values()
                .append(
                    spreadsheetId=spreadsheet_id,
                    range=GOOGLE_SHEETS_TABLES[sheet_name],
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": values},
                )
                .execute()
            )
        except Exception as exc:
            msg = f"Google Sheets export failed for {sheet_name}"
            raise GoogleSheetsExportError(msg) from exc
        rows_by_sheet[sheet_name] = len(rows)
    return rows_by_sheet


def _ensure_sheets(*, client: Any, spreadsheet_id: str, sheet_names: tuple[str, ...]) -> None:
    try:
        response = (
            client.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets.properties.title")
            .execute()
        )
    except Exception as exc:
        msg = "Google Sheets export failed while reading spreadsheet tabs"
        raise GoogleSheetsExportError(msg) from exc

    existing = {
        sheet.get("properties", {}).get("title")
        for sheet in response.get("sheets", [])
        if sheet.get("properties", {}).get("title")
    }
    missing = [sheet_name for sheet_name in sheet_names if sheet_name not in existing]
    if not missing:
        return

    try:
        (
            client.spreadsheets()
            .batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={
                    "requests": [
                        {"addSheet": {"properties": {"title": sheet_name}}}
                        for sheet_name in missing
                    ]
                },
            )
            .execute()
        )
    except Exception as exc:
        msg = "Google Sheets export failed while creating spreadsheet tabs"
        raise GoogleSheetsExportError(msg) from exc


def _sheet_has_values(*, client: Any, spreadsheet_id: str, sheet_name: str) -> bool:
    try:
        response = (
            client.spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=f"{sheet_name}!A1:Z1")
            .execute()
        )
    except Exception as exc:
        msg = f"Google Sheets export failed while checking {sheet_name}"
        raise GoogleSheetsExportError(msg) from exc
    return bool(response.get("values"))


def _table_values(
    rows: list[dict[str, object]],
    *,
    include_headers: bool,
) -> list[list[object]]:
    if not rows:
        return []
    headers = list(rows[0].keys())
    data_rows = [[row.get(header, "") for header in headers] for row in rows]
    if include_headers:
        return [headers, *data_rows]
    return data_rows


def _build_google_sheets_client(settings: Settings):
    try:
        if settings.google_credentials_path:
            from google.oauth2.service_account import Credentials

            credentials = Credentials.from_service_account_file(
                settings.google_credentials_path,
                scopes=GOOGLE_SHEETS_SCOPES,
            )
        else:
            import google.auth

            credentials, _project_id = google.auth.default(scopes=GOOGLE_SHEETS_SCOPES)

        from googleapiclient.discovery import build

        return build("sheets", "v4", credentials=credentials, cache_discovery=False)
    except Exception as exc:
        msg = "Could not initialize Google Sheets client"
        raise GoogleSheetsExportError(msg) from exc
