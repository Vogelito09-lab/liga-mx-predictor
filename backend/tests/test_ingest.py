from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select

from app import models as m
from app.ingest.loader import load_events
from app.jobs import tasks
from tests.espn_fake import FakeEspn, event, final_2016_like
from tests.helpers import load_simulated

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)


def count(session, model):
    return session.scalar(select(func.count()).select_from(model))


def test_load_is_idempotent(session):
    st1 = load_simulated(session, years=range(2016, 2017))
    n = count(session, m.Match)
    assert n == st1.inserted > 0
    st2 = load_simulated(session, years=range(2016, 2017))
    assert count(session, m.Match) == n
    assert st2.inserted == 0 and st2.updated == 0 and st2.unchanged == n
    # los datos crudos tampoco se duplican si no cambiaron
    assert count(session, m.SourceRecord) == n


def test_invalid_records_are_rejected_and_logged(session):
    bad = event("x1", datetime(2026, 9, 1, 2, 0), ("1", "A"), ("2", "B"), status="STATUS_FULL_TIME", state="post",
                completed=True, hs=-1, as_=2)
    same = event("x2", datetime(2026, 9, 1, 2, 0), ("1", "A"), ("1", "A"))
    st = load_events(session, [bad, same], NOW)
    session.commit()
    assert st.rejected == 2 and count(session, m.Match) == 0
    codes = set(session.scalars(select(m.DataIssue.code)))
    assert {"bad_score", "same_team"} <= codes


def test_finished_without_score_not_marked_finished(session):
    ev = event("x3", datetime(2026, 9, 1, 2, 0), ("1", "A"), ("2", "B"), status="STATUS_FULL_TIME", state="post",
               completed=True)
    ev["competitions"][0]["competitors"][0]["score"] = ""
    ev["competitions"][0]["competitors"][1]["score"] = ""
    load_events(session, [ev], NOW)
    session.commit()
    assert count(session, m.Match) == 0
    assert session.scalar(select(m.DataIssue.code).where(m.DataIssue.code == "finished_without_score"))


def test_extra_time_final_loaded_with_90_minute_score(session):
    load_events(session, [final_2016_like()], NOW)
    session.commit()
    mt = session.scalar(select(m.Match))
    assert (mt.home_goals, mt.away_goals, mt.home_goals_final, mt.away_goals_final) == (0, 0, 1, 1)
    assert mt.extra_time and mt.stage == "liguilla"


def test_rescheduled_match_updates_in_place(session):
    ko = datetime(2026, 10, 17, 2, 0)
    load_events(session, [event("r1", ko, ("1", "A"), ("2", "B"))], NOW)
    load_events(session, [event("r1", ko, ("1", "A"), ("2", "B"), status="STATUS_POSTPONED")], NOW)
    mt = session.scalar(select(m.Match))
    assert mt.status == m.POSTPONED
    load_events(session, [event("r1", ko + timedelta(days=20), ("1", "A"), ("2", "B"))], NOW)
    session.commit()
    assert count(session, m.Match) == 1
    mt = session.scalar(select(m.Match))
    assert mt.status == m.SCHEDULED and mt.kickoff_utc == (ko + timedelta(days=20)).replace(tzinfo=timezone.utc)


def test_finished_match_never_regresses(session):
    ko = datetime(2026, 10, 1, 2, 0)
    fin = event("f1", ko, ("1", "A"), ("2", "B"), status="STATUS_FULL_TIME", state="post", completed=True, hs=2, as_=1)
    load_events(session, [fin], NOW)
    load_events(session, [event("f1", ko, ("1", "A"), ("2", "B"), status="STATUS_SECOND_HALF", state="in", hs=1, as_=1)], NOW)
    session.commit()
    mt = session.scalar(select(m.Match))
    assert mt.status == m.FINISHED and (mt.home_goals, mt.away_goals) == (2, 1)
    assert session.scalar(select(m.DataIssue.code).where(m.DataIssue.code == "status_regression"))


def test_retroactive_score_change_is_logged(session):
    ko = datetime(2026, 10, 1, 2, 0)
    args = dict(status="STATUS_FULL_TIME", state="post", completed=True)
    load_events(session, [event("c1", ko, ("1", "A"), ("2", "B"), hs=2, as_=1, **args)], NOW)
    load_events(session, [event("c1", ko, ("1", "A"), ("2", "B"), hs=2, as_=2, **args)], NOW)
    session.commit()
    issue = session.scalar(select(m.DataIssue).where(m.DataIssue.code == "retroactive_change"))
    assert issue and issue.details["old"] == [2, 1] and issue.details["new"] == [2, 2]


def test_source_failure_keeps_existing_data(session):
    fake = FakeEspn()
    ko = datetime(2026, 10, 9, 2, 0)
    fake.put(event("s1", ko, ("1", "A"), ("2", "B"), status="STATUS_FULL_TIME", state="post", completed=True, hs=1, as_=0))
    tasks.sync(session, days_back=2, days_ahead=1, client=fake, now=NOW, predict=False)
    session.commit()
    assert count(session, m.Match) == 1
    fake.fail = True
    res = tasks.sync(session, days_back=2, days_ahead=1, client=fake, now=NOW, predict=False)
    session.commit()
    assert res["_status"] == "failed"
    assert count(session, m.Match) == 1
    mt = session.scalar(select(m.Match))
    assert (mt.home_goals, mt.away_goals, mt.status) == (1, 0, m.FINISHED)
    from app.ingest.loader import get_state
    st = get_state(session, "sync")
    assert st["last_error"] and st["last_success"]


def test_rounds_are_derived(session):
    load_simulated(session, years=range(2016, 2017), n_teams=6)
    rounds = session.scalars(select(m.Match.round).where(m.Match.tournament == "Clausura 2016")).all()
    assert min(rounds) == 1 and max(rounds) == 5
    assert all(r is not None for r in rounds)


def test_audit_detects_duplicates(session):
    from app.ingest.validate import audit_database

    ko = datetime(2026, 10, 1, 2, 0)
    load_events(session, [event("d1", ko, ("1", "A"), ("2", "B")), event("d2", ko + timedelta(hours=2), ("1", "A"), ("2", "B"))], NOW)
    issues = audit_database(session)
    assert any(i.code == "possible_duplicate" for i in issues)


def test_backfill_uses_day_by_day_and_is_resumable(session):
    fake = FakeEspn()
    for i in range(3):
        fake.put(event(f"b{i}", datetime(2026, 8, 1 + i, 2, 0), ("1", "A"), ("2", "B"), status="STATUS_FULL_TIME",
                       state="post", completed=True, hs=i, as_=0))
    tasks.backfill(session, date(2026, 8, 1), date(2026, 8, 5), client=fake, now=NOW)
    tasks.backfill(session, date(2026, 8, 1), date(2026, 8, 5), client=fake, now=NOW)
    session.commit()
    assert count(session, m.Match) == 3
    assert fake.calls == 10
