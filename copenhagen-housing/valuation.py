"""Estimate each active listing's expected SALE value from comparable sold records.

For a given active listing we find comparable *sold* homes (realised prices — the
honest ground truth, not other asking prices) and take their median price/m² as the
expected sale value. Comps are found by relaxing filters until at least `min_comps`
are found, so we always fall back to *something*, but we record how many comps and how
loose the match was so the dashboard can be honest about confidence.

We then express asking vs. that estimate. Note asking is normally ABOVE realised sale
comps (sellers ask high), so a small positive gap is the norm; a large positive gap =
expensive, a negative gap = asking below what comparable homes actually sold for.

This is a comps model on size + rooms + district only. It cannot see floor, condition,
light, layout, renovation or energy class — the things that decide whether a specific
flat is a real deal. Treat the output as a sanity range and an outlier flag, never a
precise valuation.
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

import metrics as M

log = logging.getLogger("boliga.valuation")


def _bucket(pt: Any, buckets: dict[str, list[int]]) -> str:
    code = M._to_int(pt)
    for name, codes in buckets.items():
        if code in codes:
            return name
    return "other"


def _sane_sqm(sqm: float | None, cfg: dict) -> bool:
    v = cfg["valuation"]
    return sqm is not None and v["sane_sqm_min"] <= sqm <= v["sane_sqm_max"]


def _consistent(price: float | None, size: float | None, sqm: float | None, cfg: dict) -> bool:
    """Reported price/m² should roughly equal price ÷ size — else the row is unreliable
    (andelsbolig deposit price, mixed unit, or a data error)."""
    if not (price and size and sqm) or size <= 0:
        return sqm is not None  # can't check; fall back to the sane-band test only
    implied = price / size
    return abs(implied - sqm) <= cfg["valuation"]["consistency_tol"] * sqm


def _clean_sold(sold: list[dict], cfg: dict) -> list[dict]:
    """Comps pool: apartments/houses with a plausible, internally-consistent price/m².
    This strips co-op and error rows that would otherwise poison the comp medians."""
    buckets = cfg["property_type_buckets"]
    districts = cfg["districts"]
    out = []
    for r in sold:
        sqm = M._to_float(r.get("sqm_price"))
        size = M._to_float(r.get("size_m2"))
        price = M._to_float(r.get("price"))
        bucket = _bucket(r.get("property_type"), buckets)
        if bucket not in ("apartment", "house"):
            continue
        if not _sane_sqm(sqm, cfg) or not _consistent(price, size, sqm, cfg):
            continue
        out.append({
            "sqm": sqm, "size": size, "rooms": M._to_int(r.get("rooms")),
            "bucket": bucket, "district": M.district_of(r.get("zip_code"), districts),
        })
    return out


def _estimate_one(listing: dict, pool: list[dict], cfg: dict) -> dict:
    min_comps = cfg["valuation"]["min_comps"]
    tol = cfg["valuation"]["size_tolerance"]
    size = listing.get("size")
    rooms = listing.get("rooms")
    bucket = listing.get("bucket")
    dist = listing.get("district")

    def size_ok(c):
        return size and c["size"] and abs(c["size"] - size) <= tol * size

    # Progressive relaxation; first tier with enough comps wins.
    tiers = [
        ("district+rooms+size", lambda c: c["bucket"] == bucket and c["district"] == dist
                                and c["rooms"] == rooms and size_ok(c)),
        ("district+size",       lambda c: c["bucket"] == bucket and c["district"] == dist and size_ok(c)),
        ("district",            lambda c: c["bucket"] == bucket and c["district"] == dist),
        ("bucket+size",         lambda c: c["bucket"] == bucket and size_ok(c)),
        ("bucket",              lambda c: c["bucket"] == bucket),
    ]
    for method, pred in tiers:
        comps = [c["sqm"] for c in pool if pred(c)]
        if len(comps) >= min_comps:
            return {"est_sqm": round(statistics.median(comps)), "n_comps": len(comps), "method": method}
    # last resort: whatever we have for the bucket, even if < min_comps
    comps = [c["sqm"] for c in pool if c["bucket"] == bucket]
    if comps:
        return {"est_sqm": round(statistics.median(comps)), "n_comps": len(comps), "method": "bucket-sparse"}
    return {"est_sqm": None, "n_comps": 0, "method": "none"}


def estimate(active: list[dict], sold: list[dict], cfg: dict) -> None:
    """Attach est_sqm, est_value, gap_pct, n_comps, comp_method to each active row (in place)."""
    buckets = cfg["property_type_buckets"]
    districts = cfg["districts"]
    pool = _clean_sold(sold, cfg)
    if not pool:
        log.warning("no sold comps available — skipping valuation")
        for r in active:
            r.update({"est_sqm": None, "est_value": None, "gap_pct": None,
                      "n_comps": 0, "comp_method": "none"})
        return

    def is_true(v):
        return str(v).strip().lower() in ("true", "1", "yes")

    for r in active:
        listing = {
            "size": M._to_float(r.get("size_m2")), "rooms": M._to_int(r.get("rooms")),
            "bucket": _bucket(r.get("property_type"), buckets),
            "district": M.district_of(r.get("zip_code"), districts),
        }
        est = _estimate_one(listing, pool, cfg)
        ask_sqm = M._to_float(r.get("sqm_price"))
        price = M._to_float(r.get("price"))
        # Show an estimate for any apartment/house with a plausible, consistent price/m².
        base_ok = (listing["bucket"] in ("apartment", "house")
                   and not is_true(r.get("is_foreclosure"))
                   and _sane_sqm(ask_sqm, cfg)
                   and _consistent(price, listing["size"], ask_sqm, cfg))
        # Only rank a GAP when the comp match was size-comparable — otherwise a large or
        # unusual unit gets compared to normal flats and reads as a fake bargain.
        size_matched = est["method"] in ("district+rooms+size", "district+size", "bucket+size")
        est_sqm = est["est_sqm"] if base_ok else None
        est_value = int(est_sqm * listing["size"]) if (est_sqm and listing["size"]) else None
        gap = None
        if base_ok and size_matched and est_sqm and ask_sqm and ask_sqm > 0:
            gap = round((ask_sqm - est_sqm) / est_sqm * 100, 1)
        r.update({"est_sqm": est_sqm, "est_value": est_value, "gap_pct": gap,
                  "n_comps": est["n_comps"], "comp_method": est["method"]})

    covered = sum(1 for r in active if r.get("gap_pct") is not None)
    log.info("valuation: %d/%d active listings got a trustworthy gap (pool=%d clean comps)",
             covered, len(active), len(pool))
