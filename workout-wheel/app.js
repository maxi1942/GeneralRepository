import { SHEETS_API_URL } from './config.js';
import {
  RULES, computePoints, toDateStr, addDays, weekStart, monthKey, monthLabel, shortDate, isBackdated,
} from './rules.js';
import { Wheel, pickWeighted } from './wheel.js';

const DEMO = new URLSearchParams(location.search).has('demo');
const CONFIGURED = SHEETS_API_URL.startsWith('https://script.google.com/');
const PLAYER_COLORS = [['var(--p0)', 'var(--p0b)'], ['var(--p1)', 'var(--p1b)']];

// ── Small helpers ────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const today = () => toDateStr(new Date());
const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
const fmtDay = (str) => `${DOW[new Date(`${str}T12:00:00`).getDay()]} ${shortDate(str)}`;
const fmtStamp = (iso) => {
  const d = new Date(iso);
  return `${shortDate(toDateStr(d))} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};
const pts = (n) => `${n} pt${Math.abs(n) === 1 ? '' : 's'}`;
function toast(msg) {
  const t = document.createElement('div');
  t.className = 'toast'; t.textContent = msg;
  document.body.append(t);
  setTimeout(() => t.remove(), 2600);
}

// ── Data layer: Google Sheets (via Apps Script), or an in-memory demo ────────
// Every write returns the full fresh state, so each action is one round trip.
function makeApi() {
  if (DEMO) return demoApi();
  const KEY = 'workout-wheel-auth';
  let mem = null;
  const store = {
    get() { try { return JSON.parse(localStorage.getItem(KEY)) ?? mem; } catch { return mem; } },
    set(v) { mem = v; try { localStorage.setItem(KEY, JSON.stringify(v)); } catch { /* private mode */ } },
    clear() { mem = null; try { localStorage.removeItem(KEY); } catch { /* ignore */ } },
  };
  let auth = store.get();
  async function call(action, payload = {}) {
    // No custom headers → a "simple" request, which Apps Script accepts cross-site.
    const res = await fetch(SHEETS_API_URL, {
      method: 'POST', body: JSON.stringify({ action, passcode: auth?.passcode, ...payload }),
    });
    if (!res.ok) throw new Error(`Server error (${res.status})`);
    const data = await res.json();
    if (data.error === 'BAD_PASSCODE') {
      if (action !== 'login') { store.clear(); location.reload(); }
      throw new Error('Wrong passcode');
    }
    if (data.error) throw new Error(data.error);
    return data;
  }
  const toBase64 = (blob) => new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(String(r.result).split(',')[1]);
    r.onerror = rej;
    r.readAsDataURL(blob);
  });
  return {
    async user() { return auth?.me ?? null; },
    async signIn(passcode) {
      auth = { passcode: passcode.trim() };
      const { me } = await call('login');
      auth.me = me;
      store.set(auth);
    },
    async signOut() { store.clear(); },
    loadAll: () => call('load'),
    async addWorkout(row, photo) {
      return call('addWorkout', photo ? { ...row, photo: await toBase64(photo), photo_mime: photo.type } : row);
    },
    deleteWorkout: (id) => call('deleteWorkout', { id }),
    addPrize: (row) => call('addPrize', row),
    updatePrize: (id, patch) => call('updatePrize', { id, ...patch }),
    addSpin: (row) => call('addSpin', row),
    setUsed: (id, used) => call('setUsed', { id, used }),
    async setAvatar(photo) { return call('setAvatar', { photo: await toBase64(photo), photo_mime: photo.type }); },
    photoUrl: (id, big) => `https://drive.google.com/thumbnail?id=${encodeURIComponent(id)}&sz=w${big ? 1600 : 400}`,
  };
}

