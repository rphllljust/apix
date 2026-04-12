"""Responsabilidade: implementa o modulo app/sheets/drive.py."""

from __future__ import annotations

from typing import Any

from googleapiclient.discovery import build
from loguru import logger

from app.config import Settings
from app.sheets.client import GoogleSheetsClient


class GoogleDriveClient:
    """Cliente para interagir com Google Drive API."""

    EXPORT_MIME = {
        "application/vnd.google-apps.document": "application/pdf",
        "application/vnd.google-apps.spreadsheet": "application/pdf",
        "application/vnd.google-apps.presentation": "application/pdf",
    }

    def __init__(self, settings: Settings) -> None:
        """
        Inicializa o cliente Drive usando credenciais do GoogleSheetsClient.
        As credenciais já incluem o escopo 'drive'.
        """
        creds = GoogleSheetsClient._build_credentials(settings)
        self._service = build("drive", "v3", credentials=creds)

    def list_files_in_folder(self, folder_id: str) -> list[dict[str, Any]]:
        """
        Lista todos os arquivos em uma pasta do Google Drive.

        Args:
            folder_id: ID da pasta no Google Drive

        Returns:
            Lista de dicts com 'id', 'name', 'mimeType'
        """
        try:
            resp = (
                self._service.files()
                .list(
                    q=f"'{folder_id}' in parents and trashed=false",
                    fields="files(id,name,mimeType)",
                    pageSize=100,
                )
                .execute()
            )
            files = resp.get("files", [])
            logger.info("Listed {} files in Drive folder={}", len(files), folder_id)
            return files
        except Exception as exc:
            logger.error("Falha ao listar arquivos Drive folder={} error={}", folder_id, exc)
            raise

    def download_file(self, file_id: str, mime_type: str) -> tuple[bytes, str]:
        """
        Baixa um arquivo do Google Drive.

        Se o arquivo for um Google Doc/Sheet/Slide, exporta como PDF.
        Caso contrário, faz download do arquivo binário.

        Args:
            file_id: ID do arquivo no Google Drive
            mime_type: MIME type do arquivo

        Returns:
            Tupla (conteúdo_bytes, mime_type_final)
        """
        try:
            export_mime = self.EXPORT_MIME.get(mime_type)
            if export_mime:
                # Google Docs/Sheets/Slides - export como PDF
                content = (
                    self._service.files()
                    .export_media(fileId=file_id, mimeType=export_mime)
                    .execute()
                )
                logger.debug("Exported Drive file={} as PDF", file_id)
                return content, export_mime
            # Arquivo normal - download direto
            content = self._service.files().get_media(fileId=file_id).execute()
            logger.debug("Downloaded Drive file={} mime_type={}", file_id, mime_type)
            return content, mime_type
        except Exception as exc:
            logger.error("Falha ao baixar arquivo Drive file_id={} error={}", file_id, exc)
            raise
