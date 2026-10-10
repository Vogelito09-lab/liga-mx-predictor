import { useState } from 'react'

/** Foto de perfil de la quiniela: el escudo que eligió el participante, o un círculo con su inicial; el modelo es un robot. */
/** Robot dibujado aquí mismo (sin imágenes externas) para el participante virtual: el modelo. */
function Robot({ size }: { size: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" role="img" aria-label="Robot" className="inline-block shrink-0">
      <circle cx="16" cy="16" r="16" className="fill-sky-100 dark:fill-sky-900" />
      <line x1="16" y1="5" x2="16" y2="9" className="stroke-sky-700 dark:stroke-sky-300" strokeWidth="1.5" />
      <circle cx="16" cy="4.5" r="1.8" className="fill-amber-500" />
      <rect x="8" y="9" width="16" height="13" rx="3.5" className="fill-sky-600 dark:fill-sky-400" />
      <rect x="5.5" y="13" width="2.5" height="5" rx="1" className="fill-sky-700 dark:fill-sky-300" />
      <rect x="24" y="13" width="2.5" height="5" rx="1" className="fill-sky-700 dark:fill-sky-300" />
      <circle cx="12.5" cy="14.5" r="2.2" fill="white" /><circle cx="19.5" cy="14.5" r="2.2" fill="white" />
      <circle cx="12.5" cy="14.5" r="1" className="fill-slate-900" /><circle cx="19.5" cy="14.5" r="1" className="fill-slate-900" />
      <rect x="12" y="18.5" width="8" height="1.6" rx="0.8" fill="white" />
      <rect x="10" y="23" width="12" height="5" rx="2" className="fill-sky-700 dark:fill-sky-300" />
    </svg>
  )
}

export function Avatar({ name, crestUrl, isModel = false, size = 24 }: { name: string; crestUrl: string | null | undefined; isModel?: boolean; size?: number }) {
  const [failed, setFailed] = useState(false)
  if (isModel) return <Robot size={size} />
  if (crestUrl && !failed) {
    return <img src={crestUrl} alt="" width={size} height={size} loading="lazy" onError={() => setFailed(true)} className="inline-block shrink-0 object-contain" />
  }
  return (
    <span style={{ width: size, height: size, fontSize: Math.round(size * 0.45) }} aria-hidden
      className="inline-flex shrink-0 items-center justify-center rounded-full bg-slate-200 font-bold uppercase text-slate-600 dark:bg-slate-700 dark:text-slate-200">
      {name.trim().charAt(0) || '?'}
    </span>
  )
}
