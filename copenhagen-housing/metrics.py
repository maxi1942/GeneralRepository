"""Turn a raw listing snapshot into weekly aggregate metrics + market flow.

For each snapshot we compute, per segment (all / apartment / house):
  - n_listings           active inventory
  - median_sqm_price     asking price per m2 (the headline price trend)
  - mean_sqm_price
  - median_price
  - median_days_on_market   how long current inventory has sat (staleness proxy)
  - pct_price_cut        share of listings that have cut their asking price
  - median_cut_pct       median size of those cuts (magnitude, positive number)

Flow (only the "all" segment, needs the previous snapshot):
  - new_listings         IDs present now but not in the previous snapshot
  - delisted             IDs in the previous snapshot but gone now (sold OR withdrawn)

Rows are appended to data/metrics_weekly.csv. Re-running for a date that already
exists overwrites that date's rows (idempotent), so a re-run never double-counts.

Pure stdlib on purpose — no pandas — so the CI job has almost nothing to install
and almost nothing to break.
"""

from __future__ import annotations

import csv
import gzip
import logging
import statistics
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger("boliga.metrics")

METRIC_FIELDS = [
    "snapshot_date", "segment", "n_listings",
    "median_sqm_price", "mean_sqm_price", "median_price",
    "median_days_on_market", "pct_price_cut", "median_cut_pct",
    "new_listings", "delisted",
]


def _to_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # reject NaN


def _to_int(value: Any) -> int | None:
    f = _to_float(value)
    return int(f) if f is not None else None


def _median(values: list[float]) -> float | None:
    return round(statistics.median(values), 1) if values else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 1) if values else None


def load_snapshot(path: Path) -> list[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _bucket_of(property_type: Any, buckets: dict[str, list[int]]) -> str:
    pt = _to_int(property_type)
    for name, codes in buckets.items():
        if pt in codes:
            return name
    return "other"


def _segment_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sqm = [v for r in rows if (v := _to_float(r.get("sqm_price"))) and v > 0]
    prices = [v for r in rows if (v := _to_float(r.get("price"))) and v > 0]
    dom = [v for r in rows if (v := _to_float(r.get("days_on_market"))) is not None and v >= 0]

    cut_pcts = [v for r in rows if (v := _to_float(r.get("price_change_pct"))) is not None]
    cuts = [abs(v) for v in cut_pcts if v < 0]  # magnitude of price DECREASES
    pct_cut = round(100 * len(cuts) / len(cut_pcts), 1) if cut_pcts else None

    return {
        "n_listings": len(rows),
        "median_sqm_price": _median(sqm),
        "mean_sqm_price": _mean(sqm),
        "median_price": _median(prices),
        "median_days_on_market": _median(dom),
        "pct_price_cut": pct_cut,
        "median_cut_pct": _median(cuts),
    }


def compute_metrics(rows: list[dict[str, Any]], cfg: dict[str, Any],
                    prev_ids: set[str] | None, snapshot_date: date) -> list[dict[str, Any]]:
    buckets = cfg["property_type_buckets"]

    segments: dict[str, list[dict[str, Any]]] = {"all": rows}
    for name in buckets:
        segments[name] = []
    segments.setdefault("other", [])
    for r in rows:
        seg = _bucket_of(r.get("property_type"), buckets)
        segments.setdefault(seg, []).append(r)

    # Flow (all-segment only)
    cur_ids = {str(r.get("id")) for r in rows if r.get("id") not in (None, "")}
    if prev_ids is None:
        new_listings = delisted = None
    else:
        new_listings = len(cur_ids - prev_ids)
        delisted = len(prev_ids - cur_ids)

    out: list[dict[str, Any]] = []
    for seg, seg_rows in segments.items():
        if seg == "other" and not seg_rows:
            continue
        m = _segment_metrics(seg_rows)
        m["snapshot_date"] = snapshot_date.isoformat()
        m["segment"] = seg
        m["new_listings"] = new_listings if seg == "all" else None
        m["delisted"] = delisted if seg == "all" else None
        out.append({k: m.get(k) for k in METRIC_FIELDS})

    log.info("computed metrics for %d segments (new=%s, delisted=%s)",
             len(out), new_listings, delisted)
    return out


def previous_snapshot_ids(raw_dir: Path, before: date) -> set[str] | None:
    """IDs from the most recent snapshot strictly before `before`, or None."""
    if not raw_dir.exists():
        return None
    candidates = sorted(
        p for p in raw_dir.glob("*.csv.gz")
        if p.stem.replace(".csv", "") < before.isoformat()
    )
    if not candidates:
        return None
    rows = load_snapshot(candidates[-1])
    return {str(r.get("id")) for r in rows if r.get("id") not in (None, "")}


def append_metrics(new_rows: list[dict[str, Any]], metrics_csv: Path,
                   snapshot_date: date) -> None:
    """Append rows, replacing any existing rows for the same snapshot_date."""
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if metrics_csv.exists():
        with metrics_csv.open("r", newline="", encoding="utf-8") as fh:
            existing = [r for r in csv.DictReader(fh)
                        if r.get("snapshot_date") != snapshot_date.isoformat()]

    combined = existing + new_rows
    combined.sort(key=lambda r: (str(r["snapshot_date"]), str(r["segment"])))

    with metrics_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=METRIC_FIELDS)
        writer.writeheader()
        writer.writerows(combined)

    log.info("wrote %d metric rows to %s", len(combined), metrics_csv)
