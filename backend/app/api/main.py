"""API REST de Liga MX Predictor. Documentación interactiva en /docs."""
from __future__ import annotations

import hmac
import logging
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app import models as m
from app.api.schemas import MatchOut, Paginated, PredictionOut, StatusOut, TeamOut
from app.config import get_settings
from app.db import get_sessionmaker
from app.features.build import FeatureParams, build_features
from app.ingest.loader import get_state
from app.jobs import tasks
from app.jobs.runner import run_job
from app.predict.data import load_matches_df
from app.predict.service import active_model, latest_backtest

log = logging.getLogger(__name__)
settings = get_settings()

app = FastAPI(
    title="Liga MX Predictor API",
    version="1.0.0",
    description="Predicciones probabilísticas de la Liga MX. Las predicciones expresan incertidumbre: "
                "no son resultados garantizados. Datos de partidos: ESPN (API pública).",
)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["GET", "POST"],
                   allow_headers=["Authorization", "Content-Type"])

OUTCOMES = ["local", "empate", "visitante"]


def _now() -> datetime:
    """Reloj de la API (las pruebas lo sustituyen para simular el paso del tiempo)."""
    return datetime.now(timezone.utc)


def db() -> Session:
    s = get_sessionmaker()()
    try:
        yield s
    finally:
        s.close()


DB = Annotated[Session, Depends(db)]


def require_admin(authorization: Annotated[str | None, Header()] = None) -> None:
    token = settings.admin_token
    if not token:
        raise HTTPException(503, "Administración deshabilitada: define ADMIN_TOKEN en el servidor")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise HTTPException(401, "Token de administración inválido")


# ---------------------------------------------------------------------------------------------------
# Serialización
# ---------------------------------------------------------------------------------------------------
def team_out(t: m.Team) -> TeamOut:
    return TeamOut(id=t.id, name=t.name, abbreviation=t.abbreviation, logo_url=t.logo_url)


def prediction_out(p: m.Prediction, final: bool) -> PredictionOut:
    probs = [p.p_home, p.p_draw, p.p_away]
    return PredictionOut(
        id=p.id, match_id=p.match_id, generated_at=p.generated_at, data_cutoff=p.data_cutoff,
        model_version=p.model_version.version, p_home=p.p_home, p_draw=p.p_draw, p_away=p.p_away,
        most_likely_outcome=OUTCOMES[probs.index(max(probs))], exp_home_goals=p.exp_home_goals,
        exp_away_goals=p.exp_away_goals, top_score_home=p.top_score_home, top_score_away=p.top_score_away,
        top_score_prob=p.top_score_prob, top_scores=p.top_scores, uncertainty=p.uncertainty, entropy=p.entropy,
        factors=p.factors, is_pre_kickoff_final=final,
    )


def latest_pre_kickoff(session: Session, match_ids: list[int]) -> dict[int, m.Prediction]:
    """Última predicción generada ANTES del inicio de cada partido (la que cuenta para evaluar)."""
    if not match_ids:
        return {}
    sub = (select(m.Prediction.match_id, func.max(m.Prediction.generated_at).label("g"))
           .join(m.Match, m.Match.id == m.Prediction.match_id)
           .where(m.Prediction.match_id.in_(match_ids), m.Prediction.generated_at < m.Match.kickoff_utc)
           .group_by(m.Prediction.match_id).subquery())
    rows = session.scalars(
        select(m.Prediction).options(joinedload(m.Prediction.model_version))
        .join(sub, and_(m.Prediction.match_id == sub.c.match_id, m.Prediction.generated_at == sub.c.g))
    ).all()
    return {p.match_id: p for p in rows}


