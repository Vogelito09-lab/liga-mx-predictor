"""Backtesting con origen móvil expansivo, por torneo y con reentrenamiento semanal.

Procedimiento (equivale a haber tenido el sistema funcionando en el pasado):
1. Los partidos se ordenan cronológicamente y se agrupan por torneo.
2. Los primeros `warmup` torneos solo sirven para entrenar.
3. Los torneos siguientes son VALIDACIÓN: ahí se eligen hiperparámetros y el modelo.
4. Los últimos `test_tournaments` torneos completos son PRUEBA FINAL: se evalúan una sola vez,
   con la configuración ya elegida, y no influyen en ninguna decisión.
5. Dentro de cada torneo evaluado, cada bloque de `block_days` días se predice con un modelo entrenado
   solo con partidos que empezaron antes del inicio del bloque (política de reentrenamiento semanal).
   Las variables de cada partido usan solo resultados anteriores a su hora de inicio.
"""
from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.features.build import FeatureParams, build_features, outcome_labels
from app.ml import metrics as mt
from app.ml.models import (
    BaselineModel,
    BaseModel,
    BoostingModel,
    DixonColesModel,
    EloModel,
    EnsembleModel,
    LogisticModel,
)

log = logging.getLogger(__name__)

ModelFactory = Callable[[], BaseModel]


STALE_PENDING_DAYS = 30


@dataclass
class BacktestConfig:
    warmup: int = 4
    test_tournaments: int = 2
    block_days: int = 7
    min_matches_per_tournament: int = 60
    elo_grid: list[dict] = field(default_factory=lambda: [
        {"elo_k": k, "elo_home_adv": h, "elo_regress": r}
        for k in (15.0, 25.0) for h in (50.0, 80.0) for r in (0.1, 0.3)
    ])
    dc_xi_grid: list[float] = field(default_factory=lambda: [0.001, 0.002, 0.004])
    lr_c_grid: list[float] = field(default_factory=lambda: [0.01, 0.05, 0.3])
    gbm_grid: list[dict] = field(default_factory=lambda: [
        {"n_estimators": 200, "learning_rate": 0.03, "num_leaves": 5},
        {"n_estimators": 400, "learning_rate": 0.02, "num_leaves": 9},
    ])

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


@dataclass
class Folds:
    warmup: list[str]
    validation: list[str]
    test: list[str]
    excluded: list[str]


def make_folds(df: pd.DataFrame, cfg: BacktestConfig) -> Folds:
    """Divide los torneos completos en calentamiento, validación y prueba."""
    played = df[df["hg"].notna()]
    # Mediana y no mínimo: un partido fantasma con fecha atípica no debe alterar el orden de los torneos.
    first = df.groupby("tournament")["kickoff"].median().sort_values()
    counts = played.groupby("tournament").size()
    pending = df[df["hg"].isna() & (df["status"].isin(["scheduled", "in_progress", "postponed"]))]
    # Un partido "programado" de hace más de 30 días respecto al último jugado es un registro rancio
    # (ya queda como incidencia stale_scheduled en la auditoría); no vuelve incompleto a su torneo.
    if not played.empty:
        pending = pending[pending["kickoff"] >= played["kickoff"].max() - pd.Timedelta(days=STALE_PENDING_DAYS)]
    incomplete = set(pending["tournament"])
    order = [t for t in first.index]
    usable = [t for t in order if counts.get(t, 0) >= cfg.min_matches_per_tournament and t not in incomplete]
    excluded = [t for t in order if t not in usable]
    if len(usable) < cfg.warmup + cfg.test_tournaments + 2:
        raise ValueError(f"Datos insuficientes para backtesting: {len(usable)} torneos completos utilizables")
    return Folds(
        warmup=usable[:cfg.warmup],
        validation=usable[cfg.warmup:len(usable) - cfg.test_tournaments],
        test=usable[len(usable) - cfg.test_tournaments:],
        excluded=excluded,
    )


def prepare(df: pd.DataFrame, fparams: FeatureParams) -> pd.DataFrame:
    feats = build_features(df, fparams)
    return df.set_index("match_id").join(feats, how="left").reset_index()


