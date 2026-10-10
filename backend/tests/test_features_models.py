import numpy as np
import pandas as pd
import pytest
from scipy.optimize import approx_fprime

from app.features.build import FEATURE_COLUMNS, build_features
from app.ml.backtest import make_folds, run_backtest, walk_forward
from app.ml.models import DixonColesModel, EloModel, LogisticModel, probs_from_matrix
from tests.helpers import SMALL_BT
from tests.synthetic import simulated_league


@pytest.fixture(scope="module")
def league():
    return simulated_league(n_teams=12, years=range(2016, 2020))


def test_features_use_only_past_information(league):
    """Las variables de un partido no cambian si se borra todo lo posterior (incluido su propio resultado)."""
    full = build_features(league)
    rng = np.random.default_rng(0)
    for idx in rng.choice(len(league), 15, replace=False):
        target = league.iloc[idx]
        past = league[league["kickoff"] <= target["kickoff"]].copy()
        same_time = past["kickoff"] == target["kickoff"]
        past.loc[same_time, ["hg", "ag"]] = np.nan  # resultados de esa hora aún no se conocen
        truncated = build_features(past)
        pd.testing.assert_series_equal(full.loc[target.match_id], truncated.loc[target.match_id], check_names=False)


def test_features_change_when_past_changes(league):
    """Control: modificar un resultado anterior sí cambia variables posteriores (la prueba anterior no es trivial)."""
    mod = league.copy()
    mod.loc[0, "hg"] = 9
    a, b = build_features(league), build_features(mod)
    later = league[(league["home_id"] == league.loc[0, "home_id"]) & (league.index > 0)].iloc[0].match_id
    assert not np.allclose(a.loc[later].to_numpy(), b.loc[later].to_numpy())


def test_feature_columns_complete(league):
    f = build_features(league)
    assert list(f.columns) == FEATURE_COLUMNS
    assert not f.isna().any().any()


def test_dixon_coles_gradient_matches_numeric(league):
    dc = DixonColesModel(xi=0.002)
    train = league.iloc[:300]
    cutoff = train["kickoff"].max() + pd.Timedelta(days=1)
    dc.fit(train, cutoff)
    assert dc.converged
    # el gradiente analítico ~0 en el óptimo implica que coincide con el numérico
    probs = dc.predict_proba(league.iloc[300:320])
    assert np.allclose(probs.sum(axis=1), 1, atol=1e-9)
    assert (probs > 0).all() and (probs < 1).all()


def test_dixon_coles_objective_gradient(league):
    """Comparación directa del gradiente analítico con diferencias finitas."""
    import app.ml.models as mm

    captured = {}
    orig = mm.minimize

    def spy(f, x0, jac, **kw):
        captured["f"], captured["x0"] = f, x0
        return orig(f, x0, jac=jac, **kw)

    mm.minimize = spy
    try:
        DixonColesModel().fit(league.iloc[:200], league["kickoff"].iloc[200])
    finally:
        mm.minimize = orig
    f = captured["f"]
    x = captured["x0"] + np.random.default_rng(1).normal(0, 0.1, len(captured["x0"]))
    x[-1] = 0.05
    analytic = f(x)[1]
    numeric = approx_fprime(x, lambda v: f(v)[0], 1e-6)
    assert np.allclose(analytic, numeric, atol=1e-4)


def test_score_matrix_consistent_with_goal_model(league):
    dc = DixonColesModel().fit(league.iloc[:400], league["kickoff"].iloc[400])
    rows = league.iloc[400:410]
    gp = dc.predict_goals(rows)
    for lam, mu, mat, p in zip(gp.lam_home, gp.lam_away, gp.matrices, dc.predict_proba(rows)):
        assert abs(mat.sum() - 1) < 1e-9
        np.testing.assert_allclose(probs_from_matrix(mat), p)
        g = np.arange(mat.shape[0])
        # la corrección de Dixon-Coles solo toca marcadores bajos: medias casi iguales a λ y μ
        assert abs((mat.sum(axis=1) * g).sum() - lam) < 0.05
        assert abs((mat.sum(axis=0) * g).sum() - mu) < 0.05


def test_models_output_valid_probabilities(league):
    data = league.set_index("match_id").join(build_features(league)).reset_index()
    train, test = data.iloc[:400], data.iloc[400:500]
    cutoff = test["kickoff"].min()
    for model in (EloModel(), LogisticModel(), DixonColesModel()):
        p = model.fit(train, cutoff).predict_proba(test)
        assert p.shape == (100, 3)
        assert ((p >= 0) & (p <= 1)).all()
        np.testing.assert_allclose(p.sum(axis=1), 1, atol=1e-6)


def test_walk_forward_trains_only_on_past(league):
    data = league.set_index("match_id").join(build_features(league)).reset_index()
    seen = []

    class Spy(EloModel):
        def fit(self, train, cutoff):
            seen.append((train["kickoff"].max(), cutoff))
            return super().fit(train, cutoff)

    folds = make_folds(league, SMALL_BT)
    walk_forward(data, folds.validation[:1], Spy, SMALL_BT, "validation")
    assert seen and all(tmax < cutoff for tmax, cutoff in seen)


def test_final_test_period_does_not_influence_selection(league):
    """Alterar los resultados del periodo de prueba no cambia ninguna decisión del backtesting."""
    r1 = run_backtest(league, SMALL_BT)
    test_t = r1.folds.test
    shuffled = league.copy()
    mask = shuffled["tournament"].isin(test_t)
    rng = np.random.default_rng(3)
    shuffled.loc[mask, "hg"] = rng.integers(0, 5, mask.sum())
    shuffled.loc[mask, "ag"] = rng.integers(0, 5, mask.sum())
    r2 = run_backtest(shuffled, SMALL_BT)
    assert r1.selected_model == r2.selected_model
    assert r1.chosen == r2.chosen
    assert r1.summary["validation_log_loss"] == r2.summary["validation_log_loss"]
    assert r1.summary["models"][r1.selected_model]["test"] != r2.summary["models"][r2.selected_model]["test"]


def test_stale_scheduled_record_does_not_drop_tournament(league):
    """Caso real de ESPN: un partido 'programado' con fecha muy anterior al resto de su torneo y sin resultado."""
    base = make_folds(league, SMALL_BT)
    target = base.warmup[1]
    ghost = league[league["tournament"] == target].iloc[[0]].copy()
    ghost["match_id"] = league["match_id"].max() + 1
    ghost["kickoff"] = league["kickoff"].min() - pd.Timedelta(days=200)
    ghost["hg"] = np.nan
    ghost["ag"] = np.nan
    ghost["status"] = "scheduled"
    folds = make_folds(pd.concat([league, ghost], ignore_index=True), SMALL_BT)
    assert folds == base
