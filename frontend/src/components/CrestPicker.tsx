import { useQuery } from '@tanstack/react-query'
import { quiniela } from '../lib/api'
import { Avatar } from './Avatar'
import { Loading } from './ui'

/** Cuadrícula con los escudos de los equipos de la Liga MX actual. Varios participantes pueden tener el mismo. */
export function CrestPicker({ value, onChange, disabled = false }: { value: number | null; onChange: (teamId: number | null) => void; disabled?: boolean }) {
  const crests = useQuery({ queryKey: ['crests'], queryFn: quiniela.crests, staleTime: 60 * 60_000 })
  if (crests.isLoading) return <Loading label="Cargando escudos…" />
  if (!crests.data?.length) return null
  const btn = (selected: boolean) =>
    `flex flex-col items-center gap-1 rounded-lg border p-1.5 text-[10px] leading-tight disabled:opacity-50 ${selected
      ? 'border-brand-700 bg-brand-50 ring-2 ring-brand-700 dark:bg-brand-700/20' : 'border-slate-200 hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-800'}`
  return (
    <div className="grid grid-cols-4 gap-1.5 sm:grid-cols-6" role="radiogroup" aria-label="Escudo">
      <button type="button" role="radio" aria-checked={value === null} disabled={disabled} onClick={() => onChange(null)} className={btn(value === null)}>
        <Avatar name="?" crestUrl={null} size={32} /><span className="text-center">Sin escudo</span>
      </button>
      {crests.data.map((c) => (
        <button key={c.team_id} type="button" role="radio" aria-checked={value === c.team_id} disabled={disabled} title={c.name}
          onClick={() => onChange(c.team_id)} className={btn(value === c.team_id)}>
          <Avatar name={c.name} crestUrl={c.logo_url} size={32} /><span className="line-clamp-2 text-center">{c.name}</span>
        </button>
      ))}
    </div>
  )
}
