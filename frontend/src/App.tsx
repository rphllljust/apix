import { lazy, Suspense, type ReactElement } from 'react'
import { AppErrorBoundary } from '@/components/app-error-boundary'
import { FullscreenLoader } from '@/components/fullscreen-loader'

const DashboardPage = lazy(async () => import('@/pages/dashboard-page'))

export default function App(): ReactElement {
  return (
    <AppErrorBoundary>
      <Suspense fallback={<FullscreenLoader />}>
        <DashboardPage />
      </Suspense>
    </AppErrorBoundary>
  )
}
