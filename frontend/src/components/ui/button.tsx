import { cva, type VariantProps } from 'class-variance-authority'
import type { ButtonHTMLAttributes, ReactElement } from 'react'
import { cn } from '@/lib/utils'

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 rounded-md px-4 py-2 text-sm font-semibold transition focus-visible:outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        primary: 'bg-brand text-white hover:bg-teal-700 focus-visible:ring-teal-500',
        accent: 'bg-accent text-white hover:bg-orange-700 focus-visible:ring-orange-500',
        ghost:
          'border border-line bg-panel text-ink hover:bg-amber-50 focus-visible:ring-slate-400',
      },
    },
    defaultVariants: {
      variant: 'primary',
    },
  },
)

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> &
  VariantProps<typeof buttonVariants>

export function Button({ className, variant, ...props }: ButtonProps): ReactElement {
  return <button className={cn(buttonVariants({ variant }), className)} {...props} />
}
