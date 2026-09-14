"""Parse cached Boliga listing-detail JSON into structured attributes, and derive
'why is it cheap?' flags — the interpretive layer that makes the undervalued finder
honest. A big negative gap WITH no red flags is the genuinely interesting listing.

Fields Boliga's estate API exposes (confirmed live): energyClass, floor, exp (monthly
owner cost), buildYear, evaluationPrice (public assessment), lastSoldPrice/Date, views,
lotSize, basementSize, estateUrl (agent listing). Balcony is NOT here — it lives only in
the agent's free-text description, so it's out of scope for now.
"""

from __future__ import annotations

from typing import Any

import metrics as M

POOR_ENERGY = {"E", "F", "G"}


def _unwrap(raw: Any) -> dict:
    if isinstance(raw, dict):
        for k in ("data", "estate", "result", "property"):
            if isinstance(raw.get(k), dict):
                return raw[k]
        return raw
    return {}


def parse_detail(raw: Any) -> dict[str, Any]:
    d = _unwrap(raw)
    if not d:
        return {}
    ec = str(d.get("energyClass") or "").strip().upper()
    energy = ec if ec in {"A", "A1", "A2", "B", "C", "D", "E", "F", "G"} else None
    if energy and energy.startswith("A"):
        energy = "A"
    return {
        "energy": energy,
        "floor": M._to_int(d.get("floor")),
        "monthly": M._to_int(d.get("exp")),                 # monthly owner cost (ejerudgift)
        "build_year": M._to_int(d.get("buildYear")),
        "eval_price": (M._to_int(d.get("evaluationPrice")) or None),
        "last_sold_price": (M._to_int(d.get("lastSoldPrice")) or None),
        "last_sold_date": (d.get("lastSoldDate") or None),
        "lot_size": M._to_float(d.get("lotSize")),
        "basement": M._to_float(d.get("basementSize")),
        "views": M._to_int(d.get("views")),
        "estate_url": d.get("estateUrl") or None,
        "detailed": True,
    }


def _flags(attrs: dict, r: dict, cfg: dict) -> list[str]:
    buckets = cfg["property_type_buckets"]
    pt = M._to_int(r.get("property_type"))
    is_house = pt in buckets.get("house", [])
    flags = []
    if attrs.get("energy") in POOR_ENERGY:
        flags.append("energy " + attrs["energy"])
    # a "house" with no land is typically leasehold / plot-lease (e.g. Refshaleøen)
    if is_house and attrs.get("lot_size") == 0:
        flags.append("leasehold?")
    fl = attrs.get("floor")
    if fl is not None and fl <= 0:
        flags.append("ground floor")
    dom = M._to_float(r.get("days_on_market"))
    if dom is not None and dom >= 120:
        flags.append("stale " + str(int(dom)) + "d")
    return flags


def merge_attributes(active: list[dict], cache: dict[str, dict], cfg: dict) -> None:
    """Attach parsed attributes + flags to each active row (in place)."""
    empty = {"energy": None, "floor": None, "monthly": None, "eval_price": None,
             "last_sold_price": None, "estate_url": None, "detailed": False, "flags": []}
    covered = 0
    for r in active:
        rec = cache.get(str(r.get("id")))
        if rec and rec.get("raw"):
            attrs = parse_detail(rec["raw"])
            attrs["flags"] = _flags(attrs, r, cfg)
            r.update(attrs)
            covered += 1
        else:
            r.update(dict(empty))
    return covered
