from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import models as m
from app.api.main import app
from app.config import get_settings
from app.ingest.loader import assign_rounds, load_events
from app.predict import service
from app.quiniela import api as qapi
from app.quiniela import mailer, security
from app.quiniela.service import jornada_of, pick_points
from tests.espn_fake import event
from tests.helpers import SMALL_BT, future_fixture, load_simulated

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=timezone.utc)
SLUG = "torneo-apertura-2030"


def test_pick_points():
    assert pick_points(2, 1, 2, 1) == (3, "exacto")
    assert pick_points(1, 0, 3, 1) == (1, "resultado")
    assert pick_points(0, 0, 2, 2) == (1, "resultado")
    assert pick_points(2, 2, 2, 2) == (3, "exacto")
    assert pick_points(1, 2, 2, 1) == (0, "fallo")
    assert pick_points(1, 1, 0, 1) == (0, "fallo")
    assert pick_points(2, 1, 2, 1, multiplier=2) == (6, "exacto")


def test_jornada_of_liguilla_rounds():
    def mk(stage, detail=None, rnd=None):
        return m.Match(stage=stage, stage_detail=detail, round=rnd)
    assert jornada_of(mk("regular", rnd=7)).key == "J7"
    assert jornada_of(mk("regular")) is None
    assert jornada_of(mk("liguilla", "Quarterfinals")).key == "cuartos"
    assert jornada_of(mk("liguilla", "Semifinals")).key == "semis"
    assert jornada_of(mk("liguilla", "Finals")).key == "final"
    assert jornada_of(mk("liguilla", "9Th Place Vs 10Th Place")).key == "playin"
    assert jornada_of(mk("play-in", "Play-In")).key == "playin"


def test_rescheduled_match_goes_to_the_week_it_is_played():
    from app.quiniela.service import group_jornadas

    base = datetime(2026, 9, 26, 1, 0, tzinfo=timezone.utc)

    def mk(i, rnd, days):
        return m.Match(id=i, stage="regular", round=rnd, kickoff_utc=base + timedelta(days=days))
    j10 = [mk(i, 10, i * 0.5) for i in range(1, 9)]
    j11 = [mk(10 + i, 11, 14 + i * 0.5) for i in range(1, 9)]
    moved = mk(99, 10, 15.1)  # partido de la jornada 10 reprogramado a la semana de la 11
    lonely = mk(98, 10, 30)  # reprogramado a una fecha sin jornada: va a la más cercana
    groups = {j.key: [mt.id for mt in ms] for j, ms in group_jornadas([*j10, *j11, moved, lonely])}
    assert 99 in groups["J11"] and 99 not in groups["J10"]
    assert 98 in groups["J11"]
    assert len(groups["J10"]) == 8 and len(groups["J11"]) == 10


def test_password_hash_and_names():
    h = security.hash_password("secreto123")
    assert "secreto123" not in h
    assert security.verify_password("secreto123", h) and not security.verify_password("otra", h)
    assert security.display_name_key("  José   Pérez ") == "jose perez"
    assert security.display_name_problem("ab")
    assert security.display_name_problem("hola<script>")
    assert security.display_name_problem("Peña 10") is None


# ---------------------------------------------------------------------------------------------------
# Flujo completo por la API
# ---------------------------------------------------------------------------------------------------
@pytest.fixture()
def world(session, monkeypatch):
    """Liga simulada, modelo entrenado y una jornada futura del Apertura 2030."""
    load_simulated(session)
    service.run_and_store_backtest(session, SMALL_BT)
    service.train_production(session, NOW)
    load_events(session, [
        future_fixture("q1", 1, 2, NOW + timedelta(days=1), slug=SLUG),
        future_fixture("q2", 3, 4, NOW + timedelta(days=1, hours=2), slug=SLUG),
        future_fixture("q3", 5, 6, NOW + timedelta(days=2), slug=SLUG),
    ], NOW)
    assign_rounds(session)
    service.generate_predictions(session, NOW)
    session.commit()

    clock = {"now": NOW}
    monkeypatch.setattr(qapi, "_now", lambda: clock["now"])
    monkeypatch.setattr(get_settings(), "web_url", "https://quiniela.example")
    outbox = []
    monkeypatch.setattr(mailer, "send", lambda email: outbox.append(email) or True)
    for lim in (qapi.login_limiter, qapi.email_limiter, qapi.signup_limiter):
        lim.reset()
    return {"session": session, "clock": clock, "outbox": outbox, "client": TestClient(app)}