function demoApi() {
  const me = { id: 'demo-me', name: 'Alex' };
  const db = {
    profiles: [{ ...me, created_at: '2026-01-01' }, { id: 'demo-partner', name: 'Sam', created_at: '2026-01-02' }],
    workouts: [], spins: [],
    prizes: [['Breakfast in bed', '🥐', 2], ['Massage (30 min)', '💆', 2], ['Pick the movie', '🎬', 3],
      ['Skip a chore', '🧹', 3], ['Dinner out – your choice', '🍝', 1]]
      .map(([name, emoji, weight], i) => ({ id: `p${i}`, name, emoji, weight, active: true, created_at: '2026-01-01' })),
  };
  // ~7 weeks of history: you ≈ 3×/week, partner ≈ 2.5×/week.
  const t = today();
  let id = 0;
  const add = (user_id, date, activity, extra = {}) => db.workouts.push({
    id: `w${++id}`, user_id, workout_date: date, logged_at: `${date}T18:${String(id % 60).padStart(2, '0')}:00`,
    activity, note: null, photo_path: null, deleted_at: null, ...extra,
  });
  for (let d = 49; d >= 1; d--) {
    const date = addDays(t, -d);
    const dow = new Date(`${date}T12:00:00`).getDay();
    if ([1, 3, 5].includes(dow)) add('demo-me', date, ['Gym', 'Run', 'Class'][dow % 3]);
    if ([2, 4].includes(dow) || (dow === 6 && d % 14 < 7)) add('demo-partner', date, ['Yoga', 'Run', 'Swim'][dow % 3]);
  }
  add('demo-partner', addDays(t, -3), 'Walk', { logged_at: `${addDays(t, -1)}T21:10:00`, note: 'Forgot to log this one' });
  db.spins.push({ id: 's1', user_id: 'demo-me', prize_id: 'p2', prize_name: 'Pick the movie', prize_emoji: '🎬', cost: 12, spun_at: `${addDays(t, -10)}T20:00:00`, used_at: null });
  const now = () => new Date().toISOString();
  return {
    async user() { return me; },
    async signIn() {}, async signOut() { location.href = location.pathname; },
    async loadAll() { return structuredClone(db); },
    async addWorkout(row, photo) {
      db.workouts.push({ id: `w${++id}`, user_id: me.id, logged_at: now(), deleted_at: null, ...row,
        photo_path: photo ? URL.createObjectURL(photo) : null });
    },
    async deleteWorkout(wid) { db.workouts.find((w) => w.id === wid).deleted_at = now(); },
    async addPrize(row) { db.prizes.push({ id: `p${++id}`, active: true, created_at: now(), ...row }); },
    async updatePrize(pid, patch) { Object.assign(db.prizes.find((p) => p.id === pid), patch); },
    async addSpin(row) { db.spins.push({ id: `s${++id}`, user_id: me.id, spun_at: now(), used_at: null, ...row }); },
    async setUsed(sid, used) { db.spins.find((s) => s.id === sid).used_at = used ? now() : null; },
    async setAvatar(photo) { db.profiles.find((p) => p.id === me.id).avatar = URL.createObjectURL(photo); },
    photoUrl: (path) => path,
  };
}

// ── App state ────────────────────────────────────────────────────────────────
let api;
const S = { me: null, profiles: [], workouts: [], spins: [], prizes: [], pts: null, tab: 'home', ledgerUser: null };
const view = $('#view');

function player(uid) { return S.profiles.find((p) => p.id === uid) ?? { id: uid, name: '?' }; }
// CSS variables for a player's two-tone colour, used as style="${pc(uid)}".
function pc(uid) {
  const [a, b] = PLAYER_COLORS[Math.max(0, S.profiles.findIndex((p) => p.id === uid)) % 2];
  return `--pc:${a};--pcb:${b};`;
}
function avatar(p, size = 36) {
  const url = p.avatar ? api.photoUrl(p.avatar) : null;
  return `<span class="avatar" style="${pc(p.id)}width:${size}px;height:${size}px;font-size:${Math.round(size * 0.42)}px">${
    url ? `<img src="${esc(url)}" alt="${esc(p.name)}">` : esc((p.name || '?')[0].toUpperCase())}</span>`;
}
function orderedPlayers() { return [...S.profiles].sort((a, b) => (a.id === S.me.id ? -1 : b.id === S.me.id ? 1 : 0)); }

// Pass the state a write returned to skip a second round trip; otherwise fetch it.
async function reload(data) {
  if (!data?.workouts) data = await api.loadAll();
  Object.assign(S, data);
  S.pts = computePoints({ players: S.profiles, workouts: S.workouts, spins: S.spins, today: today() });
  render();
}

// ── Boot / auth ─────────────────────────────────────────────────────────────
async function boot() {
  if (!DEMO && !CONFIGURED) return renderSetupNeeded();
  api = makeApi();
  const user = await api.user();
  if (!user) return renderLogin();
  S.me = user;
  const data = await api.loadAll();
  const mine = data.profiles.find((p) => p.id === user.id);
  if (!mine) { await api.signOut(); return renderLogin('Your player was not found in the sheet. Sign in again.'); }
  S.me = mine;
  $('#logout').onclick = async () => { await api.signOut(); location.reload(); };
  $('#tabs').hidden = false;
  await reload(data);
}

function renderSetupNeeded() {
  view.innerHTML = `<div class="card"><h3>Almost there 👋</h3>
    <p>The app isn't connected to your Google Sheet yet. Follow the steps in <b>workout-wheel/README.md</b>
    and paste your web app URL into <b>config.js</b>.</p>
    <p><a class="btn primary" href="?demo">Try the demo instead</a></p></div>`;
}

