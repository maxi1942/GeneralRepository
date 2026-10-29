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
        ("Median asking (live)", "median_sqm_price", "dkk", " DKK/m²"),
        ("Median sold (realised)", "median_sold_sqm_price", "dkk", " DKK/m²"),
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


def going_rates_table(rows, cfg) -> str:
    """Per-neighbourhood 'going rate' table — realised SOLD prices first, then asking."""
    if not rows:
        return ""
    latest = max(r["snapshot_date"] for r in rows)
    by_seg = {r["segment"]: r for r in rows if r["snapshot_date"] == latest}

    order = [("all", "All Copenhagen")] + [(f"dist:{k}", v["label"]) for k, v in cfg["districts"].items()]
    body = []
    for seg, label in order:
        r = by_seg.get(seg)
        if not r:
            continue
        sold = _num(r.get("median_sold_sqm_price"))
        ask = _num(r.get("median_sqm_price"))
        gap = None
        if sold and ask:
            gap = (ask - sold) / sold * 100
        n = _num(r.get("sold_count"))
        mos = _num(r.get("months_of_supply"))
        body.append(
            f'<tr><td>{html.escape(label)}</td>'
            f'<td class="num strong">{_fmt(sold, "dkk")}</td>'
            f'<td class="num">{_fmt(ask, "dkk")}</td>'
            f'<td class="num">{("+" if gap and gap>0 else "")+format(gap, ".1f")+"%" if gap is not None else "–"}</td>'
            f'<td class="num">{int(n) if n else "–"}</td>'
            f'<td class="num">{_fmt(mos, "months") if mos is not None else "–"}</td></tr>')
    return (
        '<figure class="card wide"><figcaption><h3>Going rates by neighbourhood</h3>'
        '<span class="sub">Realised <strong>sold</strong> price/m² is the going rate; asking is what sellers '
        'currently want. Sold lags ~1–3 months.</span></figcaption>'
        '<div class="table-wrap"><table><thead><tr>'
        '<th>Neighbourhood</th><th class="num">Sold /m² (realised)</th><th class="num">Asking /m² (live)</th>'
        '<th class="num">Asking vs sold</th><th class="num">Recent sales</th><th class="num">Months supply</th>'
        f'</tr></thead><tbody>{"".join(body)}</tbody></table></div></figure>')


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
        la, lo = M._to_float(r.get("latitude")), M._to_float(r.get("longitude"))
        # only keep coordinates that fall in a sane Copenhagen-area box (guards against
        # stray 0/null/elsewhere values plotting in the ocean)
        geo = (54.0 < (la or 0) < 58.0 and 11.0 < (lo or 0) < 13.0)
        items.append({
            "la": round(la, 5) if geo else None,     # latitude (for the map)
            "lo": round(lo, 5) if geo else None,     # longitude
            "d": dk or "other", "z": M._to_int(r.get("zip_code")),
            "u": M._to_int(r.get("id")),             # Boliga listing id (for the link)
            "s": int(size) if size else None, "r": M._to_int(r.get("rooms")),
            "p": int(price) if price else None, "sp": int(sp),
            "dom": M._to_int(r.get("days_on_market")),
            "ld": (r.get("created_date") or "")[:10] or None,  # date the listing went live
            "oh": (r.get("open_house") or "").strip()[:10] or None,   # next public showing (date)
            "oht": ((r.get("open_house") or "").strip()[11:16] or None),  # showing clock time HH:MM
            "cut": _num(r.get("price_change_pct")) or 0,
            "st": (r.get("street") or "").strip(),
            "e": int(est) if est else None,          # comps-based expected sold DKK/m²
            "g": _num(r.get("gap_pct")),             # asking vs comps, %
            "nc": M._to_int(r.get("n_comps")) or 0,  # number of comps behind the estimate
            "en": r.get("energy"),                   # energy class A-G
            "fl": r.get("flags") or [],              # 'why cheap?' flags
            "au": r.get("estate_url"),               # agent listing url
            "ls": M._to_int(r.get("last_sold_price")) or None,  # prior sale price
            "dt": 1 if r.get("detailed") else 0,     # detail fetched yet?
        })
    labels["other"] = "Other Copenhagen"
    return {"items": items, "labels": labels}


EXPLORE_HTML = """
<section class="explore card">
  <figcaption><h3>Explore current listings</h3>
  <span class="sub">Live filter over the latest snapshot — a point-in-time view, not a trend.</span></figcaption>
  <div class="areas"><span class="areas-lbl">Areas</span>
    <div id="f-dist-chips" class="chips"></div></div>
  <div class="filters">
    <label>Rooms<select id="f-rooms">
      <option value="">Any</option><option>1</option><option>2</option><option>3</option>
      <option>4</option><option value="5+">5+</option></select></label>
    <label>Min m²<input id="f-smin" type="number" min="0" step="5" placeholder="any"></label>
    <label>Max m²<input id="f-smax" type="number" min="0" step="5" placeholder="any"></label>
    <label class="grow">Street contains<input id="f-street" type="text" placeholder="e.g. Istedgade"></label>
    <label>Energy<select id="f-energy">
      <option value="">Any</option><option>A</option><option>B</option><option>C</option>
      <option>D</option><option>E</option><option>F</option><option>G</option></select></label>
    <label>Open house<select id="f-oh">
      <option value="">Any</option><option value="any">Has a showing</option></select></label>
    <label>Sort by<select id="f-sort">
      <option value="new">Newest listed</option>
      <option value="oh">Showing soonest</option>
      <option value="value">Best value (asking vs comps)</option>
      <option value="sp-desc">DKK/m² (high → low)</option>
      <option value="sp-asc">DKK/m² (low → high)</option>
      <option value="dom-desc">Longest on market</option>
    </select></label>
    <label class="chk"><input type="checkbox" id="f-clean"> Hide flagged (find clean bargains)</label>
    <label class="chk"><input type="checkbox" id="f-star"> ⭐ Starred only</label>
  </div>
  <div id="ex-stats" class="kpi-row explore-stats"></div>
  <div class="table-wrap"><table id="ex-table"><thead><tr>
    <th></th><th>District</th><th>Street</th><th class="num">m²</th><th class="num">Rooms</th>
    <th class="num">Asking</th><th class="num">Asking /m²</th><th class="num">Est. sold /m²</th>
    <th class="num">vs comps</th><th>Energy</th><th>Why cheap?</th><th>Open house</th><th>Listed</th><th class="num">Days</th><th class="num">Cut</th>
  </tr></thead><tbody></tbody></table></div>
  <div id="ex-more" class="more"></div>
  <p class="methodology">“Est. sold /m²” is the median price per m² of comparable <em>sold</em> homes
  (same district, property type, ±25% size and, where possible, same rooms). “vs comps” is how far
  asking sits above (+) or below (−) that — asking is normally a few % above realised sales, so treat
  small positives as normal. Co-op (andel) listings, foreclosures and rows with an implausible price/m²
  are excluded; “n=” flags low comp counts. The <strong>“Why cheap?”</strong> column now surfaces
  visible reasons from each listing's detail page — poor <b>energy</b> class, <b>leasehold</b> land, a
  <b>ground floor</b>, or a <b>stale</b> listing. A big negative “vs comps” with a <b>✓ clean</b> tag is
  the genuinely interesting one; tick <b>“Hide flagged”</b> to hunt those. Detail is fetched a few
  hundred listings per week (candidates first), so some rows read <em>pending…</em> until enriched.
  Balcony/condition aren't in Boliga's data — they're only in the agent's description behind the link.
  <strong>“Listed”</strong> is when the listing went live (sorted newest-first by default); a
  <span class="newbadge">NEW</span> tag marks the last 7 days — though an agent re-listing a stale flat
  can reset that date, so an occasional “new” is really a re-list.
  <strong>“Open house”</strong> is the next public showing (åbent hus) straight from Boliga's feed —
  pick a date in the filter to see only flats showing that day. It refreshes every run, but only ~half
  of listings publish a showing date, and times are shown as Boliga lists them — always confirm on the
  listing before turning up. The <strong>📅</strong> next to an upcoming showing opens Google Calendar
  with the event pre-filled; pick which calendar (e.g. your shared one) from the dropdown before saving.
  Even clean, this is a screen to shortlist and inspect, not a valuation.</p>
</section>
"""