ADMIN = {"Authorization": "Bearer token-de-prueba"}


def _link_token(text: str) -> str:
    return text.split("token=")[1].split()[0]


def _request(c, email, name, password="clave-segura-1", **extra):
    return c.post("/api/auth/register", json={"display_name": name, "email": email, "password": password, **extra})


def _uid(c, email) -> int:
    return next(u["id"] for u in c.get("/api/admin/quiniela/users", headers=ADMIN).json()["items"]
                if u["email"] == email)


def _signup(w, email, name, password="clave-segura-1") -> dict:
    """Pide acceso, el administrador aprueba y la persona inicia sesión."""
    c = w["client"]
    r = _request(c, email, name, password)
    assert r.status_code == 201, r.text
    assert c.post(f"/api/admin/quiniela/users/{_uid(c, email)}/approve", headers=ADMIN).status_code == 200
    r = c.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def _ids(session):
    return {e: session.scalar(select(m.Match.id).where(m.Match.espn_id == e)) for e in ("q1", "q2", "q3")}


def test_request_approval_login_and_name(world):
    c, outbox = world["client"], world["outbox"]
    assert c.get("/api/auth/config").json() == {"registration_open": True, "invite_code_required": False,
                                                "email_enabled": False}
    assert _request(c, "a@x.com", "Ana", password="corta").status_code == 422
    assert _request(c, "a@x.com", "ab").status_code == 422
    assert _request(c, "a@x.com", "Modelo IA").status_code == 409
    r = _request(c, "Ana@X.com ", "Ana")
    assert r.status_code == 201 and r.json()["email_sent"] is False and not outbox  # sin servicio de correo
    assert _request(c, "ana@x.com", "Otra").status_code == 409  # correo repetido
    assert _request(c, "b@x.com", "ÁNA").status_code == 409  # nombre repetido (sin acentos ni mayúsculas)
    # pendiente de aprobación: no puede entrar
    r = c.post("/api/auth/login", json={"email": "ana@x.com", "password": "clave-segura-1"})
    assert r.status_code == 423
    users = c.get("/api/admin/quiniela/users", headers=ADMIN).json()
    assert users["pending"] == 1 and users["items"][0]["display_name"] == "Ana"
    assert c.post(f"/api/admin/quiniela/users/{_uid(c, 'ana@x.com')}/approve").status_code == 401  # solo admin
    c.post(f"/api/admin/quiniela/users/{_uid(c, 'ana@x.com')}/approve", headers=ADMIN)
    assert c.post("/api/auth/login", json={"email": "ana@x.com", "password": "mala-clave"}).status_code == 401
    r = c.post("/api/auth/login", json={"email": "ANA@x.com", "password": "clave-segura-1"})
    assert r.status_code == 200
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    me = c.get("/api/auth/me", headers=h).json()
    assert me["display_name"] == "Ana" and me["approved"]
    other = _signup(world, "beto@x.com", "Beto")
    assert c.put("/api/auth/me", json={"display_name": "ana"}, headers=other).status_code == 409
    assert c.put("/api/auth/me", json={"display_name": "Beto G"}, headers=other).json()["display_name"] == "Beto G"
    # la contraseña nunca se guarda en claro
    user = world["session"].scalar(select(m.User).where(m.User.email == "ana@x.com"))
    assert "clave-segura-1" not in user.password_hash
    assert c.post("/api/auth/logout", headers=h).status_code == 200
    assert c.get("/api/auth/me", headers=h).status_code == 401


def test_reject_request(world):
    c = world["client"]
    _request(c, "x@x.com", "Intruso")
    assert c.post(f"/api/admin/quiniela/users/{_uid(c, 'x@x.com')}/reject", headers=ADMIN).status_code == 200
    assert c.get("/api/admin/quiniela/users", headers=ADMIN).json()["items"] == []
    assert c.post("/api/auth/login", json={"email": "x@x.com", "password": "clave-segura-1"}).status_code == 401


def test_optional_invite_code_and_closed_registration(world, monkeypatch):
    c = world["client"]
    monkeypatch.setattr(get_settings(), "quiniela_invite_code", "Amigos2030")
    assert _request(c, "a@x.com", "Ana", invite_code="no").status_code == 403
    assert _request(c, "a@x.com", "Ana", invite_code=" amigos2030 ").status_code == 201
    monkeypatch.setattr(get_settings(), "quiniela_registration_open", False)
    assert _request(c, "b@x.com", "Beto", invite_code="Amigos2030").status_code == 503


