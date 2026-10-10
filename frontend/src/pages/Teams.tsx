import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { MatchCard } from '../components/MatchCard'
import { TeamLogo } from '../components/TeamLogo'
import { Badge, Card, Empty, ErrorBox, Loading, SectionTitle, Stat } from '../components/ui'
import { api } from '../lib/api'
import { fmtDate, num } from '../lib/format'
import type { Agg, Team } from '../lib/types'

export function Teams() {
  const seasons = useQuery({ queryKey: ['seasons'], queryFn: api.seasons })
  const current = seasons.data?.[0]?.tournament
  const q = useQuery({ queryKey: ['teams', current], queryFn: () => api.teams(current), enabled: !!current })
  return (
    <div className="space-y-4">
      <SectionTitle>Equipos {current ? `· ${current}` : ''}</SectionTitle>
      {(q.isLoading || seasons.isLoading) && <Loading />}
      {(q.error || seasons.error) && <ErrorBox error={q.error ?? seasons.error} />}
      {seasons.data?.length === 0 && <Empty>Aún no hay datos cargados.</Empty>}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4">
        {q.data?.map((t) => (
          <Link key={t.id} to={`/equipos/${t.id}`}>
            <Card className="flex items-center gap-3 hover:border-brand-500"><TeamLogo team={t} size={36} /><span className="font-medium">{t.name}</span></Card>
          </Link>
        ))}
      </div>
    </div>
  )
}

const FORM_TONE = { G: 'green', E: 'slate', P: 'red' } as const

function AggCard({ title, a }: { title: string; a: Agg }) {
  return (
    <Stat label={title} value={a.played ? `${num(a.ppg)} pts/p` : '—'}
      hint={a.played ? `${a.played} PJ · ${a.wins}G ${a.draws}E ${a.losses}P · GF ${num(a.gf_avg)} · GC ${num(a.ga_avg)} por partido` : 'Sin partidos'} />
  )
}

/** Partidos que le faltan al equipo en el torneo en curso, con la predicción del modelo cuando ya existe. */
function PendingMatches({ team }: { team: Team }) {
  const seasons = useQuery({ queryKey: ['seasons'], queryFn: api.seasons })
  const current = seasons.data?.[0]?.tournament
  const ms = useQuery({
    queryKey: ['team-matches', team.id, current],
    queryFn: () => api.matches({ tournament: current, team_id: team.id, stage: 'regular', order: 'asc', limit: 50 }),
    enabled: !!current,
  })
  const rivals = useQuery({ queryKey: ['teams', current], queryFn: () => api.teams(current), enabled: !!current })
  if (seasons.isLoading || ms.isLoading) return <Loading />
  if (ms.error) return <ErrorBox error={ms.error} />
  const all = ms.data?.items ?? []
  const pending = all.filter((m) => m.status !== 'finished' && m.status !== 'canceled')
  const seen = new Set(all.flatMap((m) => [m.home.id, m.away.id]))
  const unscheduled = (rivals.data ?? []).filter((t) => t.id !== team.id && !seen.has(t.id))
  return (
    <section>
      <h3 className="mb-2 text-sm font-semibold">Partidos pendientes · {current} ({pending.length + unscheduled.length})</h3>
      {pending.length === 0 && unscheduled.length === 0 && <Empty>No le quedan partidos de fase regular en este torneo.</Empty>}
      <div className="grid gap-3 md:grid-cols-2">{pending.map((m) => <MatchCard key={m.id} m={m} />)}</div>
      {unscheduled.length > 0 && (
        <Card className="mt-3">
          <div className="text-sm font-medium">Rivales que faltan sin fecha publicada todavía</div>
          <div className="mt-2 flex flex-wrap gap-3">
            {unscheduled.map((t) => <span key={t.id} className="flex items-center gap-1 text-sm"><TeamLogo team={t} size={18} />{t.name}</span>)}
          </div>
          <p className="mt-2 text-xs text-slate-500">ESPN aún no publica la fecha ni quién es local; aparecerán arriba con su predicción en cuanto se publiquen.</p>
        </Card>
      )}
      <p className="mt-2 text-xs text-slate-500">La predicción se genera hasta 30 días antes de cada partido.</p>
    </section>
  )
}

export function TeamDetail() {
  const { id } = useParams()
  const q = useQuery({ queryKey: ['team', id], queryFn: () => api.teamStats(Number(id)) })
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const s = q.data!
  const elo = s.elo_history.map((e) => ({ date: fmtDate(e.date), elo: e.elo }))
  const byT = [...s.by_tournament].reverse().map((t) => ({ torneo: t.tournament, 'GF/p': t.gf_avg, 'GC/p': t.ga_avg, 'Pts/p': t.ppg }))
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <TeamLogo team={s.team} size={48} />
        <div>
          <h2 className="text-2xl font-bold">{s.team.name}</h2>
          <div className="mt-1 flex items-center gap-1 text-xs text-slate-500">Forma (últimos 5):
            {s.form_last5.split('').map((r, i) => <Badge key={i} tone={FORM_TONE[r as 'G' | 'E' | 'P']}>{r}</Badge>)}
            <span className="ml-2">{s.matches_in_database} partidos en la base</span>
          </div>
        </div>
      </div>
      <PendingMatches team={s.team} />
      <div className="grid gap-3 md:grid-cols-3">
        <AggCard title="Últimos 20 partidos" a={s.summary_recent} />
        <AggCard title="Como local (últimos 20)" a={s.home_recent} />
        <AggCard title="Como visitante (últimos 20)" a={s.away_recent} />
      </div>
      <Card>
        <h3 className="mb-2 text-sm font-semibold">Evolución del Elo</h3>
        {elo.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={elo}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="date" minTickGap={40} fontSize={11} />
              <YAxis domain={['auto', 'auto']} fontSize={11} /><Tooltip /><Line type="monotone" dataKey="elo" stroke="#0d9488" dot={false} strokeWidth={2} /></LineChart>
          </ResponsiveContainer>) : <Empty>Sin historial.</Empty>}
      </Card>
      <Card>
        <h3 className="mb-2 text-sm font-semibold">Tendencia por torneo</h3>
        <ResponsiveContainer width="100%" height={260}>
          <BarChart data={byT}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="torneo" fontSize={10} /><YAxis fontSize={11} /><Tooltip /><Legend />
            <Bar dataKey="Pts/p" fill="#0d9488" /><Bar dataKey="GF/p" fill="#6366f1" /><Bar dataKey="GC/p" fill="#f59e0b" /></BarChart>
        </ResponsiveContainer>
      </Card>
      <Card className="overflow-x-auto">
        <h3 className="mb-2 text-sm font-semibold">Últimos partidos</h3>
        <table className="w-full text-sm tabular-nums">
          <tbody>{s.recent.map((r) => (
            <tr key={r.match_id} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1 text-xs text-slate-500">{fmtDate(r.date)}</td><td>{r.home ? 'vs' : '@'} {r.opponent}</td>
              <td className="text-center">{r.gf}–{r.ga}</td><td className="text-right"><Badge tone={FORM_TONE[r.result]}>{r.result}</Badge></td>
            </tr>))}</tbody>
        </table>
      </Card>
    </div>
  )
}
