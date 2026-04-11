import type { InputHTMLAttributes, ReactElement } from 'react'
import { cn } from '@/lib/utils'

export function Input({
  className,
  ...props
}: InputHTMLAttributes<HTMLInputElement>): ReactElement {
  return (
    <input
      className={cn(
        'h-10 w-full rounded-md border border-line bg-white px-3 text-sm text-ink shadow-sm',
        'placeholder:text-slate-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand',
        className,
      )}
      {...props}
    />
  )
}