def match_out(mt: m.Match, pred: m.Prediction | None) -> MatchOut:
    hit = None
    if pred is not None and mt.status == m.FINISHED and mt.home_goals is not None:
        actual = 0 if mt.home_goals > mt.away_goals else (1 if mt.home_goals == mt.away_goals else 2)
        probs = [pred.p_home, pred.p_draw, pred.p_away]
        hit = probs.index(max(probs)) == actual
    return MatchOut(
        id=mt.id, espn_id=mt.espn_id, season=mt.season, tournament=mt.tournament, stage=mt.stage,
        stage_detail=mt.stage_detail, round=mt.round, kickoff_utc=mt.kickoff_utc, status=mt.status,
        status_detail=mt.status_detail, live_clock=mt.live_clock, home=team_out(mt.home_team),
        away=team_out(mt.away_team), home_goals=mt.home_goals, away_goals=mt.away_goals,
        home_goals_final=mt.home_goals_final, away_goals_final=mt.away_goals_final,
        home_penalties=mt.home_penalties, away_penalties=mt.away_penalties, extra_time=mt.extra_time,
        updated_at=mt.updated_at, prediction=prediction_out(pred, mt.kickoff_utc <= _now()) if pred else None,
        prediction_hit=hit,
    )


def _with_teams(q):
    return q.options(joinedload(m.Match.home_team), joinedload(m.Match.away_team))


# ---------------------------------------------------------------------------------------------------
# Sincronización al abrir la página (si los datos están atrasados y hay partidos en juego)
# ---------------------------------------------------------------------------------------------------
_visit_sync_lock = threading.Lock()
_last_visit_sync = 0.0
VISIT_SYNC_MIN_INTERVAL_S = 120


def _maybe_sync_on_visit(stale: bool, live_window: bool) -> str | None:
    global _last_visit_sync
    if not (stale and live_window):
        return None
    with _visit_sync_lock:
        if time.monotonic() - _last_visit_sync < VISIT_SYNC_MIN_INTERVAL_S:
            return "Sincronización reciente en curso"
        _last_visit_sync = time.monotonic()
    threading.Thread(target=lambda: _safe_job("live", tasks.live_sync), daemon=True).start()
    return "Datos atrasados: se inició una sincronización con la fuente"


def _safe_job(name, fn):
    try:
        run_job(name, "api", fn)
    except Exception:  # el error queda en job_runs
        log.exception("Sincronización desde la API falló")


# ---------------------------------------------------------------------------------------------------
# Rutas públicas
# ---------------------------------------------------------------------------------------------------
@app.get("/api/health", tags=["sistema"])
def health(session: DB):
    session.execute(select(1))
    return {"status": "ok", "env": settings.env, "time": _now()}


@app.get("/api/updates/status", response_model=StatusOut, tags=["sistema"])
def updates_status(session: DB, sync_if_stale: bool = True):
    now = _now()
    sync = get_state(session, "sync", {})
    version = int(get_state(session, "data_version", {"version": 0}).get("version", 0))
    last_ok = datetime.fromisoformat(sync["last_success"]) if sync.get("last_success") else None
    stale = last_ok is None or now - last_ok > timedelta(minutes=settings.stale_after_minutes)
    live = session.scalar(select(func.count()).select_from(m.Match).where(m.Match.status == m.IN_PROGRESS)) or 0
    # ventana de partido: alguno en juego o alguno que debió empezar en las últimas 3 h sin finalizar
    recent = session.scalar(select(func.count()).select_from(m.Match).where(
        m.Match.status.in_([m.SCHEDULED, m.IN_PROGRESS]),
        m.Match.kickoff_utc <= now, m.Match.kickoff_utc >= now - timedelta(hours=3))) or 0
    message = _maybe_sync_on_visit(stale, bool(live or recent)) if sync_if_stale else None
    nxt = session.scalar(select(func.min(m.Match.kickoff_utc)).where(m.Match.status == m.SCHEDULED,
                                                                      m.Match.kickoff_utc > now))
    mv = active_model(session)
    first, last_fin, total = session.execute(select(
        func.min(m.Match.kickoff_utc),
        func.max(m.Match.kickoff_utc).filter(m.Match.status == m.FINISHED),
        func.count(m.Match.id))).one()
    return StatusOut(
        data_version=version, server_time=now, last_sync_success=last_ok,
        last_sync_attempt=datetime.fromisoformat(sync["last_attempt"]) if sync.get("last_attempt") else None,
        last_sync_error=sync.get("last_error"), is_stale=stale, source="ESPN (API pública, no oficial)",
        live_matches=live, next_kickoff=nxt, active_model=mv.version if mv else None,
        model_trained_at=mv.trained_at if mv else None, model_data_cutoff=mv.data_cutoff if mv else None,
        matches_total=total, first_match=first, last_finished_match=last_fin,
        refresh_hint_seconds=30 if (live or recent) else 60, message=message,
    )