EXPLORE_JS = """
<script>
(function(){
  var DATA = window.__EXPLORE__ || {items:[],labels:{}};
  var items = DATA.items, labels = DATA.labels;
  var $ = function(id){return document.getElementById(id);};
  function keyOf(x){ return 'L'+(x.u || (x.st+'_'+x.z)); }
  function saveData(x){ return {t:'active', a:x.st, d:x.d, p:x.p, sp:x.sp, s:x.s, r:x.r, u:x.u, au:x.au, z:x.z}; }
  var sel = new Set();               // selected districts; empty = all
  var wrap = $('f-dist-chips');
  var allChip = document.createElement('button');
  allChip.className='chip all on'; allChip.textContent='All areas';
  allChip.onclick=function(){ sel.clear(); syncChips(); apply(); };
  wrap.appendChild(allChip);
  var chipEls={};
  Object.keys(labels).forEach(function(k){
    var c=document.createElement('button'); c.className='chip'; c.textContent=labels[k];
    c.onclick=function(){ if(sel.has(k)) sel.delete(k); else sel.add(k); syncChips(); apply(); };
    chipEls[k]=c; wrap.appendChild(c);
  });
  function syncChips(){
    allChip.classList.toggle('on', sel.size===0);
    Object.keys(chipEls).forEach(function(k){ chipEls[k].classList.toggle('on', sel.has(k)); });
  }
  function median(a){ if(!a.length) return null; a=a.slice().sort(function(x,y){return x-y;});
    var m=Math.floor(a.length/2); return a.length%2? a[m] : (a[m-1]+a[m])/2; }
  function fmtdkk(v){ return v==null?'–':Math.round(v).toLocaleString('da-DK'); }
  function tile(label,val,unit){ return '<div class="kpi"><div class="kpi-label">'+label+
    '</div><div class="kpi-value">'+val+'<span class="unit">'+(unit||'')+'</span></div></div>'; }
  // Build a Google Calendar "add event" link for a listing's open house. Times are the
  // clock value Boliga provides, treated as Copenhagen local (ctz); default 11:00 and a
  // 1h slot when no time is given. You pick the target calendar in Google before saving.
  function pad2(n){ return (n<10?'0':'')+n; }
  function gcalUrl(x){
    if(!x.oh) return null;
    var t=(x.oht && /^\\d{2}:\\d{2}$/.test(x.oht)) ? x.oht : '11:00';
    var hh=parseInt(t.slice(0,2),10), mm=t.slice(3,5);
    var dstr=x.oh.replace(/-/g,'');
    var start=dstr+'T'+pad2(hh)+mm+'00';
    var end = hh>=23 ? dstr+'T235900' : dstr+'T'+pad2(hh+1)+mm+'00';
    var addr=(x.st||'')+', '+(x.z||'')+' København';
    var href = x.au ? x.au : (x.u? 'https://www.boliga.dk/bolig/'+x.u : '');
    var details='Open house / åbent hus.\\n'+(href?('Listing: '+href+'\\n'):'')+
      '\\n(Time is as Boliga lists it — confirm on the listing before you go.)';
    return 'https://calendar.google.com/calendar/render?action=TEMPLATE'+
      '&text='+encodeURIComponent('Viewing: '+(x.st||'listing'))+
      '&dates='+start+'/'+end+'&ctz=Europe/Copenhagen'+
      '&location='+encodeURIComponent(addr)+
      '&details='+encodeURIComponent(details);
  }
  // populate the open-house date picker with the actual upcoming showing dates (+ counts)
  var todayStr=new Date().toISOString().slice(0,10);
  (function(){
    var counts={};
    items.forEach(function(x){ if(x.oh && x.oh>=todayStr) counts[x.oh]=(counts[x.oh]||0)+1; });
    Object.keys(counts).sort().forEach(function(d){
      var o=document.createElement('option'); o.value=d;
      var lbl=d; try{ lbl=new Date(d+'T00:00:00').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'}); }catch(e){}
      o.textContent=lbl+' ('+counts[d]+')'; $('f-oh').appendChild(o);
    });
  })();
  function apply(){
    var rm=$('f-rooms').value,
        smin=parseFloat($('f-smin').value), smax=parseFloat($('f-smax').value),
        st=$('f-street').value.trim().toLowerCase(),
        en=$('f-energy').value, clean=$('f-clean').checked, starOnly=$('f-star').checked,
        ohf=$('f-oh').value;
    var f=items.filter(function(x){
      if(sel.size && !sel.has(x.d)) return false;
      if(rm==='5+'){ if(!(x.r>=5)) return false; } else if(rm){ if(x.r!=+rm) return false; }
      if(!isNaN(smin) && (x.s==null||x.s<smin)) return false;
      if(!isNaN(smax) && (x.s==null||x.s>smax)) return false;
      if(st && x.st.toLowerCase().indexOf(st)<0) return false;
      if(en && x.en!==en) return false;
      if(clean && (x.fl&&x.fl.length)) return false;
      if(starOnly && !window.CPHStars.has(keyOf(x))) return false;
      if(ohf==='any'){ if(!x.oh) return false; }
      else if(ohf){ if(x.oh!==ohf) return false; }
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
    if(sort==='new') rows.sort(function(a,b){return (b.ld||'').localeCompare(a.ld||'');});
    else if(sort==='oh') rows.sort(function(a,b){return (a.oh||'9999-99-99').localeCompare(b.oh||'9999-99-99');});
    else if(sort==='value') rows.sort(function(a,b){return (a.g==null?BIG:a.g)-(b.g==null?BIG:b.g);});
    else if(sort==='sp-asc') rows.sort(function(a,b){return a.sp-b.sp;});
    else if(sort==='dom-desc') rows.sort(function(a,b){return (b.dom||0)-(a.dom||0);});
    else rows.sort(function(a,b){return b.sp-a.sp;});
    var top=rows.map(function(x){
      var gap = x.g==null? '–' : (x.g>0?'+':'')+x.g.toFixed(1)+'%';
      var gcls = x.g==null? '' : (x.g<=-5?'gap-lo': (x.g>=10?'gap-hi':''));
      var est = x.e? fmtdkk(x.e) : '–';
      var estTitle = x.nc? (' title="'+x.nc+' comps"'):'';
      var addr = (x.st||'').replace(/</g,'');
      var gq = encodeURIComponent((x.st||'')+', '+(x.z||'')+' København');
      var glink = '<a class="glink" target="_blank" rel="noopener" href="https://www.google.com/search?q='+gq+'" title="Search this address">⌕</a>';
      var href = x.au ? x.au : (x.u? 'https://www.boliga.dk/bolig/'+x.u : null);
      var stcell = href
        ? '<a target="_blank" rel="noopener" href="'+href+'">'+(addr||'listing')+'</a> '+glink
        : (addr||'–')+' '+glink;
      var en = x.en? '<span class="energy e'+x.en+'">'+x.en+'</span>' : '–';
      var flags = !x.dt ? '<span class="pending">pending…</span>'
        : ((x.fl&&x.fl.length)
            ? x.fl.map(function(t){return '<span class="flag">'+t+'</span>';}).join(' ')
            : '<span class="ok">✓ clean</span>');
      var isNew = (x.dom!=null && x.dom<=7);
      var listed = x.ld ? (x.ld + (isNew?' <span class="newbadge">NEW</span>':'')) : '–';
      var ohSoon = (x.oh && x.oh>=todayStr);
      var cal = (x.oh && ohSoon) ? (' <a class="glink cal" target="_blank" rel="noopener" href="'+
          gcalUrl(x)+'" title="Add viewing to Google Calendar">📅</a>') : '';
      var showing = x.oh ? ('<span class="'+(ohSoon?'ohnext':'ohpast')+'">'+x.oh+
          (x.oht?' <span class="ohtime">'+x.oht+'</span>':'')+'</span>'+cal) : '–';
      var k=keyOf(x), on=window.CPHStars.has(k);
      var star='<button class="star'+(on?' on':'')+'" data-k="'+k+'" title="Save">'+(on?'★':'☆')+'</button>';
      return '<tr><td>'+star+'</td><td>'+(labels[x.d]||'Other')+'</td><td>'+stcell+'</td><td class="num">'+
        (x.s||'–')+'</td><td class="num">'+(x.r||'–')+'</td><td class="num">'+fmtdkk(x.p)+
        '</td><td class="num">'+fmtdkk(x.sp)+'</td><td class="num"'+estTitle+'>'+est+
        (x.nc&&x.nc<8?' <span class="lowconf">n='+x.nc+'</span>':'')+
        '</td><td class="num '+gcls+'">'+gap+'</td><td>'+en+'</td><td class="flags">'+flags+
        '</td><td class="lst">'+showing+'</td><td class="lst">'+listed+'</td><td class="num">'+(x.dom==null?'–':x.dom)+
        '</td><td class="num">'+(x.cut<0? x.cut.toFixed(0)+'%':'–')+'</td></tr>';
    }).join('');
    $('ex-table').getElementsByTagName('tbody')[0].innerHTML=top;
    $('ex-more').textContent = rows.length.toLocaleString('da-DK')+' listing'+(rows.length===1?'':'s')+' shown — scroll the table to see all.';
  }
  function debounce(fn,ms){var t;return function(){clearTimeout(t);t=setTimeout(fn,ms);};}
  ['f-rooms','f-smin','f-smax','f-sort','f-energy','f-clean','f-star','f-oh'].forEach(function(id){
    $(id).addEventListener('input',apply);
  });
  $('f-street').addEventListener('input', debounce(apply,160));
  var itemByKey={}; items.forEach(function(x){ itemByKey[keyOf(x)]=x; });
  $('ex-table').addEventListener('click', function(e){
    var b=e.target.closest && e.target.closest('button.star[data-k]');
    if(!b) return;
    var k=b.getAttribute('data-k'), x=itemByKey[k];
    window.CPHStars.toggle(k, x?saveData(x):{t:'active'});
  });
  window.CPHStars.onChange(apply);
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
.callout{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--c1);
border-radius:10px;padding:12px 16px;margin:20px 0;font-size:13px;color:var(--ink2);line-height:1.55;}
.callout strong{color:var(--ink);} .callout b{color:var(--ink);font-weight:600;}
.card.wide{margin:0 0 18px;} td.strong{font-weight:600;color:var(--ink);}
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
.areas{margin:14px 0 4px;} .areas-lbl{font-size:12px;color:var(--ink2);display:block;margin-bottom:6px;}
.chips{display:flex;flex-wrap:wrap;gap:6px;}
.chip{border:1px solid var(--border);background:var(--plane);color:var(--ink2);border-radius:999px;
padding:5px 12px;font-size:13px;cursor:pointer;font-family:inherit;line-height:1.2;}
.chip:hover{border-color:var(--c1);} .chip.on{background:var(--c1);border-color:var(--c1);color:#fff;}
.chip.all{font-weight:600;}
.filters{display:flex;gap:14px;flex-wrap:wrap;margin:6px 0 4px;}
.filters label{display:flex;flex-direction:column;font-size:12px;color:var(--ink2);gap:4px;}
.filters .grow{flex:1;min-width:180px;}
.filters select,.filters input{font:14px system-ui;padding:7px 9px;border:1px solid var(--border);
border-radius:8px;background:var(--plane);color:var(--ink);}
.explore-stats{grid-template-columns:repeat(auto-fit,minmax(130px,1fr));margin:14px 0;}
.table-wrap{overflow:auto;max-height:75vh;border:1px solid var(--border);border-radius:10px;margin-top:6px;}
table{border-collapse:collapse;width:100%;font-size:13px;}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid var(--border);white-space:nowrap;}
th{color:var(--ink2);font-weight:600;position:sticky;top:0;background:var(--surface);}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums;}
tbody tr:last-child td{border-bottom:none;}
.more{color:var(--muted);font-size:12px;margin-top:8px;}
td.gap-lo{color:#0ca30c;font-weight:600;} td.gap-hi{color:var(--ink2);}
.lowconf{color:var(--muted);font-size:11px;}
table a{color:var(--c1);text-decoration:none;} table a:hover{text-decoration:underline;}
.glink{display:inline-block;margin-left:4px;color:var(--muted);font-size:13px;text-decoration:none;}
.glink:hover{color:var(--c1);}
.filters .chk{flex-direction:row;align-items:center;gap:6px;font-size:13px;color:var(--ink);align-self:end;padding-bottom:7px;}
.filters .chk input{width:auto;}
.energy{display:inline-block;min-width:18px;text-align:center;padding:1px 5px;border-radius:4px;
font-weight:600;font-size:12px;color:#fff;background:var(--muted);}
.energy.eA,.energy.eB{background:#0ca30c;} .energy.eC,.energy.eD{background:#eda100;color:#1a1a19;}
.energy.eE,.energy.eF,.energy.eG{background:#d03b3b;}
td.flags{white-space:normal;max-width:220px;}
.flag{display:inline-block;background:rgba(208,59,59,.12);color:#d03b3b;border-radius:4px;
padding:1px 6px;font-size:11px;margin:1px 2px 1px 0;white-space:nowrap;}
.ok{color:#0ca30c;font-size:12px;} .pending{color:var(--muted);font-size:11px;font-style:italic;}
td.lst{font-variant-numeric:tabular-nums;color:var(--ink2);}
.newbadge{display:inline-block;background:var(--c3);color:#fff;border-radius:4px;padding:0 5px;font-size:10px;font-weight:700;margin-left:4px;vertical-align:1px;}
.ohnext{color:var(--c1);font-weight:600;} .ohpast{color:var(--muted);}
.ohtime{color:var(--muted);font-weight:400;font-size:12px;}
.glink.cal{font-size:14px;margin-left:5px;opacity:.85;} .glink.cal:hover{opacity:1;}
.tabs{position:sticky;top:0;z-index:20;display:flex;gap:2px;overflow-x:auto;background:var(--plane);
border-bottom:1px solid var(--border);margin:18px -20px 22px;padding:0 14px;-webkit-overflow-scrolling:touch;}
.tab-btn{appearance:none;background:none;border:none;border-bottom:2px solid transparent;color:var(--ink2);
font:inherit;font-size:14px;font-weight:600;padding:12px 10px;cursor:pointer;white-space:nowrap;}
.tab-btn:hover{color:var(--ink);} .tab-btn.on{color:var(--c1);border-bottom-color:var(--c1);}
.tabcount{display:inline-block;min-width:16px;padding:0 5px;border-radius:999px;background:var(--c4);
color:#fff;font-size:11px;font-weight:700;vertical-align:1px;}
.tabpanel{display:none;} .tabpanel.on{display:block;}
.tabpanel>h2.section:first-child{margin-top:4px;border-top:none;padding-top:0;}
.mapbox{height:70vh;min-height:420px;border:1px solid var(--border);border-radius:10px;overflow:hidden;margin-top:6px;}
.leaflet-popup-content{font:13px/1.45 system-ui,-apple-system,sans-serif;margin:10px 12px;}
.leaflet-popup-content a{color:#2a78d6;text-decoration:none;} .leaflet-popup-content a:hover{text-decoration:underline;}
.map-legend{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--ink2);margin:10px 0 2px;}
.map-legend i{display:inline-block;width:11px;height:11px;border-radius:50%;margin-right:5px;vertical-align:-1px;}
.map-fallback{text-align:left;}
.star{background:none;border:none;cursor:pointer;font-size:16px;line-height:1;padding:0 2px;color:var(--muted);}
.star:hover{color:var(--c4);} .star.on{color:var(--c4);}
.saved{margin:20px 0;border-left:3px solid var(--c4);}
.saved figcaption h3{margin:0;font-size:15px;}
.linkbtn{background:none;border:none;color:var(--c1);cursor:pointer;font:inherit;font-size:12px;padding:0;text-decoration:underline;}
.soldbadge{display:inline-block;background:#0ca30c;color:#fff;border-radius:4px;padding:1px 7px;font-size:12px;font-weight:600;}
.methodology{color:var(--muted);font-size:12px;line-height:1.5;margin-top:12px;}
.methodology strong{color:var(--ink2);} .methodology em{font-style:italic;}
.note{margin-top:32px;padding:16px 18px;background:var(--surface);border:1px solid var(--border);
border-radius:12px;color:var(--ink2);font-size:13px;} .note strong{color:var(--ink);}
"""


