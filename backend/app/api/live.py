"""Marcador en vivo (GET /api/live).

Solo trabaja mientras alguien tiene la página abierta y hay un partido por empezar o en juego:
- Sin partidos en ventana no se consulta a ESPN (respuesta vacía, solo una consulta a la base de datos).
- Con partidos en ventana se pide el marcador a ESPN como mucho cada LIVE_TTL_S segundos; todas las visitas
  comparten esa misma respuesta guardada en memoria.
- Si ESPN falla o tarda, se devuelve el último dato conocido marcado como atrasado.
- Cuando ESPN da un partido por terminado (o empezado) y la base de datos aún no, se lanza la sincronización
  normal en segundo plano para que el resultado oficial y la quiniela se actualicen antes.

Nada de esto se guarda en la base: el marcador oficial a 90' y los puntos de la quiniela siguen saliendo de la
sincronización normal.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Annotated
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.db import get_sessionmaker
from app.jobs import tasks
from app.jobs.runner import run_job
from app.predict.live import elapsed_minutes, inplay_probs, remaining_fraction
from app.predict.service import latest_pre_kickoff
from app.sources.espn import LiveState, parse_live
from app.sources.http import USER_AGENT

log = logging.getLogger(__name__)

LIVE_TTL_S = 25  # una consulta a ESPN cada ~25 s como máximo, sin importar cuántas personas miren
POLL_ACTIVE_S = 30  # cada cuánto pregunta la página cuando hay partido
POLL_IDLE_S = 120
WINDOW_BEFORE = timedelta(minutes=15)  # se empieza a vigilar un poco antes del inicio
WINDOW_AFTER = timedelta(hours=3)
STALE_AFTER_S = 120  # más que esto sin poder hablar con ESPN = "dato atrasado"
DB_SYNC_MIN_INTERVAL_S = 120

router = APIRouter(tags=["en vivo"])


def _now() -> datetime:
    """Reloj del marcador en vivo (las pruebas lo sustituyen)."""
    return datetime.now(timezone.utc)


def db() -> Session:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


DB = Annotated[Session, Depends(db)]


def fetch_scoreboard(day: str | None) -> dict:
    """Una sola consulta rápida a ESPN (sin reintentos largos: en vivo vale más el siguiente intento)."""
    params = {"dates": day} if day else None
    url = f"{get_settings().espn_base_url.rstrip('/')}/scoreboard"
    resp = httpx.get(url, params=params, timeout=8.0, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    return resp.json()


class _Cache:
    def __init__(self):
        self.lock = threading.Lock()
        self.states: dict[str, LiveState] = {}
        self.checked_at = 0.0  # monotonic del último intento
        self.ok_at: datetime | None = None  # hora del último dato bueno
        self.error: str | None = None

    def reset(self):
        self.__init__()


_cache = _Cache()
_sync_lock = threading.Lock()
_last_db_sync = 0.0


def _window_matches(session: Session, now: datetime) -> list[m.Match]:
    return list(session.scalars(select(m.Match).where(or_(
        m.Match.status == m.IN_PROGRESS,
        and_(m.Match.status == m.SCHEDULED, m.Match.kickoff_utc <= now + WINDOW_BEFORE,
             m.Match.kickoff_utc >= now - WINDOW_AFTER)))))


def _refresh(matches: list[m.Match], now: datetime) -> None:
    """Pide el marcador a ESPN si el dato guardado ya caducó. Si otra visita ya lo está pidiendo, no espera."""
    if time.monotonic() - _cache.checked_at < LIVE_TTL_S and all(mt.espn_id in _cache.states for mt in matches):
        return
    if not _cache.lock.acquire(blocking=False):
        return
    try:
        _cache.checked_at = time.monotonic()
        wanted = {mt.espn_id for mt in matches}
        found: dict[str, LiveState] = {}
        # 1) El marcador "de hoy" de ESPN (sin fecha) trae los partidos en juego. 2) Si falta alguno, se pide su día.
        days: list[str | None] = [None]
        tz = ZoneInfo(get_settings().local_tz)
        for mt in matches:
            for d in (mt.kickoff_utc.astimezone(tz).strftime("%Y%m%d"), mt.kickoff_utc.strftime("%Y%m%d")):
                if d not in days:
                    days.append(d)
        errors = []
        for day in days[:4]:
            if day is not None and wanted <= set(found):
                break
            try:
                for ev in fetch_scoreboard(day).get("events") or []:
                    try:
                        st = parse_live(ev)
                    except ValueError:
                        continue
                    if st.espn_id in wanted:
                        found[st.espn_id] = st
            except Exception as exc:  # la fuente puede fallar; se conserva el último dato
                errors.append(f"{type(exc).__name__}: {exc}")
        if found:
            _cache.states.update(found)
            _cache.ok_at = now
        _cache.error = errors[0] if errors and not found else None
    finally:
        _cache.lock.release()


def _maybe_sync_db(matches: list[m.Match]) -> None:
    """Si ESPN ya ve un cambio de estado que la base aún no tiene, se adelanta la sincronización normal."""
    global _last_db_sync
    behind = False
    for mt in matches:
        st = _cache.states.get(mt.espn_id)
        if st and ((st.state == "post" and mt.status != m.FINISHED) or (st.state == "in" and mt.status == m.SCHEDULED)):
            behind = True
    if not behind:
        return
    with _sync_lock:
        if time.monotonic() - _last_db_sync < DB_SYNC_MIN_INTERVAL_S:
            return
        _last_db_sync = time.monotonic()

    def job():
        try:
            run_job("live", "api", tasks.live_sync)
        except Exception:
            log.exception("Sincronización desde el marcador en vivo falló")

    threading.Thread(target=job, daemon=True).start()


def _status_label(st: LiveState) -> str:
    name = st.source_status
    if st.state == "pre":
        return "Por empezar"
    if st.state == "post":
        return "Final"
    if name == "STATUS_HALFTIME":
        return "Medio tiempo"
    if "SHOOTOUT" in name:
        return "Penales"
    if st.period >= 3 or "EXTRA_TIME" in name or "OVERTIME" in name:
        return "Tiempo extra"
    if "END_OF_REGULATION" in name:
        return "Fin de los 90'"
    return "1er tiempo" if st.period <= 1 else "2º tiempo"


@router.get("/api/live")
def live(session: DB):
    """Marcador, minuto y probabilidad en vivo de los partidos por empezar o en juego."""
    now = _now()
    matches = _window_matches(session, now)
    if not matches:
        return {"server_time": now, "active": False, "poll_seconds": POLL_IDLE_S, "source_ok_at": _cache.ok_at,
                "stale": False, "matches": []}
    _refresh(matches, now)
    _maybe_sync_db(matches)
    preds = latest_pre_kickoff(session, [mt.id for mt in matches])
    out = []
    for mt in matches:
        st = _cache.states.get(mt.espn_id)
        if st is None:
            continue
        p = preds.get(mt.id)
        elapsed = elapsed_minutes(st.state, st.source_status, st.period, st.clock_seconds)
        live_prob = None
        if (st.state == "in" and elapsed is not None and p is not None and p.exp_home_goals is not None
                and p.exp_away_goals is not None and st.home_goals is not None and st.away_goals is not None):
            lp = inplay_probs(p.exp_home_goals, p.exp_away_goals, (p.p_home, p.p_draw, p.p_away),
                              st.home_goals, st.away_goals, remaining_fraction(st.state, st.source_status, elapsed))
            live_prob = {"p_home": round(lp.p_home, 4), "p_draw": round(lp.p_draw, 4), "p_away": round(lp.p_away, 4),
                         "top_score_home": lp.top_score_home, "top_score_away": lp.top_score_away,
                         "top_score_prob": round(lp.top_score_prob, 4), "minute": round(elapsed, 1),
                         "remaining_fraction": round(lp.remaining_fraction, 3)}
        out.append({
            "match_id": mt.id, "espn_id": mt.espn_id, "state": st.state, "status_label": _status_label(st),
            "clock": st.display_clock if st.state == "in" and st.source_status != "STATUS_HALFTIME" else None,
            "period": st.period, "home_goals": st.home_goals, "away_goals": st.away_goals,
            "home_red": st.home_red, "away_red": st.away_red, "live_prob": live_prob,
            "pregame": {"p_home": p.p_home, "p_draw": p.p_draw, "p_away": p.p_away} if p else None,
        })
    stale = _cache.ok_at is None or (now - _cache.ok_at).total_seconds() > STALE_AFTER_S
    return {"server_time": now, "active": True, "poll_seconds": POLL_ACTIVE_S, "source_ok_at": _cache.ok_at,
            "stale": stale, "source": "ESPN (API pública, no oficial)", "matches": out}