@app.get("/api/seasons", tags=["datos"])
def seasons(session: DB):
    rows = session.execute(
        select(m.Match.season, m.Match.tournament, func.count(m.Match.id),
               func.count(m.Match.id).filter(m.Match.status == m.FINISHED),
               func.min(m.Match.kickoff_utc), func.max(m.Match.kickoff_utc))
        .group_by(m.Match.season, m.Match.tournament).order_by(func.min(m.Match.kickoff_utc).desc())
    ).all()
    return [{"season": s, "tournament": t, "matches": n, "finished": f, "start": a, "end": b}
            for s, t, n, f, a, b in rows]


@app.get("/api/matches", response_model=Paginated, tags=["datos"])
def matches(session: DB,
            tournament: str | None = None, season: str | None = None,
            round: Annotated[int | None, Query(ge=1, le=40)] = None,
            team_id: int | None = None, stage: str | None = None,
            status: Annotated[str | None, Query(pattern="^(scheduled|in_progress|finished|postponed|suspended|canceled)$")] = None,
            date_from: datetime | None = None, date_to: datetime | None = None,
            order: Annotated[str, Query(pattern="^(asc|desc)$")] = "desc",
            limit: Annotated[int, Query(ge=1, le=500)] = 100, offset: Annotated[int, Query(ge=0)] = 0):
    conds = []
    if tournament:
        conds.append(m.Match.tournament == tournament)
    if season:
        conds.append(m.Match.season == season)
    if round:
        conds.append(m.Match.round == round)
    if stage:
        conds.append(m.Match.stage == stage)
    if team_id:
        conds.append(or_(m.Match.home_team_id == team_id, m.Match.away_team_id == team_id))
    if status:
        conds.append(m.Match.status == status)
    if date_from:
        conds.append(m.Match.kickoff_utc >= date_from)
    if date_to:
        conds.append(m.Match.kickoff_utc <= date_to)
    total = session.scalar(select(func.count()).select_from(m.Match).where(*conds))
    order_by = m.Match.kickoff_utc.asc() if order == "asc" else m.Match.kickoff_utc.desc()
    rows = session.scalars(_with_teams(select(m.Match).where(*conds).order_by(order_by, m.Match.id)
                                       .limit(limit).offset(offset))).all()
    preds = latest_pre_kickoff(session, [r.id for r in rows])
    return Paginated(total=total, items=[match_out(r, preds.get(r.id)) for r in rows])


@app.get("/api/fixtures/upcoming", response_model=list[MatchOut], tags=["predicciones"])
def upcoming(session: DB, days: Annotated[int, Query(ge=1, le=60)] = 14):
    now = _now()
    rows = session.scalars(_with_teams(
        select(m.Match).where(
            or_(m.Match.status == m.IN_PROGRESS,
                and_(m.Match.status.in_([m.SCHEDULED, m.POSTPONED]), m.Match.kickoff_utc >= now - timedelta(hours=3),
                     m.Match.kickoff_utc <= now + timedelta(days=days))))
        .order_by(m.Match.kickoff_utc, m.Match.id))).all()
    preds = latest_pre_kickoff(session, [r.id for r in rows])
    return [match_out(r, preds.get(r.id)) for r in rows]