def _district_series(rows, cfg, field):
    keys = cfg.get("chart_districts") or list(cfg["districts"].keys())
    out = []
    for i, key in enumerate(keys):
        spec = cfg["districts"].get(key)
        if not spec:
            continue
        out.append(_series(rows, f"dist:{key}", field, spec["label"], DISTRICT_SLOTS[i % len(DISTRICT_SLOTS)]))
    return out


def sold_payload(sold_hist, cfg) -> dict:
    districts = cfg["districts"]
    labels = {k: v["label"] for k, v in districts.items()}
    buckets = cfg["property_type_buckets"]

    def bucket(pt):
        code = M._to_int(pt)
        for name, codes in buckets.items():
            if code in codes:
                return name
        return "other"

    items = []
    for r in sold_hist:
        sp, price = _num(r.get("sqm_price")), _num(r.get("price"))
        if not sp or not price:
            continue
        ch = _num(r.get("change_pct"))
        bid = M._to_int(r.get("id"))
        items.append({
            "d": M.district_of(r.get("zip_code"), districts) or "other",
            "z": M._to_int(r.get("zip_code")), "s": M._to_int(r.get("size_m2")),
            "r": M._to_int(r.get("rooms")), "p": int(price), "sp": int(sp),
            "ch": round(ch, 1) if (ch is not None and ch < 0) else None,
            "dt": (r.get("sold_date") or "")[:10], "st": (r.get("street") or "").strip(),
            "pt": bucket(r.get("property_type")),
            "u": bid if (bid and bid > 0) else None,     # Boliga property id (has photos)
            "au": r.get("estate_url") or None,           # agent listing url
        })
    labels["other"] = "Other Copenhagen"
    return {"items": items, "labels": labels}


