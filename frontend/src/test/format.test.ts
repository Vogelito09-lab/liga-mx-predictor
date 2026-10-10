import { describe, expect, it } from 'vitest'
import { mxTodayRange, probLabel } from '../lib/format'

describe('formato', () => {
  it('el día de hoy se cuenta en la hora del centro de México', () => {
    // 10-oct-2026 03:30 UTC = 9-oct-2026 21:30 en la Ciudad de México
    const r = mxTodayRange(new Date('2026-10-10T03:30:00Z'))
    expect(r.day).toBe('2026-10-09')
    expect(r.from).toBe('2026-10-09T06:00:00.000Z')
    expect(r.to).toBe('2026-10-10T05:59:59.999Z')
  })

  it('porcentajes de la tabla', () => {
    expect(probLabel(null)).toBe('—')
    expect(probLabel(0)).toBe('0 %')
    expect(probLabel(0.0004)).toBe('<0.1 %')
    expect(probLabel(0.4732)).toBe('47.3 %')
    expect(probLabel(0.9996)).toBe('>99.9 %')
    expect(probLabel(1)).toBe('100 %')
  })
})
