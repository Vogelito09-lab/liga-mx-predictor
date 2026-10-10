"""Conexión a PostgreSQL y fábrica de sesiones."""
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    url = get_settings().database_url
    # pool_pre_ping: Neon suspende el cómputo tras inactividad; así se descartan conexiones muertas.
    return create_engine(url, pool_pre_ping=True, pool_size=5, max_overflow=5, future=True)


def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