SOLD_HTML = """
<section class="explore card">
  <figcaption><h3>Sold prices — what apartments actually went for</h3>
  <span class="sub">Every registered sale we've archived (land registry, via Boliga). Grows over time.</span></figcaption>
  <div class="areas"><span class="areas-lbl">Areas</span><div id="sf-dist-chips" class="chips"></div></div>
  <div class="filters">
    <label>Type<select id="sf-type">
      <option value="">All</option><option value="apartment">Apartments</option>
      <option value="house">Houses</option></select></label>
    <label>Rooms<select id="sf-rooms">
      <option value="">Any</option><option>1</option><option>2</option><option>3</option>
      <option>4</option><option value="5+">5+</option></select></label>
    <label>Min m²<input id="sf-smin" type="number" min="0" step="5" placeholder="any"></label>
    <label>Max m²<input id="sf-smax" type="number" min="0" step="5" placeholder="any"></label>
    <label class="grow">Street contains<input id="sf-street" type="text" placeholder="e.g. Istedgade"></label>
    <label>Sort by<select id="sf-sort">
      <option value="date">Most recent</option>
      <option value="sp-desc">DKK/m² (high → low)</option>
      <option value="sp-asc">DKK/m² (low → high)</option>
    </select></label>
    <label class="chk"><input type="checkbox" id="sf-star"> ⭐ Starred only</label>
  </div>
  <div id="sf-stats" class="kpi-row explore-stats"></div>
  <div class="table-wrap"><table id="sf-table"><thead><tr>
    <th></th><th>Sold</th><th>District</th><th>Address</th><th class="num">m²</th><th class="num">Rooms</th>
    <th class="num">Sold price</th><th class="num">Sold /m²</th><th class="num">vs ask</th>
  </tr></thead><tbody></tbody></table></div>
  <div id="sf-more" class="more"></div>
  <p class="methodology">These are <strong>realised</strong> sale prices from the public land registry —
  what buyers actually paid — for a specific apartment (full address). “vs ask” shows how far below the
  original asking price it sold, when the feed provides it. Sales register ~1–3 months after closing, so
  the most recent weeks are still filling in. Search a street to see what nearby flats fetched.</p>
</section>
"""

