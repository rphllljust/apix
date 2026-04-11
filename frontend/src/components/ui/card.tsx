import type { HTMLAttributes, ReactElement } from 'react'
import { cn } from '@/lib/utils'

export function Card({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>): ReactElement {
  return (
    <div
      className={cn(
        'rounded-lg border border-line bg-panel p-5 shadow-paper backdrop-blur-sm',
        className,
      )}
      {...props}
    />
  )
}

export function CardTitle({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement>): ReactElement {
  return <h3 className={cn('text-lg font-bold text-ink', className)} {...props} />
}

export function CardDescription({
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement>): ReactElement {
  return <p className={cn('text-sm text-slate-700', className)} {...props} />
}
