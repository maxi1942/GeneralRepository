"""Fetch live Copenhagen for-sale listings from Boliga and snapshot them.

Boliga's public site is backed by an undocumented JSON API at api.boliga.dk.
This module pages through the for-sale search endpoint for the configured
postal-code scope and writes one gzipped CSV snapshot per run into data/raw/.

The snapshot is deliberately raw (one row per listing, all fields we care about)
so metrics.py can (a) compute aggregates and (b) diff listing IDs against the
previous snapshot to derive new / delisted flow.

The API is undocumented, so field access is defensive: we probe a few candidate
key spellings for each value and tolerate missing fields rather than crashing.
"""

from __future__ import annotations

import csv
import gzip
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("boliga.scraper")

# Fields we persist per listing. Each maps to a list of candidate keys in the
# Boliga payload (spellings have drifted across API versions), tried in order.
FIELD_CANDIDATES: dict[str, list[str]] = {
    "id": ["id", "estateId", "guid"],
    "price": ["price"],
    "sqm_price": ["squaremeterPrice", "sqmPrice", "squareMeterPrice"],
    "size_m2": ["size", "livingArea", "area"],
    "rooms": ["rooms", "roomCount"],
    "days_on_market": ["daysForSale", "daysOnMarket", "daysSaleActive"],
    "price_change_pct": ["priceChangePercentTotal", "priceChangePercent"],
    "property_type": ["propertyType"],
    "zip_code": ["zipCode", "postalCode"],
    "city": ["city"],
    "build_year": ["buildYear", "yearBuilt"],
    "is_foreclosure": ["isForeclosure", "foreclosure"],
    "created_date": ["createdDate", "created"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon"],
}

USER_AGENT = (
    "copenhagen-housing-monitor/1.0 "
    "(personal market-tracking script; contact via repo owner)"
)


def _pick(record: dict[str, Any], candidates: list[str]) -> Any:
    for key in candidates:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


def _normalise(record: dict[str, Any]) -> dict[str, Any]:
    return {field: _pick(record, keys) for field, keys in FIELD_CANDIDATES.items()}


def _extract_results(payload: Any) -> list[dict[str, Any]]:
    """Boliga has wrapped results under different keys; handle the common shapes."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("results", "data", "items"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
    return []


def _total_count(payload: Any) -> int | None:
    if isinstance(payload, dict):
        meta = payload.get("meta")
        if isinstance(meta, dict):
            for key in ("totalCount", "total", "count"):
                if isinstance(meta.get(key), int):
                    return meta[key]
        for key in ("totalCount", "total", "count"):
            if isinstance(payload.get(key), int):
                return payload[key]
    return None


def _get(session: requests.Session, url: str, params: dict[str, Any],
         timeout: int, max_retries: int) -> Any:
    delay = 2.0
    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except Exception as err:  # noqa: BLE001 — retry on any transient failure
            last_err = err
            log.warning("request failed (attempt %d/%d): %s", attempt, max_retries, err)
            if attempt < max_retries:
                time.sleep(delay)
                delay *= 2
    raise RuntimeError(f"giving up after {max_retries} attempts: {last_err}")


def fetch_listings(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """Page through the for-sale endpoint and return normalised listing rows."""
    scr = cfg["scraper"]
    base_query = dict(cfg.get("query_params", {}))

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    rows: list[dict[str, Any]] = []
    seen_ids: set[Any] = set()
    page = 1
    total: int | None = None

    while page <= scr["max_pages"]:
        params = {**base_query, "pageSize": scr["page_size"], "page": page}
        payload = _get(session, scr["base_url"], params,
                       scr["request_timeout_sec"], scr["max_retries"])

        results = _extract_results(payload)
        if page == 1:
            total = _total_count(payload)
            log.info("Boliga request: %s params=%s -> total=%s, page1 results=%d",
                     scr["base_url"], params, total, len(results))

        if not results:
            log.info("no results on page %d — stopping", page)
            break

        for rec in results:
            norm = _normalise(rec)
            rid = norm.get("id")
            if rid is not None and rid in seen_ids:
                continue  # dedupe across pages
            if rid is not None:
                seen_ids.add(rid)
            rows.append(norm)

        if len(results) < scr["page_size"]:
            break
        if total is not None and len(rows) >= total:
            break

        page += 1
        time.sleep(scr["sleep_between_requests_sec"])

    log.info("collected %d unique listings across %d page(s)", len(rows), page)
    return rows


def save_snapshot(rows: list[dict[str, Any]], cfg: dict[str, Any],
                  project_dir: Path, snapshot_date: date | None = None) -> Path:
    """Write listings to data/raw/<date>.csv.gz. Returns the path written."""
    snapshot_date = snapshot_date or date.today()
    raw_dir = project_dir / cfg["paths"]["raw_dir"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    out_path = raw_dir / f"{snapshot_date.isoformat()}.csv.gz"

    fieldnames = list(FIELD_CANDIDATES.keys())
    with gzip.open(out_path, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    log.info("wrote snapshot: %s (%d rows)", out_path, len(rows))
    return out_path