SOLD_JS = """
<script>
(function(){
  var DATA = window.__SOLD__ || {items:[],labels:{}};
  var items=DATA.items, labels=DATA.labels;
  var $=function(id){return document.getElementById(id);};
  function keyOf(x){ return 'S'+(x.u || (x.st+'_'+x.dt+'_'+x.p)); }
  function saveData(x){ return {t:'sold', a:x.st, d:x.d, p:x.p, sp:x.sp, s:x.s, r:x.r, u:x.u, dt:x.dt, z:x.z}; }
  var sel=new Set(); var wrap=$('sf-dist-chips');
  var allChip=document.createElement('button'); allChip.className='chip all on'; allChip.textContent='All areas';
  allChip.onclick=function(){ sel.clear(); sync(); render(); }; wrap.appendChild(allChip);
  var chipEls={};
  Object.keys(labels).forEach(function(k){
    var c=document.createElement('button'); c.className='chip'; c.textContent=labels[k];
    c.onclick=function(){ if(sel.has(k)) sel.delete(k); else sel.add(k); sync(); render(); };
    chipEls[k]=c; wrap.appendChild(c);
  });
  function sync(){ allChip.classList.toggle('on', sel.size===0);
    Object.keys(chipEls).forEach(function(k){ chipEls[k].classList.toggle('on', sel.has(k)); }); }
  function median(a){ if(!a.length) return null; a=a.slice().sort(function(x,y){return x-y;});
    var m=Math.floor(a.length/2); return a.length%2? a[m] : (a[m-1]+a[m])/2; }
  function fmt(v){ return v==null?'–':Math.round(v).toLocaleString('da-DK'); }
  function tile(l,v,u){ return '<div class="kpi"><div class="kpi-label">'+l+'</div><div class="kpi-value">'+
    v+'<span class="unit">'+(u||'')+'</span></div></div>'; }
  function render(){
    var ty=$('sf-type').value, rm=$('sf-rooms').value,
        smin=parseFloat($('sf-smin').value), smax=parseFloat($('sf-smax').value),
        st=$('sf-street').value.trim().toLowerCase(), sort=$('sf-sort').value,
        starOnly=$('sf-star').checked;
    var f=items.filter(function(x){
      if(sel.size && !sel.has(x.d)) return false;
      if(ty && x.pt!==ty) return false;
      if(rm==='5+'){ if(!(x.r>=5)) return false; } else if(rm){ if(x.r!=+rm) return false; }
      if(!isNaN(smin) && (x.s==null||x.s<smin)) return false;
      if(!isNaN(smax) && (x.s==null||x.s>smax)) return false;
      if(st && x.st.toLowerCase().indexOf(st)<0) return false;
      if(starOnly && !window.CPHStars.has(keyOf(x))) return false;
      return true;
    });
    var sp=f.map(function(x){return x.sp;}), pr=f.map(function(x){return x.p;}),
        ch=f.filter(function(x){return x.ch!=null;}).map(function(x){return x.ch;});
    $('sf-stats').innerHTML = tile('Sales', f.length.toLocaleString('da-DK'),'') +
      tile('Median price', fmt(median(pr)),' DKK') + tile('Median DKK/m²', fmt(median(sp)),'') +
      tile('Median vs ask', ch.length? median(ch).toFixed(1)+'%':'–','');
    if(sort==='sp-desc') f.sort(function(a,b){return b.sp-a.sp;});
    else if(sort==='sp-asc') f.sort(function(a,b){return a.sp-b.sp;});
    else f.sort(function(a,b){return (b.dt||'').localeCompare(a.dt||'');});
    var top=f.map(function(x){
      var addr=(x.st||'').replace(/</g,'');
      var gq=encodeURIComponent((x.st||'')+', '+(x.z||'')+' København');
      var glink='https://www.google.com/search?q='+gq;
      var direct = x.au ? x.au : (x.u ? 'https://www.boliga.dk/bolig/'+x.u : null);
      var a = direct
        ? '<a target="_blank" rel="noopener" href="'+direct+'" title="Listing with photos">📷 '+(addr||'listing')+'</a>'
        : '<a target="_blank" rel="noopener" href="'+glink+'" title="Search this address">'+(addr||'–')+'</a>';
      var k=keyOf(x), on=window.CPHStars.has(k);
      var star='<button class="star'+(on?' on':'')+'" data-k="'+k+'" title="Save">'+(on?'★':'☆')+'</button>';
      return '<tr><td>'+star+'</td><td>'+(x.dt||'–')+'</td><td>'+(labels[x.d]||'Other')+'</td><td>'+a+
        '</td><td class="num">'+(x.s||'–')+'</td><td class="num">'+(x.r||'–')+'</td><td class="num">'+
        fmt(x.p)+'</td><td class="num">'+fmt(x.sp)+'</td><td class="num">'+(x.ch!=null? x.ch.toFixed(1)+'%':'–')+'</td></tr>';
    }).join('');
    $('sf-table').getElementsByTagName('tbody')[0].innerHTML=top;
    $('sf-more').textContent = f.length.toLocaleString('da-DK')+' sale'+(f.length===1?'':'s')+' shown — scroll the table to see all.';
  }
  function debounce(fn,ms){var t;return function(){clearTimeout(t);t=setTimeout(fn,ms);};}
  ['sf-type','sf-rooms','sf-smin','sf-smax','sf-sort','sf-star'].forEach(function(id){ $(id).addEventListener('input',render); });
  $('sf-street').addEventListener('input', debounce(render,160));
  var itemByKey={}; items.forEach(function(x){ itemByKey[keyOf(x)]=x; });
  $('sf-table').addEventListener('click', function(e){
    var b=e.target.closest && e.target.closest('button.star[data-k]');
    if(!b) return;
    var k=b.getAttribute('data-k'), x=itemByKey[k];
    window.CPHStars.toggle(k, x?saveData(x):{t:'sold'});
  });
  window.CPHStars.onChange(render);
  render();
})();
</script>
"""


