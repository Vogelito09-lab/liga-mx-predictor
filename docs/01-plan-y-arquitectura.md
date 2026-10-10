# Liga MX Predictor — Fase 1: fuentes, arquitectura y plan

Última verificación de fuentes: 2026-10-10.

## 1. Fuentes de datos

| Fuente | Qué ofrece | Cobertura verificada | Acceso | Uso en el proyecto |
|---|---|---|---|---|
| **ESPN API pública** (`site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard?dates=YYYYMMDD`) | Calendario, estado del partido (`STATUS_SCHEDULED`, en curso, `STATUS_FULL_TIME`), marcador, IDs estables de equipo y partido, tipo de torneo | Consultada el 2026-10-10: 15-oct-2016 devuelve 6 partidos finalizados del Apertura 2016 (p. ej. Chiapas 1-4 Monterrey); el endpoint actual devuelve la temporada "2026-27 Liga BBVA MX, Torneo Apertura" | Sin API key. **No documentada oficialmente**: puede cambiar sin aviso; los términos de ESPN restringen el uso comercial | **Fuente principal**: histórico 2016→hoy y estados en vivo |
| **Football-Data.co.uk** (`/new/MEX.csv`) | CSV con fecha, hora, local, visitante, goles, resultado y cuotas de apuestas desde 2012/13 | La definición de columnas (HG, AG, Res, PH…) está verificada en `notes.txt`; **la descarga del CSV aún no la pude completar** (ver bloqueo abajo) | Gratis, sin key, uso libre citando la fuente | **Fuente secundaria**: verificación cruzada de marcadores y cuotas como referencia de mercado (no como variable del modelo) |
| API-Football (api-sports.io) | API documentada, en vivo, alineaciones, estadísticas | No verificada (el plan gratuito limita temporadas y 100 consultas/día) | Requiere key | Opcional; el código deja un adaptador preparado |
| football-data.org, TheSportsDB | — | El plan gratuito de football-data.org no incluye la Liga MX; TheSportsDB es limitado sin pago | Key | Descartadas |

Regla del proyecto: un partido solo se marca **finalizado** cuando ESPN lo reporta como `STATUS_FULL_TIME` (o equivalente final). Las discrepancias con Football-Data se registran para revisión y nunca se corrigen en silencio.

## 2. Bloqueo actual

El entorno en la nube donde trabajo solo permite descargar paquetes (pip/npm); niega las conexiones a `site.api.espn.com` y `www.football-data.co.uk`. Las comprobaciones de arriba las hice con una herramienta de lectura web, que sirve para verificar pero no para descargar 10 años de partidos. Hasta que se habiliten esos dominios, construyo y pruebo todo el código con datos de prueba claramente marcados como tales, y **no publico métricas ni predicciones**.

## 3. Arquitectura elegida (100 % gratis, sin tarjeta de crédito)

Restricción del proyecto: nada de pago y nada que pida tarjeta. Todo lo de abajo es software libre o un plan gratuito sin tarjeta, verificado el 2026-10-10.

| Pieza | Elección | Costo | Límites reales del plan gratis |
|---|---|---|---|
| Datos | ESPN API pública + Football-Data.co.uk | $0 | Sin key; uso no comercial |
| Base de datos | **Neon** (PostgreSQL) | $0, sin tarjeta y sin vencimiento | 1 GB por proyecto (el histórico ocupa unos pocos MB); 100 horas de cómputo al mes; se suspende tras 5 min sin uso y despierta en la siguiente consulta |
| Tareas programadas | **GitHub Actions** (cron) | $0 | Ilimitado en repositorio público; 2 000 min/mes en privado y, sin tarjeta, se bloquea en lugar de cobrar. El cron es "mejor esfuerzo": mínimo cada 5 min y puede retrasarse unos minutos |
| API | FastAPI en **Render**, servicio web gratuito | $0 | Se duerme tras 15 min sin visitas y tarda ~1 min en despertar; 750 h/mes. Render no ofrece *workers* ni cron gratis, por eso las tareas van en GitHub Actions |
| Frontend | React en **Render Static Site** (o GitHub Pages) | $0 | Ancho de banda gratuito suficiente para uso personal |
| Código | Python, FastAPI, pandas, scikit-learn, React, etc. | $0 | Software libre |

Descarté Render Postgres porque la base gratuita caduca a los 30 días, y los VPS "siempre gratis" porque piden tarjeta.

