import { AxiosError } from 'axios'
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  api,
  fetchCourses,
  fetchCoursesGraphQL,
  fetchHealth,
  fetchSyncLogs,
  fetchSyncLogsGraphQL,
  toApiError,
  triggerCourseSync,
} from '@/lib/api'

describe('api client helpers', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('busca health com rota correta', async () => {
    const getSpy = vi.spyOn(api, 'get').mockResolvedValue({
      data: { moodle: {}, sheets_ok: true, last_moodle_to_sheets: null, last_sheets_to_moodle: null },
      status: 200,
      statusText: 'OK',
      headers: {},
      config: { headers: {} },
    })

    const data = await fetchHealth()
    expect(getSpy).toHaveBeenCalledWith('/api/v1/health')
    expect(data.sheets_ok).toBe(true)
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
    expect(postSpy).toHaveBeenCalledWith('/api/v1/sync/course/125/grades')
    expect(data.duration_seconds).toBe(3)
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
