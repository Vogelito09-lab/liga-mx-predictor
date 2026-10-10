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

Las jornadas son las de la fase regular (calculadas igual que en el resto de la página) más Play-In,
Cuartos de final, Semifinales y Final. Un partido reprogramado puede quedar en otra jornada; como cada
partido se cierra a su propia hora, eso no afecta los puntos.

Los puntos no se guardan: se calculan cada vez con los resultados confirmados que trae la sincronización
automática, así que las tablas se actualizan solas y una corrección de la fuente se refleja sin hacer nada.

## Cuentas

- Registro con correo, contraseña y el **código de invitación** (solo lo tienen tus amigos).
- La cuenta se confirma con un enlace que llega por correo (vence en 48 h). Sin confirmar no se puede entrar.
- Al primer ingreso cada persona elige el nombre que aparece en las tablas (único; se puede cambiar).
  El correo nunca se muestra.
- "Olvidé mi contraseña" manda un enlace que sirve 1 hora y una sola vez.
- Seguridad: las contraseñas se guardan con scrypt (no se pueden leer); de las sesiones y enlaces solo se
  guarda un hash. Hay límite de intentos para iniciar sesión y para mandar correos.

## Variables de entorno (servicio `ligamx-api` en Render)

| Variable | Para qué | Ejemplo |
|---|---|---|
| `QUINIELA_INVITE_CODE` | Código para registrarse. Vacío = registro cerrado | `TacosDelViernes` |
| `QUINIELA_LIGUILLA_MULTIPLIER` | Multiplicador de puntos en liguilla (opcional) | `1` |
| `EMAIL_PROVIDER` | `brevo` o `mailjet`. Vacío = no se mandan correos | `brevo` |
| `EMAIL_API_KEY` | Clave del servicio de correo | (de Brevo) |
| `EMAIL_API_SECRET` | Solo Mailjet: la "Secret key" | |
| `EMAIL_FROM` | Remitente verificado en el servicio de correo | `tucorreo@gmail.com` |
| `WEB_URL` | Dirección de la página para los enlaces (opcional; por defecto la de `CORS_ORIGINS`) | |

Render gratis **bloquea los puertos SMTP** desde septiembre de 2025, por eso no se puede mandar con Gmail
directamente y se usa un servicio que recibe los correos por HTTPS (Brevo: 300 correos al día gratis, sin
tarjeta).

### Agregar una variable en Render (paso a paso)

1. Entra a https://dashboard.render.com y abre el servicio **ligamx-api**.
2. En el menú de la izquierda haz clic en **Environment**.
3. Clic en **+ Add Environment Variable**.
4. En **Key** escribe el nombre (por ejemplo `QUINIELA_INVITE_CODE`) y en **Value** el valor.
5. Clic en **Save, rebuild, and deploy**. En unos minutos el servicio se reinicia con el cambio.

## Sin servicio de correo

Si `EMAIL_PROVIDER` está vacío todo funciona igual, pero los correos no salen. En **Administración →
Quiniela: participantes** (con el `ADMIN_TOKEN`) puedes:

- **Confirmar** a cada persona que se registró.
- Generar un **Enlace de contraseña** (sirve 24 horas) para mandarlo por WhatsApp a quien la olvidó.
- **Borrar** una cuenta y sus pronósticos.

## API

| Método y ruta | Descripción |
|---|---|
| `GET /api/auth/config` | Si el registro está abierto y si hay correos |
| `POST /api/auth/register` | `email`, `password`, `invite_code` |
| `POST /api/auth/verify` | `token` del correo → inicia sesión |
| `POST /api/auth/resend-verification` | `email` |
| `POST /api/auth/login` | `email`, `password` → `token` de sesión (60 días) |
| `POST /api/auth/logout` 👤 | Cierra la sesión |
| `GET /api/auth/me` 👤 | Usuario actual |
| `PUT /api/auth/me` 👤 | `display_name` |
| `POST /api/auth/change-password` 👤 | `current_password`, `new_password` |
| `POST /api/auth/forgot-password` | `email` |
| `POST /api/auth/reset-password` | `token`, `password` |
| `GET /api/quiniela/jornadas` | Jornadas del torneo, la actual y cuántos pronósticos te faltan |
| `GET /api/quiniela/jornadas/{clave}` | Partidos con tu pronóstico, el del modelo y (ya iniciados) los de todos |
| `PUT /api/quiniela/picks` 👤 | `picks: [{match_id, home_goals, away_goals}]`; rechaza los partidos ya iniciados |
| `GET /api/quiniela/tablas` | Tabla de cada jornada y tabla general |
| `GET /api/admin/quiniela/users` 🔒 | Participantes |
| `POST /api/admin/quiniela/users/{id}/verify` 🔒 | Confirmar a mano |
| `POST /api/admin/quiniela/users/{id}/link` 🔒 | Enlace para cambiar contraseña |
| `POST /api/admin/quiniela/users/{id}/delete` 🔒 | Borrar cuenta y pronósticos |

👤 `Authorization: Bearer <token de sesión>`. 🔒 `Authorization: Bearer <ADMIN_TOKEN>`.
Todas aceptan `tournament` para ver otro torneo (por defecto, el actual).
