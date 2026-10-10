"""Modelos predictivos. Todos devuelven probabilidades [local, empate, visitante].

A. BaselineModel   — frecuencias históricas.
B. EloModel        — logit ordinal sobre la diferencia de Elo (incluye ventaja de local).
C. DixonColesModel — Poisson bivariante con corrección de marcadores bajos y ponderación temporal.
D. LogisticModel   — regresión logística multinomial sobre las variables pre-partido.
E. BoostingModel   — LightGBM sobre las mismas variables.
   EnsembleModel   — promedio ponderado de modelos ya entrenados.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import minimize
from scipy.special import expit, gammaln
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.features.build import FEATURE_COLUMNS, outcome_labels

MAX_GOALS = 10
EPS = 1e-12


@dataclass
class GoalsPrediction:
    lam_home: np.ndarray
    lam_away: np.ndarray
    matrices: list[np.ndarray]  # matriz (MAX_GOALS+1)^2: fila = goles local, columna = goles visitante


def probs_from_matrix(mat: np.ndarray) -> np.ndarray:
    return np.array([np.tril(mat, -1).sum(), np.trace(mat), np.triu(mat, 1).sum()])


class BaseModel:
    name = "base"
    produces_goals = False

    def fit(self, train: pd.DataFrame, cutoff: pd.Timestamp) -> BaseModel:
        raise NotImplementedError

    def predict_proba(self, rows: pd.DataFrame) -> np.ndarray:
        raise NotImplementedError

    def params(self) -> dict:
        return {}


class BaselineModel(BaseModel):
    name = "A_referencia"

    def fit(self, train, cutoff):
        y = outcome_labels(train["hg"], train["ag"])
        counts = np.bincount(y, minlength=3).astype(float) + 1.0
        self.freq = counts / counts.sum()
        return self

    def predict_proba(self, rows):
        return np.tile(self.freq, (len(rows), 1))

    def params(self):
        return {"freq": self.freq.round(4).tolist()}


class EloModel(BaseModel):
    """P(y <= k) = σ(θ_k − β·elo_diff) con y ordenada visitante < empate < local."""

    name = "B_elo"

    def fit(self, train, cutoff):
        x = train["elo_diff"].to_numpy() / 100.0
        y = 2 - outcome_labels(train["hg"], train["ag"])  # 0 visitante, 1 empate, 2 local

        def nll(v):
            t1, gap, b = v
            t2 = t1 + math.exp(gap)
            c1, c2 = expit(t1 - b * x), expit(t2 - b * x)
            p = np.where(y == 0, c1, np.where(y == 1, c2 - c1, 1 - c2))
            return -np.log(np.clip(p, EPS, 1)).sum()

        res = minimize(nll, x0=np.array([-1.0, 0.0, 0.5]), method="L-BFGS-B")
        self.t1, gap, self.b = res.x
        self.t2 = self.t1 + math.exp(gap)
        return self

    def predict_proba(self, rows):
        x = rows["elo_diff"].to_numpy() / 100.0
        c1, c2 = expit(self.t1 - self.b * x), expit(self.t2 - self.b * x)
        return np.column_stack([1 - c2, c2 - c1, c1])

    def params(self):
        return {"theta1": self.t1, "theta2": self.t2, "beta": self.b}


def _tau(x, y, lam, mu, rho):
    out = np.ones_like(lam)
    out = np.where((x == 0) & (y == 0), 1 - lam * mu * rho, out)
    out = np.where((x == 0) & (y == 1), 1 + lam * rho, out)
    out = np.where((x == 1) & (y == 0), 1 + mu * rho, out)
    out = np.where((x == 1) & (y == 1), 1 - rho, out)
    return out


class DixonColesModel(BaseModel):
    """Dixon & Coles (1997). log λ = hogar + ataque_local + defensa_visitante; log μ = ataque_visit + defensa_local.

    Pesos temporales w = exp(−ξ·días) respecto a la fecha de corte. Regularización L2 suave para que los
    equipos con pocos partidos no tengan parámetros extremos. Equipos sin historial (ascendidos o nuevos)
    reciben un ataque/defensa de respaldo algo inferior a la media.
    """

    name = "C_poisson_dc"
    produces_goals = True

    def __init__(self, xi: float = 0.0019, l2: float = 1.0, max_years: float = 5.0,
                 new_team_attack: float = -0.10, new_team_defense: float = 0.10):
        self.xi, self.l2, self.max_years = xi, l2, max_years
        self.new_team_attack, self.new_team_defense = new_team_attack, new_team_defense

    def fit(self, train, cutoff):
        if train.empty:
            raise ValueError("Dixon-Coles: no hay partidos de entrenamiento")
        age_days = (cutoff - train["kickoff"]).dt.total_seconds().to_numpy() / 86400.0
        # ventana de años contada desde el partido más reciente (no desde la fecha de corte)
        span = (train["kickoff"].max() - train["kickoff"]).dt.total_seconds().to_numpy() / 86400.0
        keep = span <= self.max_years * 365.25
        tr = train[keep]
        age_days = age_days[keep]
        w = np.exp(-self.xi * age_days)
        teams = np.unique(np.concatenate([tr["home_id"].to_numpy(), tr["away_id"].to_numpy()]))
        self.team_index = {int(t): i for i, t in enumerate(teams)}
        n = len(teams)
        hi = np.array([self.team_index[int(t)] for t in tr["home_id"]])
        ai = np.array([self.team_index[int(t)] for t in tr["away_id"]])
        x, y = tr["hg"].to_numpy(dtype=float), tr["ag"].to_numpy(dtype=float)
        const = (gammaln(x + 1) + gammaln(y + 1))
        wsum = w.sum()

        def unpack(v):
            return v[:n], v[n:2 * n], v[2 * n], v[2 * n + 1]

        def f(v):
            att, dfn, home, rho = unpack(v)
            log_lam = home + att[hi] + dfn[ai]
            log_mu = att[ai] + dfn[hi]
            lam, mu = np.exp(log_lam), np.exp(log_mu)
            tau = _tau(x, y, lam, mu, rho)
            ll = np.log(np.clip(tau, EPS, None)) + x * log_lam - lam + y * log_mu - mu - const
            obj = -(w * ll).sum() / wsum + self.l2 * ((att ** 2).sum() + (dfn ** 2).sum()) / wsum
            # gradiente (la parte de tau se trata exactamente para los cuatro marcadores bajos)
            d_lam = x - lam
            d_mu = y - mu
            m00, m01 = (x == 0) & (y == 0), (x == 0) & (y == 1)
            m10, m11 = (x == 1) & (y == 0), (x == 1) & (y == 1)
            safe = np.clip(tau, EPS, None)
            d_lam = d_lam + np.where(m00, -lam * mu * rho / safe, 0) + np.where(m01, lam * rho / safe, 0)
            d_mu = d_mu + np.where(m00, -lam * mu * rho / safe, 0) + np.where(m10, mu * rho / safe, 0)
            d_rho = np.where(m00, -lam * mu, 0) + np.where(m01, lam, 0) + np.where(m10, mu, 0) + np.where(m11, -1, 0)
            d_rho = d_rho / safe
            g_att = np.bincount(hi, w * d_lam, n) + np.bincount(ai, w * d_mu, n)
            g_def = np.bincount(ai, w * d_lam, n) + np.bincount(hi, w * d_mu, n)
            grad = np.concatenate([
                -g_att / wsum + 2 * self.l2 * att / wsum,
                -g_def / wsum + 2 * self.l2 * dfn / wsum,
                [-(w * d_lam).sum() / wsum],
                [-(w * d_rho).sum() / wsum],
            ])
            return obj, grad

        v0 = np.concatenate([np.zeros(2 * n), [0.25, -0.05]])
        bounds = [(None, None)] * (2 * n) + [(None, None), (-0.3, 0.3)]
        res = minimize(f, v0, jac=True, method="L-BFGS-B", bounds=bounds)
        att, dfn, home, rho = unpack(res.x)
        # centrar: ataque medio = 0 (se compensa en el intercepto)
        shift = att.mean()
        self.att, self.dfn = att - shift, dfn + shift
        self.home, self.rho = float(home), float(rho)
        self.converged = bool(res.success)
        self.n_train = int(len(tr))
        return self

    def _ad(self, team_id: int) -> tuple[float, float]:
        i = self.team_index.get(int(team_id))
        if i is None:
            return self.new_team_attack, self.new_team_defense
        return float(self.att[i]), float(self.dfn[i])

    def predict_goals(self, rows: pd.DataFrame) -> GoalsPrediction:
        lams, mus, mats = [], [], []
        g = np.arange(MAX_GOALS + 1)
        for h, a in zip(rows["home_id"], rows["away_id"]):
            ah, dh = self._ad(h)
            aa, da = self._ad(a)
            lam = math.exp(self.home + ah + da)
            mu = math.exp(aa + dh)
            mat = np.outer(poisson.pmf(g, lam), poisson.pmf(g, mu))
            mat[0, 0] *= 1 - lam * mu * self.rho
            mat[0, 1] *= 1 + lam * self.rho
            mat[1, 0] *= 1 + mu * self.rho
            mat[1, 1] *= 1 - self.rho
            mat = np.clip(mat, 0, None)
            mat /= mat.sum()
            lams.append(lam)
            mus.append(mu)
            mats.append(mat)
        return GoalsPrediction(np.array(lams), np.array(mus), mats)

    def predict_proba(self, rows):
        gp = self.predict_goals(rows)
        return np.array([probs_from_matrix(mat) for mat in gp.matrices]) if len(rows) else np.zeros((0, 3))

    def params(self):
        return {"xi": self.xi, "l2": self.l2, "home": self.home, "rho": self.rho, "converged": self.converged}


class LogisticModel(BaseModel):
    name = "D_logistica"

    def __init__(self, C: float = 0.05, features: list[str] | None = None):
        self.C = C
        self.features = features or FEATURE_COLUMNS

    def fit(self, train, cutoff):
        X = train[self.features].to_numpy(dtype=float)
        y = outcome_labels(train["hg"], train["ag"])
        self.pipe = make_pipeline(StandardScaler(), LogisticRegression(C=self.C, max_iter=2000))
        self.pipe.fit(X, y)
        return self

    def predict_proba(self, rows):
        return self.pipe.predict_proba(rows[self.features].to_numpy(dtype=float))

    def contributions(self, row: pd.Series) -> list[tuple[str, float]]:
        """Contribución de cada variable al logit local-vs-visitante (interna del modelo, no causal)."""
        scaler, lr = self.pipe[0], self.pipe[1]
        z = (row[self.features].to_numpy(dtype=float) - scaler.mean_) / scaler.scale_
        diff = lr.coef_[0] - lr.coef_[2]
        contrib = z * diff
        order = np.argsort(-np.abs(contrib))
        return [(self.features[i], float(contrib[i])) for i in order]

    def params(self):
        return {"C": self.C, "n_features": len(self.features)}


class BoostingModel(BaseModel):
    name = "E_lightgbm"

    def __init__(self, n_estimators: int = 300, learning_rate: float = 0.02, num_leaves: int = 7,
                 min_child_samples: int = 40):
        self.kw = dict(n_estimators=n_estimators, learning_rate=learning_rate, num_leaves=num_leaves,
                       min_child_samples=min_child_samples, subsample=0.8, subsample_freq=1,
                       colsample_bytree=0.8, reg_lambda=1.0, verbose=-1, random_state=42)

    def fit(self, train, cutoff):
        from lightgbm import LGBMClassifier

        X = train[FEATURE_COLUMNS].to_numpy(dtype=float)
        y = outcome_labels(train["hg"], train["ag"])
        self.clf = LGBMClassifier(objective="multiclass", **self.kw)
        self.clf.fit(X, y)
        return self

    def predict_proba(self, rows):
        return self.clf.predict_proba(rows[FEATURE_COLUMNS].to_numpy(dtype=float))

    def params(self):
        return {k: v for k, v in self.kw.items() if k != "verbose"}


class EnsembleModel(BaseModel):
    name = "F_combinado"

    def __init__(self, members: list[BaseModel], weights: list[float]):
        self.members, self.weights = members, np.array(weights) / np.sum(weights)

    @property
    def produces_goals(self):
        return any(mm.produces_goals for mm in self.members)

    def fit(self, train, cutoff):
        for mm in self.members:
            mm.fit(train, cutoff)
        return self

    def predict_proba(self, rows):
        return sum(w * mm.predict_proba(rows) for w, mm in zip(self.weights, self.members))

    def params(self):
        return {"members": [mm.name for mm in self.members], "weights": self.weights.round(3).tolist(),
                "member_params": {mm.name: mm.params() for mm in self.members}}
