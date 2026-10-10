"""Tareas del sistema. Cada una recibe una sesión y devuelve estadísticas (dict)."""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m
from app.config import get_settings
from app.ingest.loader import (
    assign_rounds,
    bump_data_version,
    get_state,
    load_events,
    record_issue,
    set_state,
)
from app.ingest.validate import audit_database
from app.predict import service
from app.sources.espn import EspnClient
from app.sources.http import SourceError

__all__ = ["SourceError"]

log = logging.getLogger(__name__)


def _fetch_days(client: EspnClient, days: list[date]) -> tuple[list[dict], list[str]]:
    events, errors = [], []
    for d in days:
        try:
            events.extend(client.scoreboard(d).get("events") or [])
        except SourceError as exc:
            errors.append(f"{d.isoformat()}: {exc}")
    return events, errors


def sync(session: Session, days_back: int | None = None, days_ahead: int | None = None,
         client: EspnClient | None = None, now: datetime | None = None, predict: bool = True) -> dict:
    """Sincroniza resultados y calendario de una ventana de días alrededor de hoy.

    Si la fuente falla, los datos existentes se conservan y el error queda en las estadísticas.
    """
    s = get_settings()
    now = now or datetime.now(timezone.utc)
    client = client or EspnClient()
    back = s.sync_days_back if days_back is None else days_back
    ahead = s.sync_days_ahead if days_ahead is None else days_ahead
    today = now.date()
    days = [today + timedelta(days=i) for i in range(-back, ahead + 1)]
    events, errors = _fetch_days(client, days)
    stats = load_events(session, events, now)
    result = {"days": len(days), "source_errors": errors, **stats.as_dict()}
    if errors and not events:
        # Se conservan los datos válidos existentes; la ejecución queda marcada como fallida.
        _set_sync_state(session, now, ok=False, error=errors[0])
        result["_status"] = "failed"
        result["message"] = f"La fuente no respondió ({len(errors)} errores). Primer error: {errors[0]}"
        return result
    if stats.changed:
        tournaments = set(session.scalars(select(m.Match.tournament).where(
            m.Match.kickoff_utc >= now - timedelta(days=back + 1), m.Match.kickoff_utc <= now + timedelta(days=ahead + 1))))
        assign_rounds(session, tournaments)
        bump_data_version(session, "sync")
    if predict and (stats.changed or not session.scalar(select(m.Prediction.id).limit(1))):
        result["predictions"] = service.generate_predictions(session, now)
    _set_sync_state(session, now, ok=not errors, error=errors[0] if errors else None)
    return result


def _set_sync_state(session: Session, now: datetime, ok: bool, error: str | None) -> None:
    state = get_state(session, "sync", {})
    state["last_attempt"] = now.isoformat()
    if ok:
        state["last_success"] = now.isoformat()
        state["last_error"] = None
    else:
        state["last_error"] = error
        state["last_error_at"] = now.isoformat()
    set_state(session, "sync", state)


def live_sync(session: Session, now: datetime | None = None, client: EspnClient | None = None) -> dict:
    """Sincronización ligera para días de partido: solo ayer, hoy y mañana (3 consultas)."""
    return sync(session, days_back=1, days_ahead=1, client=client, now=now)


def backfill(session: Session, start: date, end: date, client: EspnClient | None = None,
             now: datetime | None = None) -> dict:
    """Descarga histórica día por día (idempotente: se puede repetir o reanudar sin duplicar)."""
    now = now or datetime.now(timezone.utc)
    client = client or EspnClient()
    total = {"days": 0, "received": 0, "inserted": 0, "updated": 0, "rejected": 0, "source_errors": []}
    day = start
    while day <= end:
        chunk_end = min(day + timedelta(days=30), end)
        days = [day + timedelta(days=i) for i in range((chunk_end - day).days + 1)]
        events, errors = _fetch_days(client, days)
        st = load_events(session, events, now)
        session.commit()  # por bloques: si se interrumpe, lo cargado se conserva
        total["days"] += len(days)
        for k in ("received", "inserted", "updated", "rejected"):
            total[k] += getattr(st, k)
        total["source_errors"].extend(errors)
        log.info("Histórico %s → %s: %s", day, chunk_end, st.as_dict())
        day = chunk_end + timedelta(days=1)
    assign_rounds(session)
    for issue in audit_database(session):
        record_issue(session, issue, source="audit")
    bump_data_version(session, "backfill")
    total["source_errors"] = total["source_errors"][:50]
    return total


