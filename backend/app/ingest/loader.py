"""Carga idempotente de partidos en la base de datos.

Reglas:
- Un partido se identifica por su ID de ESPN; ejecutar la carga N veces no crea duplicados.
- Se guarda una copia cruda de cada versión distinta del dato (`source_records`).
- Un partido finalizado no vuelve a "en curso" ni a "programado" por una respuesta posterior de la fuente;
  se registra el problema.
- Un cambio de marcador de un partido ya finalizado se aplica (la fuente lo corrigió) y queda registrado.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app import models as m
from app.ingest.validate import Issue, has_errors, norm_name, validate_parsed
from app.sources.espn import SOURCE, ParsedMatch, ParsedTeam, parse_event, slim_event

log = logging.getLogger(__name__)

_TERMINAL = {m.FINISHED, m.CANCELED}


@dataclass
class LoadStats:
    received: int = 0
    inserted: int = 0
    updated: int = 0
    unchanged: int = 0
    rejected: int = 0
    newly_finished: list[int] = field(default_factory=list)
    status_changes: list[tuple[int, str, str]] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.inserted or self.updated)

    def as_dict(self) -> dict:
        return {
            "received": self.received, "inserted": self.inserted, "updated": self.updated,
            "unchanged": self.unchanged, "rejected": self.rejected,
            "newly_finished": self.newly_finished,
            "status_changes": [list(x) for x in self.status_changes],
        }


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def record_issue(session: Session, issue: Issue, source: str = SOURCE) -> None:
    """Inserta el problema si no existe ya (misma fuente, clave y código)."""
    stmt = pg_insert(m.DataIssue).values(
        match_id=issue.match_id, source=source, source_key=issue.source_key, severity=issue.severity,
        code=issue.code, message=issue.message, details=issue.details, created_at=m.utcnow(), resolved=False,
    ).on_conflict_do_nothing(constraint="uq_issue_per_record")
    session.execute(stmt)


def save_raw(session: Session, source: str, key: str, payload: dict) -> None:
    stmt = pg_insert(m.SourceRecord).values(
        source=source, source_key=key, payload_hash=payload_hash(payload), payload=payload, fetched_at=m.utcnow(),
    ).on_conflict_do_nothing(constraint="uq_source_record_version")
    session.execute(stmt)


def upsert_team(session: Session, pt: ParsedTeam, cache: dict[str, m.Team]) -> m.Team:
    team = cache.get(pt.espn_id) or session.scalar(select(m.Team).where(m.Team.espn_id == pt.espn_id))
    if team is None:
        team = m.Team(espn_id=pt.espn_id, name=pt.name, abbreviation=pt.abbreviation, logo_url=pt.logo_url)
        session.add(team)
        session.flush()
    else:
        # El nombre más reciente gana; el anterior se conserva como alias.
        if pt.name and pt.name != team.name:
            _add_alias(session, team, team.name)
            team.name = pt.name
        team.abbreviation = pt.abbreviation or team.abbreviation
        team.logo_url = pt.logo_url or team.logo_url
    _add_alias(session, team, pt.name)
    cache[pt.espn_id] = team
    return team


def _add_alias(session: Session, team: m.Team, name: str, source: str = SOURCE) -> None:
    key = norm_name(name)
    if not key:
        return
    stmt = pg_insert(m.TeamAlias).values(team_id=team.id, alias_key=key, alias=name, source=source)
    session.execute(stmt.on_conflict_do_nothing(index_elements=["alias_key"]))


_FIELDS = ("season", "tournament", "stage", "stage_detail", "kickoff_utc", "status", "status_detail",
           "home_goals", "away_goals", "home_goals_final", "away_goals_final", "home_penalties",
           "away_penalties", "extra_time", "live_clock")


def load_events(session: Session, events: list[dict], now: datetime | None = None) -> LoadStats:
    """Valida y carga eventos crudos de ESPN. Hace flush pero no commit."""
    now = now or datetime.now(timezone.utc)
    stats = LoadStats()
    team_cache: dict[str, m.Team] = {}
    seen: set[str] = set()
    for ev in events:
        stats.received += 1
        key = str(ev.get("id"))
        if key in seen:  # el mismo evento puede aparecer en dos días consultados
            stats.unchanged += 1
            continue
        seen.add(key)
        ev = slim_event(ev)
        save_raw(session, SOURCE, key, ev)
        try:
            pm = parse_event(ev)
        except (KeyError, ValueError, TypeError) as exc:
            stats.rejected += 1
            record_issue(session, Issue("error", "unparseable", f"No se pudo interpretar el evento: {exc}", key))
            continue
        issues = validate_parsed(pm, now)
        existing = session.scalar(select(m.Match).where(m.Match.espn_id == pm.espn_id))
        for issue in issues:
            issue.match_id = existing.id if existing else None
            record_issue(session, issue)
        if has_errors(issues):
            stats.rejected += 1
            continue
        _apply(session, pm, existing, team_cache, stats, now)
    session.flush()
    return stats


def _apply(session: Session, pm: ParsedMatch, existing: m.Match | None, team_cache: dict,
           stats: LoadStats, now: datetime) -> None:
    home = upsert_team(session, pm.home, team_cache)
    away = upsert_team(session, pm.away, team_cache)
    values = {f: getattr(pm, f) for f in _FIELDS}
    values.update(home_team_id=home.id, away_team_id=away.id)

    if existing is None:
        match = m.Match(espn_id=pm.espn_id, source=SOURCE, first_seen_at=now, updated_at=now, **values)
        if pm.status == m.FINISHED:
            match.finished_confirmed_at = now
        session.add(match)
        session.flush()
        stats.inserted += 1
        if pm.status == m.FINISHED:
            stats.newly_finished.append(match.id)
        return

    old_status = existing.status
    if old_status == m.FINISHED and pm.status in (m.SCHEDULED, m.IN_PROGRESS):
        # Nunca se "des-finaliza" un partido confirmado por una respuesta contradictoria.
        record_issue(session, Issue("warning", "status_regression",
                                    f"La fuente reporta '{pm.status}' para un partido ya finalizado; se ignora",
                                    pm.espn_id, existing.id))
        stats.unchanged += 1
        return
    if old_status == m.FINISHED and pm.status == m.FINISHED and (
            (existing.home_goals_final, existing.away_goals_final) != (pm.home_goals_final, pm.away_goals_final)):
        record_issue(session, Issue(
            "warning", "retroactive_change",
            f"La fuente corrigió el marcador de {existing.home_goals_final}-{existing.away_goals_final} "
            f"a {pm.home_goals_final}-{pm.away_goals_final}", pm.espn_id, existing.id,
            {"old": [existing.home_goals_final, existing.away_goals_final],
             "new": [pm.home_goals_final, pm.away_goals_final], "at": now.isoformat()}))

    changed = False
    for k, v in values.items():
        if getattr(existing, k) != v:
            setattr(existing, k, v)
            changed = True
    if changed:
        existing.updated_at = now
        stats.updated += 1
        if old_status != pm.status:
            stats.status_changes.append((existing.id, old_status, pm.status))
            if pm.status == m.FINISHED:
                existing.finished_confirmed_at = now
                stats.newly_finished.append(existing.id)
    else:
        stats.unchanged += 1


def assign_rounds(session: Session, tournaments: set[str] | None = None) -> int:
    """Deriva la jornada de fase regular: el n-ésimo partido de cada equipo en el torneo.

    ESPN no publica la jornada para la Liga MX. La jornada derivada es max(n_local, n_visitante), con
    partidos ordenados por fecha. Los partidos reprogramados pueden quedar en una jornada distinta a la
    oficial; se documenta como limitación.
    """
    q = select(m.Match).where(m.Match.stage == "regular", m.Match.status != m.CANCELED)
    if tournaments:
        q = q.where(m.Match.tournament.in_(tournaments))
    by_t: dict[str, list[m.Match]] = defaultdict(list)
    for match in session.scalars(q.order_by(m.Match.kickoff_utc, m.Match.id)):
        by_t[match.tournament].append(match)
    changed = 0
    for matches in by_t.values():
        count: dict[int, int] = defaultdict(int)
        for match in matches:
            count[match.home_team_id] += 1
            count[match.away_team_id] += 1
            rnd = max(count[match.home_team_id], count[match.away_team_id])
            if match.round != rnd:
                match.round = rnd
                changed += 1
    session.flush()
    return changed


# ---- estado de la aplicación -------------------------------------------------------------------------

def get_state(session: Session, key: str, default: dict | None = None) -> dict:
    row = session.get(m.AppState, key)
    return dict(row.value) if row else dict(default or {})


def set_state(session: Session, key: str, value: dict) -> None:
    stmt = pg_insert(m.AppState).values(key=key, value=value, updated_at=m.utcnow())
    stmt = stmt.on_conflict_do_update(index_elements=["key"], set_={"value": value, "updated_at": m.utcnow()})
    session.execute(stmt)


def bump_data_version(session: Session, reason: str) -> int:
    """Incrementa la versión de datos. El frontend la consulta para saber si debe refrescar."""
    state = get_state(session, "data_version", {"version": 0})
    version = int(state.get("version", 0)) + 1
    set_state(session, "data_version", {"version": version, "reason": reason, "at": m.utcnow().isoformat()})
    return version
