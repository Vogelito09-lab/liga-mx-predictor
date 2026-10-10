"""Liga SIMULADA solo para pruebas automáticas.

Estos datos no representan partidos reales de la Liga MX y nunca se cargan en la base de datos de producción.
Sirven para comprobar que el código funciona (sin fugas, sin duplicados, métricas coherentes).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd


def simulated_league(n_teams: int = 18, years: range = range(2016, 2022), seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    attack = rng.normal(0, 0.25, n_teams)
    defense = rng.normal(0, 0.2, n_teams)
    home_adv = 0.3
    rows = []
    mid = 1
    for year in years:
        for kind, month in (("Clausura", 1), ("Apertura", 7)):
            tournament = f"{kind} {year}"
            start = datetime(year, month, 8, 1, 0, tzinfo=timezone.utc)
            teams = list(range(1, n_teams + 1))
            rng.shuffle(teams)
            # calendario round-robin (método del círculo)
            for rnd in range(n_teams - 1):
                pairs = [(teams[i], teams[n_teams - 1 - i]) for i in range(n_teams // 2)]
                for j, (h, a) in enumerate(pairs):
                    if rnd % 2:
                        h, a = a, h
                    lam = np.exp(home_adv + attack[h - 1] + defense[a - 1])
                    mu = np.exp(attack[a - 1] + defense[h - 1])
                    kickoff = start + timedelta(days=7 * rnd, hours=2 * (j % 3))
                    rows.append({"match_id": mid, "kickoff": kickoff, "tournament": tournament,
                                 "season": f"{year}", "stage": "regular", "home_id": h, "away_id": a,
                                 "hg": int(rng.poisson(lam)), "ag": int(rng.poisson(mu)), "status": "finished"})
                    mid += 1
                teams = [teams[0]] + [teams[-1]] + teams[1:-1]
            # deriva lenta de la fuerza entre torneos
            attack += rng.normal(0, 0.05, n_teams)
            defense += rng.normal(0, 0.05, n_teams)
    df = pd.DataFrame(rows)
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    return df
