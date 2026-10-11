import { useQuery } from '@tanstack/react-query'
import { api } from './api'
import type { LiveMatch, Match } from './types'

/**
 * Marcador en vivo compartido por toda la página: una sola consulta a /api/live, sin importar cuántas
 * tarjetas lo usen. Con partido en juego se pregunta cada 30 s (lo indica el servidor); si no, cada 2 min.
 * El servidor solo consulta a ESPN cuando hay partidos por empezar o en juego.
 */
export function useLiveScores() {
  return useQuery({
    queryKey: ['live'],
    queryFn: api.live,
    refetchInterval: (query) => (query.state.data?.poll_seconds ?? 120) * 1000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: 1,
  })
}

/** Dato en vivo de un partido, solo si aporta algo sobre lo que ya tiene la base de datos. */
export function useLiveMatch(m: Pick<Match, 'id' | 'status'>): { lv: LiveMatch | null; stale: boolean } {
  const q = useLiveScores()
  const lv = q.data?.matches.find((x) => x.match_id === m.id) ?? null
  // Cuando la base ya tiene el resultado final, manda la base.
  if (!lv || m.status === 'finished' || lv.state === 'pre') return { lv: null, stale: false }
  return { lv, stale: q.data?.stale ?? false }
}
