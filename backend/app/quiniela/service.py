"""Reglas de la quiniela: jornadas, cierre de pronósticos, puntos y tablas.

Reglas (acordadas con el dueño del proyecto el 2026-10-10):
- Cada usuario pronostica el marcador de cada partido. Puede cambiarlo hasta que ese partido empieza.
- Marcador exacto: 3 puntos. Solo el ganador o el empate: 1 punto. Nada: 0 puntos.
- Se califica con el marcador a los 90 minutos (sin prórroga ni penales), como en las quinielas tradicionales.
- Los pronósticos de los demás se ven solo cuando el partido ya empezó.
- Desempate en las tablas: más marcadores exactos.
- El modelo de predicción juega como un participante más con su marcador más probable (la última
  predicción guardada antes del inicio), pero el ganador de la quiniela es el mejor participante humano.
- La liguilla cuenta con puntos multiplicados por QUINIELA_LIGUILLA_MULTIPLIER (1 = puntos normales).

Los puntos no se guardan: se calculan cada vez con los resultados confirmados, así que una corrección de
la fuente se refleja sola.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import models as m
from app.config import get_settings
from app.predict.service import latest_pre_kickoff

EXACT_POINTS = 3
OUTCOME_POINTS = 1
MODEL_NAME = "Modelo (IA)"

LIGUILLA_ROUNDS = [  # (clave, nombre, orden, palabras en stage_detail)
    ("playin", "Play-In", 100, ()),
    ("cuartos", "Cuartos de final", 101, ("quarter", "cuartos")),
    ("semis", "Semifinales", 102, ("semi",)),
    ("final", "Final", 103, ("final",)),
]


@dataclass(frozen=True)
class Jornada:
    key: str
    label: str
    order: int
    liguilla: bool


def jornada_of(mt: m.Match) -> Jornada | None:
    if mt.stage == "regular":
        return Jornada(f"J{mt.round}", f"Jornada {mt.round}", mt.round, False) if mt.round else None
    detail = (mt.stage_detail or "").lower()
    if mt.stage == "liguilla":
        # "semi" y "quarter" se revisan antes que "final" porque "Semifinals" también contiene "final".
        for key, label, order, words in LIGUILLA_ROUNDS[1:]:
            if any(w in detail for w in words):
                return Jornada(key, label, order, True)
    key, label, order, _ = LIGUILLA_ROUNDS[0]  # repechajes / play-in
    return Jornada(key, label, order, True)


def is_locked(mt: m.Match, now: datetime) -> bool:
    """Cada partido se cierra a su hora de inicio (o antes, si la fuente ya lo marca en juego)."""
    return mt.kickoff_utc <= now or mt.status in (m.IN_PROGRESS, m.FINISHED, m.SUSPENDED, m.CANCELED)


def is_scored(mt: m.Match) -> bool:
    return mt.status == m.FINISHED and mt.home_goals is not None and mt.away_goals is not None


def _sign(h: int, a: int) -> int:
    return (h > a) - (h < a)


def pick_points(ph: int, pa: int, hg: int, ag: int, multiplier: int = 1) -> tuple[int, str]:
    """Puntos de un pronóstico (ph-pa) contra el resultado a los 90' (hg-ag)."""
    if (ph, pa) == (hg, ag):
        return EXACT_POINTS * multiplier, "exacto"
    if _sign(ph, pa) == _sign(hg, ag):
        return OUTCOME_POINTS * multiplier, "resultado"
    return 0, "fallo"


def multiplier_for(mt: m.Match) -> int:
    j = jornada_of(mt)
    return max(1, get_settings().quiniela_liguilla_multiplier) if j and j.liguilla else 1


def score_match(mt: m.Match, home: int, away: int) -> tuple[int, str] | None:
    if not is_scored(mt):
        return None
    return pick_points(home, away, mt.home_goals, mt.away_goals, multiplier_for(mt))


# ---------------------------------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------------------------------
def tournament_matches(session: Session, tournament: str) -> list[m.Match]:
    rows = session.scalars(select(m.Match).options(joinedload(m.Match.home_team), joinedload(m.Match.away_team))
                           .where(m.Match.tournament == tournament, m.Match.status != m.CANCELED)
                           .order_by(m.Match.kickoff_utc, m.Match.id)).all()
    return [r for r in rows if jornada_of(r) is not None]


def group_jornadas(matches: list[m.Match]) -> list[tuple[Jornada, list[m.Match]]]:
    groups: dict[Jornada, list[m.Match]] = defaultdict(list)
    for mt in matches:
        groups[jornada_of(mt)].append(mt)
    return sorted(groups.items(), key=lambda kv: kv[0].order)


def current_jornada_key(groups: list[tuple[Jornada, list[m.Match]]], now: datetime) -> str | None:
    """La primera jornada con al menos la mitad de sus partidos abiertos (un partido reprogramado no
    deja "atorada" la jornada vieja); si no hay, la primera con algo abierto; si no, la última."""
    open_counts = [(j, sum(not is_locked(mt, now) for mt in ms), len(ms)) for j, ms in groups]
    for j, n_open, n in open_counts:
        if n_open and n_open * 2 >= n:
            return j.key
    for j, n_open, _ in open_counts:
        if n_open:
            return j.key
    return groups[-1][0].key if groups else None


