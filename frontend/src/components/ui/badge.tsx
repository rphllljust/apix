import { cva, type VariantProps } from 'class-variance-authority'
import type { HTMLAttributes, ReactElement } from 'react'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold',
  {
    variants: {
      tone: {
        neutral: 'border-slate-300 bg-slate-100 text-slate-800',
        success: 'border-emerald-300 bg-emerald-100 text-emerald-900',
        warning: 'border-amber-300 bg-amber-100 text-amber-900',
        danger: 'border-red-300 bg-red-100 text-red-900',
      },
    },
    defaultVariants: {
      tone: 'neutral',
    },
  },
)

type BadgeProps = HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>

export function Badge({ className, tone, ...props }: BadgeProps): ReactElement {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}
