import threading
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import models as m
from app.api.main import app
from app.ingest.loader import get_state, load_events
from app.jobs import tasks
from app.jobs.runner import run_job, write_lock
from app.predict import service
from tests.espn_fake import FakeEspn, event
from tests.helpers import SMALL_BT, future_fixture, load_simulated

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
AUTH = {"Authorization": "Bearer token-de-prueba"}


@pytest.fixture()
def trained(session):
    load_simulated(session)
    service.run_and_store_backtest(session, SMALL_BT)
    service.train_production(session, NOW)
    session.commit()
    return session


def n_predictions(session):
    return session.scalar(select(func.count()).select_from(m.Prediction))


def test_predictions_valid_and_only_for_pending(trained):
    s = trained
    load_events(s, [
        future_fixture("p1", 1, 2, NOW + timedelta(days=2)),
        future_fixture("p2", 3, 4, NOW + timedelta(days=3)),
        future_fixture("p3", 5, 6, NOW - timedelta(hours=1)),  # ya empezó (sigue "programado" en la fuente)
    ], NOW)
    res = service.generate_predictions(s, NOW)
    s.commit()
    assert res["created"] == 2
    preds = s.scalars(select(m.Prediction)).all()
    started = s.scalar(select(m.Match.id).where(m.Match.espn_id == "p3"))
    assert all(p.match_id != started for p in preds)
    finished_ids = set(s.scalars(select(m.Match.id).where(m.Match.status == m.FINISHED)))
    assert not finished_ids & {p.match_id for p in preds}
    for p in preds:
        assert 0 <= p.p_home <= 1 and 0 <= p.p_draw <= 1 and 0 <= p.p_away <= 1
        assert abs(p.p_home + p.p_draw + p.p_away - 1) < 1e-6
        assert p.top_scores[0]["p"] == max(t["p"] for t in p.top_scores)
        assert (p.top_score_home, p.top_score_away) == (p.top_scores[0]["home"], p.top_scores[0]["away"])
        assert p.uncertainty in ("baja", "media", "alta") and p.factors


def test_prediction_history_is_preserved(trained):
    s = trained
    load_events(s, [future_fixture("h1", 1, 2, NOW + timedelta(days=5))], NOW)
    service.generate_predictions(s, NOW)
    s.commit()
    first = s.scalar(select(m.Prediction))
    snapshot = (first.id, first.p_home, first.p_draw, first.p_away, first.generated_at)
    # sin cambios en los datos: no se crea otra versión
    assert service.generate_predictions(s, NOW + timedelta(hours=1))["created"] == 0
    # un resultado nuevo de uno de los equipos cambia sus variables → nueva versión, la anterior intacta
    load_events(s, [event("h0", (NOW + timedelta(days=1)).replace(tzinfo=None), ("1", "Equipo 1"), ("3", "Equipo 3"),
                          status="STATUS_FULL_TIME", state="post", completed=True, hs=4, as_=0,
                          slug="torneo-apertura-2030")], NOW + timedelta(days=1, hours=3))
    service.generate_predictions(s, NOW + timedelta(days=1, hours=3))
    s.commit()
    rows = s.scalars(select(m.Prediction).join(m.Match).where(m.Match.espn_id == "h1")
                     .order_by(m.Prediction.generated_at)).all()
    assert len(rows) == 2
    assert (rows[0].id, rows[0].p_home, rows[0].p_draw, rows[0].p_away, rows[0].generated_at) == snapshot


def test_retrain_policy(trained):
    s = trained
    retrain, _ = service.needs_retrain(s, NOW)
    assert retrain is False
    mv = service.active_model(s)
    evs = [event(f"n{i}", (mv.data_cutoff + timedelta(days=1, hours=i)).replace(tzinfo=None),
                 (str(1 + i % 6), f"Equipo {1 + i % 6}"), (str(7 + i % 6), f"Equipo {7 + i % 6}"),
                 status="STATUS_FULL_TIME", state="post", completed=True, hs=1, as_=1) for i in range(9)]
    load_events(s, evs, NOW)
    s.commit()
    retrain, reason = service.needs_retrain(s, NOW)
    assert retrain and "9 partidos" in reason


