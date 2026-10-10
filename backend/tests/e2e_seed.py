"""Prepara la base de datos de la prueba de extremo a extremo con la liga SIMULADA (no son datos reales)."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.db import get_engine, get_sessionmaker
from app.predict import service
from tests.helpers import SMALL_BT, load_simulated

root = Path(__file__).resolve().parents[1]
with get_engine().begin() as conn:
    conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
cfg = Config(str(root / "alembic.ini"))
cfg.set_main_option("script_location", str(root / "alembic"))
command.upgrade(cfg, "head")
with get_sessionmaker()() as s:
    load_simulated(s)
    service.run_and_store_backtest(s, SMALL_BT)
    service.train_production(s)
    s.commit()
print("seed ok")
