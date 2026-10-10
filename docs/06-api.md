# API

Documentación interactiva (OpenAPI) en `/docs` del backend. Todas las fechas en UTC (ISO 8601).

| Método y ruta | Parámetros | Respuesta |
|---|---|---|
| `GET /api/health` | — | Estado del servidor y conexión a la base |
| `GET /api/updates/status` | `sync_if_stale` (bool, por defecto true) | Versión de datos, última sincronización, si los datos están atrasados, partidos en juego, modelo activo y cada cuánto consultar. Si los datos tienen más de 30 min y hay partidos en curso, inicia una sincronización ligera |
| `GET /api/seasons` | — | Torneos con número de partidos y fechas |
| `GET /api/matches` | `tournament`, `season`, `round` (1–40), `team_id`, `stage`, `status`, `date_from`, `date_to`, `order` (asc/desc), `limit` (1–500), `offset` | Partidos con resultado y la última predicción previa al inicio, más si acertó |
| `GET /api/fixtures/upcoming` | `days` (1–60) | Partidos en juego, programados y finalizados en las últimas 12 h, con predicción |
| `GET /api/predictions` | `match_id` (obligatorio) | Historial completo de predicciones de un partido (404 si no existe) |
| `GET /api/teams` | `tournament` | Equipos |
| `GET /api/teams/{team_id}/statistics` | `last` (5–60) | Forma, local/visitante, por torneo, evolución del Elo |
| `GET /api/standings` | `tournament` (obligatorio) | Tabla de fase regular calculada |
| `GET /api/model/metrics` | — | Último backtesting (todos los modelos, validación y prueba) y rendimiento real |
| `GET /api/backtest/predictions` | `model`, `split` (validation/test), `limit` | Predicciones del backtesting |
| `GET /api/admin/jobs` 🔒 | `limit` | Últimas ejecuciones de tareas |
| `GET /api/admin/issues` 🔒 | `severity`, `resolved`, `limit` | Problemas de datos |
| `POST /api/admin/issues/{id}/resolve` 🔒 | — | Marca un problema como revisado |
| `POST /api/admin/update-data` 🔒 | — | Inicia una sincronización (202) |
| `POST /api/admin/retrain` 🔒 | — | Reentrena y regenera predicciones (202) |
| `POST /api/admin/backtest` 🔒 | — | Backtesting completo (202). En Render gratuito puede quedarse sin memoria; mejor usar GitHub Actions |

🔒 Requiere la cabecera `Authorization: Bearer <ADMIN_TOKEN>`. Sin `ADMIN_TOKEN` configurado responden 503;
con token incorrecto, 401.

Errores: `404` recurso inexistente, `422` parámetros inválidos (con el detalle de FastAPI), `401/503` administración.
