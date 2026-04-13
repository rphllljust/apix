import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Activity,
  BookOpenCheck,
  Cloud,
  Eye,
  EyeOff,
  KeyRound,
  RefreshCw,
  Search,
  Server,
  ShieldCheck,
  X,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type ReactElement } from 'react'
import { useForm } from 'react-hook-form'
import { z } from 'zod'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardDescription, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Select } from '@/components/ui/select'
import { SHEETS_ENROLLMENT_COLUMNS } from '@/constants/sheets-columns'
import { useDebounce } from '@/hooks/use-debounce'
import {
  configureGoogleSheetsAppsScript,
  configureMoodleToken,
  fetchGoogleSheetsConfig,
  fetchCourses,
  fetchCoursesGraphQL,
  fetchHealth,
  fetchSyncLogs,
  fetchSyncLogsGraphQL,
  resolvedApiBaseUrl,
  startGoogleSheetsOAuth,
  toApiError,
  triggerCourseSync,
  triggerDriveToMoodleSync,
} from '@/lib/api'
import { useUiStore } from '@/store/use-ui-store'
import type { CourseItem, SyncLogItem } from '@/types/api'

const syncFormSchema = z.object({
  courseId: z.coerce.number().int().positive('Informe um curso valido.'),
  mode: z.enum(['full', 'grades', 'enrollments']),
})

type SyncFormInput = z.input<typeof syncFormSchema>
type SyncFormOutput = z.output<typeof syncFormSchema>

function mapStatusTone(
  status: SyncLogItem['status'],
): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'success') {
    return 'success'
  }
  if (status === 'partial') {
    return 'warning'
  }
  if (status === 'failed') {
    return 'danger'
  }
  return 'neutral'
}

function mapMoodleStatusTone(
  status: 'online' | 'offline' | 'auth_error' | undefined,
): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'online') {
    return 'success'
  }
  if (status === 'auth_error') {
    return 'warning'
  }
  if (status === 'offline') {
    return 'danger'
  }
  return 'neutral'
}

function moodleStatusLabel(status: 'online' | 'offline' | 'auth_error' | undefined): string {
  if (status === 'online') {
    return 'Online'
  }
  if (status === 'auth_error') {
    return 'Erro de Token'
  }
  if (status === 'offline') {
    return 'Offline'
  }
  return 'Pendente'
}

function sortCourses(courses: CourseItem[] | undefined): CourseItem[] {
  return [...(courses ?? [])].sort((a, b) =>
    (a.fullname ?? a.shortname ?? '').localeCompare(b.fullname ?? b.shortname ?? ''),
  )
}