def test_job_lock_prevents_concurrent_runs(engine):
    started, release = threading.Event(), threading.Event()

    def slow(session):
        started.set()
        release.wait(10)
        return {"ok": True}

    results = {}
    t = threading.Thread(target=lambda: results.setdefault("a", run_job("sync", "manual", slow)))
    t.start()
    started.wait(10)
    b = run_job("sync", "manual", lambda s: {"ok": True})
    release.set()
    t.join(10)
    assert b.status == "skipped"
    assert results["a"].status == "success"
    with write_lock() as got:
        assert got  # el candado se liberó


def test_failed_job_rolls_back_and_rerun_does_not_duplicate(engine, session):
    ko = datetime(2026, 10, 1, 2, 0)
    evs = [event(f"j{i}", ko + timedelta(hours=i), ("1", "A"), ("2", "B"), status="STATUS_FULL_TIME", state="post",
                 completed=True, hs=1, as_=0) for i in range(3)]

    def crashing(s):
        load_events(s, evs, NOW)
        raise RuntimeError("fallo a mitad de la tarea (simulado)")

    with pytest.raises(RuntimeError):
        run_job("sync", "manual", crashing)
    assert session.scalar(select(func.count()).select_from(m.Match)) == 0
    assert session.scalar(select(m.JobRun.status).where(m.JobRun.job == "sync")) == "failed"
    run_job("sync", "manual", lambda s: load_events(s, evs, NOW).as_dict())
    run_job("sync", "manual", lambda s: load_events(s, evs, NOW).as_dict())
    session.expire_all()
    assert session.scalar(select(func.count()).select_from(m.Match)) == 3


def test_api_handles_empty_database(engine):
    c = TestClient(app)
    assert c.get("/api/health").json()["status"] == "ok"
    st = c.get("/api/updates/status").json()
    assert st["data_version"] == 0 and st["active_model"] is None and st["is_stale"] is True
    assert c.get("/api/matches").json() == {"total": 0, "items": []}
    assert c.get("/api/fixtures/upcoming").json() == []
    assert c.get("/api/teams").json() == []
    assert c.get("/api/seasons").json() == []
    assert c.get("/api/model/metrics").json()["available"] is False
    assert c.get("/api/predictions", params={"match_id": 1}).status_code == 404
    assert c.get("/api/teams/1/statistics").status_code == 404


def test_api_input_validation_and_admin_auth(engine):
    c = TestClient(app)
    assert c.get("/api/matches", params={"status": "inventado"}).status_code == 422
    assert c.get("/api/matches", params={"limit": 10_000}).status_code == 422
    assert c.post("/api/admin/update-data").status_code == 401
    assert c.post("/api/admin/update-data", headers={"Authorization": "Bearer otro"}).status_code == 401
    assert c.get("/api/admin/jobs", headers=AUTH).status_code == 200