SAVED_HTML = """
<section id="saved-panel" class="card saved">
  <figcaption><h3>⭐ Saved listings (<span id="saved-count">0</span>) · <span id="saved-sold">0</span> sold</h3>
  <span class="sub">Starred on this device. Each one is auto-matched against the sold archive —
  when it sells, it's flagged <strong>SOLD</strong> with the price it went for vs. the asking you
  saved. <button id="saved-clear" class="linkbtn">Clear all</button></span></figcaption>
  <p id="saved-empty" class="empty">Nothing saved yet. Tap the ☆ on any listing in
  <strong>For sale</strong> or <strong>Sold</strong> and it shows up here — then we track what it
  eventually sells for versus the asking you saved.</p>
  <div class="table-wrap"><table id="saved-table"><thead><tr>
    <th></th><th>Area</th><th>Address</th><th class="num">m²</th><th class="num">Your asking</th>
    <th class="num">Sold for</th><th class="num">Δ vs ask</th><th>Status</th>
  </tr></thead><tbody></tbody></table></div>
  <p class="methodology">Matched by address against the weekly sold archive, so a sale shows up here
  within a week or two of registering (land-registry lag). “Your asking” is the price captured the
  moment you starred it; “Sold for” is the realised price; “Δ vs ask” is how far below (−) or above
  the asking it actually sold. Stars live in <strong>this browser</strong> only.</p>
</section>
"""

# Tab navigation: show one panel at a time, remember the choice in the URL hash so a
# shared/reopened link lands on the same tab. Default tab is "For sale".
TABS_JS = """
<script>
(function(){
  var valid={'for-sale':1,'map':1,'sold':1,'saved':1,'market':1}, def='for-sale';
  var btns=[].slice.call(document.querySelectorAll('.tab-btn'));
  var panels=[].slice.call(document.querySelectorAll('.tabpanel'));
  function show(name){
    if(!valid[name]) name=def;
    btns.forEach(function(b){ b.classList.toggle('on', b.getAttribute('data-tab')===name); });
    panels.forEach(function(p){ p.classList.toggle('on', p.id==='tab-'+name); });
    // the map is built lazily the first time its tab is opened, and needs a resize nudge
    // because Leaflet can't measure a hidden container.
    if(name==='map' && window.CPHMap) { try{ window.CPHMap.onShow(); }catch(e){} }
  }
  btns.forEach(function(b){ b.addEventListener('click', function(){
    var n=b.getAttribute('data-tab');
    try{ history.replaceState(null,'','#'+n); }catch(e){ location.hash=n; }
    show(n); window.scrollTo(0,0);
  }); });
  window.addEventListener('hashchange', function(){ show((location.hash||'').replace('#','')); });
  show((location.hash||'').replace('#','') || def);
})();
</script>
"""

# Shared "star / save" module (browser localStorage) + the saved-panel renderer.
# Loaded before the section scripts so window.CPHStars exists when they run.
STARS_JS = """
<script>
window.CPHStars=(function(){
  var K='cphStars_v1', store={};
  try{ store=JSON.parse(localStorage.getItem(K)||'{}')||{}; }catch(e){ store={}; }
  var cbs=[];
  function persist(){ try{ localStorage.setItem(K, JSON.stringify(store)); }catch(e){} }
  function fire(){ cbs.forEach(function(c){ try{c();}catch(e){} }); }
  return {
    has:function(k){ return !!store[k]; },
    toggle:function(k,d){ if(store[k]) delete store[k]; else store[k]=Object.assign({at:Date.now()},d); persist(); fire(); },
    remove:function(k){ delete store[k]; persist(); fire(); },
    clear:function(){ store={}; persist(); fire(); },
    all:function(){ return store; },
    count:function(){ return Object.keys(store).length; },
    onChange:function(cb){ cbs.push(cb); }
  };
})();
(function(){
  var labels=(window.__EXPLORE__&&window.__EXPLORE__.labels)||{};
  var $=function(id){return document.getElementById(id);};
  function fmt(v){ return v==null?'–':Math.round(v).toLocaleString('da-DK'); }
  function norm(s){ return (s||'').toLowerCase().replace(/\\s+/g,' ').trim(); }
  function link(d){
    var addr=(d.a||'').replace(/</g,'');
    var href = d.au ? d.au : (d.u? 'https://www.boliga.dk/bolig/'+d.u
      : ('https://www.google.com/search?q='+encodeURIComponent((d.a||'')+', '+(d.z||'')+' København')));
    return '<a target="_blank" rel="noopener" href="'+href+'">'+(addr||'listing')+'</a>';
  }
  // index the embedded sold archive by address (and id) so a saved listing can be
  // matched to its realised sale entirely in the browser.
  var soldByAddr={}, soldById={};
  var soldItems=(window.__SOLD__&&window.__SOLD__.items)||[];
  soldItems.forEach(function(s){
    var a=norm(s.st); if(a && !soldByAddr[a]) soldByAddr[a]=s;
    if(s.u) soldById[s.u]=s;
  });
  function matchSold(d){
    if(d.u && soldById[d.u]) return soldById[d.u];
    var a=norm(d.a); return a? soldByAddr[a] : null;
  }
  function render(){
    var panel=$('saved-panel'); if(!panel) return;
    var st=window.CPHStars.all(), keys=Object.keys(st);
    $('saved-count').textContent=keys.length;
    // Saved now lives in its own tab, so show an empty-state instead of hiding the panel.
    var empty=$('saved-empty'), wrapEl=panel.querySelector('.table-wrap');
    if(empty) empty.style.display = keys.length? 'none':'block';
    if(wrapEl) wrapEl.style.display = keys.length? '':'none';
    var badge=document.getElementById('tab-saved-count');
    if(badge) badge.textContent = keys.length? keys.length : '';
    keys.sort(function(a,b){return (st[b].at||0)-(st[a].at||0);});
    var soldN=0;
    var html=keys.map(function(k){
      var d=st[k];
      // a saved sold-record is already a realised sale; a saved listing we try to match
      var isSold = d.t==='sold', m = isSold? d : matchSold(d);
      var ask = isSold? null : d.p;              // price captured when starred
      var soldFor = m? m.p : null;
      var when = m? (m.dt||'') : '';
      var delta=null;
      if(soldFor!=null && ask) delta=(soldFor-ask)/ask*100;
      if(m) soldN++;
      var dStr = delta==null? '–' : (delta>0?'+':'')+delta.toFixed(1)+'%';
      var dCls = delta==null? '' : (delta<0?'gap-lo':'gap-hi');
      var status = m
        ? '<span class="soldbadge">SOLD'+(when?' '+when:'')+'</span>'
        : '<span class="pending">listed / watching</span>';
      return '<tr><td><button class="star on" data-sk="'+k+'" title="Remove">★</button></td>'+
        '<td>'+(labels[d.d]||'–')+'</td><td>'+link(d)+'</td>'+
        '<td class="num">'+(d.s||'–')+'</td>'+
        '<td class="num">'+fmt(ask)+'</td>'+
        '<td class="num">'+fmt(soldFor)+'</td>'+
        '<td class="num '+dCls+'">'+dStr+'</td>'+
        '<td>'+status+'</td></tr>';
    }).join('');
    $('saved-table').getElementsByTagName('tbody')[0].innerHTML=html;
    $('saved-sold').textContent=soldN;
  }
  document.addEventListener('click', function(e){
    var b=e.target.closest && e.target.closest('button[data-sk]');
    if(b){ window.CPHStars.remove(b.getAttribute('data-sk')); }
  });
  var clr=$('saved-clear'); if(clr) clr.onclick=function(){
    if(confirm('Remove all saved listings?')) window.CPHStars.clear();
  };
  window.CPHStars.onChange(render);
  render();
})();
</script>
"""