def test_admin_reset_link(world):
    c = world["client"]
    _signup(world, "ana@x.com", "Ana")
    link = c.post(f"/api/admin/quiniela/users/{_uid(c, 'ana@x.com')}/link", headers=ADMIN).json()["link"]
    assert link.startswith("https://quiniela.example/quiniela/restablecer?token=")
    tok = _link_token(link)
    r = c.post("/api/auth/reset-password", json={"token": tok, "password": "nueva-clave-2"})
    assert r.status_code == 200 and r.json()["token"]
    assert c.post("/api/auth/reset-password", json={"token": tok, "password": "otra-3333"}).status_code == 400
    assert c.post("/api/auth/login", json={"email": "ana@x.com", "password": "clave-segura-1"}).status_code == 401
    assert c.post("/api/auth/login", json={"email": "ana@x.com", "password": "nueva-clave-2"}).status_code == 200


def test_with_email_service(world, monkeypatch):
    """Con servicio de correo: confirmar correo y recuperar contraseña sin ayuda del administrador."""
    c, outbox = world["client"], world["outbox"]
    monkeypatch.setattr(mailer, "configured", lambda: True)
    r = _request(c, "ana@x.com", "Ana")
    assert r.json()["email_sent"] and "confirmar?token=" in outbox[-1].text
    r = c.post("/api/auth/verify", json={"token": _link_token(outbox[-1].text)})
    assert r.status_code == 200 and r.json()["token"] is None  # confirmado, falta la aprobación
    assert c.post("/api/auth/login", json={"email": "ana@x.com", "password": "clave-segura-1"}).status_code == 423
    c.post(f"/api/admin/quiniela/users/{_uid(c, 'ana@x.com')}/approve", headers=ADMIN)
    assert c.post("/api/auth/forgot-password", json={"email": "nadie@x.com"}).status_code == 200
    n = len(outbox)
    c.post("/api/auth/forgot-password", json={"email": "ana@x.com"})
    assert len(outbox) == n + 1 and "restablecer?token=" in outbox[-1].text
    tok = _link_token(outbox[-1].text)
    world["clock"]["now"] = NOW + timedelta(hours=2)  # vence en 1 hora
    assert c.post("/api/auth/reset-password", json={"token": tok, "password": "otra-clave-3"}).status_code == 400


