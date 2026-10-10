"""Lectura de partidos desde la base de datos al formato que usan variables y modelos."""
from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models as m


def load_matches_df(session: Session) -> pd.DataFrame:
    """Todos los partidos no cancelados. hg/ag = marcador a 90' solo si el partido está finalizado."""
    rows = session.execute(
        select(m.Match.id, m.Match.kickoff_utc, m.Match.tournament, m.Match.season, m.Match.stage,
               m.Match.home_team_id, m.Match.away_team_id, m.Match.home_goals, m.Match.away_goals,
               m.Match.status)
        .where(m.Match.status != m.CANCELED)
    ).all()
    df = pd.DataFrame(rows, columns=["match_id", "kickoff", "tournament", "season", "stage", "home_id", "away_id",
                                     "hg", "ag", "status"])
    if df.empty:
        df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
        return df
    df["kickoff"] = pd.to_datetime(df["kickoff"], utc=True)
    not_final = df["status"] != m.FINISHED
    df.loc[not_final, ["hg", "ag"]] = None
    df["hg"] = pd.to_numeric(df["hg"]).astype("float")
    df["ag"] = pd.to_numeric(df["ag"]).astype("float")
    return df.sort_values(["kickoff", "match_id"]).reset_index(drop=True)
