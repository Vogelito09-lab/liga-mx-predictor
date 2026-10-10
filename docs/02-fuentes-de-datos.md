# Fuentes de datos y cobertura

Última verificación: **2026-10-10**. Solo se usan fuentes gratuitas que no piden registro ni tarjeta.

## Tabla de fuentes

| | ESPN (principal) | Football-Data.co.uk (verificación) | API-Football | football-data.org | TheSportsDB |
|---|---|---|---|---|---|
| URL | `https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1/scoreboard?dates=AAAAMMDD` | `https://www.football-data.co.uk/new/MEX.csv` | api-sports.io | api.football-data.org | thesportsdb.com |
| Temporadas | Comprobado: partidos del Apertura 2016 (15-oct-2016) y temporada actual 2026-27 | El sitio indica desde 2012/13 (descarga pendiente de verificar, ver abajo) | Plan gratis limitado a pocas temporadas | Plan gratis **no incluye** Liga MX | Limitado sin pago |
| Datos | Fecha/hora UTC, estado (programado, en juego, final, final tras prórroga/penales, aplazado…), marcador, goles con minuto, penales, IDs estables de equipo y partido, escudos | Fecha, hora, local, visitante, goles (HG, AG), resultado, cuotas de apuestas | Completo (alineaciones, estadísticas) | — | — |
| Formato | JSON | CSV | JSON | JSON | JSON |
| API key | No | No | Sí | Sí | Sí para lo útil |
| Costo | $0 | $0 | Gratis limitado / pago | — | — |
| Límites | No publicados; el sistema hace pausas de 0.4 s entre consultas y reintenta con espera exponencial | Archivo único, se descarga una vez por semana | 100 consultas/día gratis | — | — |
| Términos | API pública no documentada; los términos de ESPN restringen el uso comercial. Este proyecto es personal y no comercial | Uso libre citando la fuente | — | — | — |
| Uso aquí | Histórico, calendario y resultados en vivo | Verificación cruzada de marcadores | No se usa (no es gratis sin límites) | No se usa | No se usa |

## Qué se verificó y cómo

El 2026-10-10 se consultó la API de ESPN y se confirmó:

- `?dates=20161015` devuelve 6 partidos finalizados del Apertura 2016 (por ejemplo, Chiapas 1-4 Monterrey) con
  `season.slug = "torneo-apertura-2016"` y la lista de goles con su minuto (`details[].clock.displayValue`).
- `?dates=20161225` devuelve la final del Apertura 2016 (Tigres vs América): estado `STATUS_FINAL_PEN`,
  marcador 1-1 que **incluye la prórroga** (goles en los minutos 95 y 119), penales 3-0 en `shootoutScore`,
  `season.slug = "apertura-2016---final"`.
- El endpoint sin fecha devuelve la temporada "2026-27 Liga BBVA MX, Torneo Apertura".

De Football-Data.co.uk se verificó la definición de columnas en `notes.txt` (HG, AG, Res, cuotas). **La descarga del
CSV no se pudo completar** desde el entorno de desarrollo en la nube porque su red solo permite gestores de paquetes;
el código está listo y probado con un CSV de ejemplo, y la verificación real se hará en la primera ejecución con acceso.

## Cómo se tratan los datos

- **Datos crudos**: cada versión distinta de un partido recibido se guarda en `source_records` (subconjunto del JSON,
  sin enlaces ni transmisiones). Los datos limpios viven en `matches` y `teams`.
- **Identificadores estables**: equipos y partidos se identifican por su ID de ESPN. Los cambios de nombre se guardan
  como alias (`team_aliases`), de modo que un club que cambia de nombre (o de sede) sigue siendo el mismo equipo si ESPN
  mantiene su ID; si ESPN le asigna un ID nuevo, se trata como equipo nuevo y la auditoría avisa si los nombres son casi iguales.
- **Marcador a 90 minutos**: es el que usan los modelos. En partidos con prórroga se calcula con la lista de goles
  (minuto ≤ 90, incluido el añadido "90'+3'"). Si la lista no cuadra con el marcador final, el marcador a 90' queda vacío,
  el partido no se usa para entrenar y se registra el problema. El marcador final y los penales se guardan aparte.
- **Torneo y temporada**: del `season.slug` de ESPN; si no lo trae, por la fecha local (julio–diciembre = Apertura).
- **Fase**: regular, liguilla o play-in, según el `slug` y las notas del partido.
- **Jornada**: ESPN no la publica para la Liga MX. Se deriva como el n-ésimo partido de cada equipo en el torneo, así que
  un partido reprogramado puede aparecer en una jornada distinta a la oficial.
- **Estado finalizado**: solo cuando ESPN reporta un estado final y hay marcador. Un partido finalizado nunca vuelve a
  "en juego" por una respuesta contradictoria posterior (se registra el problema). Si ESPN corrige un marcador ya
  finalizado, se aplica la corrección y queda registrada como "cambio retroactivo".

## Validaciones (tabla `data_issues`)

| Código | Qué detecta | Efecto |
|---|---|---|
| `missing_id`, `missing_team`, `same_team`, `bad_status`, `bad_date` | Campos obligatorios ausentes o inválidos | Registro rechazado |
| `bad_score`, `contradictory_score` | Goles negativos, > 15, o marcador a 90' mayor que el final | Registro rechazado |
| `finished_without_score`, `finished_in_future` | Finalizado sin marcador confirmado o antes de empezar | Registro rechazado |
| `regulation_score_unknown` | Prórroga sin lista de goles consistente | Se guarda sin marcador a 90' |
| `stale_scheduled` | Programado en el pasado sin resultado (posible reprogramación) | Aviso |
| `status_regression` | La fuente "des-finaliza" un partido | Se ignora el cambio |
| `retroactive_change` | La fuente corrige un marcador final | Se aplica y se registra |
| `possible_duplicate` | Mismo enfrentamiento con dos IDs a menos de 36 h | Aviso |
| `similar_team_names` | Dos equipos con nombres casi iguales | Aviso |
| `crosscheck_mismatch` | ESPN y Football-Data no coinciden | Aviso con ambos marcadores |

Las cargas son **idempotentes**: repetir una descarga no duplica partidos ni borra datos válidos (hay pruebas para ello).
