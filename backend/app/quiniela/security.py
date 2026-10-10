"""Contraseñas, tokens de sesión y enlaces de un solo uso (solo biblioteca estándar).

- Contraseñas: scrypt con sal aleatoria por usuario. Nunca se guarda la contraseña ni se puede recuperar.
- Tokens (sesión y enlaces de correo): 32 bytes aleatorios; en la base de datos solo se guarda su SHA-256,
  así que una copia de la base de datos no permite entrar a ninguna cuenta.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import unicodedata

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
MIN_PASSWORD = 8
MAX_PASSWORD = 128

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
NAME_RE = re.compile(r"^[\w .\-]+$")  # \w incluye letras con acento y ñ
NAME_MIN, NAME_MAX = 3, 20


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        calc = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(digest)))
        return hmac.compare_digest(calc, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


def new_token() -> tuple[str, str]:
    """Devuelve (token para el usuario, hash para guardar)."""
    token = secrets.token_urlsafe(32)
    return token, token_hash(token)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().lower()


def valid_email(email: str) -> bool:
    return len(email) <= 254 and bool(EMAIL_RE.match(email))


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD:
        return f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres"
    if len(password) > MAX_PASSWORD:
        return f"La contraseña debe tener como máximo {MAX_PASSWORD} caracteres"
    return None


def clean_display_name(name: str) -> str:
    return " ".join(name.split())


def display_name_key(name: str) -> str:
    """Clave para comparar nombres: sin acentos, minúsculas y sin espacios repetidos."""
    base = unicodedata.normalize("NFKD", clean_display_name(name)).encode("ascii", "ignore").decode()
    return base.lower()


def display_name_problem(name: str) -> str | None:
    if not NAME_MIN <= len(name) <= NAME_MAX:
        return f"El nombre debe tener entre {NAME_MIN} y {NAME_MAX} caracteres"
    if not NAME_RE.match(name) or "_" in name:
        return "Usa solo letras, números, espacios, puntos o guiones"
    return None


def same_secret(given: str, expected: str) -> bool:
    """Compara el código de invitación sin distinguir mayúsculas ni espacios alrededor."""
    return hmac.compare_digest(given.strip().lower().encode(), expected.strip().lower().encode())
