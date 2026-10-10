"""Utilidades de prueba: carga la liga simulada en la base de datos con formato ESPN."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.ingest.loader import assign_rounds, load_events
from app.ml.backtest import BacktestConfig
from tests.espn_fake import event
from tests.synthetic import simulated_league

SMALL_BT = BacktestConfig(
    warmup=3, test_tournaments=1, min_matches_per_tournament=50,
    elo_grid=[{"elo_k": 20.0, "elo_home_adv": 60.0, "elo_regress": 0.2}],
    dc_xi_grid=[0.002], lr_c_grid=[0.05],
    gbm_grid=[{"n_estimators": 50, "learning_rate": 0.05, "num_leaves": 5}],
)


def simulated_events(years=range(2016, 2020), n_teams=12):
    df = simulated_league(n_teams=n_teams, years=years)
    evs = []
    for r in df.itertuples():
        kind, year = r.tournament.split()
        evs.append(event(f"sim{r.match_id}", r.kickoff.to_pydatetime().replace(tzinfo=None),
                         (str(r.home_id), f"Equipo {r.home_id}"), (str(r.away_id), f"Equipo {r.away_id}"),
                         status="STATUS_FULL_TIME", state="post", completed=True, hs=r.hg, as_=r.ag,
                         slug=f"torneo-{kind.lower()}-{year}"))
    return evs


def load_simulated(session, years=range(2016, 2020), n_teams=12):
    now = datetime(2030, 1, 1, tzinfo=timezone.utc)
    stats = load_events(session, simulated_events(years, n_teams), now)
    assign_rounds(session)
    session.commit()
    return stats


def future_fixture(eid: str, home: int, away: int, kickoff: datetime, slug="torneo-apertura-2030"):
    return event(eid, kickoff.replace(tzinfo=None), (str(home), f"Equipo {home}"), (str(away), f"Equipo {away}"),
                 slug=slug)


def utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


__all__ = ["SMALL_BT", "load_simulated", "future_fixture", "utc", "timedelta"]
