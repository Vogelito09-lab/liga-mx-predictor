import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Avatar } from '../components/Avatar'
import { CrestPicker } from '../components/CrestPicker'
import { Alert, Ok, input, primary } from '../components/quiniela-ui'
import { Card, Loading, SectionTitle } from '../components/ui'
import { quiniela } from '../lib/api'
import { useAuth } from '../lib/auth'

/** Mi perfil: nombre visible, escudo (foto de perfil) y contraseña. */
export function Profile() {
  const { user, loading } = useAuth()
  if (loading) return <Loading />
  if (!user) {
    return (
      <div className="space-y-4">
        <SectionTitle>Mi perfil</SectionTitle>
        <p className="text-sm text-slate-500">Primero <Link className="underline" to="/quiniela">entra a la quiniela</Link>.</p>
      </div>
    )
  }
  return (
    <div className="space-y-6">
      <SectionTitle>Mi perfil</SectionTitle>
      <div className="flex items-center gap-3">
        <Avatar name={user.display_name ?? '?'} crestUrl={user.crest?.logo_url} size={56} />
        <div className="min-w-0">
          <div className="text-lg font-semibold">{user.display_name ?? 'Sin nombre'}</div>
          <div className="break-all text-sm text-slate-500">{user.email} (solo tú lo ves)</div>
        </div>
      </div>
      <NameForm />
      <CrestForm />
      <PasswordForm />
    </div>
  )
}

function NameForm() {
  const { token, user, setUser } = useAuth()
  const [name, setName] = useState(user?.display_name ?? '')
  const save = useMutation({ mutationFn: () => quiniela.updateProfile(token!, { display_name: name }), onSuccess: setUser })
  return (
    <Card className="max-w-xl space-y-3">
      <h3 className="font-semibold">Nombre</h3>
      <p className="text-sm text-slate-500">Es el nombre que ven todos en las tablas. De 3 a 20 letras o números; no puede repetirse.</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <input className={input} value={name} onChange={(e) => { setName(e.target.value); save.reset() }} maxLength={20} placeholder="Tu nombre" />
        <button className={primary} disabled={save.isPending || name.trim().length < 3 || name.trim() === user?.display_name}>Guardar</button>
      </form>
      {save.isSuccess && <Ok>Listo, tu nombre cambió.</Ok>}
      {save.error && <Alert>{save.error.message}</Alert>}
    </Card>
  )
}

function CrestForm() {
  const { token, user, setUser } = useAuth()
  const save = useMutation({ mutationFn: (id: number | null) => quiniela.updateProfile(token!, { crest_team_id: id }), onSuccess: setUser })
  return (
    <Card className="max-w-xl space-y-3">
      <h3 className="font-semibold">Escudo</h3>
      <p className="text-sm text-slate-500">Es tu foto de perfil en la quiniela. Elige el de tu equipo; puedes cambiarlo cuando quieras.</p>
      <CrestPicker value={user?.crest?.team_id ?? null} onChange={(id) => save.mutate(id)} disabled={save.isPending} />
      {save.isSuccess && <Ok>Listo, tu escudo cambió.</Ok>}
      {save.error && <Alert>{save.error.message}</Alert>}
    </Card>
  )
}

function PasswordForm() {
  const { token } = useAuth()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const save = useMutation({
    mutationFn: () => quiniela.changePassword(token!, current, next),
    onSuccess: () => { setCurrent(''); setNext('') },
  })
  return (
    <Card className="max-w-xl space-y-3">
      <h3 className="font-semibold">Contraseña</h3>
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); save.mutate() }}>
        <input className={input} type="password" value={current} onChange={(e) => setCurrent(e.target.value)} placeholder="Contraseña actual" autoComplete="current-password" required />
        <input className={input} type="password" value={next} onChange={(e) => setNext(e.target.value)} placeholder="Nueva contraseña (mínimo 8)" autoComplete="new-password" minLength={8} required />
        <button className={primary} disabled={save.isPending}>Cambiar contraseña</button>
      </form>
      {save.isSuccess && <Ok>Listo, tu contraseña cambió.</Ok>}
      {save.error && <Alert>{save.error.message}</Alert>}
    </Card>
  )
}
