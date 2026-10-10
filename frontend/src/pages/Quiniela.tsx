import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { CrestPicker } from '../components/CrestPicker'
import { StatusBadge } from '../components/MatchCard'
import { Alert, Ok, input, primary } from '../components/quiniela-ui'
import { TeamLogo } from '../components/TeamLogo'
import { Badge, Card, Empty, ErrorBox, Loading, SectionTitle, Select } from '../components/ui'
import { quiniela } from '../lib/api'
import { useAuth } from '../lib/auth'
import { fmtDateTime } from '../lib/format'
import type { QItem, QPick, QRow } from '../lib/types'

const KIND_TONE = { exacto: 'green', resultado: 'blue', fallo: 'slate' } as const
const KIND_LABEL = { exacto: 'Exacto', resultado: 'Ganador', fallo: 'Fallo' }

export function Quiniela() {
  const { user, loading } = useAuth()
  const [tab, setTab] = useState<'picks' | 'jornada' | 'general'>('picks')
  if (loading) return <Loading />
  return (
    <div className="space-y-6">
      <SectionTitle right={user?.display_name ? <Link className="text-sm text-slate-500 underline" to="/quiniela/perfil">Mi perfil</Link> : undefined}>Quiniela</SectionTitle>
      <Rules />
      {!user ? <AuthPanel /> : !user.display_name ? <ChooseName /> : null}
      <div className="flex gap-1 text-sm" role="tablist">
        {([['picks', 'Mis pronósticos'], ['jornada', 'Tabla de la jornada'], ['general', 'Tabla general']] as const).map(([k, label]) => (
          <button key={k} role="tab" aria-selected={tab === k} onClick={() => setTab(k)}
            className={`rounded-lg px-3 py-1.5 ${tab === k ? 'bg-brand-700 text-white' : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'}`}>
            {label}
          </button>
        ))}
      </div>
      {tab === 'general' ? <GeneralTable /> : <JornadaView mode={tab} />}
    </div>
  )
}

function Rules() {
  return (
    <Card className="text-sm text-slate-600 dark:text-slate-400">
      Pronostica el marcador de cada partido antes de que empiece. <b>Marcador exacto: 3 puntos.</b> Solo el ganador
      o el empate: 1 punto. Se califica con el marcador a los 90 minutos. Cada jornada trae los partidos que se juegan esa semana, también los reprogramados. Puedes cambiar tu pronóstico hasta que el
      partido inicia; desde ese momento todos ven los pronósticos de todos. Empate en la tabla: gana quien tenga más
      marcadores exactos. El modelo de la página juega con su marcador más probable para que veas si le ganas.
    </Card>
  )
}

// ---------------------------------------------------------------------------------------------------
// Cuenta
// ---------------------------------------------------------------------------------------------------
/** Primera vez que entra alguien sin nombre: nombre y escudo. Después se cambian en Mi perfil. */
function ChooseName() {
  const { token, user, setUser } = useAuth()
  const [name, setName] = useState(user?.display_name ?? '')
  const [crest, setCrest] = useState<number | null>(user?.crest?.team_id ?? null)
  const save = useMutation({
    mutationFn: () => quiniela.updateProfile(token!, { display_name: name, crest_team_id: crest }),
    onSuccess: setUser,
  })
  return (
    <Card className="w-full max-w-xl space-y-3">
      <h3 className="font-semibold">¿Con qué nombre quieres aparecer?</h3>
      <p className="text-sm text-slate-500">Es el nombre que verán todos en las tablas (tu correo nunca se muestra). De 3 a 20 letras o números.</p>
      <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <input className={input} value={name} onChange={(e) => setName(e.target.value)} maxLength={20} placeholder="Tu nombre" autoFocus />
        <p className="text-sm text-slate-500">Elige tu escudo (tu foto de perfil; lo puedes cambiar cuando quieras):</p>
        <CrestPicker value={crest} onChange={setCrest} />
        <button className={primary} disabled={save.isPending || name.trim().length < 3}>Guardar</button>
      </form>
      {save.error && <Alert>{save.error.message}</Alert>}
    </Card>
  )
}

