"""Esquemas de respuesta de la API (también documentan /docs)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class TeamOut(BaseModel):
    id: int
    name: str
    abbreviation: str | None = None
    logo_url: str | None = Field(None, description="Escudo servido por ESPN (a.espncdn.com)")


class ScoreProb(BaseModel):
    home: int
    away: int
    p: float


class Factor(BaseModel):
    key: str
    text: str


class PredictionOut(BaseModel):
    id: int
    match_id: int
    generated_at: datetime
    data_cutoff: datetime
    model_version: str
    p_home: float
    p_draw: float
    p_away: float
    most_likely_outcome: str = Field(description="local | empate | visitante (mayor probabilidad 1X2)")
    exp_home_goals: float | None
    exp_away_goals: float | None
    top_score_home: int | None = Field(description="Marcador exacto de mayor probabilidad conjunta")
    top_score_away: int | None
    top_score_prob: float | None
    top_scores: list[ScoreProb] | None
    uncertainty: str
    entropy: float
    factors: list[Factor] | None
    is_pre_kickoff_final: bool = Field(description="Última predicción generada antes del inicio del partido")


class MatchOut(BaseModel):
    id: int
    espn_id: str
    season: str
    tournament: str
    stage: str
    stage_detail: str | None
    round: int | None
    kickoff_utc: datetime
    status: str
    status_detail: str | None
    live_clock: str | None
    home: TeamOut
    away: TeamOut
    home_goals: int | None = Field(description="Goles a los 90' (base de la predicción)")
    away_goals: int | None
    home_goals_final: int | None = Field(description="Marcador final de la fuente (incluye prórroga)")
    away_goals_final: int | None
    home_penalties: int | None
    away_penalties: int | None
    extra_time: bool
    updated_at: datetime
    prediction: PredictionOut | None = Field(None, description="Última predicción previa al inicio")
    prediction_hit: bool | None = Field(None, description="¿Acertó el resultado más probable? (solo finalizados)")


class Paginated(BaseModel):
    total: int
    items: list[MatchOut]


class StatusOut(BaseModel):
    data_version: int
    server_time: datetime
    last_sync_success: datetime | None
    last_sync_attempt: datetime | None
    last_sync_error: str | None
    is_stale: bool
    source: str
    live_matches: int
    next_kickoff: datetime | None
    active_model: str | None
    model_trained_at: datetime | None
    model_data_cutoff: datetime | None
    matches_total: int
    first_match: datetime | None
    last_finished_match: datetime | None
    refresh_hint_seconds: int
    message: str | None
