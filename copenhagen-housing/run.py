"""Orchestrate one weekly run: scrape -> compute metrics -> rebuild dashboard.

    python run.py               # normal run (hits Boliga)
    python run.py --dry-run     # generate synthetic listings instead of scraping
                                # (for testing the pipeline without network access)

Exit code is non-zero on failure so CI surfaces it.
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
from datetime import date
from pathlib import Path

import yaml

import build_dashboard
import metrics as metrics_mod
import scraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("boliga.run")

PROJECT_DIR = Path(__file__).resolve().parent


def _synthetic_listings(n: int = 400) -> list[dict]:
    """Fake but plausible Copenhagen listings, for --dry-run pipeline testing."""
    rng = random.Random(date.today().toordinal())  # varies day to day
    rows = []
    for i in range(n):
        ptype = rng.choice([2, 2, 2, 1, 3])  # apartments dominate
        base = 55000 if ptype == 2 else 42000
        sqm = base + rng.randint(-12000, 18000)
        size = rng.randint(45, 140)
        rows.append({
            "id": 900000 + i,
            "price": int(sqm * size),
            "sqm_price": sqm,
            "size_m2": size,
            "rooms": rng.randint(1, 5),
            "days_on_market": max(1, int(rng.gauss(55, 30))),
            "price_change_pct": rng.choice([0, 0, 0, -rng.randint(2, 12)]),
            "property_type": ptype,
            "zip_code": rng.choice([1050, 2100, 2200, 2300, 2400, 2500, 1800]),
            "city": "København",
            "build_year": rng.randint(1900, 2022),
            "is_foreclosure": False,
            "created_date": "", "latitude": "", "longitude": "",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="use synthetic listings instead of hitting Boliga")
    ap.add_argument("--config", default=str(PROJECT_DIR / "config.yaml"))
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    today = date.today()

    # 1. scrape
    if args.dry_run:
        log.info("DRY RUN — generating synthetic listings")
        listings = _synthetic_listings()
    else:
        listings = scraper.fetch_listings(cfg)
        if not listings:
            log.error("scraper returned 0 listings — check config.query_params "
                      "against the live Boliga API (see config.yaml notes). "
                      "Not writing an empty snapshot.")
            return 1

    scraper.save_snapshot(listings, cfg, PROJECT_DIR, today)

    # 2. metrics (diff against previous snapshot for flow)
    raw_dir = PROJECT_DIR / cfg["paths"]["raw_dir"]
    prev_ids = metrics_mod.previous_snapshot_ids(raw_dir, today)
    metric_rows = metrics_mod.compute_metrics(listings, cfg, prev_ids, today)
    metrics_csv = PROJECT_DIR / cfg["paths"]["metrics_csv"]
    metrics_mod.append_metrics(metric_rows, metrics_csv, today)

    # 3. dashboard
    all_metrics = build_dashboard.load_metrics(metrics_csv)
    build_dashboard.write_dashboard(
        all_metrics, cfg["scope"]["name"],
        PROJECT_DIR / cfg["paths"]["dashboard_html"], today)

    log.info("run complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
