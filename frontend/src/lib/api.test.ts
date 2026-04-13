import { AxiosError } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  configureGoogleSheetsAppsScript,
  configureGoogleSheets,
  configureMoodleToken,
  fetchGoogleSheetsConfig,
  fetchCourses,
  fetchCoursesGraphQL,
  fetchHealth,
  fetchSyncLogs,
  fetchSyncLogsGraphQL,
  startGoogleSheetsOAuth,
  toApiError,
  triggerCourseSync,
} from '@/lib/api'

describe('api client helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('busca health com rota correta', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        moodle: {
          status: 'online',
          username: 'admin',
          fullname: 'Administrador AVA',
          userid: 2,
          site: 'cursos.idep.ro.gov.br',
          version: '4.3',
        },
        sheets: { status: 'online', last_check: '2026-04-12T10:00:00Z' },
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchHealth()
    expect(getSpy).toHaveBeenCalledWith('/api/v1/health')
    expect(data.sheets.status).toBe('online')
  })

  it('busca cursos', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: [{ id: 125, fullname: 'Curso A' }],
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchCourses()
    expect(getSpy).toHaveBeenCalledWith('/api/v1/moodle/courses')
    expect(data[0]?.id).toBe(125)
  })

  it('busca cursos via graphql', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        data: {
          courses: [{ id: 126, fullname: 'Curso GraphQL', shortname: 'GQL' }],
        },
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchCoursesGraphQL()
    expect(postSpy).toHaveBeenCalledWith('/api/v1/graphql', expect.any(Object))
    expect(data[0]?.id).toBe(126)
  })

  it('busca logs', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: [],
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchSyncLogs()
    expect(getSpy).toHaveBeenCalledWith('/api/v1/sync/logs')
    expect(data).toEqual([])
  })

  it('busca logs via graphql', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        data: {
          syncLogs: [],
        },
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchSyncLogsGraphQL()
    expect(postSpy).toHaveBeenCalledWith('/api/v1/graphql', expect.any(Object))
    expect(data).toEqual([])
  })

  it('falha graphql quando retorna errors', async () => {
    vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        errors: [{ message: 'Falha GraphQL' }],
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    await expect(fetchCoursesGraphQL()).rejects.toThrow('Falha GraphQL')
  })

  it('dispara sync por curso e modo', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        direction: 'moodle_to_sheets',
        started_at: '2026-04-11T00:00:00Z',
        finished_at: '2026-04-11T00:00:03Z',
        duration_seconds: 3,
        processed_counts: {},
        warnings: [],
        extra: {},
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await triggerCourseSync(125, 'grades')
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/sync/course/125/grades',
      undefined,
      { timeout: 180000 },
    )
    expect(data.duration_seconds).toBe(3)
  })

  it('dispara matriculas da planilha para o ava no modo enrollments', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        direction: 'sheets_to_moodle',
        started_at: '2026-04-11T00:00:00Z',
        finished_at: '2026-04-11T00:00:03Z',
        duration_seconds: 3,
        processed_counts: {},
        warnings: [],
        extra: {},
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await triggerCourseSync(125, 'enrollments')
    expect(postSpy).toHaveBeenCalledWith(
      '/api/v1/sync/course/125/enrollments-from-sheet',
      undefined,
      { timeout: 180000 },
    )
    expect(data.direction).toBe('sheets_to_moodle')
  })

  it('configura token do Moodle', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        ok: true,
        message: 'Token Moodle validado e salvo com sucesso.',
        moodle: {
          username: 'admin',
          fullname: 'Administrador AVA',
          userid: 2,
          site: 'cursos.idep.ro.gov.br',
          version: '4.3',
        },
        runtime_status: 'online',
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await configureMoodleToken('abc123token')
    expect(postSpy).toHaveBeenCalledWith('/api/v1/config/moodle-token', {
      token: 'abc123token',
    })
    expect(data.ok).toBe(true)
  })

  it('inicia oauth do google sheets', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        auth_url: 'https://accounts.google.com/o/oauth2/v2/auth?...',
        expires_in_seconds: 900,
        redirect_uri: 'http://localhost:8000/api/v1/google-sheets/oauth/callback',
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await startGoogleSheetsOAuth()
    expect(getSpy).toHaveBeenCalledWith('/api/v1/google-sheets/oauth/start')
    expect(data.expires_in_seconds).toBe(900)
  })

  it('busca configuracao do google sheets', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: {
        integration_mode: 'oauth',
        oauth: {
          configured: true,
          client_id_masked: '1234****abcd',
          redirect_uri: 'http://localhost:8000/api/v1/google-sheets/oauth/callback',
          refresh_token_configured: true,
        },
        apps_script: {
          configured: false,
          webhook_url: '',
          webhook_token_configured: false,
          timeout_seconds: 20,
        },
        spreadsheet: {
          id: '1abc',
          url: 'https://docs.google.com/spreadsheets/d/1abc/edit',
        },
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchGoogleSheetsConfig()
    expect(getSpy).toHaveBeenCalledWith('/api/v1/config/google-sheets')
    expect(data.oauth.configured).toBe(true)
  })

  it('salva configuracao do google sheets', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        ok: true,
        message: 'Configuracao Google salva com sucesso.',
        integration_mode: 'oauth',
        oauth: {
          configured: true,
          redirect_uri: 'http://localhost:8000/api/v1/google-sheets/oauth/callback',
          refresh_token_configured: false,
        },
        spreadsheet: {
          id: '1abc',
          url: 'https://docs.google.com/spreadsheets/d/1abc/edit',
        },
        sheets_runtime_status: 'offline',
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const payload = {
      client_id: '123.apps.googleusercontent.com',
      client_secret: 'super-secret',
      redirect_uri: 'http://localhost:8000/api/v1/google-sheets/oauth/callback',
      spreadsheet: 'https://docs.google.com/spreadsheets/d/1abc/edit',
    }

    const data = await configureGoogleSheets(payload)
    expect(postSpy).toHaveBeenCalledWith('/api/v1/config/google-sheets', payload)
    expect(data.ok).toBe(true)
  })

  it('salva configuracao do apps script', async () => {
    const postSpy = vi.spyOn(api, 'post').mockResolvedValue({
      data: {
        ok: true,
        message: 'Configuracao do Apps Script salva com sucesso.',
        integration_mode: 'apps_script',
        oauth: {
          configured: false,
          redirect_uri: 'http://localhost:8000/api/v1/google-sheets/oauth/callback',
          refresh_token_configured: false,
        },
        apps_script: {
          configured: true,
          webhook_url: 'https://script.google.com/macros/s/abc/exec',
          webhook_token_configured: false,
          timeout_seconds: 20,
        },
        spreadsheet: {
          id: '1abc',
          url: 'https://docs.google.com/spreadsheets/d/1abc/edit',
        },
        sheets_runtime_status: 'online',
      },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const payload = {
      spreadsheet: 'https://docs.google.com/spreadsheets/d/1abc/edit',
      webhook_url: 'https://script.google.com/macros/s/abc/exec',
      webhook_token: '',
    }

    const data = await configureGoogleSheetsAppsScript(payload)
    expect(postSpy).toHaveBeenCalledWith('/api/v1/config/google-sheets/apps-script', payload)
    expect(data.integration_mode).toBe('apps_script')
  })

  it('converte erro Axios com payload estruturado', () => {
    const err = new AxiosError('Falha', '500', undefined, undefined, {
      data: { error: { message: 'Erro detalhado' } },
      status: 500,
      statusText: 'Internal Server Error',
      headers: {},
      config: { headers: {} },
    })

    const normalized = toApiError(err)
    expect(normalized.message).toBe('Erro detalhado')
  })

  it('converte erro generico', () => {
    const normalized = toApiError(new Error('Falha de rede'))
    expect(normalized.message).toBe('Falha de rede')
  })
})