**Cómo funciona sin tu computadora**: GitHub Actions ejecuta la sincronización con ESPN cada 10 min en las ventanas de partido (vie–lun por la tarde-noche, hora del centro de México) y cada 6 h fuera de ellas. Cada ejecución valida los datos, guarda resultados confirmados en Neon y regenera las predicciones pendientes. El reentrenamiento corre semanalmente o al cerrar cada jornada.

**Actualización de la página sin recargar**: el frontend consulta `/api/updates/status` cada 60 s y vuelve a pedir partidos y predicciones solo cuando cambia la versión de los datos. Elegí consulta periódica en lugar de SSE porque en planes gratuitos que se duermen es más fiable. En local también funciona igual.

**Límite honesto**: los marcadores "en vivo" se refrescan cada ~10 min (el retraso del cron gratuito de GitHub se suma), no segundo a segundo. La página siempre muestra la hora de la última sincronización.

Desarrollo local en Windows: Python, Node y PostgreSQL instalados localmente (o Docker Desktop, también gratis), con el mismo código.

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2 + Alembic (migraciones), Pydantic.
- **Tablas**: `teams`, `team_aliases`, `matches`, `match_sources`, `data_issues`, `predictions` (solo inserciones), `model_versions`, `backtest_runs`, `job_runs`.
- **Concurrencia**: candado `pg_advisory_lock` y `concurrency` de GitHub Actions para que nunca corran dos sincronizaciones a la vez.
- **Modelos guardados**: archivos versionados (hash + fecha) en la base de datos, para no depender de disco temporal.

## 4. Modelos

| Modelo | Descripción |
|---|---|
| A. Referencia | Frecuencias históricas L/E/V de la ventana de entrenamiento |
| B. Elo | Elo con ventaja de local y factor de margen de goles; probabilidades mediante regresión ordinal sobre la diferencia de Elo |
| C. Poisson (Dixon-Coles) | Ataque/defensa por equipo con ponderación temporal exponencial y corrección de marcadores bajos; produce la matriz de marcadores (de ahí salen el 1X2, los goles esperados y el marcador más probable) |
| D. Logística multinomial | Variables pre-partido: forma de los últimos 5 y 10 partidos, goles, puntos por partido, local/visita, Elo, H2H, descanso, temporada actual |
| E. Gradient boosting | LightGBM, condicionado a que supere a D en validación |

La selección se hace por **log loss** en validación con origen móvil por torneo. El periodo final de prueba (los dos últimos torneos completos) queda reservado y solo se evalúa una vez.

Liguilla: se predice el resultado a los 90 minutos; la prórroga y los penales se guardan aparte y no cuentan para el resultado 1X2.

## 5. Plan por fases

| Fase | Estado (2026-10-10) |
|---|---|
| 1. Fuentes, arquitectura y plan | ✅ Hecho |
| 2. Ingesta ESPN + Football-Data, normalización, validaciones, carga idempotente | ✅ Código y pruebas listos · ⏳ descarga real pendiente de acceso a red |
| 3. Variables con prueba anti-fuga | ✅ Hecho |
| 4–5. Modelos A–F, backtesting con origen móvil, selección y prueba final | ✅ Código y pruebas listos · ⏳ métricas reales pendientes de datos |
| 6. API FastAPI + predicciones inmutables | ✅ Hecho |
| 7. Frontend | ✅ Hecho |
| 8. Tareas programadas + actualización sin recargar + prueba programado→en juego→final | ✅ Hecho (prueba con navegador real) |
| 9. Seguridad, pruebas, README para Windows y despliegue gratuito | ✅ Hecho · ⏳ despliegue real cuando haya repositorio y cuentas |

## 6. Riesgos

- Para publicar la app necesitas una cuenta gratuita de GitHub, Neon y Render; ninguna pide tarjeta.
- La API de ESPN no está documentada: un adaptador aislado y la verificación cruzada con Football-Data reducen el impacto si cambia.
- Cambios de formato de la Liga MX (sin descenso desde 2020, play-in, nuevos clubes como Atlante en 2026-27): se manejan con IDs estables y alias de nombres.
- Para equipos recién llegados hay pocos datos: se usa un Elo y una fuerza previa de respaldo documentados.
- El fútbol tiene mucho azar: un modelo bueno ronda el 50 % de acierto 1X2, y se informará con honestidad frente a la referencia.
