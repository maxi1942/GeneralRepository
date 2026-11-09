import { SUPABASE_URL, SUPABASE_ANON_KEY } from './config.js';
import {
  RULES, computePoints, toDateStr, addDays, weekStart, monthKey, monthLabel, shortDate, isBackdated,
} from './rules.js';
import { Wheel, pickWeighted } from './wheel.js';

const DEMO = new URLSearchParams(location.search).has('demo');
const CONFIGURED = !SUPABASE_URL.includes('YOUR-PROJECT');
const PLAYER_COLORS = ['var(--p0)', 'var(--p1)'];

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

// ── Data layer: Supabase, or an in-memory demo ──────────────────────────────
async function makeApi() {
  if (DEMO) return demoApi();
  const { createClient } = await import('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/+esm');
  const sb = createClient(SUPABASE_URL, SUPABASE_ANON_KEY);
  const check = ({ data, error }) => { if (error) throw error; return data; };
  const fetchAll = async (table, col) => {
    let rows = [];
    for (let from = 0; ; from += 1000) {
      const page = check(await sb.from(table).select('*').order(col).range(from, from + 999));
      rows = rows.concat(page);
      if (page.length < 1000) return rows;
    }
  };
  return {
    async user() { return (await sb.auth.getSession()).data.session?.user ?? null; },
    async signIn(email, password) { check(await sb.auth.signInWithPassword({ email, password })); },
    async signOut() { await sb.auth.signOut(); },
    async saveProfile(id, name) { check(await sb.from('profiles').upsert({ id, name })); },
    async loadAll() {
      const [profiles, workouts, spins, prizes] = await Promise.all([
        fetchAll('profiles', 'created_at'), fetchAll('workouts', 'logged_at'),
        fetchAll('spins', 'spun_at'), fetchAll('prizes', 'created_at'),
      ]);
      return { profiles, workouts, spins, prizes };
    },
    async addWorkout(row) { check(await sb.from('workouts').insert(row)); },
    async deleteWorkout(id) { check(await sb.from('workouts').update({ deleted_at: new Date().toISOString() }).eq('id', id)); },
    async addPrize(row) { check(await sb.from('prizes').insert(row)); },
    async updatePrize(id, patch) { check(await sb.from('prizes').update(patch).eq('id', id)); },
    async addSpin(row) { check(await sb.from('spins').insert(row)); },
    async setUsed(id, used) { check(await sb.from('spins').update({ used_at: used ? new Date().toISOString() : null }).eq('id', id)); },
    async uploadPhoto(uid, blob) {
      const path = `${uid}/${crypto.randomUUID()}.jpg`;
      check(await sb.storage.from('workout-photos').upload(path, blob, { contentType: 'image/jpeg' }));
      return path;
    },
    async photoUrls(paths) {
      if (!paths.length) return {};
      const data = check(await sb.storage.from('workout-photos').createSignedUrls(paths, 3600));
      return Object.fromEntries(data.filter((d) => d.signedUrl).map((d) => [d.path, d.signedUrl]));
    },
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
    async saveProfile() {},
    async loadAll() { return structuredClone(db); },
    async addWorkout(row) { db.workouts.push({ id: `w${++id}`, user_id: me.id, logged_at: now(), deleted_at: null, ...row }); },
    async deleteWorkout(wid) { db.workouts.find((w) => w.id === wid).deleted_at = now(); },
    async addPrize(row) { db.prizes.push({ id: `p${++id}`, active: true, created_at: now(), ...row }); },
    async updatePrize(pid, patch) { Object.assign(db.prizes.find((p) => p.id === pid), patch); },
    async addSpin(row) { db.spins.push({ id: `s${++id}`, user_id: me.id, spun_at: now(), used_at: null, ...row }); },
    async setUsed(sid, used) { db.spins.find((s) => s.id === sid).used_at = used ? now() : null; },
    async uploadPhoto(uid, blob) { return URL.createObjectURL(blob); },
    async photoUrls(paths) { return Object.fromEntries(paths.map((p) => [p, p])); },
  };
}

