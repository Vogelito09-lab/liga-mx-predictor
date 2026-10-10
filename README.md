# Liga MX Predictor

Aplicación web que estima probabilidades de **victoria local, empate y victoria visitante** y el **marcador más probable**
de cada partido de la Liga MX. Usa el histórico desde el Apertura 2016, modelos estadísticos y de machine learning
evaluados con backtesting, y se actualiza sola cuando terminan los partidos.

> Las predicciones son estimaciones con incertidumbre, no resultados garantizados.

Todo el proyecto usa software libre y servicios gratuitos que no piden tarjeta de crédito (ver [docs/04-despliegue.md](docs/04-despliegue.md)).

## Contenido

| Carpeta | Qué hay |
|---|---|
| `backend/app/sources` | Adaptadores de las fuentes de datos (ESPN, Football-Data.co.uk) |
| `backend/app/ingest` | Normalización, validación y carga idempotente |
| `backend/app/features` | Variables predictivas sin fuga de información |
| `backend/app/ml` | Modelos A–F, métricas y backtesting |
| `backend/app/predict` | Entrenamiento del modelo de producción y predicciones inmutables |
| `backend/app/jobs` | Tareas (sincronización, mantenimiento, backtesting) y candado de concurrencia |
| `backend/app/api` | API REST (FastAPI) |
| `backend/alembic` | Migraciones de la base de datos |
| `backend/tests` | Pruebas automáticas (pytest) |
| `frontend/` | Web (React + TypeScript + Vite + Tailwind + Recharts) |
| `.github/workflows` | Pruebas, tareas programadas y copias de seguridad (GitHub Actions) |
| `render.yaml` | Despliegue gratuito de la API y la web en Render |
| `docs/` | Plan, fuentes, modelos, despliegue y limitaciones |

## Documentación

1. [Plan y arquitectura](docs/01-plan-y-arquitectura.md)
2. [Fuentes de datos y cobertura](docs/02-fuentes-de-datos.md)
3. [Modelos, variables y backtesting](docs/03-modelos-y-backtesting.md)
4. [Despliegue gratuito y tareas automáticas](docs/04-despliegue.md)
5. [Limitaciones conocidas](docs/05-limitaciones.md)
6. [API](docs/06-api.md) (y documentación interactiva en `http://localhost:8000/docs`)
7. [Resultados con datos reales](docs/07-resultados-reales.md)
8. [Quiniela entre amigos](docs/08-quiniela.md)

---

## Instalación en Windows (PowerShell + Visual Studio Code)

Todos los comandos son para **PowerShell**. Cada bloque indica desde qué carpeta se ejecuta.

### 1. Instalar las herramientas (una sola vez)

Abre PowerShell y ejecuta (si `winget` no existe, instala "App Installer" desde Microsoft Store):

```powershell
winget install --id Git.Git -e
winget install --id Python.Python.3.13 -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id PostgreSQL.PostgreSQL.16 -e
winget install --id Microsoft.VisualStudioCode -e
```

Durante la instalación de PostgreSQL elige una contraseña para el usuario `postgres` y anótala.
Cierra y vuelve a abrir PowerShell para que reconozca los programas. Comprueba:

```powershell
python --version   # 3.13.x
node --version     # v22.x o superior
git --version
```

Si PowerShell no deja activar entornos virtuales, ejecuta una vez:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

### 2. Crear la base de datos local

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE ligamx;"
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE ligamx_test;"
```

### 3. Entorno virtual de Python y dependencias

Desde la carpeta raíz del proyecto (`liga-mx-predictor`):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
```

Cada vez que abras una terminal nueva, vuelve a activar el entorno con `.\.venv\Scripts\Activate.ps1`
(en VS Code: `Ctrl+Shift+P` → "Python: Select Interpreter" → `.venv`).

### 4. Variables de entorno

Desde `liga-mx-predictor\backend`:

```powershell
Copy-Item .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Abre `backend\.env` en VS Code y ajusta:

- `DATABASE_URL=postgresql+psycopg://postgres:TU_CLAVE@localhost:5432/ligamx`
- `ADMIN_TOKEN=` el valor que imprimió el comando anterior.

### 5. Crear las tablas

Desde `liga-mx-predictor\backend`:

```powershell
alembic upgrade head
```

### 6. Descargar el histórico (Apertura 2016 → hoy)

Desde `liga-mx-predictor\backend` (tarda unos 30–60 minutos porque consulta ESPN día por día con pausas):

```powershell
python -m app.jobs.cli backfill --start 2016-07-01
```

Se puede interrumpir y volver a ejecutar: no duplica partidos y conserva lo ya descargado.

### 7. Validar los datos

