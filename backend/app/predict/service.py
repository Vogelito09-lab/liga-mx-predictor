"""Backtesting persistido, entrenamiento del modelo de producción y generación de predicciones.

Política de reentrenamiento (ver `needs_retrain`):
- No hay modelo activo, o
- se acumularon al menos RETRAIN_MIN_NEW_MATCHES partidos nuevos desde la fecha de corte del modelo, o
- el modelo tiene más de RETRAIN_MAX_AGE_DAYS días y hay al menos un partido nuevo.
Actualizar estadísticas (Elo, forma) NO requiere reentrenar: las variables se recalculan con cada
resultado nuevo y el modelo vigente se aplica sobre ellas.
"""
from __future__ import annotations

import hashlib
import json
import logging
import pickle
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session, joinedload

from app import models as m
from app.features.build import FeatureParams, build_features
from app.ml.backtest import BacktestConfig, BacktestResult, ensemble_factory, model_factories, run_backtest
from app.ml.models import DixonColesModel, EnsembleModel, LogisticModel
from app.predict.data import load_matches_df

log = logging.getLogger(__name__)

RETRAIN_MIN_NEW_MATCHES = 9  # ~una jornada
RETRAIN_MAX_AGE_DAYS = 7
PREDICTION_HORIZON_DAYS = 30

FEATURE_LABELS = {
    "elo_diff": "Diferencia de Elo (con ventaja de local)",
    "h_ppg5": "Puntos por partido del local (últimos 5)",
    "a_ppg5": "Puntos por partido del visitante (últimos 5)",
    "h_home_ppg5": "Puntos por partido del local jugando en casa (últimos 5)",
    "a_away_ppg5": "Puntos por partido del visitante jugando fuera (últimos 5)",
    "h_ewm_gf": "Goles a favor recientes del local (ponderados)",
    "a_ewm_gf": "Goles a favor recientes del visitante (ponderados)",
    "h_ewm_ga": "Goles en contra recientes del local (ponderados)",
    "a_ewm_ga": "Goles en contra recientes del visitante (ponderados)",
    "h_tour_ppg": "Puntos por partido del local en el torneo",
    "a_tour_ppg": "Puntos por partido del visitante en el torneo",
    "h2h_home_pts": "Puntos medios del local en enfrentamientos directos",
}


# ---------------------------------------------------------------------------------------------------
# Backtesting
# ---------------------------------------------------------------------------------------------------
def run_and_store_backtest(session: Session, cfg: BacktestConfig | None = None) -> m.BacktestRun:
    df = load_matches_df(session)
    result: BacktestResult = run_backtest(df, cfg)
    summary = json.loads(json.dumps(result.summary, default=_json_default))
    run = m.BacktestRun(config=json.loads(json.dumps(result.config, default=_json_default)), summary=summary,
                        selected_model=result.selected_model)
    session.add(run)
    session.flush()
    preds = result.predictions
    records = [
        {"run_id": run.id, "match_id": int(r.match_id), "model": r.model, "split": r.split, "fold": r.fold,
         "p_home": float(r.p_home), "p_draw": float(r.p_draw), "p_away": float(r.p_away),
         "exp_home_goals": _f(getattr(r, "exp_home_goals", None)), "exp_away_goals": _f(getattr(r, "exp_away_goals", None))}
        for r in preds.itertuples(index=False)
    ]
    for i in range(0, len(records), 2000):
        session.execute(m.BacktestPrediction.__table__.insert(), records[i:i + 2000])
    return run


def _f(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else float(v)


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (datetime, pd.Timestamp)):
        return o.isoformat()
    return str(o)


def latest_backtest(session: Session) -> m.BacktestRun | None:
    return session.scalar(select(m.BacktestRun).order_by(m.BacktestRun.id.desc()).limit(1))


# ---------------------------------------------------------------------------------------------------
# Entrenamiento del modelo de producción
# ---------------------------------------------------------------------------------------------------
def active_model(session: Session) -> m.ModelVersion | None:
    return session.scalar(select(m.ModelVersion).where(m.ModelVersion.is_active.is_(True))
                          .order_by(m.ModelVersion.id.desc()).limit(1))


def load_artifact(mv: m.ModelVersion) -> dict:
    # Los artefactos solo los escribe este mismo sistema (train_production); se verifica su hash.
    if hashlib.sha256(mv.artifact).hexdigest() != mv.artifact_sha256:
        raise RuntimeError(f"El artefacto del modelo {mv.version} no coincide con su hash")
    return pickle.loads(mv.artifact)  # noqa: S301


