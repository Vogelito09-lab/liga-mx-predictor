import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../lib/api'
import { fmtDate, fmtDateTime, num, pct, STATUS_LABEL } from '../lib/format'
import type { Match } from '../lib/types'
import { ProbBar } from './ProbBar'
import { TeamLogo } from './TeamLogo'
import { Badge, Card } from './ui'

const UNC_TONE = { baja: 'green', media: 'amber', alta: 'red' } as const
const OUTCOME_LABEL = { local: 'Victoria local', empate: 'Empate', visitante: 'Victoria visitante' }

export function StatusBadge({ m }: { m: Pick<Match, 'status' | 'live_clock' | 'extra_time'> }) {
  if (m.status === 'in_progress') return <Badge tone="live"><span className="size-1.5 animate-pulse rounded-full bg-white" />En juego {m.live_clock ?? ''}</Badge>
  if (m.status === 'finished') return <Badge tone="slate">Final{m.extra_time ? ' (tras prórroga)' : ''}</Badge>
  if (m.status === 'scheduled') return <Badge tone="blue">{STATUS_LABEL[m.status]}</Badge>
  return <Badge tone="amber">{STATUS_LABEL[m.status] ?? m.status}</Badge>
}

export function MatchCard({ m }: { m: Match }) {
  const [open, setOpen] = useState(false)
  const p = m.prediction
  const showScore = m.status === 'in_progress' || m.status === 'finished'
  return (
    <Card className="flex flex-col gap-3" >
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>{m.tournament} · {m.stage === 'regular' ? `Jornada ${m.round ?? '—'}` : (m.stage_detail ?? m.stage)}</span>
        <span className="flex items-center gap-2">{fmtDateTime(m.kickoff_utc)} <StatusBadge m={m} /></span>
      </div>

      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3" data-testid={`match-${m.espn_id}`}>
        <div className="flex min-w-0 items-center gap-2">
          <TeamLogo team={m.home} />
          <span className="truncate font-medium">{m.home.name}</span>
        </div>
        <div className="text-center tabular-nums">
          {showScore ? (
            <div data-testid="score" className={`text-2xl font-bold ${m.status === 'in_progress' ? 'text-red-600' : ''}`}>
              {m.home_goals_final} – {m.away_goals_final}
            </div>
          ) : <div className="text-sm text-slate-400">vs</div>}
          {m.extra_time && m.home_goals !== null && <div className="text-[11px] text-slate-500">90': {m.home_goals}–{m.away_goals}</div>}
          {m.home_penalties !== null && m.away_penalties !== null && <div className="text-[11px] text-slate-500">Penales {m.home_penalties}–{m.away_penalties}</div>}
        </div>
        <div className="flex min-w-0 items-center justify-end gap-2">
          <span className="truncate text-right font-medium">{m.away.name}</span>
          <TeamLogo team={m.away} />
        </div>
      </div>

      {p ? (
        <div className="space-y-2">
          <ProbBar home={p.p_home} draw={p.p_draw} away={p.p_away} />
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
            <span>Más probable: <b>{OUTCOME_LABEL[p.most_likely_outcome]}</b></span>
            <span>Marcador más probable: <b className="tabular-nums">{p.top_score_home}–{p.top_score_away}</b> ({pct(p.top_score_prob)})</span>
            <span>Goles esperados: <b className="tabular-nums">{num(p.exp_home_goals)} – {num(p.exp_away_goals)}</b></span>
            <Badge tone={UNC_TONE[p.uncertainty]}>Incertidumbre {p.uncertainty}</Badge>
            {m.prediction_hit !== null && (m.prediction_hit ? <Badge tone="green">Acertó</Badge> : <Badge tone="red">Falló</Badge>)}
          </div>
          <button onClick={() => setOpen((o) => !o)} className="text-xs font-medium text-brand-700 hover:underline dark:text-brand-500">
            {open ? 'Ocultar detalles' : 'Ver factores e historial'}
          </button>
          {open && <PredictionDetails m={m} />}
        </div>
      ) : (
        <p className="text-xs text-slate-500">{m.status === 'scheduled' ? 'Aún no hay predicción para este partido.' : 'No se guardó una predicción antes del inicio.'}</p>
      )}
    </Card>
  )
}

function PredictionDetails({ m }: { m: Match }) {
  const p = m.prediction!
  const hist = useQuery({ queryKey: ['predictions', m.id], queryFn: () => api.predictions(m.id) })
  return (
    <div className="space-y-3 rounded-lg bg-slate-50 p-3 text-xs dark:bg-slate-800/50">
      <ul className="list-disc space-y-1 pl-4">{p.factors?.map((f) => <li key={f.key}>{f.text}</li>)}</ul>
      {p.top_scores && (
        <div>
          <div className="mb-1 font-medium">Marcadores más probables</div>
          <div className="flex flex-wrap gap-2">{p.top_scores.map((s) => <Badge key={`${s.home}-${s.away}`}>{s.home}–{s.away} · {pct(s.p, 1)}</Badge>)}</div>
        </div>
      )}
      <div className="text-slate-500">
        Modelo {p.model_version} · Generada {fmtDateTime(p.generated_at)} · Datos hasta {fmtDate(p.data_cutoff)}
      </div>
      {hist.data && hist.data.length > 1 && (
        <div>
          <div className="mb-1 font-medium">Historial de predicciones ({hist.data.length})</div>
          <table className="w-full tabular-nums">
            <thead className="text-slate-500"><tr><th className="text-left">Generada</th><th>L</th><th>E</th><th>V</th><th>Marcador</th></tr></thead>
            <tbody>{hist.data.map((h) => (
              <tr key={h.id} className={h.is_pre_kickoff_final ? 'font-semibold' : ''}>
                <td>{fmtDateTime(h.generated_at)}{h.is_pre_kickoff_final ? ' (última antes del inicio)' : ''}</td>
                <td className="text-center">{pct(h.p_home)}</td><td className="text-center">{pct(h.p_draw)}</td><td className="text-center">{pct(h.p_away)}</td>
                <td className="text-center">{h.top_score_home}–{h.top_score_away}</td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
      <p className="text-slate-500">Las probabilidades expresan incertidumbre; no son resultados garantizados.</p>
    </div>
  )
}
