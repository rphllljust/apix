# Frontend AVA IDEP

Painel frontend em React + Vite + TypeScript para operar e monitorar a API middleware Moodle ↔ Google Sheets.

## Stack implantada

- React 19 + TypeScript + Vite
- TailwindCSS
- Componentes no padrão shadcn/ui (`components.json` + `src/components/ui`)
- Axios
- TanStack Query
- Zustand
- React Hook Form + Zod
- Code splitting com `React.lazy` + `Suspense`
- Error Boundary para fallback de runtime
- ESLint + Prettier

## Setup

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## Variáveis de ambiente

- `VITE_API_BASE_URL`: URL da API middleware (ex.: `http://localhost:8000`)
- `VITE_API_KEY`: chave para header `X-API-Key`

## Comandos

```bash
npm run dev
npm run build
npm run lint
npm run format
npm run format:check
npm run test:coverage
npm run analyze
npm run preview
```

## Funcionalidades implementadas

- Painel de saúde da integração (`/api/v1/health`)
- Listagem de cursos com alternância de fonte (`REST` ou `GraphQL`)
- Disparo de sincronização por curso:
  - `full`
  - `grades`
  - `enrollments`
- Tabela de logs recentes (`REST` ou `GraphQL`)
- Busca com debounce
- Infinite scroll para logs
- Loading states, fallback de erro e layout responsivo mobile-first

## Estrutura principal

- `src/lib/api.ts`: client Axios e funções de API
- `src/store/use-ui-store.ts`: estado global com Zustand
- `src/components/ui/*`: componentes base
- `src/components/app-error-boundary.tsx`: fallback global de erro
- `src/pages/dashboard-page.tsx`: dashboard e fluxos de operação
