"""Marcador en vivo: lectura de ESPN, probabilidad por minuto y ruta /api/live."""
import copy
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.api import live as live_api
from app.api.main import app
from app.ingest.loader import load_events
from app.predict import service
from app.predict.live import elapsed_minutes, inplay_probs, remaining_fraction
from app.sources.espn import parse_live
from tests.espn_fake import event
from tests.helpers import SMALL_BT, future_fixture, load_simulated

REAL = json.loads((Path(__file__).parent / "fixtures" / "espn_live_ht_20261010.json").read_text())
NOW = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------------------------------
# Lectura del JSON real de ESPN
# ---------------------------------------------------------------------------------------------------
def test_parse_live_real_halftime():
    by_id = {e["id"]: parse_live(e) for e in REAL["events"]}
    juarez_tijuana = by_id["401876952"]
    assert juarez_tijuana.state == "in" and juarez_tijuana.source_status == "STATUS_HALFTIME"
    assert (juarez_tijuana.home_goals, juarez_tijuana.away_goals) == (0, 1)
    assert juarez_tijuana.period == 1 and juarez_tijuana.display_clock == "45'+4'"
    assert (juarez_tijuana.home_red, juarez_tijuana.away_red) == (0, 0)
    assert elapsed_minutes("in", "STATUS_HALFTIME", 1, juarez_tijuana.clock_seconds) == 45
    scheduled = by_id["401876950"]
    assert scheduled.state == "pre" and scheduled.home_goals is None


def test_parse_live_real_second_half():
    data = json.loads((Path(__file__).parent / "fixtures" / "espn_live_2t_20261010.json").read_text())
    st = {e["id"]: parse_live(e) for e in data["events"]}["401876952"]  # FC Juárez 0-1 Tijuana, minuto 50
    assert (st.state, st.source_status, st.period, st.display_clock) == ("in", "STATUS_SECOND_HALF", 2, "50'")
    assert (st.home_goals, st.away_goals) == (0, 1)
    minute = elapsed_minutes(st.state, st.source_status, st.period, st.clock_seconds)
    assert minute == 50
    lp = inplay_probs(1.4, 1.1, (0.45, 0.28, 0.27), st.home_goals, st.away_goals,
                      remaining_fraction(st.state, st.source_status, minute))
    assert lp.p_away > 0.27 and lp.top_score_away >= 1


def test_parse_live_counts_red_cards():
    ev = copy.deepcopy(REAL["events"][0])
    away_id = next(c["team"]["id"] for c in ev["competitions"][0]["competitors"] if c["homeAway"] == "away")
    ev["competitions"][0]["details"].append({"type": {"text": "Red Card"}, "redCard": True, "team": {"id": away_id}})
    st = parse_live(ev)
    assert (st.home_red, st.away_red) == (0, 1)


def test_elapsed_minutes():
    assert elapsed_minutes("pre", "STATUS_SCHEDULED", 0, 0) == 0
    assert elapsed_minutes("in", "STATUS_FIRST_HALF", 1, 20 * 60) == 20
    assert elapsed_minutes("in", "STATUS_FIRST_HALF", 1, 2700) == 45  # añadido del 1er tiempo
    assert elapsed_minutes("in", "STATUS_SECOND_HALF", 2, 67 * 60 + 30) == 67.5
    assert elapsed_minutes("in", "STATUS_SECOND_HALF", 2, 99 * 60) == 90
    assert elapsed_minutes("in", "STATUS_FIRST_HALF_EXTRA_TIME", 3, 95 * 60) is None
    assert elapsed_minutes("post", "STATUS_FULL_TIME", 2, 5400) is None
    # en el añadido aún puede haber goles; en el descanso no corre el reloj
    assert remaining_fraction("in", "STATUS_SECOND_HALF", 90) > 0
    assert remaining_fraction("in", "STATUS_HALFTIME", 45) == 0.5


# ---------------------------------------------------------------------------------------------------
# Probabilidad según el minuto
# ---------------------------------------------------------------------------------------------------
PRE = (0.48, 0.27, 0.25)


def test_minute_zero_equals_pregame_prediction():
    lp = inplay_probs(1.6, 1.1, PRE, 0, 0, 1.0)
    assert (lp.p_home, lp.p_draw, lp.p_away) == pytest.approx(PRE, abs=1e-9)


def test_probabilities_follow_score_and_clock():
    seq = [inplay_probs(1.6, 1.1, PRE, 1, 0, f) for f in (0.9, 0.6, 0.3, 0.05)]
    for lp in seq:
        assert lp.p_home + lp.p_draw + lp.p_away == pytest.approx(1)
    # ganando 1-0, la victoria local es cada vez más probable mientras pasa el tiempo
    assert [lp.p_home for lp in seq] == sorted(lp.p_home for lp in seq)
    # 0-0 con el tiempo casi agotado → empate casi seguro
    assert inplay_probs(1.6, 1.1, PRE, 0, 0, 0.01).p_draw > 0.95
    end = inplay_probs(1.6, 1.1, PRE, 1, 2, 0.0)
    assert (end.p_away, end.top_score_home, end.top_score_away) == (1.0, 1, 2)
    # el marcador final más probable nunca es menor que el marcador actual
    lp = inplay_probs(1.6, 1.1, PRE, 2, 1, 0.5)
    assert lp.top_score_home >= 2 and lp.top_score_away >= 1


