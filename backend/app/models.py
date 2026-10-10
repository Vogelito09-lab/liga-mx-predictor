"""Modelo de datos (SQLAlchemy 2). Las migraciones viven en alembic/versions."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# Estados normalizados de un partido.
SCHEDULED = "scheduled"
IN_PROGRESS = "in_progress"
FINISHED = "finished"
POSTPONED = "postponed"
SUSPENDED = "suspended"
CANCELED = "canceled"
MATCH_STATUSES = (SCHEDULED, IN_PROGRESS, FINISHED, POSTPONED, SUSPENDED, CANCELED)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    espn_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    abbreviation: Mapped[str | None] = mapped_column(String(16))
    logo_url: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    aliases: Mapped[list[TeamAlias]] = relationship(back_populates="team")


class TeamAlias(Base):
    """Nombres alternativos de un equipo (cambios de nombre, nombres en otras fuentes)."""

    __tablename__ = "team_aliases"

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    alias_key: Mapped[str] = mapped_column(String(120), unique=True)  # normalizado (minúsculas, sin acentos)
    alias: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(32))

    team: Mapped[Team] = relationship(back_populates="aliases")


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[int] = mapped_column(primary_key=True)
    espn_id: Mapped[str] = mapped_column(String(32), unique=True)
    season: Mapped[str] = mapped_column(String(16))  # p. ej. "2016-17"
    tournament: Mapped[str] = mapped_column(String(40))  # p. ej. "Apertura 2016"
    stage: Mapped[str] = mapped_column(String(20))  # regular | liguilla | play-in
    stage_detail: Mapped[str | None] = mapped_column(String(80))
    round: Mapped[int | None] = mapped_column(Integer)  # jornada (fase regular)
    kickoff_utc: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    status: Mapped[str] = mapped_column(String(16))
    status_detail: Mapped[str | None] = mapped_column(String(80))
    # Marcador al minuto 90 (+ añadido). Es el que usa el modelo.
    home_goals: Mapped[int | None] = mapped_column(Integer)
    away_goals: Mapped[int | None] = mapped_column(Integer)
    # Marcador final según la fuente (incluye prórroga si la hubo).
    home_goals_final: Mapped[int | None] = mapped_column(Integer)
    away_goals_final: Mapped[int | None] = mapped_column(Integer)
    home_penalties: Mapped[int | None] = mapped_column(Integer)
    away_penalties: Mapped[int | None] = mapped_column(Integer)
    extra_time: Mapped[bool] = mapped_column(Boolean, default=False)
    # Minuto en curso o descripción corta que da la fuente para partidos en juego.
    live_clock: Mapped[str | None] = mapped_column(String(40))
    source: Mapped[str] = mapped_column(String(32), default="espn")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])

    __table_args__ = (
        Index("ix_matches_kickoff", "kickoff_utc"),
        Index("ix_matches_tournament", "tournament"),
        Index("ix_matches_status", "status"),
    )

    @property
    def has_regulation_score(self) -> bool:
        return self.home_goals is not None and self.away_goals is not None


class SourceRecord(Base):
    """Copia cruda de lo que devolvió cada fuente (una fila por versión distinta del dato)."""

    __tablename__ = "source_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    source_key: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("source", "source_key", "payload_hash", name="uq_source_record_version"),)


class DataIssue(Base):
    """Problemas de calidad detectados. Nunca se borran datos en silencio: se registran aquí."""

    __tablename__ = "data_issues"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int | None] = mapped_column(ForeignKey("matches.id"))
    source: Mapped[str] = mapped_column(String(32))
    source_key: Mapped[str | None] = mapped_column(String(64))
    severity: Mapped[str] = mapped_column(String(10))  # info | warning | error
    code: Mapped[str] = mapped_column(String(60))
    message: Mapped[str] = mapped_column(Text)
    details: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (UniqueConstraint("source", "source_key", "code", name="uq_issue_per_record"),)


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    version: Mapped[str] = mapped_column(String(80), unique=True)
    model_type: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    train_matches: Mapped[int] = mapped_column(Integer)
    metrics: Mapped[dict | None] = mapped_column(JSON)
    artifact: Mapped[bytes] = mapped_column(LargeBinary)
    artifact_sha256: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)


class Prediction(Base):
    """Predicción inmutable. Una nueva predicción para el mismo partido crea otra fila."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"))
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    data_cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    exp_home_goals: Mapped[float | None] = mapped_column(Float)
    exp_away_goals: Mapped[float | None] = mapped_column(Float)
    top_score_home: Mapped[int | None] = mapped_column(Integer)
    top_score_away: Mapped[int | None] = mapped_column(Integer)
    top_score_prob: Mapped[float | None] = mapped_column(Float)
    top_scores: Mapped[list | None] = mapped_column(JSON)
    uncertainty: Mapped[str] = mapped_column(String(10))  # baja | media | alta
    entropy: Mapped[float] = mapped_column(Float)
    factors: Mapped[list | None] = mapped_column(JSON)
    inputs_hash: Mapped[str] = mapped_column(String(64))

    match: Mapped[Match] = relationship()
    model_version: Mapped[ModelVersion] = relationship()

    __table_args__ = (Index("ix_predictions_match_generated", "match_id", "generated_at"),)


