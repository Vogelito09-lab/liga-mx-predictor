# Quiniela entre amigos

Sección **Quiniela** de la página: cada amigo se registra, pronostica el marcador de cada partido de la
jornada y la página lleva una tabla por jornada y una tabla general del torneo.

## Reglas

| Concepto | Regla |
|---|---|
| Marcador exacto | 3 puntos |
| Solo el ganador o el empate | 1 punto |
| No acierta nada | 0 puntos |
| Marcador que cuenta | El de los 90 minutos (sin prórroga ni penales) |
| Hasta cuándo se puede pronosticar | Cada partido se cierra a su hora de inicio (los demás de la jornada siguen abiertos) |
| Pronósticos de los demás | Se ven cuando el partido ya empezó |
| Desempate | Más marcadores exactos |
| Liguilla | Cuenta igual que la fase regular. Para puntos dobles: `QUINIELA_LIGUILLA_MULTIPLIER=2` |
| El modelo | Juega como participante virtual con su marcador más probable (la última predicción antes del inicio). Aparece en las tablas pero el campeón es el mejor participante humano |

Cada jornada de la quiniela tiene los partidos que **se juegan esa semana**. ESPN no publica el número de
jornada oficial y la página lo calcula; un partido reprogramado quedaría en su jornada original aunque se
juegue semanas después. Por eso la quiniela lo pasa a la jornada en cuyas fechas se juega (la ventana de
fechas de la mayoría de sus partidos; si no cae en ninguna, la más cercana). Después vienen Play-In,
Cuartos de final, Semifinales y Final. Los pronósticos van pegados a cada partido, así que mover un
partido de jornada no los afecta; solo cambia en qué tabla de jornada cuenta.

Los puntos no se guardan: se calculan cada vez con los resultados confirmados que trae la sincronización
automática, así que las tablas se actualizan solas y una corrección de la fuente se refleja sin hacer nada.

## Cuentas: el organizador aprueba a cada persona

1. En **Quiniela → Pedir acceso** la persona escribe su nombre (el que verán todos), su correo, una contraseña y, si quiere, el escudo de su equipo.
2. La solicitud aparece en **Administración → Quiniela: solicitudes y participantes** (entras con el `ADMIN_TOKEN`).
3. El organizador da clic en **Aprobar** o **Rechazar**. Sin aprobar nadie puede entrar ni pronosticar.
4. Ya aprobada, la persona entra con su correo y contraseña. El correo nunca se muestra en las tablas.

- Nombres únicos (sin distinguir mayúsculas ni acentos); se pueden cambiar después.
- **Escudo (foto de perfil)**: cada quien elige el escudo de un equipo de la Liga MX actual (se pueden repetir).
  Sale junto a su nombre en las tablas y en los pronósticos. Sin escudo se muestra un círculo con su inicial.
- **Panel arriba a la derecha**: nombre y escudo de quien entró; al darle clic muestra sus puntos y su lugar en
  la tabla general, **Mi perfil** (`/quiniela/perfil`: cambiar nombre, escudo y contraseña) y **Cerrar sesión**.
- **Olvidó su contraseña**: en Administración, botón **Enlace de contraseña** junto a su nombre. El enlace
  sirve 24 horas y una sola vez; se manda por WhatsApp.
- **Borrar**: saca a la persona de la quiniela junto con sus pronósticos.
- Seguridad: las contraseñas se guardan con scrypt (no se pueden leer); de las sesiones y enlaces solo se
  guarda un hash. Hay límite de intentos para iniciar sesión y para pedir acceso.

No hace falta ninguna variable nueva en Render. Opcionales (servicio `ligamx-api` → **Environment**):

| Variable | Para qué |
|---|---|
| `QUINIELA_REGISTRATION_OPEN` | `false` para dejar de recibir solicitudes nuevas |
| `QUINIELA_INVITE_CODE` | Pedir además un código al solicitar acceso |
| `QUINIELA_LIGUILLA_MULTIPLIER` | `2` para puntos dobles en liguilla |

### Correos (opcional, apagado)

El código puede mandar correos de confirmación y de "olvidé mi contraseña" con Brevo o Mailjet
(`EMAIL_PROVIDER`, `EMAIL_API_KEY`, `EMAIL_FROM`; `EMAIL_API_SECRET` solo Mailjet). Se decidió no usarlo:
la aprobación del organizador ya filtra quién entra. Render gratis bloquea los puertos SMTP desde
septiembre de 2025, por eso no se puede usar Gmail directo.

## API

| Método y ruta | Descripción |
|---|---|
| `GET /api/auth/config` | Si el registro está abierto y si hay correos |
| `POST /api/auth/register` | Pedir acceso: `display_name`, `email`, `password`, `crest_team_id` opcional (`invite_code` si se configuró) |
| `POST /api/auth/verify` | `token` del correo (solo con correos activados) |
| `POST /api/auth/resend-verification` | `email` |
| `POST /api/auth/login` | `email`, `password` → `token` de sesión (60 días). 423 si falta la aprobación |
| `POST /api/auth/logout` 👤 | Cierra la sesión |
| `GET /api/auth/me` 👤 | Usuario actual |
| `PUT /api/auth/me` 👤 | `display_name` y/o `crest_team_id` (lo que no se envía no cambia; `null` quita el escudo) |
| `GET /api/auth/crests` | Escudos que se pueden elegir (equipos del torneo actual) |
| `POST /api/auth/change-password` 👤 | `current_password`, `new_password` |
| `POST /api/auth/forgot-password` | `email` |
| `POST /api/auth/reset-password` | `token`, `password` |
| `GET /api/quiniela/jornadas` | Jornadas del torneo, la actual y cuántos pronósticos te faltan |
| `GET /api/quiniela/jornadas/{clave}` | Partidos con tu pronóstico, el del modelo y (ya iniciados) los de todos |
| `PUT /api/quiniela/picks` 👤 | `picks: [{match_id, home_goals, away_goals}]`; rechaza los partidos ya iniciados |
| `GET /api/quiniela/tablas` | Tabla de cada jornada y tabla general |
| `GET /api/admin/quiniela/users` 🔒 | Participantes |
| `POST /api/admin/quiniela/users/{id}/approve` 🔒 | Aprobar solicitud |
| `POST /api/admin/quiniela/users/{id}/reject` 🔒 | Rechazar solicitud (la borra) |
| `POST /api/admin/quiniela/users/{id}/link` 🔒 | Enlace para cambiar contraseña |
| `POST /api/admin/quiniela/users/{id}/delete` 🔒 | Borrar cuenta y pronósticos |

👤 `Authorization: Bearer <token de sesión>`. 🔒 `Authorization: Bearer <ADMIN_TOKEN>`.
Todas aceptan `tournament` para ver otro torneo (por defecto, el actual).
