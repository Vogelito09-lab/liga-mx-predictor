import { useState } from 'react'
import type { Team } from '../lib/types'

/** Escudo servido por ESPN; si no carga, se muestran las iniciales. */
export function TeamLogo({ team, size = 32 }: { team: Team; size?: number }) {
  const [failed, setFailed] = useState(false)
  if (!team.logo_url || failed) {
    return (
      <span style={{ width: size, height: size }} aria-hidden
        className="inline-flex shrink-0 items-center justify-center rounded-full bg-slate-200 text-[10px] font-bold text-slate-600 dark:bg-slate-700 dark:text-slate-200">
        {(team.abbreviation ?? team.name).slice(0, 3)}
      </span>
    )
  }
  return <img src={team.logo_url} alt="" width={size} height={size} loading="lazy" onError={() => setFailed(true)} className="shrink-0 object-contain" />
}