def participants(session: Session) -> list[m.User]:
    """Usuarios aprobados por el administrador y con nombre."""
    return list(session.scalars(select(m.User).where(m.User.approved_at.is_not(None),
                                                     m.User.display_name.is_not(None))
                                .order_by(m.User.display_name_key)))


def user_picks(session: Session, match_ids: list[int], user_ids: list[int] | None = None
               ) -> dict[tuple[int, int], m.QuinielaPick]:
    """Pronósticos por (user_id, match_id)."""
    if not match_ids:
        return {}
    q = select(m.QuinielaPick).where(m.QuinielaPick.match_id.in_(match_ids))
    if user_ids is not None:
        q = q.where(m.QuinielaPick.user_id.in_(user_ids))
    return {(p.user_id, p.match_id): p for p in session.scalars(q)}


def model_picks(session: Session, match_ids: list[int]) -> dict[int, tuple[int, int]]:
    """Marcador más probable de la última predicción guardada antes del inicio de cada partido."""
    preds = latest_pre_kickoff(session, match_ids)
    return {mid: (p.top_score_home, p.top_score_away) for mid, p in preds.items()
            if p.top_score_home is not None and p.top_score_away is not None}


# ---------------------------------------------------------------------------------------------------
# Tablas
# ---------------------------------------------------------------------------------------------------
@dataclass
class Row:
    user_id: int | None
    display_name: str
    is_model: bool = False
    points: int = 0
    exact: int = 0
    outcome: int = 0
    scored_picks: int = 0
    pending_picks: int = 0
    jornadas_won: int = 0
    by_jornada: dict[str, int] = field(default_factory=dict)

    def add(self, jornada: str, result: tuple[int, str] | None) -> None:
        if result is None:
            self.pending_picks += 1
            return
        pts, kind = result
        self.points += pts
        self.scored_picks += 1
        self.exact += kind == "exacto"
        self.outcome += kind == "resultado"
        self.by_jornada[jornada] = self.by_jornada.get(jornada, 0) + pts


def _rank(rows: list[Row]) -> list[dict]:
    rows = sorted(rows, key=lambda r: (-r.points, -r.exact, r.is_model, r.display_name.lower()))
    out, pos, prev = [], 0, None
    for i, r in enumerate(rows, 1):
        if (r.points, r.exact) != prev:
            pos, prev = i, (r.points, r.exact)
        out.append({"position": pos, "user_id": r.user_id, "display_name": r.display_name, "is_model": r.is_model,
                    "points": r.points, "exact": r.exact, "outcome": r.outcome, "scored_picks": r.scored_picks,
                    "pending_picks": r.pending_picks, "jornadas_won": r.jornadas_won, "by_jornada": r.by_jornada})
    return out


def _winners(ranked: list[dict]) -> list[str]:
    humans = [r for r in ranked if not r["is_model"] and r["scored_picks"] > 0]
    if not humans:
        return []
    best = (humans[0]["points"], humans[0]["exact"])
    return [r["display_name"] for r in humans if (r["points"], r["exact"]) == best]


def build_tables(session: Session, tournament: str, now: datetime) -> dict:
    """Tabla de cada jornada y tabla general acumulada del torneo."""
    groups = group_jornadas(tournament_matches(session, tournament))
    users = participants(session)
    match_ids = [mt.id for _, ms in groups for mt in ms]
    picks = user_picks(session, match_ids, [u.id for u in users])
    bot = model_picks(session, match_ids)

    general = {u.id: Row(u.id, u.display_name) for u in users}
    general_model = Row(None, MODEL_NAME, is_model=True)
    jornadas = []
    for j, ms in groups:
        rows = {u.id: Row(u.id, u.display_name) for u in users}
        model_row = Row(None, MODEL_NAME, is_model=True)
        for mt in ms:
            for u in users:
                p = picks.get((u.id, mt.id))
                if p is not None:
                    res = score_match(mt, p.home_goals, p.away_goals)
                    rows[u.id].add(j.key, res)
                    general[u.id].add(j.key, res)
            if mt.id in bot:
                res = score_match(mt, *bot[mt.id])
                model_row.add(j.key, res)
                general_model.add(j.key, res)
        finished = all(is_scored(mt) for mt in ms)
        ranked = _rank([*rows.values(), model_row])
        winners = _winners(ranked) if finished else []
        for row in general.values():
            if row.display_name in winners:
                row.jornadas_won += 1
        jornadas.append({"key": j.key, "label": j.label, "liguilla": j.liguilla, "matches": len(ms),
                         "finished_matches": sum(is_scored(mt) for mt in ms), "finished": finished,
                         "winners": winners, "rows": ranked})
    ranked = _rank([*general.values(), general_model])
    has_final = any(j.key == "final" for j, _ in groups)
    finished = bool(groups) and has_final and all(is_scored(mt) for _, ms in groups for mt in ms)
    return {"tournament": tournament, "finished": finished, "winners": _winners(ranked) if finished else [],
            "rows": ranked, "jornadas": jornadas}
