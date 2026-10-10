import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { MatchCard } from '../components/MatchCard'
import { Empty, ErrorBox, Loading, SectionTitle, Stat } from '../components/ui'
import { api } from '../lib/api'
import { fmtDate, fmtDateTime, MODEL_LABEL, relative } from '../lib/format'
import { useLive } from '../lib/live'

export function Home() {
  const { status } = useLive()
  const up = useQuery({ queryKey: ['upcoming', 14], queryFn: () => api.upcoming(14) })
  const live = up.data?.filter((m) => m.status === 'in_progress') ?? []
  const recent = up.data?.filter((m) => m.status === 'finished') ?? []
  const pending = up.data?.filter((m) => m.status !== 'in_progress' && m.status !== 'finished') ?? []
  const nextRound = pending[0] ? pending.filter((m) => m.tournament === pending[0].tournament && m.round === pending[0].round) : []
  return (
    <div className="space-y-8">
      <section className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Próximo partido" value={status?.next_kickoff ? fmtDateTime(status.next_kickoff) : '—'} hint={pending[0] ? `${pending[0].tournament} · Jornada ${pending[0].round ?? '—'}` : undefined} />
        <Stat label="Partidos pendientes (14 días)" value={pending.length} hint={`${pending.filter((m) => m.prediction).length} con predicción`} />
        <Stat label="Modelo activo" value={<span className="text-base">{status?.active_model ? (MODEL_LABEL[status.active_model.split('-')[0]] ?? status.active_model) : 'Sin entrenar'}</span>}
          hint={status?.model_trained_at ? `Entrenado ${relative(status.model_trained_at)} · datos hasta ${fmtDate(status.model_data_cutoff)}` : 'Ejecuta el backtesting para entrenarlo'} />
        <Stat label="Partidos en la base" value={status?.matches_total ?? '—'} hint={status?.first_match ? `Desde ${fmtDate(status.first_match)}` : undefined} />
      </section>

      {up.isLoading && <Loading />}
      {up.error && <ErrorBox error={up.error} />}

      {live.length > 0 && (
        <section>
          <SectionTitle>En juego</SectionTitle>
          <div className="grid gap-3 md:grid-cols-2">{live.map((m) => <MatchCard key={m.id} m={m} />)}</div>
        </section>
      )}

      {recent.length > 0 && (
        <section>
          <SectionTitle>Resultados recientes</SectionTitle>
          <div className="grid gap-3 md:grid-cols-2">{recent.map((m) => <MatchCard key={m.id} m={m} />)}</div>
        </section>
      )}

      <section>
        <SectionTitle right={<Link to="/predicciones" className="text-sm text-brand-700 hover:underline dark:text-brand-500">Ver todas →</Link>}>
          {nextRound[0] ? `Próxima jornada · ${nextRound[0].tournament} · Jornada ${nextRound[0].round ?? '—'}` : 'Próxima jornada'}
        </SectionTitle>
        {up.data && nextRound.length === 0 && <Empty>No hay partidos programados en los próximos 14 días según la fuente.</Empty>}
        <div className="grid gap-3 md:grid-cols-2">{nextRound.map((m) => <MatchCard key={m.id} m={m} />)}</div>
      </section>
    </div>
  )
}
