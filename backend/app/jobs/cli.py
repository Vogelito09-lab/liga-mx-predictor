"""Línea de comandos de tareas. Ejemplos (desde la carpeta backend):

    python -m app.jobs.cli backfill --start 2016-07-01
    python -m app.jobs.cli backtest
    python -m app.jobs.cli sync
    python -m app.jobs.cli live
    python -m app.jobs.cli maintenance [--force-retrain]
    python -m app.jobs.cli crosscheck
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, datetime, timezone

from app.config import get_settings
from app.jobs import tasks
from app.jobs.runner import run_job


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="app.jobs.cli", description="Tareas de Liga MX Predictor")
    parser.add_argument("--trigger", default="manual", choices=["manual", "schedule", "api"])
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backfill", help="Descarga el histórico desde ESPN")
    b.add_argument("--start", default=get_settings().history_start)
    b.add_argument("--end", default=None)
    sub.add_parser("sync", help="Sincroniza resultados y calendario cercanos")
    sub.add_parser("live", help="Sincronización ligera (ayer, hoy, mañana)")
    mt = sub.add_parser("maintenance", help="Auditoría, reentrenamiento según política y predicciones")
    mt.add_argument("--force-retrain", action="store_true")
    sub.add_parser("backtest", help="Backtesting completo, selección de modelo y entrenamiento")
    sub.add_parser("crosscheck", help="Verificación cruzada con Football-Data.co.uk")
    args = parser.parse_args(argv)

    if args.cmd == "backfill":
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end) if args.end else datetime.now(timezone.utc).date()
        fn = lambda s: tasks.backfill(s, start, end)  # noqa: E731
    elif args.cmd == "sync":
        fn = tasks.sync
    elif args.cmd == "live":
        fn = tasks.live_sync
    elif args.cmd == "maintenance":
        fn = lambda s: tasks.maintenance(s, force_retrain=args.force_retrain)  # noqa: E731
    elif args.cmd == "backtest":
        fn = tasks.backtest
    else:
        fn = tasks.crosscheck
    run = run_job(args.cmd, args.trigger, fn)
    print(json.dumps({"job": run.job, "status": run.status, "message": run.message, "stats": run.stats},
                     ensure_ascii=False, indent=2, default=str))
    return 0 if run.status in ("success", "skipped") else 1


if __name__ == "__main__":
    sys.exit(main())
