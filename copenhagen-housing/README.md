# Copenhagen Housing Monitor

A self-running weekly snapshot of the Copenhagen housing market, built to give a
**live sense of market direction** — asking-price development, price cuts on live
listings, days-on-market, realised sold prices, and how fast inventory is clearing.

It runs as a GitHub Action every Monday: it scrapes Boliga (active listings + recent
sales), computes aggregate metrics, appends them to a time series, and regenerates a
dashboard — all committed back to this repo. No servers to maintain.

## Read this first — what this is and isn't

- **Asking prices are what sellers _want_, not what they get.** Asking prices, price
  cuts and days-on-market are *leading* indicators — they move weeks before registered
  sale prices. That's the point: an early-warning view.
- **Sold prices are the lagging ground truth.** They come from the land registry via
  Boliga and lag ~1–3 months (sales register after they close). They confirm the
  leading signals rather than lead them.
- **The source is an undocumented scrape.** Boliga has no public API contract; the
  endpoint or its parameters can change and break the scraper. When that happens the
  Action fails loudly (it won't write an empty snapshot). See *Troubleshooting*.
- **Scraping is legally grey.** Check Boliga's terms before running at scale. The
  scraper is deliberately gentle (one region, paged slowly, ~1 req/sec). Don't crank it.
- **A single snapshot shows no direction.** All the value is in the consistent weekly
  series that builds up over time. Give it a month before reading trends; cross-check
  quarterly against [Finans Danmark](https://finansdanmark.dk) and
  [Danmarks Statistik](https://www.statistikbanken.dk).

## The dashboard has two views

### 1. Market direction (weekly trend)
Pre-computed weekly aggregates, sliced by **property type** (apartment / house) and by
**district**. This is the "which way is the market moving" view.

| Metric | What it tells you |
|---|---|
| Asking price per m² | Headline price trend (overall, by type, by district) |
| Asking vs. realised sold price per m² | The gap between want and get |
| Days on market (median) | How long current inventory has sat — **rising = slowing** |
| % of listings with a price cut | Seller capitulation on live listings |
| Realised sale-to-ask discount | Median concession on homes that actually sold |
| **Months of supply** | Inventory ÷ monthly sales — see below |
| Active inventory | Supply |
| Weekly flow (new vs. delisted) | Demand pressure — delisted ≈ sold or withdrawn |

**Months of supply** = active listings ÷ homes sold per month (over a trailing 90-day
window). It answers: *at the current sales pace, how many months to clear everything
for sale?* Lower = tighter/faster (seller's market); higher = slower (buyer's market).
As a rough rule, ~6 months is "balanced", well below that favours sellers, well above
favours buyers.

### 2. Explore the current market
The *latest* snapshot's listings embedded in the page, with live client-side filters —
**district, sqm range, number of rooms, and street text-search**. It recomputes median
price/m², days-on-market etc. for whatever you filter to, and lists the matches. This
is a point-in-time view, not a trend (deliberately — a weekly line for a single street
would be noise).

## Districts

Tagged by postcode (approximate — postcode ≠ neighbourhood exactly):

| District | Postcodes |
|---|---|
| København K | 1050–1473 |
| Vesterbro | 1500–1799 |
| Frederiksberg C | 1800–1999 |
| Østerbro | 2100 |
| Nørrebro | 2200 |

Edit `districts` in `config.yaml` to add or change these.

## How it runs

```
run.py
 ├─ scraper.fetch_listings   active for-sale listings  -> data/raw/<date>.csv.gz
 ├─ scraper.fetch_sold       sales, trailing 90 days   -> data/sold_raw/<date>.csv.gz
 ├─ metrics.py               aggregate + diff vs. last  -> data/metrics_weekly.csv
 └─ build_dashboard.py       render trend + explore     -> dashboard.html
```

The GitHub Action (`.github/workflows/copenhagen-housing.yml`) does this weekly and
commits the results. To run it on demand: **Actions** tab → *Copenhagen housing
snapshot* → *Run workflow*.

### Viewing the dashboard

`dashboard.html` is a **self-contained file** (inline SVG + inline JS, no dependencies).
Two ways to view it:

1. **Download it** from the repo and open it in a browser — always works.
2. **GitHub Pages** for a live URL that updates weekly: repo **Settings → Pages** →
   Source **Deploy from a branch** → branch **main**, folder **`/ (root)`** → **Save**.
   Wait ~1–2 minutes for the first build (a "Your site is live at…" banner appears),
   then open:
   `https://<your-user>.github.io/<repo>/copenhagen-housing/dashboard.html`

   Notes: GitHub's *raw file preview* shows code, not the rendered page — use Pages or
   download. If the repo is **private**, Pages public sites require a paid GitHub plan.

### Running locally

```bash
pip install -r requirements.txt
python run.py            # real run (needs internet access to Boliga)
python run.py --dry-run  # synthetic data, to test the pipeline offline
```

## Configuration

Everything tunable lives in `config.yaml` — postal-code scope, the exact Boliga query
parameters (for-sale and sold), district definitions, property-type buckets, the sold
look-back window, and scraper politeness settings. You can change scope and even the
API parameter names without touching code.

## Troubleshooting

- **Action succeeds but nothing changes / "0 listings" in the log.** The Boliga
  for-sale parameters have drifted. Open the run log (it prints the request URL + count)
  and adjust `query_params` in `config.yaml`. Re-run via *Run workflow*.
- **Sold metrics are blank.** The sold fetch is best-effort — it won't fail the run.
  If it returns 0, adjust `sold_query_params` in `config.yaml` (or set `sold.enabled:
  false` to skip it). The log says which happened.
- **Pages URL 404s.** Pages isn't enabled yet, is still building (wait 1–2 min), the
  repo is private without a paid plan, or the path is wrong — it must include
  `/copenhagen-housing/dashboard.html`.
- **Want a different area or district set?** Edit `scope` / `districts` in `config.yaml`.

## Known limitations / next steps

- **Realised sale-to-ask discount** currently uses Boliga's own change field on each
  sold record. A more precise version would match each sale back to *our* listing
  history by street address (now that street is captured) — meaningful once several
  weeks of history accumulate.
- **Street-level trends** aren't provided on purpose: most streets have too few
  listings for a weekly series to mean anything. Street works as a filter/search in the
  Explore view instead.
