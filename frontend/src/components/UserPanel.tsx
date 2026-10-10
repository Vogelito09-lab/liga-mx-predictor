import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { quiniela } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Avatar } from './Avatar'

/** Arriba a la derecha: nombre y escudo de quien entró a la quiniela, con un menú pequeño. */
export function UserPanel() {
  const { user, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const tables = useQuery({ queryKey: ['quiniela', 'tablas'], queryFn: () => quiniela.tables(), enabled: open && !!user?.display_name, refetchInterval: 60_000 })

  useEffect(() => {
    if (!open) return
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const esc = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', close)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', close); document.removeEventListener('keydown', esc) }
  }, [open])

  if (!user) {
    return <Link to="/quiniela" className="rounded-lg border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">Entrar a la quiniela</Link>
  }
  const name = user.display_name ?? 'Elige tu nombre'
  const row = tables.data?.rows.find((r) => r.user_id === user.id)
  const item = 'block w-full rounded-lg px-3 py-2 text-left hover:bg-slate-100 dark:hover:bg-slate-800'
  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className="flex items-center gap-2 rounded-full border border-slate-200 py-1 pl-1 pr-3 text-sm font-medium hover:bg-slate-100 dark:border-slate-700 dark:hover:bg-slate-800">
        <Avatar name={name} crestUrl={user.crest?.logo_url} size={28} />
        <span className="max-w-[10rem] truncate">{name}</span>
        <span className="text-xs text-slate-400" aria-hidden>▾</span>
      </button>
      {open && (
        <div role="menu" className="absolute right-0 z-20 mt-2 w-64 rounded-xl border border-slate-200 bg-white p-2 text-sm shadow-lg dark:border-slate-800 dark:bg-slate-900">
          <div className="flex items-center gap-3 px-3 py-2">
            <Avatar name={name} crestUrl={user.crest?.logo_url} size={40} />
            <div className="min-w-0">
              <div className="truncate font-semibold">{name}</div>
              <div className="text-xs text-slate-500">
                {!user.display_name ? 'Todavía no eliges tu nombre'
                  : tables.isLoading ? 'Cargando tus puntos…'
                  : row ? <>{row.points} {row.points === 1 ? 'punto' : 'puntos'} · lugar {row.position} de {tables.data!.rows.length}</>
                  : 'Sin puntos todavía'}
              </div>
              {tables.data && <div className="text-[11px] text-slate-400">{tables.data.tournament}</div>}
            </div>
          </div>
          <hr className="my-1 border-slate-200 dark:border-slate-800" />
          <Link role="menuitem" to="/quiniela/perfil" className={item} onClick={() => setOpen(false)}>Mi perfil</Link>
          <Link role="menuitem" to="/quiniela" className={item} onClick={() => setOpen(false)}>Mis pronósticos</Link>
          <button role="menuitem" className={`${item} text-red-700 dark:text-red-400`} onClick={() => { setOpen(false); signOut() }}>Cerrar sesión</button>
        </div>
      )}
    </div>
  )
}
