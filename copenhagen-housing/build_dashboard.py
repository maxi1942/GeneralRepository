"""Generate a self-contained dashboard.html: a Trend view + an Explore view.

Trend view  — pre-computed weekly aggregates as inline-SVG line charts (price/m2 by
              property type and by district, asking vs. realised sold price, days on
              market, price cuts, inventory, weekly flow, months of supply).
Explore view — the CURRENT snapshot's listings embedded in the page, with client-side
              filters (district, sqm range, rooms, street search) that recompute
              summary stats live. A snapshot, not a trend.

No external dependencies, no CDN. Charts render as static SVG; the Explore filters and
chart hover use inline vanilla JS as progressive enhancement. Colours follow the
validated data-viz reference palette (slots 1-6, both light and dark).
"""

from __future__ import annotations

import csv
import html
import json
import logging
from datetime import date
from pathlib import Path
from typing import Any

import metrics as M

log = logging.getLogger("boliga.dashboard")

# Palette slots (light, dark) — data-viz reference categorical slots 1-6.
SLOTS = {
    "c1": ("#2a78d6", "#3987e5"), "c2": ("#eb6834", "#d95926"),
    "c3": ("#1baf7a", "#199e70"), "c4": ("#eda100", "#c98500"),
    "c5": ("#e87ba4", "#d55181"), "c6": ("#008300", "#008300"),
}
PTYPE = {"all": ("All", "c1"), "apartment": ("Apartments", "c2"), "house": ("Houses", "c3")}
DISTRICT_SLOTS = ["c1", "c2", "c3", "c4", "c5"]


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


def _pts(rows: list[dict], segment: str, field: str) -> list[tuple[str, float]]:
    out = []
    for r in rows:
        if r.get("segment") == segment and (y := _num(r.get(field))) is not None:
            out.append((r["snapshot_date"], y))
    return sorted(out)


def _series(rows, segment, field, label, slot) -> dict | None:
    pts = _pts(rows, segment, field)
    return {"label": label, "slot": slot, "pts": pts} if pts else None


# --------------------------------------------------------------------------- #
# SVG line chart (generic, multi-series)
# --------------------------------------------------------------------------- #

W, H = 720, 300
PAD_L, PAD_R, PAD_T, PAD_B = 58, 104, 20, 40


def _fmt(v: float | None, kind: str) -> str:
    if v is None:
        return "–"
    if kind == "dkk":
        return f"{v:,.0f}".replace(",", ".")
    if kind == "pct":
        return f"{v:.1f}%"
    if kind == "months":
        return f"{v:.1f}"
    return f"{v:.0f}"