function renderLogin(msg = '') {
  view.innerHTML = `<div class="card"><form id="login"><h2>Sign in</h2>
    <p class="muted small">Use your personal passcode from the <b>Players</b> tab of the Google Sheet. You only need to do this once per phone.</p>
    <label>Passcode<input type="password" name="passcode" required autocomplete="current-password"></label>
    <p class="err" id="login-err">${esc(msg)}</p>
    <button class="btn primary block" id="login-btn">Sign in</button></form></div>`;
  $('#login').onsubmit = async (e) => {
    e.preventDefault();
    $('#login-btn').disabled = true;
    try { await api.signIn(new FormData(e.target).get('passcode')); location.reload(); }
    catch (err) { $('#login-err').textContent = err.message; $('#login-btn').disabled = false; }
  };
}

// ── Rendering ────────────────────────────────────────────────────────────────
function render() {
  S.me = S.profiles.find((p) => p.id === S.me.id) ?? S.me;
  renderHeader();
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === S.tab));
  ({ home: renderHome, history: renderHistory, spin: renderSpin, prizes: renderPrizes, points: renderPoints })[S.tab]();
}

function countedDays(uid) {
  return new Set(S.workouts.filter((w) => w.user_id === uid && S.pts.counted.get(w.id)).map((w) => w.workout_date));
}

function renderHeader() {
  $('#who').innerHTML = `${DEMO ? '<span class="chip">demo</span>' : ''}
    <button class="me-btn" data-action="profile" aria-label="Your profile">${avatar(S.me, 38)}</button>`;
}

// Workouts that earn points (max 1/day), per player, within [from, to] (inclusive dates).
function workoutCount(uid, from = '0000-00-00', to = '9999-99-99') {
  return [...countedDays(uid)].filter((d) => d >= from && d <= to).length;
}

// Consecutive Mon–Sun weeks with 3+ workouts, counting back from this week (or last week if this one isn't done yet).
function weekStreak(uid) {
  const perWeek = new Map();
  for (const d of countedDays(uid)) perWeek.set(weekStart(d), (perWeek.get(weekStart(d)) ?? 0) + 1);
  const active = (m) => (perWeek.get(m) ?? 0) >= RULES.activeWeekThreshold;
  let m = weekStart(today());
  if (!active(m)) m = addDays(m, -7);
  let n = 0;
  while (active(m)) { n++; m = addDays(m, -7); }
  return n;
}

const PERIODS = {
  week: { label: 'Week', range: (t) => [weekStart(t), t], caption: 'this week' },
  month: { label: 'Month', range: (t) => [`${monthKey(t)}-01`, t], caption: 'this month' },
  year: { label: 'Year', range: (t) => [`${t.slice(0, 4)}-01-01`, t], caption: 'this year' },
  all: { label: 'All time', range: (t) => ['0000-00-00', t], caption: 'all time' },
};