def test_picks_lock_visibility_and_tables(world):
    c, s, clock = world["client"], world["session"], world["clock"]
    ana = _signup(world, "ana@x.com", "Ana")
    beto = _signup(world, "beto@x.com", "Beto")
    ids = _ids(s)

    jj = c.get("/api/quiniela/jornadas", headers=ana).json()
    assert jj["tournament"] == "Apertura 2030"
    cur = jj["current"]
    assert next(j for j in jj["jornadas"] if j["key"] == cur)["missing_picks"] == 3

    def put(h, picks):
        return c.put("/api/quiniela/picks", headers=h, json={"picks": [
            {"match_id": ids[e], "home_goals": hg, "away_goals": ag} for e, hg, ag in picks]})

    assert put(ana, [("q1", 2, 1), ("q2", 0, 0), ("q3", 1, 1)]).json()["saved"] == [ids["q1"], ids["q2"], ids["q3"]]
    assert put(ana, [("q1", 3, 1)]).status_code == 200  # se puede cambiar antes del inicio
    put(beto, [("q1", 1, 0), ("q2", 1, 2), ("q3", 0, 0)])

    # antes del inicio nadie ve los pronósticos de los demás
    d = c.get(f"/api/quiniela/jornadas/{cur}", headers=beto).json()
    q1 = next(i for i in d["items"] if i["match"]["id"] == ids["q1"])
    assert q1["picks"] == [] and q1["my_pick"]["home"] == 1 and not q1["locked"]
    assert q1["model_pick"] is not None  # el modelo siempre muestra su marcador

    # empieza q1: queda cerrado y se ven los pronósticos de todos en ese partido (q2 sigue oculto)
    clock["now"] = NOW + timedelta(days=1, minutes=1)
    r = put(ana, [("q1", 0, 0), ("q2", 2, 2)]).json()
    assert r["saved"] == [ids["q2"]] and r["rejected"][0]["match_id"] == ids["q1"]
    d = c.get(f"/api/quiniela/jornadas/{cur}").json()  # sin sesión también se ve
    q1 = next(i for i in d["items"] if i["match"]["id"] == ids["q1"])
    q2 = next(i for i in d["items"] if i["match"]["id"] == ids["q2"])
    assert q1["locked"] and {p["display_name"]: (p["home"], p["away"]) for p in q1["picks"]} == {
        "Ana": (3, 1), "Beto": (1, 0)}
    assert q2["picks"] == []

    # resultados: q1 3-1 (Ana exacto, Beto ganador), q2 2-2 (Ana exacto con su cambio), q3 1-0 (nadie)
    kick = {e: s.scalar(select(m.Match.kickoff_utc).where(m.Match.espn_id == e)) for e in ids}
    load_events(s, [event(e, kick[e].replace(tzinfo=None), (str(h), f"Equipo {h}"), (str(a), f"Equipo {a}"),
                          status="STATUS_FULL_TIME", state="post", completed=True, hs=hs, as_=as_, slug=SLUG)
                    for e, h, a, hs, as_ in [("q1", 1, 2, 3, 1), ("q2", 3, 4, 2, 2), ("q3", 5, 6, 1, 0)]],
                NOW + timedelta(days=3))
    s.commit()
    clock["now"] = NOW + timedelta(days=3)

    t = c.get("/api/quiniela/tablas").json()
    rows = {r["display_name"]: r for r in t["rows"]}
    assert (rows["Ana"]["points"], rows["Ana"]["exact"], rows["Ana"]["outcome"]) == (6, 2, 0)
    assert (rows["Beto"]["points"], rows["Beto"]["exact"], rows["Beto"]["outcome"]) == (1, 0, 1)
    assert "Modelo (IA)" in rows and rows["Modelo (IA)"]["is_model"]
    jt = next(j for j in t["jornadas"] if j["key"] == cur)
    assert jt["finished"] and jt["winners"] == ["Ana"]
    assert rows["Ana"]["jornadas_won"] == 1
    assert not t["finished"]  # no hay final todavía

    d = c.get(f"/api/quiniela/jornadas/{cur}", headers=ana).json()
    pts = {i["match"]["id"]: i["my_pick"]["points"] for i in d["items"]}
    assert pts == {ids["q1"]: 3, ids["q2"]: 3, ids["q3"]: 0}


def test_tiebreak_more_exact_scores(world):
    from app.quiniela.service import Row, _rank

    a = Row(1, "A", points=4, exact=0)
    b = Row(2, "B", points=4, exact=1)
    c_ = Row(3, "C", points=4, exact=1)
    ranked = _rank([a, b, c_])
    assert [r["display_name"] for r in ranked] == ["B", "C", "A"]
    assert [r["position"] for r in ranked] == [1, 1, 3]


def test_crest_profile_picture(world):
    c = world["client"]
    crests = c.get("/api/auth/crests").json()
    assert crests and {"team_id", "name", "logo_url"} <= set(crests[0])
    team = crests[0]["team_id"]
    r = _request(c, "ana@x.com", "Ana", crest_team_id=team)
    assert r.status_code == 201
    assert _request(c, "b@x.com", "Beto", crest_team_id=999999).status_code == 422
    c.post(f"/api/admin/quiniela/users/{_uid(c, 'ana@x.com')}/approve", headers=ADMIN)
    h = {"Authorization": f"Bearer {c.post('/api/auth/login', json={'email': 'ana@x.com', 'password': 'clave-segura-1'}).json()['token']}"}
    me = c.get("/api/auth/me", headers=h).json()
    assert me["crest"]["team_id"] == team
    # cambiar solo el escudo no toca el nombre; se puede repetir el de otra persona
    other = crests[1]["team_id"]
    me = c.put("/api/auth/me", json={"crest_team_id": other}, headers=h).json()
    assert me["crest"]["team_id"] == other and me["display_name"] == "Ana"
    beto = _signup(world, "beto@x.com", "Beto")
    assert c.put("/api/auth/me", json={"crest_team_id": other}, headers=beto).json()["crest"]["team_id"] == other
    rows = {r["display_name"]: r for r in c.get("/api/quiniela/tablas").json()["rows"]}
    assert rows["Ana"]["crest_url"] == crests[1]["logo_url"]
    assert rows["Modelo (IA)"]["crest_url"] is None
    # quitarlo
    assert c.put("/api/auth/me", json={"crest_team_id": None}, headers=h).json()["crest"] is None
