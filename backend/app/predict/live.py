"""Probabilidad en vivo: cómo cambian local / empate / visitante con el minuto y el marcador.

Método (sencillo y verificable):
1. Del modelo previo al partido se toman los goles esperados de cada equipo (λ local, μ visitante) para los 90'.
2. Se supone que los goles caen de forma pareja durante el partido: si falta una fracción `f` del tiempo,
   los goles que faltan de cada equipo siguen una Poisson de media λ·f y μ·f.
3. Marcador actual + goles que faltan → probabilidad de cada resultado a los 90'.
4. Para que en el minuto 0 coincida exactamente con la predicción previa (que combina Poisson y Elo), cada
   resultado se corrige por (p_previa / p_poisson_previa)^f; esa corrección se desvanece hacia el final.

No se ajusta por tarjetas rojas, cambios ni posesión: no hay datos propios para medir su efecto.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import poisson

REGULATION_MIN = 90.0
MAX_EXTRA_GOALS = 10
# Mientras el balón rueda en el añadido el partido aún no termina: se deja al menos este tiempo por jugar.
MIN_REMAINING_IN_PLAY = 1.0


def elapsed_minutes(state: str, source_status: str, period: int, clock_seconds: float) -> float | None:
    """Minutos reglamentarios jugados (0-90). None si el partido ya pasó de los 90' (prórroga o penales)."""
    if state == "pre":
        return 0.0
    if state == "post" or period >= 3 or "SHOOTOUT" in source_status or "OVERTIME" in source_status \
            or "EXTRA_TIME" in source_status or "END_OF" in source_status:
        return None
    if source_status == "STATUS_HALFTIME":
        return 45.0
    minute = clock_seconds / 60.0
    if period <= 1:
        return min(max(minute, 0.0), 45.0)
    return min(max(minute, 45.0), REGULATION_MIN)


def remaining_fraction(state: str, source_status: str, elapsed: float) -> float:
    remaining = REGULATION_MIN - elapsed
    if state == "in" and source_status != "STATUS_HALFTIME":
        remaining = max(remaining, MIN_REMAINING_IN_PLAY)
    return max(remaining, 0.0) / REGULATION_MIN


@dataclass
class LiveProbs:
    p_home: float
    p_draw: float
    p_away: float
    top_score_home: int
    top_score_away: int
    top_score_prob: float
    remaining_fraction: float


def _outcome_index(h: np.ndarray, a: np.ndarray) -> np.ndarray:
    return np.where(h > a, 0, np.where(h == a, 1, 2))


def inplay_probs(exp_home: float, exp_away: float, pregame: tuple[float, float, float],
                 home_goals: int, away_goals: int, frac: float) -> LiveProbs:
    """Probabilidades del resultado a los 90' dado el marcador actual y la fracción de partido que falta."""
    frac = min(max(frac, 0.0), 1.0)
    k = np.arange(MAX_EXTRA_GOALS + 1)
    grid_h, grid_a = np.meshgrid(k, k, indexing="ij")

    def matrix(lam: float, mu: float) -> np.ndarray:
        mat = np.outer(poisson.pmf(k, lam), poisson.pmf(k, mu))
        return mat / mat.sum()

    # Goles que faltan + marcador actual
    rest = matrix(exp_home * frac, exp_away * frac)
    outcome = _outcome_index(grid_h + home_goals, grid_a + away_goals)
    # Corrección para empatar con la predicción previa al inicio (se desvanece con el tiempo)
    full = matrix(exp_home, exp_away)
    base = np.array([full[_outcome_index(grid_h, grid_a) == i].sum() for i in range(3)])
    pre = np.asarray(pregame, dtype=float)
    tilt = np.ones(3) if frac == 0 else np.power(np.clip(pre, 1e-9, None) / np.clip(base, 1e-9, None), frac)
    weighted = rest * tilt[outcome]
    weighted /= weighted.sum()
    probs = np.array([weighted[outcome == i].sum() for i in range(3)])
    i, j = np.unravel_index(np.argmax(weighted), weighted.shape)
    return LiveProbs(p_home=float(probs[0]), p_draw=float(probs[1]), p_away=float(probs[2]),
                     top_score_home=int(home_goals + i), top_score_away=int(away_goals + j),
                     top_score_prob=float(weighted[i, j]), remaining_fraction=float(frac))
