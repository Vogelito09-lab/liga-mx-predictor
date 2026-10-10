import type { AdminUsers, AuthConfig, AuthResult, AuthUser, Issue, JobRun, Match, MetricsResponse, MessageResult, Paginated, Prediction, QJornadaDetail, QJornadas, QTables, SeasonRow, Standings, Status, Team, TeamStats } from './types'

// En producción VITE_API_URL apunta al backend (p. ej. https://ligamx-api.onrender.com).
const BASE = (import.meta.env.VITE_API_URL ?? '').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, init)
  if (!res.ok) {
    let detail = res.statusText
    try { detail = (await res.json()).detail ?? detail } catch { /* sin cuerpo JSON */ }
    // Los errores de validación de FastAPI llegan como lista; se muestra el primero.
    if (Array.isArray(detail)) detail = detail[0]?.msg ?? 'Datos no válidos'
    throw new ApiError(res.status, typeof detail === 'string' ? detail : JSON.stringify(detail))
  }
  return res.json() as Promise<T>
}

function qs(params: Record<string, string | number | undefined | null>) {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  const s = q.toString()
  return s ? `?${s}` : ''
}

const admin = (token: string) => ({ headers: { Authorization: `Bearer ${token}` } })
const bearer = (token: string | null): Record<string, string> => (token ? { Authorization: `Bearer ${token}` } : {})
const send = (method: string, body: unknown, token: string | null = null): RequestInit =>
  ({ method, headers: { 'Content-Type': 'application/json', ...bearer(token) }, body: JSON.stringify(body) })

export const api = {
  status: () => request<Status>('/api/updates/status'),
  upcoming: (days = 14) => request<Match[]>(`/api/fixtures/upcoming${qs({ days })}`),
  matches: (p: Record<string, string | number | undefined>) => request<Paginated>(`/api/matches${qs(p)}`),
  predictions: (matchId: number) => request<Prediction[]>(`/api/predictions${qs({ match_id: matchId })}`),
  seasons: () => request<SeasonRow[]>('/api/seasons'),
  teams: (tournament?: string) => request<Team[]>(`/api/teams${qs({ tournament })}`),
  teamStats: (id: number) => request<TeamStats>(`/api/teams/${id}/statistics`),
  standings: (tournament?: string) => request<Standings>(`/api/standings${qs({ tournament })}`),
  metrics: () => request<MetricsResponse>('/api/model/metrics'),
  adminJobs: (t: string) => request<JobRun[]>('/api/admin/jobs', admin(t)),
  adminIssues: (t: string) => request<{ open_counts: Record<string, number>; items: Issue[] }>('/api/admin/issues', admin(t)),
  adminResolve: (t: string, id: number) => request(`/api/admin/issues/${id}/resolve`, { method: 'POST', ...admin(t) }),
  adminAction: (t: string, action: 'update-data' | 'retrain' | 'backtest') =>
    request<{ started: string; message: string }>(`/api/admin/${action}`, { method: 'POST', ...admin(t) }),
  adminUsers: (t: string) => request<AdminUsers>('/api/admin/quiniela/users', admin(t)),
  adminUserAction: (t: string, id: number, action: 'verify' | 'delete') =>
    request(`/api/admin/quiniela/users/${id}/${action}`, { method: 'POST', ...admin(t) }),
  adminUserLink: (t: string, id: number) =>
    request<{ link: string; expires_hours: number }>(`/api/admin/quiniela/users/${id}/link`, { method: 'POST', ...admin(t) }),
}

/** Cuentas y quiniela. `token` es el de la sesión del usuario (no el de administración). */
export const quiniela = {
  config: () => request<AuthConfig>('/api/auth/config'),
  register: (email: string, password: string, invite_code: string) =>
    request<MessageResult>('/api/auth/register', send('POST', { email, password, invite_code })),
  resendVerification: (email: string) => request<MessageResult>('/api/auth/resend-verification', send('POST', { email })),
  verify: (token: string) => request<AuthResult>('/api/auth/verify', send('POST', { token })),
  login: (email: string, password: string) => request<AuthResult>('/api/auth/login', send('POST', { email, password })),
  logout: (token: string) => request('/api/auth/logout', { method: 'POST', headers: bearer(token) }),
  me: (token: string) => request<AuthUser>('/api/auth/me', { headers: bearer(token) }),
  setName: (token: string, display_name: string) => request<AuthUser>('/api/auth/me', send('PUT', { display_name }, token)),
  changePassword: (token: string, current_password: string, new_password: string) =>
    request('/api/auth/change-password', send('POST', { current_password, new_password }, token)),
  forgotPassword: (email: string) => request<MessageResult>('/api/auth/forgot-password', send('POST', { email })),
  resetPassword: (token: string, password: string) =>
    request<AuthResult>('/api/auth/reset-password', send('POST', { token, password })),
  jornadas: (token: string | null, tournament?: string) =>
    request<QJornadas>(`/api/quiniela/jornadas${qs({ tournament })}`, { headers: bearer(token) }),
  jornada: (token: string | null, key: string, tournament?: string) =>
    request<QJornadaDetail>(`/api/quiniela/jornadas/${encodeURIComponent(key)}${qs({ tournament })}`, { headers: bearer(token) }),
  savePicks: (token: string, picks: { match_id: number; home_goals: number; away_goals: number }[]) =>
    request<{ saved: number[]; rejected: { match_id: number; reason: string }[] }>('/api/quiniela/picks', send('PUT', { picks }, token)),
  tables: (tournament?: string) => request<QTables>(`/api/quiniela/tablas${qs({ tournament })}`),
}