@app.get("/api/predictions", response_model=list[PredictionOut], tags=["predicciones"])
def predictions(session: DB, match_id: int):
    """Historial completo (inmutable) de predicciones de un partido, de la más reciente a la más antigua."""
    mt = session.get(m.Match, match_id)
    if mt is None:
        raise HTTPException(404, "Partido no encontrado")
    rows = session.scalars(select(m.Prediction).options(joinedload(m.Prediction.model_version))
                           .where(m.Prediction.match_id == match_id).order_by(m.Prediction.generated_at.desc())).all()
    final_id = next((p.id for p in rows if p.generated_at < mt.kickoff_utc), None)
    return [prediction_out(p, p.id == final_id and mt.kickoff_utc <= _now()) for p in rows]


@app.get("/api/teams", response_model=list[TeamOut], tags=["equipos"])
def teams(session: DB, tournament: str | None = None):
    q = select(m.Team).order_by(m.Team.name)
    if tournament:
        ids = select(m.Match.home_team_id).where(m.Match.tournament == tournament).union(
            select(m.Match.away_team_id).where(m.Match.tournament == tournament))
        q = q.where(m.Team.id.in_(ids))
    return [team_out(t) for t in session.scalars(q)]


_elo_cache: dict = {"version": None, "elo": None, "params": None}


def _elo_history(session: Session) -> dict[int, list]:
    version = int(get_state(session, "data_version", {"version": 0}).get("version", 0))
    if _elo_cache["version"] != version:
        bt = latest_backtest(session)
        fp = FeatureParams(**bt.summary["feature_params"]) if bt else FeatureParams()
        _, builder = build_features(load_matches_df(session), fp, return_builder=True)
        hist: dict[int, list] = defaultdict(list)
        for match_id, kickoff, team_id, elo in builder.elo_history:
            hist[int(team_id)].append({"match_id": int(match_id), "date": kickoff.isoformat(), "elo": round(elo, 1)})
        _elo_cache.update(version=version, elo=hist)
    return _elo_cache["elo"]


@app.get("/api/teams/{team_id}/statistics", tags=["equipos"])
def team_statistics(session: DB, team_id: int, last: Annotated[int, Query(ge=5, le=60)] = 20):
    team = session.get(m.Team, team_id)
    if team is None:
        raise HTTPException(404, "Equipo no encontrado")
    rows = session.scalars(_with_teams(select(m.Match).where(
        m.Match.status == m.FINISHED, m.Match.home_goals.is_not(None),
        or_(m.Match.home_team_id == team_id, m.Match.away_team_id == team_id))
        .order_by(m.Match.kickoff_utc.desc()))).all()

    def line(mt: m.Match):
        home = mt.home_team_id == team_id
        gf, ga = (mt.home_goals, mt.away_goals) if home else (mt.away_goals, mt.home_goals)
        res = "G" if gf > ga else ("E" if gf == ga else "P")
        return {"match_id": mt.id, "date": mt.kickoff_utc, "tournament": mt.tournament, "home": home,
                "opponent": (mt.away_team if home else mt.home_team).name, "gf": gf, "ga": ga, "result": res,
                "points": {"G": 3, "E": 1, "P": 0}[res]}

    lines = [line(r) for r in rows]

    def agg(items):
        n = len(items)
        if not n:
            return {"played": 0}
        return {"played": n, "wins": sum(i["result"] == "G" for i in items),
                "draws": sum(i["result"] == "E" for i in items), "losses": sum(i["result"] == "P" for i in items),
                "gf": sum(i["gf"] for i in items), "ga": sum(i["ga"] for i in items),
                "ppg": round(sum(i["points"] for i in items) / n, 3),
                "gf_avg": round(sum(i["gf"] for i in items) / n, 3), "ga_avg": round(sum(i["ga"] for i in items) / n, 3)}

    recent = lines[:last]
    by_t: dict[str, list] = defaultdict(list)
    for ln in lines:
        by_t[ln["tournament"]].append(ln)
    return {
        "team": team_out(team),
        "matches_in_database": len(lines),
        "recent": recent,
        "form_last5": "".join(i["result"] for i in lines[:5]),
        "summary_recent": agg(recent),
        "home_recent": agg([i for i in lines if i["home"]][:last]),
        "away_recent": agg([i for i in lines if not i["home"]][:last]),
        "by_tournament": [{"tournament": t, **agg(v)} for t, v in list(by_t.items())[:12]],
        "elo_history": _elo_history(session).get(team_id, [])[-150:],
    }


