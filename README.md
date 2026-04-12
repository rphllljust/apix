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
- Conta Google Cloud com Service Account **ou** Google Apps Script Web App

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

## Alternativa sem Google Cloud (Google Apps Script)

Se voce nao quiser usar Google Cloud, da para integrar via Web App do Apps Script.

1. Abra a planilha Google de destino.
2. Va em `Extensoes > Apps Script`.
3. Cole o conteudo de `scripts/google_apps_script_webhook.gs`.
4. (Opcional) Em `Configuracoes do projeto > Propriedades do script`, crie:
   - `APPS_SCRIPT_WEBHOOK_TOKEN` (segredo compartilhado)
   - `SPREADSHEET_ID` (se o script for standalone em vez de vinculado a planilha)
5. Publique em `Implantar > Nova implantacao > Aplicativo da Web`:
   - Executar como: `Voce`
   - Quem tem acesso: `Qualquer pessoa com o link`
6. Copie a URL do Web App publicado e configure no `.env`:

```bash
GOOGLE_APPS_SCRIPT_WEBHOOK_URL=https://script.google.com/macros/s/SEU_DEPLOYMENT_ID/exec
GOOGLE_APPS_SCRIPT_WEBHOOK_TOKEN=SEU_TOKEN_OPCIONAL
GOOGLE_APPS_SCRIPT_TIMEOUT_SECONDS=20
SPREADSHEET_ID=ID_DA_PLANILHA_GOOGLE
GOOGLE_SPREADSHEET_ID=ID_DA_PLANILHA_GOOGLE
```

Quando `GOOGLE_APPS_SCRIPT_WEBHOOK_URL` estiver preenchido, a API usa o Apps Script em vez da autenticacao Google Cloud.

## 3) Configuracao do projeto

1. Copie arquivo de ambiente:

```bash
cp .env.example .env
```

2. Edite `.env` com seus valores reais:

- `MOODLE_BASE_URL`
- `MOODLE_URL` (alias de compatibilidade)
- `MOODLE_TOKEN`
- `MOODLE_WSFORMAT` (`json`)
- `GOOGLE_CREDENTIALS_FILE`
- `SPREADSHEET_ID`
- `GOOGLE_OAUTH_CLIENT_ID` (opcional para login Google Sheets via OAuth)
- `GOOGLE_OAUTH_CLIENT_SECRET` (opcional para login Google Sheets via OAuth)
- `GOOGLE_OAUTH_REDIRECT_URI` (ex.: `http://localhost:8000/api/v1/google-sheets/oauth/callback`)
- `GOOGLE_APPS_SCRIPT_WEBHOOK_URL` (opcional, para modo sem Google Cloud)
- `GOOGLE_APPS_SCRIPT_WEBHOOK_TOKEN` (opcional, recomendado para proteger o webhook)
- `GOOGLE_APPS_SCRIPT_TIMEOUT_SECONDS` (opcional, padrao `20`)
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

## Login Google Sheets via OAuth (opcional)

Se preferir login Google no painel em vez de `credentials.json`:

1. No Google Cloud, crie credencial OAuth 2.0 (tipo Web).
2. Adicione no `.env`:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REDIRECT_URI` (ex.: `http://localhost:8000/api/v1/google-sheets/oauth/callback`)
3. No painel, use o botao **Login Google Sheets** quando o status estiver offline.
4. Ao concluir o consentimento, o backend salva `GOOGLE_OAUTH_REFRESH_TOKEN` no `.env` automaticamente.
5. Se preferir, configure tudo pelo proprio painel em **Configurar Google**:
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `GOOGLE_OAUTH_REDIRECT_URI`
   - URL da planilha (o backend extrai o `SPREADSHEET_ID`)

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
- `POST /api/v1/config/moodle-token` (valida e salva token do Moodle)
- `GET /api/v1/config/google-sheets` (consulta configuracao atual do OAuth/planilha)
- `POST /api/v1/config/google-sheets` (salva OAuth Google e planilha no `.env`)
- `GET /api/v1/google-sheets/oauth/start` (gera URL de login Google Sheets)
- `GET /api/v1/google-sheets/oauth/callback` (recebe callback e salva refresh token)

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
