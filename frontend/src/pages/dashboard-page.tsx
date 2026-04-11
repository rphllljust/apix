import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, BookOpenCheck, RefreshCw, Search, Server, ShieldCheck } from 'lucide-react'
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
  fetchCourses,
  fetchCoursesGraphQL,
  fetchHealth,
  fetchSyncLogs,
  fetchSyncLogsGraphQL,
  toApiError,
  triggerCourseSync,
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

function sortCourses(courses: CourseItem[] | undefined): CourseItem[] {
  return [...(courses ?? [])].sort((a, b) =>
    (a.fullname ?? a.shortname ?? '').localeCompare(b.fullname ?? b.shortname ?? ''),
  )
}

export default function DashboardPage(): ReactElement {
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

  const syncMutation = useMutation({
    mutationFn: ({ courseId, mode }: SyncFormOutput) => triggerCourseSync(courseId, mode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['sync-logs'] })
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

  const onSubmit = handleSubmit((values: SyncFormOutput) => {
    setSelectedCourseId(values.courseId)
    setSyncMode(values.mode)
    syncMutation.mutate(values)
  })

  return (
    <div className="relative min-h-screen overflow-x-hidden bg-bg text-ink">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_10%_15%,rgba(15,118,110,.22),transparent_40%),radial-gradient(circle_at_90%_5%,rgba(194,65,12,.18),transparent_32%),radial-gradient(circle_at_50%_95%,rgba(15,118,110,.17),transparent_40%)]" />
      <main className="relative mx-auto flex w-full max-w-7xl flex-col gap-6 px-4 py-8 md:px-10">
        <header className="flex flex-col gap-3">
          <p className="w-fit rounded-full border border-line bg-panel px-3 py-1 font-mono text-xs uppercase tracking-[0.16em] text-slate-700">
            Middleware AVA IDEP
          </p>
          <h1 className="text-3xl font-bold leading-tight md:text-5xl">
            Painel de Integracao Moodle ↔ Google Sheets
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
                  <strong>{import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'}</strong>
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
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Moodle</p>
                <p className="mt-1 text-sm font-semibold">{healthQuery.data?.moodle?.site_name ?? '—'}</p>
                <p className="text-xs text-slate-500">
                  Usuario tecnico: {healthQuery.data?.moodle?.username ?? '—'}
                </p>
              </div>
              <div className="rounded-md border border-line bg-white p-3">
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Google Sheets
                </p>
                <p className="mt-1 text-sm font-semibold">
                  {healthQuery.data?.sheets_ok ? 'Conectado' : 'Indisponivel'}
                </p>
                <p className="text-xs text-slate-500">
                  Ultimo status: {healthQuery.isSuccess ? 'OK' : 'Pendente'}
                </p>
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
                  <option value="enrollments">Matriculas</option>
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
      </main>
    </div>
  )
}
