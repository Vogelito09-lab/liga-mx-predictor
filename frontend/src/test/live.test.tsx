import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { MatchCard } from '../components/MatchCard'
import { api } from '../lib/api'
import { LiveProvider } from '../lib/live'
import type { Match, Status } from '../lib/types'

const baseStatus: Status = {
  data_version: 1, server_time: '2026-10-10T00:00:00Z', last_sync_success: '2026-10-10T00:00:00Z', last_sync_attempt: null,
  last_sync_error: null, is_stale: false, source: 'ESPN', live_matches: 0, next_kickoff: null, active_model: null,
  model_trained_at: null, model_data_cutoff: null, matches_total: 1, first_match: null, last_finished_match: null,
  refresh_hint_seconds: 60, message: null,
}
const team = (id: number, name: string) => ({ id, name, abbreviation: name.slice(0, 3), logo_url: null })
const match = (over: Partial<Match>): Match => ({
  id: 1, espn_id: 'm1', season: '2026-27', tournament: 'Apertura 2026', stage: 'regular', stage_detail: null, round: 12,
  kickoff_utc: '2026-10-11T02:00:00Z', status: 'scheduled', status_detail: null, live_clock: null,
  home: team(1, 'Equipo Local'), away: team(2, 'Equipo Visitante'), home_goals: null, away_goals: null,
  home_goals_final: null, away_goals_final: null, home_penalties: null, away_penalties: null, extra_time: false,
  updated_at: '2026-10-10T00:00:00Z', prediction: null, prediction_hit: null, ...over,
})

function Upcoming() {
  const q = useQuery({ queryKey: ['upcoming'], queryFn: () => api.upcoming() })
  return <>{q.data?.map((m) => <MatchCard key={m.id} m={m} />)}</>
}

afterEach(() => vi.restoreAllMocks())

describe('actualización automática sin recargar', () => {
  it('muestra el marcador confirmado cuando el backend anuncia una nueva versión de datos', async () => {
    let version = 1
    let current = match({})
    vi.spyOn(api, 'status').mockImplementation(async () => ({ ...baseStatus, data_version: version }))
    vi.spyOn(api, 'upcoming').mockImplementation(async () => [current])
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <LiveProvider intervalOverrideMs={50}>
          <MemoryRouter><Upcoming /></MemoryRouter>
        </LiveProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Equipo Local')).toBeInTheDocument()
    expect(screen.queryByTestId('score')).toBeNull()

    // El backend confirma que el partido está en juego (nueva versión de datos)
    current = match({ status: 'in_progress', live_clock: "55'", home_goals_final: 1, away_goals_final: 0 })
    version = 2
    await waitFor(() => expect(screen.getByTestId('score')).toHaveTextContent('1 – 0'), { timeout: 2000 })

    // ...y luego que terminó
    current = match({ status: 'finished', home_goals: 2, away_goals: 1, home_goals_final: 2, away_goals_final: 1 })
    version = 3
    await waitFor(() => expect(screen.getByTestId('score')).toHaveTextContent('2 – 1'), { timeout: 2000 })
    expect(screen.getByText('Final')).toBeInTheDocument()
  })

  it('sin cambio de versión no vuelve a pedir los partidos', async () => {
    vi.spyOn(api, 'status').mockResolvedValue(baseStatus)
    const up = vi.spyOn(api, 'upcoming').mockResolvedValue([match({})])
    const qc = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
    render(<QueryClientProvider client={qc}><LiveProvider intervalOverrideMs={30}><MemoryRouter><Upcoming /></MemoryRouter></LiveProvider></QueryClientProvider>)
    await screen.findByText('Equipo Local')
    await new Promise((r) => setTimeout(r, 200))
    expect(up).toHaveBeenCalledTimes(1)
  })
})

describe('MatchCard', () => {
  it('muestra probabilidades, marcador más probable e incertidumbre sin inventar marcador', () => {
    const m = match({
      prediction: {
        id: 9, match_id: 1, generated_at: '2026-10-09T00:00:00Z', data_cutoff: '2026-10-05T00:00:00Z', model_version: 'X-1',
        p_home: 0.5, p_draw: 0.3, p_away: 0.2, most_likely_outcome: 'local', exp_home_goals: 1.6, exp_away_goals: 0.9,
        top_score_home: 1, top_score_away: 0, top_score_prob: 0.12, top_scores: null, uncertainty: 'media', entropy: 0.9,
        factors: [], is_pre_kickoff_final: false,
      },
    })
    render(<QueryClientProvider client={new QueryClient()}><MatchCard m={m} /></QueryClientProvider>)
    expect(screen.getByText('50 %')).toBeInTheDocument()
    expect(screen.getByText('1–0')).toBeInTheDocument()
    expect(screen.getByText('Incertidumbre media')).toBeInTheDocument()
    expect(screen.queryByTestId('score')).toBeNull()
  })
})
