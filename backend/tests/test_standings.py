from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.api.main import app
from app.ingest.loader import load_events
from app.predict import service
from app.predict.standings import current_tournament, regular_table, simulate_tournament
from tests.helpers import SMALL_BT, future_fixture, load_simulated

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def trained(session):
    load_simulated(session)
    service.run_and_store_backtest(session, SMALL_BT)
    service.train_production(session, NOW)
    session.commit()
    return session


def _match(home: m.Team, away: m.Team, hg: int, ag: int) -> m.Match:
    return m.Match(home_team_id=home.id, away_team_id=away.id, home_team=home, away_team=away, status=m.FINISHED,
                   home_goals_final=hg, away_goals_final=ag)


def test_regular_table_tiebreakers():
    a, b, c, d, e = (m.Team(id=i, name=n) for i, n in enumerate("ABCDE", 1))
    rows = regular_table([
        _match(a, b, 0, 1),  # B le gana a A en el directo
        _match(a, c, 1, 0),
        _match(d, b, 1, 0),
        m.Match(home_team_id=e.id, away_team_id=c.id, home_team=e, away_team=c, status=m.SCHEDULED),
    ])
    # A y B empatan en puntos (3), diferencia (0) y goles a favor (1): B va arriba por el resultado directo.
    # E aún no juega y aparece con 0 puntos, por encima de C (diferencia -1).
    assert [r["team"].name for r in rows] == ["D", "B", "A", "E", "C"]
    assert [r["position"] for r in rows] == [1, 2, 3, 4, 5]
    by = {r["team"].name: r for r in rows}
    assert (by["A"]["played"], by["A"]["points"], by["A"]["gd"]) == (2, 3, 0)
    assert by["E"]["played"] == 0


def test_simulation_finished_regular_season_and_known_playoff(trained):
    s = trained
    t = current_tournament(s)
    sim = simulate_tournament(s, t, n_sims=2000)
    assert sim["pending_matches"] == 0 and sim["unscheduled_matches"] == 0
    regular = list(s.scalars(select(m.Match).where(m.Match.tournament == t, m.Match.stage == "regular")))
    table = regular_table(regular)
    seeds = [r["team_id"] for r in table]
    probs = sim["teams"]
    # con la fase regular terminada la clasificación es segura
    assert all(probs[tid]["p_qualify"] == 1.0 for tid in seeds[:8])
    assert all(probs[tid]["p_qualify"] == 0.0 and probs[tid]["p_champion"] == 0.0 for tid in seeds[8:])
    assert sum(p["p_champion"] for p in probs.values()) == pytest.approx(1.0)

    # liguilla real ya jugada: el 8.º sembrado gana todo (comprueba cruces, reacomodo y uso de marcadores reales)
    ko = max(mt.kickoff_utc for mt in regular) + timedelta(days=3)
    n = [0]

    def leg(home_seed: int, away_seed: int, hg: int, ag: int):
        n[0] += 1
        s.add(m.Match(espn_id=f"lig{n[0]}", season="x", tournament=t, stage="liguilla", kickoff_utc=ko + timedelta(hours=n[0]),
                      home_team_id=seeds[home_seed - 1], away_team_id=seeds[away_seed - 1], status=m.FINISHED,
                      home_goals=hg, away_goals=ag, home_goals_final=hg, away_goals_final=ag))

    def series(hi: int, lo: int, winner: int):
        if winner == lo:
            leg(lo, hi, 2, 0), leg(hi, lo, 1, 1)
        else:
            leg(lo, hi, 1, 1), leg(hi, lo, 0, 0)  # empate global: avanza el mejor sembrado

    series(1, 8, 8), series(2, 7, 2), series(3, 6, 3), series(4, 5, 4)
    series(2, 8, 8), series(3, 4, 3)  # semifinales con reacomodo: 2 vs 8 y 3 vs 4
    series(3, 8, 8)
    s.flush()
    sim = simulate_tournament(s, t, n_sims=500)
    assert sim["teams"][seeds[7]]["p_champion"] == 1.0


def test_simulation_mid_tournament_and_api(trained):
    s = trained
    ko = NOW + timedelta(days=2)
    # torneo nuevo con solo la jornada 1 publicada: el resto de cruces se simula igual
    load_events(s, [future_fixture(f"n{i}", 2 * i - 1, 2 * i, ko + timedelta(hours=i)) for i in range(1, 7)], NOW)
    service.generate_predictions(s, NOW)
    s.commit()
    t = current_tournament(s)
    assert t == "Apertura 2030"
    sim = simulate_tournament(s, t, n_sims=3000)
    assert sim["pending_matches"] == 6 and sim["unscheduled_matches"] == 12 * 11 // 2 - 6
    assert sum(p["p_qualify"] for p in sim["teams"].values()) == pytest.approx(8.0)
    assert sum(p["p_champion"] for p in sim["teams"].values()) == pytest.approx(1.0)

    c = TestClient(app)
    body = c.get("/api/standings").json()
    assert body["tournament"] == "Apertura 2030" and body["current"] is True and body["qualify_spots"] == 8
    assert len(body["rows"]) == 12 and all(r["played"] == 0 for r in body["rows"])
    assert all(r["p_qualify"] is not None and r["p_champion"] is not None for r in body["rows"])
    assert body["simulation"]["n_sims"] > 0 and "teams" not in body["simulation"]
    old = c.get("/api/standings", params={"tournament": "Clausura 2019"}).json()
    assert old["current"] is False and old["simulation"] is None and old["rows"][0]["p_qualify"] is None