# ---------------------------------------------------------------------------------------------------
# Ruta /api/live
# ---------------------------------------------------------------------------------------------------
@pytest.fixture()
def live_setup(session, monkeypatch):
    load_simulated(session)
    service.run_and_store_backtest(session, SMALL_BT)
    service.train_production(session, NOW - timedelta(days=1))
    load_events(session, [future_fixture("lv1", 1, 2, NOW + timedelta(minutes=10)),
                          future_fixture("lv2", 3, 4, NOW + timedelta(days=3))], NOW - timedelta(days=1))
    service.generate_predictions(session, NOW - timedelta(days=1))
    session.commit()
    live_api._cache.reset()
    clock = {"now": NOW}
    monkeypatch.setattr(live_api, "_now", lambda: clock["now"])
    feed = {"events": [], "fail": False, "calls": 0}

    def fake_fetch(day):
        feed["calls"] += 1
        if feed["fail"]:
            raise RuntimeError("ESPN no responde (simulado)")
        return {"events": feed["events"]}

    syncs = []
    monkeypatch.setattr(live_api, "fetch_scoreboard", fake_fetch)
    monkeypatch.setattr(live_api, "run_job", lambda *a: syncs.append(a))
    monkeypatch.setattr(live_api, "_last_db_sync", 0.0)
    return session, clock, feed, syncs


def _live_event(status, state, clock_s, period, hs, as_, details=None):
    ev = event("lv1", (NOW + timedelta(minutes=10)).replace(tzinfo=None), ("1", "Equipo 1"), ("2", "Equipo 2"),
               status=status, state=state, hs=hs, as_=as_, slug="torneo-apertura-2030", details=details)
    ev["competitions"][0]["status"].update({"clock": clock_s, "period": period,
                                            "displayClock": f"{int(clock_s // 60)}'"})
    return ev


def test_live_route_minute_by_minute(live_setup):
    s, clock, feed, syncs = live_setup
    client = TestClient(app)
    # Antes del inicio: aparece por empezar, sin probabilidad en vivo
    feed["events"] = [_live_event("STATUS_SCHEDULED", "pre", 0, 0, None, None)]
    body = client.get("/api/live").json()
    assert body["active"] and body["poll_seconds"] == live_api.POLL_ACTIVE_S
    (lv,) = body["matches"]
    assert lv["state"] == "pre" and lv["live_prob"] is None and lv["pregame"] is not None

    # Minuto 30, 1-0: la probabilidad local sube respecto a la previa
    live_api._cache.checked_at = 0
    clock["now"] = NOW + timedelta(minutes=40)
    feed["events"] = [_live_event("STATUS_FIRST_HALF", "in", 30 * 60, 1, 1, 0,
                                  details=[{"redCard": True, "team": {"id": "2"}}])]
    (lv,) = client.get("/api/live").json()["matches"]
    assert lv["state"] == "in" and lv["clock"] == "30'" and lv["status_label"] == "1er tiempo"
    assert (lv["home_goals"], lv["away_goals"], lv["away_red"]) == (1, 0, 1)
    assert lv["live_prob"]["minute"] == 30
    assert lv["live_prob"]["p_home"] > lv["pregame"]["p_home"]
    p30 = lv["live_prob"]["p_home"]
    # ESPN ya ve el partido en juego y la base no: se adelanta la sincronización normal (una sola vez)
    assert len(syncs) == 1

    # Dentro de los 25 s siguientes no se vuelve a consultar a ESPN
    calls = feed["calls"]
    client.get("/api/live")
    assert feed["calls"] == calls

    # Minuto 80, sigue 1-0: aún más probable
    live_api._cache.checked_at = 0
    clock["now"] = NOW + timedelta(minutes=95)
    feed["events"] = [_live_event("STATUS_SECOND_HALF", "in", 80 * 60, 2, 1, 0)]
    (lv,) = client.get("/api/live").json()["matches"]
    assert lv["live_prob"]["p_home"] > p30 and lv["status_label"] == "2º tiempo"


def test_live_route_keeps_last_data_when_espn_fails(live_setup):
    s, clock, feed, _ = live_setup
    client = TestClient(app)
    feed["events"] = [_live_event("STATUS_SECOND_HALF", "in", 60 * 60, 2, 0, 2)]
    first = client.get("/api/live").json()
    assert not first["stale"]
    feed["fail"] = True
    live_api._cache.checked_at = 0
    clock["now"] = NOW + timedelta(minutes=5)
    body = client.get("/api/live").json()
    (lv,) = body["matches"]
    assert (lv["home_goals"], lv["away_goals"]) == (0, 2)  # último dato conocido
    assert body["stale"]


def test_no_espn_calls_without_matches_in_window(live_setup):
    s, clock, feed, _ = live_setup
    clock["now"] = NOW - timedelta(days=1)
    body = TestClient(app).get("/api/live").json()
    assert body == {**body, "active": False, "matches": [], "poll_seconds": live_api.POLL_IDLE_S}
    assert feed["calls"] == 0


def test_finished_in_db_is_not_overridden(live_setup):
    """Un partido que la base ya tiene como finalizado sale del marcador en vivo: manda el resultado oficial."""
    s, clock, feed, _ = live_setup
    load_events(s, [event("lv1", (NOW + timedelta(minutes=10)).replace(tzinfo=None), ("1", "Equipo 1"),
                          ("2", "Equipo 2"), status="STATUS_FULL_TIME", state="post", completed=True, hs=2, as_=0,
                          slug="torneo-apertura-2030")], NOW + timedelta(hours=2))
    s.commit()
    assert s.scalar(select(m.Match.status).where(m.Match.espn_id == "lv1")) == m.FINISHED
    clock["now"] = NOW + timedelta(hours=2)
    assert TestClient(app).get("/api/live").json()["matches"] == []