def needs_retrain(session: Session, now: datetime | None = None) -> tuple[bool, str]:
    now = now or datetime.now(timezone.utc)
    mv = active_model(session)
    if mv is None:
        return True, "no hay modelo activo"
    new = session.scalar(select(func.count()).select_from(m.Match).where(
        m.Match.status == m.FINISHED, m.Match.home_goals.is_not(None), m.Match.kickoff_utc > mv.data_cutoff))
    if new >= RETRAIN_MIN_NEW_MATCHES:
        return True, f"{new} partidos nuevos desde el último entrenamiento"
    if new > 0 and now - mv.trained_at > timedelta(days=RETRAIN_MAX_AGE_DAYS):
        return True, f"modelo con más de {RETRAIN_MAX_AGE_DAYS} días y {new} partidos nuevos"
    return False, f"{new} partidos nuevos; no es necesario reentrenar"


def train_production(session: Session, now: datetime | None = None) -> m.ModelVersion:
    """Entrena con TODOS los partidos jugados la configuración elegida en el último backtesting."""
    now = now or datetime.now(timezone.utc)
    bt = latest_backtest(session)
    if bt is None:
        raise RuntimeError("Primero hay que ejecutar el backtesting para elegir el modelo")
    s = bt.summary
    fparams = FeatureParams(**s["feature_params"])
    chosen = s["chosen_hyperparams"]
    selected = s["selected_model"]
    df = load_matches_df(session)
    feats = build_features(df, fparams)
    data = df.set_index("match_id").join(feats).reset_index()
    played = data[data["hg"].notna() & (data["kickoff"] < now)]
    cutoff = played["kickoff"].max()
    if selected == "F_combinado":
        model = ensemble_factory(chosen, chosen["ensemble_members"])()
    else:
        model = model_factories(chosen)[selected]()
    model.fit(played, pd.Timestamp(now))
    goals = DixonColesModel(xi=chosen["dc_xi"]).fit(played, pd.Timestamp(now))
    artifact = pickle.dumps({"model": model, "goals": goals, "feature_params": fparams.as_dict(),
                             "selected": selected})
    sha = hashlib.sha256(artifact).hexdigest()
    version = f"{selected}-{now.strftime('%Y%m%d%H%M')}-{sha[:8]}"
    test_metrics = s["models"][selected]["test"]
    mv = m.ModelVersion(
        version=version, model_type=selected,
        params={"model": model.params(), "goals": goals.params(), "feature_params": fparams.as_dict(),
                "backtest_run_id": bt.id},
        trained_at=now, data_cutoff=cutoff.to_pydatetime(), train_matches=int(len(played)),
        metrics={k: test_metrics.get(k) for k in ("n", "accuracy", "log_loss", "brier", "rps")},
        artifact=artifact, artifact_sha256=sha, is_active=True,
    )
    for old in session.scalars(select(m.ModelVersion).where(m.ModelVersion.is_active.is_(True))):
        old.is_active = False
    session.add(mv)
    session.flush()
    log.info("Modelo %s entrenado con %d partidos", version, len(played))
    return mv


# ---------------------------------------------------------------------------------------------------
# Predicciones
# ---------------------------------------------------------------------------------------------------
def uncertainty_label(p: np.ndarray) -> tuple[str, float]:
    entropy = float(-(p * np.log(np.clip(p, 1e-12, 1))).sum() / np.log(3))
    top = float(p.max())
    label = "baja" if top >= 0.60 else ("media" if top >= 0.45 else "alta")
    return label, entropy


def describe_factors(row: pd.Series, home: str, away: str, model, n_home: int, n_away: int) -> list[dict]:
    """Datos estadísticos que el modelo tuvo a la vista. Son descriptivos: no implican causalidad."""
    out = [
        {"key": "elo", "text": f"Elo previo: {home} {row.elo_home:.0f} · {away} {row.elo_away:.0f} "
                               f"(diferencia con ventaja de local {row.elo_diff:+.0f})"},
        {"key": "forma", "text": f"Puntos por partido, últimos 5: {home} {row.h_ppg5:.2f} · {away} {row.a_ppg5:.2f}"},
        {"key": "condicion", "text": f"{home} en casa (últimos 5): {row.h_home_ppg5:.2f} pts/partido · "
                                     f"{away} de visita (últimos 5): {row.a_away_ppg5:.2f}"},
        {"key": "goles", "text": f"Goles recientes a favor/en contra (ponderados): {home} "
                                 f"{row.h_ewm_gf:.2f}/{row.h_ewm_ga:.2f} · {away} {row.a_ewm_gf:.2f}/{row.a_ewm_ga:.2f}"},
    ]
    if row.h2h_n > 0:
        out.append({"key": "h2h", "text": f"Enfrentamientos directos recientes: {int(row.h2h_n)}; "
                                          f"{home} promedió {row.h2h_home_pts:.2f} pts"})
    out.append({"key": "descanso", "text": f"Días de descanso: {home} {row.h_rest:.0f} · {away} {row.a_rest:.0f}"})
    if min(row.h_tour_played, row.a_tour_played) < 3:
        out.append({"key": "inicio_torneo", "text": "Inicio de torneo: hay pocos partidos del torneo actual; "
                                                     "se usan la forma previa y el Elo como respaldo."})
    for name, n in ((home, n_home), (away, n_away)):
        if n == 0:
            out.append({"key": "sin_historial", "text": f"{name} no tiene partidos previos en la base: "
                                                         "se usa una fuerza de respaldo inferior a la media."})
    lr = model if isinstance(model, LogisticModel) else next(
        (mm for mm in getattr(model, "members", []) if isinstance(mm, LogisticModel)), None)
    if lr is not None:
        top = [(f, c) for f, c in lr.contributions(row) if f in FEATURE_LABELS][:3]
        out.append({"key": "peso_modelo", "text": "Variables con más peso en este cálculo (no implica causa): "
                    + "; ".join(f"{FEATURE_LABELS[f]} ({'a favor del local' if c > 0 else 'a favor del visitante'})"
                                for f, c in top)})
    out.append({"key": "limitacion", "text": "El modelo no considera alineaciones, lesiones ni noticias."})
    return out


