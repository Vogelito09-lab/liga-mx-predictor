import os

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://postgres:postgres@localhost:5432/ligamx_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ENV"] = "test"
os.environ["ADMIN_TOKEN"] = "token-de-prueba"

import pytest  # noqa: E402

from app.db import get_engine, get_sessionmaker  # noqa: E402


@pytest.fixture()
def engine():
    """Base de datos limpia creada con las migraciones reales de Alembic (incluye triggers)."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import text

    eng = get_engine()
    with eng.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    command.upgrade(cfg, "head")
    yield eng


@pytest.fixture()
def session(engine):
    s = get_sessionmaker()()
    yield s
    s.rollback()
    s.close()
