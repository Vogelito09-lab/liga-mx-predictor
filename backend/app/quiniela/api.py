"""Rutas de la quiniela: cuentas (/api/auth) y juego (/api/quiniela).

La sesión viaja en el encabezado Authorization: Bearer <token>. El navegador guarda el token; la base de
datos solo guarda su hash. Las cookies no sirven aquí porque la página y la API están en dominios distintos
de onrender.com (que los navegadores tratan como sitios separados).
"""
from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.db import get_sessionmaker
from app.predict.standings import current_tournament
from app.quiniela import mailer
from app.quiniela import security as sec
from app.quiniela import service as q

log = logging.getLogger(__name__)

SESSION_DAYS = 60
VERIFY_HOURS = 48
RESET_HOURS = 1


def _now() -> datetime:
    """Reloj de la quiniela (las pruebas lo sustituyen)."""
    return datetime.now(timezone.utc)


def db() -> Session:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


DB = Annotated[Session, Depends(db)]


# ---------------------------------------------------------------------------------------------------
# Límite de intentos (en memoria; suficiente para un solo servidor)
# ---------------------------------------------------------------------------------------------------
class RateLimiter:
    def __init__(self, limit: int, window_s: int):
        self.limit, self.window = limit, window_s
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self.lock:
            d = self.hits[key]
            while d and now - d[0] > self.window:
                d.popleft()
            if len(d) >= self.limit:
                raise HTTPException(429, "Demasiados intentos. Espera unos minutos y vuelve a intentar.")
            d.append(now)

    def reset(self) -> None:
        with self.lock:
            self.hits.clear()


login_limiter = RateLimiter(10, 15 * 60)   # intentos de inicio de sesión por correo
email_limiter = RateLimiter(3, 15 * 60)    # correos enviados por dirección
signup_limiter = RateLimiter(20, 60 * 60)  # registros por IP


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() or (request.client.host if request.client else "?")


# ---------------------------------------------------------------------------------------------------
# Sesión
# ---------------------------------------------------------------------------------------------------
def _session_user(session: Session, authorization: str | None) -> m.User | None:
    token = (authorization or "").removeprefix("Bearer ").strip()
    if not token:
        return None
    row = session.scalar(select(m.UserSession).where(m.UserSession.token_hash == sec.token_hash(token)))
    if row is None or row.expires_at <= _now() or row.user.approved_at is None:
        return None
    return row.user


def optional_user(session: DB, authorization: Annotated[str | None, Header()] = None) -> m.User | None:
    return _session_user(session, authorization)


def current_user(session: DB, authorization: Annotated[str | None, Header()] = None) -> m.User:
    user = _session_user(session, authorization)
    if user is None:
        raise HTTPException(401, "Inicia sesión para continuar")
    return user


def player(user: Annotated[m.User, Depends(current_user)]) -> m.User:
    if user.display_name is None:
        raise HTTPException(409, "Primero elige tu nombre para la quiniela")
    return user


CurrentUser = Annotated[m.User, Depends(current_user)]
OptionalUser = Annotated[m.User | None, Depends(optional_user)]
Player = Annotated[m.User, Depends(player)]


def _start_session(session: Session, user: m.User) -> str:
    token, digest = sec.new_token()
    now = _now()
    session.add(m.UserSession(user_id=user.id, token_hash=digest, created_at=now,
                              expires_at=now + timedelta(days=SESSION_DAYS)))
    session.execute(delete(m.UserSession).where(m.UserSession.user_id == user.id, m.UserSession.expires_at <= now))
    user.last_login_at = now
    return token


def crest_out(t: m.Team | None) -> dict | None:
    return {"team_id": t.id, "name": t.name, "logo_url": t.logo_url} if t else None


def user_out(u: m.User) -> dict:
    return {"id": u.id, "email": u.email, "display_name": u.display_name,
            "email_verified": u.email_verified_at is not None, "approved": u.approved_at is not None,
            "crest": crest_out(u.crest_team)}


