import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { TeamLogo } from '../components/TeamLogo'
import { Card, Empty, ErrorBox, Loading, SectionTitle } from '../components/ui'
import { api } from '../lib/api'
import { fmtDateTime, MODEL_LABEL, probLabel } from '../lib/format'

function ProbCell({ p, tone }: { p: number | null; tone: 'green' | 'amber' }) {
  const bar = tone === 'green' ? 'bg-emerald-500/25' : 'bg-amber-500/30'
  return (
    <td className="relative px-2 py-1.5 text-right">
      {p !== null && <span className={`absolute inset-y-1 left-0 rounded-r ${bar}`} style={{ width: `${Math.round(p * 100)}%` }} />}
      <span className="relative font-medium">{probLabel(p)}</span>
    </td>
  )
}

const HEAD = ['#', 'Equipo', 'PJ', 'G', 'E', 'P', 'GF', 'GC', 'DIF', 'PTS']

export function Standings() {
  const q = useQuery({ queryKey: ['standings', 'current'], queryFn: () => api.standings() })
  const d = q.data
  const spots = d?.qualify_spots ?? 8
  const sim = d?.simulation
  return (
    <div className="space-y-4">
      <SectionTitle right={<Link to="/historico" className="text-sm text-brand-700 hover:underline dark:text-brand-500">Tablas de otros torneos →</Link>}>
        Tabla general {d?.tournament ? `· ${d.tournament}` : ''}
      </SectionTitle>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {d && d.rows.length === 0 && <Empty>Aún no hay partidos de este torneo en la base de datos.</Empty>}
      {d && d.rows.length > 0 && (
        <Card className="overflow-x-auto p-0">
          <table className="w-full min-w-[720px] text-sm tabular-nums" data-testid="standings-table">
            <thead className="text-xs text-slate-500">
              <tr>
                {HEAD.map((h) => <th key={h} className={`px-2 py-2 ${h === 'Equipo' ? 'text-left' : 'text-center'}`}>{h}</th>)}
                <th className="px-2 py-2 text-right" title="Probabilidad de terminar entre los 8 primeros">% Clasificar</th>
                <th className="px-2 py-2 text-right" title="Probabilidad de ganar la final">% Campeón</th>
              </tr>
            </thead>
            <tbody>
              {d.rows.map((r) => (
                <tr key={r.team.id}
                  className={`border-t ${r.position === spots + 1 ? 'border-t-2 border-t-slate-400 dark:border-t-slate-500' : 'border-slate-100 dark:border-slate-800'}`}>
                  <td className="px-2 py-1.5 text-center">
                    <span className={`inline-block w-6 rounded ${r.position <= spots ? 'bg-emerald-100 font-semibold text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300' : ''}`}>{r.position}</span>
                  </td>
                  <td className="px-2 py-1.5">
                    <Link to={`/equipos/${r.team.id}`} className="flex items-center gap-2 hover:underline">
                      <TeamLogo team={r.team} size={20} />{r.team.name}
                    </Link>
                  </td>
                  {[r.played, r.wins, r.draws, r.losses, r.gf, r.ga, r.gd > 0 ? `+${r.gd}` : r.gd].map((v, i) =>
                    <td key={i} className="px-2 py-1.5 text-center">{v}</td>)}
                  <td className="px-2 py-1.5 text-center font-bold">{r.points}</td>
                  <ProbCell p={r.p_qualify} tone="green" />
                  <ProbCell p={r.p_champion} tone="amber" />
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}
      {d && d.rows.length > 0 && (
        <div className="space-y-2 text-xs text-slate-600 dark:text-slate-400">
          <p>
            <span className="mr-1 inline-block size-3 rounded bg-emerald-100 align-middle dark:bg-emerald-950" />
            Los {spots} primeros clasifican directo a cuartos de final (sin Play-In). {d.note}
          </p>
          {sim ? (
            <p>
              <b>¿De dónde salen los porcentajes?</b> Se simuló {sim.n_sims.toLocaleString('es-MX')} veces lo que falta del torneo
              ({sim.pending_matches + sim.unscheduled_matches} partidos de fase regular{sim.unscheduled_matches > 0 ? `, ${sim.unscheduled_matches} de ellos aún sin fecha publicada` : ''} y
              la liguilla) con el modelo {MODEL_LABEL[sim.model_version.split('-')[0]] ?? sim.model_version}. <b>% Clasificar</b> es la
              proporción de simulaciones en las que el equipo terminó entre los {spots} primeros; <b>% Campeón</b>, en las que ganó la final.
              Liguilla: 1 vs 8, 2 vs 7, 3 vs 6 y 4 vs 5, semifinales con reacomodo; en cuartos y semifinales el empate global lo gana el mejor
              ubicado y la final se define con tiempos extra y penales. Son estimaciones, no resultados garantizados.
              Calculado {fmtDateTime(sim.computed_at)}; se actualiza solo con cada resultado nuevo.
            </p>
          ) : (
            <p>Las probabilidades aparecen cuando hay un modelo entrenado y el torneo está en curso.</p>
          )}
        </div>
      )}
    </div>
  )
}
