"""Métricas de evaluación de probabilidades 1X2 y de goles."""
from __future__ import annotations

import numpy as np

LABELS = ["local", "empate", "visitante"]


def _onehot(y: np.ndarray) -> np.ndarray:
    out = np.zeros((len(y), 3))
    out[np.arange(len(y)), y] = 1.0
    return out


def log_loss(p: np.ndarray, y: np.ndarray) -> float:
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), y], 1e-15, 1))))


def brier(p: np.ndarray, y: np.ndarray) -> float:
    """Brier multiclase: suma de errores cuadrados de las 3 clases (0 = perfecto, 2 = peor)."""
    return float(np.mean(((p - _onehot(y)) ** 2).sum(axis=1)))


def rps(p: np.ndarray, y: np.ndarray) -> float:
    """Ranked Probability Score (orden local < empate < visitante)."""
    cp = np.cumsum(p, axis=1)[:, :2]
    co = np.cumsum(_onehot(y), axis=1)[:, :2]
    return float(np.mean(((cp - co) ** 2).sum(axis=1) / 2))


def accuracy(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean(p.argmax(axis=1) == y))


def confusion(p: np.ndarray, y: np.ndarray) -> list[list[int]]:
    """Filas = resultado real, columnas = resultado más probable predicho."""
    mat = np.zeros((3, 3), dtype=int)
    for t, q in zip(y, p.argmax(axis=1)):
        mat[t, q] += 1
    return mat.tolist()


def calibration(p: np.ndarray, y: np.ndarray, bins: int = 10) -> dict:
    """Para cada clase: probabilidad media predicha vs frecuencia observada por intervalo."""
    out = {}
    oh = _onehot(y)
    edges = np.linspace(0, 1, bins + 1)
    for k, label in enumerate(LABELS):
        rows = []
        idx = np.clip(np.digitize(p[:, k], edges) - 1, 0, bins - 1)
        for b in range(bins):
            mask = idx == b
            if mask.sum() == 0:
                continue
            rows.append({"bin": f"{edges[b]:.1f}-{edges[b + 1]:.1f}", "n": int(mask.sum()),
                         "predicted": float(p[mask, k].mean()), "observed": float(oh[mask, k].mean())})
        out[label] = rows
    return out


def goal_metrics(lam_h, lam_a, top_h, top_a, hg, ag) -> dict:
    hg, ag = np.asarray(hg, float), np.asarray(ag, float)
    return {
        "mae_expected_goals": float(np.mean(np.abs(np.concatenate([lam_h - hg, lam_a - ag])))),
        "mae_top_score": float(np.mean(np.abs(np.concatenate([top_h - hg, top_a - ag])))),
        "exact_score_hit_rate": float(np.mean((top_h == hg) & (top_a == ag))),
    }


def summarize(p: np.ndarray, y: np.ndarray) -> dict:
    if len(y) == 0:
        return {"n": 0}
    return {
        "n": int(len(y)),
        "accuracy": accuracy(p, y),
        "log_loss": log_loss(p, y),
        "brier": brier(p, y),
        "rps": rps(p, y),
        "confusion": confusion(p, y),
        "mean_probs": p.mean(axis=0).round(4).tolist(),
        "observed_freq": (np.bincount(y, minlength=3) / len(y)).round(4).tolist(),
    }