def _check_crest(session: Session, team_id: int | None) -> int | None:
    if team_id is None:
        return None
    if session.get(m.Team, team_id) is None:
        raise HTTPException(422, "Ese escudo no existe")
    return team_id


def _check_can_enter(user: m.User) -> None:
    """Para entrar: aprobado por el administrador y, si hay servicio de correo, con el correo confirmado."""
    if mailer.configured() and user.email_verified_at is None and user.approved_at is None:
        raise HTTPException(403, "Todavía no confirmas tu correo. Busca el mensaje que te mandamos "
                                 "(revisa también spam) o pide uno nuevo.")
    if user.approved_at is None:
        raise HTTPException(423, "Tu solicitud está esperando que el administrador la apruebe. "
                                 "Vuelve a intentar más tarde.")


def _check_name(session: Session, name: str, user_id: int | None = None) -> tuple[str, str]:
    name = sec.clean_display_name(name)
    if problem := sec.display_name_problem(name):
        raise HTTPException(422, problem)
    key = sec.display_name_key(name)
    if key == sec.display_name_key(q.MODEL_NAME) or key.startswith("modelo"):
        raise HTTPException(409, "Ese nombre está reservado")
    taken = select(m.User.id).where(m.User.display_name_key == key)
    if user_id is not None:
        taken = taken.where(m.User.id != user_id)
    if session.scalar(taken):
        raise HTTPException(409, "Ese nombre ya lo usa otra persona. Elige otro.")
    return name, key


def _send_link(session: Session, user: m.User, purpose: str) -> bool:
    """Crea un enlace de un solo uso y lo envía. Devuelve si el correo salió."""
    email_limiter.check(f"{purpose}:{user.email}")
    now = _now()
    # Los enlaces anteriores del mismo tipo dejan de servir.
    session.execute(delete(m.EmailToken).where(m.EmailToken.user_id == user.id, m.EmailToken.purpose == purpose,
                                               m.EmailToken.used_at.is_(None)))
    token, digest = sec.new_token()
    hours = VERIFY_HOURS if purpose == "verify" else RESET_HOURS
    session.add(m.EmailToken(user_id=user.id, purpose=purpose, token_hash=digest, created_at=now,
                             expires_at=now + timedelta(hours=hours)))
    session.commit()
    web = get_settings().public_web_url
    path = "confirmar" if purpose == "verify" else "restablecer"
    link = f"{web}/quiniela/{path}?token={token}"
    email = (mailer.verification_email if purpose == "verify" else mailer.reset_email)(user.email, link)
    try:
        return mailer.send(email)
    except mailer.EmailError:
        return False


def _use_link(session: Session, token: str, purpose: str) -> m.User:
    row = session.scalar(select(m.EmailToken).where(m.EmailToken.token_hash == sec.token_hash(token.strip()),
                                                    m.EmailToken.purpose == purpose))
    if row is None or row.used_at is not None:
        raise HTTPException(400, "El enlace no es válido o ya se usó. Pide uno nuevo.")
    if row.expires_at <= _now():
        raise HTTPException(400, "El enlace venció. Pide uno nuevo.")
    row.used_at = _now()
    return row.user


# ---------------------------------------------------------------------------------------------------
# Cuentas
# ---------------------------------------------------------------------------------------------------
auth = APIRouter(prefix="/api/auth", tags=["cuentas"])


class RegisterIn(BaseModel):
    display_name: str = Field(max_length=60)
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)
    invite_code: str = Field("", max_length=100)
    crest_team_id: int | None = None


class LoginIn(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=200)


class EmailIn(BaseModel):
    email: str = Field(max_length=254)


class TokenIn(BaseModel):
    token: str = Field(max_length=200)


class ResetIn(BaseModel):
    token: str = Field(max_length=200)
    password: str = Field(max_length=200)


class ProfileIn(BaseModel):
    """Solo se cambian los campos que se envían."""
    display_name: str | None = Field(None, max_length=60)
    crest_team_id: int | None = None


