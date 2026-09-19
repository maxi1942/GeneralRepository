"""Fetch live for-sale listings AND recent sold records from Boliga.

Boliga's public site is backed by an undocumented JSON API at api.boliga.dk.
This module pages through two endpoints for the configured postal-code scope:
  - for-sale search  -> active listings (asking prices, days-on-market, cuts)
  - sold search      -> realised sale prices from the land registry (lags ~1-3 mo)

Each run writes one gzipped CSV snapshot per feed. Snapshots are deliberately raw
(one row per listing) so metrics.py can aggregate them and diff IDs for flow.

The API is undocumented, so field access is defensive: we probe several candidate
key spellings for each value and tolerate missing fields rather than crashing.
"""

from __future__ import annotations

import csv
import gzip
import logging
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("boliga.scraper")

# For-sale fields. Each maps to candidate keys tried in order.
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
    "street": ["street", "address", "road"],
    "build_year": ["buildYear", "yearBuilt"],
    "is_foreclosure": ["isForeclosure", "foreclosure"],
    "created_date": ["createdDate", "created"],
    "latitude": ["latitude", "lat"],
    "longitude": ["longitude", "lng", "lon"],
}

# Sold-record fields.
SOLD_FIELD_CANDIDATES: dict[str, list[str]] = {
    "id": ["estateId", "id", "guid"],                 # Boliga property id, if the sale was ever listed
    "estate_url": ["estateUrl", "url"],               # agent listing url, if present
    "price": ["price", "amount", "soldPrice"],
    "sqm_price": ["squaremeterPrice", "sqmPrice", "squareMeterPrice"],
    "size_m2": ["size", "livingArea", "area"],
    "rooms": ["rooms", "roomCount"],
    # % change from original listing to realised sale, if Boliga provides it — this is
    # the realised sale-to-ask discount when present.
    "change_pct": ["change", "priceChangePercentTotal", "changePercent"],
    "property_type": ["propertyType"],
    "zip_code": ["zipCode", "postalCode"],
    "city": ["city"],
    "street": ["street", "address", "road"],
    "sold_date": ["soldDate", "saleDate", "date"],
    "sale_type": ["saleType", "saleTypeName"],
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


def _normalise(record: dict[str, Any], candidates: dict[str, list[str]]) -> dict[str, Any]:
    return {field: _pick(record, keys) for field, keys in candidates.items()}


def _extract_results(payload: Any) -> list[dict[str, Any]]:
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
            # Boliga rate-limits a burst of requests with HTTP 429. Respect Retry-After
            # (or wait a fixed cooldown) so the paged fetch can drain and continue,
            # instead of giving up and returning partial data.
            wait = delay
            resp_obj = getattr(err, "response", None)
            if resp_obj is not None and getattr(resp_obj, "status_code", None) == 429:
                ra = resp_obj.headers.get("Retry-After")
                wait = float(ra) if (ra and str(ra).isdigit()) else 20.0
            log.warning("request failed (attempt %d/%d): %s — waiting %.0fs",
                        attempt, max_retries, err, wait if attempt < max_retries else 0)
            if attempt < max_retries:
                time.sleep(wait)
                delay *= 2
    raise RuntimeError(f"giving up after {max_retries} attempts: {last_err}")


def _paged_fetch(base_url: str, base_query: dict[str, Any], page_size: int,
                 max_pages: int, timeout: int, sleep_s: float, max_retries: int,
                 candidates: dict[str, list[str]], label: str,
                 dedupe_key: str | None, time_budget: float | None = None,
                 soft_fail: bool = False) -> list[dict[str, Any]]:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    rows: list[dict[str, Any]] = []
    seen: set[Any] = set()
    page = 1
    total: int | None = None
    start = time.monotonic()

    while page <= max_pages:
        if time_budget is not None and time.monotonic() - start > time_budget:
            log.warning("%s: time budget (%ss) reached at page %d — returning %d partial rows",
                        label, time_budget, page, len(rows))
            break
        params = {**base_query, "pageSize": page_size, "page": page}
        try:
            payload = _get(session, base_url, params, timeout, max_retries)
        except Exception as err:  # noqa: BLE001
            if soft_fail:
                log.warning("%s: page %d failed (%s) — returning %d partial rows",
                            label, page, err, len(rows))
                break
            raise
        results = _extract_results(payload)
        if page == 1:
            total = _total_count(payload)
            log.info("%s request: %s params=%s -> total=%s, page1 results=%d",
                     label, base_url, params, total, len(results))
        if not results:
            break
        for rec in results:
            norm = _normalise(rec, candidates)
            if dedupe_key:
                k = norm.get(dedupe_key)
                if k is not None and k in seen:
                    continue
                if k is not None:
                    seen.add(k)
            rows.append(norm)
        if len(results) < page_size:
            break
        if total is not None and len(rows) >= total:
            break
        page += 1
        time.sleep(sleep_s)

    log.info("%s: collected %d rows across %d page(s)", label, len(rows), page)
    return rows


def fetch_listings(cfg: dict[str, Any]) -> list[dict[str, Any]]:
    scr = cfg["scraper"]
    return _paged_fetch(
        scr["base_url"], dict(cfg.get("query_params", {})),
        scr["page_size"], scr["max_pages"], scr["request_timeout_sec"],
        scr["sleep_between_requests_sec"], scr["max_retries"],
        FIELD_CANDIDATES, "for-sale", dedupe_key="id")


def fetch_sold(cfg: dict[str, Any], today: date | None = None) -> list[dict[str, Any]]:
    sold = cfg["sold"]
    today = today or date.today()
    since = (today - timedelta(days=sold["lookback_days"])).isoformat()
    base_query = {
        **dict(cfg.get("sold_query_params", {})),
        "salesDateMin": since,
        "salesDateMax": today.isoformat(),
    }
    scr = cfg["scraper"]
    return _paged_fetch(
        sold["base_url"], base_query,
        sold["page_size"], sold["max_pages"],
        sold.get("request_timeout_sec", scr["request_timeout_sec"]),
        scr["sleep_between_requests_sec"],
        sold.get("max_retries", 2),
        SOLD_FIELD_CANDIDATES, "sold", dedupe_key=None,
        time_budget=sold.get("time_budget_sec", 120), soft_fail=True)


def save_snapshot(rows: list[dict[str, Any]], out_dir: Path, fieldnames: list[str],
                  snapshot_date: date | None = None) -> Path:
    snapshot_date = snapshot_date or date.today()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{snapshot_date.isoformat()}.csv.gz"
    with gzip.open(out_path, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    log.info("wrote snapshot: %s (%d rows)", out_path, len(rows))
    return out_path
