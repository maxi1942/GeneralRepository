"""Orchestrate one weekly run: scrape active + sold -> metrics -> dashboard.

    python run.py               # normal run (hits Boliga)
    python run.py --dry-run     # synthetic data, for testing the pipeline offline

Exit code is non-zero on failure so CI surfaces it. The sold fetch is best-effort:
if it fails or returns nothing, the run still succeeds (sold metrics just stay blank
that week) — the for-sale feed is the core and must not be blocked by the sold feed.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import yaml

import attributes
import build_dashboard
import detail_scraper
import metrics as metrics_mod
import scraper
import valuation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("boliga.run")

PROJECT_DIR = Path(__file__).resolve().parent
STREETS = ["Istedgade", "Nørrebrogade", "Østerbrogade", "Gammel Kongevej",
           "Amagerbrogade", "Vesterbrogade", "Falkoner Allé", "Strandvejen"]
ZIPS = [1051, 1200, 1300, 1620, 1700, 1850, 1900, 2100, 2200]


def _synthetic(n: int, sold: bool, rng: random.Random) -> list[dict]:
    rows = []
    for i in range(n):
        ptype = rng.choice([3, 3, 3, 1, 2, 9])
        base = 55000 if ptype == 3 else 42000
        sqm = base + rng.randint(-12000, 20000)
        size = rng.randint(38, 160)
        zc = rng.choice(ZIPS)
        row = {
            "price": int(sqm * size), "sqm_price": sqm, "size_m2": size,
            "rooms": rng.randint(1, 6), "property_type": ptype, "zip_code": zc,
            "city": "København", "street": rng.choice(STREETS),
        }
        if sold:
            row.update({"change_pct": rng.choice([0, -rng.randint(1, 10)]),
                        "sold_date": (date.today() - timedelta(days=rng.randint(1, 90))).isoformat(),
                        "sale_type": "Alm. Salg"})
        else:
            row.update({"id": 900000 + i,
                        "days_on_market": max(1, int(rng.gauss(55, 30))),
                        "price_change_pct": rng.choice([0, 0, 0, -rng.randint(2, 12)]),
                        "build_year": rng.randint(1900, 2022), "is_foreclosure": False,
                        "created_date": "", "latitude": "", "longitude": ""})
        rows.append(row)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--config", default=str(PROJECT_DIR / "config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    today = date.today()

    # 1. active listings
    if args.dry_run:
        log.info("DRY RUN — synthetic data")
        active = _synthetic(400, sold=False, rng=random.Random(today.toordinal()))
        sold = _synthetic(120, sold=True, rng=random.Random(today.toordinal() + 1))
    else:
        active = scraper.fetch_listings(cfg)
        if not active:
            log.error("for-sale scraper returned 0 listings — check config.query_params "
                      "against the live API (see config.yaml). Not writing an empty snapshot.")
            return 1
        sold = []
        if cfg["sold"].get("enabled", True):
            try:
                sold = scraper.fetch_sold(cfg, today)
                if not sold:
                    log.warning("sold fetch returned 0 records — sold metrics will be blank. "
                                "Check config.sold_query_params against the live sold API.")
            except Exception as err:  # noqa: BLE001 — sold is best-effort
                log.warning("sold fetch failed (%s) — continuing without sold metrics", err)

    scraper.save_snapshot(active, PROJECT_DIR / cfg["paths"]["raw_dir"],
                          list(scraper.FIELD_CANDIDATES.keys()), today)
    if sold:
        scraper.save_snapshot(sold, PROJECT_DIR / cfg["paths"]["sold_raw_dir"],
                              list(scraper.SOLD_FIELD_CANDIDATES.keys()), today)

    # 2. metrics
    raw_dir = PROJECT_DIR / cfg["paths"]["raw_dir"]
    prev_ids = metrics_mod.previous_snapshot_ids(raw_dir, today)
    metric_rows = metrics_mod.compute_metrics(active, sold, cfg, prev_ids, today)
    metrics_csv = PROJECT_DIR / cfg["paths"]["metrics_csv"]
    metrics_mod.append_metrics(metric_rows, metrics_csv, today)

    # 3. valuation — expected sale value per active listing from sold comps (in place)
    valuation.estimate(active, sold, cfg)

    # 3b. detail enrichment — fetch per-listing attributes (capped, cached, candidates
    #     first). Best-effort: failures never break the run.
    cache = {}
    if not args.dry_run and cfg.get("detail", {}).get("enabled"):
        try:
            priority = [r["id"] for r in sorted(
                active, key=lambda r: r["gap_pct"] if r.get("gap_pct") is not None else 1e9)
                if r.get("id") not in (None, "")]
            cache = detail_scraper.enrich(active, cfg, PROJECT_DIR, priority)
        except Exception as err:  # noqa: BLE001
            log.warning("detail enrichment failed (%s) — continuing", err)
    else:
        cache = detail_scraper.load_cache(PROJECT_DIR / cfg["detail"]["cache"])
    n = attributes.merge_attributes(active, cache, cfg)
    log.info("attributes merged for %d/%d listings", n, len(active))

    # 4. dashboard (trend view from the time series + explore view from latest snapshot)
    all_metrics = build_dashboard.load_metrics(metrics_csv)
    build_dashboard.write_dashboard(all_metrics, active, cfg,
                                    PROJECT_DIR / cfg["paths"]["dashboard_html"], today)

    log.info("run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
