"""Turn raw snapshots (active + sold) into weekly aggregate metrics.

For each segment (property type: all / apartment / house / other, and each district)
we compute, from the ACTIVE listing snapshot:
  n_listings, median/mean_sqm_price, median_price, median_days_on_market,
  pct_price_cut, median_cut_pct
and from the SOLD snapshot (trailing `lookback_days`):
  sold_count, median_sold_sqm_price, median_sold_discount_pct (if Boliga provides it),
  months_of_supply = active inventory / monthly sales rate

Flow (all-segment only, needs the previous snapshot): new_listings, delisted.

Rows are appended to data/metrics_weekly.csv; re-running for an existing date
overwrites that date's rows (idempotent). Pure stdlib — no pandas.
"""

from __future__ import annotations

import csv
import gzip
import logging
import statistics
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("boliga.metrics")

METRIC_FIELDS = [
    "snapshot_date", "segment", "n_listings",
    "median_sqm_price", "mean_sqm_price", "median_price",
    "median_days_on_market", "pct_price_cut", "median_cut_pct",
    "sold_count", "median_sold_sqm_price", "median_sold_discount_pct",
    "months_of_supply", "new_listings", "delisted",
]


def _to_float(value: Any) -> float | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


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


# --------------------------------------------------------------------------- #
# Segment predicates
# --------------------------------------------------------------------------- #

def district_of(zip_code: Any, districts: dict[str, Any]) -> str | None:
    z = _to_int(zip_code)
    if z is None:
        return None
    for key, spec in districts.items():
        for lo, hi in spec["ranges"]:
            if lo <= z <= hi:
                return key
    return None


def build_segments(cfg: dict[str, Any]) -> dict[str, Callable[[dict], bool]]:
    buckets = cfg["property_type_buckets"]
    districts = cfg["districts"]

    def in_codes(codes):
        return lambda r: _to_int(r.get("property_type")) in codes

    def in_district(key):
        return lambda r: district_of(r.get("zip_code"), districts) == key

    known = {c for codes in buckets.values() for c in codes}
    segs: dict[str, Callable[[dict], bool]] = {"all": lambda r: True}
    for name, codes in buckets.items():
        segs[name] = in_codes(codes)
    segs["other"] = lambda r: _to_int(r.get("property_type")) not in known
    for key in districts:
        segs[f"dist:{key}"] = in_district(key)
    return segs


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def _active_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    sqm = [v for r in rows if (v := _to_float(r.get("sqm_price"))) and v > 0]
    prices = [v for r in rows if (v := _to_float(r.get("price"))) and v > 0]
    dom = [v for r in rows if (v := _to_float(r.get("days_on_market"))) is not None and v >= 0]
    cut_pcts = [v for r in rows if (v := _to_float(r.get("price_change_pct"))) is not None]
    cuts = [abs(v) for v in cut_pcts if v < 0]
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


def _parse_date(v: Any) -> date | None:
    if not v:
        return None
    s = str(v)[:10]
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def _sold_metrics(rows: list[dict[str, Any]], n_active: int,
                  cfg: dict[str, Any], today: date) -> dict[str, Any]:
    sqm = [v for r in rows if (v := _to_float(r.get("sqm_price"))) and v > 0]
    # realised discount: Boliga's `change` is negative when sold below original ask
    discounts = [abs(v) for r in rows
                 if (v := _to_float(r.get("change_pct"))) is not None and v < 0]

    # Sales RATE over a fully-registered window (ends rate_lag_days ago) to avoid the
    # registry-lag undercount that would inflate months-of-supply. See config comments.
    sold = cfg["sold"]
    rate_end = today - timedelta(days=sold["rate_lag_days"])
    rate_start = rate_end - timedelta(days=sold["rate_window_days"])
    in_window = 0
    dated = 0
    for r in rows:
        d = _parse_date(r.get("sold_date"))
        if d is not None:
            dated += 1
            if rate_start < d <= rate_end:
                in_window += 1

    months_supply = None
    # only trust the rate if sold records actually carry dates
    if dated > 0 and in_window > 0:
        monthly_rate = in_window / (sold["rate_window_days"] / 30.0)
        months_supply = round(n_active / monthly_rate, 1)
    return {
        "sold_count": len(rows),
        "median_sold_sqm_price": _median(sqm),
        "median_sold_discount_pct": _median(discounts),
        "months_of_supply": months_supply,
    }


def compute_metrics(active: list[dict[str, Any]], sold: list[dict[str, Any]],
                    cfg: dict[str, Any], prev_ids: set[str] | None,
                    snapshot_date: date) -> list[dict[str, Any]]:
    segments = build_segments(cfg)

    cur_ids = {str(r.get("id")) for r in active if r.get("id") not in (None, "")}
    if prev_ids is None:
        new_listings = delisted = None
    else:
        new_listings = len(cur_ids - prev_ids)
        delisted = len(prev_ids - cur_ids)

    out: list[dict[str, Any]] = []
    for seg, pred in segments.items():
        act = [r for r in active if pred(r)]
        sld = [r for r in sold if pred(r)]
        if seg == "other" and not act and not sld:
            continue
        m = {k: None for k in METRIC_FIELDS}
        m.update(_active_metrics(act))
        m.update(_sold_metrics(sld, len(act), cfg, snapshot_date))
        m["snapshot_date"] = snapshot_date.isoformat()
        m["segment"] = seg
        if seg == "all":
            m["new_listings"] = new_listings
            m["delisted"] = delisted
        out.append({k: m.get(k) for k in METRIC_FIELDS})

    log.info("computed metrics for %d segments (active=%d, sold=%d, new=%s, delisted=%s)",
             len(out), len(active), len(sold), new_listings, delisted)
    return out


def previous_snapshot_ids(raw_dir: Path, before: date) -> set[str] | None:
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
    metrics_csv.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict[str, Any]] = []
    if metrics_csv.exists():
        with metrics_csv.open("r", newline="", encoding="utf-8") as fh:
            existing = [{k: r.get(k) for k in METRIC_FIELDS} for r in csv.DictReader(fh)
                        if r.get("snapshot_date") != snapshot_date.isoformat()]
    combined = existing + new_rows
    combined.sort(key=lambda r: (str(r["snapshot_date"]), str(r["segment"])))
    with metrics_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=METRIC_FIELDS)
        writer.writeheader()
        writer.writerows(combined)
    log.info("wrote %d metric rows to %s", len(combined), metrics_csv)
