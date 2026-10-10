import type { ReactNode } from 'react'

/** Piezas compartidas por las pantallas de la quiniela y de la cuenta. */
export const input = 'w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900'
export const primary = 'rounded-lg bg-brand-700 px-4 py-2 text-sm font-medium text-white hover:bg-brand-600 disabled:opacity-50'

export function Alert({ children }: { children: ReactNode }) {
  return <p role="alert" className="rounded-lg bg-red-50 p-2 text-sm text-red-800 dark:bg-red-950 dark:text-red-200">{children}</p>
}
export function Ok({ children }: { children: ReactNode }) {
  return <p className="rounded-lg bg-emerald-50 p-2 text-sm text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">{children}</p>
}
