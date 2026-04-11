"""Script de diagnostico inicial para validar conexoes com Moodle e Google Sheets."""

from __future__ import annotations

import asyncio
import re
import sys
from datetime import UTC, datetime

from app.config import get_settings
from app.exceptions import MoodleAPIError, MoodleConnectionError, MoodleTokenExpiredError
from app.moodle.client import MoodleClient
from app.moodle.metrics import MoodleService
from app.sheets.client import GoogleSheetsClient
from app.sheets.exceptions import SheetQuotaExceededError, SheetsSyncError


def _titulo(texto: str) -> None:
    print(f"\n=== {texto} ===")


def _ok(texto: str) -> None:
    print(f"[OK] {texto}")


def _erro(texto: str) -> None:
    print(f"[ERRO] {texto}")


def _extrair_capabilities(texto: str) -> list[str]:
    encontrados = re.findall(r"[a-z]+/[a-z0-9:_]+", texto.lower())
    unicos: list[str] = []
    for item in encontrados:
        if item not in unicos:
            unicos.append(item)
    return unicos


async def main() -> int:
    """Executa teste de conectividade fim a fim com mensagens em portugues."""
    settings = get_settings()

    moodle_client = MoodleClient(settings)
    moodle_service = MoodleService(moodle_client, settings)
    sheets_client = GoogleSheetsClient(settings)

    falhou = False

    try:
        _titulo("Teste Moodle")
        try:
            site_info = await moodle_service.ping()
            cursos = await moodle_service.get_courses()
            _ok(
                "Autenticacao Moodle validada com sucesso. "
                f"Site: {site_info.get('site_name') or 'N/A'} | Usuario: {site_info.get('username') or 'N/A'}",
            )
            _ok(f"Leitura de cursos validada. Total retornado: {len(cursos)}")
        except MoodleTokenExpiredError:
            falhou = True
            _erro("Token do Moodle invalido ou expirado. Gere um novo token em Administracao > Servicos web > Tokens.")
        except MoodleConnectionError as exc:
            falhou = True
            _erro(f"Falha de conexao com o Moodle: {exc}")
        except MoodleAPIError as exc:
            falhou = True
            _erro(f"Erro da API Moodle: {exc.errorcode} | {exc.message}")
            texto_permissao = f"{exc.errorcode} {exc.message} {exc.debuginfo}".lower()
            if any(token in texto_permissao for token in ("nopermissions", "accessdenied", "requirecapability", "permission")):
                capacidades = _extrair_capabilities(texto_permissao)
                if capacidades:
                    _erro("Sugestao: habilite no perfil/tipo de servico as capabilities: " + ", ".join(capacidades))
                else:
                    _erro(
                        "Sugestao: verifique as capabilities do perfil do token (ex.: webservice/rest:use e permissoes das funcoes Web Services).",
                    )

        _titulo("Teste Google Sheets")
        try:
            if sheets_client.ping():
                _ok("Conexao com Google Sheets validada com sucesso.")

            sheet_name = f"_diagnostico_conexao_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"
            payload = [
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "mensagem": "teste de escrita e leitura",
                    "status": "ok",
                },
            ]
            linhas_escritas = sheets_client.overwrite_records(sheet_name, payload)
            linhas_lidas = sheets_client.read_records(sheet_name)

            if linhas_escritas == 1 and len(linhas_lidas) == 1:
                _ok(f"Escrita e leitura validadas na aba temporaria '{sheet_name}'.")
            else:
                falhou = True
                _erro("Falha na validacao de escrita/leitura do Google Sheets.")
        except SheetQuotaExceededError:
            falhou = True
            _erro("Quota da API Google Sheets excedida. Aguarde alguns minutos e tente novamente.")
        except SheetsSyncError as exc:
            falhou = True
            _erro(f"Erro de sincronizacao com Google Sheets: {exc}")

    finally:
        await moodle_client.close()

    _titulo("Resultado Final")
    if falhou:
        _erro("Diagnostico finalizado com falhas. Corrija os pontos acima antes do primeiro uso.")
        return 1

    _ok("Diagnostico concluido com sucesso. Ambiente pronto para uso inicial.")
    return 0


if __name__ == "__main__":
    codigo = asyncio.run(main())
    sys.exit(codigo)
