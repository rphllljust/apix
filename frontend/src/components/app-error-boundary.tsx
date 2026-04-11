import { Component, type ErrorInfo, type ReactNode } from 'react'
import { Button } from '@/components/ui/button'

interface AppErrorBoundaryProps {
  children: ReactNode
}

interface AppErrorBoundaryState {
  hasError: boolean
  message: string
}

export class AppErrorBoundary extends Component<AppErrorBoundaryProps, AppErrorBoundaryState> {
  public constructor(props: AppErrorBoundaryProps) {
    super(props)
    this.state = {
      hasError: false,
      message: '',
    }
  }

  public static getDerivedStateFromError(error: Error): AppErrorBoundaryState {
    return {
      hasError: true,
      message: error.message || 'Falha inesperada na interface.',
    }
  }

  public componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error('Falha capturada pelo ErrorBoundary:', error, info)
  }

  public render(): ReactNode {
    if (!this.state.hasError) {
      return this.props.children
    }

    return (
      <main className="flex min-h-screen items-center justify-center bg-bg px-4">
        <section
          className="w-full max-w-lg rounded-lg border border-red-200 bg-red-50 p-6 text-red-900 shadow-paper"
          role="alert"
          aria-live="assertive"
        >
          <h1 className="text-xl font-bold">Falha ao renderizar o dashboard</h1>
          <p className="mt-2 text-sm">{this.state.message}</p>
          <Button
            className="mt-4"
            onClick={() => window.location.reload()}
            variant="accent"
            type="button"
          >
            Recarregar aplicação
          </Button>
        </section>
      </main>
    )
  }
}
