import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis } from 'recharts'
import { Badge, Card, Empty, ErrorBox, Loading, SectionTitle, Select, Stat } from '../components/ui'
import { api } from '../lib/api'
import { fmtDateTime, MODEL_LABEL, num, pct } from '../lib/format'
import type { MetricSummary } from '../lib/types'

const OUT = ['local', 'empate', 'visitante']

export function Performance() {
  const q = useQuery({ queryKey: ['metrics'], queryFn: api.metrics })
  const [split, setSplit] = useState<'test' | 'validation'>('test')
  if (q.isLoading) return <Loading />
  if (q.error) return <ErrorBox error={q.error} />
  const d = q.data!
  if (!d.available || !d.summary) return <Empty>{d.message ?? 'Aún no hay métricas.'} Las métricas solo se muestran cuando el backtesting se ejecutó con datos reales.</Empty>
  const s = d.summary
  const models = Object.keys(s.models)
  const sel = s.models[s.selected_model][split]
  const rows = models.map((m) => ({ m, ...s.models[m][split] }))
  const byT = Object.entries(sel.by_tournament ?? {}).map(([t, v]) => ({ torneo: t, Exactitud: v.accuracy, 'Log loss': v.log_loss, n: v.n }))
  return (
    <div className="space-y-6">
      <SectionTitle right={<Select label="Periodo" value={split} onChange={(v) => setSplit(v as 'test' | 'validation')}
        options={[{ value: 'test', label: 'Prueba final (no usada para elegir)' }, { value: 'validation', label: 'Validación (usada para elegir)' }]} />}>
        Rendimiento del modelo
      </SectionTitle>
      <p className="text-sm text-slate-600 dark:text-slate-400">
        Backtesting con origen móvil: cada partido se predijo con un modelo entrenado solo con partidos anteriores (reentrenamiento semanal).
        Modelo seleccionado por <b>{s.selection_metric}</b>: <Badge tone="green">{MODEL_LABEL[s.selected_model] ?? s.selected_model}</Badge>.
        Ejecutado el {fmtDateTime(d.created_at)}
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Partidos evaluados" value={sel.n} hint={split === 'test' ? s.folds.test.join(', ') : `${s.folds.validation.length} torneos`} />
        <Stat label="Exactitud (resultado más probable)" value={pct(sel.accuracy, 1)} hint={`Referencia: ${pct(s.models.A_referencia?.[split].accuracy, 1)}`} />
        <Stat label="Log loss (menor es mejor)" value={num(sel.log_loss, 3)} hint={`Referencia: ${num(s.models.A_referencia?.[split].log_loss, 3)}`} />
        <Stat label="Brier multiclase (menor es mejor)" value={num(sel.brier, 3)} hint={`RPS ${num(sel.rps, 3)}`} />
      </div>

      <Card className="overflow-x-auto">
        <h3 className="mb-2 text-sm font-semibold">Comparación de modelos ({split === 'test' ? 'prueba final' : 'validación'})</h3>
        <table className="w-full min-w-[640px] text-sm tabular-nums">
          <thead className="text-xs text-slate-500"><tr><th className="text-left">Modelo</th><th>n</th><th>Exactitud</th><th>Log loss</th><th>Brier</th><th>RPS</th><th>MAE goles esperados</th><th>MAE marcador</th><th>Marcador exacto</th></tr></thead>
          <tbody>{rows.map((r) => (
            <tr key={r.m} className={`border-t border-slate-100 text-center dark:border-slate-800 ${r.m === s.selected_model ? 'font-semibold' : ''}`}>
              <td className="py-1 text-left">{MODEL_LABEL[r.m] ?? r.m}</td><td>{r.n}</td><td>{pct(r.accuracy, 1)}</td><td>{num(r.log_loss, 4)}</td>
              <td>{num(r.brier, 4)}</td><td>{num(r.rps, 4)}</td><td>{num(r.goals?.mae_expected_goals)}</td><td>{num(r.goals?.mae_top_score)}</td><td>{pct(r.goals?.exact_score_hit_rate, 1)}</td>
            </tr>))}</tbody>
        </table>
      </Card>

      <div className="grid gap-4 md:grid-cols-2">
        <Calibration m={sel} />
        <Card>
          <h3 className="mb-2 text-sm font-semibold">Matriz de confusión (filas = real, columnas = predicho)</h3>
          <table className="mx-auto text-sm tabular-nums">
            <thead><tr><th /><th className="px-3">{OUT[0]}</th><th className="px-3">{OUT[1]}</th><th className="px-3">{OUT[2]}</th><th className="px-3 text-slate-500">Acierto</th></tr></thead>
            <tbody>{sel.confusion?.map((row, i) => (
              <tr key={i}><th className="pr-3 text-right">{OUT[i]}</th>{row.map((v, j) => <td key={j} className={`px-3 py-1 text-center ${i === j ? 'font-bold text-brand-700' : ''}`}>{v}</td>)}
                <td className="px-3 text-center text-slate-500">{pct(sel.recall_by_outcome?.[OUT[i]], 0)}</td></tr>))}</tbody>
          </table>
          <p className="mt-3 text-xs text-slate-500">Frecuencia real L/E/V: {sel.observed_freq?.map((x) => pct(x)).join(' / ')} · Probabilidad media predicha: {sel.mean_probs?.map((x) => pct(x)).join(' / ')}</p>
        </Card>
      </div>

      <Card>
        <h3 className="mb-2 text-sm font-semibold">Evolución por torneo (modelo seleccionado)</h3>
        {byT.length ? (
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={byT}><CartesianGrid strokeDasharray="3 3" opacity={0.3} /><XAxis dataKey="torneo" fontSize={10} /><YAxis yAxisId="a" domain={[0.3, 0.7]} fontSize={11} />
              <YAxis yAxisId="b" orientation="right" domain={['auto', 'auto']} fontSize={11} /><Tooltip /><Legend />
              <Line yAxisId="a" dataKey="Exactitud" stroke="#0d9488" /><Line yAxisId="b" dataKey="Log loss" stroke="#6366f1" /></LineChart>
          </ResponsiveContainer>) : <Empty>Sin datos.</Empty>}
      </Card>

      <Card>
        <h3 className="mb-2 text-sm font-semibold">Rendimiento real (predicciones guardadas antes de cada partido)</h3>
        {d.live.n ? (
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4 text-sm">
            <div>Partidos: <b>{d.live.n}</b></div><div>Exactitud: <b>{pct(d.live.accuracy, 1)}</b></div>
            <div>Log loss: <b>{num(d.live.log_loss, 3)}</b></div><div>Brier: <b>{num(d.live.brier, 3)}</b></div>
          </div>) : <p className="text-sm text-slate-500">{d.live.message ?? 'Sin partidos evaluados todavía.'}</p>}
      </Card>

      <Card className="text-xs text-slate-600 dark:text-slate-400">
        <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-slate-100">Cómo leer estas métricas</h3>
        <ul className="list-disc space-y-1 pl-4">
          <li><b>Exactitud</b>: porcentaje de partidos donde el resultado con mayor probabilidad ocurrió. Ignora qué tan seguras eran las probabilidades.</li>
          <li><b>Log loss</b>: castiga mucho asignar baja probabilidad a lo que ocurrió. Es la métrica usada para elegir el modelo. Adivinar 1/3 para todo da 1.099.</li>
          <li><b>Brier y RPS</b>: error cuadrático de las probabilidades; RPS además considera que el empate está "entre" local y visitante.</li>
          <li><b>Calibración</b>: si el modelo dice 40 %, el evento debería ocurrir cerca del 40 % de las veces.</li>
          <li>Con pocos cientos de partidos por periodo, diferencias pequeñas entre modelos pueden deberse al azar.</li>
        </ul>
      </Card>
    </div>
  )
}

function Calibration({ m }: { m: MetricSummary }) {
  const colors = { local: '#0d9488', empate: '#94a3b8', visitante: '#6366f1' }
  return (
    <Card>
      <h3 className="mb-2 text-sm font-semibold">Calibración (probabilidad predicha vs frecuencia observada)</h3>
      <ResponsiveContainer width="100%" height={260}>
        <ScatterChart><CartesianGrid strokeDasharray="3 3" opacity={0.3} />
          <XAxis type="number" dataKey="predicted" domain={[0, 1]} name="Predicha" fontSize={11} />
          <YAxis type="number" dataKey="observed" domain={[0, 1]} name="Observada" fontSize={11} />
          <ZAxis type="number" dataKey="n" range={[20, 200]} name="n" /><Tooltip /><Legend />
          {OUT.map((k) => <Scatter key={k} name={k} data={m.calibration?.[k] ?? []} fill={colors[k as keyof typeof colors]} />)}
          <Scatter name="perfecta" data={[{ predicted: 0, observed: 0, n: 1 }, { predicted: 1, observed: 1, n: 1 }]} line shape={() => <g />} fill="#cbd5e1" legendType="none" />
        </ScatterChart>
      </ResponsiveContainer>
    </Card>
  )
}