function renderLeaderboard() {
  const t = today();
  const period = PERIODS[S.lbPeriod] ?? PERIODS.month;
  const [from, to] = period.range(t);
  const rows = orderedPlayers().map((p) => ({ p, n: workoutCount(p.id, from, to), streak: weekStreak(p.id) }));
  const max = Math.max(1, ...rows.map((r) => r.n));
  const top = Math.max(...rows.map((r) => r.n));
  const leaders = rows.filter((r) => r.n === top && top > 0);

  const cols = rows.map(({ p, n }) => {
    const lead = top > 0 && n === top;
    const h = Math.max(36, Math.round((n / max) * 150));
    return `<div class="col ${lead ? 'lead' : ''}" style="${pc(p.id)}">
      <div class="crown ${lead ? '' : 'none'}">👑</div>
      ${avatar(p, 58)}
      <div class="pole" data-h="${h}">${n}</div>
      <div class="who-name">${esc(p.name)}</div>
    </div>`;
  }).join('');

  let caption;
  if (top === 0) caption = `No workouts ${period.caption} yet. First one takes the crown 👀`;
  else if (leaders.length > 1) caption = `🤝 Dead heat: ${top} each ${period.caption}`;
  else {
    const second = Math.max(0, ...rows.filter((r) => r !== leaders[0]).map((r) => r.n));
    const gap = top - second;
    caption = `${esc(leaders[0].p.name)} leads by ${gap} workout${gap === 1 ? '' : 's'} ${gap >= 4 ? '🚀' : gap >= 2 ? '🔥' : '😤'}`;
  }

  let note = '';
  if ((S.lbPeriod ?? 'month') === 'month') {
    const lastDay = addDays(`${monthKey(addDays(`${monthKey(t)}-28`, 7))}-01`, -1);
    const left = Math.round((new Date(`${lastDay}T12:00:00`) - new Date(`${t}T12:00:00`)) / 864e5);
    note = `<p class="muted small center" style="margin:2px 0 0">Month winner gets +${RULES.monthlyWinnerBonus} bonus point · ${left} day${left === 1 ? '' : 's'} left</p>`;
  }
  const streaks = rows.filter((r) => r.streak > 0)
    .map((r) => `<span class="chip fire">🔥 ${esc(r.p.name)}: ${r.streak}-week streak</span>`).join('');

  // Last 6 months, side-by-side bars.
  const months = [];
  for (let i = 5, mk = monthKey(t); i >= 0; i--) {
    let k = mk;
    for (let j = 0; j < i; j++) k = monthKey(addDays(`${k}-01`, -1));
    months.push(k);
  }
  const monthCounts = months.map((mk) => {
    const last = addDays(`${monthKey(addDays(`${mk}-28`, 7))}-01`, -1);
    return rows.map(({ p }) => ({ p, n: workoutCount(p.id, `${mk}-01`, last) }));
  });
  const mMax = Math.max(1, ...monthCounts.flat().map((x) => x.n));
  const monthHtml = months.map((mk, i) => {
    const c = monthCounts[i];
    const best = Math.max(...c.map((x) => x.n));
    const winners = best > 0 ? c.filter((x) => x.n === best) : [];
    const done = mk < monthKey(t);
    return `<div class="month">
      <div class="win">${done && winners.length === 1 ? avatar(winners[0].p, 16) : done && winners.length > 1 ? '🤝' : ''}</div>
      <div class="bars">${c.map(({ p, n }) => `<i style="${pc(p.id)}height:${Math.round((n / mMax) * 70)}px" title="${esc(p.name)}: ${n}"></i>`).join('')}</div>
      <div class="lbl">${monthLabel(mk).slice(0, 3)}</div></div>`;
  }).join('');

  return `<div class="card">
    <div class="lb-head"><h3 style="margin:0">🏆 Leaderboard</h3>
      <div class="pills">${Object.entries(PERIODS).map(([k, v]) =>
        `<button class="${k === (S.lbPeriod ?? 'month') ? 'on' : ''}" data-action="lb" data-p="${k}">${v.label}</button>`).join('')}</div></div>
    <div class="podium">${cols}</div>
    <div class="lb-caption">${caption}</div>
    ${note}
    ${streaks ? `<div class="streaks">${streaks}</div>` : ''}
    <h3 style="margin:22px 0 0">Last 6 months</h3>
    <div class="months">${monthHtml}</div>
    <div class="legend">${rows.map(({ p }) => `<span style="${pc(p.id)}"><i></i>${esc(p.name)}</span>`).join('')}</div>
  </div>`;
}

function renderHome() {
  const t = today();
  const monday = weekStart(t);
  const hour = new Date().getHours();
  const greet = hour < 12 ? 'Good morning' : hour < 18 ? 'Good afternoon' : 'Good evening';

  const cards = orderedPlayers().map((p) => {
    const ledger = S.pts.ledgers[p.id] ?? { balance: 0 };
    const days = countedDays(p.id);
    const weekN = [...days].filter((d) => weekStart(d) === monday).length;
    const spinsReady = Math.floor(Math.max(0, ledger.balance) / RULES.spinCost);
    const pct = spinsReady ? 100 : Math.max(0, (ledger.balance / RULES.spinCost) * 100);
    const dots = [0, 1, 2, 3, 4, 5, 6].map((i) => {
      const d = addDays(monday, i);
      return `<div class="dot ${days.has(d) ? 'on' : ''} ${d === t ? 'today' : ''}">${'MTWTFSS'[i]}</div>`;
    }).join('');
    return `<div class="card player" style="${pc(p.id)}" data-action="ledger" data-uid="${p.id}">
      <div class="row">${avatar(p, 30)}<span class="name grow">${esc(p.name)}</span></div>
      <div style="margin-top:12px"><span class="balance">${ledger.balance}</span> <span class="muted small">pts</span></div>
      <div class="bar"><i style="width:${Math.min(100, pct)}%"></i></div>
      <div class="small">${spinsReady
        ? `<span class="ready">🎉 ${spinsReady} spin${spinsReady > 1 ? 's' : ''} ready</span>`
        : `<span class="muted">${RULES.spinCost - ledger.balance} to next spin</span>`}</div>
      <div class="dots">${dots}</div>
      <div class="small muted" style="margin-top:6px">${weekN >= RULES.activeWeekThreshold
        ? '🔥 Active week!' : `${weekN}/${RULES.activeWeekThreshold} for week bonus`}</div>
    </div>`;
  }).join('');

  view.innerHTML = `
    <div class="hello">${greet}, ${esc(S.me.name)} 👋</div>
    <p class="muted" style="margin:0 0 14px">${fmtDay(t)} · keep the streak alive</p>
    <button class="btn primary block big" data-action="log">＋ Log a workout</button>
    <div class="players">${cards}</div>
    ${renderLeaderboard()}
    <p class="center"><button class="link" data-action="tab" data-tab="points">How do points work?</button></p>`;
  // Grow the bars after they're on screen.
  requestAnimationFrame(() => requestAnimationFrame(() => {
    document.querySelectorAll('.pole').forEach((el) => { el.style.height = `${el.dataset.h}px`; });
  }));
}