class PasswordChangeIn(BaseModel):
    current_password: str = Field(max_length=200)
    new_password: str = Field(max_length=200)


@auth.get("/config")
def auth_config():
    s = get_settings()
    return {"registration_open": s.quiniela_registration_open, "invite_code_required": bool(s.quiniela_invite_code),
            "email_enabled": mailer.configured()}


@auth.post("/register", status_code=201)
def register(body: RegisterIn, session: DB, request: Request):
    """Solicitud para jugar. Queda pendiente hasta que el administrador la aprueba."""
    s = get_settings()
    if not s.quiniela_registration_open:
        raise HTTPException(503, "Por ahora no se aceptan solicitudes nuevas")
    signup_limiter.check(_ip(request))
    if s.quiniela_invite_code and not sec.same_secret(body.invite_code, s.quiniela_invite_code):
        raise HTTPException(403, "El código de invitación no es correcto")
    email = sec.normalize_email(body.email)
    if not sec.valid_email(email):
        raise HTTPException(422, "Escribe un correo válido")
    if problem := sec.password_problem(body.password):
        raise HTTPException(422, problem)
    name, key = _check_name(session, body.display_name)
    crest = _check_crest(session, body.crest_team_id)
    if session.scalar(select(m.User.id).where(m.User.email == email)):
        raise HTTPException(409, "Ese correo ya está registrado. Inicia sesión o recupera tu contraseña.")
    user = m.User(email=email, password_hash=sec.hash_password(body.password), display_name=name,
                  display_name_key=key, crest_team_id=crest, created_at=_now())
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Ese correo o ese nombre ya están registrados.")
    sent = _send_link(session, user, "verify") if mailer.configured() else False
    message = "Listo, tu solicitud le llegó al administrador. Podrás entrar cuando te apruebe."
    if sent:
        message += " Mientras, confirma tu correo con el enlace que te mandamos (revisa también spam)."
    return {"ok": True, "email_sent": sent, "message": message}


@auth.post("/resend-verification")
def resend_verification(body: EmailIn, session: DB):
    user = session.scalar(select(m.User).where(m.User.email == sec.normalize_email(body.email)))
    sent = False
    if user is not None and user.email_verified_at is None:
        sent = _send_link(session, user, "verify")
    return {"ok": True, "email_sent": sent,
            "message": "Si ese correo está registrado y sin confirmar, te mandamos un enlace nuevo."}


@auth.post("/verify")
def verify(body: TokenIn, session: DB):
    user = _use_link(session, body.token, "verify")
    user.email_verified_at = user.email_verified_at or _now()
    if user.approved_at is None:  # confirmado, pero todavía falta la aprobación
        session.commit()
        return {"token": None, "user": user_out(user)}
    token = _start_session(session, user)
    session.commit()
    return {"token": token, "user": user_out(user)}


@auth.post("/login")
def login(body: LoginIn, session: DB):
    email = sec.normalize_email(body.email)
    login_limiter.check(email)
    user = session.scalar(select(m.User).where(m.User.email == email))
    if user is None or not sec.verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Correo o contraseña incorrectos")
    _check_can_enter(user)
    token = _start_session(session, user)
    session.commit()
    return {"token": token, "user": user_out(user)}


@auth.post("/logout")
def logout(session: DB, authorization: Annotated[str | None, Header()] = None):
    token = (authorization or "").removeprefix("Bearer ").strip()
    if token:
        session.execute(delete(m.UserSession).where(m.UserSession.token_hash == sec.token_hash(token)))
        session.commit()
    return {"ok": True}


@auth.get("/me")
def me(user: CurrentUser):
    return user_out(user)


@auth.put("/me")
def update_profile(body: ProfileIn, user: CurrentUser, session: DB):
    if body.display_name is not None:
        name, key = _check_name(session, body.display_name, user.id)
        user.display_name, user.display_name_key = name, key
    if "crest_team_id" in body.model_fields_set:
        user.crest_team_id = _check_crest(session, body.crest_team_id)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Ese nombre ya lo usa otra persona. Elige otro.")
    return user_out(user)


