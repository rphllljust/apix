import axios, { AxiosError } from 'axios'
import axiosRetry from 'axios-retry'
import type {
  CourseItem,
  HealthResponse,
  SyncLogItem,
  SyncSummaryResponse,
} from '@/types/api'

const baseURL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'
const apiKey = import.meta.env.VITE_API_KEY ?? ''

export const api = axios.create({
  baseURL,
  timeout: 30000,
})

axiosRetry(api, {
  retries: 3,
  retryDelay: axiosRetry.exponentialDelay,
  shouldResetTimeout: true,
  retryCondition: (error) =>
    axiosRetry.isNetworkOrIdempotentRequestError(error) ||
    (error.response?.status !== undefined && error.response.status >= 500),
})

api.interceptors.request.use((config) => {
  if (apiKey) {
    config.headers['X-API-Key'] = apiKey
  }
  return config
})

function extractErrorMessage(error: unknown): string {
  if (error instanceof AxiosError) {
    const fallback =
      error.response?.statusText || error.message || 'Falha na comunicacao com a API.'
    const data = error.response?.data as
      | { error?: { message?: string }; message?: string }
      | undefined
    return data?.error?.message || data?.message || fallback
  }
  if (error instanceof Error) {
    return error.message
  }
  return 'Erro inesperado.'
}

export function toApiError(error: unknown): Error {
  return new Error(extractErrorMessage(error))
}

export async function fetchHealth(): Promise<HealthResponse> {
  const { data } = await api.get<HealthResponse>('/api/v1/health')
  return data
}

export async function fetchCourses(): Promise<CourseItem[]> {
  const { data } = await api.get<CourseItem[]>('/api/v1/moodle/courses')
  return data
}

interface GraphQLResponse<TData> {
  data?: TData
  errors?: Array<{ message?: string }>
}

async function queryGraphQL<TData>(query: string, variables?: Record<string, unknown>): Promise<TData> {
  const { data } = await api.post<GraphQLResponse<TData>>('/api/v1/graphql', {
    query,
    variables,
  })
  if (data.errors && data.errors.length > 0) {
    throw new Error(data.errors[0]?.message || 'Falha ao consultar endpoint GraphQL.')
  }
  if (!data.data) {
    throw new Error('Resposta GraphQL sem payload de dados.')
  }
  return data.data
}

export async function fetchCoursesGraphQL(): Promise<CourseItem[]> {
  const payload = await queryGraphQL<{ courses: CourseItem[] }>(`
    query Courses {
      courses {
        id
        shortname
        fullname
        visible
      }
    }
  `)
  return payload.courses ?? []
}

export async function fetchSyncLogs(): Promise<SyncLogItem[]> {
  const { data } = await api.get<SyncLogItem[]>('/api/v1/sync/logs')
  return data
}

export async function fetchSyncLogsGraphQL(): Promise<SyncLogItem[]> {
  const payload = await queryGraphQL<{ syncLogs: SyncLogItem[] }>(`
    query SyncLogs {
      syncLogs {
        sync_id
        timestamp
        direction
        entity
        course_id
        records_processed
        records_created
        records_updated
        records_failed
        errors
        duration_seconds
        status
      }
    }
  `)
  return payload.syncLogs ?? []
}

export async function triggerCourseSync(
  courseId: number,
  mode: 'full' | 'grades' | 'enrollments',
): Promise<SyncSummaryResponse> {
  const { data } = await api.post<SyncSummaryResponse>(
    `/api/v1/sync/course/${courseId}/${mode}`,
  )
  return data
}