// ── App state ────────────────────────────────────────────────────────────────
let api;
const S = { me: null, profiles: [], workouts: [], spins: [], prizes: [], pts: null, photos: {}, tab: 'home', ledgerUser: null };
const view = $('#view');

function player(uid) { return S.profiles.find((p) => p.id === uid) ?? { id: uid, name: '?' }; }
function colorOf(uid) { const i = S.profiles.findIndex((p) => p.id === uid); return PLAYER_COLORS[Math.max(0, i) % 2]; }
function orderedPlayers() { return [...S.profiles].sort((a, b) => (a.id === S.me.id ? -1 : b.id === S.me.id ? 1 : 0)); }

async function reload() {
  const data = await api.loadAll();
  Object.assign(S, data);
  S.pts = computePoints({ players: S.profiles, workouts: S.workouts, spins: S.spins, today: today() });
  const paths = S.workouts.filter((w) => w.photo_path && !w.deleted_at && !S.photos[w.photo_path]).map((w) => w.photo_path);
  try { Object.assign(S.photos, await api.photoUrls(paths)); } catch (e) { console.warn('photos', e); }
  render();
}

// ── Boot / auth ─────────────────────────────────────────────────────────────
async function boot() {
  if (!DEMO && !CONFIGURED) return renderSetupNeeded();
  api = await makeApi();
  const user = await api.user();
  if (!user) return renderLogin();
  S.me = { id: user.id };
  const { profiles } = await api.loadAll();
  const mine = profiles.find((p) => p.id === user.id);
  if (!mine) return renderNamePrompt(user.id);
  S.me = mine;
  $('#who').innerHTML = `${esc(mine.name)}${DEMO ? ' <span class="chip">demo</span>' : ''} <button class="link" id="logout">Sign out</button>`;
  $('#logout').onclick = async () => { await api.signOut(); location.reload(); };
  $('#tabs').hidden = false;
  await reload();
}

function renderSetupNeeded() {
  view.innerHTML = `<div class="card"><h3>Almost there 👋</h3>
    <p>The app isn't connected to a database yet. Follow the steps in <b>workout-wheel/README.md</b>
    and paste your Supabase details into <b>config.js</b>.</p>
    <p><a class="btn primary" href="?demo">Try the demo instead</a></p></div>`;
}

function renderLogin() {
  view.innerHTML = `<div class="card"><form id="login"><h2>Sign in</h2>
    <label>Email<input type="email" name="email" required autocomplete="username"></label>
    <label>Password<input type="password" name="password" required autocomplete="current-password"></label>
    <p class="err" id="login-err"></p>
    <button class="btn primary block">Sign in</button></form></div>`;
  $('#login').onsubmit = async (e) => {
    e.preventDefault();
    const f = new FormData(e.target);
    try { await api.signIn(f.get('email'), f.get('password')); location.reload(); }
    catch (err) { $('#login-err').textContent = err.message; }
  };
}

function renderNamePrompt(uid) {
  view.innerHTML = `<div class="card"><form id="name-form"><h2>What should we call you?</h2>
    <label>Name<input type="text" name="name" maxlength="30" required></label>
    <button class="btn primary block">Continue</button></form></div>`;
  $('#name-form').onsubmit = async (e) => {
    e.preventDefault();
    await api.saveProfile(uid, new FormData(e.target).get('name').trim());
    location.reload();
  };
}

// ── Rendering ────────────────────────────────────────────────────────────────
function render() {
  document.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('on', b.dataset.tab === S.tab));
  ({ home: renderHome, history: renderHistory, spin: renderSpin, prizes: renderPrizes, points: renderPoints })[S.tab]();
}

function countedDays(uid) {
  return new Set(S.workouts.filter((w) => w.user_id === uid && S.pts.counted.get(w.id)).map((w) => w.workout_date));
}

