const TZ = 'America/Mexico_City'

export const fmtDateTime = (iso: string | null | undefined) =>
  iso ? new Intl.DateTimeFormat('es-MX', { timeZone: TZ, weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' }).format(new Date(iso)) : '—'

export const fmtDate = (iso: string | null | undefined) =>
  iso ? new Intl.DateTimeFormat('es-MX', { timeZone: TZ, day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(iso)) : '—'

export const fmtTime = (iso: string | null | undefined) =>
  iso ? new Intl.DateTimeFormat('es-MX', { timeZone: TZ, hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(new Date(iso)) : '—'

export const pct = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? '—' : `${(x * 100).toFixed(digits)} %`)

export const num = (x: number | null | undefined, digits = 2) => (x === null || x === undefined ? '—' : x.toFixed(digits))

export function relative(iso: string | null | undefined, now = Date.now()) {
  if (!iso) return 'nunca'
  const s = Math.round((now - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'hace unos segundos'
  if (s < 3600) return `hace ${Math.round(s / 60)} min`
  if (s < 86400) return `hace ${Math.round(s / 3600)} h`
  return `hace ${Math.round(s / 86400)} días`
}

export const STATUS_LABEL: Record<string, string> = {
  scheduled: 'Programado', in_progress: 'En juego', finished: 'Finalizado',
  postponed: 'Aplazado', suspended: 'Suspendido', canceled: 'Cancelado',
}

export const MODEL_LABEL: Record<string, string> = {
  A_referencia: 'A · Referencia (frecuencias)', B_elo: 'B · Elo', C_poisson_dc: 'C · Poisson (Dixon-Coles)',
  D_logistica: 'D · Logística multinomial', E_lightgbm: 'E · LightGBM', F_combinado: 'F · Combinado',
}
