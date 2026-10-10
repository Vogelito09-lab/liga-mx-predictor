# Despliegue gratuito y tareas automáticas

Todo funciona sin que tu computadora esté encendida y sin pagar nada. Ningún servicio de esta guía pide tarjeta de
crédito. Límites verificados el 2026-10-10.

```
GitHub Actions (cron) ──► ESPN ──► Neon (PostgreSQL) ◄── Render: API FastAPI ◄── Render: web estática ◄── navegador
     tareas cada 10 min / 6 h / diario / mensual                (se duerme sin visitas)       consulta cada 30–60 s
```

| Servicio | Para qué | Plan gratuito |
|---|---|---|
| GitHub | Código y tareas programadas (Actions) | Repositorio público: minutos ilimitados. Privado: 2 000 min/mes; sin tarjeta, al llegar al límite se pausan, no se cobra |
| Neon | Base de datos PostgreSQL | 1 GB por proyecto, 100 horas de cómputo/mes, sin vencimiento; se suspende tras 5 min sin uso y despierta sola |
| Render | API (servicio web) y web (sitio estático) | 750 h/mes; el servicio web se duerme tras 15 min sin visitas y tarda ~1 min en despertar. La base de datos gratuita de Render caduca a los 30 días, por eso se usa Neon |

## 1. Subir el código a GitHub

1. Crea una cuenta gratuita en https://github.com.
2. Crea un repositorio nuevo (por ejemplo `liga-mx-predictor`). Recomendado: **público** (minutos ilimitados de Actions;
   el código no contiene contraseñas, que van en "Secrets").
3. Desde la carpeta raíz del proyecto, en PowerShell:

```powershell
git init
git add .
git commit -m "Liga MX Predictor"
git branch -M main
git remote add origin https://github.com/TU_USUARIO/liga-mx-predictor.git
git push -u origin main
```

## 2. Base de datos en Neon

1. Crea una cuenta en https://neon.com (puedes entrar con tu cuenta de GitHub).
2. Crea un proyecto (región: `AWS US East` es la más cercana a México disponible normalmente).
3. En **Connect**, copia la cadena de conexión (`postgresql://usuario:clave@ep-....neon.tech/neondb?sslmode=require`).
   El sistema acepta ese formato tal cual.

## 3. Secretos en GitHub

En el repositorio: **Settings → Secrets and variables → Actions → New repository secret**:

- `DATABASE_URL`: la cadena de Neon.

## 4. Carga inicial (una sola vez)

En el repositorio: **Actions → Tareas programadas → Run workflow**, y ejecuta en este orden, esperando a que cada una
termine en verde:

1. `backfill` (descarga desde el Apertura 2016; 30–60 min).
2. `crosscheck` (verificación con Football-Data.co.uk).
3. `backtest` (evalúa y entrena el modelo; varios minutos).

## 5. API y web en Render

1. Crea una cuenta en https://render.com (con GitHub).
2. **New → Blueprint** y elige el repositorio. Render lee `render.yaml` y propone dos servicios gratuitos:
   `ligamx-api` y `ligamx-web`.
3. Te pedirá los valores marcados como `sync: false`:
   - `ligamx-api` → `DATABASE_URL`: la cadena de Neon. `CORS_ORIGINS`: la URL de la web (puedes poner primero
     `https://ligamx-web.onrender.com` y corregirla cuando Render muestre la definitiva).
   - `ligamx-web` → `VITE_API_URL`: la URL de la API (p. ej. `https://ligamx-api.onrender.com`).
4. Render genera `ADMIN_TOKEN` automáticamente: cópialo desde **ligamx-api → Environment** para entrar a
   **Administración** en la web.
5. Si cambias `VITE_API_URL`, vuelve a desplegar `ligamx-web` (Manual Deploy) porque se incrusta al compilar.

## 6. Tareas programadas (`.github/workflows/scheduled.yml`)

| Tarea | Cuándo (hora del centro de México) | Qué hace |
|---|---|---|
| `live` | Cada 10 min de 17:00 a 00:59 | Consulta ayer, hoy y mañana: estados y marcadores; si algo cambió, recalcula predicciones de partidos que no han empezado |
| `sync` | Cada 6 h | Últimos 4 días y próximos 60 días: resultados, reprogramaciones y calendario nuevo |
| `maintenance` | Diario 03:40 | Auditoría, reentrenamiento según la política, predicciones pendientes |
| `crosscheck` | Lunes 05:05 | Verificación cruzada con Football-Data.co.uk |
| `backtest` | Día 1 de cada mes 04:00 | Backtesting completo, selección de modelo y entrenamiento |
| Copia de seguridad | Domingo 06:30 | `pg_dump` guardado como artefacto de GitHub durante 90 días (`backup.yml`) |

- Dos tareas nunca corren a la vez: GitHub las pone en cola (`concurrency`) y además cada tarea toma un candado en
  PostgreSQL; si otra ya escribe, la nueva termina como `skipped` sin tocar datos.
- Si ESPN falla, se conservan los datos existentes, la ejecución queda como `failed` con el error, la web muestra
  "La fuente falló en el último intento" y la siguiente ejecución vuelve a intentarlo.
- GitHub desactiva los cron de repositorios sin actividad durante 60 días; la tarea diaria hace un commit automático
  cada 45 días sin actividad para evitarlo.
- **Repositorio privado**: la tarea `live` consume ~48 min/día (~1 450 min/mes) más el resto; cabe en los 2 000 min,
  pero con poco margen. Si lo prefieres privado, cambia `*/10` por `*/15` en `scheduled.yml`.

## 7. Qué tan "en vivo" es

- La web consulta la API cada 30 s si hay partidos en juego y cada 60 s si no; cuando la versión de datos cambia,
  vuelve a pedir marcadores, tablas y predicciones sin recargar.
- Los datos nuevos llegan con la tarea `live` (cada ~10 min; GitHub puede retrasarla algunos minutos). Además, si alguien
  abre la web durante un partido y los datos tienen más de 30 min, la API lanza una sincronización ligera (como máximo una
  cada 2 min).
- Si la API estaba dormida, la primera visita tarda ~1 min en cargar.

## 8. Mantenimiento

- Restaurar una copia: descarga el artefacto de **Actions → Copia de seguridad** y ejecuta
  `pg_restore --clean --no-owner -d "CADENA_DE_CONEXION" ligamx-AAAAMMDD.dump`.
  Neon además permite volver a cualquier punto de las últimas 6 horas (plan gratuito).
- Actualizar dependencias: edita `backend/requirements.in`, instala, ejecuta las pruebas y regenera
  `backend/requirements.txt` con `pip freeze`. En el frontend, `npm update` y `npm test`.
- Cambios en la base de datos: modifica `backend/app/models.py`, crea la migración con
  `alembic revision --autogenerate -m "descripción"`, revísala y súbela; Render y las tareas aplican
  `alembic upgrade head` automáticamente.
