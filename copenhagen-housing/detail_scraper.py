"""Fetch per-listing detail from Boliga and cache it, to enrich the valuation.

The search API only returns summary fields. Attributes that decide whether a flat is
actually a good deal — floor, energy class, ownership type (ejer / andel / leasehold),
balcony, elevator, monthly owner fee, renovation year — live on the listing detail.

Because that's ~1 request per listing, we:
  - cache each listing's RAW detail JSON forever (data/details.csv.gz), keyed by id, so
    every listing is fetched at most once ever;
  - cap new fetches per run (`detail.max_per_run`) and go gently (throttled);
  - fetch in a caller-supplied priority order (undervalued candidates first).

We store the RAW JSON and parse it in code (attributes.py), so refining the parsing
never requires re-fetching. The detail endpoint is undocumented, so we try a few
candidate URLs and log the first success's shape for inspection.
"""

from __future__ import annotations

import csv
import gzip
import json
import logging
import time
from datetime import date
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("boliga.detail")

USER_AGENT = ("copenhagen-housing-monitor/1.0 "
             "(personal market-tracking script; contact via repo owner)")


def load_cache(path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return cache
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            raw = row.get("raw") or ""
            try:
                parsed = json.loads(raw) if raw else None
            except json.JSONDecodeError:
                parsed = None
            cache[str(row["id"])] = {
                "fetched_date": row.get("fetched_date"),
                "endpoint": row.get("endpoint"),
                "raw": parsed,
            }
    return cache


def save_cache(cache: dict[str, dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["id", "fetched_date", "endpoint", "raw"])
        writer.writeheader()
        for rid, rec in cache.items():
            writer.writerow({
                "id": rid,
                "fetched_date": rec.get("fetched_date"),
                "endpoint": rec.get("endpoint"),
                "raw": json.dumps(rec.get("raw"), ensure_ascii=False) if rec.get("raw") is not None else "",
            })


def _looks_useful(payload: Any) -> bool:
    """A real detail response is a dict (or wraps one) with several fields."""
    if isinstance(payload, dict):
        d = payload
        for key in ("data", "estate", "result", "property"):
            if isinstance(payload.get(key), dict):
                d = payload[key]
                break
        return len(d) >= 5
    return False


def fetch_detail(session: requests.Session, listing_id: Any, endpoints: list[str],
                 timeout: int, max_retries: int) -> tuple[dict | None, str | None]:
    for tmpl in endpoints:
        url = tmpl.format(id=listing_id)
        delay = 2.0
        for attempt in range(1, max_retries + 1):
            try:
                resp = session.get(url, timeout=timeout)
                if resp.status_code == 404:
                    break  # try next endpoint template
                resp.raise_for_status()
                payload = resp.json()
                if _looks_useful(payload):
                    return payload, tmpl
                break
            except Exception as err:  # noqa: BLE001
                log.debug("detail fetch %s failed (%d/%d): %s", url, attempt, max_retries, err)
                if attempt < max_retries:
                    time.sleep(delay)
                    delay *= 2
    return None, None


def enrich(active: list[dict], cfg: dict, project_dir: Path,
           priority_ids: list[Any]) -> dict[str, dict[str, Any]]:
    dcfg = cfg["detail"]
    path = project_dir / dcfg["cache"]
    cache = load_cache(path)
    have = set(cache.keys())

    active_ids = {str(r.get("id")) for r in active if r.get("id") not in (None, "")}
    # priority order, then any remaining active ids, skipping already-cached
    ordered = [str(i) for i in priority_ids if str(i) in active_ids]
    ordered += [i for i in active_ids if i not in ordered]
    todo = [i for i in ordered if i not in have][:dcfg["max_per_run"]]

    if not todo:
        log.info("detail cache: %d listings cached, nothing new to fetch", len(cache))
        # still prune stale entries occasionally (ids long gone from the market)
        return cache

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    endpoints = dcfg["endpoints"]
    # Detail-specific network settings: short timeout, few retries — detail is
    # best-effort and must never hang the run.
    timeout = dcfg.get("request_timeout_sec", 12)
    retries = dcfg.get("max_retries", 1)
    budget = dcfg.get("time_budget_sec", 180)
    abort_n = dcfg.get("abort_after_consecutive_failures", 12)
    start = time.monotonic()
    fetched = 0
    consecutive_fail = 0
    logged_sample = False
    for i, rid in enumerate(todo):
        if time.monotonic() - start > budget:
            log.info("detail: time budget (%ds) reached after %d attempts — stopping early", budget, i)
            break
        if consecutive_fail >= abort_n:
            log.warning("detail: %d consecutive failures — likely rate-limited; stopping "
                        "(will resume next run)", consecutive_fail)
            break
        raw, ep = fetch_detail(session, rid, endpoints, timeout, retries)
        if raw is None:
            consecutive_fail += 1
        else:
            consecutive_fail = 0
        if raw is not None:
            cache[rid] = {"fetched_date": date.today().isoformat(), "endpoint": ep, "raw": raw}
            fetched += 1
            if not logged_sample:
                log.info("DETAIL SAMPLE (endpoint=%s id=%s): %s", ep, rid,
                         json.dumps(raw, ensure_ascii=False)[:1800])
                logged_sample = True
        time.sleep(dcfg["sleep_between_requests_sec"])

    save_cache(cache, path)
    log.info("detail enrichment: fetched %d new / %d attempted; cache now %d listings",
             fetched, len(todo), len(cache))
    if fetched == 0:
        log.warning("detail: 0 successful fetches — check detail.endpoints in config.yaml "
                    "against the live Boliga API.")
    return cache
