"""Validaciones de calidad de datos.

Las validaciones nunca borran registros: devuelven problemas que se guardan en `data_issues`
para revisarlos desde el panel de administración.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app import models as m
from app.sources.espn import ParsedMatch, strip_accents

MAX_GOALS = 15


@dataclass
class Issue:
    severity: str  # info | warning | error
    code: str
    message: str
    source_key: str | None = None
    match_id: int | None = None
    details: dict | None = None


def validate_parsed(pm: ParsedMatch, now: datetime | None = None) -> list[Issue]:
    """Validación de un registro recibido. Si hay un error, el registro no se carga."""
    now = now or datetime.now(timezone.utc)
    out = [Issue(sev, code, msg, pm.espn_id) for sev, code, msg in pm.issues]

    def err(code: str, msg: str):
        out.append(Issue("error", code, msg, pm.espn_id))

    if not pm.espn_id:
        err("missing_id", "Partido sin identificador")
    if not pm.home.espn_id or not pm.away.espn_id or pm.home.espn_id == "None" or pm.away.espn_id == "None":
        err("missing_team", "Falta el identificador de un equipo")
    if pm.home.espn_id == pm.away.espn_id:
        err("same_team", "Local y visitante son el mismo equipo")
    if pm.status not in m.MATCH_STATUSES:
        err("bad_status", f"Estado desconocido: {pm.status}")
    if not (datetime(2000, 1, 1, tzinfo=timezone.utc) <= pm.kickoff_utc <= now + timedelta(days=730)):
        err("bad_date", f"Fecha fuera de rango: {pm.kickoff_utc.isoformat()}")
    for label, val in (("local", pm.home_goals_final), ("visitante", pm.away_goals_final),
                       ("local 90'", pm.home_goals), ("visitante 90'", pm.away_goals)):
        if val is not None and not (0 <= val <= MAX_GOALS):
            err("bad_score", f"Goles {label} inválidos: {val}")
    if pm.status == m.FINISHED and (pm.home_goals_final is None or pm.away_goals_final is None):
        err("finished_without_score", "Partido finalizado sin marcador confirmado")
    if pm.status == m.FINISHED and pm.kickoff_utc > now + timedelta(hours=1):
        err("finished_in_future", "La fuente marca como finalizado un partido que aún no empieza")
    if (pm.home_goals is not None and pm.home_goals_final is not None
            and (pm.home_goals > pm.home_goals_final or pm.away_goals > pm.away_goals_final)):
        err("contradictory_score", "El marcador a 90' supera al marcador final")
    if pm.status == m.SCHEDULED and pm.kickoff_utc < now - timedelta(hours=6):
        out.append(Issue("warning", "stale_scheduled",
                         "Partido programado en el pasado sin resultado: puede estar reprogramado", pm.espn_id))
    return out


def has_errors(issues: list[Issue]) -> bool:
    return any(i.severity == "error" for i in issues)


def norm_name(name: str) -> str:
    s = strip_accents(name.lower())
    for junk in ("club ", "deportivo ", "f.c.", " fc", "c.f.", "cf ", "."):
        s = s.replace(junk, " ")
    return " ".join(s.split())


def name_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, norm_name(a), norm_name(b)).ratio()


def audit_database(session: Session) -> list[Issue]:
    """Comprobaciones globales tras una carga: duplicados, finalizados sin marcador, equipos parecidos."""
    out: list[Issue] = []

    # Mismo enfrentamiento con dos IDs distintos a menos de 36 h → posible duplicado.
    a, b = aliased(m.Match), aliased(m.Match)
    rows = session.execute(
        select(a.id, b.id, a.kickoff_utc, b.kickoff_utc)
        .where(a.id < b.id, a.home_team_id == b.home_team_id, a.away_team_id == b.away_team_id,
               a.status != m.CANCELED, b.status != m.CANCELED)
    ).all()
    for ida, idb, ka, kb in rows:
        if abs((ka - kb).total_seconds()) < 36 * 3600:
            out.append(Issue("warning", "possible_duplicate", f"Partidos {ida} y {idb} parecen el mismo encuentro",
                             source_key=f"dup-{ida}-{idb}", match_id=idb))

    for match in session.scalars(select(m.Match).where(m.Match.status == m.FINISHED,
                                                       m.Match.home_goals_final.is_(None))):
        out.append(Issue("error", "finished_without_score", "Finalizado sin marcador", source_key=match.espn_id,
                         match_id=match.id))

    teams = session.scalars(select(m.Team)).all()
    for i, t1 in enumerate(teams):
        for t2 in teams[i + 1:]:
            if name_similarity(t1.name, t2.name) > 0.92:
                out.append(Issue("warning", "similar_team_names",
                                 f"Equipos con nombres casi iguales: '{t1.name}' y '{t2.name}'",
                                 source_key=f"team-{t1.id}-{t2.id}"))
    return out
