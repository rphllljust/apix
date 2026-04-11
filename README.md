# API Middleware Moodle <-> Google Sheets (FastAPI)

API intermediaria bidirecional para integrar AVA Moodle (Web Services REST) com Google Sheets, com sincronizacao de alunos, matriculas, notas, progresso e logs.

## Visao Geral

A API faz:

- `Moodle -> Sheets`: cursos, alunos, matriculas, gradebook, conclusao, progresso, badges, competencias, grupos e logs.
- `Sheets -> Moodle`: criacao/atualizacao de aluno (upsert) e matricula por planilhas de entrada.
- idempotencia de sincronizacao para nao duplicar registros.
- retry com backoff exponencial (`2s`, `4s`, `8s`) para timeout/5xx.
- batch de matriculas em lotes maximos de `50`.
- logs estruturados + persistencia em SQLite (`sync_log` e `error_log`).

## Requisitos

- Python `3.11+`
- Docker e Docker Compose (opcional para deploy)
- Moodle com Web Services REST ativos
- Conta Google Cloud com Service Account

## 1) Configuracao do Moodle

1. Acesse o Moodle como administrador.
2. Ative Web Services:
   - `Administracao do site > Recursos avancados > Habilitar servicos web`
3. Ative protocolo REST:
   - `Administracao do site > Plugins > Servicos web > Gerenciar protocolos > REST`
4. Crie um servico externo e adicione as funcoes exigidas.
5. Gere token para o usuario tecnico desse servico.
6. Guarde:
   - URL base do AVA (ex.: `https://cursos.idep.ro.gov.br`)
   - token do Moodle

## 2) Configuracao do Google Cloud + Sheets

1. Crie projeto no Google Cloud.
2. Ative APIs:
   - Google Sheets API
   - Google Drive API
3. Crie Service Account.
4. Gere chave JSON e baixe o arquivo.
5. Salve como `credentials.json` na raiz do projeto.
6. Compartilhe a planilha de destino com o email da Service Account (permissao de Editor).
7. Copie o `SPREADSHEET_ID` da URL da planilha.

## 3) Configuracao do projeto

1. Copie arquivo de ambiente:

```bash
cp .env.example .env
```

2. Edite `.env` com seus valores reais:

- `MOODLE_BASE_URL`
- `MOODLE_TOKEN`
- `GOOGLE_CREDENTIALS_FILE`
- `SPREADSHEET_ID`
- `API_SECRET_KEY`
- `CORS_ALLOWED_ORIGINS`

3. Instale dependencias:

```bash
pip install -r requirements.txt
```

## 4) Teste de conexao antes do primeiro uso

Execute:

```bash
python scripts/test_connection.py
```

O script valida:

- autenticacao no Moodle
- leitura de cursos no Moodle
- conectividade com Google Sheets
- escrita/leitura em aba temporaria

Toda a saida do script esta em portugues brasileiro.

## 5) Executar localmente

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Docs Swagger:

- `http://localhost:8000/docs`

## Token JWT (opcional)

Se quiser autenticar com `Bearer` em vez de `X-API-Key`:

```bash
curl -X POST http://localhost:8000/api/v1/auth/token \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=sua_senha_auth"
```

Use o `access_token` retornado no header:

```bash
Authorization: Bearer <token>
```

## 6) Executar com Docker (primeiro `docker-compose up`)

1. Garanta que `.env` e `credentials.json` estao configurados.
2. Suba stack:

```bash
docker compose up -d --build
```

3. Verifique saude:

```bash
curl http://localhost:8000/api/v1/health
```

## Seguranca Implementada

- token Moodle so via `.env`
- `credentials.json` no `.gitignore`
- autenticacao por `X-API-Key` **ou** JWT (`Bearer`) via OAuth2 password flow
- rate limit na middleware (padrao `60 req/min`)
- CORS restrito a origens configuradas
- secure headers (`CSP`, `X-Frame-Options`, `X-Content-Type-Options`, `HSTS`)
- sanitizacao de token/API key/CPF/email em logs e respostas de erro

## Endpoints Principais

### Sincronizacao

- `POST /api/v1/sync/course/{course_id}/full`
- `POST /api/v1/sync/course/{course_id}/grades`
- `POST /api/v1/sync/course/{course_id}/enrollments`
- `POST /api/v1/sync/sheets-to-moodle/enroll`
- `POST /api/v1/auth/token` (emite JWT)

### Consultas

- `GET /api/v1/moodle/courses`
- `GET /api/v1/moodle/course/{course_id}/students`
- `GET /api/v1/moodle/course/{course_id}/grades`
- `GET /api/v1/moodle/user/{user_id}/progress`

### Monitoramento

- `GET /api/v1/health`
- `GET /api/v1/sync/logs`
- `GET /api/v1/sync/logs/{sync_id}`

### GraphQL

- `POST /api/v1/graphql`
- Queries: `health`, `courses`, `syncLogs`
- Mutation: `triggerCourseSync`

## Testes

Executar:

```bash
python -m pytest -q
```

Cobertura minima implementada:

- conexao Moodle (autenticacao + cursos)
- conexao Sheets (leitura/escrita)
- `null` vs `0` em notas
- CPF invalido rejeitado
- idempotencia (sync 2x)
- encoding UTF-8 com acentos
- retry com backoff exponencial
- batch de 100+ alunos em lotes de 50

## Estrutura de Pastas

- `app/`: codigo da API
- `tests/`: testes unitarios
- `scripts/`: scripts operacionais
- `data/`: SQLite e artefatos locais
- `logs/`: logs de execucao

## Observacao sobre permissoes no Moodle

Se alguma funcao retornar erro de permissao, a API registra erro com sugestao de capabilities no log.
Verifique o servico externo, o perfil do usuario do token e as capacidades exigidas por cada wsfunction.
