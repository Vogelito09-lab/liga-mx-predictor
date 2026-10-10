"""Ejecución de tareas con candado global, registro en `job_runs` y manejo de errores.

El candado es un advisory lock de PostgreSQL: si una tarea de escritura ya está corriendo (en GitHub
Actions, en la API o en tu computadora), la segunda se registra como "skipped" y termina sin tocar datos.
"""
from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from contextlib import contextmanager

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app import models as m
from app.db import get_engine, get_sessionmaker

log = logging.getLogger(__name__)

WRITE_LOCK_KEY = 482_017_2016  # número arbitrario y fijo para este proyecto


@contextmanager
def write_lock():
    """Candado a nivel de sesión de PostgreSQL. Devuelve True si se obtuvo.

    La conexión va en AUTOCOMMIT: si quedara "idle in transaction" durante una tarea larga, Neon la cortaría
    (idle_in_transaction_session_timeout) y el desbloqueo fallaría aunque la tarea ya hubiera terminado bien.
    """
    conn = get_engine().connect().execution_options(isolation_level="AUTOCOMMIT")
    try:
        got = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": WRITE_LOCK_KEY}).scalar()
        try:
            yield bool(got)
        finally:
            if got:
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": WRITE_LOCK_KEY})
                except DBAPIError:  # si la conexión se cayó, PostgreSQL ya liberó el candado
                    log.warning("No se pudo liberar el candado explícitamente; la conexión ya estaba cerrada")
    finally:
        conn.close()


def run_job(job: str, trigger: str, fn: Callable[[Session], dict]) -> m.JobRun:
    """Ejecuta `fn(session)` dentro del candado. Si falla, se revierte todo lo que escribió."""
    Sess = get_sessionmaker()
    with Sess() as s:
        run = m.JobRun(job=job, trigger=trigger, status="running")
        s.add(run)
        s.commit()
        run_id = run.id
    with write_lock() as got:
        if not got:
            return _finish(run_id, "skipped", "Otra actualización está en curso; se omite esta ejecución", None)
        try:
            with Sess() as s:
                stats = fn(s)
                s.commit()
            stats = stats if isinstance(stats, dict) else {}
            status = stats.pop("_status", "success")
            return _finish(run_id, status, stats.pop("message", None), stats)
        except Exception as exc:  # se registra y se re-lanza para que el proceso termine con error
            log.exception("Tarea %s falló", job)
            _finish(run_id, "failed", f"{type(exc).__name__}: {exc}", {"traceback": traceback.format_exc()[-4000:]})
            raise


def _finish(run_id: int, status: str, message: str | None, stats: dict | None) -> m.JobRun:
    with get_sessionmaker()() as s:
        run = s.get(m.JobRun, run_id)
        run.status, run.message, run.stats, run.finished_at = status, message, stats, m.utcnow()
        s.commit()
        s.refresh(run)
        return run