function renderHome() {
  const t = today();
  const monday = weekStart(t);
  const mk = monthKey(t);
  const lastDay = addDays(`${monthKey(addDays(`${mk}-28`, 7))}-01`, -1);
  const daysLeft = Math.round((new Date(`${lastDay}T12:00:00`) - new Date(`${t}T12:00:00`)) / 864e5);

  const cards = orderedPlayers().map((p) => {
    const ledger = S.pts.ledgers[p.id] ?? { balance: 0 };
    const days = countedDays(p.id);
    const weekN = [...days].filter((d) => weekStart(d) === monday).length;
    const spinsReady = Math.floor(Math.max(0, ledger.balance) / RULES.spinCost);
    const toNext = RULES.spinCost - ledger.balance;
    const pct = spinsReady ? 100 : Math.max(0, (ledger.balance / RULES.spinCost) * 100);
    const dots = [0, 1, 2, 3, 4, 5, 6].map((i) => {
      const d = addDays(monday, i);
      return `<div class="dot ${days.has(d) ? 'on' : ''} ${d === t ? 'today' : ''}">${'MTWTFSS'[i]}</div>`;
    }).join('');
    const weekMsg = weekN >= RULES.activeWeekThreshold
      ? `<span class="chip good">🔥 Active week bonus earned (+${RULES.activeWeekBonus})</span>`
      : `<span class="muted small">${weekN}/${RULES.activeWeekThreshold} this week → +${RULES.activeWeekBonus} active-week bonus</span>`;
    return `<div class="card player" style="--pc:${colorOf(p.id)}">
      <div class="row spread"><h3>${esc(p.name)}${p.id === S.me.id ? ' (you)' : ''}</h3>
        <button class="link" data-action="ledger" data-uid="${p.id}">See points →</button></div>
      <div class="row spread"><div><span class="balance">${ledger.balance}</span> <span class="muted">points</span></div>
        <div class="small ${spinsReady ? '' : 'muted'}">${spinsReady ? `🎉 <b>${spinsReady} spin${spinsReady > 1 ? 's' : ''} ready</b>` : `${toNext} to next spin`}</div></div>
      <div class="bar"><i style="width:${Math.min(100, pct)}%"></i></div>
      <div class="dots">${dots}</div>
      <div style="margin-top:6px">${weekMsg}</div>
    </div>`;
  }).join('');

  const race = orderedPlayers().map((p) => ({ p, n: [...countedDays(p.id)].filter((d) => monthKey(d) === mk).length }));
  const max = Math.max(0, ...race.map((r) => r.n));
  const raceRows = race.map(({ p, n }) => `<div class="row" style="--pc:${colorOf(p.id)}; margin:6px 0">
      <div style="width:84px" class="small">${n === max && n > 0 ? '👑 ' : ''}${esc(p.name)}</div>
      <div class="grow bar" style="margin:0"><i style="width:${max ? (n / max) * 100 : 0}%"></i></div>
      <b style="width:28px;text-align:right">${n}</b></div>`).join('');

  view.innerHTML = `
    <button class="btn primary block big" data-action="log" style="margin-top:12px">＋ Log a workout</button>
    ${cards}
    <div class="card"><h3>${monthLabel(mk)} race</h3>
      ${raceRows}
      <p class="muted small" style="margin:6px 0 0">Most workouts when the month ends gets +${RULES.monthlyWinnerBonus} point (ties: both). ${daysLeft} day${daysLeft === 1 ? '' : 's'} left.</p>
    </div>
    <p class="center"><button class="link" data-action="tab" data-tab="points">How do points work?</button></p>`;
}

