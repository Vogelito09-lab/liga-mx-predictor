import { useMutation } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { Card, Loading, SectionTitle } from '../components/ui'
import { quiniela } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Alert, Ok } from '../components/quiniela-ui'

/** Página a la que lleva el enlace del correo de confirmación. */
export function ConfirmEmail() {
  const [params] = useSearchParams()
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''
  const verify = useMutation({
    mutationFn: () => quiniela.verify(token),
    onSuccess: (r) => { if (r.token) { signIn(r.token, r.user); setTimeout(() => navigate('/quiniela'), 1500) } },
  })
  const started = useRef(false)
  useEffect(() => {
    // El enlace es de un solo uso: se envía una sola vez aunque React monte el componente dos veces.
    if (token && !started.current) { started.current = true; verify.mutate() }
  }, [token, verify])
  return (
    <Card className="mx-auto max-w-md space-y-3">
      <SectionTitle>Confirmar correo</SectionTitle>
      {!token && <Alert>El enlace está incompleto. Ábrelo de nuevo desde el correo.</Alert>}
      {verify.isPending && <Loading label="Confirmando…" />}
      {verify.data && (verify.data.token
        ? <Ok>¡Listo! Tu correo quedó confirmado. Te llevamos a la quiniela…</Ok>
        : <Ok>¡Listo! Tu correo quedó confirmado. Podrás entrar cuando el organizador apruebe tu solicitud.</Ok>)}
      {verify.error && <><Alert>{verify.error.message}</Alert><Link className="text-sm underline" to="/quiniela">Ir a la quiniela</Link></>}
    </Card>
  )
}

/** Página a la que lleva el enlace para cambiar la contraseña. */
export function ResetPassword() {
  const [params] = useSearchParams()
  const { signIn } = useAuth()
  const navigate = useNavigate()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [password2, setPassword2] = useState('')
  const [localError, setLocalError] = useState('')
  const reset = useMutation({
    mutationFn: () => quiniela.resetPassword(token, password),
    onSuccess: (r) => { if (r.token) { signIn(r.token, r.user); setTimeout(() => navigate('/quiniela'), 1500) } },
  })
  return (
    <Card className="mx-auto max-w-md space-y-3">
      <SectionTitle>Nueva contraseña</SectionTitle>
      {!token ? <Alert>El enlace está incompleto. Ábrelo de nuevo desde el correo.</Alert> : reset.isSuccess ? (
        <Ok>{reset.data?.token ? 'Tu contraseña cambió y ya iniciaste sesión. Te llevamos a la quiniela…'
          : 'Tu contraseña cambió. Podrás entrar cuando el organizador apruebe tu solicitud.'}</Ok>
      ) : (
        <form className="space-y-2" onSubmit={(e) => {
          e.preventDefault()
          if (password !== password2) { setLocalError('Las contraseñas no coinciden'); return }
          setLocalError('')
          reset.mutate()
        }}>
          <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900" type="password"
            value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Nueva contraseña (mínimo 8)" autoComplete="new-password" minLength={8} required />
          <input className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900" type="password"
            value={password2} onChange={(e) => setPassword2(e.target.value)} placeholder="Repite la contraseña" autoComplete="new-password" required />
          <button className="rounded-lg bg-brand-700 px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={reset.isPending}>Guardar contraseña</button>
          {(localError || reset.error) && <Alert>{localError || reset.error?.message}</Alert>}
        </form>
      )}
    </Card>
  )
}