function AuthPanel() {
  const [mode, setMode] = useState<'login' | 'register' | 'forgot'>('login')
  const cfg = useQuery({ queryKey: ['auth-config'], queryFn: quiniela.config })
  return (
    <Card className="mx-auto w-full max-w-md space-y-4">
      <div className="flex gap-2 text-sm">
        <Tab active={mode === 'login'} onClick={() => setMode('login')}>Entrar</Tab>
        <Tab active={mode === 'register'} onClick={() => setMode('register')}>Registro</Tab>
      </div>
      {mode === 'login' && <LoginForm onForgot={() => setMode('forgot')} />}
      {mode === 'register' && (cfg.data && !cfg.data.registration_open
        ? <Alert>Por ahora no se aceptan solicitudes nuevas. Pregúntale al organizador.</Alert>
        : <RegisterForm codeRequired={!!cfg.data?.invite_code_required} />)}
      {mode === 'forgot' && <ForgotForm onBack={() => setMode('login')} />}
    </Card>
  )
}

function Tab({ active, onClick, children }: { active: boolean; onClick: () => void; children: ReactNode }) {
  return <button type="button" onClick={onClick} className={`rounded-lg px-3 py-1.5 ${active ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900' : 'text-slate-600 dark:text-slate-300'}`}>{children}</button>
}

function LoginForm({ onForgot }: { onForgot: () => void }) {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const login = useMutation({ mutationFn: () => quiniela.login(email, password), onSuccess: (r) => { if (r.token) signIn(r.token, r.user) } })
  const resend = useMutation({ mutationFn: () => quiniela.resendVerification(email) })
  const notVerified = (login.error as { status?: number } | null)?.status === 403
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); login.mutate() }}>
      <input className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Correo" autoComplete="email" required />
      <input className={input} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Contraseña" autoComplete="current-password" required />
      <div className="flex items-center justify-between">
        <button className={primary} disabled={login.isPending}>Entrar</button>
        <button type="button" className="text-xs text-slate-500 underline" onClick={onForgot}>Olvidé mi contraseña</button>
      </div>
      {login.error && <Alert>{login.error.message}</Alert>}
      {notVerified && (
        <button type="button" className="text-xs text-brand-700 underline" onClick={() => resend.mutate()} disabled={resend.isPending}>
          Mandarme otra vez el correo de confirmación
        </button>
      )}
      {resend.data && <Ok>{resend.data.message}</Ok>}
      {resend.error && <Alert>{resend.error.message}</Alert>}
    </form>
  )
}

function RegisterForm({ codeRequired }: { codeRequired: boolean }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [code, setCode] = useState('')
  const [crest, setCrest] = useState<number | null>(null)
  const [localError, setLocalError] = useState('')
  const reg = useMutation({ mutationFn: () => quiniela.register(name, email, password, code, crest) })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (password !== password2) { setLocalError('Las contraseñas no coinciden'); return }
    setLocalError('')
    reg.mutate()
  }
  if (reg.data) return <Ok>{reg.data.message}</Ok>
  return (
    <form className="space-y-3" onSubmit={submit}>
      <input className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="Tu nombre en la quiniela (lo verán todos)" maxLength={20} minLength={3} required />
      <input className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Correo (para entrar; nadie más lo ve)" autoComplete="email" required />
      <input className={input} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Contraseña (mínimo 8 caracteres)" autoComplete="new-password" minLength={8} required />
      <input className={input} type="password" value={password2} onChange={(e) => setPassword2(e.target.value)} placeholder="Repite la contraseña" autoComplete="new-password" required />
      <p className="text-sm text-slate-500">Elige tu escudo (será tu foto de perfil; lo puedes cambiar después):</p>
      <CrestPicker value={crest} onChange={setCrest} />
      {codeRequired && <input className={input} value={code} onChange={(e) => setCode(e.target.value)} placeholder="Código de invitación" autoComplete="off" required />}
      <p className="text-xs text-slate-500">Tu registro le llega al organizador de la quiniela. Cuando te apruebe ya podrás entrar con tu correo y contraseña.</p>
      <button className={primary} disabled={reg.isPending}>Registrarme</button>
      {(localError || reg.error) && <Alert>{localError || reg.error?.message}</Alert>}
    </form>
  )
}

