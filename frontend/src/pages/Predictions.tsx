import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { MatchCard } from '../components/MatchCard'
import { Empty, ErrorBox, Loading, SectionTitle, Select } from '../components/ui'
import { api } from '../lib/api'
import type { Match } from '../lib/types'

export function Predictions() {
  const [days, setDays] = useState('14')
  const q = useQuery({ queryKey: ['upcoming', Number(days)], queryFn: () => api.upcoming(Number(days)) })
  const groups = new Map<string, Match[]>()
  for (const m of q.data ?? []) {
    const key = m.stage === 'regular' ? `${m.tournament} · Jornada ${m.round ?? '—'}` : `${m.tournament} · ${m.stage_detail ?? m.stage}`
    groups.set(key, [...(groups.get(key) ?? []), m])
  }
  return (
    <div className="space-y-6">
      <SectionTitle right={<Select label="Horizonte" value={days} onChange={setDays}
        options={[{ value: '7', label: '7 días' }, { value: '14', label: '14 días' }, { value: '30', label: '30 días' }]} />}>
        Predicciones de la jornada
      </SectionTitle>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Probabilidades de victoria local, empate y victoria visitante al minuto 90. El <b>marcador más probable</b> es el de mayor
        probabilidad conjunta en la distribución de goles del modelo; los <b>goles esperados</b> son el promedio de esa distribución.
        Pueden no coincidir con el resultado más probable: es normal en fútbol.
      </p>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && q.data.length === 0 && <Empty>No hay partidos programados en este periodo según la fuente.</Empty>}
      {[...groups.entries()].map(([k, ms]) => (
        <section key={k}>
          <h3 className="mb-2 text-sm font-semibold text-slate-500">{k}</h3>
          <div className="grid gap-3 md:grid-cols-2">{ms.map((m) => <MatchCard key={m.id} m={m} />)}</div>
        </section>
      ))}
    </div>
  )
}
