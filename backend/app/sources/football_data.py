"""Football-Data.co.uk (archivo MEX.csv): fuente secundaria para verificación cruzada de marcadores.

Columnas usadas (definidas en https://www.football-data.co.uk/notes.txt):
  Season, Date (dd/mm/yyyy), Time, Home, Away, HG, AG, Res.
Este archivo no se usa para cargar partidos: solo para detectar discrepancias con ESPN, que quedan
registradas en `data_issues` para revisión manual.
"""
from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date, datetime

from app.config import get_settings
from app.sources.http import PoliteClient

SOURCE = "football-data"


@dataclass
class FDRow:
    day: date
    home: str
    away: str
    hg: int | None
    ag: int | None
    season: str


def parse_csv(text: str) -> tuple[list[FDRow], list[str]]:
    rows, problems = [], []
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for i, r in enumerate(reader, start=2):
        try:
            raw = (r.get("Date") or "").strip()
            fmt = "%d/%m/%Y" if len(raw.split("/")[-1]) == 4 else "%d/%m/%y"
            day = datetime.strptime(raw, fmt).date()
            hg = int(r["HG"]) if (r.get("HG") or "").strip() != "" else None
            ag = int(r["AG"]) if (r.get("AG") or "").strip() != "" else None
            rows.append(FDRow(day, r["Home"].strip(), r["Away"].strip(), hg, ag, (r.get("Season") or "").strip()))
        except (KeyError, ValueError) as exc:
            problems.append(f"fila {i}: {exc}")
    return rows, problems


def fetch(client: PoliteClient | None = None) -> str:
    client = client or PoliteClient()
    return client.get_text(get_settings().football_data_url)