def walk_forward(data: pd.DataFrame, tournaments: list[str], factory: ModelFactory, cfg: BacktestConfig,
                 split: str) -> pd.DataFrame:
    """Predice los partidos jugados de `tournaments` con reentrenamiento por bloques."""
    played = data[data["hg"].notna()]
    out = []
    for t in tournaments:
        target = played[played["tournament"] == t].sort_values("kickoff")
        if target.empty:
            continue
        start = target["kickoff"].iloc[0]
        block = ((target["kickoff"] - start).dt.total_seconds() // (cfg.block_days * 86400)).astype(int)
        for _, chunk in target.groupby(block):
            cutoff = chunk["kickoff"].min()
            train = played[played["kickoff"] < cutoff]
            model = factory().fit(train, cutoff)
            p = model.predict_proba(chunk)
            res = pd.DataFrame({"match_id": chunk["match_id"].to_numpy(), "fold": t, "split": split,
                                "p_home": p[:, 0], "p_draw": p[:, 1], "p_away": p[:, 2]})
            if model.produces_goals:
                dc = model if isinstance(model, DixonColesModel) else next(
                    mm for mm in model.members if isinstance(mm, DixonColesModel))
                gp = dc.predict_goals(chunk)
                tops = [np.unravel_index(np.argmax(mat), mat.shape) for mat in gp.matrices]
                res["exp_home_goals"], res["exp_away_goals"] = gp.lam_home, gp.lam_away
                res["top_home"] = [int(a) for a, _ in tops]
                res["top_away"] = [int(b) for _, b in tops]
            out.append(res)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def score(preds: pd.DataFrame, data: pd.DataFrame) -> dict:
    merged = preds.merge(data[["match_id", "hg", "ag", "tournament", "season", "stage"]], on="match_id")
    p = merged[["p_home", "p_draw", "p_away"]].to_numpy()
    y = outcome_labels(merged["hg"], merged["ag"])
    res = mt.summarize(p, y)
    res["calibration"] = mt.calibration(p, y)
    if "exp_home_goals" in merged:
        res["goals"] = mt.goal_metrics(merged["exp_home_goals"].to_numpy(), merged["exp_away_goals"].to_numpy(),
                                       merged["top_home"].to_numpy(), merged["top_away"].to_numpy(),
                                       merged["hg"], merged["ag"])
    for key in ("tournament", "season", "stage"):
        res[f"by_{key}"] = {
            str(k): {kk: v for kk, v in mt.summarize(g[["p_home", "p_draw", "p_away"]].to_numpy(),
                                                     outcome_labels(g["hg"], g["ag"])).items()
                     if kk in ("n", "accuracy", "log_loss", "brier")}
            for k, g in merged.groupby(key, sort=False)
        }
    # Rendimiento según el resultado real (local/empate/visitante): acierto por clase (recall).
    conf = np.array(res["confusion"])
    res["recall_by_outcome"] = {
        lab: (float(conf[i, i] / conf[i].sum()) if conf[i].sum() else None) for i, lab in enumerate(mt.LABELS)
    }
    return res


def _ll(preds: pd.DataFrame, data: pd.DataFrame) -> float:
    merged = preds.merge(data[["match_id", "hg", "ag"]], on="match_id")
    return mt.log_loss(merged[["p_home", "p_draw", "p_away"]].to_numpy(), outcome_labels(merged["hg"], merged["ag"]))


@dataclass
class BacktestResult:
    config: dict
    folds: Folds
    feature_params: FeatureParams
    chosen: dict  # hiperparámetros elegidos por modelo
    selected_model: str
    summary: dict
    predictions: pd.DataFrame


def model_factories(chosen: dict) -> dict[str, ModelFactory]:
    return {
        "A_referencia": lambda: BaselineModel(),
        "B_elo": lambda: EloModel(),
        "C_poisson_dc": lambda: DixonColesModel(xi=chosen["dc_xi"]),
        "D_logistica": lambda: LogisticModel(C=chosen["lr_c"]),
        "E_lightgbm": lambda: BoostingModel(**chosen["gbm"]),
    }


def ensemble_factory(chosen: dict, members: list[str]) -> ModelFactory:
    base = model_factories(chosen)
    return lambda: EnsembleModel([base[name]() for name in members], [1.0] * len(members))


def run_backtest(df: pd.DataFrame, cfg: BacktestConfig | None = None) -> BacktestResult:
    cfg = cfg or BacktestConfig()
    t0 = time.time()
    folds = make_folds(df, cfg)
    val = folds.validation
    grid_log: dict[str, list] = {"elo": [], "dc_xi": [], "lr_c": [], "gbm": []}

    # 1) Parámetros de Elo/variables: se eligen por log loss del modelo Elo en validación.
    best = None
    for g in cfg.elo_grid:
        fp = FeatureParams(**g)
        data = prepare(df, fp)
        ll = _ll(walk_forward(data, val, EloModel, cfg, "validation"), data)
        grid_log["elo"].append({**g, "log_loss": ll})
        if best is None or ll < best[0]:
            best = (ll, fp, data)
    _, fparams, data = best
    log.info("Elo elegido %s (%.1fs)", fparams, time.time() - t0)

    chosen: dict = {}
    for xi in cfg.dc_xi_grid:
        ll = _ll(walk_forward(data, val, lambda: DixonColesModel(xi=xi), cfg, "validation"), data)
        grid_log["dc_xi"].append({"xi": xi, "log_loss": ll})
    chosen["dc_xi"] = min(grid_log["dc_xi"], key=lambda r: r["log_loss"])["xi"]
    for c in cfg.lr_c_grid:
        ll = _ll(walk_forward(data, val, lambda: LogisticModel(C=c), cfg, "validation"), data)
        grid_log["lr_c"].append({"C": c, "log_loss": ll})
    chosen["lr_c"] = min(grid_log["lr_c"], key=lambda r: r["log_loss"])["C"]
    for gp in cfg.gbm_grid:
        ll = _ll(walk_forward(data, val, lambda: BoostingModel(**gp), cfg, "validation"), data)
        grid_log["gbm"].append({**gp, "log_loss": ll})
    best_gbm = min(grid_log["gbm"], key=lambda r: r["log_loss"])
    chosen["gbm"] = {k: v for k, v in best_gbm.items() if k != "log_loss"}
    log.info("Hiperparámetros elegidos %s (%.1fs)", chosen, time.time() - t0)

    # 2) Validación de todos los modelos con sus hiperparámetros elegidos.
    factories = model_factories(chosen)
    val_preds = {name: walk_forward(data, val, f, cfg, "validation") for name, f in factories.items()}
    val_ll = {name: _ll(p, data) for name, p in val_preds.items()}
    # Combinado: el modelo de goles (necesario para marcadores) + el mejor modelo de clasificación.
    best_clf = min(("B_elo", "D_logistica", "E_lightgbm"), key=lambda n: val_ll[n])
    members = ["C_poisson_dc", best_clf]
    factories["F_combinado"] = ensemble_factory(chosen, members)
    chosen["ensemble_members"] = members
    val_preds["F_combinado"] = walk_forward(data, val, factories["F_combinado"], cfg, "validation")
    val_ll["F_combinado"] = _ll(val_preds["F_combinado"], data)
    selected = min(val_ll, key=val_ll.get)
    log.info("Modelo seleccionado en validación: %s", selected)

    # 3) Prueba final: se evalúa una sola vez, tras haber fijado todo lo anterior.
    test_preds = {name: walk_forward(data, folds.test, f, cfg, "test") for name, f in factories.items()}

    summary = {
        "selection_metric": "log_loss (validación)",
        "selected_model": selected,
        "validation_log_loss": val_ll,
        "grid_search": grid_log,
        "feature_params": fparams.as_dict(),
        "chosen_hyperparams": chosen,
        "folds": folds.__dict__,
        "models": {},
        "elapsed_s": round(time.time() - t0, 1),
    }
    for name in factories:
        summary["models"][name] = {
            "validation": score(val_preds[name], data),
            "test": score(test_preds[name], data),
        }
    all_preds = []
    for name in factories:
        for p in (val_preds[name], test_preds[name]):
            q = p.copy()
            q["model"] = name
            all_preds.append(q)
    return BacktestResult(cfg.as_dict(), folds, fparams, chosen, selected, summary,
                          pd.concat(all_preds, ignore_index=True))