class BacktestRun(Base):
    __tablename__ = "backtest_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    config: Mapped[dict] = mapped_column(JSON)
    summary: Mapped[dict] = mapped_column(JSON)
    selected_model: Mapped[str | None] = mapped_column(String(40))


class BacktestPrediction(Base):
    __tablename__ = "backtest_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("backtest_runs.id", ondelete="CASCADE"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    model: Mapped[str] = mapped_column(String(40))
    split: Mapped[str] = mapped_column(String(12))  # validation | test
    fold: Mapped[str] = mapped_column(String(40))  # torneo evaluado
    p_home: Mapped[float] = mapped_column(Float)
    p_draw: Mapped[float] = mapped_column(Float)
    p_away: Mapped[float] = mapped_column(Float)
    exp_home_goals: Mapped[float | None] = mapped_column(Float)
    exp_away_goals: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_bt_pred_run_model", "run_id", "model"),)


class JobRun(Base):
    __tablename__ = "job_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job: Mapped[str] = mapped_column(String(40))
    trigger: Mapped[str] = mapped_column(String(20))  # schedule | manual | api
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(12))  # running | success | failed | skipped
    message: Mapped[str | None] = mapped_column(Text)
    stats: Mapped[dict | None] = mapped_column(JSON)

    __table_args__ = (Index("ix_job_runs_job_started", "job", "started_at"),)


class AppState(Base):
    """Pares clave/valor: versión de datos, última sincronización, etc."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


# ---------------------------------------------------------------------------------------------------
# Quiniela entre amigos: cuentas de usuario y pronósticos
# ---------------------------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # siempre en minúsculas
    password_hash: Mapped[str] = mapped_column(String(200))
    # Nombre que aparece en las tablas (nunca se muestra el correo). Se elige al primer ingreso.
    display_name: Mapped[str | None] = mapped_column(String(24))
    display_name_key: Mapped[str | None] = mapped_column(String(24), unique=True)  # minúsculas, sin acentos
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Cada persona pide entrar y el administrador la aprueba. Sin aprobar no puede iniciar sesión.
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(Base):
    """Sesión iniciada. Solo se guarda el hash del token que tiene el navegador."""

    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class EmailToken(Base):
    """Enlace de un solo uso enviado por correo: confirmar la cuenta o restablecer la contraseña."""

    __tablename__ = "email_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String(10))  # verify | reset
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship()


class QuinielaPick(Base):
    """Marcador que un usuario pronosticó para un partido. Se puede cambiar hasta que el partido empieza."""

    __tablename__ = "quiniela_picks"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id"))
    home_goals: Mapped[int] = mapped_column(Integer)
    away_goals: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped[User] = relationship()

    __table_args__ = (UniqueConstraint("user_id", "match_id", name="uq_pick_user_match"),
                      Index("ix_picks_match", "match_id"))