function renderHistory() {
  const events = [
    ...S.workouts.map((w) => ({ type: 'w', sort: `${w.workout_date}|${w.logged_at}`, w })),
    ...S.spins.map((s) => ({ type: 's', sort: `${toDateStr(new Date(s.spun_at))}|${s.spun_at}`, s })),
  ].sort((a, b) => b.sort.localeCompare(a.sort));

  const items = events.slice(0, 200).map((e) => {
    if (e.type === 's') {
      const s = e.s, p = player(s.user_id);
      return `<div class="item" style="${pc(p.id)}">${avatar(p)}
        <div class="grow"><b>${esc(p.name)}</b> spun the wheel ${esc(s.prize_emoji)}
          <div>Won <b>${esc(s.prize_name)}</b> <span class="minus">−${s.cost}</span></div>
          <div class="muted small">${fmtStamp(s.spun_at)}</div></div></div>`;
    }
    const w = e.w, p = player(w.user_id);
    const chips = [];
    if (isBackdated(w)) chips.push(`<span class="chip warn">⚑ Backdated – logged ${fmtStamp(w.logged_at)}</span>`);
    if (w.deleted_at) chips.push(`<span class="chip warn">🗑 Deleted ${fmtStamp(w.deleted_at)}</span>`);
    else if (!S.pts.counted.get(w.id)) chips.push('<span class="chip">2nd workout that day – 0 pts</span>');
    else chips.push(`<span class="chip good">+${RULES.pointsPerWorkout}</span>`);
    const url = w.photo_path && !w.deleted_at ? api.photoUrl(w.photo_path) : null;
    const canDelete = w.user_id === S.me.id && !w.deleted_at;
    return `<div class="item ${w.deleted_at ? 'deleted' : ''}" style="${pc(p.id)}">
      ${avatar(p)}
      <div class="grow">
        <div><b>${esc(p.name)}</b> · ${esc(w.activity || 'Workout')}</div>
        <div class="muted small">${fmtDay(w.workout_date)}</div>
        ${w.note ? `<div>${esc(w.note)}</div>` : ''}
        <div class="chips">${chips.join('')}
          ${canDelete ? `<button class="link" data-action="del" data-id="${w.id}" style="margin-left:6px">Delete</button>` : ''}</div>
      </div>
      ${url ? `<a href="${esc(api.photoUrl(w.photo_path, true))}" target="_blank" rel="noopener"><img class="thumb" src="${esc(url)}" alt="Workout photo" loading="lazy"></a>` : ''}
    </div>`;
  }).join('');
  view.innerHTML = `<h2>History</h2><p class="muted small">Everything either of you logged. Backdated and deleted entries stay visible.</p>
    <div class="card">${items || '<p class="muted">Nothing logged yet.</p>'}</div>`;
}

let wheel;
function renderSpin() {
  const prizes = S.prizes.filter((p) => p.active);
  const bal = S.pts.ledgers[S.me.id]?.balance ?? 0;
  const can = bal >= RULES.spinCost && prizes.length > 0;
  view.innerHTML = `
    <div class="wheel-wrap"><div class="pointer"></div><canvas id="wheel"></canvas></div>
    <p class="center">You have <b>${pts(bal)}</b>. A spin costs <b>${RULES.spinCost}</b>.</p>
    <button class="btn primary block big" data-action="spin" ${can ? '' : 'disabled'}>
      ${prizes.length === 0 ? 'Add prizes first' : can ? `Spin! (−${RULES.spinCost} pts)` : `${RULES.spinCost - bal} more points to spin`}</button>
    <p class="center muted small">Bigger slice = more likely. Edit prizes and odds in the Prizes tab.</p>`;
  wheel = new Wheel($('#wheel'));
  wheel.draw(prizes);
}

