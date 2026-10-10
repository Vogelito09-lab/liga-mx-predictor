import { NavLink, Outlet } from 'react-router-dom'
import { fmtDateTime, fmtTime, relative } from '../lib/format'
import { useLive } from '../lib/live'
import { Badge } from './ui'

const NAV = [
  { to: '/', label: 'Inicio' },
  { to: '/predicciones', label: 'Predicciones' },
  { to: '/historico', label: 'Calendario e histórico' },
  { to: '/equipos', label: 'Equipos' },
  { to: '/rendimiento', label: 'Rendimiento del modelo' },
  { to: '/admin', label: 'Administración' },
]

export function SyncIndicator() {
  const { status, error, isFetching, lastChecked } = useLive()
  if (error && !status) return <Badge tone="red">Sin conexión con el servidor</Badge>
  if (!status) return <Badge>Conectando…</Badge>
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="sync-indicator">
      {status.live_matches > 0 && <Badge tone="live">{status.live_matches} en juego</Badge>}
      {error ? <Badge tone="red">Error al consultar el servidor; se muestran los últimos datos válidos</Badge>
        : status.last_sync_error ? <Badge tone="amber">La fuente falló en el último intento</Badge>
        : status.is_stale ? <Badge tone="amber">Datos posiblemente atrasados</Badge>
        : <Badge tone="green">Datos actualizados</Badge>}
      <span className="text-slate-500" title={fmtDateTime(status.last_sync_success)}>
        Última sincronización con ESPN: {relative(status.last_sync_success)}
      </span>
      <span className="text-slate-400">· revisado {lastChecked ? fmtTime(new Date(lastChecked).toISOString()) : '—'}{isFetching ? ' …' : ''}</span>
    </div>
  )
}

export function Layout() {
  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/90 backdrop-blur dark:border-slate-800 dark:bg-slate-950/90">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <NavLink to="/" className="flex items-center gap-2 text-lg font-bold tracking-tight">
              <img src="/favicon.svg" alt="" width={24} height={24} /> Liga MX Predictor
            </NavLink>
            <SyncIndicator />
          </div>
          <nav className="-mx-1 flex gap-1 overflow-x-auto text-sm">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} end={n.to === '/'}
                className={({ isActive }) => `whitespace-nowrap rounded-lg px-3 py-1.5 ${isActive ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
                {n.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6"><Outlet /></main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 text-xs text-slate-500">
        Datos de partidos: API pública de ESPN (no oficial), verificados con Football-Data.co.uk. Escudos: ESPN.
        Las predicciones son estimaciones probabilísticas y pueden fallar. Proyecto personal sin fines comerciales.
      </footer>
    </div>
  )
}
