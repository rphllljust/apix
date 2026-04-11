import type { ReactElement } from 'react'

export function FullscreenLoader(): ReactElement {
  return (
    <main className="flex min-h-screen items-center justify-center bg-bg px-4">
      <section
        className="rounded-lg border border-line bg-panel px-6 py-4 shadow-paper"
        aria-live="polite"
      >
        <p className="text-sm font-semibold text-slate-700">Carregando dashboard...</p>
      </section>
    </main>
  )
}