def test_live_match_flow_scheduled_inprogress_finished(trained, monkeypatch):
    """Prueba obligatoria: un partido pasa de programado → en curso → finalizado.

    El backend detecta cada cambio, sube la versión de datos (que el frontend vigila) y expone el marcador
    confirmado; la predicción previa al inicio se conserva y se evalúa.
    """
    s = trained
    fake = FakeEspn()
    ko = NOW + timedelta(hours=2)
    teams = (("1", "Equipo 1"), ("2", "Equipo 2"))
    fake.put(event("live1", ko.replace(tzinfo=None), *teams, slug="torneo-clausura-2030"))
    import app.api.main as api

    clock = {"now": NOW}
    monkeypatch.setattr(api, "_now", lambda: clock["now"])
    c = TestClient(app)

    def version():
        return c.get("/api/updates/status", params={"sync_if_stale": False}).json()["data_version"]

    tasks.sync(s, days_back=1, days_ahead=2, client=fake, now=NOW)
    s.commit()
    v1 = version()
    up = c.get("/api/fixtures/upcoming", params={"days": 2}).json()
    match = next(x for x in up if x["espn_id"] == "live1")
    assert match["status"] == "scheduled" and match["prediction"] is not None
    pred_id = match["prediction"]["id"]

    fake.put(event("live1", ko.replace(tzinfo=None), *teams, status="STATUS_FIRST_HALF", state="in", hs=1, as_=0,
                   detail="23'", slug="torneo-clausura-2030"))
    clock["now"] = ko + timedelta(minutes=25)
    tasks.sync(s, days_back=1, days_ahead=2, client=fake, now=clock["now"])
    s.commit()
    v2 = version()
    assert v2 > v1
    live = c.get(f"/api/matches", params={"status": "in_progress"}).json()["items"][0]
    assert live["home_goals_final"] == 1 and live["live_clock"] == "23'" and live["home_goals"] is None

    fake.put(event("live1", ko.replace(tzinfo=None), *teams, status="STATUS_FULL_TIME", state="post", completed=True,
                   hs=2, as_=0, slug="torneo-clausura-2030"))
    clock["now"] = ko + timedelta(hours=2)
    res = tasks.sync(s, days_back=1, days_ahead=2, client=fake, now=clock["now"])
    s.commit()
    assert res["newly_finished"]
    assert version() > v2
    done = c.get(f"/api/matches", params={"status": "finished", "limit": 1}).json()["items"][0]
    assert done["espn_id"] == "live1" and (done["home_goals"], done["away_goals"]) == (2, 0)
    assert done["prediction"]["id"] == pred_id and done["prediction"]["is_pre_kickoff_final"] is True
    assert done["prediction_hit"] in (True, False)
    # repetir la sincronización no duplica el resultado ni cambia la versión
    v3 = version()
    tasks.sync(s, days_back=1, days_ahead=2, client=fake, now=ko + timedelta(hours=3))
    s.commit()
    assert version() == v3
    assert s.scalar(select(func.count()).select_from(m.Match).where(m.Match.espn_id == "live1")) == 1
    live_metrics = c.get("/api/model/metrics").json()["live"]
    assert live_metrics["n"] >= 1


def test_api_endpoints_with_data(trained):
    c = TestClient(app)
    seasons = c.get("/api/seasons").json()
    assert seasons and seasons[0]["matches"] > 0
    t = seasons[0]["tournament"]
    table = c.get("/api/standings", params={"tournament": t}).json()
    assert table["rows"][0]["position"] == 1
    team = c.get("/api/teams").json()[0]
    stats = c.get(f"/api/teams/{team['id']}/statistics").json()
    assert stats["summary_recent"]["played"] > 0 and stats["elo_history"]
    metrics = c.get("/api/model/metrics").json()
    assert metrics["available"] and metrics["summary"]["selected_model"]
    assert c.get("/api/backtest/predictions").json()
    filtered = c.get("/api/matches", params={"tournament": t, "round": 1}).json()
    assert filtered["total"] > 0 and all(x["round"] == 1 for x in filtered["items"])


def test_database_rejects_prediction_updates(trained):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    s = trained
    load_events(s, [future_fixture("u1", 1, 2, NOW + timedelta(days=2))], NOW)
    service.generate_predictions(s, NOW)
    s.commit()
    with pytest.raises(DBAPIError, match="inmutables"):
        s.execute(text("UPDATE predictions SET p_home = 0.99"))
    s.rollback()


def test_crosscheck_flags_discrepancies(session):
    from tests.espn_fake import event as ev

    args = dict(status="STATUS_FULL_TIME", state="post", completed=True)
    load_events(session, [
        ev("c1", datetime(2024, 8, 3, 1, 0), ("1", "Club América"), ("2", "Cruz Azul"), hs=2, as_=1, **args),
        ev("c2", datetime(2024, 8, 3, 3, 0), ("3", "Tigres UANL"), ("4", "Monterrey"), hs=0, as_=0, **args),
    ], NOW)
    session.commit()
    csv_text = ("Country,League,Season,Date,Time,Home,Away,HG,AG,Res\n"
                "Mexico,Liga MX,2024/2025,02/08/2024,19:00,America,Cruz Azul,2,1,H\n"
                "Mexico,Liga MX,2024/2025,02/08/2024,21:00,Tigres,Monterrey,1,0,H\n")
    res = tasks.crosscheck(session, csv_text)
    session.commit()
    assert res == {"rows": 2, "matched": 2, "mismatched": 1, "unmatched": 0, "parse_problems": []}
    issue = session.scalar(select(m.DataIssue).where(m.DataIssue.code == "crosscheck_mismatch"))
    assert issue.source == "football-data" and issue.details["football_data"] == [1, 0]