@app.get("/api/standings", tags=["datos"])
def standings(session: DB, tournament: str):
    """Tabla de fase regular calculada con los partidos finalizados (marcador final de la fuente)."""
    rows = session.scalars(_with_teams(select(m.Match).where(
        m.Match.tournament == tournament, m.Match.stage == "regular", m.Match.status == m.FINISHED)))
    table: dict[int, dict] = {}
    for mt in rows:
        for tid, team, gf, ga in ((mt.home_team_id, mt.home_team, mt.home_goals_final, mt.away_goals_final),
                                  (mt.away_team_id, mt.away_team, mt.away_goals_final, mt.home_goals_final)):
            r = table.setdefault(tid, {"team": team_out(team).model_dump(), "played": 0, "wins": 0, "draws": 0,
                                       "losses": 0, "gf": 0, "ga": 0, "points": 0})
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            if gf > ga:
                r["wins"] += 1
                r["points"] += 3
            elif gf == ga:
                r["draws"] += 1
                r["points"] += 1
            else:
                r["losses"] += 1
    out = sorted(table.values(), key=lambda r: (-r["points"], -(r["gf"] - r["ga"]), -r["gf"], r["team"]["name"]))
    for i, r in enumerate(out, 1):
        r["position"] = i
        r["gd"] = r["gf"] - r["ga"]
    return {"tournament": tournament, "note": "Calculada con los partidos registrados; los criterios oficiales "
                                              "de desempate pueden diferir.", "rows": out}


@app.get("/api/model/metrics", tags=["modelo"])
def model_metrics(session: DB):
    bt = latest_backtest(session)
    mv = active_model(session)
    live = _live_metrics(session)
    if bt is None:
        return {"available": False, "message": "Aún no se ha ejecutado el backtesting", "live": live}
    return {
        "available": True, "backtest_run_id": bt.id, "created_at": bt.created_at, "summary": bt.summary,
        "active_model": {"version": mv.version, "trained_at": mv.trained_at, "data_cutoff": mv.data_cutoff,
                         "train_matches": mv.train_matches, "params": mv.params} if mv else None,
        "live": live,
    }


def _live_metrics(session: Session) -> dict:
    """Rendimiento real: predicciones guardadas antes del partido vs resultado confirmado."""
    import numpy as np

    from app.ml import metrics as mt

    finished = session.scalars(select(m.Match).where(m.Match.status == m.FINISHED,
                                                     m.Match.home_goals.is_not(None))).all()
    preds = latest_pre_kickoff(session, [f.id for f in finished])
    pairs = [(preds[f.id], f) for f in finished if f.id in preds]
    if not pairs:
        return {"n": 0, "message": "Todavía no hay partidos finalizados con predicción previa guardada"}
    p = np.array([[pr.p_home, pr.p_draw, pr.p_away] for pr, _ in pairs])
    y = np.array([0 if f.home_goals > f.away_goals else (1 if f.home_goals == f.away_goals else 2) for _, f in pairs])
    return mt.summarize(p, y)


