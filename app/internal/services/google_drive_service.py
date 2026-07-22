"""Google Drive folder listing for spreadsheet templates (service account)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from app.internal.services.google_sheet_service import GoogleSheetError, parse_drive_folder_url
from app.settings import config


@dataclass
class DriveSpreadsheetItem:
    file_id: str
    name: str
    modified_time: Optional[str] = None
    web_view_link: Optional[str] = None


class GoogleDriveService:
    """List spreadsheets inside a shared Drive folder via service account."""

    MIME_SHEET = "application/vnd.google-apps.spreadsheet"

    def __init__(self) -> None:
        self._credentials_path = getattr(config, "GOOGLE_SERVICE_ACCOUNT_JSON", "") or ""
        self._credentials_json = getattr(config, "GOOGLE_SERVICE_ACCOUNT_JSON_DATA", "") or ""

    def _has_credentials(self) -> bool:
        if self._credentials_json.strip():
            return True
        path = self._credentials_path.strip()
        return bool(path and os.path.isfile(path))

    def _build_service(self):
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GoogleSheetError(
                "Google Drive API не установлен на сервере. "
                "Добавьте google-api-python-client и google-auth."
            ) from exc

        scopes = ["https://www.googleapis.com/auth/drive.readonly"]
        if self._credentials_json.strip():
            info = json.loads(self._credentials_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        else:
            creds = service_account.Credentials.from_service_account_file(
                self._credentials_path.strip(),
                scopes=scopes,
            )
        return build("drive", "v3", credentials=creds, cache_discovery=False)

    def list_spreadsheets_in_folder(self, folder_url: str) -> list[DriveSpreadsheetItem]:
        if not self._has_credentials():
            raise GoogleSheetError(
                "Для чтения папки Google Drive настройте GOOGLE_SERVICE_ACCOUNT_JSON "
                "и расшарьте папку на email сервисного аккаунта."
            )

        folder_id = parse_drive_folder_url(folder_url)
        service = self._build_service()
        query = (
            f"'{folder_id}' in parents and "
            f"mimeType='{self.MIME_SHEET}' and trashed=false"
        )

        items: list[DriveSpreadsheetItem] = []
        page_token: Optional[str] = None
        while True:
            resp = (
                service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, modifiedTime, webViewLink)",
                    pageToken=page_token,
                    pageSize=100,
                    orderBy="modifiedTime desc",
                )
                .execute()
            )
            for f in resp.get("files", []):
                items.append(
                    DriveSpreadsheetItem(
                        file_id=f["id"],
                        name=f.get("name") or "Без названия",
                        modified_time=f.get("modifiedTime"),
                        web_view_link=f.get("webViewLink"),
                    )
                )
            page_token = resp.get("nextPageToken")
            if not page_token:
                break
        return items

    @staticmethod
    def spreadsheet_url(file_id: str) -> str:
        return f"https://docs.google.com/spreadsheets/d/{file_id}/edit"
