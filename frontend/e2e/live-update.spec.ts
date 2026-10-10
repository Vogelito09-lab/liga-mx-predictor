import { expect, test } from '@playwright/test'
import { execFileSync } from 'node:child_process'

// Prueba obligatoria: un partido pasa de programado → en curso → finalizado y la página
// se actualiza sola, sin recargar. Los equipos y marcadores son simulados.
const FAKE = 'http://127.0.0.1:9911/__event'
const PY = process.env.E2E_PYTHON ?? '../.venv/bin/python'
const DB = process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://postgres:postgres@localhost:5432/ligamx_e2e'

const kickoff = new Date(Date.now() + 60 * 60 * 1000) // dentro de una hora
const iso = kickoff.toISOString().slice(0, 16) + 'Z'

function ev(status: string, state: string, hs: number | null, as: number | null, detail = '') {
  const comp = (side: string, id: string, score: number | null) => ({
    homeAway: side, score: score === null ? '0' : String(score), team: { id, displayName: `Equipo ${id}`, abbreviation: `E${id}`, logo: null },
  })
  return {
    id: 'e2e-1', date: iso, name: 'Equipo 2 at Equipo 1', season: { year: 2030, type: 1, slug: 'torneo-apertura-2030' },
    competitions: [{ date: iso, status: { type: { name: status, state, completed: state === 'post', detail, shortDetail: detail } },
      notes: [], competitors: [comp('home', '1', hs), comp('away', '2', as)], details: [] }],
  }
}

async function setEvent(body: object) {
  const r = await fetch(FAKE, { method: 'POST', body: JSON.stringify(body) })
  expect(r.ok).toBeTruthy()
}

function runSync() {
  execFileSync(PY, ['-m', 'app.jobs.cli', 'live'], {
    cwd: '../backend', env: { ...process.env, DATABASE_URL: DB, ESPN_BASE_URL: 'http://127.0.0.1:9911', HTTP_MIN_INTERVAL_S: '0' },
    stdio: 'pipe',
  })
}

test('la página refleja el resultado confirmado sin recargar', async ({ page }) => {
  await setEvent(ev('STATUS_SCHEDULED', 'pre', null, null))
  runSync()

  await page.goto('/predicciones')
  const card = page.getByTestId('match-e2e-1').locator('..')
  await expect(card).toBeVisible()
  await expect(card.getByText(/Marcador más probable/)).toBeVisible()
  await expect(page.getByTestId('match-e2e-1').getByTestId('score')).toHaveCount(0)
  await page.evaluate(() => { (window as unknown as { __sinRecarga: boolean }).__sinRecarga = true })

  await setEvent(ev('STATUS_FIRST_HALF', 'in', 1, 0, "31'"))
  runSync()
  await expect(page.getByTestId('match-e2e-1').getByTestId('score')).toHaveText('1 – 0', { timeout: 15_000 })
  await expect(card.getByText(/En juego/)).toBeVisible()

  await setEvent(ev('STATUS_FULL_TIME', 'post', 2, 0, 'FT'))
  runSync()
  await expect(page.getByTestId('match-e2e-1').getByTestId('score')).toHaveText('2 – 0', { timeout: 15_000 })
  await expect(card.getByText('Final', { exact: true })).toBeVisible()

  // la página nunca se recargó: la marca puesta en window sigue ahí
  expect(await page.evaluate(() => (window as unknown as { __sinRecarga?: boolean }).__sinRecarga)).toBe(true)
})