def maintenance(session: Session, now: datetime | None = None, force_retrain: bool = False) -> dict:
    """Tarea diaria: auditoría, reentrenamiento según la política y predicciones pendientes."""
    now = now or datetime.now(timezone.utc)
    out: dict = {}
    issues = audit_database(session)
    for issue in issues:
        record_issue(session, issue, source="audit")
    out["audit_issues"] = len(issues)
    retrain, reason = service.needs_retrain(session, now)
    out["retrain_reason"] = reason
    if (retrain or force_retrain) and service.latest_backtest(session) is not None:
        mv = service.train_production(session, now)
        out["trained"] = mv.version
        bump_data_version(session, "retrain")
    elif service.latest_backtest(session) is None:
        out["trained"] = None
        out["message"] = "Sin backtesting todavía: ejecuta la tarea 'backtest'"
    out["predictions"] = service.generate_predictions(session, now)
    if out["predictions"].get("created"):
        bump_data_version(session, "predictions")
    return out


def backtest(session: Session, now: datetime | None = None) -> dict:
    run = service.run_and_store_backtest(session)
    session.flush()
    mv = service.train_production(session, now)
    out = {"backtest_run": run.id, "selected_model": run.selected_model, "trained": mv.version}
    out["predictions"] = service.generate_predictions(session, now)
    bump_data_version(session, "backtest")
    return out


def crosscheck(session: Session, csv_text: str | None = None) -> dict:
    """Compara marcadores de ESPN con Football-Data.co.uk y registra discrepancias (no corrige nada)."""
    from app.ingest.validate import Issue, name_similarity
    from app.sources import football_data as fd

    text_ = csv_text if csv_text is not None else fd.fetch()
    rows, problems = fd.parse_csv(text_)
    start = date.fromisoformat(get_settings().history_start)
    rows = [r for r in rows if r.day >= start and r.hg is not None]
    finished = session.scalars(select(m.Match).where(m.Match.status == m.FINISHED)).all()
    names: dict[int, list[str]] = {}
    for alias in session.scalars(select(m.TeamAlias)):
        names.setdefault(alias.team_id, []).append(alias.alias)
    by_day: dict[date, list[m.Match]] = {}
    for match in finished:
        by_day.setdefault(match.kickoff_utc.date(), []).append(match)

    def sim(fd_name: str, team_id: int) -> float:
        return max((name_similarity(fd_name, n) for n in names.get(team_id, [])), default=0.0)

    matched = mismatched = unmatched = 0
    for r in rows:
        cands = [mm for d in (r.day - timedelta(days=1), r.day, r.day + timedelta(days=1)) for mm in by_day.get(d, [])]
        scored = sorted(((sim(r.home, c.home_team_id) + sim(r.away, c.away_team_id), c) for c in cands),
                        key=lambda t: -t[0])
        if not scored or scored[0][0] < 1.0 or (len(scored) > 1 and scored[0][0] - scored[1][0] < 0.15):
            unmatched += 1
            continue
        match = scored[0][1]
        matched += 1
        espn_scores = {(match.home_goals_final, match.away_goals_final), (match.home_goals, match.away_goals)}
        if (r.hg, r.ag) not in espn_scores:
            mismatched += 1
            record_issue(session, Issue(
                "warning", "crosscheck_mismatch",
                f"ESPN {match.home_goals_final}-{match.away_goals_final} vs Football-Data {r.hg}-{r.ag} "
                f"({r.home} - {r.away}, {r.day.isoformat()})",
                source_key=match.espn_id, match_id=match.id,
                details={"football_data": [r.hg, r.ag], "espn_final": [match.home_goals_final, match.away_goals_final],
                         "espn_90": [match.home_goals, match.away_goals]}), source=fd.SOURCE)
    set_state(session, "crosscheck", {"at": datetime.now(timezone.utc).isoformat(), "rows": len(rows),
                                      "matched": matched, "mismatched": mismatched, "unmatched": unmatched})
    return {"rows": len(rows), "matched": matched, "mismatched": mismatched, "unmatched": unmatched,
            "parse_problems": problems[:20]}
