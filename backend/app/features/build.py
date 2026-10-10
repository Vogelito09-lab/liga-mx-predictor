"""Ingeniería de características sin fuga de información.

Todas las variables de un partido se calculan con el estado de los equipos ANTES de su hora de inicio:
los partidos se recorren en orden cronológico y, para cada hora de inicio, primero se calculan las
variables de todos los partidos que empiezan a esa hora y solo después se incorporan sus resultados.

Disponibilidad de cada variable (todas se conocen antes del saque inicial):
- Elo, forma reciente, goles, puntos, rendimiento local/visitante, H2H, torneo actual:
  resultados de partidos con hora de inicio estrictamente anterior.
- Días de descanso: fecha del último partido de Liga MX del equipo (no incluye Copa/Concacaf: limitación).
- Fase (regular/liguilla): conocida desde la publicación del calendario.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

LEAGUE_HOME_GOALS = 1.55  # valores iniciales; se sustituyen por promedios observados en el recorrido
LEAGUE_AWAY_GOALS = 1.15


@dataclass(frozen=True)
class FeatureParams:
    elo_k: float = 20.0
    elo_home_adv: float = 60.0
    elo_new_team: float = 1450.0  # equipo sin historial (p. ej. ascendido): algo por debajo de la media
    elo_regress: float = 0.20  # regresión a la media entre torneos (cambios de plantilla)
    ewm_half_life: float = 8.0  # partidos; ponderación temporal de goles
    h2h_n: int = 6
    short_window: int = 5
    long_window: int = 10

    def as_dict(self) -> dict:
        return asdict(self)


FEATURE_COLUMNS = [
    "elo_home", "elo_away", "elo_diff",
    "h_ppg5", "a_ppg5", "h_ppg10", "a_ppg10",
    "h_gf5", "h_ga5", "a_gf5", "a_ga5",
    "h_gf10", "h_ga10", "a_gf10", "a_ga10",
    "h_home_ppg5", "h_home_gf5", "h_home_ga5",
    "a_away_ppg5", "a_away_gf5", "a_away_ga5",
    "h_ewm_gf", "h_ewm_ga", "a_ewm_gf", "a_ewm_ga",
    "h_tour_ppg", "a_tour_ppg", "h_tour_gd", "a_tour_gd", "h_tour_played", "a_tour_played",
    "h2h_n", "h2h_home_pts",
    "h_rest", "a_rest",
    "h_trend", "a_trend",
    "is_liguilla",
]


def elo_expected(diff: float) -> float:
    return 1.0 / (1.0 + 10 ** (-diff / 400.0))


class _TeamState:
    __slots__ = ("results", "home_results", "away_results", "ewm_gf", "ewm_ga", "last_kickoff", "tour")

    def __init__(self, maxlen: int):
        self.results: deque = deque(maxlen=maxlen)  # (gf, ga, pts)
        self.home_results: deque = deque(maxlen=maxlen)
        self.away_results: deque = deque(maxlen=maxlen)
        self.ewm_gf: float | None = None
        self.ewm_ga: float | None = None
        self.last_kickoff = None
        self.tour: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])  # torneo -> [jugados, pts, dif]


def _pts(gf: int, ga: int) -> int:
    return 3 if gf > ga else (1 if gf == ga else 0)


def _agg(dq: deque, n: int, idx: int, default: float) -> float:
    items = list(dq)[-n:]
    if not items:
        return default
    return float(np.mean([r[idx] for r in items]))


class FeatureBuilder:
    """Recorre partidos ordenados y produce variables pre-partido + ratings Elo."""

    def __init__(self, params: FeatureParams | None = None):
        self.p = params or FeatureParams()
        self.teams: dict[int, _TeamState] = {}
        self.elo: dict[int, float] = {}
        self.h2h: dict[tuple[int, int], deque] = defaultdict(lambda: deque(maxlen=self.p.h2h_n))
        self.current_tournament: str | None = None
        self.goal_sums = [0.0, 0.0, 0]  # goles local, visitante, partidos
        self.elo_history: list[tuple] = []  # (match_id, kickoff, team_id, elo_after)

    # --- utilidades --------------------------------------------------------------------------------
    def _team(self, tid: int) -> _TeamState:
        if tid not in self.teams:
            self.teams[tid] = _TeamState(self.p.long_window)
            self.elo[tid] = self.p.elo_new_team
        return self.teams[tid]

    def league_avgs(self) -> tuple[float, float]:
        hg, ag, n = self.goal_sums
        if n < 50:
            return LEAGUE_HOME_GOALS, LEAGUE_AWAY_GOALS
        return hg / n, ag / n

    def _new_tournament(self, tournament: str) -> None:
        """Al empezar un torneo, los Elo regresan parcialmente a la media (plantillas cambian)."""
        if self.current_tournament is not None and tournament != self.current_tournament and self.elo:
            mean = float(np.mean(list(self.elo.values())))
            for tid in self.elo:
                self.elo[tid] = mean + (self.elo[tid] - mean) * (1 - self.p.elo_regress)
        self.current_tournament = tournament

    # --- variables de un partido ----------------------------------------------------------------------
    def features_for(self, home: int, away: int, kickoff, tournament: str, stage: str) -> dict:
        p = self.p
        h, a = self._team(home), self._team(away)
        lh, la = self.league_avgs()
        mean_goals = (lh + la) / 2
        prior_ppg = 1.2  # respaldo para equipos sin historial: algo por debajo de la media de la liga (~1.37)

        def rest(st: _TeamState) -> float:
            if st.last_kickoff is None:
                return 14.0
            return float(min((kickoff - st.last_kickoff).total_seconds() / 86400.0, 30.0))

        def tour(st: _TeamState):
            played, pts, gd = st.tour[tournament]
            if played == 0:
                # Primeras jornadas: se usa la forma de los últimos 10 partidos como respaldo.
                return _agg(st.results, p.long_window, 2, prior_ppg), 0.0, 0
            return pts / played, gd / played, played

        def trend(st: _TeamState) -> float:
            return _agg(st.results, p.short_window, 2, prior_ppg) - _agg(st.results, p.long_window, 2, prior_ppg)

        h2h = list(self.h2h[(min(home, away), max(home, away))])
        h2h_pts = [(_pts(r[1], r[2]) if r[0] == home else _pts(r[2], r[1])) for r in h2h]
        eh, ea = self.elo[home], self.elo[away]
        ht, at = tour(h), tour(a)
        return {
            "elo_home": eh, "elo_away": ea, "elo_diff": eh + p.elo_home_adv - ea,
            "h_ppg5": _agg(h.results, p.short_window, 2, prior_ppg),
            "a_ppg5": _agg(a.results, p.short_window, 2, prior_ppg),
            "h_ppg10": _agg(h.results, p.long_window, 2, prior_ppg),
            "a_ppg10": _agg(a.results, p.long_window, 2, prior_ppg),
            "h_gf5": _agg(h.results, p.short_window, 0, mean_goals),
            "h_ga5": _agg(h.results, p.short_window, 1, mean_goals),
            "a_gf5": _agg(a.results, p.short_window, 0, mean_goals),
            "a_ga5": _agg(a.results, p.short_window, 1, mean_goals),
            "h_gf10": _agg(h.results, p.long_window, 0, mean_goals),
            "h_ga10": _agg(h.results, p.long_window, 1, mean_goals),
            "a_gf10": _agg(a.results, p.long_window, 0, mean_goals),
            "a_ga10": _agg(a.results, p.long_window, 1, mean_goals),
            "h_home_ppg5": _agg(h.home_results, p.short_window, 2, prior_ppg),
            "h_home_gf5": _agg(h.home_results, p.short_window, 0, lh),
            "h_home_ga5": _agg(h.home_results, p.short_window, 1, la),
            "a_away_ppg5": _agg(a.away_results, p.short_window, 2, prior_ppg),
            "a_away_gf5": _agg(a.away_results, p.short_window, 0, la),
            "a_away_ga5": _agg(a.away_results, p.short_window, 1, lh),
            "h_ewm_gf": h.ewm_gf if h.ewm_gf is not None else mean_goals,
            "h_ewm_ga": h.ewm_ga if h.ewm_ga is not None else mean_goals,
            "a_ewm_gf": a.ewm_gf if a.ewm_gf is not None else mean_goals,
            "a_ewm_ga": a.ewm_ga if a.ewm_ga is not None else mean_goals,
            "h_tour_ppg": ht[0], "a_tour_ppg": at[0],
            "h_tour_gd": ht[1], "a_tour_gd": at[1],
            "h_tour_played": ht[2], "a_tour_played": at[2],
            "h2h_n": len(h2h),
            "h2h_home_pts": float(np.mean(h2h_pts)) if h2h_pts else 1.37,
            "h_rest": rest(h), "a_rest": rest(a),
            "h_trend": trend(h), "a_trend": trend(a),
            "is_liguilla": 0.0 if stage == "regular" else 1.0,
        }

    # --- incorporar un resultado ---------------------------------------------------------------------
    def update(self, match_id, home: int, away: int, hg: int, ag: int, kickoff, tournament: str) -> None:
        p = self.p
        h, a = self._team(home), self._team(away)
        hp, ap = _pts(hg, ag), _pts(ag, hg)
        h.results.append((hg, ag, hp))
        a.results.append((ag, hg, ap))
        h.home_results.append((hg, ag, hp))
        a.away_results.append((ag, hg, ap))
        alpha = 1 - 0.5 ** (1 / p.ewm_half_life)
        for st, gf, ga in ((h, hg, ag), (a, ag, hg)):
            st.ewm_gf = gf if st.ewm_gf is None else (1 - alpha) * st.ewm_gf + alpha * gf
            st.ewm_ga = ga if st.ewm_ga is None else (1 - alpha) * st.ewm_ga + alpha * ga
            st.last_kickoff = kickoff
        for st, pts, gd in ((h, hp, hg - ag), (a, ap, ag - hg)):
            t = st.tour[tournament]
            t[0] += 1
            t[1] += pts
            t[2] += gd
        self.h2h[(min(home, away), max(home, away))].append((home, hg, ag))
        self.goal_sums[0] += hg
        self.goal_sums[1] += ag
        self.goal_sums[2] += 1
        # Elo con multiplicador por diferencia de goles.
        exp_h = elo_expected(self.elo[home] + p.elo_home_adv - self.elo[away])
        score_h = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        mult = math.log(abs(hg - ag) + 1) + 1.0
        delta = p.elo_k * mult * (score_h - exp_h)
        self.elo[home] += delta
        self.elo[away] -= delta
        self.elo_history.append((match_id, kickoff, home, self.elo[home]))
        self.elo_history.append((match_id, kickoff, away, self.elo[away]))


def build_features(matches: pd.DataFrame, params: FeatureParams | None = None,
                   return_builder: bool = False):
    """Calcula variables pre-partido para TODOS los partidos de `matches`.

    `matches` necesita: match_id, kickoff (datetime UTC), tournament, stage, home_id, away_id,
    hg, ag (goles a 90'; NaN si no se jugó o no se conoce). Solo los partidos con hg/ag conocidos
    actualizan el estado. Devuelve un DataFrame indexado por match_id con FEATURE_COLUMNS.
    """
    builder = FeatureBuilder(params)
    df = matches.sort_values(["kickoff", "match_id"]).reset_index(drop=True)
    rows: list[dict] = []
    for _, group in df.groupby("kickoff", sort=True):
        for r in group.itertuples(index=False):
            builder._new_tournament(r.tournament)
            feats = builder.features_for(r.home_id, r.away_id, r.kickoff, r.tournament, r.stage)
            feats["match_id"] = r.match_id
            rows.append(feats)
        for r in group.itertuples(index=False):
            if not (pd.isna(r.hg) or pd.isna(r.ag)):
                builder.update(r.match_id, r.home_id, r.away_id, int(r.hg), int(r.ag), r.kickoff, r.tournament)
    out = pd.DataFrame(rows).set_index("match_id")[FEATURE_COLUMNS] if rows else pd.DataFrame(columns=FEATURE_COLUMNS)
    return (out, builder) if return_builder else out


def outcome_labels(hg: pd.Series, ag: pd.Series) -> np.ndarray:
    """0 = local, 1 = empate, 2 = visitante."""
    return np.where(hg > ag, 0, np.where(hg == ag, 1, 2))