function renderPrizes() {
  const active = S.prizes.filter((p) => p.active);
  const total = active.reduce((s, p) => s + p.weight, 0) || 1;
  const toClaim = S.spins.filter((s) => !s.used_at).sort((a, b) => a.spun_at.localeCompare(b.spun_at));
  const used = S.spins.filter((s) => s.used_at).sort((a, b) => b.used_at.localeCompare(a.used_at));
  const spinRow = (s, btn) => {
    const p = player(s.user_id);
    return `<div class="item" style="${pc(p.id)}">${avatar(p)}
      <div class="grow"><b>${esc(s.prize_emoji)} ${esc(s.prize_name)}</b>
      <div class="muted small">Won by ${esc(p.name)} · ${fmtStamp(s.spun_at)}${s.used_at ? ` · used ${fmtStamp(s.used_at)}` : ''}</div></div>${btn}</div>`;
  };
  view.innerHTML = `
    <h2>Prizes to claim</h2>
    <div class="card">${toClaim.map((s) => spinRow(s, `<button class="btn small primary" data-action="use" data-id="${s.id}">Mark used</button>`)).join('')
      || '<p class="muted">No unclaimed prizes. Go earn a spin!</p>'}</div>

    <h2>On the wheel</h2>
    <div class="card">
      ${active.map((p) => `<div class="item"><div class="grow"><b>${esc(p.emoji)} ${esc(p.name)}</b>
          <div class="muted small">${Math.round((p.weight / total) * 100)}% chance · slice size ${p.weight}</div></div>
          <div class="row"><button class="btn small ghost" data-action="weight" data-id="${p.id}" data-d="-1" ${p.weight <= 1 ? 'disabled' : ''}>−</button>
          <button class="btn small ghost" data-action="weight" data-id="${p.id}" data-d="1" ${p.weight >= 10 ? 'disabled' : ''}>＋</button>
          <button class="btn small ghost" data-action="archive" data-id="${p.id}" title="Remove from wheel">✕</button></div></div>`).join('')
        || '<p class="muted">No prizes yet.</p>'}
      <form id="add-prize" class="add-prize">
        <input class="inp" name="emoji" value="🎁" maxlength="4" aria-label="Emoji">
        <input class="inp" name="name" placeholder="New prize, e.g. Lie-in Sunday" maxlength="60" required aria-label="Prize name">
        <button class="btn primary full">Add to wheel</button>
      </form>
    </div>

    <details class="card"><summary>Used prizes (${used.length})</summary>
      ${used.map((s) => spinRow(s, `<button class="link" data-action="unuse" data-id="${s.id}">Undo</button>`)).join('') || '<p class="muted">None yet.</p>'}
    </details>
    <details class="card"><summary>Removed from wheel (${S.prizes.length - active.length})</summary>
      ${S.prizes.filter((p) => !p.active).map((p) => `<div class="item"><div class="grow">${esc(p.emoji)} ${esc(p.name)}</div>
        <button class="link" data-action="restore" data-id="${p.id}">Put back</button></div>`).join('') || '<p class="muted">None.</p>'}
    </details>`;
  $('#add-prize').onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    const data = await api.addPrize({ name: f.get('name').trim(), emoji: f.get('emoji').trim() || '🎁', weight: 1 });
    toast('Prize added'); reload(data);
  };
}

