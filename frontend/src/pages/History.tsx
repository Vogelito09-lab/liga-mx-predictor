import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { StatusBadge } from '../components/MatchCard'
import { ProbBar } from '../components/ProbBar'
import { TeamLogo } from '../components/TeamLogo'
import { Badge, Card, Empty, ErrorBox, Loading, SectionTitle, Select } from '../components/ui'
import { api } from '../lib/api'
import { fmtDateTime, pct } from '../lib/format'

const PAGE = 50

export function History() {
  const seasons = useQuery({ queryKey: ['seasons'], queryFn: api.seasons })
  const [tournament, setTournament] = useState('')
  const [round, setRound] = useState('')
  const [team, setTeam] = useState('')
  const [status, setStatus] = useState('')
  const [page, setPage] = useState(0)
  const [view, setView] = useState<'partidos' | 'tabla'>('partidos')
  useEffect(() => { if (!tournament && seasons.data?.[0]) setTournament(seasons.data[0].tournament) }, [seasons.data, tournament])
  useEffect(() => setPage(0), [tournament, round, team, status])
  const teams = useQuery({ queryKey: ['teams', tournament], queryFn: () => api.teams(tournament || undefined) })
  const params = { tournament, round, team_id: team, status, limit: PAGE, offset: page * PAGE, order: 'asc' }
  const q = useQuery({ queryKey: ['matches', params], queryFn: () => api.matches(params), enabled: view === 'partidos' })
  const table = useQuery({ queryKey: ['standings', tournament], queryFn: () => api.standings(tournament), enabled: view === 'tabla' && !!tournament })
  const tournaments = seasons.data ?? []
  return (
    <div className="space-y-4">
      <SectionTitle right={
        <div className="flex gap-1 text-sm">{(['partidos', 'tabla'] as const).map((v) => (
          <button key={v} onClick={() => setView(v)} className={`rounded-lg px-3 py-1 ${view === v ? 'bg-brand-700 text-white' : 'bg-slate-100 dark:bg-slate-800'}`}>
            {v === 'partidos' ? 'Partidos' : 'Tabla'}
          </button>))}
        </div>}>Calendario e histórico</SectionTitle>
      <Card className="flex flex-wrap gap-3">
        <Select label="Torneo" value={tournament} onChange={setTournament}
          options={[{ value: '', label: 'Todos' }, ...tournaments.map((t) => ({ value: t.tournament, label: `${t.tournament} (${t.season})` }))]} />
        {view === 'partidos' && <>
          <Select label="Jornada" value={round} onChange={setRound}
            options={[{ value: '', label: 'Todas' }, ...Array.from({ length: 19 }, (_, i) => ({ value: String(i + 1), label: `Jornada ${i + 1}` }))]} />
          <Select label="Equipo" value={team} onChange={setTeam}
            options={[{ value: '', label: 'Todos' }, ...(teams.data ?? []).map((t) => ({ value: String(t.id), label: t.name }))]} />
          <Select label="Estado" value={status} onChange={setStatus}
            options={[{ value: '', label: 'Todos' }, { value: 'finished', label: 'Finalizados' }, { value: 'scheduled', label: 'Programados' },
              { value: 'in_progress', label: 'En juego' }, { value: 'postponed', label: 'Aplazados' }]} />
        </>}
      </Card>

      {view === 'tabla' ? (
        table.isLoading ? <Loading /> : table.error ? <ErrorBox error={table.error} /> : table.data && (
          <Card className="overflow-x-auto">
            <table className="w-full text-sm tabular-nums">
              <thead className="text-xs text-slate-500"><tr>{['#', 'Equipo', 'PJ', 'G', 'E', 'P', 'GF', 'GC', 'DIF', 'PTS'].map((h) => <th key={h} className="px-2 py-1 text-left">{h}</th>)}</tr></thead>
              <tbody>{table.data.rows.map((r) => (
                <tr key={r.team.id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="px-2 py-1">{r.position}</td>
                  <td className="px-2 py-1"><span className="flex items-center gap-2"><TeamLogo team={r.team} size={20} />{r.team.name}</span></td>
                  <td className="px-2">{r.played}</td><td className="px-2">{r.wins}</td><td className="px-2">{r.draws}</td><td className="px-2">{r.losses}</td>
                  <td className="px-2">{r.gf}</td><td className="px-2">{r.ga}</td><td className="px-2">{r.gd}</td><td className="px-2 font-bold">{r.points}</td>
                </tr>))}</tbody>
            </table>
            <p className="mt-2 text-xs text-slate-500">{table.data.note}</p>
          </Card>
        )
      ) : (
        <>
          {q.isLoading && <Loading />}
          {q.error && <ErrorBox error={q.error} />}
          {q.data && q.data.total === 0 && <Empty>No hay partidos con estos filtros.</Empty>}
          {q.data && q.data.total > 0 && (
            <Card className="overflow-x-auto p-0">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="bg-slate-50 text-xs text-slate-500 dark:bg-slate-800/50">
                  <tr><th className="px-3 py-2 text-left">Fecha</th><th className="text-left">Partido</th><th>Resultado</th><th className="w-48">Predicción original (L/E/V)</th><th>Marcador pred.</th><th>Acierto</th></tr>
                </thead>
                <tbody>{q.data.items.map((m) => (
                  <tr key={m.id} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">{fmtDateTime(m.kickoff_utc)}<div>{m.stage === 'regular' ? `J${m.round ?? '—'}` : m.stage_detail}</div></td>
                    <td className="py-2"><div className="flex items-center gap-1"><TeamLogo team={m.home} size={18} />{m.home.name}</div><div className="flex items-center gap-1"><TeamLogo team={m.away} size={18} />{m.away.name}</div></td>
                    <td className="text-center tabular-nums">{m.status === 'finished' || m.status === 'in_progress'
                      ? <><b>{m.home_goals_final}–{m.away_goals_final}</b>{m.extra_time && <div className="text-[11px] text-slate-500">90': {m.home_goals ?? '?'}–{m.away_goals ?? '?'}</div>}</>
                      : <StatusBadge m={m} />}</td>
                    <td className="px-2">{m.prediction ? <><ProbBar compact home={m.prediction.p_home} draw={m.prediction.p_draw} away={m.prediction.p_away} />
                      <div className="mt-1 text-center text-[11px] tabular-nums text-slate-500">{pct(m.prediction.p_home)} / {pct(m.prediction.p_draw)} / {pct(m.prediction.p_away)}</div></> : <span className="text-xs text-slate-400">Sin predicción guardada</span>}</td>
                    <td className="text-center tabular-nums">{m.prediction ? `${m.prediction.top_score_home}–${m.prediction.top_score_away}` : '—'}</td>
                    <td className="text-center">{m.prediction_hit === null ? '—' : m.prediction_hit ? <Badge tone="green">Sí</Badge> : <Badge tone="red">No</Badge>}</td>
                  </tr>))}</tbody>
              </table>
              <div className="flex items-center justify-between border-t border-slate-100 p-3 text-xs dark:border-slate-800">
                <span>{q.data.total} partidos · página {page + 1} de {Math.max(1, Math.ceil(q.data.total / PAGE))}</span>
                <span className="flex gap-2">
                  <button disabled={page === 0} onClick={() => setPage((p) => p - 1)} className="rounded border px-2 py-1 disabled:opacity-40">Anterior</button>
                  <button disabled={(page + 1) * PAGE >= q.data.total} onClick={() => setPage((p) => p + 1)} className="rounded border px-2 py-1 disabled:opacity-40">Siguiente</button>
                </span>
              </div>
            </Card>
          )}
          <p className="text-xs text-slate-500">Los partidos históricos anteriores al arranque del sistema no tienen predicción guardada en tiempo real; su evaluación está en «Rendimiento del modelo» (backtesting).</p>
        </>
      )}
    </div>
  )
}
