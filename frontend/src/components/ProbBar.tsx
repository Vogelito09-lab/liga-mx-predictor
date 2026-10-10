import { pct } from '../lib/format'

export function ProbBar({ home, draw, away, compact = false }: { home: number; draw: number; away: number; compact?: boolean }) {
  const parts = [
    { key: 'L', label: 'Local', v: home, cls: 'bg-home' },
    { key: 'E', label: 'Empate', v: draw, cls: 'bg-draw' },
    { key: 'V', label: 'Visitante', v: away, cls: 'bg-away' },
  ]
  return (
    <div>
      <div className="flex h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800" role="img"
        aria-label={`Local ${pct(home)}, empate ${pct(draw)}, visitante ${pct(away)}`}>
        {parts.map((p) => <div key={p.key} className={p.cls} style={{ width: `${p.v * 100}%` }} />)}
      </div>
      {!compact && (
        <div className="mt-1.5 grid grid-cols-3 text-xs tabular-nums">
          {parts.map((p, i) => (
            <div key={p.key} className={i === 0 ? 'text-left' : i === 1 ? 'text-center' : 'text-right'}>
              <span className="text-slate-500">{p.label} </span><span className="font-semibold">{pct(p.v)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
