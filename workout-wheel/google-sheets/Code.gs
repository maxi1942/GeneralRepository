/**
 * Workout Wheel — Google Sheets backend.
 *
 * HOW TO USE: see workout-wheel/README.md. In short:
 *   1. Paste this whole file into Extensions → Apps Script (replacing what's there).
 *   2. Run `setup` once (pick it in the dropdown at the top, click ▶ Run).
 *   3. Deploy → New deployment → Web app → Execute as: Me, Who has access: Anyone.
 *
 * The sheet IS the database. Only edit names / passcodes in the "Players" tab by hand.
 */

const TABS = {
  Players: ['id', 'name', 'passcode', 'avatar'],
  Workouts: ['id', 'user_id', 'workout_date', 'logged_at', 'activity', 'note', 'photo_path', 'deleted_at'],
  Prizes: ['id', 'name', 'emoji', 'weight', 'active', 'created_at'],
  Spins: ['id', 'user_id', 'prize_id', 'prize_name', 'prize_emoji', 'cost', 'spun_at', 'used_at'],
};
const MAX_BACKDATE_DAYS = 7; // keep in sync with rules.js

// ── One-time setup ──────────────────────────────────────────────────────────
function setup() {
  const ss = SpreadsheetApp.getActive();
  Object.keys(TABS).forEach((name) => {
    const headers = TABS[name];
    let sh = ss.getSheetByName(name) || ss.insertSheet(name);
    // Plain-text format everywhere, so Sheets doesn't turn dates/passcodes into numbers.
    sh.getRange(1, 1, sh.getMaxRows(), sh.getMaxColumns()).setNumberFormat('@');
    if (sh.getLastRow() === 0) {
      sh.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      sh.setFrozenRows(1);
    }
  });
  const blank = ss.getSheetByName('Sheet1');
  if (blank && blank.getLastRow() === 0) ss.deleteSheet(blank);

  if (sheet_('Players').getLastRow() === 1) {
    append_('Players', { id: Utilities.getUuid(), name: 'Max', passcode: 'change-me-1' });
    append_('Players', { id: Utilities.getUuid(), name: 'Partner', passcode: 'change-me-2' });
  }
  if (sheet_('Prizes').getLastRow() === 1) {
    [['Breakfast in bed', '🥐', 2], ['Massage (30 min)', '💆', 2], ['Pick the movie', '🎬', 3],
      ['Skip a chore', '🧹', 3], ['Dinner out – your choice', '🍝', 1]].forEach(([name, emoji, weight]) =>
      append_('Prizes', { id: Utilities.getUuid(), name, emoji, weight, active: true, created_at: now_() }));
  }
  const props = PropertiesService.getScriptProperties();
  if (!props.getProperty('PHOTO_FOLDER_ID')) {
    props.setProperty('PHOTO_FOLDER_ID', DriveApp.createFolder('Workout Wheel photos').getId());
  }
  Logger.log('✅ Setup done. Now edit the names + passcodes in the "Players" tab, then Deploy.');
}

// ── Web API ─────────────────────────────────────────────────────────────────
function doGet() {
  return ContentService.createTextOutput('✅ Workout Wheel backend is running.');
}

function doPost(e) {
  let out;
  try {
    const req = JSON.parse(e.postData.contents);
    const me = auth_(req.passcode);
    out = handle_(me, req);
  } catch (err) {
    out = { error: String((err && err.message) || err) };
  }
  return ContentService.createTextOutput(JSON.stringify(out)).setMimeType(ContentService.MimeType.JSON);
}

function handle_(me, req) {
  if (req.action === 'login') return { me: { id: me.id, name: me.name } };
  if (req.action === 'load') return state_();

  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    switch (req.action) {
      case 'addWorkout': {
        const date = String(req.workout_date || '');
        if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) throw new Error('Invalid date');
        const today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd');
        if (date > addDays_(today, 1) || date < addDays_(today, -(MAX_BACKDATE_DAYS + 1))) {
          throw new Error(`Pick a day within the last ${MAX_BACKDATE_DAYS} days`);
        }
        append_('Workouts', {
          id: Utilities.getUuid(), user_id: me.id, workout_date: date, logged_at: now_(),
          activity: clip_(req.activity, 30), note: clip_(req.note, 140),
          photo_path: req.photo ? savePhoto_(me, date, req.photo, req.photo_mime) : '',
        });
        break;
      }
      case 'deleteWorkout': {
        const w = read_('Workouts').find((r) => r.id === req.id);
        if (!w || w.user_id !== me.id) throw new Error('You can only delete your own workouts');
        update_('Workouts', req.id, { deleted_at: now_() });
        break;
      }
      case 'addPrize':
        append_('Prizes', {
          id: Utilities.getUuid(), name: clip_(req.name, 60) || 'Prize', emoji: clip_(req.emoji, 8) || '🎁',
          weight: weight_(req.weight), active: true, created_at: now_(),
        });
        break;
      case 'updatePrize': {
        const patch = {};
        if ('active' in req) patch.active = !!req.active;
        if ('weight' in req) patch.weight = weight_(req.weight);
        update_('Prizes', req.id, patch);
        break;
      }
      case 'addSpin': {
        const prize = read_('Prizes').find((p) => p.id === req.prize_id);
        if (!prize) throw new Error('Unknown prize');
        append_('Spins', {
          id: Utilities.getUuid(), user_id: me.id, prize_id: prize.id, prize_name: prize.name,
          prize_emoji: prize.emoji, cost: Number(req.cost) || 12, spun_at: now_(), used_at: '',
        });
        break;
      }
      case 'setUsed':
        update_('Spins', req.id, { used_at: req.used ? now_() : '' });
        break;
      case 'setAvatar': {
        if (!req.photo) throw new Error('No photo');
        const old = me.avatar;
        update_('Players', me.id, { avatar: savePhoto_(me, 'avatar', req.photo, req.photo_mime) });
        if (old) { try { DriveApp.getFileById(old).setTrashed(true); } catch (e) { /* already gone */ } }
        break;
      }
      default:
        throw new Error(`Unknown action: ${req.action}`);
    }
  } finally {
    lock.releaseLock();
  }
  return state_();
}

