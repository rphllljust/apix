"""Responsabilidade: implementa o modulo scripts/setup_sheets.py."""

from __future__ import annotations

from app.config import get_settings
from app.sheets.client import GoogleSheetsClient
from app.sheets.templates import DEFAULT_SHEETS


def main() -> None:
    settings = get_settings()
    client = GoogleSheetsClient(settings)
    for sheet_name in DEFAULT_SHEETS:
        client.read_records(sheet_name)
        print(f"[OK] Aba validada/criada: {sheet_name}")

    headers_inscricao = [
        "Carimbo de data/hora",
        "Email - (Obrigatoriamente Gmail)",
        "Local que pretende fazer o curso",
        "Horario que pretende fazer o curso",
        "Nome completo",
        "CPF",
        "RG",
        "Orgao Expedidor (Nao colocar CNH)",
        "Data de Nascimento",
        "Natural (UF)",
        "Nome da Mae",
        "Nome do Pai",
        "Endereco",
        "Numero",
        "Bairro",
        "Cidade",
        "Estado",
        "Telefone Pessoal",
        "Telefone Emergencial",
        "Sexo",
        "Escolaridade",
        "Cursou ou cursa a modalidade",
        "Possui deficiencia",
        "Deficiencia / Transtorno",
        "RACA/COR",
        "Inserir todos os documentos em um unico arquivo PDF, seguindo a ordem. RG, CPF,",
        "Curso ID",
        "Status Sync",
        "Erro",
    ]
    client.ensure_headers(
        settings.google_enrollments_input_sheet,
        headers_inscricao,
    )
    print(f"[OK] Cabecalhos da aba de inscricoes atualizados: {settings.google_enrollments_input_sheet}")


if __name__ == "__main__":
    main()

