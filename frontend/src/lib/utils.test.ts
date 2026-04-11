import { describe, expect, it } from 'vitest'
import { cn } from '@/lib/utils'

describe('cn', () => {
  it('une classes e remove duplicidade utilitaria', () => {
    const value = cn('p-2', 'text-sm', undefined, 'p-4')
    expect(value).toContain('text-sm')
    expect(value).toContain('p-4')
    expect(value).not.toContain('p-2')
  })
})
