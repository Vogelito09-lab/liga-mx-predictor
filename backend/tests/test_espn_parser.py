from datetime import datetime, timezone

from app import models as m
from app.sources.espn import parse_event, slim_event, stage_from, tournament_from
from tests.espn_fake import event, final_2016_like, goal


def test_regular_match_parsed():
    ev = event("452519", datetime(2016, 10, 15, 22, 0), ("234", "Chiapas"), ("220", "Monterrey"),
               status="STATUS_FULL_TIME", state="post", completed=True, hs=1, as_=4,
               details=[goal("7'", "220"), goal("13'", "234"), goal("50'", "220"), goal("70'", "220"), goal("90'+2'", "220")])
    pm = parse_event(ev)
    assert pm.status == m.FINISHED
    assert pm.tournament == "Apertura 2016" and pm.season == "2016-17" and pm.stage == "regular"
    assert (pm.home_goals, pm.away_goals) == (1, 4)
    assert (pm.home_goals_final, pm.away_goals_final) == (1, 4)
    assert pm.kickoff_utc == datetime(2016, 10, 15, 22, 0, tzinfo=timezone.utc)
    assert not pm.issues


def test_extra_time_final_uses_90_minute_score():
    pm = parse_event(final_2016_like())
    assert pm.stage == "liguilla" and pm.stage_detail == "Final"
    assert (pm.home_goals_final, pm.away_goals_final) == (1, 1)
    assert (pm.home_goals, pm.away_goals) == (0, 0)  # 0-0 al minuto 90
    assert pm.extra_time is True
    assert (pm.home_penalties, pm.away_penalties) == (3, 0)


def test_extra_time_without_details_leaves_regulation_unknown():
    ev = final_2016_like()
    ev["competitions"][0]["details"] = []
    pm = parse_event(ev)
    assert pm.home_goals is None and pm.away_goals is None
    assert any(code == "regulation_score_unknown" for _, code, _ in pm.issues)


def test_status_mapping():
    base = dict(kickoff=datetime(2026, 10, 18, 2, 0), home=("1", "A"), away=("2", "B"))
    assert parse_event(event("1", **base, status="STATUS_POSTPONED")).status == m.POSTPONED
    assert parse_event(event("1", **base, status="STATUS_CANCELED")).status == m.CANCELED
    live = parse_event(event("1", **base, status="STATUS_SECOND_HALF", state="in", hs=1, as_=0, detail="67'"))
    assert live.status == m.IN_PROGRESS and live.live_clock == "67'" and live.home_goals is None
    assert live.home_goals_final == 1


def test_tournament_from_slug_and_date():
    assert tournament_from("torneo-clausura-2019", datetime(2019, 2, 1, tzinfo=timezone.utc)) == ("Clausura 2019", "2018-19")
    # sin slug: se usa la fecha local (México)
    assert tournament_from(None, datetime(2024, 1, 15, tzinfo=timezone.utc)) == ("Clausura 2024", "2023-24")
    assert tournament_from(None, datetime(2024, 8, 15, tzinfo=timezone.utc)) == ("Apertura 2024", "2024-25")


def test_stage_detection():
    assert stage_from("torneo-apertura-2016", [])[0] == "regular"
    assert stage_from("apertura-2016---quarterfinals", [])[0] == "liguilla"
    assert stage_from("apertura-2023---play-in", [])[0] == "play-in"


def test_slim_event_keeps_everything_parse_needs():
    ev = final_2016_like()
    slim = slim_event(ev)
    assert "broadcasts" not in slim["competitions"][0]
    assert parse_event(slim) == parse_event(ev)
