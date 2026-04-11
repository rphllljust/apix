import type { ReactElement, SelectHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export function Select({
  className,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement>): ReactElement {
  return (
    <select
      className={cn(
        'h-10 w-full rounded-md border border-line bg-white px-3 text-sm text-ink shadow-sm',
        'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
        className,
      )}
      {...props}
    />
  )
}
