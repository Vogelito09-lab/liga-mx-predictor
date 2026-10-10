import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Badge, Card, Empty, ErrorBox, Loading, SectionTitle, Stat } from '../components/ui'
import { api } from '../lib/api'
import { fmtDateTime, relative } from '../lib/format'
import { useLive } from '../lib/live'

const KEY = 'ligamx-admin-token'
function readToken() { try { return sessionStorage.getItem(KEY) ?? '' } catch { return '' } }

const JOB_TONE: Record<string, 'green' | 'amber' | 'red' | 'slate'> = { success: 'green', skipped: 'amber', failed: 'red', running: 'slate' }

export function Admin() {
  const { status } = useLive()
  const [token, setToken] = useState(readToken)
  const [draft, setDraft] = useState('')
  const qc = useQueryClient()
  const jobs = useQuery({ queryKey: ['admin-jobs', token], queryFn: () => api.adminJobs(token), enabled: !!token, refetchInterval: 15000 })
  const issues = useQuery({ queryKey: ['admin-issues', token], queryFn: () => api.adminIssues(token), enabled: !!token })
  const action = useMutation({
    mutationFn: (a: 'update-data' | 'retrain' | 'backtest') => api.adminAction(token, a),
    onSuccess: () => setTimeout(() => qc.invalidateQueries({ queryKey: ['admin-jobs'] }), 1500),
  })
  const resolve = useMutation({ mutationFn: (id: number) => api.adminResolve(token, id), onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-issues'] }) })

  if (!token) {
    return (
      <Card className="mx-auto max-w-md space-y-3">
        <SectionTitle>Administración</SectionTitle>
        <p className="text-sm text-slate-600 dark:text-slate-400">Introduce el token de administración (variable ADMIN_TOKEN del servidor). Se guarda solo en esta pestaña.</p>
        <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); try { sessionStorage.setItem(KEY, draft) } catch { /* sin almacenamiento */ } setToken(draft) }}>
          <input type="password" value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Token" autoComplete="off"
            className="flex-1 rounded-lg border border-slate-300 px-3 py-1.5 text-sm dark:border-slate-700 dark:bg-slate-900" />
          <button className="rounded-lg bg-brand-700 px-3 py-1.5 text-sm text-white">Entrar</button>
        </form>
      </Card>
    )
  }
  const unauthorized = (jobs.error as { status?: number } | null)?.status === 401
  return (
    <div className="space-y-6">
      <SectionTitle right={<button className="text-xs text-slate-500 underline" onClick={() => { try { sessionStorage.removeItem(KEY) } catch { /* */ } setToken('') }}>Salir</button>}>Administración</SectionTitle>
      {unauthorized && <ErrorBox error={new Error('Token inválido')} />}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Fuente" value={<span className="text-base">ESPN</span>} hint={status?.last_sync_error ? `Último error: ${status.last_sync_error}` : 'Sin errores en el último intento'} />
        <Stat label="Última sincronización correcta" value={<span className="text-base">{relative(status?.last_sync_success)}</span>} hint={fmtDateTime(status?.last_sync_success)} />
        <Stat label="Versión de datos" value={status?.data_version ?? '—'} />
        <Stat label="Problemas de datos abiertos" value={Object.values(issues.data?.open_counts ?? {}).reduce((a, b) => a + b, 0)}
          hint={Object.entries(issues.data?.open_counts ?? {}).map(([k, v]) => `${k}: ${v}`).join(' · ')} />
      </div>
      <Card className="space-y-3">
        <h3 className="text-sm font-semibold">Acciones</h3>
        <div className="flex flex-wrap gap-2">
          <button onClick={() => action.mutate('update-data')} className="rounded-lg bg-brand-700 px-3 py-1.5 text-sm text-white">Actualizar datos ahora</button>
          <button onClick={() => { if (confirm('¿Reentrenar el modelo con todos los datos actuales?')) action.mutate('retrain') }} className="rounded-lg border px-3 py-1.5 text-sm">Reentrenar modelo</button>
          <button onClick={() => { if (confirm('El backtesting completo tarda varios minutos y reentrena el modelo. ¿Continuar?')) action.mutate('backtest') }} className="rounded-lg border px-3 py-1.5 text-sm">Backtesting completo</button>
        </div>
        {action.data && <p className="text-sm text-emerald-700">{action.data.message}</p>}
        {action.error && <ErrorBox error={action.error} />}
        <p className="text-xs text-slate-500">
          Tareas programadas (GitHub Actions): sincronización ligera cada 10 min en horario de partidos (17:00–00:59, hora del centro de México),
          sincronización completa cada 6 h, mantenimiento diario (reentrenamiento según política) y backtesting mensual.
        </p>
      </Card>
      <Card className="overflow-x-auto">
        <h3 className="mb-2 text-sm font-semibold">Últimas ejecuciones</h3>
        {jobs.isLoading ? <Loading /> : !jobs.data?.length ? <Empty>Sin ejecuciones registradas.</Empty> : (
          <table className="w-full min-w-[640px] text-xs">
            <thead className="text-slate-500"><tr><th className="text-left">Inicio</th><th className="text-left">Tarea</th><th>Origen</th><th>Estado</th><th className="text-left">Mensaje</th></tr></thead>
            <tbody>{jobs.data.map((j) => (
              <tr key={j.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1">{fmtDateTime(j.started_at)}</td><td>{j.job}</td><td className="text-center">{j.trigger}</td>
                <td className="text-center"><Badge tone={JOB_TONE[j.status] ?? 'slate'}>{j.status}</Badge></td>
                <td className="max-w-md truncate" title={JSON.stringify(j.stats)}>{j.message ?? ''}</td>
              </tr>))}</tbody>
          </table>)}
      </Card>
      <Card className="overflow-x-auto">
        <h3 className="mb-2 text-sm font-semibold">Registro de problemas de datos</h3>
        {issues.isLoading ? <Loading /> : !issues.data?.items.length ? <Empty>No hay problemas abiertos.</Empty> : (
          <table className="w-full min-w-[640px] text-xs">
            <thead className="text-slate-500"><tr><th className="text-left">Fecha</th><th>Gravedad</th><th className="text-left">Código</th><th className="text-left">Detalle</th><th /></tr></thead>
            <tbody>{issues.data.items.map((i) => (
              <tr key={i.id} className="border-t border-slate-100 dark:border-slate-800">
                <td className="py-1">{fmtDateTime(i.created_at)}</td>
                <td className="text-center"><Badge tone={i.severity === 'error' ? 'red' : i.severity === 'warning' ? 'amber' : 'slate'}>{i.severity}</Badge></td>
                <td>{i.code}</td><td>{i.message}</td>
                <td><button className="underline" onClick={() => resolve.mutate(i.id)}>Marcar revisado</button></td>
              </tr>))}</tbody>
          </table>)}
      </Card>
    </div>
  )
}