@auth.get("/crests")
def crests(session: DB):
    """Escudos para elegir: los equipos del torneo en curso."""
    t = current_tournament(session)
    q_ = select(m.Team).order_by(m.Team.name)
    if t:
        ids = select(m.Match.home_team_id).where(m.Match.tournament == t).union(
            select(m.Match.away_team_id).where(m.Match.tournament == t))
        q_ = q_.where(m.Team.id.in_(ids))
    return [crest_out(team) for team in session.scalars(q_)]


@auth.post("/change-password")
def change_password(body: PasswordChangeIn, user: CurrentUser, session: DB,
                    authorization: Annotated[str | None, Header()] = None):
    if not sec.verify_password(body.current_password, user.password_hash):
        raise HTTPException(403, "La contraseña actual no es correcta")
    if problem := sec.password_problem(body.new_password):
        raise HTTPException(422, problem)
    user.password_hash = sec.hash_password(body.new_password)
    # Se cierran las demás sesiones abiertas; la actual sigue.
    current = sec.token_hash((authorization or "").removeprefix("Bearer ").strip())
    session.execute(delete(m.UserSession).where(m.UserSession.user_id == user.id,
                                                m.UserSession.token_hash != current))
    session.commit()
    return {"ok": True}


@auth.post("/forgot-password")
def forgot_password(body: EmailIn, session: DB):
    user = session.scalar(select(m.User).where(m.User.email == sec.normalize_email(body.email)))
    sent = _send_link(session, user, "reset") if user is not None else False
    if user is None:
        email_limiter.check(f"reset:{sec.normalize_email(body.email)}")
    return {"ok": True, "email_enabled": mailer.configured(), "email_sent": sent,
            "message": "Si ese correo está registrado, te mandamos un enlace para cambiar tu contraseña."}


@auth.post("/reset-password")
def reset_password(body: ResetIn, session: DB):
    if problem := sec.password_problem(body.password):
        raise HTTPException(422, problem)
    user = _use_link(session, body.token, "reset")
    user.password_hash = sec.hash_password(body.password)
    user.email_verified_at = user.email_verified_at or _now()  # recibió el enlace: el correo es suyo
    session.execute(delete(m.UserSession).where(m.UserSession.user_id == user.id))
    token = _start_session(session, user) if user.approved_at is not None else None
    session.commit()
    return {"token": token, "user": user_out(user)}


# ---------------------------------------------------------------------------------------------------
# Juego
# ---------------------------------------------------------------------------------------------------
game = APIRouter(prefix="/api/quiniela", tags=["quiniela"])


def _tournament(session: Session, tournament: str | None) -> str:
    t = tournament or current_tournament(session)
    if t is None:
        raise HTTPException(404, "Aún no hay partidos")
    return t


def _team(t: m.Team) -> dict:
    return {"id": t.id, "name": t.name, "abbreviation": t.abbreviation, "logo_url": t.logo_url}


def _match(mt: m.Match) -> dict:
    return {"id": mt.id, "kickoff_utc": mt.kickoff_utc, "status": mt.status, "status_detail": mt.status_detail,
            "live_clock": mt.live_clock, "stage": mt.stage, "stage_detail": mt.stage_detail, "round": mt.round,
            "home": _team(mt.home_team), "away": _team(mt.away_team), "home_goals": mt.home_goals,
            "away_goals": mt.away_goals, "home_goals_final": mt.home_goals_final,
            "away_goals_final": mt.away_goals_final, "extra_time": mt.extra_time}