export default function DashboardPage(): ReactElement {
  const apiBaseUrl = resolvedApiBaseUrl
  const apiBaseUrlDisplay =
    apiBaseUrl.startsWith('/') && typeof window !== 'undefined'
      ? `${window.location.origin}${apiBaseUrl}`
      : apiBaseUrl

  const queryClient = useQueryClient()
  const selectedCourseId = useUiStore((s) => s.selectedCourseId)
  const setSelectedCourseId = useUiStore((s) => s.setSelectedCourseId)
  const syncMode = useUiStore((s) => s.syncMode)
  const setSyncMode = useUiStore((s) => s.setSyncMode)
  const dataSource = useUiStore((s) => s.dataSource)
  const setDataSource = useUiStore((s) => s.setDataSource)

  const [courseSearchText, setCourseSearchText] = useState<string>('')
  const [logSearchText, setLogSearchText] = useState<string>('')
  const [visibleLogsCount, setVisibleLogsCount] = useState<number>(10)
  const [isTokenModalOpen, setIsTokenModalOpen] = useState<boolean>(false)
  const [tokenInput, setTokenInput] = useState<string>('')
  const [tokenVisible, setTokenVisible] = useState<boolean>(false)
  const [isGoogleConfigModalOpen, setIsGoogleConfigModalOpen] = useState<boolean>(false)
  const [googleAppsScriptUrl, setGoogleAppsScriptUrl] = useState<string>('')
  const [googleAppsScriptToken, setGoogleAppsScriptToken] = useState<string>('')
  const [googleAppsScriptTokenVisible, setGoogleAppsScriptTokenVisible] = useState<boolean>(false)
  const [googleSpreadsheetInput, setGoogleSpreadsheetInput] = useState<string>('')
  const [isDriveModalOpen, setIsDriveModalOpen] = useState<boolean>(false)
  const [driveFolderId, setDriveFolderId] = useState<string>('')
  const [driveFileIds, setDriveFileIds] = useState<string>('')
  const [driveSectionNumber, setDriveSectionNumber] = useState<number>(0)
  const loadMoreRef = useRef<HTMLDivElement | null>(null)

  const debouncedCourseSearch = useDebounce(courseSearchText, 300)
  const debouncedLogSearch = useDebounce(logSearchText, 300)

  const {
    register,
    handleSubmit,
    setValue,
    formState: { errors },
  } = useForm<SyncFormInput, unknown, SyncFormOutput>({
    resolver: zodResolver(syncFormSchema),
    mode: 'onSubmit',
    defaultValues: {
      courseId: selectedCourseId ?? undefined,
      mode: syncMode,
    },
  })

  const healthQuery = useQuery({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30000,
  })

  const coursesQuery = useQuery({
    queryKey: ['courses', dataSource],
    queryFn: dataSource === 'graphql' ? fetchCoursesGraphQL : fetchCourses,
    staleTime: 5 * 60 * 1000,
    retry: 2,
  })

  const logsQuery = useQuery({
    queryKey: ['sync-logs', dataSource],
    queryFn: dataSource === 'graphql' ? fetchSyncLogsGraphQL : fetchSyncLogs,
    refetchInterval: 20000,
    retry: 2,
  })

  const googleSheetsConfigQuery = useQuery({
    queryKey: ['google-sheets-config'],
    queryFn: fetchGoogleSheetsConfig,
    staleTime: 5 * 60 * 1000,
    retry: 1,
  })

  const syncMutation = useMutation({
    mutationFn: ({ courseId, mode }: SyncFormOutput) => triggerCourseSync(courseId, mode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sync-logs'] })
      void queryClient.invalidateQueries({ queryKey: ['health'] })
    },
  })

  const tokenMutation = useMutation({
    mutationFn: (token: string) => configureMoodleToken(token),
    onSuccess: () => {
      setTokenInput('')
      setTokenVisible(false)
      setIsTokenModalOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['health'] })
      void queryClient.invalidateQueries({ queryKey: ['courses'] })
    },
  })

  const sheetsOAuthMutation = useMutation({
    mutationFn: () => startGoogleSheetsOAuth(),
    onSuccess: (payload) => {
      window.open(payload.auth_url, '_blank', 'noopener,noreferrer')
    },
    onError: (error) => {
      const message = toApiError(error).message.toLowerCase()
      if (message.includes('google_oauth_client_id') || message.includes('google_oauth_client_secret')) {
        setIsGoogleConfigModalOpen(true)
      }
    },
  })

  const driveToMoodleMutation = useMutation({
    mutationFn: (payload: { folder_id?: string; file_ids?: string[]; section_number?: number }) =>
      selectedCourseId ? triggerDriveToMoodleSync(selectedCourseId, payload) : Promise.reject(new Error('Nenhum curso selecionado')),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sync-logs'] })
      void queryClient.invalidateQueries({ queryKey: ['health'] })
    },
  })

  const googleConfigMutation = useMutation({
    mutationFn: () =>
      configureGoogleSheetsAppsScript({
        spreadsheet: googleSpreadsheetInput.trim(),
        webhook_url: googleAppsScriptUrl.trim(),
        webhook_token: googleAppsScriptToken.trim(),
      }),
    onSuccess: () => {
      setGoogleAppsScriptToken('')
      setGoogleAppsScriptTokenVisible(false)
      setIsGoogleConfigModalOpen(false)
      void queryClient.invalidateQueries({ queryKey: ['google-sheets-config'] })
      void queryClient.invalidateQueries({ queryKey: ['health'] })
    },
  })

  const filteredCourses = useMemo(() => {
    const search = debouncedCourseSearch.trim().toLowerCase()
    const sorted = sortCourses(coursesQuery.data)
    if (!search) {
      return sorted
    }
    return sorted.filter((course) => {
      const label = `${course.id} ${course.fullname ?? ''} ${course.shortname ?? ''}`.toLowerCase()
      return label.includes(search)
    })
  }, [coursesQuery.data, debouncedCourseSearch])

  const filteredLogs = useMemo(() => {
    const search = debouncedLogSearch.trim().toLowerCase()
    const rows = logsQuery.data ?? []
    if (!search) {
      return rows
    }
    return rows.filter((row) => {
      const line =
        `${row.entity} ${row.direction} ${row.course_id} ${row.status} ${row.timestamp}`.toLowerCase()
      return line.includes(search)
    })
  }, [logsQuery.data, debouncedLogSearch])

  const visibleLogs = useMemo(
    () => filteredLogs.slice(0, visibleLogsCount),
    [filteredLogs, visibleLogsCount],
  )

  useEffect(() => {
    const node = loadMoreRef.current
    if (!node) {
      return
    }
    const observer = new IntersectionObserver(
      (entries) => {
        const [entry] = entries
        if (entry?.isIntersecting) {
          setVisibleLogsCount((prev) => Math.min(prev + 10, filteredLogs.length))
        }
      },
      { rootMargin: '120px' },
    )
    observer.observe(node)
    return () => observer.disconnect()
  }, [filteredLogs.length])

  const latestSyncStatus = useMemo(() => {
    const item = logsQuery.data?.[0]
    if (!item) {
      return <Badge tone="neutral">Sem sincronizacao registrada</Badge>
    }
    return <Badge tone={mapStatusTone(item.status)}>{item.status.toUpperCase()}</Badge>
  }, [logsQuery.data])

  const moodleStatus = healthQuery.data?.moodle?.status
  const sheetsStatus = healthQuery.data?.sheets?.status
  const isMoodleAuthError = moodleStatus === 'auth_error'
  const googleAppsScriptConfigured = googleSheetsConfigQuery.data?.apps_script?.configured ?? false
  const googleAppsScriptTokenConfigured =
    googleSheetsConfigQuery.data?.apps_script?.webhook_token_configured ?? false
  const googleIntegrationMode = googleSheetsConfigQuery.data?.integration_mode ?? 'oauth'

  const onSubmit = handleSubmit((values: SyncFormOutput) => {
    setSelectedCourseId(values.courseId)
    setSyncMode(values.mode)
    syncMutation.mutate(values)
  })

  const openGoogleConfigModal = () => {
    const currentConfig = googleSheetsConfigQuery.data
    setGoogleAppsScriptUrl(currentConfig?.apps_script.webhook_url || '')
    setGoogleAppsScriptToken('')
    setGoogleAppsScriptTokenVisible(false)
    setGoogleSpreadsheetInput(currentConfig?.spreadsheet.url || currentConfig?.spreadsheet.id || '')
    setIsGoogleConfigModalOpen(true)
    void googleSheetsConfigQuery.refetch()
  }

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-bg text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_10%_15%,rgba(15,118,110,.22),transparent_40%),radial-gradient(circle_at_90%_5%,rgba(194,65,12,.18),transparent_32%),radial-gradient(circle_at_50%_95%,rgba(15,118,110,.17),transparent_40%)]" />
      <main className="relative mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-8 md:px-10">
        <header className="flex flex-col gap-3">
          <p className="w-fit rounded-full border border-line bg-panel px-3 py-1 font-mono text-xs uppercase tracking-[0.16em] text-slate-700">
            Middleware AVA IDEP
          </p>
          <h1 className="text-3xl font-bold leading-tight md:text-5xl">
            Painel de Integracao Moodle &lt;-&gt; Google Sheets
          </h1>
          <p className="max-w-3xl text-sm text-slate-700 md:text-base">
            Operacao direta de sync e monitoramento da API FastAPI.
          </p>
        </header>

        <section className="grid gap-4 md:grid-cols-3">
          <Card className="md:col-span-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="space-y-2">
                <CardTitle className="flex items-center gap-2">
                  <Server className="h-5 w-5 text-brand" />
                  Saude da Integracao
                </CardTitle>
                <CardDescription>
                  Base URL:{' '}
                  <strong>{apiBaseUrlDisplay}</strong>
                </CardDescription>
              </div>
              <div className="flex items-center gap-2">
                <Select
                  aria-label="Fonte de dados de consulta"
                  value={dataSource}
                  onChange={(event) => setDataSource(event.target.value as 'rest' | 'graphql')}
                >
                  <option value="rest">REST</option>
                  <option value="graphql">GraphQL</option>
                </Select>
                <Button
                  variant="ghost"
                  onClick={() => {
                    void healthQuery.refetch()
                    void logsQuery.refetch()
                    void coursesQuery.refetch()
                    void googleSheetsConfigQuery.refetch()
                  }}
                  disabled={healthQuery.isFetching}
                >
                  <RefreshCw className={`h-4 w-4 ${healthQuery.isFetching ? 'animate-spin' : ''}`} />
                  Atualizar
                </Button>
              </div>
            </div>

            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              <div className="rounded-md border border-line bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Moodle</p>
                  <Badge tone={mapMoodleStatusTone(moodleStatus)}>
                    {moodleStatusLabel(moodleStatus)}
                  </Badge>
                </div>
                <p className="mt-1 text-sm font-semibold">
                  {healthQuery.data?.moodle?.fullname || 'Usuario tecnico nao identificado'}
                </p>
                <p className="text-xs text-slate-500">
                  Usuario tecnico: {healthQuery.data?.moodle?.username || '—'}
                </p>
                <p className="text-xs text-slate-500">{healthQuery.data?.moodle?.site || '—'}</p>
                {isMoodleAuthError && (
                  <Button
                    className="mt-3 w-full"
                    variant="accent"
                    type="button"
                    onClick={() => setIsTokenModalOpen(true)}
                  >
                    <KeyRound className="h-4 w-4" />
                    Configurar Token
                  </Button>
                )}
              </div>
              <div className="rounded-md border border-line bg-white p-3">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                    Google Sheets
                  </p>
                  <Badge tone={sheetsStatus === 'online' ? 'success' : 'danger'}>
                    {sheetsStatus === 'online' ? 'Online' : 'Offline'}
                  </Badge>
                </div>
                <p className="mt-1 text-sm font-semibold">
                  {healthQuery.data?.sheets?.status === 'online' ? 'Conectado' : 'Indisponivel'}
                </p>
                <p className="text-xs text-slate-500">
                  Ultima verificacao: {' '}
                  {healthQuery.data?.sheets?.last_check
                    ? new Date(healthQuery.data.sheets.last_check).toLocaleString('pt-BR')
                    : 'Pendente'}
                </p>
                <p className="text-xs text-slate-500">
                  Planilha: {googleSheetsConfigQuery.data?.spreadsheet.id || 'Nao configurada'}
                </p>
                <p className="text-xs text-slate-500">
                  Modo: {googleIntegrationMode === 'apps_script' ? 'Apps Script (sem Cloud)' : 'OAuth'}
                </p>
                <p className="text-xs text-slate-500">
                  Apps Script: {googleAppsScriptConfigured ? 'Configurado' : 'Pendente'} | Token:{' '}
                  {googleAppsScriptTokenConfigured ? 'OK' : 'Nao configurado'}
                </p>
                <div className="mt-3 grid gap-2">
                  <Button
                    className="w-full"
                    variant="ghost"
                    type="button"
                    onClick={openGoogleConfigModal}
                    disabled={googleConfigMutation.isPending}
                  >
                    <KeyRound className="h-4 w-4" />
                    Configurar Apps Script
                  </Button>
                  {googleIntegrationMode === 'oauth' && sheetsStatus !== 'online' && (
                    <Button
                      className="w-full"
                      variant="accent"
                      type="button"
                      onClick={() => sheetsOAuthMutation.mutate()}
                      disabled={sheetsOAuthMutation.isPending}
                    >
                      <KeyRound className="h-4 w-4" />
                      {sheetsOAuthMutation.isPending ? 'Abrindo login...' : 'Login Google Sheets'}
                    </Button>
                  )}
                </div>
                {googleConfigMutation.isSuccess && (
                  <p className="mt-2 text-xs font-semibold text-emerald-700">
                    {googleConfigMutation.data.message}
                  </p>
                )}
                {googleIntegrationMode === 'oauth' && sheetsOAuthMutation.isError && (
                  <p className="mt-2 text-xs font-semibold text-red-700">
                    {toApiError(sheetsOAuthMutation.error).message}
                  </p>
                )}
              </div>
            </div>
          </Card>

          <Card>
            <CardTitle className="flex items-center gap-2">
              <ShieldCheck className="h-5 w-5 text-accent" />
              Status de Sync
            </CardTitle>
            <CardDescription className="mt-2">Ultima execucao registrada.</CardDescription>
            <div className="mt-4">{latestSyncStatus}</div>
            <p className="mt-3 text-xs text-slate-500">Consulta ativa: {dataSource.toUpperCase()}</p>
          </Card>
        </section>

        <section className="grid gap-4 lg:grid-cols-5">
          <Card className="lg:col-span-2">
            <CardTitle className="flex items-center gap-2">
              <BookOpenCheck className="h-5 w-5 text-brand" />
              Executar Sincronizacao
            </CardTitle>
            <CardDescription className="mt-2">
              Selecione curso e tipo de sincronizacao para disparo imediato.
            </CardDescription>

            <div className="mt-4 space-y-1">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                Busca rapida de curso
              </label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-slate-500" />
                <Input
                  className="pl-8"
                  placeholder="Digite nome, shortname ou ID..."
                  value={courseSearchText}
                  onChange={(event) => setCourseSearchText(event.target.value)}
                />
              </div>
            </div>

            {coursesQuery.isLoading && (
              <p className="mt-3 text-xs text-slate-500" role="status" aria-live="polite">
                Carregando cursos...
              </p>
            )}

            <form className="mt-4 space-y-3" onSubmit={onSubmit}>
              <div className="space-y-1">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Curso
                </label>
                <Select
                  {...register('courseId')}
                  onChange={(event) => {
                    const nextValue = Number(event.target.value)
                    setValue('courseId', nextValue)
                    setSelectedCourseId(Number.isNaN(nextValue) ? null : nextValue)
                  }}
                  value={selectedCourseId ?? ''}
                >
                  <option value="">Selecione...</option>
                  {filteredCourses.map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.id} - {course.fullname ?? course.shortname ?? 'Curso sem nome'}
                    </option>
                  ))}
                </Select>
                {errors.courseId && (
                  <p className="text-xs font-semibold text-red-700">{errors.courseId.message}</p>
                )}
              </div>

              <div className="space-y-1">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Modo
                </label>
                <Select
                  {...register('mode')}
                  onChange={(event) => {
                    const nextMode = event.target.value as SyncFormOutput['mode']
                    setValue('mode', nextMode)
                    setSyncMode(nextMode)
                  }}
                  value={syncMode}
                >
                  <option value="full">Completo</option>
                  <option value="grades">Notas e progresso</option>
                  <option value="enrollments">Matriculas (Planilha para AVA)</option>
                </Select>
              </div>

              <Button className="w-full" type="submit" disabled={syncMutation.isPending}>
                <Activity className="h-4 w-4" />
                {syncMutation.isPending ? 'Sincronizando...' : 'Disparar sync'}
              </Button>
            </form>

            {syncMutation.isError && (
              <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                {toApiError(syncMutation.error).message}
              </div>
            )}

            {syncMutation.isSuccess && (
              <div className="mt-3 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                Sync concluido em {syncMutation.data.duration_seconds.toFixed(2)}s.
              </div>
            )}
          </Card>

          <Card className="lg:col-span-3">
            <CardTitle>Logs recentes</CardTitle>
            <CardDescription className="mt-2">
              Historico das sincronizacoes registradas no backend.
            </CardDescription>

            <div className="mt-4 space-y-2">
              <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                Buscar nos logs
              </label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-2 top-2.5 h-4 w-4 text-slate-500" />
                <Input
                  className="pl-8"
                  placeholder="Filtrar por entidade, curso, status..."
                  value={logSearchText}
                  onChange={(event) => {
                    setLogSearchText(event.target.value)
                    setVisibleLogsCount(10)
                  }}
                />
              </div>
            </div>

            {logsQuery.isLoading && (
              <p className="mt-3 text-xs text-slate-500" role="status" aria-live="polite">
                Carregando logs...
              </p>
            )}

            <div className="mt-4 max-h-[420px] overflow-x-auto overflow-y-auto">
              <table className="min-w-full border-collapse" aria-label="Tabela de logs de sincronizacao">
                <thead className="sticky top-0 z-10">
                  <tr className="border-b border-line bg-amber-100/90">
                    <th className="px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-700">
                      Data/Hora
                    </th>
                    <th className="px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-700">
                      Entidade
                    </th>
                    <th className="px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-700">
                      Curso
                    </th>
                    <th className="px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-700">
                      Processados
                    </th>
                    <th className="px-3 py-2 text-left text-xs uppercase tracking-wide text-slate-700">
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {visibleLogs.map((log) => (
                    <tr key={log.sync_id} className="border-b border-line/70 bg-white">
                      <td className="px-3 py-2 text-sm text-slate-700">
                        {new Date(log.timestamp).toLocaleString('pt-BR')}
                      </td>
                      <td className="px-3 py-2 text-sm font-semibold capitalize text-slate-800">
                        {log.entity}
                      </td>
                      <td className="px-3 py-2 text-sm text-slate-700">{log.course_id}</td>
                      <td className="px-3 py-2 text-sm text-slate-700">{log.records_processed}</td>
                      <td className="px-3 py-2">
                        <Badge tone={mapStatusTone(log.status)}>{log.status}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div ref={loadMoreRef} className="h-4" />
            </div>
          </Card>
        </section>

        <section className="grid gap-4">
          <Card>
            <CardTitle className="flex items-center gap-2">
              <Cloud className="h-5 w-5 text-blue-500" />
              Google Drive → Moodle
            </CardTitle>
            <CardDescription className="mt-2">
              Envie arquivos do Google Drive como recursos de curso no Moodle.
            </CardDescription>

            <div className="mt-4 space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Selecione o curso de destino
                </label>
                <Select
                  value={selectedCourseId ?? ''}
                  onChange={(event) => setSelectedCourseId(Number(event.target.value) || null)}
                >
                  <option value="">Selecione um curso...</option>
                  {sortCourses(coursesQuery.data).map((course) => (
                    <option key={course.id} value={course.id}>
                      {course.id} - {course.fullname ?? course.shortname ?? 'Curso sem nome'}
                    </option>
                  ))}
                </Select>
              </div>

              <Button
                className="w-full"
                variant="accent"
                type="button"
                onClick={() => setIsDriveModalOpen(true)}
                disabled={!selectedCourseId}
              >
                <Cloud className="h-4 w-4" />
                Selecionar arquivos do Drive
              </Button>

              {driveToMoodleMutation.isError && (
                <div className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {toApiError(driveToMoodleMutation.error).message}
                </div>
              )}

              {driveToMoodleMutation.isSuccess && (
                <div className="space-y-2 rounded-md border border-emerald-200 bg-emerald-50 p-3 text-sm text-emerald-800">
                  <p className="font-semibold">✓ Sincronizacao concluida em {driveToMoodleMutation.data.duration_seconds.toFixed(2)}s</p>
                  {driveToMoodleMutation.data.extra.uploaded.length > 0 && (
                    <div>
                      <p className="font-semibold">Enviados com sucesso ({driveToMoodleMutation.data.extra.uploaded.length}):</p>
                      <ul className="ml-4 list-disc text-xs">
                        {driveToMoodleMutation.data.extra.uploaded.map((file) => (
                          <li key={file}>{file}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {driveToMoodleMutation.data.extra.failed.length > 0 && (
                    <div>
                      <p className="font-semibold text-red-700">Falharam ({driveToMoodleMutation.data.extra.failed.length}):</p>
                      <ul className="ml-4 list-disc text-xs text-red-700">
                        {driveToMoodleMutation.data.extra.failed.map((file) => (
                          <li key={file}>{file}</li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </Card>
        </section>

        <footer className="grid gap-3 rounded-lg border border-line bg-panel px-4 py-3 text-xs text-slate-600 md:grid-cols-3">
          <div className="font-semibold">React + Vite + TypeScript</div>
          <div>Axios + TanStack Query + Zustand</div>
          <div>Tailwind + componentes estilo shadcn/ui</div>
        </footer>

        <Card>
          <CardTitle>Campos esperados da planilha de inscricao</CardTitle>
          <CardDescription className="mt-2">
            Ordem oficial recebida para aba de inscricoes no Google Sheets.
          </CardDescription>
          <div className="mt-4 grid gap-2 md:grid-cols-2 lg:grid-cols-3">
            {SHEETS_ENROLLMENT_COLUMNS.map((column) => (
              <div
                key={column}
                className="rounded-md border border-line bg-white px-3 py-2 text-xs text-slate-700"
              >
                {column}
              </div>
            ))}
          </div>
        </Card>

        {isGoogleConfigModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4">
            <div className="w-full max-w-xl rounded-lg border border-line bg-panel p-5 shadow-2xl">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-bold text-ink">Configurar Google Sheets via Apps Script</h2>
                  <p className="text-sm text-slate-600">
                    Modo sem Google Cloud: informe a URL do Web App e o link da planilha.
                  </p>
                </div>
                <Button
                  aria-label="Fechar configuracao do Google Sheets"
                  className="h-9 w-9 rounded-full p-0"
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    if (!googleConfigMutation.isPending) {
                      setIsGoogleConfigModalOpen(false)
                    }
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              {googleSheetsConfigQuery.data?.apps_script.webhook_url && (
                <p className="mt-3 text-xs text-slate-600">
                  Webhook atual: {googleSheetsConfigQuery.data.apps_script.webhook_url}
                </p>
              )}

              <div className="mt-4 space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  URL do Web App (Apps Script)
                </label>
                <Input
                  autoFocus
                  placeholder="https://script.google.com/macros/s/.../exec"
                  value={googleAppsScriptUrl}
                  onChange={(event) => setGoogleAppsScriptUrl(event.target.value)}
                />
              </div>

              <div className="mt-3 space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Token do webhook (opcional)
                </label>
                <div className="flex gap-2">
                  <Input
                    placeholder="Deixe vazio se nao configurou token no Apps Script"
                    type={googleAppsScriptTokenVisible ? 'text' : 'password'}
                    value={googleAppsScriptToken}
                    onChange={(event) => setGoogleAppsScriptToken(event.target.value)}
                  />
                  <Button
                    aria-label={googleAppsScriptTokenVisible ? 'Ocultar token' : 'Mostrar token'}
                    type="button"
                    variant="ghost"
                    onClick={() => setGoogleAppsScriptTokenVisible((prev) => !prev)}
                  >
                    {googleAppsScriptTokenVisible ? (
                      <EyeOff className="h-4 w-4" />
                    ) : (
                      <Eye className="h-4 w-4" />
                    )}
                  </Button>
                </div>
              </div>

              <div className="mt-3 space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Planilha Google (URL completa)
                </label>
                <Input
                  placeholder="https://docs.google.com/spreadsheets/d/.../edit"
                  value={googleSpreadsheetInput}
                  onChange={(event) => setGoogleSpreadsheetInput(event.target.value)}
                />
              </div>

              {googleConfigMutation.isError && (
                <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {toApiError(googleConfigMutation.error).message}
                </div>
              )}

              <div className="mt-4 flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setIsGoogleConfigModalOpen(false)}
                  disabled={googleConfigMutation.isPending}
                >
                  Cancelar
                </Button>
                <Button
                  type="button"
                  disabled={
                    googleConfigMutation.isPending ||
                    googleAppsScriptUrl.trim().length < 20 ||
                    googleSpreadsheetInput.trim().length < 10
                  }
                  onClick={() => googleConfigMutation.mutate()}
                >
                  {googleConfigMutation.isPending ? 'Salvando...' : 'Salvar Configuracao'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {isTokenModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4">
            <div className="w-full max-w-lg rounded-lg border border-line bg-panel p-5 shadow-2xl">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-bold text-ink">Configurar Token Moodle</h2>
                  <p className="text-sm text-slate-600">
                    Informe a chave de Web Service do administrador e valide a conexao.
                  </p>
                </div>
                <Button
                  aria-label="Fechar configuracao de token"
                  className="h-9 w-9 rounded-full p-0"
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    if (!tokenMutation.isPending) {
                      setIsTokenModalOpen(false)
                    }
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              <div className="mt-4 space-y-2">
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                  Token Moodle
                </label>
                <div className="flex gap-2">
                  <Input
                    autoFocus
                    placeholder="Cole aqui o token de Web Service"
                    type={tokenVisible ? 'text' : 'password'}
                    value={tokenInput}
                    onChange={(event) => setTokenInput(event.target.value)}
                  />
                  <Button
                    aria-label={tokenVisible ? 'Ocultar token' : 'Mostrar token'}
                    type="button"
                    variant="ghost"
                    onClick={() => setTokenVisible((prev) => !prev)}
                  >
                    {tokenVisible ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </Button>
                </div>
              </div>

              {tokenMutation.isError && (
                <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {toApiError(tokenMutation.error).message}
                </div>
              )}

              <div className="mt-4 flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setIsTokenModalOpen(false)}
                  disabled={tokenMutation.isPending}
                >
                  Cancelar
                </Button>
                <Button
                  type="button"
                  disabled={tokenMutation.isPending || tokenInput.trim().length < 8}
                  onClick={() => tokenMutation.mutate(tokenInput.trim())}
                >
                  {tokenMutation.isPending ? 'Testando...' : 'Testar Conexao'}
                </Button>
              </div>
            </div>
          </div>
        )}

        {isDriveModalOpen && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/45 px-4">
            <div className="w-full max-w-lg rounded-lg border border-line bg-panel p-5 shadow-2xl">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-lg font-bold text-ink">Google Drive → Moodle</h2>
                  <p className="text-sm text-slate-600">
                    Cole o ID da pasta ou IDs dos arquivos do Google Drive.
                  </p>
                </div>
                <Button
                  aria-label="Fechar selecao do Google Drive"
                  className="h-9 w-9 rounded-full p-0"
                  type="button"
                  variant="ghost"
                  onClick={() => {
                    if (!driveToMoodleMutation.isPending) {
                      setIsDriveModalOpen(false)
                    }
                  }}
                >
                  <X className="h-4 w-4" />
                </Button>
              </div>

              <div className="mt-4 space-y-3">
                <div className="space-y-1">
                  <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                    ID da pasta do Drive (OU file IDs abaixo)
                  </label>
                  <Input
                    placeholder="Ex: 1A2B3C4D5E6F7G8H9I0J..."
                    value={driveFolderId}
                    onChange={(event) => setDriveFolderId(event.target.value)}
                  />
                  <p className="text-xs text-slate-500">
                    Encontre o ID na URL: docs.google.com/drive/folders/<span className="font-mono">ID_AQUI</span>
                  </p>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                    IDs dos arquivos (separados por virgula)
                  </label>
                  <Input
                    placeholder="Ex: file1,file2,file3"
                    value={driveFileIds}
                    onChange={(event) => setDriveFileIds(event.target.value)}
                  />
                  <p className="text-xs text-slate-500">
                    Alternativa ao ID da pasta. Encontre em: drive.google.com/file/d/<span className="font-mono">ID_AQUI</span>/view
                  </p>
                </div>

                <div className="space-y-1">
                  <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
                    Número da seção do curso
                  </label>
                  <Input
                    type="number"
                    min="0"
                    placeholder="0"
                    value={driveSectionNumber}
                    onChange={(event) => setDriveSectionNumber(Number(event.target.value) || 0)}
                  />
                  <p className="text-xs text-slate-500">
                    Seção do Moodle onde adicionar os recursos (0 = seção geral)
                  </p>
                </div>
              </div>

              {driveToMoodleMutation.isError && (
                <div className="mt-3 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  {toApiError(driveToMoodleMutation.error).message}
                </div>
              )}

              <div className="mt-4 flex items-center justify-end gap-2">
                <Button
                  type="button"
                  variant="ghost"
                  onClick={() => setIsDriveModalOpen(false)}
                  disabled={driveToMoodleMutation.isPending}
                >
                  Cancelar
                </Button>
                <Button
                  type="button"
                  disabled={
                    driveToMoodleMutation.isPending ||
                    (!driveFolderId.trim() && !driveFileIds.trim())
                  }
                  onClick={() => {
                    driveToMoodleMutation.mutate({
                      folder_id: driveFolderId.trim() || undefined,
                      file_ids: driveFileIds
                        .trim()
                        .split(',')
                        .map((id) => id.trim())
                        .filter((id) => id.length > 0) || undefined,
                      section_number: driveSectionNumber,
                    })
                    setIsDriveModalOpen(false)
                  }}
                >
                  {driveToMoodleMutation.isPending ? 'Enviando...' : 'Enviar para Moodle'}
                </Button>
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
