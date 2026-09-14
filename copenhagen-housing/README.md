# Copenhagen Housing Monitor

A self-running weekly snapshot of the Copenhagen live-listing market, built to give
a **live sense of market direction** — asking-price development, the share of
listings cutting their price, days-on-market, and inventory flow.

It runs as a GitHub Action every Monday: it scrapes current for-sale listings from
Boliga, computes aggregate metrics, appends them to a time series, and regenerates
a dashboard — all committed back to this repo. No servers to maintain.

## Read this first — what this is and isn't

- **These are _asking_ prices on live listings, not realised sale prices.** Asking
  prices and days-on-market are *leading* indicators: they move weeks before
  registered transaction prices. That's the point — it's an early-warning view, not
  a record of what actually sold.
- **The data source is an undocumented scrape.** Boliga has no public API contract.
  The endpoint or its parameters can change without notice, which would break the
  scraper. When that happens the Action fails loudly (it won't write an empty
  snapshot) — see *Troubleshooting*.
- **Scraping is legally grey.** Check Boliga's terms before running this at scale.
  The scraper is deliberately gentle (one region, paged slowly, ~1 req/sec). Don't
  crank it up.
- **A single snapshot tells you nothing about direction.** All the value is in the
  consistent weekly series that builds up over time. Give it a month before reading
  trends; cross-check quarterly against official [Finans Danmark](https://finansdanmark.dk)
  and [Danmarks Statistik](https://www.statistikbanken.dk) figures so scraper drift
  doesn't fool you.

## What it tracks

| Metric | What it tells you |
|---|---|
| Median asking price per m² | Headline price trend, split by apartments / houses |
| Days on market (median) | How long current inventory has sat — **rising = market slowing** |
| % of listings with a price cut | Seller capitulation — a key softening signal |
| Median price-cut size | How deep the cuts are |
| Active inventory | Supply |
| Weekly flow (new vs. delisted) | Demand pressure — delisted ≈ sold or withdrawn |

## How it runs

```
run.py
 ├─ scraper.py         fetch live listings from Boliga  -> data/raw/<date>.csv.gz
 ├─ metrics.py         aggregate + diff vs. last week   -> data/metrics_weekly.csv
 └─ build_dashboard.py render the time series           -> dashboard.html
```

The GitHub Action (`.github/workflows/copenhagen-housing.yml`) does this weekly and
commits the results. **To start collecting data now**, trigger it manually:
`Actions` tab → *Copenhagen housing snapshot* → *Run workflow*.

### Viewing the dashboard

`dashboard.html` is a **self-contained file** (inline SVG, no dependencies). Open it
in a browser locally, or enable **GitHub Pages** on this repo to get a live URL.
Note: GitHub's raw-file preview won't render it — download it or use Pages.

### Running locally

```bash
pip install -r requirements.txt
python run.py            # real run (needs internet access to Boliga)
python run.py --dry-run  # synthetic data, to test the pipeline offline
```

## Configuration

Everything tunable lives in `config.yaml` — postal-code scope, the exact Boliga
query parameters, property-type buckets, and scraper politeness settings. **You can
change scope and even the API parameter names without touching any code.**

## Troubleshooting

- **Action succeeds but nothing changes / "0 listings" in the log.** The Boliga API
  parameters have most likely drifted. Open the run log — it prints the request URL
  and result count — then adjust `query_params` in `config.yaml` (the file lists the
  known-working alternatives). Re-run via *Run workflow*.
- **Want a different area?** Edit `scope` / `query_params` in `config.yaml`.
- **Want realised sale prices too?** Boliga has a separate `sold` endpoint; this
  monitor deliberately tracks live listings only (the leading-indicator view). Adding
  a sold-price series is a natural next step if you want to confirm the leading
  signals against what actually closed.