function ForgotForm({ onBack }: { onBack: () => void }) {
  const [email, setEmail] = useState('')
  const forgot = useMutation({ mutationFn: () => quiniela.forgotPassword(email) })
  return (
    <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); forgot.mutate() }}>
      <p className="text-sm text-slate-600 dark:text-slate-400">Escribe tu correo y te mandamos un enlace para elegir una contraseña nueva.</p>
      <input className={input} type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Correo" autoComplete="email" required />
      <div className="flex items-center justify-between">
        <button className={primary} disabled={forgot.isPending}>Enviar enlace</button>
        <button type="button" className="text-xs text-slate-500 underline" onClick={onBack}>Volver</button>
      </div>
      {forgot.data && <Ok>{forgot.data.email_enabled === false
        ? 'Por ahora la página no manda correos: pídele al organizador un enlace para cambiar tu contraseña.'
        : forgot.data.message}</Ok>}
      {forgot.error && <Alert>{forgot.error.message}</Alert>}
    </form>
  )
}

// ---------------------------------------------------------------------------------------------------
// Jornadas y pronósticos
// ---------------------------------------------------------------------------------------------------
function useJornadas() {
  const { token } = useAuth()
  return useQuery({ queryKey: ['quiniela', 'jornadas', token], queryFn: () => quiniela.jornadas(token), refetchInterval: 60_000 })
}

function JornadaView({ mode }: { mode: 'picks' | 'jornada' }) {
  const jj = useJornadas()
  const [key, setKey] = useState<string | null>(null)
  const selected = key ?? jj.data?.current ?? null
  if (jj.isLoading) return <Loading />
  if (jj.error) return <ErrorBox error={jj.error} />
  if (!jj.data || !selected) return <Empty>Todavía no hay jornadas.</Empty>
  const options = jj.data.jornadas.map((j) => ({
    value: j.key,
    label: `${j.label}${j.missing_picks ? ` · te faltan ${j.missing_picks}` : ''}${j.key === jj.data.current ? ' (actual)' : ''}`,
  }))
  const pending = jj.data.jornadas.filter((j) => j.missing_picks && j.key !== selected)
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Select label={jj.data.tournament} value={selected} onChange={setKey} options={options} />
        {jj.data.liguilla_multiplier > 1 && <Badge tone="amber">Liguilla: puntos ×{jj.data.liguilla_multiplier}</Badge>}
      </div>
      {mode === 'picks' && pending.length > 0 && (
        <p className="text-xs text-amber-700 dark:text-amber-400">
          También te faltan partidos en: {pending.map((j, i) => (
            <span key={j.key}>{i > 0 && ', '}<button className="underline" onClick={() => setKey(j.key)}>{j.label} ({j.missing_picks})</button></span>
          ))}
        </p>
      )}
      {mode === 'picks' ? <PicksForm key={selected} jornada={selected} tournament={jj.data.tournament} /> : <JornadaTable jornada={selected} />}
    </div>
  )
}

type Draft = Record<number, { home: string; away: string }>