MAP_HTML = """
<section class="explore card">
  <figcaption><h3>Map of current listings</h3>
  <span class="sub">Plot listings by area and filter to a viewing day — handy for planning a route
  between open houses. Loads a map from the internet; if that fails, the rest of the app still works.</span></figcaption>
  <div class="areas"><span class="areas-lbl">Areas</span><div id="map-dist-chips" class="chips"></div></div>
  <div class="filters">
    <label>Open house<select id="map-oh"><option value="">Any</option>
      <option value="any">Has a showing</option></select></label>
    <label>Rooms<select id="map-rooms">
      <option value="">Any</option><option>1</option><option>2</option><option>3</option>
      <option>4</option><option value="5+">5+</option></select></label>
    <label class="chk"><input type="checkbox" id="map-star"> ⭐ Starred only</label>
  </div>
  <div class="map-legend">
    <span><i style="background:#eb6834"></i>Showing today</span>
    <span><i style="background:#2a78d6"></i>Upcoming showing</span>
    <span><i style="background:#9a9a94"></i>No showing date</span>
  </div>
  <div id="map-stats" class="more"></div>
  <div id="map" class="mapbox"></div>
  <p id="map-fallback" class="empty map-fallback" hidden></p>
  <p class="methodology">Pins come straight from Boliga's coordinates (every listing has them). Colour
  shows whether a public showing is booked. Click a pin for the address, price, showing time, a
  <strong>📅</strong> add-to-calendar link and the listing. The map is the only part of the app that
  loads anything from the internet — if it can't (no connection, or blocked), you'll see a notice here
  and every other tab keeps working.</p>
</section>
"""

# Map tab: Leaflet + OpenStreetMap tiles, built lazily on first open and fully isolated —
# if Leaflet fails to load or anything throws, we show a fallback notice and the rest of the
# app is untouched. Canvas-rendered circle markers (no icon images) keep ~2.5k pins smooth.
MAP_JS = """
<script>
window.CPHMap=(function(){
  var built=false, map=null, layer=null, warned=false;
  var DATA=window.__EXPLORE__||{items:[],labels:{}};
  var items=DATA.items, labels=DATA.labels;
  var $=function(id){return document.getElementById(id);};
  var sel=new Set();
  function todayStr(){ return new Date().toISOString().slice(0,10); }
  function pad2(n){ return (n<10?'0':'')+n; }
  function gcal(x){
    if(!x.oh) return null;
    var t=(x.oht && /^\\d{2}:\\d{2}$/.test(x.oht)) ? x.oht : '11:00';
    var hh=parseInt(t.slice(0,2),10), mm=t.slice(3,5), ds=x.oh.replace(/-/g,'');
    var start=ds+'T'+pad2(hh)+mm+'00', end=hh>=23?ds+'T235900':ds+'T'+pad2(hh+1)+mm+'00';
    var href=x.au?x.au:(x.u?'https://www.boliga.dk/bolig/'+x.u:'');
    return 'https://calendar.google.com/calendar/render?action=TEMPLATE'+
      '&text='+encodeURIComponent('Viewing: '+(x.st||'listing'))+
      '&dates='+start+'/'+end+'&ctz=Europe/Copenhagen'+
      '&location='+encodeURIComponent((x.st||'')+', '+(x.z||'')+' København')+
      '&details='+encodeURIComponent('Open house / åbent hus.\\n'+(href?('Listing: '+href+'\\n'):'')+
        '\\n(Time as Boliga lists it — confirm on the listing.)');
  }
  function keyOf(x){ return 'L'+(x.u || (x.st+'_'+x.z)); }
  function fmt(v){ return v==null?'–':Math.round(v).toLocaleString('da-DK'); }
  function color(x){
    if(!x.oh) return '#9a9a94';
    return x.oh===todayStr() ? '#eb6834' : (x.oh>=todayStr() ? '#2a78d6' : '#9a9a94');
  }
  function fallback(msg){
    var el=$('map-fallback'); if(el){ el.hidden=false;
      el.innerHTML='🗺️ '+(msg||'The map could not load.')+' It needs a live connection and pulls a '+
        'map library + tiles from the internet (the only part of this app that does). Everything else '+
        'works — <button class="linkbtn" onclick="location.hash=\\'for-sale\\'">browse in For sale</button> '+
        'and use the area + open-house filters there.'; }
    var m=$('map'); if(m) m.style.display='none';
  }
  function popup(x){
    var addr=(x.st||'listing').replace(/</g,'');
    var href=x.au?x.au:(x.u?'https://www.boliga.dk/bolig/'+x.u:null);
    var title=href?('<a target="_blank" rel="noopener" href="'+href+'">'+addr+'</a>'):addr;
    var oh = x.oh ? ('<br><b>Open house:</b> '+x.oh+(x.oht?' '+x.oht:'')+
       (gcal(x)&&x.oh>=todayStr()?' <a target="_blank" rel="noopener" href="'+gcal(x)+'" title="Add to Google Calendar">📅</a>':'')) : '';
    return '<b>'+title+'</b><br>'+(labels[x.d]||'')+' · '+(x.z||'')+
      '<br>'+fmt(x.p)+' DKK · '+(x.s||'–')+' m² · '+(x.r||'–')+' rm · '+fmt(x.sp)+' /m²'+oh;
  }
  function render(){
    if(!layer) return;
    layer.clearLayers();
    var ohf=$('map-oh').value, rm=$('map-rooms').value, starOnly=$('map-star').checked;
    var shown=0;
    items.forEach(function(x){
      if(x.la==null||x.lo==null) return;
      if(sel.size && !sel.has(x.d)) return;
      if(rm==='5+'){ if(!(x.r>=5)) return; } else if(rm){ if(x.r!=+rm) return; }
      if(ohf==='any'){ if(!x.oh) return; } else if(ohf){ if(x.oh!==ohf) return; }
      if(starOnly && !window.CPHStars.has(keyOf(x))) return;
      var m=L.circleMarker([x.la,x.lo],{radius:6,weight:1,color:'#fff',fillColor:color(x),fillOpacity:0.85});
      m.bindPopup(popup(x)); layer.addLayer(m); shown++;
    });
    $('map-stats').textContent=shown.toLocaleString('da-DK')+' listing'+(shown===1?'':'s')+' on the map.';
  }
  function build(){
    map=L.map('map',{preferCanvas:true,scrollWheelZoom:true}).setView([55.682,12.57],12);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
      maxZoom:19, attribution:'&copy; OpenStreetMap'
    }).addTo(map).on('tileerror', function(){
      if(!warned){ warned=true; var s=$('map-stats');
        if(s) s.textContent+='  (map tiles are slow or unavailable right now.)'; }
    });
    layer=L.layerGroup().addTo(map);
    var wrap=$('map-dist-chips');
    var allChip=document.createElement('button'); allChip.className='chip all on'; allChip.textContent='All areas';
    allChip.onclick=function(){ sel.clear(); syncChips(); render(); }; wrap.appendChild(allChip);
    var chipEls={};
    Object.keys(labels).forEach(function(k){
      var c=document.createElement('button'); c.className='chip'; c.textContent=labels[k];
      c.onclick=function(){ if(sel.has(k)) sel.delete(k); else sel.add(k); syncChips(); render(); };
      chipEls[k]=c; wrap.appendChild(c);
    });
    function syncChips(){ allChip.classList.toggle('on', sel.size===0);
      Object.keys(chipEls).forEach(function(k){ chipEls[k].classList.toggle('on', sel.has(k)); }); }
    var counts={}, t=todayStr();
    items.forEach(function(x){ if(x.oh && x.oh>=t) counts[x.oh]=(counts[x.oh]||0)+1; });
    Object.keys(counts).sort().forEach(function(d){
      var o=document.createElement('option'); o.value=d;
      var lbl=d; try{ lbl=new Date(d+'T00:00:00').toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short'}); }catch(e){}
      o.textContent=lbl+' ('+counts[d]+')'; $('map-oh').appendChild(o);
    });
    ['map-oh','map-rooms','map-star'].forEach(function(id){ $(id).addEventListener('input',render); });
    window.CPHStars.onChange(render);
    render();
  }
  function whenLeaflet(cb,tries){
    if(typeof L!=='undefined' && L.map) return cb(true);
    if(tries<=0) return cb(false);
    setTimeout(function(){ whenLeaflet(cb,tries-1); }, 300);
  }
  function onShow(){
    if(built){ if(map) setTimeout(function(){ map.invalidateSize(); },60); return; }
    built=true;
    whenLeaflet(function(ok){
      if(!ok){ fallback('The map library did not load.'); return; }
      try{ build(); setTimeout(function(){ map.invalidateSize(); },60); }
      catch(e){ fallback('Something went wrong setting up the map.'); }
    }, 25);
  }
  return { onShow:onShow };
})();
</script>
"""