@app.get("/api/backtest/predictions", tags=["modelo"])
def backtest_predictions(session: DB, model: str | None = None, split: str = "test",
                         limit: Annotated[int, Query(ge=1, le=1000)] = 200):
    bt = latest_backtest(session)
    if bt is None:
        return []
    model = model or bt.selected_model
    rows = session.execute(
        select(m.BacktestPrediction, m.Match).join(m.Match, m.Match.id == m.BacktestPrediction.match_id)
        .options(joinedload(m.Match.home_team), joinedload(m.Match.away_team))
        .where(m.BacktestPrediction.run_id == bt.id, m.BacktestPrediction.model == model,
               m.BacktestPrediction.split == split)
        .order_by(m.Match.kickoff_utc.desc()).limit(limit)).all()
    return [{"match_id": mt_.id, "kickoff_utc": mt_.kickoff_utc, "tournament": mt_.tournament,
             "home": mt_.home_team.name, "away": mt_.away_team.name, "home_goals": mt_.home_goals,
             "away_goals": mt_.away_goals, "p_home": bp.p_home, "p_draw": bp.p_draw, "p_away": bp.p_away,
             "exp_home_goals": bp.exp_home_goals, "exp_away_goals": bp.exp_away_goals}
            for bp, mt_ in rows]


# ---------------------------------------------------------------------------------------------------
# Administración (requiere Authorization: Bearer <ADMIN_TOKEN>)
# ---------------------------------------------------------------------------------------------------
@app.get("/api/admin/jobs", tags=["admin"], dependencies=[Depends(require_admin)])
def admin_jobs(session: DB, limit: Annotated[int, Query(ge=1, le=200)] = 50):
    rows = session.scalars(select(m.JobRun).order_by(m.JobRun.id.desc()).limit(limit)).all()
    return [{"id": r.id, "job": r.job, "trigger": r.trigger, "status": r.status, "started_at": r.started_at,
             "finished_at": r.finished_at, "message": r.message,
             "stats": {k: v for k, v in (r.stats or {}).items() if k != "traceback"}} for r in rows]


@app.get("/api/admin/issues", tags=["admin"], dependencies=[Depends(require_admin)])
def admin_issues(session: DB, severity: str | None = None, resolved: bool = False,
                 limit: Annotated[int, Query(ge=1, le=500)] = 100):
    q = select(m.DataIssue).where(m.DataIssue.resolved.is_(resolved)).order_by(m.DataIssue.id.desc()).limit(limit)
    if severity:
        q = q.where(m.DataIssue.severity == severity)
    counts = dict(session.execute(select(m.DataIssue.severity, func.count()).where(m.DataIssue.resolved.is_(False))
                                  .group_by(m.DataIssue.severity)).all())
    return {"open_counts": counts, "items": [
        {"id": i.id, "match_id": i.match_id, "source": i.source, "source_key": i.source_key, "severity": i.severity,
         "code": i.code, "message": i.message, "details": i.details, "created_at": i.created_at}
        for i in session.scalars(q)]}


@app.post("/api/admin/issues/{issue_id}/resolve", tags=["admin"], dependencies=[Depends(require_admin)])
def admin_resolve_issue(session: DB, issue_id: int):
    issue = session.get(m.DataIssue, issue_id)
    if issue is None:
        raise HTTPException(404, "Problema no encontrado")
    issue.resolved = True
    session.commit()
    return {"ok": True}


def _start_background(name: str, fn) -> dict:
    threading.Thread(target=lambda: _safe_job(name, fn), daemon=True).start()
    return {"started": name, "message": "Tarea iniciada; revisa /api/admin/jobs para ver el resultado"}


@app.post("/api/admin/update-data", tags=["admin"], dependencies=[Depends(require_admin)], status_code=202)
def admin_update_data():
    return _start_background("sync", tasks.sync)


@app.post("/api/admin/retrain", tags=["admin"], dependencies=[Depends(require_admin)], status_code=202)
def admin_retrain():
    return _start_background("maintenance", lambda s: tasks.maintenance(s, force_retrain=True))


@app.post("/api/admin/backtest", tags=["admin"], dependencies=[Depends(require_admin)], status_code=202)
def admin_backtest():
    return _start_background("backtest", tasks.backtest)