function PicksForm({ jornada, tournament }: { jornada: string; tournament: string }) {
  const { token, user } = useAuth()
  const qc = useQueryClient()
  const detail = useQuery({
    queryKey: ['quiniela', 'jornada', tournament, jornada, token],
    queryFn: () => quiniela.jornada(token, jornada, tournament),
    refetchInterval: 60_000, // los partidos se cierran solos al llegar su hora
  })
  const [draft, setDraft] = useState<Draft>({})
  const canPlay = !!user?.display_name
  const save = useMutation({
    mutationFn: (picks: { match_id: number; home_goals: number; away_goals: number }[]) => quiniela.savePicks(token!, picks),
    onSuccess: (r) => {
      setDraft((d) => Object.fromEntries(Object.entries(d).filter(([id]) => !r.saved.includes(Number(id)))))
      qc.invalidateQueries({ queryKey: ['quiniela'] })
    },
  })
  if (detail.isLoading) return <Loading />
  if (detail.error) return <ErrorBox error={detail.error} />
  const items = detail.data?.items ?? []
  const edits = Object.entries(draft).filter(([id]) => items.some((i) => i.match.id === Number(id) && !i.locked))
  const incomplete = edits.filter(([, v]) => (v.home === '') !== (v.away === ''))
  const ready = edits.filter(([, v]) => v.home !== '' && v.away !== '')
  const submit = () => save.mutate(ready.map(([id, v]) => ({ match_id: Number(id), home_goals: Number(v.home), away_goals: Number(v.away) })))
  const myTotal = items.reduce((a, i) => a + (i.my_pick?.points ?? 0), 0)
  return (
    <div className="space-y-3">
      {!canPlay && <p className="text-sm text-slate-500">Entra a tu cuenta para guardar tus pronósticos.</p>}
      {canPlay && items.some((i) => i.my_pick?.points !== null && i.my_pick?.points !== undefined) && (
        <p className="text-sm">Llevas <b>{myTotal}</b> {myTotal === 1 ? 'punto' : 'puntos'} en esta jornada.</p>
      )}
      <div className="space-y-2">
        {items.map((it) => (
          <PickRow key={it.match.id} it={it} canPlay={canPlay} value={draft[it.match.id]}
            onChange={(v) => setDraft((d) => ({ ...d, [it.match.id]: v }))} />
        ))}
      </div>
      {canPlay && items.some((i) => !i.locked) && (
        // Solo se queda pegada abajo cuando hay cambios sin guardar; si no, no tapa los partidos.
        <div className={`${edits.length ? 'sticky bottom-[max(0.5rem,env(safe-area-inset-bottom))] z-10 shadow-lg' : ''} flex flex-wrap items-center gap-3 rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-800 dark:bg-slate-900`}>
          <button className={primary} disabled={save.isPending || ready.length === 0 || incomplete.length > 0} onClick={submit}>
            {save.isPending ? 'Guardando…' : `Guardar pronósticos${ready.length ? ` (${ready.length})` : ''}`}
          </button>
          {incomplete.length > 0 && <span className="text-xs text-amber-700">Completa los dos goles de cada partido.</span>}
          {save.data && !edits.length && <span className="text-xs text-emerald-700">Guardado ✓</span>}
          {save.data?.rejected.map((r) => <span key={r.match_id} className="text-xs text-red-700">{r.reason}</span>)}
          {save.error && <span className="text-xs text-red-700">{save.error.message}</span>}
        </div>
      )}
    </div>
  )
}

function goalInput(value: string, onChange: (v: string) => void, label: string) {
  return (
    <input aria-label={label} inputMode="numeric" value={value} maxLength={2}
      onChange={(e) => { const v = e.target.value.replace(/\D/g, ''); onChange(v === '' ? '' : String(Math.min(20, Number(v)))) }}
      className="w-11 rounded-lg border border-slate-300 py-1.5 text-center text-lg font-semibold tabular-nums dark:border-slate-700 dark:bg-slate-900" />
  )
}