def build_html(rows, active, sold_hist, cfg, generated) -> str:
    ptype_series = [_series(rows, seg, "median_sqm_price", lbl, slot) for seg, (lbl, slot) in PTYPE.items()]
    trend = [
        line_chart("Asking price per m²", "Median DKK, by property type",
                   ptype_series, "dkk", "price"),
        line_chart("Asking price per m² by district", "Median DKK — what sellers want, by area",
                   _district_series(rows, cfg, "median_sqm_price"), "dkk", "price-dist"),
        line_chart("Sold price per m² by district", "Median DKK — realised going rate, by area",
                   _district_series(rows, cfg, "median_sold_sqm_price"), "dkk", "sold-dist"),
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
    sold_pl = json.dumps(sold_payload(sold_hist or [], cfg)).replace("</", "<\\/")
    n_sold = len(sold_hist or [])

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f9f9f7" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#0d0d0d" media="(prefers-color-scheme: dark)">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="CPH Housing">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<title>Copenhagen Housing Monitor</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.css">
<script defer src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.js"></script>
<style>{CSS}</style></head>
<body><div class="wrap">
<header><h1>Copenhagen Housing Monitor</h1>
<p>Live-listing indicators for <strong>{html.escape(cfg['scope']['name'])}</strong>, snapshotted weekly
from Boliga. Asking prices, cuts and days-on-market are <em>leading</em> indicators; realised
sold prices are the lagging ground truth.</p>
<div class="asof">Generated {generated.isoformat()} · {len(snaps)} snapshot(s) · {span}</div></header>
<nav class="tabs" role="tablist">
  <button class="tab-btn" data-tab="for-sale" role="tab">For sale</button>
  <button class="tab-btn" data-tab="map" role="tab">Map</button>
  <button class="tab-btn" data-tab="sold" role="tab">Sold</button>
  <button class="tab-btn" data-tab="saved" role="tab">Saved <span id="tab-saved-count" class="tabcount"></span></button>
  <button class="tab-btn" data-tab="market" role="tab">Market</button>
</nav>

<section class="tabpanel" id="tab-for-sale" role="tabpanel">
<h2 class="section">Explore the current market</h2>
{EXPLORE_HTML}
</section>

<section class="tabpanel" id="tab-map" role="tabpanel">
<h2 class="section">Map — listings &amp; viewings</h2>
{MAP_HTML}
</section>

<section class="tabpanel" id="tab-sold" role="tabpanel">
<h2 class="section">Sold prices — {n_sold:,} archived sales</h2>
{SOLD_HTML}
</section>

<section class="tabpanel" id="tab-saved" role="tabpanel">
<h2 class="section">Saved &amp; tracked</h2>
{SAVED_HTML}
</section>

<section class="tabpanel" id="tab-market" role="tabpanel">
<h2 class="section">Market snapshot</h2>
{kpi_tiles(rows)}
<div class="callout"><strong>Asking vs. sold — the key distinction.</strong>
<b>Asking</b> = what sellers list live listings at (leading, updates weekly).
<b>Sold (realised)</b> = what homes actually changed hands for, from the land registry
(lagging ~1–3 months). Asking normally sits a few % above sold. For "going rates in a
neighbourhood", read the <b>sold</b> column.</div>
{going_rates_table(rows, cfg)}
<h2 class="section">Market direction (weekly trend)</h2>
<div class="grid-charts">{''.join(trend)}</div>
<div class="note"><strong>Read this before trusting a trend.</strong> Asking prices are what sellers
<em>want</em>, not what they get; realised sold prices lag ~1-3 months. District tags are by postcode
(approximate). The source (Boliga) is an undocumented scrape that can drift. A single snapshot shows no
direction — several consistent weeks do. Cross-check quarterly against official Finans Danmark / Danmarks
Statistik figures before any decision that matters.</div>
</section>
</div>
<script>window.__EXPLORE__ = {payload};</script>
<script>window.__SOLD__ = {sold_pl};</script>
{TABS_JS}
{STARS_JS}
{EXPLORE_JS}
{SOLD_JS}
{MAP_JS}
</body></html>
"""


def ptype_series_field(rows, field):
    return [_series(rows, seg, field, lbl, slot) for seg, (lbl, slot) in PTYPE.items()]


def write_dashboard(rows, active, sold_hist, cfg, out_path: Path, generated: date | None = None) -> Path:
    generated = generated or date.today()
    out_path.write_text(build_html(rows, active or [], sold_hist or [], cfg, generated), encoding="utf-8")
    log.info("wrote dashboard: %s", out_path)
    return out_path
