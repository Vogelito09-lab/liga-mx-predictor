"""Configuración de la aplicación leída de variables de entorno (.env)."""
from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: str = Field("development", description="development | production | test")
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/ligamx"
    admin_token: str = Field("", description="Token para rutas /api/admin. Vacío = admin deshabilitado.")
    cors_origins: str = "http://localhost:5173"

    espn_base_url: str = "https://site.api.espn.com/apis/site/v2/sports/soccer/mex.1"
    football_data_url: str = "https://www.football-data.co.uk/new/MEX.csv"
    http_timeout_s: float = 20.0
    http_min_interval_s: float = 0.4  # pausa mínima entre consultas a la misma fuente

    history_start: str = "2016-07-01"  # inicio del Apertura 2016
    local_tz: str = "America/Mexico_City"

    # Sincronización: días hacia atrás/adelante que se revisan en cada ejecución.
    sync_days_back: int = 4
    sync_days_ahead: int = 60  # cubre el calendario hasta el final de la fase regular
    # Si la última sincronización es más antigua que esto, la API lo indica como "datos atrasados".
    stale_after_minutes: int = 30
    # Sin partidos en juego la sincronización completa corre cada 6 h (GitHub puede retrasarla un poco).
    stale_after_minutes_idle: int = 7 * 60

    @field_validator("database_url")
    @classmethod
    def _driver(cls, v: str) -> str:
        # Neon y Render entregan "postgres://" o "postgresql://"; SQLAlchemy necesita el driver psycopg 3.
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