@game.get("/jornadas")
def jornadas(session: DB, user: OptionalUser, tournament: str | None = None):
    """Jornadas del torneo, cuál está en juego y cuántos partidos te faltan por pronosticar."""
    t = _tournament(session, tournament)
    now = _now()
    groups = q.group_jornadas(q.tournament_matches(session, t))
    mine = q.user_picks(session, [mt.id for _, ms in groups for mt in ms], [user.id]) if user else {}
    out = []
    for j, ms in groups:
        open_ms = [mt for mt in ms if not q.is_locked(mt, now)]
        out.append({"key": j.key, "label": j.label, "liguilla": j.liguilla, "matches": len(ms),
                    "open_matches": len(open_ms), "first_kickoff": ms[0].kickoff_utc,
                    "last_kickoff": ms[-1].kickoff_utc, "finished": all(q.is_scored(mt) for mt in ms),
                    "missing_picks": sum((user.id, mt.id) not in mine for mt in open_ms) if user else None})
    seasons = session.execute(select(m.Match.tournament).group_by(m.Match.tournament)
                              .order_by(func.min(m.Match.kickoff_utc).desc()).limit(6)).scalars().all()
    return {"tournament": t, "tournaments": list(seasons), "current": q.current_jornada_key(groups, now),
            "liguilla_multiplier": max(1, get_settings().quiniela_liguilla_multiplier), "jornadas": out}


@game.get("/jornadas/{key}")
def jornada_detail(key: str, session: DB, user: OptionalUser, tournament: str | None = None):
    """Partidos de una jornada con tu pronóstico, el del modelo y, ya iniciado cada partido, los de todos."""
    t = _tournament(session, tournament)
    now = _now()
    groups = {j.key: (j, ms) for j, ms in q.group_jornadas(q.tournament_matches(session, t))}
    if key not in groups:
        raise HTTPException(404, "Jornada no encontrada")
    j, ms = groups[key]
    ids = [mt.id for mt in ms]
    users = q.participants(session)
    picks = q.user_picks(session, ids)
    bot = q.model_picks(session, ids)
    names = {u.id: u.display_name for u in users}
    crest_urls = {u.id: u.crest_team.logo_url if u.crest_team else None for u in users}
    items = []
    for mt in ms:
        locked = q.is_locked(mt, now)
        mine = picks.get((user.id, mt.id)) if user else None
        model = bot.get(mt.id)
        others = []
        if locked:  # los pronósticos de los demás solo se ven cuando el partido ya empezó
            for (uid, mid), p in picks.items():
                if mid == mt.id and uid in names:
                    res = q.score_match(mt, p.home_goals, p.away_goals)
                    others.append({"display_name": names[uid], "crest_url": crest_urls[uid],
                                   "is_me": bool(user and uid == user.id),
                                   "home": p.home_goals, "away": p.away_goals,
                                   "points": res[0] if res else None, "kind": res[1] if res else None})
            others.sort(key=lambda o: o["display_name"].lower())
        my_res = q.score_match(mt, mine.home_goals, mine.away_goals) if mine else None
        model_res = q.score_match(mt, *model) if model else None
        items.append({
            "match": _match(mt), "locked": locked, "scored": q.is_scored(mt), "multiplier": q.multiplier_for(mt),
            "my_pick": {"home": mine.home_goals, "away": mine.away_goals, "points": my_res[0] if my_res else None,
                        "kind": my_res[1] if my_res else None} if mine else None,
            "model_pick": {"home": model[0], "away": model[1], "points": model_res[0] if model_res else None,
                           "kind": model_res[1] if model_res else None} if model else None,
            "picks": others,
        })
    return {"tournament": t, "key": key, "label": j.label, "liguilla": j.liguilla, "items": items}


class PickIn(BaseModel):
    match_id: int
    home_goals: int = Field(ge=0, le=20)
    away_goals: int = Field(ge=0, le=20)


class PicksIn(BaseModel):
    picks: list[PickIn] = Field(max_length=60)


