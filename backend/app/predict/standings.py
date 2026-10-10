"""Tabla general y simulación Monte Carlo del resto del torneo (clasificación a liguilla y campeón).

Formato usado (Apertura 2026 en adelante: sin Play-In):
- Fase regular: 3 puntos por victoria, 1 por empate. Desempate: puntos, diferencia de goles, goles a favor,
  resultado entre los equipos empatados, goles como visitante y, al final, orden alfabético (la tabla
  de Fair Play no está en la fuente de datos).
- Clasifican los 8 primeros directo a cuartos de final: 1 vs 8, 2 vs 7, 3 vs 6, 4 vs 5.
- Semifinales con reacomodo: el mejor sembrado que sigue vivo contra el peor, y los otros dos entre sí.
- Eliminatorias a ida y vuelta; la vuelta en casa del mejor sembrado. En cuartos y semifinales, si hay
  empate en el global avanza el mejor sembrado. En la final hay tiempos extra y, si sigue el empate, penales.

Cómo se simula:
- Cada partido pendiente de la fase regular se juega con la matriz de marcadores del modelo de goles
  (Dixon-Coles) del modelo activo. Si el partido ya tiene una predicción guardada, la matriz se reescala
  para que sus probabilidades de local/empate/visitante coincidan con las de esa predicción (la del modelo
  activo, que es la que se muestra en la página).
- Los cruces de la fase regular que la fuente todavía no publica (todos contra todos, una vez) se simulan
  promediando las dos opciones de local.
- La liguilla se juega con el modelo de goles. Los partidos de liguilla ya terminados usan su marcador real.
- Tiempos extra: goles con un tercio del promedio de un partido (30 minutos). Penales: 50 % cada equipo.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import models as m
from app.ml.models import MAX_GOALS
from app.predict.service import active_model, load_artifact

N_QUALIFY = 8
N_SIMS = 10_000
SEED = 2026
G = MAX_GOALS + 1


def current_tournament(session: Session) -> str | None:
    """El torneo con el partido de fase regular más reciente."""
    return session.scalar(select(m.Match.tournament).where(m.Match.stage == "regular")
                          .order_by(m.Match.kickoff_utc.desc()).limit(1))


def _regular_matches(session: Session, tournament: str) -> list[m.Match]:
    return list(session.scalars(select(m.Match).where(
        m.Match.tournament == tournament, m.Match.stage == "regular", m.Match.status != m.CANCELED)))


def _is_done(mt: m.Match) -> bool:
    return mt.status == m.FINISHED and mt.home_goals_final is not None and mt.away_goals_final is not None


def regular_table(matches: list[m.Match]) -> list[dict]:
    """Tabla de fase regular con los partidos finalizados. Incluye a los equipos que aún no juegan."""
    table: dict[int, dict] = {}
    for mt in matches:
        for tid, team in ((mt.home_team_id, mt.home_team), (mt.away_team_id, mt.away_team)):
            table.setdefault(tid, {"team_id": tid, "team": team, "played": 0, "wins": 0, "draws": 0, "losses": 0,
                                   "gf": 0, "ga": 0, "away_gf": 0, "points": 0})
    done = [mt for mt in matches if _is_done(mt)]
    for mt in done:
        for tid, gf, ga, away in ((mt.home_team_id, mt.home_goals_final, mt.away_goals_final, False),
                                  (mt.away_team_id, mt.away_goals_final, mt.home_goals_final, True)):
            r = table[tid]
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            r["away_gf"] += gf if away else 0
            if gf > ga:
                r["wins"] += 1
                r["points"] += 3
            elif gf == ga:
                r["draws"] += 1
                r["points"] += 1
            else:
                r["losses"] += 1
    for r in table.values():
        r["gd"] = r["gf"] - r["ga"]

    # resultado entre los equipos empatados en puntos, diferencia y goles a favor
    groups: dict[tuple, list[int]] = defaultdict(list)
    for tid, r in table.items():
        groups[(r["points"], r["gd"], r["gf"])].append(tid)
    h2h: dict[int, int] = defaultdict(int)
    for tied in groups.values():
        if len(tied) < 2:
            continue
        ts = set(tied)
        for mt in done:
            if mt.home_team_id in ts and mt.away_team_id in ts:
                hg, ag = mt.home_goals_final, mt.away_goals_final
                h2h[mt.home_team_id] += 3 if hg > ag else (1 if hg == ag else 0)
                h2h[mt.away_team_id] += 3 if ag > hg else (1 if hg == ag else 0)
    out = sorted(table.values(), key=lambda r: (-r["points"], -r["gd"], -r["gf"], -h2h[r["team_id"]],
                                                -r["away_gf"], r["team"].name))
    for i, r in enumerate(out, 1):
        r["position"] = i
    return out


# ---------------------------------------------------------------------------------------------------
# Simulación
# ---------------------------------------------------------------------------------------------------
def _reweight(mat: np.ndarray, p: tuple[float, float, float]) -> np.ndarray:
    """Reescala las zonas local/empate/visitante de la matriz para que sumen p."""
    out = mat.copy()
    masks = (np.tril(np.ones_like(mat, dtype=bool), -1), np.eye(len(mat), dtype=bool),
             np.triu(np.ones_like(mat, dtype=bool), 1))
    for mask, target in zip(masks, p):
        total = mat[mask].sum()
        if total > 0:
            out[mask] *= target / total
    return out / out.sum()


def _sample_fixed(cdf: np.ndarray, rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray]:
    k = np.minimum(np.searchsorted(cdf, rng.random(n), side="right"), G * G - 1)
    return k // G, k % G


def simulate_tournament(session: Session, tournament: str, n_sims: int = N_SIMS, seed: int = SEED,
                        now: datetime | None = None) -> dict | None:
    """Probabilidad de clasificar (top 8) y de ser campeón de cada equipo. None si no hay modelo activo."""
    mv = active_model(session)
    if mv is None:
        return None
    goals = load_artifact(mv)["goals"]
    regular = _regular_matches(session, tournament)
    if not regular:
        return None
    table = regular_table(regular)
    teams = [r["team_id"] for r in table]
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)
    if T < N_QUALIFY:
        return None
    rng = np.random.default_rng(seed)

    # matrices de marcadores para todos los cruces posibles (local i, visitante j)
    pairs = pd.DataFrame([(h, a) for h in teams for a in teams], columns=["home_id", "away_id"])
    gp = goals.predict_goals(pairs)
    mats = np.array(gp.matrices).reshape(T, T, G, G)
    lam = gp.lam_home.reshape(T, T)
    mu = gp.lam_away.reshape(T, T)
    cdf_all = np.cumsum(mats.reshape(T, T, G * G), axis=2)

    # fase regular: puntos actuales + partidos pendientes
    pts = np.tile(np.array([r["points"] for r in table], dtype=float), (n_sims, 1))
    gf = np.tile(np.array([r["gf"] for r in table], dtype=float), (n_sims, 1))
    ga = np.tile(np.array([r["ga"] for r in table], dtype=float), (n_sims, 1))
    pending = [mt for mt in regular if not _is_done(mt)]
    latest = _latest_predictions(session, [mt.id for mt in pending])
    for mt in pending:
        h, a = idx[mt.home_team_id], idx[mt.away_team_id]
        mat = mats[h, a]
        pred = latest.get(mt.id)
        if pred is not None:
            mat = _reweight(mat, (pred.p_home, pred.p_draw, pred.p_away))
        hg, ag = _sample_fixed(np.cumsum(mat.ravel()), rng, n_sims)
        gf[:, h] += hg
        ga[:, h] += ag
        gf[:, a] += ag
        ga[:, a] += hg
        pts[:, h] += np.where(hg > ag, 3, np.where(hg == ag, 1, 0))
        pts[:, a] += np.where(ag > hg, 3, np.where(hg == ag, 1, 0))

    # Liga MX juega todos contra todos una vez. Los cruces que la fuente aún no publica en el calendario se
    # simulan igual (sin saber quién es local: se promedian las dos posibilidades).
    scheduled = {frozenset((mt.home_team_id, mt.away_team_id)) for mt in regular}
    missing = [(i, j) for i in range(T) for j in range(i + 1, T) if frozenset((teams[i], teams[j])) not in scheduled]
    for i, j in missing:
        mat = 0.5 * (mats[i, j] + mats[j, i].T)
        gi, gj = _sample_fixed(np.cumsum(mat.ravel()), rng, n_sims)
        gf[:, i] += gi
        ga[:, i] += gj
        gf[:, j] += gj
        ga[:, j] += gi
        pts[:, i] += np.where(gi > gj, 3, np.where(gi == gj, 1, 0))
        pts[:, j] += np.where(gj > gi, 3, np.where(gi == gj, 1, 0))

    if pending or missing:
        # desempate dentro de la simulación: puntos, diferencia, goles a favor y después al azar
        key = pts * 1e7 + (gf - ga + 500) * 1e3 + gf + rng.random((n_sims, T))
        order = np.argsort(-key, axis=1)
    else:
        # fase regular terminada: la siembra es la tabla real (con todos sus criterios de desempate)
        order = np.tile(np.arange(T), (n_sims, 1))
    seeds = order[:, :N_QUALIFY]  # seeds[n, s] = equipo en la posición s+1
    qualify = np.bincount(seeds.ravel(), minlength=T) / n_sims

    # resultados reales de liguilla ya jugados: (local, visitante) -> marcador
    known = _known_playoff_results(session, tournament, idx, T)
    rows = np.arange(n_sims)

    def play(h: np.ndarray, a: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cdf = cdf_all[h, a]
        k = np.minimum((cdf < rng.random(n_sims)[:, None]).sum(axis=1), G * G - 1)
        hg, ag = k // G, k % G
        kh, ka = known["h"][h, a], known["a"][h, a]
        played = kh >= 0
        return np.where(played, kh, hg), np.where(played, ka, ag)

    def tie(hi_s: np.ndarray, lo_s: np.ndarray, final: bool = False) -> np.ndarray:
        """Eliminatoria entre posiciones de siembra (hi_s mejor sembrado). Devuelve la posición que avanza."""
        hi, lo = seeds[rows, hi_s], seeds[rows, lo_s]
        g1_lo, g1_hi = play(lo, hi)  # ida en casa del peor sembrado
        g2_hi, g2_lo = play(hi, lo)  # vuelta en casa del mejor sembrado
        agg_hi, agg_lo = g1_hi + g2_hi, g1_lo + g2_lo
        if final:
            level = agg_hi == agg_lo
            et_hi = np.where(known["et_h"][hi, lo] >= 0, known["et_h"][hi, lo], rng.poisson(lam[hi, lo] / 3))
            et_lo = np.where(known["et_a"][hi, lo] >= 0, known["et_a"][hi, lo], rng.poisson(mu[hi, lo] / 3))
            agg_hi = agg_hi + np.where(level, et_hi, 0)
            agg_lo = agg_lo + np.where(level, et_lo, 0)
            pens_hi = np.where(known["pen"][hi, lo] >= 0, known["pen"][hi, lo] == 1, rng.random(n_sims) < 0.5)
            return np.where(agg_hi > agg_lo, hi_s, np.where(agg_lo > agg_hi, lo_s, np.where(pens_hi, hi_s, lo_s)))
        return np.where(agg_lo > agg_hi, lo_s, hi_s)

    qf = np.stack([tie(np.full(n_sims, i), np.full(n_sims, N_QUALIFY - 1 - i)) for i in range(N_QUALIFY // 2)],
                  axis=1)
    qf.sort(axis=1)  # reacomodo para semifinales
    sf1 = tie(qf[:, 0], qf[:, 3])
    sf2 = tie(qf[:, 1], qf[:, 2])
    champ_s = tie(np.minimum(sf1, sf2), np.maximum(sf1, sf2), final=True)
    champion = np.bincount(seeds[rows, champ_s], minlength=T) / n_sims

    return {
        "tournament": tournament,
        "model_version": mv.version,
        "n_sims": n_sims,
        "pending_matches": len(pending),
        "unscheduled_matches": len(missing),
        "computed_at": (now or datetime.now(timezone.utc)).isoformat(),
        "teams": {int(t): {"p_qualify": float(qualify[i]), "p_champion": float(champion[i])}
                  for i, t in enumerate(teams)},
    }


def _latest_predictions(session: Session, match_ids: list[int]) -> dict[int, m.Prediction]:
    if not match_ids:
        return {}
    sub = (select(m.Prediction.match_id, func.max(m.Prediction.generated_at).label("g"))
           .where(m.Prediction.match_id.in_(match_ids)).group_by(m.Prediction.match_id).subquery())
    rows = session.scalars(select(m.Prediction).join(
        sub, (m.Prediction.match_id == sub.c.match_id) & (m.Prediction.generated_at == sub.c.g))).all()
    return {p.match_id: p for p in rows}


def _known_playoff_results(session: Session, tournament: str, idx: dict[int, int], T: int) -> dict[str, np.ndarray]:
    """Marcadores reales de liguilla por cruce (local, visitante); -1 = no jugado."""
    out = {k: np.full((T, T), -1, dtype=int) for k in ("h", "a", "et_h", "et_a", "pen")}
    rows = session.scalars(select(m.Match).where(
        m.Match.tournament == tournament, m.Match.stage == "liguilla", m.Match.status == m.FINISHED,
        m.Match.home_goals.is_not(None)))
    for mt in rows:
        h, a = idx.get(mt.home_team_id), idx.get(mt.away_team_id)
        if h is None or a is None:
            continue
        out["h"][h, a], out["a"][h, a] = mt.home_goals, mt.away_goals
        if mt.extra_time and mt.home_goals_final is not None:
            out["et_h"][h, a] = mt.home_goals_final - mt.home_goals
            out["et_a"][h, a] = mt.away_goals_final - mt.away_goals
        if mt.home_penalties is not None and mt.away_penalties is not None:
            out["pen"][h, a] = int(mt.home_penalties > mt.away_penalties)
    return out


__all__ = ["current_tournament", "regular_table", "simulate_tournament"]