function renderHistory() {
  const events = [
    ...S.workouts.map((w) => ({ type: 'w', sort: `${w.workout_date}|${w.logged_at}`, w })),
    ...S.spins.map((s) => ({ type: 's', sort: `${toDateStr(new Date(s.spun_at))}|${s.spun_at}`, s })),
  ].sort((a, b) => b.sort.localeCompare(a.sort));

  const items = events.slice(0, 200).map((e) => {
    if (e.type === 's') {
      const s = e.s, p = player(s.user_id);
      return `<div class="item" style="--pc:${colorOf(p.id)}"><div class="avatar">${esc(p.name[0])}</div>
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
    const url = w.photo_path && !w.deleted_at ? S.photos[w.photo_path] : null;
    const canDelete = w.user_id === S.me.id && !w.deleted_at;
    return `<div class="item ${w.deleted_at ? 'deleted' : ''}" style="--pc:${colorOf(p.id)}">
      <div class="avatar">${esc(p.name[0])}</div>
      <div class="grow">
        <div><b>${esc(p.name)}</b> · ${esc(w.activity || 'Workout')}</div>
        <div class="muted small">${fmtDay(w.workout_date)}</div>
        ${w.note ? `<div>${esc(w.note)}</div>` : ''}
        <div class="chips">${chips.join('')}
          ${canDelete ? `<button class="link" data-action="del" data-id="${w.id}" style="margin-left:6px">Delete</button>` : ''}</div>
      </div>
      ${url ? `<a href="${esc(url)}" target="_blank" rel="noopener"><img class="thumb" src="${esc(url)}" alt="Workout photo" loading="lazy"></a>` : ''}
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
    return `<div class="item" style="--pc:${colorOf(p.id)}"><div class="avatar">${esc(p.name[0])}</div>
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
    await api.addPrize({ name: f.get('name').trim(), emoji: f.get('emoji').trim() || '🎁', weight: 1 });
    toast('Prize added'); reload();
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
  tab: (el) => { S.tab = el.dataset.tab; render(); scrollTo(0, 0); },
  ledger: (el) => { S.ledgerUser = el.dataset.uid; S.tab = 'points'; render(); },
  async del(el) {
    if (!confirm('Delete this workout? Its points are removed, but it stays visible (crossed out) in History.')) return;
    await api.deleteWorkout(el.dataset.id); toast('Workout deleted'); reload();
  },
  async use(el) { await api.setUsed(el.dataset.id, true); toast('Enjoy! 🎉'); reload(); },
  async unuse(el) { await api.setUsed(el.dataset.id, false); reload(); },
  async archive(el) { await api.updatePrize(el.dataset.id, { active: false }); reload(); },
  async restore(el) { await api.updatePrize(el.dataset.id, { active: true }); reload(); },
  async weight(el) {
    const p = S.prizes.find((x) => x.id === el.dataset.id);
    await api.updatePrize(p.id, { weight: Math.min(10, Math.max(1, p.weight + Number(el.dataset.d))) });
    reload();
  },
  async spin(el) {
    el.disabled = true;
    await reload();                                   // re-check balance with fresh data
    const prizes = S.prizes.filter((p) => p.active);
    if ((S.pts.ledgers[S.me.id]?.balance ?? 0) < RULES.spinCost || !prizes.length) return;
    $('[data-action="spin"]').disabled = true;
    const idx = pickWeighted(prizes);
    const prize = prizes[idx];
    await api.addSpin({ prize_id: prize.id, prize_name: prize.name, prize_emoji: prize.emoji, cost: RULES.spinCost });
    await wheel.spinTo(idx);                          // saved first, so closing the app mid-spin can't re-roll
    $('#result-body').innerHTML = `<div class="result-emoji">${esc(prize.emoji)}</div><h2>${esc(prize.name)}!</h2>
      <p class="muted">It's in your Prizes tab. Mark it used when you claim it.</p>`;
    $('#result-dialog').showModal();
    $('#result-dialog').addEventListener('close', () => reload(), { once: true }); // keep the wheel where it stopped until then
  },
};

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
    let photo_path = null;
    const file = logForm.photo.files[0];
    if (file) photo_path = await api.uploadPhoto(S.me.id, await shrinkPhoto(file));
    await api.addWorkout({
      workout_date: date, activity: logForm.activity.value,
      note: logForm.note.value.trim() || null, photo_path,
    });
    $('#log-dialog').close();
    toast(date < t ? 'Logged (flagged as backdated)' : 'Workout logged 💪');
    await reload();
  } catch (err) {
    console.error(err); toast(`Couldn't save: ${err.message}`);
  } finally {
    btn.disabled = false; btn.textContent = 'Save workout';
  }
});

boot().catch((err) => {
  console.error(err);
  view.innerHTML = `<div class="card"><h3>Something went wrong</h3><p class="err">${esc(err.message)}</p>
    <button class="btn" onclick="location.reload()">Try again</button></div>`;
});
