"""Generate a self-contained dashboard.html from the metrics time series.

No external dependencies, no CDN, no build step: charts are inline SVG so the
committed file renders anywhere it's opened (including offline). A little inline
JS adds hover tooltips as progressive enhancement — the charts are fully readable
without it.

Colours follow the validated data-viz reference palette (categorical slots 1-3,
both light and dark). Segment -> colour mapping is fixed so a series keeps its
colour across every chart.
"""

from __future__ import annotations

import csv
import html
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

log = logging.getLogger("boliga.dashboard")

# Fixed segment -> colour slot (light, dark). Colour follows the entity.
SEGMENT_STYLE = {
    "all":       {"label": "All Copenhagen", "light": "#2a78d6", "dark": "#3987e5"},
    "apartment": {"label": "Apartments",     "light": "#eb6834", "dark": "#d95926"},
    "house":     {"label": "Houses",         "light": "#1baf7a", "dark": "#199e70"},
}
SEGMENT_ORDER = ["all", "apartment", "house"]


def load_metrics(metrics_csv: Path) -> list[dict[str, Any]]:
    if not metrics_csv.exists():
        return []
    with metrics_csv.open("r", newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _series(rows: list[dict], segment: str, field: str) -> list[tuple[str, float]]:
    pts = []
    for r in rows:
        if r.get("segment") == segment:
            y = _num(r.get(field))
            if y is not None:
                pts.append((r["snapshot_date"], y))
    return sorted(pts)


# --------------------------------------------------------------------------- #
# SVG primitives
# --------------------------------------------------------------------------- #

W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 56, 96, 20, 40


def _fmt(v: float, kind: str) -> str:
    if kind == "dkk":
        return f"{v:,.0f}".replace(",", ".")
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "days":
        return f"{v:.0f}"
    return f"{v:g}"


def _x(i: int, n: int) -> float:
    if n <= 1:
        return PAD_L + (W - PAD_L - PAD_R) / 2
    return PAD_L + i * (W - PAD_L - PAD_R) / (n - 1)


def _y(v: float, lo: float, hi: float) -> float:
    if hi == lo:
        return (PAD_T + H - PAD_B) / 2
    return H - PAD_B - (v - lo) * (H - PAD_T - PAD_B) / (hi - lo)


def line_chart(title: str, subtitle: str, segments: list[str],
               field: str, rows: list[dict], kind: str, chart_id: str) -> str:
    data = {seg: _series(rows, seg, field) for seg in segments}
    data = {seg: pts for seg, pts in data.items() if pts}
    if not data:
        return f'<figure class="card"><h3>{html.escape(title)}</h3><p class="empty">No data yet.</p></figure>'

    dates = sorted({d for pts in data.values() for d, _ in pts})
    n = len(dates)
    date_idx = {d: i for i, d in enumerate(dates)}
    all_y = [y for pts in data.values() for _, y in pts]
    lo, hi = min(all_y), max(all_y)
    span = hi - lo or (hi or 1)
    lo = max(0, lo - span * 0.12)
    hi = hi + span * 0.12

    parts = [f'<figure class="card"><figcaption><h3>{html.escape(title)}</h3>'
             f'<span class="sub">{html.escape(subtitle)}</span></figcaption>']
    parts.append(f'<svg viewBox="0 0 {W} {H}" role="img" '
                 f'aria-label="{html.escape(title)}" class="chart" data-chart="{chart_id}">')

    # gridlines + y ticks
    for t in range(5):
        gy = PAD_T + t * (H - PAD_T - PAD_B) / 4
        val = hi - t * (hi - lo) / 4
        parts.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{gy + 4:.1f}" class="tick tick-y">{_fmt(val, kind)}</text>')

    # x ticks (first, middle, last to avoid clutter)
    for i in (0, n // 2, n - 1) if n > 2 else range(n):
        parts.append(f'<text x="{_x(i, n):.1f}" y="{H - PAD_B + 18:.1f}" '
                     f'class="tick tick-x">{html.escape(dates[i][5:])}</text>')

    # series
    end_labels = []  # (seg, y_at_end) collected for de-collision
    for seg in segments:
        if seg not in data:
            continue
        pts = data[seg]
        coords = [(_x(date_idx[d], n), _y(y, lo, hi)) for d, y in pts]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        parts.append(f'<polyline points="{poly}" class="line seg-{seg}" fill="none"/>')
        for (x, y) in coords:
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="dot seg-{seg}"/>')
        end_labels.append((seg, coords[-1][1]))

    # push end-labels apart so converging series don't overprint each other
    end_labels.sort(key=lambda t: t[1])
    min_gap = 13.0
    for i in range(1, len(end_labels)):
        seg, y = end_labels[i]
        prev_y = end_labels[i - 1][1]
        if y - prev_y < min_gap:
            end_labels[i] = (seg, prev_y + min_gap)
    lx = _x(n - 1, n) + 8
    for seg, ly in end_labels:
        parts.append(f'<text x="{lx:.1f}" y="{ly + 4:.1f}" class="dlabel seg-{seg}">'
                     f'{html.escape(SEGMENT_STYLE[seg]["label"])}</text>')

    parts.append('</svg></figure>')
    return "".join(parts)


def bar_chart(title: str, subtitle: str, rows: list[dict], chart_id: str) -> str:
    new = _series(rows, "all", "new_listings")
    delisted = _series(rows, "all", "delisted")
    dates = sorted({d for d, _ in new + delisted})
    if not dates:
        return f'<figure class="card"><h3>{html.escape(title)}</h3><p class="empty">No flow data yet (needs 2+ snapshots).</p></figure>'

    nmap = dict(new)
    dmap = dict(delisted)
    n = len(dates)
    all_y = [v for v in list(nmap.values()) + list(dmap.values())]
    hi = max(all_y + [1]) * 1.15

    parts = [f'<figure class="card"><figcaption><h3>{html.escape(title)}</h3>'
             f'<span class="sub">{html.escape(subtitle)}</span></figcaption>']
    parts.append(f'<svg viewBox="0 0 {W} {H}" role="img" '
                 f'aria-label="{html.escape(title)}" class="chart" data-chart="{chart_id}">')
    for t in range(5):
        gy = PAD_T + t * (H - PAD_T - PAD_B) / 4
        val = hi - t * hi / 4
        parts.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W - PAD_R}" y2="{gy:.1f}" class="grid"/>')
        parts.append(f'<text x="{PAD_L - 8}" y="{gy + 4:.1f}" class="tick tick-y">{val:.0f}</text>')

    group_w = (W - PAD_L - PAD_R) / max(n, 1)
    bw = min(group_w * 0.32, 22)
    for i, d in enumerate(dates):
        cx = PAD_L + (i + 0.5) * group_w
        for j, (m, cls) in enumerate(((nmap, "flow-new"), (dmap, "flow-del"))):
            if d not in m:
                continue
            v = m[d]
            bh = (v / hi) * (H - PAD_T - PAD_B)
            bx = cx - bw + j * bw
            by = H - PAD_B - bh
            parts.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bw - 2:.1f}" '
                         f'height="{bh:.1f}" rx="3" class="{cls}"/>')
        if i in (0, n // 2, n - 1) or n <= 3:
            parts.append(f'<text x="{cx:.1f}" y="{H - PAD_B + 18:.1f}" '
                         f'class="tick tick-x">{html.escape(d[5:])}</text>')
    parts.append('</svg>')
    parts.append('<div class="legend">'
                 '<span><i class="sw flow-new"></i>New listings</span>'
                 '<span><i class="sw flow-del"></i>Delisted (sold or withdrawn)</span></div>')
    parts.append('</figure>')
    return "".join(parts)


# --------------------------------------------------------------------------- #
# KPI tiles
# --------------------------------------------------------------------------- #

def kpi_tiles(rows: list[dict]) -> str:
    all_rows = sorted([r for r in rows if r.get("segment") == "all"],
                      key=lambda r: r["snapshot_date"])
    if not all_rows:
        return '<p class="empty">No snapshots recorded yet.</p>'
    cur = all_rows[-1]
    prev = all_rows[-2] if len(all_rows) > 1 else None

    specs = [
        ("Median asking price", "median_sqm_price", "dkk", " DKK/m²"),
        ("Median days on market", "median_days_on_market", "days", " days"),
        ("Listings with a price cut", "pct_price_cut", "pct", ""),
        ("Active listings", "n_listings", "days", ""),
    ]
    tiles = []
    for label, field, kind, unit in specs:
        cv = _num(cur.get(field))
        if cv is None:
            continue
        delta_html = '<span class="delta flat">— first snapshot</span>'
        if prev is not None:
            pv = _num(prev.get(field))
            if pv not in (None, 0):
                pct = (cv - pv) / pv * 100
                arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
                cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
                delta_html = (f'<span class="delta {cls}">{arrow} {abs(pct):.1f}% '
                              f'<span class="wow">WoW</span></span>')
        tiles.append(
            f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
            f'<div class="kpi-value">{_fmt(cv, kind)}<span class="unit">{unit}</span></div>'
            f'{delta_html}</div>')
    return f'<div class="kpi-row">{"".join(tiles)}</div>'


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #

CSS = """
:root {
  color-scheme: light dark;
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --seg-all:#2a78d6; --seg-apartment:#eb6834; --seg-house:#1baf7a;
  --flow-new:#2a78d6; --flow-del:#eb6834;
}
@media (prefers-color-scheme: dark) {
  :root {
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --seg-all:#3987e5; --seg-apartment:#d95926; --seg-house:#199e70;
    --flow-new:#3987e5; --flow-del:#d95926;
  }
}
* { box-sizing:border-box; }
body { margin:0; background:var(--plane); color:var(--ink);
  font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; }
.wrap { max-width:1080px; margin:0 auto; padding:32px 20px 64px; }
header h1 { margin:0 0 4px; font-size:24px; letter-spacing:-.01em; }
header p { margin:0; color:var(--ink2); max-width:70ch; }
.asof { color:var(--muted); font-size:13px; margin-top:8px; }
.kpi-row { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr));
  gap:14px; margin:28px 0; }
.kpi { background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px; }
.kpi-label { color:var(--ink2); font-size:13px; }
.kpi-value { font-size:26px; font-weight:600; margin:6px 0 4px; letter-spacing:-.01em; }
.kpi-value .unit { font-size:14px; font-weight:400; color:var(--muted); margin-left:3px; }
.delta { font-size:13px; color:var(--ink2); }
.delta .wow { color:var(--muted); font-size:11px; }
.grid-charts { display:grid; grid-template-columns:repeat(auto-fit,minmax(340px,1fr));
  gap:18px; }
.card { background:var(--surface); border:1px solid var(--border); border-radius:12px;
  padding:16px 18px 12px; margin:0; }
.card figcaption h3 { margin:0; font-size:15px; }
.card .sub { color:var(--muted); font-size:12px; }
.chart { width:100%; height:auto; display:block; margin-top:8px; overflow:visible; }
.grid { stroke:var(--grid); stroke-width:1; }
.tick { fill:var(--muted); font-size:11px; font-variant-numeric:tabular-nums; }
.tick-y { text-anchor:end; }
.tick-x { text-anchor:middle; }
.line { stroke-width:2; }
.line.seg-all,.dot.seg-all,.dlabel.seg-all { stroke:var(--seg-all); }
.line.seg-apartment,.dot.seg-apartment,.dlabel.seg-apartment { stroke:var(--seg-apartment); }
.line.seg-house,.dot.seg-house,.dlabel.seg-house { stroke:var(--seg-house); }
.dot { stroke-width:1.5; fill:var(--surface); }
.dlabel { font-size:11px; font-weight:600; stroke:none; }
.dlabel.seg-all { fill:var(--seg-all); }
.dlabel.seg-apartment { fill:var(--seg-apartment); }
.dlabel.seg-house { fill:var(--seg-house); }
.flow-new { fill:var(--flow-new); }
.flow-del { fill:var(--flow-del); }
.legend { display:flex; gap:18px; font-size:12px; color:var(--ink2); margin-top:6px; }
.legend .sw { display:inline-block; width:11px; height:11px; border-radius:3px;
  margin-right:5px; vertical-align:-1px; }
.legend .sw.flow-new { background:var(--flow-new); }
.legend .sw.flow-del { background:var(--flow-del); }
.empty { color:var(--muted); font-size:13px; padding:24px 0; }
.note { margin-top:32px; padding:16px 18px; background:var(--surface);
  border:1px solid var(--border); border-radius:12px; color:var(--ink2); font-size:13px; }
.note strong { color:var(--ink); }
"""


def build_html(rows: list[dict], scope_name: str, generated: date) -> str:
    charts = [
        line_chart("Asking price per m²", "Median, DKK — the headline price trend",
                   SEGMENT_ORDER, "median_sqm_price", rows, "dkk", "price"),
        line_chart("Days on market", "Median age of active listings — rising = slowing",
                   SEGMENT_ORDER, "median_days_on_market", rows, "days", "dom"),
        line_chart("Listings with a price cut", "% of active listings below their original ask",
                   SEGMENT_ORDER, "pct_price_cut", rows, "pct", "cut"),
        line_chart("Active inventory", "Number of listings for sale",
                   ["all"], "n_listings", rows, "days", "inv"),
        bar_chart("Weekly flow", "New listings vs. delisted (sold or withdrawn)",
                  rows, "flow"),
    ]
    snapshots = sorted({r["snapshot_date"] for r in rows})
    span = f"{snapshots[0]} → {snapshots[-1]}" if snapshots else "no data yet"

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Copenhagen Housing Monitor</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<header>
  <h1>Copenhagen Housing Monitor</h1>
  <p>Live-listing indicators for <strong>{html.escape(scope_name)}</strong>, snapshotted weekly
  from Boliga. Asking-price cuts and days-on-market are <em>leading</em> indicators —
  they move weeks before realised sale prices.</p>
  <div class="asof">Generated {generated.isoformat()} · {len(snapshots)} snapshot(s) · {span}</div>
</header>
{kpi_tiles(rows)}
<div class="grid-charts">
{''.join(charts)}
</div>
<div class="note">
  <strong>Read this before trusting a trend.</strong> These are <em>asking</em> prices on
  live listings, not realised sale prices, and the source (Boliga) is an undocumented
  scrape that can drift. A single point means nothing — direction only becomes reliable
  after several weeks of consistent snapshots. Cross-check quarterly against official
  Finans Danmark / Danmarks Statistik figures before making any decision that matters.
</div>
</div></body></html>
"""


def write_dashboard(rows: list[dict], scope_name: str, out_path: Path,
                    generated: date | None = None) -> Path:
    generated = generated or date.today()
    out_path.write_text(build_html(rows, scope_name, generated), encoding="utf-8")
    log.info("wrote dashboard: %s", out_path)
    return out_path
