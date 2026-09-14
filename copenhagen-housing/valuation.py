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


def _clean_sold(sold: list[dict], cfg: dict) -> list[dict]:
    buckets = cfg["property_type_buckets"]
    districts = cfg["districts"]
    out = []
    for r in sold:
        sqm = M._to_float(r.get("sqm_price"))
        size = M._to_float(r.get("size_m2"))
        if not sqm or sqm <= 0:
            continue
        out.append({
            "sqm": sqm, "size": size, "rooms": M._to_int(r.get("rooms")),
            "bucket": _bucket(r.get("property_type"), buckets),
            "district": M.district_of(r.get("zip_code"), districts),
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

    for r in active:
        listing = {
            "size": M._to_float(r.get("size_m2")), "rooms": M._to_int(r.get("rooms")),
            "bucket": _bucket(r.get("property_type"), buckets),
            "district": M.district_of(r.get("zip_code"), districts),
        }
        est = _estimate_one(listing, pool, cfg)
        ask_sqm = M._to_float(r.get("sqm_price"))
        gap = None
        est_value = None
        if est["est_sqm"] and listing["size"]:
            est_value = int(est["est_sqm"] * listing["size"])
        if est["est_sqm"] and ask_sqm and ask_sqm > 0:
            gap = round((ask_sqm - est["est_sqm"]) / est["est_sqm"] * 100, 1)
        r.update({"est_sqm": est["est_sqm"], "est_value": est_value, "gap_pct": gap,
                  "n_comps": est["n_comps"], "comp_method": est["method"]})

    covered = sum(1 for r in active if r.get("est_sqm"))
    log.info("valuation: estimated %d/%d active listings from %d sold comps",
             covered, len(active), len(pool))
