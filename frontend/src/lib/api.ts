import type { Issue, JobRun, Match, MetricsResponse, Paginated, Prediction, SeasonRow, Standings, Status, Team, TeamStats } from './types'

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
}