function renderPoints() {
  const uid = S.ledgerUser ?? S.me.id;
  const ledger = S.pts.ledgers[uid] ?? { entries: [], balance: 0, earned: 0, spent: 0 };
  const players = orderedPlayers();
  const R = RULES;
  const rows = [...ledger.entries].reverse().map((e) => `<tr>
      <td class="small muted" style="white-space:nowrap">${shortDate(e.date)}</td><td>${esc(e.label)}</td>
      <td class="num ${e.points > 0 ? 'plus' : e.points < 0 ? 'minus' : 'zero'}">${e.points > 0 ? '+' : ''}${e.points}</td>
      <td class="num">${e.balance}</td></tr>`).join('');
  const months = [...S.pts.months].reverse().map((m) => `<tr><td>${monthLabel(m.month)}</td>
      ${players.map((p) => `<td class="num">${m.counts[p.id] ?? 0}</td>`).join('')}
      <td>${m.winners.map((u) => esc(player(u).name)).join(' & ') || '–'}</td></tr>`).join('');

  view.innerHTML = `
    <h2>How points work</h2>
    <div class="card"><ul class="rules" style="padding-left:18px;margin:0">
      <li>🏋️ <b>Workout: +${R.pointsPerWorkout}</b>. Max ${R.maxCountedWorkoutsPerDay} per day counts. A second session that day is logged but earns 0.</li>
      <li>🔥 <b>Active week: +${R.activeWeekBonus}</b> for every Mon–Sun week with ${R.activeWeekThreshold}+ workouts. Added on the day you hit ${R.activeWeekThreshold}.</li>
      <li>🏆 <b>Monthly winner: +${R.monthlyWinnerBonus}</b> for most workouts in a calendar month (ties: both). Added on the 1st of the next month.</li>
      <li>🎡 <b>Spin: −${R.spinCost}</b>.</li>
      <li>⚑ <b>Backdating</b> up to ${R.maxBackdateDays} days is allowed, but is always flagged in History with when it was really logged.</li>
      <li>🗑 <b>Deleting</b> a workout removes its points (and any bonus it unlocked). It stays visible in History.</li>
    </ul>
    <p class="small muted" style="margin-bottom:0"><b>What that means:</b> ~2.5 workouts/week ≈ 11 workouts + ~2 active weeks ≈ 13 pts/month → about <b>1 spin a month</b>.
      3/week every week ≈ 17 pts → ~1.4 spins/month. Points never expire.</p></div>

    <div class="seg">${players.map((p) => `<button class="${p.id === uid ? 'on' : ''}" data-action="ledger" data-uid="${p.id}">${esc(p.name)}</button>`).join('')}</div>
    <div class="card row spread" style="text-align:center">
      <div><div class="balance plus" style="font-size:24px">${ledger.earned}</div><div class="small muted">earned</div></div>
      <div><div class="balance minus" style="font-size:24px">${ledger.spent}</div><div class="small muted">spent</div></div>
      <div><div class="balance" style="font-size:24px">${ledger.balance}</div><div class="small muted">balance</div></div>
    </div>
    <div class="card"><h3>Every point, line by line</h3>
      <table class="ledger"><thead><tr><th>Date</th><th>Reason</th><th class="num">Pts</th><th class="num">Bal</th></tr></thead>
      <tbody>${rows || '<tr><td colspan="4" class="muted">No points yet.</td></tr>'}</tbody></table></div>
    ${months ? `<div class="card"><h3>Monthly results</h3><table class="ledger"><thead><tr><th>Month</th>
      ${players.map((p) => `<th class="num">${esc(p.name)}</th>`).join('')}<th>Winner</th></tr></thead><tbody>${months}</tbody></table></div>` : ''}`;
}

// ── Actions ─────────────────────────────────────────────────────────────────
const actions = {
  log: openLog,
  lb: (el) => { S.lbPeriod = el.dataset.p; renderHome(); },
  profile: openProfile,
  tab: (el) => { S.tab = el.dataset.tab; render(); scrollTo(0, 0); },
  ledger: (el) => { S.ledgerUser = el.dataset.uid; S.tab = 'points'; render(); },
  async del(el) {
    if (!confirm('Delete this workout? Its points are removed, but it stays visible (crossed out) in History.')) return;
    const data = await api.deleteWorkout(el.dataset.id); toast('Workout deleted'); reload(data);
  },
  async use(el) { el.disabled = true; const d = await api.setUsed(el.dataset.id, true); toast('Enjoy! 🎉'); reload(d); },
  async unuse(el) { reload(await api.setUsed(el.dataset.id, false)); },
  async archive(el) { reload(await api.updatePrize(el.dataset.id, { active: false })); },
  async restore(el) { reload(await api.updatePrize(el.dataset.id, { active: true })); },
  async weight(el) {
    const p = S.prizes.find((x) => x.id === el.dataset.id);
    el.disabled = true;
    reload(await api.updatePrize(p.id, { weight: Math.min(10, Math.max(1, p.weight + Number(el.dataset.d))) }));
  },
  async spin(el) {
    el.disabled = true;
    await reload();                                   // re-check balance with fresh data
    const prizes = S.prizes.filter((p) => p.active);
    if ((S.pts.ledgers[S.me.id]?.balance ?? 0) < RULES.spinCost || !prizes.length) return;
    $('[data-action="spin"]').disabled = true;
    const idx = pickWeighted(prizes);
    const prize = prizes[idx];
    const saved = await api.addSpin({ prize_id: prize.id, prize_name: prize.name, prize_emoji: prize.emoji, cost: RULES.spinCost });
    await wheel.spinTo(idx);                          // saved first, so closing the app mid-spin can't re-roll
    $('#result-body').innerHTML = `<div class="result-emoji">${esc(prize.emoji)}</div><h2>${esc(prize.name)}!</h2>
      <p class="muted">It's in your Prizes tab. Mark it used when you claim it.</p>`;
    $('#result-dialog').showModal();
    $('#result-dialog').addEventListener('close', () => reload(saved), { once: true }); // keep the wheel where it stopped until then
  },
};

