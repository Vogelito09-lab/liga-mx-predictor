"""Envío de correos (confirmación de cuenta y cambio de contraseña).

Render gratis bloquea los puertos SMTP (25, 465 y 587), así que se usan servicios que reciben el correo
por HTTPS. Proveedores: "brevo" o "mailjet" (ambos con plan gratuito sin tarjeta). Si EMAIL_PROVIDER está
vacío no se envía nada: el enlace queda en el registro del servidor y el administrador puede confirmar
la cuenta a mano desde la página de Administración.
"""
from __future__ import annotations

import html
import logging
from dataclasses import dataclass

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class Email:
    to: str
    subject: str
    text: str
    html: str


class EmailError(Exception):
    pass


def configured() -> bool:
    s = get_settings()
    return bool(s.email_provider and s.email_api_key and s.email_from)


def send(email: Email) -> bool:
    """Envía el correo. Devuelve False si el envío está deshabilitado; lanza EmailError si el servicio falla."""
    s = get_settings()
    if not configured():
        log.warning("Envío de correos deshabilitado (EMAIL_PROVIDER vacío). Correo para %s: %s",
                    email.to, email.text)
        return False
    provider = s.email_provider.strip().lower()
    try:
        if provider == "brevo":
            r = httpx.post("https://api.brevo.com/v3/smtp/email", timeout=15, headers={"api-key": s.email_api_key},
                           json={"sender": {"email": s.email_from, "name": s.email_from_name},
                                 "to": [{"email": email.to}], "subject": email.subject,
                                 "htmlContent": email.html, "textContent": email.text})
        elif provider == "mailjet":
            r = httpx.post("https://api.mailjet.com/v3.1/send", timeout=15,
                           auth=(s.email_api_key, s.email_api_secret),
                           json={"Messages": [{"From": {"Email": s.email_from, "Name": s.email_from_name},
                                               "To": [{"Email": email.to}], "Subject": email.subject,
                                               "TextPart": email.text, "HTMLPart": email.html}]})
        else:
            raise EmailError(f"EMAIL_PROVIDER desconocido: {s.email_provider}")
    except httpx.HTTPError as exc:
        log.exception("No se pudo contactar al servicio de correo")
        raise EmailError(str(exc)) from exc
    if r.status_code >= 300:
        log.error("El servicio de correo respondió %s: %s", r.status_code, r.text[:500])
        raise EmailError(f"El servicio de correo respondió {r.status_code}")
    return True


def _layout(title: str, intro: str, link: str, button: str, outro: str) -> tuple[str, str]:
    text = f"{title}\n\n{intro}\n\n{link}\n\n{outro}"
    body = f"""<div style="font-family:Arial,sans-serif;max-width:480px;margin:auto;color:#0f172a">
<h2 style="margin:0 0 12px">{html.escape(title)}</h2>
<p>{html.escape(intro)}</p>
<p style="margin:24px 0"><a href="{html.escape(link)}" style="background:#15803d;color:#fff;padding:10px 18px;
border-radius:8px;text-decoration:none;display:inline-block">{html.escape(button)}</a></p>
<p style="font-size:12px;color:#64748b">Si el botón no funciona, copia este enlace en tu navegador:<br>
{html.escape(link)}</p>
<p style="font-size:12px;color:#64748b">{html.escape(outro)}</p></div>"""
    return text, body


def verification_email(to: str, link: str) -> Email:
    text, body = _layout("Confirma tu correo", "Te registraste en la quiniela de Liga MX Predictor. "
                         "Confirma tu correo para empezar a jugar:", link, "Confirmar mi correo",
                         "El enlace vence en 48 horas. Si no fuiste tú, ignora este mensaje.")
    return Email(to, "Confirma tu correo · Quiniela Liga MX", text, body)


def reset_email(to: str, link: str) -> Email:
    text, body = _layout("Cambia tu contraseña", "Pediste cambiar la contraseña de tu cuenta de la quiniela. "
                         "Elige una nueva aquí:", link, "Cambiar contraseña",
                         "El enlace vence en 1 hora. Si no lo pediste, ignora este mensaje: tu contraseña no cambia.")
    return Email(to, "Cambia tu contraseña · Quiniela Liga MX", text, body)