function PickRow({ it, canPlay, value, onChange }: { it: QItem; canPlay: boolean; value?: { home: string; away: string }; onChange: (v: { home: string; away: string }) => void }) {
  const [showAll, setShowAll] = useState(false)
  const m = it.match
  const cur = value ?? { home: it.my_pick ? String(it.my_pick.home) : '', away: it.my_pick ? String(it.my_pick.away) : '' }
  const editable = canPlay && !it.locked
  const started = m.status === 'in_progress' || m.status === 'finished'
  return (
    <Card className="space-y-2 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
        <span>{fmtDateTime(m.kickoff_utc)}{it.multiplier > 1 ? ` · puntos ×${it.multiplier}` : ''}</span>
        <span className="flex items-center gap-2">
          {it.locked ? <Badge>Cerrado</Badge> : <Badge tone="green">Abierto hasta el inicio</Badge>}
          {m.status !== 'scheduled' && <StatusBadge m={m} />}
        </span>
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
        <div className="flex min-w-0 items-center gap-2"><TeamLogo team={m.home} /><span className="truncate text-sm font-medium">{m.home.name}</span></div>
        <div className="flex items-center gap-1">
          {editable ? (
            <>{goalInput(cur.home, (v) => onChange({ ...cur, home: v }), `Goles de ${m.home.name}`)}<span className="text-slate-400">–</span>{goalInput(cur.away, (v) => onChange({ ...cur, away: v }), `Goles de ${m.away.name}`)}</>
          ) : it.my_pick ? (
            <span className="text-lg font-semibold tabular-nums">{it.my_pick.home} – {it.my_pick.away}</span>
          ) : <span className="text-xs text-slate-400">{canPlay ? 'Sin pronóstico' : '—'}</span>}
        </div>
        <div className="flex min-w-0 items-center justify-end gap-2"><span className="truncate text-right text-sm font-medium">{m.away.name}</span><TeamLogo team={m.away} /></div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-400">
        {started && m.home_goals !== null && <span>Resultado (90'): <b className="tabular-nums">{m.home_goals}–{m.away_goals}</b></span>}
        {it.my_pick && <PointsBadge p={it.my_pick} prefix="Tú" />}
        {it.model_pick && <span className="inline-flex items-center gap-1"><Avatar name="Modelo" crestUrl={null} isModel size={16} />Modelo: <b className="tabular-nums">{it.model_pick.home}–{it.model_pick.away}</b>{it.model_pick.points !== null && ` (${it.model_pick.points} pts)`}</span>}
        {it.locked && it.picks.length > 0 && (
          <button className="text-brand-700 underline dark:text-brand-500" onClick={() => setShowAll((s) => !s)}>
            {showAll ? 'Ocultar pronósticos' : `Ver pronósticos de todos (${it.picks.length})`}
          </button>
        )}
        {!it.locked && <span className="text-slate-400">Los pronósticos de los demás se ven cuando empiece el partido.</span>}
      </div>
      {showAll && (
        <div className="flex flex-wrap gap-2">
          {it.picks.map((p) => (
            <Badge key={p.display_name} tone={p.kind ? KIND_TONE[p.kind] : 'slate'}>
              <span className="mr-1 inline-flex align-middle"><Avatar name={p.display_name} crestUrl={p.crest_url} size={16} /></span>
              {p.is_me ? <b>{p.display_name}</b> : p.display_name}: {p.home}–{p.away}{p.points !== null ? ` · ${p.points}` : ''}
            </Badge>
          ))}
        </div>
      )}
    </Card>
  )
}

function PointsBadge({ p, prefix }: { p: QPick; prefix: string }) {
  if (p.points === null || !p.kind) return null
  return <Badge tone={KIND_TONE[p.kind]}>{prefix}: {KIND_LABEL[p.kind]} · {p.points} {p.points === 1 ? 'punto' : 'puntos'}</Badge>
}

// ---------------------------------------------------------------------------------------------------
// Tablas
// ---------------------------------------------------------------------------------------------------
function useTables() {
  return useQuery({ queryKey: ['quiniela', 'tablas'], queryFn: () => quiniela.tables(), refetchInterval: 60_000 })
}

function JornadaTable({ jornada }: { jornada: string }) {
  const t = useTables()
  if (t.isLoading) return <Loading />
  if (t.error) return <ErrorBox error={t.error} />
  const j = t.data?.jornadas.find((x) => x.key === jornada)
  if (!j) return <Empty>Sin datos para esta jornada.</Empty>
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">
        {j.finished ? 'Jornada terminada.' : `${j.finished_matches} de ${j.matches} partidos terminados; la tabla se actualiza sola.`}
      </p>
      {j.finished && j.winners.length > 0 && <Winner names={j.winners} what={`Ganador de la ${j.label.toLowerCase()}`} />}
      <RankTable rows={j.rows} />
    </div>
  )
}

function GeneralTable() {
  const t = useTables()
  if (t.isLoading) return <Loading />
  if (t.error) return <ErrorBox error={t.error} />
  if (!t.data) return null
  return (
    <div className="space-y-3">
      <p className="text-sm text-slate-500">{t.data.tournament}: puntos acumulados de todas las jornadas{t.data.jornadas.some((j) => j.liguilla) ? ' y la liguilla' : ''}.</p>
      {t.data.finished && t.data.winners.length > 0 && <Winner names={t.data.winners} what={`Campeón de la quiniela del ${t.data.tournament}`} />}
      <RankTable rows={t.data.rows} general />
    </div>
  )
}

function Winner({ names, what }: { names: string[]; what: string }) {
  return (
    <Card className="border-amber-300 bg-amber-50 text-center dark:border-amber-800 dark:bg-amber-950">
      <div className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-300">{what}</div>
      <div className="text-xl font-bold">🏆 {names.join(' y ')}</div>
    </Card>
  )
}

function RankTable({ rows, general = false }: { rows: QRow[]; general?: boolean }) {
  const { user } = useAuth()
  if (!rows.length) return <Empty>Todavía no hay participantes.</Empty>
  return (
    <Card className="overflow-x-auto p-0">
      <table className="w-full text-sm tabular-nums">
        <thead className="text-xs text-slate-500">
          <tr className="border-b border-slate-200 dark:border-slate-800">
            <th className="p-2 text-left">#</th><th className="p-2 text-left">Participante</th><th className="p-2">Puntos</th>
            <th className="p-2" title="Marcadores exactos (3 puntos)">Exactos</th><th className="p-2" title="Solo ganador o empate (1 punto)">Ganador</th>
            <th className="hidden p-2 sm:table-cell" title="Partidos ya calificados con pronóstico">Jugados</th>
            {general && <th className="p-2" title="Jornadas ganadas"><span className="sm:hidden">Jor. ganadas</span><span className="hidden sm:inline">Jornadas ganadas</span></th>}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const me = user && r.user_id === user.id
            return (
              <tr key={r.user_id ?? 'modelo'} className={`border-t border-slate-100 dark:border-slate-800 ${me ? 'bg-brand-50 font-semibold dark:bg-brand-700/20' : ''} ${r.is_model ? 'text-slate-500' : ''}`}>
                <td className="p-2">{r.position}</td>
                <td className="p-2">
                  <span className="flex items-center gap-2">
                    <Avatar name={r.display_name} crestUrl={r.crest_url} isModel={r.is_model} />
                    <span>{r.display_name}{me && ' (tú)'}{r.is_model && <span className="ml-1"><Badge tone="blue">virtual</Badge></span>}</span>
                  </span>
                </td>
                <td className="p-2 text-center text-base font-bold">{r.points}</td>
                <td className="p-2 text-center">{r.exact}</td>
                <td className="p-2 text-center">{r.outcome}</td>
                <td className="hidden p-2 text-center sm:table-cell">{r.scored_picks}</td>
                {general && <td className="p-2 text-center">{r.jornadas_won}</td>}
              </tr>
            )
          })}
        </tbody>
      </table>
    </Card>
  )
}