document.querySelector('.top').addEventListener('click', (e) => {
  if (e.target.closest('[data-action="profile"]')) openProfile();
});
view.addEventListener('click', (e) => {
  const el = e.target.closest('[data-action]');
  if (!el) return;
  Promise.resolve(actions[el.dataset.action]?.(el)).catch((err) => { console.error(err); toast(`Error: ${err.message}`); });
});
$('#tabs').addEventListener('click', (e) => {
  const b = e.target.closest('button');
  if (b) { S.tab = b.dataset.tab; render(); scrollTo(0, 0); }
});
document.querySelectorAll('[data-close]').forEach((b) => b.addEventListener('click', () => b.closest('dialog').close()));
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible' && S.pts && !document.querySelector('dialog[open]')) reload().catch(() => {});
});

// ── Log workout sheet ─────────────────────────────────────────────────────────
const logForm = $('#log-form');
function openLog() {
  logForm.reset();
  const t = today();
  logForm.date.value = t;
  logForm.date.max = t;
  logForm.date.min = addDays(t, -RULES.maxBackdateDays);
  $('#log-preview').hidden = true;
  updateLogHint();
  $('#log-dialog').showModal();
}
function updateLogHint() {
  const d = logForm.date.value;
  const msgs = [];
  if (d && d < today()) msgs.push('⚑ This will be flagged as backdated in History.');
  if (countedDays(S.me.id).has(d)) msgs.push(`You already logged a workout on this day. Only ${RULES.maxCountedWorkoutsPerDay} per day earns points.`);
  $('#log-hint').hidden = !msgs.length;
  $('#log-hint').textContent = msgs.join(' ');
}
logForm.date.addEventListener('change', updateLogHint);
logForm.photo.addEventListener('change', () => {
  const f = logForm.photo.files[0];
  $('#log-preview').hidden = !f;
  if (f) $('#log-preview').src = URL.createObjectURL(f);
});

async function shrinkPhoto(file) {
  try {
    const img = await createImageBitmap(file);
    const scale = Math.min(1, 1280 / Math.max(img.width, img.height));
    const c = document.createElement('canvas');
    c.width = Math.round(img.width * scale); c.height = Math.round(img.height * scale);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.75));
  } catch {
    return file; // unknown format: upload as-is
  }
}

logForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const btn = $('#log-submit');
  const date = logForm.date.value;
  const t = today();
  if (date > t || date < addDays(t, -RULES.maxBackdateDays)) return toast(`Pick a day within the last ${RULES.maxBackdateDays} days`);
  btn.disabled = true; btn.textContent = 'Saving…';
  try {
    const file = logForm.photo.files[0];
    const data = await api.addWorkout({
      workout_date: date, activity: logForm.activity.value, note: logForm.note.value.trim() || null,
    }, file ? await shrinkPhoto(file) : null);
    $('#log-dialog').close();
    toast(date < t ? 'Logged (flagged as backdated)' : 'Workout logged 💪');
    await reload(data);
  } catch (err) {
    console.error(err); toast(`Couldn't save: ${err.message}`);
  } finally {
    btn.disabled = false; btn.textContent = 'Save workout';
  }
});

// ── Profile photo ───────────────────────────────────────────────────────────
function openProfile() {
  $('#profile-body').innerHTML = `${avatar(S.me, 110)}<h2 style="margin:14px 0 2px">${esc(S.me.name)}</h2>
    <p class="muted small" style="margin:0">Your photo shows on the leaderboard and in History.</p>`;
  $('#profile-dialog').showModal();
}

// Crop to a centred square and shrink, so profile photos are small and look right in circles.
async function squarePhoto(file, size = 400) {
  try {
    const img = await createImageBitmap(file);
    const side = Math.min(img.width, img.height);
    const c = document.createElement('canvas');
    c.width = c.height = Math.min(size, side);
    c.getContext('2d').drawImage(img, (img.width - side) / 2, (img.height - side) / 2, side, side, 0, 0, c.width, c.height);
    return await new Promise((res) => c.toBlob(res, 'image/jpeg', 0.85));
  } catch {
    return file;
  }
}

$('#avatar-input').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const label = e.target.closest('label');
  label.firstChild.textContent = 'Uploading… ';
  try {
    const data = await api.setAvatar(await squarePhoto(file));
    $('#profile-dialog').close();
    toast('Looking good 😎');
    await reload(data);
  } catch (err) {
    console.error(err);
    toast(/Unknown action/.test(err.message) ? 'Update the Google script first (see Claude’s steps)' : `Couldn't save: ${err.message}`);
  } finally {
    label.firstChild.textContent = '📷 Change profile photo ';
    e.target.value = '';
  }
});

boot().catch((err) => {
  console.error(err);
  view.innerHTML = `<div class="card"><h3>Something went wrong</h3><p class="err">${esc(err.message)}</p>
    <button class="btn" onclick="location.reload()">Try again</button></div>`;
});
