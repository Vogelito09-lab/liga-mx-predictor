import { defineConfig } from '@playwright/test'

// Prueba de extremo a extremo: backend real + navegador real + servidor falso con formato ESPN.
// Requiere PostgreSQL local con la base "ligamx_e2e". Ver README (sección Pruebas).
const PY = process.env.E2E_PYTHON ?? '../.venv/bin/python'
const DB = process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://postgres:postgres@localhost:5432/ligamx_e2e'
const env = { DATABASE_URL: DB, ESPN_BASE_URL: 'http://127.0.0.1:9911', HTTP_MIN_INTERVAL_S: '0', ENV: 'test' }

export default defineConfig({
  testDir: './e2e',
  timeout: 120_000,
  use: { baseURL: 'http://127.0.0.1:5199', launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {} },
  webServer: [
    { command: `${PY} tests/e2e_fake_espn.py 9911`, cwd: '../backend', port: 9911, reuseExistingServer: false },
    { command: `${PY} -m tests.e2e_seed && ${PY} -m uvicorn app.api.main:app --port 8199`, cwd: '../backend', port: 8199,
      env, timeout: 180_000, reuseExistingServer: false },
    { command: 'npx vite --port 5199 --strictPort --host 127.0.0.1', port: 5199, reuseExistingServer: false,
      env: { VITE_PROXY_TARGET: 'http://127.0.0.1:8199', VITE_STATUS_POLL_MS: '1500' } },
  ],
})
