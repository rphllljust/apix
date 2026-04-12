"""Responsabilidade: implementa o modulo app/sheets/client.py."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

import gspread
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2.service_account import Credentials
from gspread.exceptions import APIError, WorksheetNotFound
from loguru import logger

from app.config import Settings
from app.sheets.exceptions import SheetQuotaExceededError, SheetsSyncError

SHEETS_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


def _column_letter(index: int) -> str:
    if index < 1:
        raise ValueError("Column index must be >= 1")
    result = []
    while index:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return "".join(reversed(result))


def _serialize(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


class GoogleSheetsClient:
    @staticmethod
    def _is_oauth_configured(settings: Settings) -> bool:
        return bool(
            settings.google_oauth_refresh_token
            and settings.google_oauth_client_id
            and settings.google_oauth_client_secret
        )

    @classmethod
    def _build_credentials(cls, settings: Settings) -> Credentials | OAuthCredentials:
        if cls._is_oauth_configured(settings):
            creds = OAuthCredentials(
                token=None,
                refresh_token=settings.google_oauth_refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_oauth_client_id,
                client_secret=settings.google_oauth_client_secret,
                scopes=SHEETS_SCOPES,
            )
            creds.refresh(GoogleAuthRequest())
            return creds

        return Credentials.from_service_account_file(
            settings.google_service_account_file,
            scopes=SHEETS_SCOPES,
        )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        creds = self._build_credentials(settings)
        self._client = gspread.authorize(creds)
        self._spreadsheet = self._client.open_by_key(settings.google_spreadsheet_id)

    @staticmethod
    def _is_quota_error(exc: APIError) -> bool:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)

        text = str(exc).lower()
        hints = (
            "quota",
            "rate limit",
            "ratelimit",
            "too many requests",
            "userratelimitexceeded",
            "ratelimitexceeded",
            "quotaexceeded",
            "resource_exhausted",
            "100s",
        )
        if status_code == 429:
            return True
        if any(hint in text for hint in hints):
            return True

        try:
            payload = response.json() if response is not None else {}
        except Exception:
            payload = {}
        payload_text = json.dumps(payload, ensure_ascii=False).lower() if payload else ""
        if payload_text and any(hint in payload_text for hint in hints):
            return True

        return False

    @classmethod
    def _raise_sheets_error(cls, exc: APIError, operation: str) -> None:
        if cls._is_quota_error(exc):
            logger.error(
                "Falha final Google Sheets operation={} error=quota_exceeded",
                operation,
            )
            raise SheetQuotaExceededError(
                f"Quota excedida no Google Sheets durante '{operation}'.",
            ) from exc
        logger.error("Falha final Google Sheets operation={} error={}", operation, exc)
        raise SheetsSyncError(f"Falha no Google Sheets durante '{operation}': {exc}") from exc

    def _worksheet(self, title: str, create_if_missing: bool = True) -> gspread.Worksheet:
        try:
            return self._spreadsheet.worksheet(title)
        except WorksheetNotFound:
            if not create_if_missing:
                raise
            try:
                return self._spreadsheet.add_worksheet(title=title, rows=1000, cols=80)
            except APIError as exc:
                self._raise_sheets_error(exc, f"add_worksheet:{title}")
        except APIError as exc:
            self._raise_sheets_error(exc, f"worksheet:{title}")

    def ensure_headers(self, sheet_name: str, required_headers: list[str]) -> list[str]:
        try:
            ws = self._worksheet(sheet_name)
            existing_headers = ws.row_values(1)
            if not existing_headers:
                ws.update("A1", [required_headers], value_input_option="RAW")
                return required_headers
            merged = existing_headers + [h for h in required_headers if h not in existing_headers]
            if merged != existing_headers:
                ws.update("A1", [merged], value_input_option="RAW")
            return merged
        except APIError as exc:
            self._raise_sheets_error(exc, f"ensure_headers:{sheet_name}")

    def read_records(self, sheet_name: str) -> list[dict[str, str]]:
        try:
            ws = self._worksheet(sheet_name)
            values = ws.get_all_values()
            if not values:
                return []

            headers = [header.strip() for header in values[0]]
            records: list[dict[str, str]] = []
            for row in values[1:]:
                full_row = row + [""] * (len(headers) - len(row))
                item = {headers[idx]: full_row[idx] for idx in range(len(headers))}
                if any(str(val).strip() for val in item.values()):
                    records.append(item)
            return records
        except APIError as exc:
            self._raise_sheets_error(exc, f"read_records:{sheet_name}")

    def read_records_with_row_number(self, sheet_name: str) -> list[dict[str, str | int]]:
        try:
            ws = self._worksheet(sheet_name)
            values = ws.get_all_values()
            if not values:
                return []

            headers = [header.strip() for header in values[0]]
            rows: list[dict[str, str | int]] = []
            for idx, row in enumerate(values[1:], start=2):
                full_row = row + [""] * (len(headers) - len(row))
                item: dict[str, str | int] = {"_row_number": idx}
                item.update({headers[h_idx]: full_row[h_idx] for h_idx in range(len(headers))})
                if any(str(val).strip() for key, val in item.items() if key != "_row_number"):
                    rows.append(item)
            return rows
        except APIError as exc:
            self._raise_sheets_error(exc, f"read_records_with_row_number:{sheet_name}")

    def upsert_records(
        self,
        sheet_name: str,
        records: list[dict[str, Any]],
        key_fields: list[str],
    ) -> dict[str, int]:
        try:
            ws = self._worksheet(sheet_name)
            if not records:
                return {"inserted": 0, "updated": 0}

            incoming_headers = list(
                dict.fromkeys(key for record in records for key in record.keys()),
            )
            existing_headers = ws.row_values(1)
            if not existing_headers:
                headers = incoming_headers
                ws.update("A1", [headers])
            else:
                headers = existing_headers + [h for h in incoming_headers if h not in existing_headers]
                if headers != existing_headers:
                    ws.update("A1", [headers])

            all_current = ws.get_all_records(head=1, default_blank="", expected_headers=headers)
            index: dict[tuple[str, ...], int] = {}
            for row_num, item in enumerate(all_current, start=2):
                key = tuple(str(item.get(field, "")).strip() for field in key_fields)
                if all(key):
                    index[key] = row_num

            updates = []
            append_rows = []
            inserted = 0
            updated = 0

            for record in records:
                normalized = {header: _serialize(record.get(header)) for header in headers}
                key = tuple(normalized.get(field, "").strip() for field in key_fields)
                row_values = [normalized.get(header, "") for header in headers]

                if all(key) and key in index:
                    row_number = index[key]
                    col_last = _column_letter(len(headers))
                    updates.append(
                        {
                            "range": f"A{row_number}:{col_last}{row_number}",
                            "values": [row_values],
                        },
                    )
                    updated += 1
                else:
                    append_rows.append(row_values)
                    inserted += 1

            if updates:
                ws.batch_update(updates, value_input_option="RAW")
            if append_rows:
                ws.append_rows(append_rows, value_input_option="RAW")

            return {"inserted": inserted, "updated": updated}
        except APIError as exc:
            self._raise_sheets_error(exc, f"upsert_records:{sheet_name}")

    def overwrite_records(
        self,
        sheet_name: str,
        records: list[dict[str, Any]],
        headers: list[str] | None = None,
    ) -> int:
        try:
            ws = self._worksheet(sheet_name)
            ws.clear()
            if not records:
                return 0

            all_headers = list(dict.fromkeys(key for record in records for key in record.keys()))
            if headers:
                merged = headers + [item for item in all_headers if item not in headers]
            else:
                merged = all_headers
            rows = [[_serialize(record.get(header)) for header in merged] for record in records]
            ws.update("A1", [merged, *rows], value_input_option="RAW")
            return len(records)
        except APIError as exc:
            self._raise_sheets_error(exc, f"overwrite_records:{sheet_name}")

    def overwrite_table_with_subheader(
        self,
        sheet_name: str,
        headers: list[str],
        subheader: list[str],
        rows: list[list[Any]],
    ) -> int:
        try:
            ws = self._worksheet(sheet_name)
            ws.clear()
            if not headers:
                return 0
            normalized_rows = [[_serialize(cell) for cell in row] for row in rows]
            ws.update(
                "A1",
                [headers, [_serialize(cell) for cell in subheader], *normalized_rows],
                value_input_option="RAW",
            )
            ws.freeze(rows=2)
            return len(rows)
        except APIError as exc:
            self._raise_sheets_error(exc, f"overwrite_table_with_subheader:{sheet_name}")

    def clear_rows(self, sheet_name: str, row_numbers: list[int]) -> None:
        if not row_numbers:
            return
        try:
            ws = self._worksheet(sheet_name)
            headers = ws.row_values(1)
            if not headers:
                return
            blank = [""] * len(headers)
            updates = []
            last_col = _column_letter(len(headers))
            for row_number in sorted(set(row_numbers)):
                updates.append(
                    {
                        "range": f"A{row_number}:{last_col}{row_number}",
                        "values": [blank],
                    },
                )
            ws.batch_update(updates, value_input_option="RAW")
        except APIError as exc:
            self._raise_sheets_error(exc, f"clear_rows:{sheet_name}")

    def update_sync_status_rows(
        self,
        sheet_name: str,
        updates: list[dict[str, Any]],
        status_header: str = "Status Sync",
        error_header: str = "Erro",
    ) -> None:
        if not updates:
            return
        try:
            headers = self.ensure_headers(sheet_name, [status_header, error_header])
            status_col = headers.index(status_header) + 1
            error_col = headers.index(error_header) + 1
            ws = self._worksheet(sheet_name)
            payload = []
            for item in updates:
                row = int(item["row_number"])
                payload.append(
                    {
                        "range": f"{_column_letter(status_col)}{row}",
                        "values": [[_serialize(item.get("status"))]],
                    },
                )
                payload.append(
                    {
                        "range": f"{_column_letter(error_col)}{row}",
                        "values": [[_serialize(item.get("error"))]],
                    },
                )
            ws.batch_update(payload, value_input_option="RAW")
        except APIError as exc:
            self._raise_sheets_error(exc, f"update_sync_status_rows:{sheet_name}")

    def append_event(self, sheet_name: str, payload: dict[str, Any]) -> None:
        try:
            ws = self._worksheet(sheet_name)
            existing_headers = ws.row_values(1)
            payload_headers = list(payload.keys())

            if not existing_headers:
                ws.update("A1", [payload_headers])
                headers = payload_headers
            else:
                headers = existing_headers + [h for h in payload_headers if h not in existing_headers]
                if headers != existing_headers:
                    ws.update("A1", [headers])

            row_values = [_serialize(payload.get(header)) for header in headers]
            ws.append_row(row_values, value_input_option="RAW")
        except APIError as exc:
            self._raise_sheets_error(exc, f"append_event:{sheet_name}")

    def apply_alunos_layout(self, sheet_name: str, header_count: int) -> None:
        try:
            ws = self._worksheet(sheet_name)
            sheet_id = ws.id
            status_values = ws.col_values(5)[1:] if ws.row_count >= 2 else []
            progress_values = ws.col_values(7)[1:] if ws.row_count >= 2 else []

            requests = [
                {
                    "updateSheetProperties": {
                        "properties": {
                            "sheetId": sheet_id,
                            "gridProperties": {"frozenRowCount": 1},
                        },
                        "fields": "gridProperties.frozenRowCount",
                    },
                },
                {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 0,
                            "endRowIndex": 1,
                            "startColumnIndex": 0,
                            "endColumnIndex": max(header_count, 1),
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "backgroundColor": {
                                    "red": 0.102,
                                    "green": 0.235,
                                    "blue": 0.369,
                                },
                                "textFormat": {
                                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                                    "bold": True,
                                },
                            },
                        },
                        "fields": "userEnteredFormat(backgroundColor,textFormat)",
                    },
                },
            ]

            def number_format_request(
                start_col: int,
                end_col: int,
                fmt_type: str,
                pattern: str,
            ) -> dict[str, Any]:
                return {
                    "repeatCell": {
                        "range": {
                            "sheetId": sheet_id,
                            "startRowIndex": 1,
                            "startColumnIndex": start_col,
                            "endColumnIndex": end_col,
                        },
                        "cell": {
                            "userEnteredFormat": {
                                "numberFormat": {"type": fmt_type, "pattern": pattern},
                            },
                        },
                        "fields": "userEnteredFormat.numberFormat",
                    },
                }

            requests.extend(
                [
                    number_format_request(0, 1, "NUMBER", "0"),
                    number_format_request(5, 6, "DATE", "dd/mm/yyyy"),
                    number_format_request(6, 7, "NUMBER", '0.00"%"'),
                    number_format_request(7, 8, "NUMBER", "0.0"),
                    number_format_request(8, 9, "NUMBER", "0.0"),
                    number_format_request(9, 10, "NUMBER", '0.00"%"'),
                    number_format_request(11, 12, "DATE_TIME", "dd/mm/yyyy hh:mm"),
                ],
            )

            status_colors = {
                "ativo": {"red": 0.831, "green": 0.929, "blue": 0.855},
                "suspenso": {"red": 1.0, "green": 0.953, "blue": 0.804},
                "concluido": {"red": 0.8, "green": 0.898, "blue": 1.0},
            }
            for idx, raw_status in enumerate(status_values, start=2):
                status_text = str(raw_status or "").strip().lower()
                color = status_colors.get(status_text)
                if not color:
                    continue
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": idx - 1,
                                "endRowIndex": idx,
                                "startColumnIndex": 4,
                                "endColumnIndex": 5,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "backgroundColor": color,
                                    "textFormat": {"bold": True},
                                },
                            },
                            "fields": "userEnteredFormat(backgroundColor,textFormat.bold)",
                        },
                    },
                )

            for idx, raw_progress in enumerate(progress_values, start=2):
                value_str = str(raw_progress or "").strip().replace(",", ".")
                match = re.search(r"-?\d+(\.\d+)?", value_str)
                if not match:
                    continue
                value = float(match.group(0))
                if value <= 33:
                    color = {"red": 0.972, "green": 0.596, "blue": 0.596}
                elif value <= 66:
                    color = {"red": 1.0, "green": 0.949, "blue": 0.6}
                else:
                    color = {"red": 0.741, "green": 0.902, "blue": 0.741}
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": idx - 1,
                                "endRowIndex": idx,
                                "startColumnIndex": 6,
                                "endColumnIndex": 7,
                            },
                            "cell": {"userEnteredFormat": {"backgroundColor": color}},
                            "fields": "userEnteredFormat.backgroundColor",
                        },
                    },
                )

            self._spreadsheet.batch_update({"requests": requests})
        except APIError as exc:
            self._raise_sheets_error(exc, f"apply_alunos_layout:{sheet_name}")

    def ping(self) -> bool:
        try:
            _ = self._spreadsheet.title
            return True
        except APIError as exc:
            self._raise_sheets_error(exc, "ping")
        except Exception as exc:  # pragma: no cover - conectividade externa
            raise SheetsSyncError(f"Falha ao acessar Google Sheets: {exc}") from exc

