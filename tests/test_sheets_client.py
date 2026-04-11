"""Testes do cliente de Google Sheets com fake in-memory para conexao, escrita e encoding."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from app.sheets.client import GoogleSheetsClient, _column_letter, _serialize


class FakeWorksheet:
    """Worksheet fake que simula operacoes usadas nos testes."""

    def __init__(self) -> None:
        self.headers: list[str] = []
        self.rows: list[list[str]] = []

    def clear(self) -> None:
        self.headers = []
        self.rows = []

    def row_values(self, row: int) -> list[str]:
        if row == 1:
            return list(self.headers)
        row_index = row - 2
        if 0 <= row_index < len(self.rows):
            return list(self.rows[row_index])
        return []

    def update(self, _: str, values: list[list[Any]], value_input_option: str = "RAW") -> None:
        if not values:
            return
        self.headers = [str(item) for item in values[0]]
        incoming_rows = values[1:]
        self.rows = [["" if cell is None else str(cell) for cell in row] for row in incoming_rows]

    def get_all_values(self) -> list[list[str]]:
        if not self.headers:
            return []
        return [list(self.headers), *[list(row) for row in self.rows]]


class FakeSpreadsheet:
    """Spreadsheet fake para permitir ping sem chamar API externa."""

    def __init__(self, title: str = "Planilha Teste") -> None:
        self.title = title


def build_fake_client() -> tuple[GoogleSheetsClient, FakeWorksheet]:
    """Monta cliente fake sem credenciais reais do Google."""
    client = object.__new__(GoogleSheetsClient)
    worksheet = FakeWorksheet()
    client._worksheet = lambda sheet_name, create_if_missing=True: worksheet  # type: ignore[attr-defined]
    client._spreadsheet = FakeSpreadsheet()
    return client, worksheet


def test_column_letter() -> None:
    """Converte indice numerico para letra de coluna do Sheets."""
    assert _column_letter(1) == "A"
    assert _column_letter(26) == "Z"
    assert _column_letter(27) == "AA"


def test_serialize_null_and_zero_are_different() -> None:
    """Garante que None vira vazio e zero vira string 0."""
    assert _serialize(None) == ""
    assert _serialize(0) == "0"


def test_sheets_connection_read_write_roundtrip() -> None:
    """Valida escrita e leitura no cliente fake simulando conexao funcional."""
    client, _ = build_fake_client()

    written = client.overwrite_records(
        "Aba Teste",
        [
            {"id": 1, "nome": "Aluno 1", "nota": 8.5},
            {"id": 2, "nome": "Aluno 2", "nota": 7.0},
        ],
    )
    records = client.read_records("Aba Teste")

    assert written == 2
    assert len(records) == 2
    assert records[0]["nome"] == "Aluno 1"


def test_null_is_not_zero_in_sheet_cells() -> None:
    """Confirma que nota nula nao e convertida para zero na planilha."""
    client, _ = build_fake_client()

    client.overwrite_records(
        "Notas",
        [
            {"id": "1", "nota": None},
            {"id": "2", "nota": 0},
        ],
    )
    records = client.read_records("Notas")

    assert records[0]["nota"] == ""
    assert records[1]["nota"] == "0"


def test_encoding_utf8_accents_survive_roundtrip() -> None:
    """Valida preservacao de acentos em ida e volta para o Sheets."""
    client, _ = build_fake_client()

    client.overwrite_records(
        "Acentos",
        [
            {
                "id": "1",
                "nome": "José da Conceição",
                "atualizado_em": datetime(2026, 4, 11, 15, 30),
            },
        ],
    )
    records = client.read_records("Acentos")

    assert records[0]["nome"] == "José da Conceição"