```powershell
python -m app.jobs.cli crosscheck     # compara marcadores con Football-Data.co.uk
python -m app.jobs.cli maintenance    # auditoría (duplicados, equipos con nombres casi iguales, etc.)
```

Los problemas encontrados no se borran ni se corrigen solos: quedan registrados y se revisan en la página
**Administración** de la web.

### 8. Backtesting y primer modelo

```powershell
python -m app.jobs.cli backtest
```

Evalúa los modelos A–F con origen móvil, elige el mejor por log loss en validación, informa el resultado en el
periodo de prueba reservado, entrena el modelo de producción y genera las predicciones pendientes.
Tarda varios minutos.

### 9. Iniciar el backend

Desde `liga-mx-predictor\backend`:

```powershell
uvicorn app.api.main:app --reload
```

API en `http://localhost:8000` y documentación interactiva en `http://localhost:8000/docs`.

### 10. Iniciar el frontend

En **otra** terminal, desde `liga-mx-predictor\frontend`:

```powershell
npm install
npm run dev
```

Abre `http://localhost:5173`. La página consulta al backend cada 30–60 segundos y se actualiza sola.

### 11. Actualización manual

Desde `liga-mx-predictor\backend`:

```powershell
python -m app.jobs.cli sync           # resultados de los últimos 4 días y calendario de 60 días
python -m app.jobs.cli live           # ayer, hoy y mañana (rápido)
python -m app.jobs.cli maintenance --force-retrain
```

También puedes usar los botones de la página **Administración** (pide el `ADMIN_TOKEN`).

### 12. Tareas automáticas

En tu computadora puedes programar `python -m app.jobs.cli live` con el Programador de tareas de Windows, pero
la forma recomendada (y gratuita) es GitHub Actions, que funciona aunque tu computadora esté apagada.
Ver [docs/04-despliegue.md](docs/04-despliegue.md).

### 13. Despliegue en internet

Neon (base de datos) + Render (API y web) + GitHub Actions (tareas), todo en plan gratuito.
Paso a paso en [docs/04-despliegue.md](docs/04-despliegue.md).

---

## Pruebas

Backend (desde `liga-mx-predictor\backend`, con el entorno activado; usa la base `ligamx_test`):

```powershell
$env:TEST_DATABASE_URL = "postgresql+psycopg://postgres:TU_CLAVE@localhost:5432/ligamx_test"
python -m pytest
```

Frontend (desde `liga-mx-predictor\frontend`):

```powershell
npm test
```

Prueba de extremo a extremo con navegador real (programado → en juego → finalizado sin recargar la página).
Necesita la base `ligamx_e2e` y descargar Chromium una vez. Desde `liga-mx-predictor\frontend`:

```powershell
& "C:\Program Files\PostgreSQL\16\bin\psql.exe" -U postgres -c "CREATE DATABASE ligamx_e2e;"
npx playwright install chromium
$env:E2E_PYTHON = "..\.venv\Scripts\python.exe"
$env:E2E_DATABASE_URL = "postgresql+psycopg://postgres:TU_CLAVE@localhost:5432/ligamx_e2e"
npm run e2e
```

Las pruebas usan una liga **simulada** (equipos "Equipo 1", "Equipo 2"…) para comprobar el código; esos datos
nunca se mezclan con la base real.

## Solución de errores comunes

| Síntoma | Causa probable y solución |
|---|---|
| `python` abre Microsoft Store | Desactiva los "alias de ejecución de aplicaciones" de Python en Configuración de Windows, o reinstala Python con winget |
| `Activate.ps1 cannot be loaded` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| `password authentication failed` | La contraseña de `DATABASE_URL` en `backend\.env` no coincide con la de PostgreSQL |
| `connection refused` en el puerto 5432 | El servicio de PostgreSQL no está iniciado: `Start-Service postgresql-x64-16` (PowerShell como administrador) |
| `relation "matches" does not exist` | Falta `alembic upgrade head` |
| La web dice "Sin conexión con el servidor" | El backend no está corriendo en el puerto 8000 |
| La web dice "Datos posiblemente atrasados" | No hubo sincronización correcta en los últimos 30 min con partidos en juego (o en 7 h sin partidos); ejecuta `python -m app.jobs.cli live` o revisa Administración |
| `Primero hay que ejecutar el backtesting` | Ejecuta `python -m app.jobs.cli backtest` |
| `Datos insuficientes para backtesting` | Falta descargar el histórico (paso 6) |
| Una tarea termina como `skipped` | Otra actualización estaba en curso; es el candado que evita corrupción. Vuelve a intentarlo después |
| `Otra actualización está en curso` durante mucho tiempo | Si una tarea se cortó, el candado se libera solo al cerrarse su conexión; reinicia el backend |
