import { useState } from 'react'

/** Foto de perfil de la quiniela: el escudo que eligió el participante, o un círculo con su inicial. */
export function Avatar({ name, crestUrl, isModel = false, size = 24 }: { name: string; crestUrl: string | null | undefined; isModel?: boolean; size?: number }) {
  const [failed, setFailed] = useState(false)
  if (crestUrl && !failed) {
    return <img src={crestUrl} alt="" width={size} height={size} loading="lazy" onError={() => setFailed(true)} className="inline-block shrink-0 object-contain" />
  }
  return (
    <span style={{ width: size, height: size, fontSize: Math.round(size * 0.45) }} aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-slate-200 font-bold uppercase text-slate-600 dark:bg-slate-700 dark:text-slate-200">
      {isModel ? '🤖' : name.trim().charAt(0) || '?'}
    </span>
  )
}