// ── Helpers ─────────────────────────────────────────────────────────────────
function auth_(passcode) {
  const code = String(passcode || '').trim();
  const me = code && read_('Players').find((p) => String(p.passcode).trim() === code);
  if (!me) throw new Error('BAD_PASSCODE');
  return me;
}

function state_() {
  return {
    profiles: read_('Players').map((p) => ({ id: p.id, name: p.name, avatar: p.avatar })),
    workouts: read_('Workouts'),
    prizes: read_('Prizes'),
    spins: read_('Spins'),
  };
}

function sheet_(name) {
  const sh = SpreadsheetApp.getActive().getSheetByName(name);
  if (!sh) throw new Error(`Missing tab "${name}" — run setup()`);
  return sh;
}

function read_(name) {
  const values = sheet_(name).getDataRange().getValues();
  const headers = TABS[name]; // by position, so older sheets missing a new header still read fine
  const tz = Session.getScriptTimeZone();
  return values.slice(1).filter((row) => row[0] !== '').map((row) => {
    const o = {};
    headers.forEach((h, i) => {
      let v = row[i];
      if (v instanceof Date) v = h === 'workout_date' ? Utilities.formatDate(v, tz, 'yyyy-MM-dd') : v.toISOString();
      if (v === '' || v === undefined) v = null;
      if (h === 'weight' || h === 'cost') v = Number(v) || 1;
      if (h === 'active') v = v === true || String(v).toUpperCase() === 'TRUE';
      if (v !== null && typeof v !== 'string' && typeof v !== 'number' && typeof v !== 'boolean') v = String(v);
      if (h === 'id' || h === 'user_id' || h === 'passcode' || h === 'name') v = v === null ? '' : String(v);
      o[h] = v;
    });
    return o;
  });
}

// Adds any new column headers (e.g. "avatar") to sheets created by an older version.
function ensureHeaders_(sh, name) {
  const headers = TABS[name];
  const current = sh.getRange(1, 1, 1, headers.length).getValues()[0].map(String);
  if (current.join('|') !== headers.join('|')) sh.getRange(1, 1, 1, headers.length).setValues([headers]);
}

function append_(name, obj) {
  const sh = sheet_(name);
  ensureHeaders_(sh, name);
  const headers = TABS[name];
  const row = sh.getLastRow() + 1;
  if (row > sh.getMaxRows()) sh.insertRowsAfter(sh.getMaxRows(), 200);
  const range = sh.getRange(row, 1, 1, headers.length);
  range.setNumberFormat('@');
  range.setValues([headers.map((h) => cell_(obj[h]))]);
}

function cell_(v) {
  if (v === undefined || v === null) return '';
  if (typeof v === 'boolean') return v ? 'TRUE' : 'FALSE';
  return String(v);
}

function update_(name, id, patch) {
  const sh = sheet_(name);
  ensureHeaders_(sh, name);
  const headers = TABS[name];
  const ids = sh.getRange(1, 1, sh.getLastRow(), 1).getValues().map((r) => String(r[0]));
  const idx = ids.indexOf(String(id));
  if (idx < 1) throw new Error('Not found');
  Object.keys(patch).forEach((k) => {
    const col = headers.indexOf(k) + 1;
    const cell = sh.getRange(idx + 1, col, 1, 1);
    cell.setNumberFormat('@');
    cell.setValues([[cell_(patch[k])]]);
  });
}

function savePhoto_(me, date, base64, mime) {
  const folder = DriveApp.getFolderById(PropertiesService.getScriptProperties().getProperty('PHOTO_FOLDER_ID'));
  const type = /^image\/[a-z0-9.+-]+$/.test(mime || '') ? mime : 'image/jpeg';
  const blob = Utilities.newBlob(Utilities.base64Decode(base64), type, `${date} ${me.name}.${type.split('/')[1]}`);
  const file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); // so the app can show it
  return file.getId();
}

function addDays_(str, n) {
  const p = str.split('-').map(Number);
  const d = new Date(Date.UTC(p[0], p[1] - 1, p[2] + n));
  return d.toISOString().slice(0, 10);
}
function now_() { return new Date().toISOString(); }
function clip_(s, n) { return String(s == null ? '' : s).trim().slice(0, n); }
function weight_(w) { return Math.min(10, Math.max(1, Math.round(Number(w) || 1))); }
