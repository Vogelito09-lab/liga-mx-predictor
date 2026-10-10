import { useQuery, useQueryClient } from '@tanstack/react-query'
import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { ApiError, quiniela } from './api'
import type { AuthUser } from './types'

/**
 * Sesión de la quiniela. El token se guarda en este navegador (localStorage) y viaja en el encabezado
 * Authorization; la API solo guarda su hash. Si el servidor responde 401, la sesión se borra.
 */
const KEY = 'ligamx-quiniela-token'

function readToken() { try { return localStorage.getItem(KEY) } catch { return null } }
function writeToken(t: string | null) {
  try { if (t) localStorage.setItem(KEY, t); else localStorage.removeItem(KEY) } catch { /* sin almacenamiento */ }
}

interface AuthCtx {
  token: string | null
  user: AuthUser | undefined
  loading: boolean
  signIn: (token: string, user: AuthUser) => void
  signOut: () => void
  setUser: (user: AuthUser) => void
}

const Ctx = createContext<AuthCtx>({ token: null, user: undefined, loading: false, signIn: () => {}, signOut: () => {}, setUser: () => {} })

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient()
  const [token, setToken] = useState<string | null>(readToken)
  const me = useQuery({ queryKey: ['auth-me', token], queryFn: () => quiniela.me(token!), enabled: !!token, staleTime: Infinity, retry: false })

  const signIn = useCallback((t: string, user: AuthUser) => {
    writeToken(t)
    qc.setQueryData(['auth-me', t], user)
    setToken(t)
    qc.invalidateQueries({ queryKey: ['quiniela'] })
  }, [qc])

  const signOut = useCallback(() => {
    if (token) quiniela.logout(token).catch(() => { /* la sesión se borra igual en este navegador */ })
    writeToken(null)
    setToken(null)
    qc.removeQueries({ queryKey: ['auth-me'] })
    qc.invalidateQueries({ queryKey: ['quiniela'] })
  }, [qc, token])

  const setUser = useCallback((user: AuthUser) => qc.setQueryData(['auth-me', token], user), [qc, token])

  // Sesión vencida o cerrada desde otro lado.
  useEffect(() => {
    if (me.error instanceof ApiError && me.error.status === 401) {
      writeToken(null)
      setToken(null)
    }
  }, [me.error])

  return (
    <Ctx.Provider value={{ token, user: token ? me.data : undefined, loading: !!token && me.isLoading, signIn, signOut, setUser }}>
      {children}
    </Ctx.Provider>
  )
}

export const useAuth = () => useContext(Ctx)
