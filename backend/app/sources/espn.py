"""Adaptador de la API pública de ESPN para la Liga MX (liga `mex.1`).

Endpoint: {base}/scoreboard?dates=YYYYMMDD  → partidos de ese día (hora UTC de ESPN).
La API no está documentada oficialmente; toda la interpretación del JSON vive en este archivo
para que un cambio de formato se corrija en un solo lugar. Campos verificados el 2026-10-10:
  event.id, event.date ("2016-10-15T22:00Z"), event.season.slug ("torneo-apertura-2016",
  "apertura-2016---final"), competitions[0].status.type.{name,state,completed,detail},
  competitors[].{homeAway,score,shootoutScore,team.{id,displayName,abbreviation,logo}},
  competitions[0].details[].{clock.displayValue,scoringPlay,ownGoal,shootout,team.id},
  competitions[0].notes[].headline.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app import models as m
from app.config import get_settings
from app.sources.http import PoliteClient

SOURCE = "espn"

# Mapeo de status.type.name de ESPN → estado normalizado.
_STATUS_MAP = {
    "STATUS_SCHEDULED": m.SCHEDULED,
    "STATUS_DELAYED": m.SCHEDULED,
    "STATUS_POSTPONED": m.POSTPONED,
    "STATUS_CANCELED": m.CANCELED,
    "STATUS_CANCELLED": m.CANCELED,
    "STATUS_ABANDONED": m.SUSPENDED,
    "STATUS_SUSPENDED": m.SUSPENDED,
    "STATUS_FORFEIT": m.SUSPENDED,
    "STATUS_FULL_TIME": m.FINISHED,
    "STATUS_FINAL": m.FINISHED,
    "STATUS_FINAL_AET": m.FINISHED,
    "STATUS_FINAL_PEN": m.FINISHED,
}
# Estados finales donde pudo haber prórroga: el marcador de ESPN incluye los goles de la prórroga.
_POSSIBLE_EXTRA_TIME = {"STATUS_FINAL_AET", "STATUS_FINAL_PEN"}

_LIGUILLA_WORDS = ("final", "semifinal", "quarterfinal", "cuartos", "liguilla", "playoff", "round of")
_PLAYIN_WORDS = ("play-in", "playin", "reclasificacion", "reclasificación", "repechaje", "wild card")


@dataclass
class ParsedTeam:
    espn_id: str
    name: str
    abbreviation: str | None
    logo_url: str | None


@dataclass
class ParsedMatch:
    espn_id: str
    kickoff_utc: datetime
    season: str
    tournament: str
    stage: str
    stage_detail: str | None
    home: ParsedTeam
    away: ParsedTeam
    status: str
    status_detail: str | None
    source_status: str
    live_clock: str | None
    home_goals: int | None  # 90 minutos
    away_goals: int | None
    home_goals_final: int | None
    away_goals_final: int | None
    home_penalties: int | None
    away_penalties: int | None
    extra_time: bool
    issues: list[tuple[str, str, str]] = field(default_factory=list)  # (severidad, código, mensaje)


def strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def parse_kickoff(value: str) -> datetime:
    # ESPN usa "2016-10-15T22:00Z" (sin segundos).
    value = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def tournament_from(slug: str | None, kickoff_utc: datetime) -> tuple[str, str]:
    """Devuelve (torneo, temporada). Ej.: ("Apertura 2016", "2016-17").

    Se usa el slug de ESPN si nombra el torneo; si no, la fecha local (jul–dic = Apertura).
    """
    local = kickoff_utc.astimezone(ZoneInfo(get_settings().local_tz))
    kind, year = None, None
    if slug:
        s = strip_accents(slug.lower())
        mt = re.search(r"(apertura|clausura|guard1anes)[^0-9]*(\d{4})", s)
        if mt:
            kind = "Clausura" if mt.group(1) == "clausura" else "Apertura"
            year = int(mt.group(2))
    if kind is None:
        # Las finales del Apertura pueden caer en enero en horario UTC raro; se toma la fecha local.
        kind = "Apertura" if local.month >= 7 else "Clausura"
        year = local.year
    season = f"{year}-{str(year + 1)[-2:]}" if kind == "Apertura" else f"{year - 1}-{str(year)[-2:]}"
    return f"{kind} {year}", season


def stage_from(slug: str | None, notes: list[str]) -> tuple[str, str | None]:
    text = strip_accents(" ".join([slug or "", *notes]).lower())
    if any(w in text for w in _PLAYIN_WORDS):
        return "play-in", _detail(slug, notes)
    # El slug de fase regular es "torneo-apertura-2016"; las eliminatorias llevan sufijo ("---final").
    if slug and "---" in slug:
        return "liguilla", _detail(slug, notes)
    if any(w in text for w in _LIGUILLA_WORDS) and not (slug or "").startswith("torneo-"):
        return "liguilla", _detail(slug, notes)
    return "regular", None


def _detail(slug: str | None, notes: list[str]) -> str | None:
    if slug and "---" in slug:
        return slug.split("---", 1)[1].replace("-", " ").strip().title() or None
    return notes[0][:80] if notes else None


def _minute_base(display: str | None) -> int | None:
    """"90'+3'" → 90; "105'+1'" → 105; "7'" → 7."""
    if not display:
        return None
    mt = re.match(r"\s*(\d+)", display)
    return int(mt.group(1)) if mt else None


def _int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def parse_event(event: dict) -> ParsedMatch:
    comp = (event.get("competitions") or [{}])[0]
    competitors = comp.get("competitors") or []
    by_side = {c.get("homeAway"): c for c in competitors}
    if set(by_side) != {"home", "away"}:
        raise ValueError(f"evento {event.get('id')}: no tiene local y visitante")

    def team(c: dict) -> ParsedTeam:
        t = c.get("team") or {}
        return ParsedTeam(
            espn_id=str(t.get("id")),
            name=t.get("displayName") or t.get("name") or t.get("shortDisplayName") or "?",
            abbreviation=t.get("abbreviation"),
            logo_url=t.get("logo"),
        )

    home, away = team(by_side["home"]), team(by_side["away"])
    kickoff = parse_kickoff(event.get("date") or comp.get("date"))
    slug = (event.get("season") or {}).get("slug")
    notes = [n.get("headline", "") for n in comp.get("notes") or [] if isinstance(n, dict)]
    tournament, season = tournament_from(slug, kickoff)
    stage, stage_detail = stage_from(slug, notes)

    stype = (comp.get("status") or event.get("status") or {}).get("type") or {}
    source_status = stype.get("name") or "UNKNOWN"
    state = stype.get("state")
    status = _STATUS_MAP.get(source_status)
    if status is None:
        status = {"pre": m.SCHEDULED, "in": m.IN_PROGRESS}.get(state, m.SCHEDULED)
        if state == "post":
            status = m.FINISHED if stype.get("completed") else m.SUSPENDED
    detail = stype.get("shortDetail") or stype.get("detail")
    issues: list[tuple[str, str, str]] = []

    hs, as_ = _int(by_side["home"].get("score")), _int(by_side["away"].get("score"))
    pm = ParsedMatch(
        espn_id=str(event["id"]),
        kickoff_utc=kickoff,
        season=season,
        tournament=tournament,
        stage=stage,
        stage_detail=stage_detail,
        home=home,
        away=away,
        status=status,
        status_detail=detail,
        source_status=source_status,
        live_clock=detail if status == m.IN_PROGRESS else None,
        home_goals=None,
        away_goals=None,
        home_goals_final=None,
        away_goals_final=None,
        home_penalties=_int(by_side["home"].get("shootoutScore")),
        away_penalties=_int(by_side["away"].get("shootoutScore")),
        extra_time=False,
        issues=issues,
    )
    if status in (m.FINISHED, m.IN_PROGRESS):
        pm.home_goals_final, pm.away_goals_final = hs, as_
        if hs is None or as_ is None:
            issues.append(("error", "missing_score", f"Estado {source_status} sin marcador"))
    if status == m.FINISHED and hs is not None and as_ is not None:
        _set_regulation_score(pm, comp, source_status, by_side)
    return pm


def _set_regulation_score(pm: ParsedMatch, comp: dict, source_status: str, by_side: dict) -> None:
    """Calcula el marcador a los 90' a partir de la lista de goles (details).

    Los goles de ESPN se acreditan al equipo beneficiado (también en autogoles). Se valida que la suma de
    todos los goles (sin tanda de penales) coincida con el marcador final; si no coincide, el marcador a 90'
    se deja vacío y se registra un problema en lugar de adivinar.
    """
    home_id, away_id = pm.home.espn_id, pm.away.espn_id
    goals = [
        d for d in comp.get("details") or []
        if d.get("scoringPlay") and not d.get("shootout")
    ]
    tot = {home_id: 0, away_id: 0}
    reg = {home_id: 0, away_id: 0}
    max_minute = 0
    for g in goals:
        tid = str((g.get("team") or {}).get("id"))
        minute = _minute_base((g.get("clock") or {}).get("displayValue"))
        if tid not in tot or minute is None:
            continue
        tot[tid] += 1
        max_minute = max(max_minute, minute)
        if minute <= 90:
            reg[tid] += 1
    details_consistent = goals and tot[home_id] == pm.home_goals_final and tot[away_id] == pm.away_goals_final

    went_extra = source_status == "STATUS_FINAL_AET" or (
        source_status == "STATUS_FINAL_PEN" and (max_minute > 90 or "aet" in (pm.status_detail or "").lower())
    )
    if source_status not in _POSSIBLE_EXTRA_TIME:
        pm.home_goals, pm.away_goals = pm.home_goals_final, pm.away_goals_final
        if goals and not details_consistent:
            pm.issues.append(("info", "details_mismatch",
                              "La lista de goles no coincide con el marcador final; se usa el marcador final"))
        return
    if pm.home_goals_final == 0 and pm.away_goals_final == 0:
        pm.home_goals, pm.away_goals = 0, 0
        pm.extra_time = went_extra
        return
    if details_consistent:
        pm.home_goals, pm.away_goals = reg[home_id], reg[away_id]
        pm.extra_time = went_extra or (reg != tot)
        return
    pm.extra_time = True
    pm.issues.append(("warning", "regulation_score_unknown",
                      "Partido con posible prórroga y sin lista de goles consistente: no se conoce el marcador a 90'"))


class EspnClient:
    def __init__(self, client: PoliteClient | None = None):
        self.base = get_settings().espn_base_url.rstrip("/")
        self.http = client or PoliteClient()

    def scoreboard(self, day: date) -> dict:
        return self.http.get_json(f"{self.base}/scoreboard", params={"dates": day.strftime("%Y%m%d")})

    def events_between(self, start: date, end: date):
        """Itera (día, evento crudo) día por día. Un día por consulta es lo verificado como fiable."""
        day = start
        while day <= end:
            payload = self.scoreboard(day)
            for ev in payload.get("events") or []:
                yield day, ev
            day += timedelta(days=1)


def slim_event(event: dict) -> dict:
    """Subconjunto del evento que se archiva como dato crudo (evita guardar enlaces, cuotas y transmisiones).

    Contiene todo lo que usa `parse_event`, de modo que `parse_event(slim_event(ev))` == `parse_event(ev)`.
    """
    comp = (event.get("competitions") or [{}])[0]
    return {
        "id": event.get("id"),
        "date": event.get("date"),
        "name": event.get("name"),
        "season": event.get("season"),
        "competitions": [{
            "date": comp.get("date"),
            "status": comp.get("status"),
            "notes": comp.get("notes"),
            "competitors": [
                {
                    "homeAway": c.get("homeAway"),
                    "score": c.get("score"),
                    "shootoutScore": c.get("shootoutScore"),
                    "winner": c.get("winner"),
                    "team": {k: (c.get("team") or {}).get(k) for k in ("id", "displayName", "abbreviation", "logo")},
                }
                for c in comp.get("competitors") or []
            ],
            "details": [
                {
                    "clock": {"displayValue": (d.get("clock") or {}).get("displayValue")},
                    "scoringPlay": d.get("scoringPlay"),
                    "ownGoal": d.get("ownGoal"),
                    "penaltyKick": d.get("penaltyKick"),
                    "shootout": d.get("shootout"),
                    "team": {"id": (d.get("team") or {}).get("id")},
                }
                for d in comp.get("details") or [] if d.get("scoringPlay")
            ],
        }],
        "status": event.get("status"),
    }


# ---------------------------------------------------------------------------------------------------
# Marcador en vivo
# ---------------------------------------------------------------------------------------------------
# Campos verificados el 2026-10-10 con partidos en juego: competitions[0].status.{clock (segundos de juego,
# se queda en 2700 durante el añadido del 1er tiempo y en el descanso), displayClock ("45'+4'"), period (1, 2;
# 3-4 = prórroga), type.name (STATUS_FIRST_HALF, STATUS_HALFTIME, STATUS_SECOND_HALF…)} y
# details[].{redCard, team.id}.
@dataclass
class LiveState:
    espn_id: str
    state: str  # pre | in | post (de ESPN)
    source_status: str
    period: int
    clock_seconds: float
    display_clock: str | None
    detail: str | None
    home_goals: int | None  # marcador actual de la fuente (incluye prórroga si la hay)
    away_goals: int | None
    home_red: int
    away_red: int


def parse_live(event: dict) -> LiveState:
    comp = (event.get("competitions") or [{}])[0]
    by_side = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    if set(by_side) != {"home", "away"}:
        raise ValueError(f"evento {event.get('id')}: no tiene local y visitante")
    st = comp.get("status") or event.get("status") or {}
    stype = st.get("type") or {}
    home_id = str((by_side["home"].get("team") or {}).get("id"))
    away_id = str((by_side["away"].get("team") or {}).get("id"))
    reds = {home_id: 0, away_id: 0}
    for d in comp.get("details") or []:
        tid = str((d.get("team") or {}).get("id"))
        if d.get("redCard") and tid in reds:
            reds[tid] += 1
    state = stype.get("state") or "pre"
    return LiveState(
        espn_id=str(event.get("id")),
        state=state if state in ("pre", "in", "post") else "pre",
        source_status=stype.get("name") or "UNKNOWN",
        period=_int(st.get("period")) or 0,
        clock_seconds=float(st.get("clock") or 0),
        display_clock=st.get("displayClock"),
        detail=stype.get("shortDetail") or stype.get("detail"),
        home_goals=_int(by_side["home"].get("score")) if state != "pre" else None,
        away_goals=_int(by_side["away"].get("score")) if state != "pre" else None,
        home_red=reds[home_id],
        away_red=reds[away_id],
    )