def generate_predictions(session: Session, now: datetime | None = None) -> dict:
    """Crea predicciones para partidos programados que aún no empiezan.

    Inmutable: nunca modifica predicciones existentes. Solo inserta una nueva si cambió el modelo o las
    variables del partido (por ejemplo, tras un resultado nuevo de alguno de los equipos).
    """
    now = now or datetime.now(timezone.utc)
    mv = active_model(session)
    if mv is None:
        return {"created": 0, "skipped": 0, "reason": "sin modelo activo"}
    art = load_artifact(mv)
    fparams = FeatureParams(**art["feature_params"])
    model, goals = art["model"], art["goals"]
    df = load_matches_df(session)
    feats = build_features(df, fparams)
    data = df.set_index("match_id").join(feats).reset_index()
    pending = data[(data["status"] == m.SCHEDULED) & (data["kickoff"] > now)
                   & (data["kickoff"] <= now + timedelta(days=PREDICTION_HORIZON_DAYS))]
    if pending.empty:
        return {"created": 0, "skipped": 0, "reason": "no hay partidos pendientes"}
    played = data[data["hg"].notna()]
    data_cutoff = played["kickoff"].max().to_pydatetime() if not played.empty else now
    counts = pd.concat([played["home_id"], played["away_id"]]).value_counts()
    teams = {t.id: t.name for t in session.scalars(select(m.Team))}

    probs = model.predict_proba(pending)
    gp = goals.predict_goals(pending)
    created = skipped = 0
    for i, row in enumerate(pending.itertuples(index=False)):
        r = pending.iloc[i]
        p = np.clip(probs[i], 1e-6, 1)
        p = p / p.sum()
        mat = gp.matrices[i]
        flat = np.argsort(mat, axis=None)[::-1][:5]
        top_scores = [{"home": int(a), "away": int(b), "p": float(mat[a, b])}
                      for a, b in (np.unravel_index(k, mat.shape) for k in flat)]
        inputs = json.dumps({"v": mv.version, "f": [round(float(r[c]), 4) for c in feats.columns]})
        inputs_hash = hashlib.sha256(inputs.encode()).hexdigest()
        last = session.scalar(select(m.Prediction).where(m.Prediction.match_id == int(row.match_id))
                              .order_by(m.Prediction.generated_at.desc()).limit(1))
        if last is not None and last.inputs_hash == inputs_hash:
            skipped += 1
            continue
        label, entropy = uncertainty_label(p)
        session.add(m.Prediction(
            match_id=int(row.match_id), model_version_id=mv.id, generated_at=now, data_cutoff=data_cutoff,
            p_home=float(p[0]), p_draw=float(p[1]), p_away=float(p[2]),
            exp_home_goals=float(gp.lam_home[i]), exp_away_goals=float(gp.lam_away[i]),
            top_score_home=top_scores[0]["home"], top_score_away=top_scores[0]["away"],
            top_score_prob=top_scores[0]["p"], top_scores=top_scores, uncertainty=label, entropy=entropy,
            factors=describe_factors(r, teams.get(int(row.home_id), "Local"), teams.get(int(row.away_id), "Visitante"),
                                     model, int(counts.get(row.home_id, 0)), int(counts.get(row.away_id, 0))),
            inputs_hash=inputs_hash,
        ))
        created += 1
    session.flush()
    return {"created": created, "skipped": skipped, "model_version": mv.version}


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
