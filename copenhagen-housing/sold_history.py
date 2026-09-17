"""Accumulate a permanent, de-duplicated archive of actual sold apartments.

Boliga's sold feed is a rolling ~180-day window, so on its own it forgets older
sales. This keeps every sale we've ever seen (keyed by address + date + price) in
data/sold_history.csv.gz, so you can check back and compare what specific apartments
went for over time — not just the last few months.

Garbage dates in the feed (far-future / far-past values) are filtered out.
"""

from __future__ import annotations

import csv
import gzip
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import metrics as M

log = logging.getLogger("boliga.soldhist")

FIELDS = ["street", "zip_code", "size_m2", "rooms", "price", "sqm_price",
          "change_pct", "property_type", "sold_date"]
MAX_AGE_DAYS = 400   # ignore records dated older than this or in the future


def _norm(s: Any) -> str:
    return str(s or "").strip().lower()


def _valid_date(value: Any, today: date) -> date | None:
    try:
        d = datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    if d > today or d < today - timedelta(days=MAX_AGE_DAYS):
        return None
    return d


def _key(rec: dict) -> str:
    return f"{_norm(rec.get('street'))}|{rec.get('zip_code')}|{rec.get('sold_date')}|{rec.get('price')}"


def load(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[_key(r)] = {k: r.get(k) for k in FIELDS}
    return out


def merge(history: dict[str, dict], sold: list[dict], today: date | None = None) -> int:
    today = today or date.today()
    added = 0
    for r in sold:
        d = _valid_date(r.get("sold_date"), today)
        if d is None:
            continue
        price = M._to_float(r.get("price"))
        sqm = M._to_float(r.get("sqm_price"))
        if not price or price <= 0 or not sqm or sqm <= 0:
            continue
        rec = {k: r.get(k) for k in FIELDS}
        rec["sold_date"] = d.isoformat()
        k = _key(rec)
        if k not in history:
            history[k] = rec
            added += 1
    log.info("sold history: +%d new records, %d total", added, len(history))
    return added


def save(history: dict[str, dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(history.values(), key=lambda r: str(r.get("sold_date")), reverse=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def as_list(history: dict[str, dict]) -> list[dict]:
    return sorted(history.values(), key=lambda r: str(r.get("sold_date")), reverse=True)
