"""Constructores de eventos con el MISMO FORMATO que la API de ESPN, solo para pruebas.

El formato replica los campos verificados el 2026-10-10 (ver app/sources/espn.py). Los equipos y
marcadores de estas pruebas son ficticios salvo donde se indica.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta


def event(eid: str, kickoff: datetime, home: tuple[str, str], away: tuple[str, str], status: str = "STATUS_SCHEDULED",
          state: str = "pre", completed: bool = False, hs: int | None = None, as_: int | None = None,
          slug: str = "torneo-apertura-2016", details: list | None = None, detail: str = "",
          pens: tuple[int, int] | None = None, notes: list[str] | None = None) -> dict:
    def comp(side, team, score, pen):
        c = {"homeAway": side, "score": "0" if score is None else str(score),
             "team": {"id": team[0], "displayName": team[1], "abbreviation": team[1][:3].upper(),
                      "logo": f"https://a.espncdn.com/i/teamlogos/soccer/500/{team[0]}.png"}}
        if pen is not None:
            c["shootoutScore"] = pen
        return c

    return {
        "id": eid,
        "date": kickoff.strftime("%Y-%m-%dT%H:%MZ"),
        "name": f"{away[1]} at {home[1]}",
        "season": {"year": kickoff.year, "type": 1, "slug": slug},
        "competitions": [{
            "date": kickoff.strftime("%Y-%m-%dT%H:%MZ"),
            "status": {"type": {"name": status, "state": state, "completed": completed,
                                "detail": detail, "shortDetail": detail}},
            "notes": [{"headline": n} for n in (notes or [])],
            "competitors": [comp("home", home, hs, pens[0] if pens else None),
                            comp("away", away, as_, pens[1] if pens else None)],
            "details": details or [],
            "broadcasts": [{"names": ["TV"]}],  # campo volátil que no debe archivarse
        }],
    }


def goal(minute: str, team_id: str, shootout: bool = False) -> dict:
    return {"clock": {"displayValue": minute}, "scoringPlay": True, "ownGoal": False, "penaltyKick": False,
            "shootout": shootout, "team": {"id": team_id}}


def final_2016_like() -> dict:
    """Estructura de la final del Apertura 2016 (Tigres–América, 1-1 tras prórroga, 3-0 en penales),
    tal como la devolvió ESPN al verificarla: goles en 95' y 119', estado STATUS_FINAL_PEN."""
    return event("468819", datetime(2016, 12, 26, 0, 30), ("232", "Tigres UANL"), ("227", "América"),
                 status="STATUS_FINAL_PEN", state="post", completed=True, hs=1, as_=1, slug="apertura-2016---final",
                 detail="FT-Pens", pens=(3, 0),
                 notes=["2nd Leg - Tied on aggregate - Tigres UANL advance 3-0 on penalties"],
                 details=[goal("95'", "227"), goal("119'", "232"), goal("120'", "232", True),
                          goal("120'", "232", True), goal("120'", "232", True)])


class FakeEspn:
    """Sustituto de EspnClient: devuelve eventos por día desde un diccionario modificable."""

    def __init__(self):
        self.by_day: dict[date, list[dict]] = {}
        self.fail = False
        self.calls = 0

    def put(self, ev: dict) -> None:
        d = datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").date()
        for k in list(self.by_day):
            self.by_day[k] = [e for e in self.by_day[k] if e["id"] != ev["id"]]
        self.by_day.setdefault(d, []).append(ev)

    def scoreboard(self, day: date) -> dict:
        from app.sources.http import SourceError

        self.calls += 1
        if self.fail:
            raise SourceError("fuente caída (simulada)")
        return {"events": list(self.by_day.get(day, []))}


def days(start: date, n: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(n)]