@game.put("/picks")
def save_picks(body: PicksIn, user: Player, session: DB):
    """Guarda o cambia pronósticos. Los partidos que ya empezaron se rechazan uno por uno."""
    now = _now()
    ids = [p.match_id for p in body.picks]
    matches = {mt.id: mt for mt in session.scalars(select(m.Match).where(m.Match.id.in_(ids)))} if ids else {}
    existing = q.user_picks(session, ids, [user.id])
    saved, rejected = [], []
    for p in body.picks:
        mt = matches.get(p.match_id)
        if mt is None or q.jornada_of(mt) is None:
            rejected.append({"match_id": p.match_id, "reason": "Partido no encontrado"})
            continue
        if q.is_locked(mt, now):
            rejected.append({"match_id": p.match_id, "reason": "El partido ya empezó; no se puede cambiar"})
            continue
        row = existing.get((user.id, mt.id))
        if row is None:
            session.add(m.QuinielaPick(user_id=user.id, match_id=mt.id, home_goals=p.home_goals,
                                       away_goals=p.away_goals, created_at=now, updated_at=now))
        elif (row.home_goals, row.away_goals) != (p.home_goals, p.away_goals):
            row.home_goals, row.away_goals, row.updated_at = p.home_goals, p.away_goals, now
        saved.append(p.match_id)
    try:
        session.commit()
    except IntegrityError:  # doble clic: el mismo pronóstico llegó dos veces al mismo tiempo
        session.rollback()
        raise HTTPException(409, "Se guardó otro cambio al mismo tiempo. Vuelve a intentar.")
    return {"saved": saved, "rejected": rejected}


@game.get("/tablas")
def tables(session: DB, tournament: str | None = None):
    """Tabla de cada jornada y tabla general acumulada."""
    t = _tournament(session, tournament)
    return q.build_tables(session, t, _now())


# ---------------------------------------------------------------------------------------------------
# Administración de usuarios (mismo token que el resto de /api/admin)
# ---------------------------------------------------------------------------------------------------
def _require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    from app.api.main import require_admin  # import tardío: main incluye este módulo

    require_admin(authorization)


admin = APIRouter(prefix="/api/admin/quiniela", tags=["admin"], dependencies=[Depends(_require_admin)])


@admin.get("/users")
def admin_users(session: DB):
    counts = dict(session.execute(select(m.QuinielaPick.user_id, func.count()).group_by(m.QuinielaPick.user_id)).all())
    users = session.scalars(select(m.User).order_by(m.User.created_at.desc())).all()
    return {"email_enabled": mailer.configured(),
            "registration_open": get_settings().quiniela_registration_open,
            "pending": sum(u.approved_at is None for u in users),
            "items": [{**user_out(u), "created_at": u.created_at, "last_login_at": u.last_login_at,
                       "picks": counts.get(u.id, 0)} for u in users]}


@admin.post("/users/{user_id}/approve")
def admin_approve(user_id: int, session: DB):
    """Aprueba una solicitud. El administrador responde por la persona, así que su correo cuenta como confirmado."""
    user = session.get(m.User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    now = _now()
    user.approved_at = user.approved_at or now
    user.email_verified_at = user.email_verified_at or now
    session.commit()
    return user_out(user)


@admin.post("/users/{user_id}/link")
def admin_link(user_id: int, session: DB):
    """Enlace para cambiar la contraseña, para mandarlo a mano (p. ej. por WhatsApp) si no hay correo."""
    user = session.get(m.User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    session.execute(delete(m.EmailToken).where(m.EmailToken.user_id == user.id, m.EmailToken.purpose == "reset",
                                               m.EmailToken.used_at.is_(None)))
    token, digest = sec.new_token()
    now = _now()
    session.add(m.EmailToken(user_id=user.id, purpose="reset", token_hash=digest, created_at=now,
                             expires_at=now + timedelta(hours=24)))
    session.commit()
    return {"link": f"{get_settings().public_web_url}/quiniela/restablecer?token={token}", "expires_hours": 24}


@admin.post("/users/{user_id}/reject")
@admin.post("/users/{user_id}/delete")
def admin_delete(user_id: int, session: DB):
    user = session.get(m.User, user_id)
    if user is None:
        raise HTTPException(404, "Usuario no encontrado")
    session.execute(delete(m.QuinielaPick).where(m.QuinielaPick.user_id == user_id))
    session.delete(user)
    session.commit()
    return {"ok": True}
