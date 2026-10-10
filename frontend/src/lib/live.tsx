import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useContext, useEffect, useRef, type ReactNode } from 'react'
import { api } from './api'
import type { Status } from './types'

/**
 * Sincronización automática sin recargar la página.
 * Se consulta /api/updates/status cada `refresh_hint_seconds` (30 s con partidos en juego, 60 s si no).
 * Cuando cambia `data_version`, el backend confirmó datos nuevos y se invalidan todas las consultas,
 * de modo que marcadores, tablas y predicciones se vuelven a pedir. La interfaz nunca simula marcadores.
 */
interface LiveCtx { status: Status | undefined; error: Error | null; isFetching: boolean; lastChecked: number | null }
const Ctx = createContext<LiveCtx>({ status: undefined, error: null, isFetching: false, lastChecked: null })

// Solo para pruebas de extremo a extremo: VITE_STATUS_POLL_MS acelera la consulta.
const ENV_POLL = Number(import.meta.env.VITE_STATUS_POLL_MS) || undefined

export function LiveProvider({ children, intervalOverrideMs = ENV_POLL }: { children: ReactNode; intervalOverrideMs?: number }) {
  const qc = useQueryClient()
  const lastVersion = useRef<number | null>(null)
  const q = useQuery({
    queryKey: ['status'],
    queryFn: api.status,
    refetchInterval: (query) => intervalOverrideMs ?? (query.state.data?.refresh_hint_seconds ?? 60) * 1000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    retry: 1,
  })
  useEffect(() => {
    const v = q.data?.data_version
    if (v === undefined) return
    if (lastVersion.current !== null && v !== lastVersion.current) {
      qc.invalidateQueries({ predicate: (query) => query.queryKey[0] !== 'status' })
    }
    lastVersion.current = v
  }, [q.data?.data_version, qc])
  return (
    <Ctx.Provider value={{ status: q.data, error: q.error, isFetching: q.isFetching, lastChecked: q.dataUpdatedAt || null }}>
      {children}
    </Ctx.Provider>
  )
}

export const useLive = () => useContext(Ctx)
