import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { useDebounce } from '@/hooks/use-debounce'

describe('useDebounce', () => {
  it('retarda atualizacao do valor', () => {
    vi.useFakeTimers()

    const { result, rerender } = renderHook(
      ({ value, delay }: { value: string; delay: number }) => useDebounce(value, delay),
      {
        initialProps: { value: 'inicio', delay: 300 },
      },
    )

    expect(result.current).toBe('inicio')

    rerender({ value: 'novo', delay: 300 })
    expect(result.current).toBe('inicio')

    act(() => {
      vi.advanceTimersByTime(299)
    })
    expect(result.current).toBe('inicio')

    act(() => {
      vi.advanceTimersByTime(1)
    })
    expect(result.current).toBe('novo')

    vi.useRealTimers()
  })
})