def line_chart(title, subtitle, series, kind, chart_id) -> str:
    series = [s for s in series if s and s["pts"]]
    if not series:
        return (f'<figure class="card"><figcaption><h3>{html.escape(title)}</h3></figcaption>'
                f'<p class="empty">No data yet.</p></figure>')

    dates = sorted({d for s in series for d, _ in s["pts"]})
    n = len(dates)
    idx = {d: i for i, d in enumerate(dates)}
    ys = [y for s in series for _, y in s["pts"]]
    lo, hi = min(ys), max(ys)
    span = (hi - lo) or (hi or 1)
    lo = max(0, lo - span * 0.12)
    hi = hi + span * 0.12

    def X(i):
        return PAD_L if n <= 1 else PAD_L + i * (W - PAD_L - PAD_R) / (n - 1)

    def Y(v):
        return (PAD_T + H - PAD_B) / 2 if hi == lo else H - PAD_B - (v - lo) * (H - PAD_T - PAD_B) / (hi - lo)

    p = [f'<figure class="card"><figcaption><h3>{html.escape(title)}</h3>'
         f'<span class="sub">{html.escape(subtitle)}</span></figcaption>'
         f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}" class="chart">']
    for t in range(5):
        gy = PAD_T + t * (H - PAD_T - PAD_B) / 4
        val = hi - t * (hi - lo) / 4
        p.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W-PAD_R}" y2="{gy:.1f}" class="grid"/>')
        p.append(f'<text x="{PAD_L-8}" y="{gy+4:.1f}" class="tick ty">{_fmt(val, kind)}</text>')
    for i in ((0, n // 2, n - 1) if n > 2 else range(n)):
        p.append(f'<text x="{X(i):.1f}" y="{H-PAD_B+18:.1f}" class="tick tx">{html.escape(dates[i][5:])}</text>')

    end = []
    for s in series:
        coords = [(X(idx[d]), Y(y)) for d, y in s["pts"]]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
        p.append(f'<polyline points="{poly}" class="line s-{s["slot"]}" fill="none"/>')
        for x, y in coords:
            p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" class="dot s-{s["slot"]}"/>')
        end.append([s["slot"], s["label"], coords[-1][1]])

    end.sort(key=lambda e: e[2])
    for i in range(1, len(end)):
        if end[i][2] - end[i-1][2] < 13:
            end[i][2] = end[i-1][2] + 13
    lx = X(n - 1) + 8
    for slot, label, y in end:
        p.append(f'<text x="{lx:.1f}" y="{y+4:.1f}" class="dlabel s-{slot}">{html.escape(label)}</text>')
    p.append('</svg></figure>')
    return "".join(p)


def bar_chart(title, subtitle, rows) -> str:
    new, delisted = _pts(rows, "all", "new_listings"), _pts(rows, "all", "delisted")
    dates = sorted({d for d, _ in new + delisted})
    if not dates:
        return (f'<figure class="card"><figcaption><h3>{html.escape(title)}</h3></figcaption>'
                f'<p class="empty">No flow data yet (needs 2+ snapshots).</p></figure>')
    nmap, dmap = dict(new), dict(delisted)
    n = len(dates)
    hi = max(list(nmap.values()) + list(dmap.values()) + [1]) * 1.15
    p = [f'<figure class="card"><figcaption><h3>{html.escape(title)}</h3>'
         f'<span class="sub">{html.escape(subtitle)}</span></figcaption>'
         f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}" class="chart">']
    for t in range(5):
        gy = PAD_T + t * (H - PAD_T - PAD_B) / 4
        p.append(f'<line x1="{PAD_L}" y1="{gy:.1f}" x2="{W-PAD_R}" y2="{gy:.1f}" class="grid"/>')
        p.append(f'<text x="{PAD_L-8}" y="{gy+4:.1f}" class="tick ty">{hi - t*hi/4:.0f}</text>')
    gw = (W - PAD_L - PAD_R) / max(n, 1)
    bw = min(gw * 0.32, 22)
    for i, d in enumerate(dates):
        cx = PAD_L + (i + 0.5) * gw
        for j, (m, cls) in enumerate(((nmap, "s-c1"), (dmap, "s-c2"))):
            if d in m:
                bh = (m[d] / hi) * (H - PAD_T - PAD_B)
                p.append(f'<rect x="{cx-bw+j*bw:.1f}" y="{H-PAD_B-bh:.1f}" width="{bw-2:.1f}" '
                         f'height="{bh:.1f}" rx="3" class="fill {cls}"/>')
        if i in (0, n // 2, n - 1) or n <= 3:
            p.append(f'<text x="{cx:.1f}" y="{H-PAD_B+18:.1f}" class="tick tx">{html.escape(d[5:])}</text>')
    p.append('</svg><div class="legend"><span><i class="sw s-c1"></i>New listings</span>'
             '<span><i class="sw s-c2"></i>Delisted (sold or withdrawn)</span></div></figure>')
    return "".join(p)


# --------------------------------------------------------------------------- #
# KPI tiles
# --------------------------------------------------------------------------- #

def kpi_tiles(rows) -> str:
    allrows = sorted([r for r in rows if r.get("segment") == "all"], key=lambda r: r["snapshot_date"])
    if not allrows:
        return '<p class="empty">No snapshots recorded yet.</p>'
    cur, prev = allrows[-1], (allrows[-2] if len(allrows) > 1 else None)
    specs = [
        ("Median asking price", "median_sqm_price", "dkk", " DKK/m²"),
        ("Median sold price", "median_sold_sqm_price", "dkk", " DKK/m²"),
        ("Months of supply", "months_of_supply", "months", " mo"),
        ("Median days on market", "median_days_on_market", "days", " days"),
        ("Listings with a price cut", "pct_price_cut", "pct", ""),
        ("Active listings", "n_listings", "days", ""),
    ]
    tiles = []
    for label, field, kind, unit in specs:
        cv = _num(cur.get(field))
        if cv is None:
            continue
        delta = '<span class="delta flat">— first snapshot</span>'
        if prev and (pv := _num(prev.get(field))) not in (None, 0):
            pct = (cv - pv) / pv * 100
            arrow = "▲" if pct > 0 else ("▼" if pct < 0 else "▬")
            cls = "up" if pct > 0 else ("down" if pct < 0 else "flat")
            delta = f'<span class="delta {cls}">{arrow} {abs(pct):.1f}% <span class="wow">WoW</span></span>'
        tiles.append(f'<div class="kpi"><div class="kpi-label">{html.escape(label)}</div>'
                     f'<div class="kpi-value">{_fmt(cv, kind)}<span class="unit">{unit}</span></div>{delta}</div>')
    return f'<div class="kpi-row">{"".join(tiles)}</div>'


# --------------------------------------------------------------------------- #
# Explore view (client-side filtering over the current snapshot)
# --------------------------------------------------------------------------- #

def explore_payload(active: list[dict], cfg: dict) -> dict:
    districts = cfg["districts"]
    labels = {k: v["label"] for k, v in districts.items()}
    items = []
    for r in active:
        sp, size, price = _num(r.get("sqm_price")), _num(r.get("size_m2")), _num(r.get("price"))
        if not sp or sp <= 0:
            continue
        dk = M.district_of(r.get("zip_code"), districts)
        est = M._to_float(r.get("est_sqm"))
        items.append({
            "d": dk or "", "z": M._to_int(r.get("zip_code")),
            "s": int(size) if size else None, "r": M._to_int(r.get("rooms")),
            "p": int(price) if price else None, "sp": int(sp),
            "dom": M._to_int(r.get("days_on_market")),
            "cut": _num(r.get("price_change_pct")) or 0,
            "st": (r.get("street") or "").strip(),
            "e": int(est) if est else None,          # comps-based expected sold DKK/m²
            "g": _num(r.get("gap_pct")),             # asking vs comps, %
            "nc": M._to_int(r.get("n_comps")) or 0,  # number of comps behind the estimate
        })
    return {"items": items, "labels": labels}


EXPLORE_HTML = """
<section class="explore card">
  <figcaption><h3>Explore current listings</h3>
  <span class="sub">Live filter over the latest snapshot — a point-in-time view, not a trend.</span></figcaption>
  <div class="filters">
    <label>District<select id="f-dist"><option value="">All</option></select></label>
    <label>Rooms<select id="f-rooms">
      <option value="">Any</option><option>1</option><option>2</option><option>3</option>
      <option>4</option><option value="5+">5+</option></select></label>
    <label>Min m²<input id="f-smin" type="number" min="0" step="5" placeholder="any"></label>
    <label>Max m²<input id="f-smax" type="number" min="0" step="5" placeholder="any"></label>
    <label class="grow">Street contains<input id="f-street" type="text" placeholder="e.g. Istedgade"></label>
    <label>Sort by<select id="f-sort">
      <option value="value">Best value (asking vs comps)</option>
      <option value="sp-desc">DKK/m² (high → low)</option>
      <option value="sp-asc">DKK/m² (low → high)</option>
      <option value="dom-desc">Longest on market</option>
    </select></label>
  </div>
  <div id="ex-stats" class="kpi-row explore-stats"></div>
  <div class="table-wrap"><table id="ex-table"><thead><tr>
    <th>District</th><th>Street</th><th class="num">m²</th><th class="num">Rooms</th>
    <th class="num">Price</th><th class="num">DKK/m²</th><th class="num">Est/m²</th>
    <th class="num">vs comps</th><th class="num">Days</th><th class="num">Cut</th>
  </tr></thead><tbody></tbody></table></div>
  <div id="ex-more" class="more"></div>
  <p class="methodology">“Est/m²” is the median price per m² of comparable <em>sold</em> homes
  (same district, property type, ±25% size and, where possible, same rooms). “vs comps” is how
  far the asking price sits above (+) or below (−) that — asking is normally a few % above realised
  sales, so treat small positives as normal and look for clear negatives. This uses size, rooms and
  district only; it can't see floor, condition, light or renovation, so it's a sanity range and an
  outlier flag, <strong>not</strong> a valuation. Low comp counts (shown as “n=”) mean low confidence.</p>
</section>
"""

EXPLORE_JS = """
<script>
(function(){
  var DATA = window.__EXPLORE__ || {items:[],labels:{}};
  var items = DATA.items, labels = DATA.labels;
  var $ = function(id){return document.getElementById(id);};
  var dsel = $('f-dist');
  Object.keys(labels).forEach(function(k){
    var o=document.createElement('option'); o.value=k; o.textContent=labels[k]; dsel.appendChild(o);
  });
  function median(a){ if(!a.length) return null; a=a.slice().sort(function(x,y){return x-y;});
    var m=Math.floor(a.length/2); return a.length%2? a[m] : (a[m-1]+a[m])/2; }
  function fmtdkk(v){ return v==null?'–':Math.round(v).toLocaleString('da-DK'); }
  function tile(label,val,unit){ return '<div class="kpi"><div class="kpi-label">'+label+
    '</div><div class="kpi-value">'+val+'<span class="unit">'+(unit||'')+'</span></div></div>'; }
  function apply(){
    var d=$('f-dist').value, rm=$('f-rooms').value,
        smin=parseFloat($('f-smin').value), smax=parseFloat($('f-smax').value),
        st=$('f-street').value.trim().toLowerCase();
    var f=items.filter(function(x){
      if(d && x.d!==d) return false;
      if(rm==='5+'){ if(!(x.r>=5)) return false; } else if(rm){ if(x.r!=+rm) return false; }
      if(!isNaN(smin) && (x.s==null||x.s<smin)) return false;
      if(!isNaN(smax) && (x.s==null||x.s>smax)) return false;
      if(st && x.st.toLowerCase().indexOf(st)<0) return false;
      return true;
    });
    var sp=f.map(function(x){return x.sp;}),
        pr=f.filter(function(x){return x.p;}).map(function(x){return x.p;}),
        dom=f.filter(function(x){return x.dom!=null;}).map(function(x){return x.dom;}),
        cut=f.filter(function(x){return x.cut<0;}).length;
    var gaps=f.filter(function(x){return x.g!=null;}).map(function(x){return x.g;});
    $('ex-stats').innerHTML =
      tile('Matches', f.length.toLocaleString('da-DK'),'') +
      tile('Median price', fmtdkk(median(pr)),' DKK') +
      tile('Median DKK/m²', fmtdkk(median(sp)),'') +
      tile('Median vs comps', gaps.length? (median(gaps)>0?'+':'')+median(gaps).toFixed(1)+'%':'–','') +
      tile('Median days', median(dom)==null?'–':Math.round(median(dom)),' days');
    var sort=$('f-sort').value;
    var rows=f.slice();
    var BIG=1e12;
    if(sort==='value') rows.sort(function(a,b){return (a.g==null?BIG:a.g)-(b.g==null?BIG:b.g);});
    else if(sort==='sp-asc') rows.sort(function(a,b){return a.sp-b.sp;});
    else if(sort==='dom-desc') rows.sort(function(a,b){return (b.dom||0)-(a.dom||0);});
    else rows.sort(function(a,b){return b.sp-a.sp;});
    var top=rows.slice(0,60).map(function(x){
      var gap = x.g==null? '–' : (x.g>0?'+':'')+x.g.toFixed(1)+'%';
      var gcls = x.g==null? '' : (x.g<=-5?'gap-lo': (x.g>=10?'gap-hi':''));
      var est = x.e? fmtdkk(x.e) : '–';
      var estTitle = x.nc? (' title="'+x.nc+' comps"'):'';
      return '<tr><td>'+(labels[x.d]||'–')+'</td><td>'+(x.st||'–')+'</td><td class="num">'+
        (x.s||'–')+'</td><td class="num">'+(x.r||'–')+'</td><td class="num">'+fmtdkk(x.p)+
        '</td><td class="num">'+fmtdkk(x.sp)+'</td><td class="num"'+estTitle+'>'+est+
        (x.nc&&x.nc<8?' <span class="lowconf">n='+x.nc+'</span>':'')+
        '</td><td class="num '+gcls+'">'+gap+'</td><td class="num">'+(x.dom==null?'–':x.dom)+
        '</td><td class="num">'+(x.cut<0? x.cut.toFixed(0)+'%':'–')+'</td></tr>';
    }).join('');
    $('ex-table').getElementsByTagName('tbody')[0].innerHTML=top;
    $('ex-more').textContent = rows.length>60? ('Showing top 60 of '+rows.length+'.'):'';
  }
  ['f-dist','f-rooms','f-smin','f-smax','f-street','f-sort'].forEach(function(id){
    $(id).addEventListener('input',apply);
  });
  apply();
})();
</script>
"""


# --------------------------------------------------------------------------- #
# Page
# --------------------------------------------------------------------------- #

CSS = """
:root{color-scheme:light dark;--plane:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;
--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);
--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--c6:#008300;}
@media (prefers-color-scheme:dark){:root{--plane:#0d0d0d;--surface:#1a1a19;--ink:#fff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);
--c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--c6:#008300;}}
*{box-sizing:border-box;}
body{margin:0;background:var(--plane);color:var(--ink);font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;}
.wrap{max-width:1120px;margin:0 auto;padding:32px 20px 64px;}
header h1{margin:0 0 4px;font-size:24px;letter-spacing:-.01em;}
header p{margin:0;color:var(--ink2);max-width:74ch;}
.asof{color:var(--muted);font-size:13px;margin-top:8px;}
h2.section{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);
margin:36px 0 14px;border-top:1px solid var(--border);padding-top:22px;}
.kpi-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:24px 0;}
.kpi{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px 16px;}
.kpi-label{color:var(--ink2);font-size:13px;}
.kpi-value{font-size:24px;font-weight:600;margin:6px 0 4px;letter-spacing:-.01em;}
.kpi-value .unit{font-size:13px;font-weight:400;color:var(--muted);margin-left:3px;}
.delta{font-size:13px;color:var(--ink2);} .delta .wow{color:var(--muted);font-size:11px;}
.grid-charts{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:18px;}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px 12px;margin:0;}
.card figcaption h3{margin:0;font-size:15px;} .card .sub{color:var(--muted);font-size:12px;}
.chart{width:100%;height:auto;display:block;margin-top:8px;overflow:visible;}
.grid{stroke:var(--grid);stroke-width:1;}
.tick{fill:var(--muted);font-size:11px;font-variant-numeric:tabular-nums;}
.ty{text-anchor:end;} .tx{text-anchor:middle;}
.line{stroke-width:2;} .dot{stroke-width:1.5;fill:var(--surface);}
.dlabel{font-size:11px;font-weight:600;stroke:none;}
.s-c1{stroke:var(--c1);} .s-c2{stroke:var(--c2);} .s-c3{stroke:var(--c3);}
.s-c4{stroke:var(--c4);} .s-c5{stroke:var(--c5);} .s-c6{stroke:var(--c6);}
.dlabel.s-c1{fill:var(--c1);} .dlabel.s-c2{fill:var(--c2);} .dlabel.s-c3{fill:var(--c3);}
.dlabel.s-c4{fill:var(--c4);} .dlabel.s-c5{fill:var(--c5);} .dlabel.s-c6{fill:var(--c6);}
.fill.s-c1{fill:var(--c1);} .fill.s-c2{fill:var(--c2);}
.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin-top:6px;}
.legend .sw{display:inline-block;width:11px;height:11px;border-radius:3px;margin-right:5px;vertical-align:-1px;}
.legend .sw.s-c1{background:var(--c1);} .legend .sw.s-c2{background:var(--c2);}
.empty{color:var(--muted);font-size:13px;padding:24px 0;}
.explore{margin-top:16px;}
.filters{display:flex;gap:14px;flex-wrap:wrap;margin:14px 0 4px;}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2);gap:4px;}
.filters .grow{flex:1;min-width:180px;}
.filters select,.filters input{font:14px system-ui;padding:7px 9px;border:1px solid var(--border);
border-radius:8px;background:var(--plane);color:var(--ink);}
.explore-stats{grid-template-columns:repeat(auto-fit,minmax(130px,1fr));margin:14px 0;}
.table-wrap{overflow-x:auto;border:1px solid var(--border);border-radius:10px;margin-top:6px;}
table{border-collapse:collapse;width:100%;font-size:13px;}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap;}
th{color:var(--ink2);font-weight:600;position:sticky;top:0;background:var(--surface);}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
tbody tr:last-child td{border-bottom:none;}
.more{color:var(--muted);font-size:12px;margin-top:8px;}
td.gap-lo{color:#0ca30c;font-weight:600;} td.gap-hi{color:var(--ink2);}
.lowconf{color:var(--muted);font-size:11px;}
.methodology{color:var(--muted);font-size:12px;line-height:1.5;margin-top:12px;}
.methodology strong{color:var(--ink2);} .methodology em{font-style:italic;}
.note{margin-top:32px;padding:16px 18px;background:var(--surface);border:1px solid var(--border);
border-radius:12px;color:var(--ink2);font-size:13px;} .note strong{color:var(--ink);}
"""


def _district_series(rows, cfg, field):
    out = []
    for i, (key, spec) in enumerate(cfg["districts"].items()):
        out.append(_series(rows, f"dist:{key}", field, spec["label"], DISTRICT_SLOTS[i % len(DISTRICT_SLOTS)]))
    return out


def build_html(rows, active, cfg, generated) -> str:
    ptype_series = [_series(rows, seg, "median_sqm_price", lbl, slot) for seg, (lbl, slot) in PTYPE.items()]
    trend = [
        line_chart("Asking price per m²", "Median DKK, by property type",
                   ptype_series, "dkk", "price"),
        line_chart("Asking price per m² by district", "Median DKK — where the divergence is",
                   _district_series(rows, cfg, "median_sqm_price"), "dkk", "price-dist"),
        line_chart("Asking vs. realised sold price per m²", "Median DKK — sold lags ~1-3 months",
                   [_series(rows, "all", "median_sqm_price", "Asking", "c1"),
                    _series(rows, "all", "median_sold_sqm_price", "Sold", "c2")], "dkk", "asksold"),
        line_chart("Months of supply", "Inventory ÷ monthly sales — higher = more buyer's market",
                   [_series(rows, "all", "months_of_supply", "All", "c1")], "months", "supply"),
        line_chart("Days on market", "Median age of active listings — rising = slowing",
                   ptype_series_field(rows, "median_days_on_market"), "days", "dom"),
        line_chart("Listings with a price cut", "% of active listings below their original ask",
                   ptype_series_field(rows, "pct_price_cut"), "pct", "cut"),
        line_chart("Active inventory", "Number of listings for sale",
                   [_series(rows, "all", "n_listings", "All", "c1")], "days", "inv"),
        bar_chart("Weekly flow", "New listings vs. delisted (sold or withdrawn)", rows),
    ]
    snaps = sorted({r["snapshot_date"] for r in rows})
    span = f"{snaps[0]} → {snaps[-1]}" if snaps else "no data yet"
    payload = json.dumps(explore_payload(active, cfg)).replace("</", "<\\/")

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f9f9f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="CPH Housing">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Copenhagen Housing Monitor</title><style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>Copenhagen Housing Monitor</h1>
<p>Live-listing indicators for <strong>{html.escape(cfg['scope']['name'])}</strong>, snapshotted weekly
from Boliga. Asking prices, cuts and days-on-market are <em>leading</em> indicators; realised
sold prices are the lagging ground truth.</p>
<div class="asof">Generated {generated.isoformat()} · {len(snaps)} snapshot(s) · {span}</div></header>
{kpi_tiles(rows)}
<h2 class="section">Market direction (weekly trend)</h2>
<div class="grid-charts">{''.join(trend)}</div>
<h2 class="section">Explore the current market</h2>
{EXPLORE_HTML}
<div class="note"><strong>Read this before trusting a trend.</strong> Asking prices are what sellers
<em>want</em>, not what they get; realised sold prices lag ~1-3 months. District tags are by postcode
(approximate). The source (Boliga) is an undocumented scrape that can drift. A single snapshot shows no
direction — several consistent weeks do. Cross-check quarterly against official Finans Danmark / Danmarks
Statistik figures before any decision that matters.</div>
</div>
<script>window.__EXPLORE__ = {payload};</script>
{EXPLORE_JS}
</body></html>
"""


def ptype_series_field(rows, field):
    return [_series(rows, seg, field, lbl, slot) for seg, (lbl, slot) in PTYPE.items()]


def write_dashboard(rows, active, cfg, out_path: Path, generated: date | None = None) -> Path:
    generated = generated or date.today()
    out_path.write_text(build_html(rows, active or [], cfg, generated), encoding="utf-8")
    log.info("wrote dashboard: %s", out_path)
    return out_path
