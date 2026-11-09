// ─────────────────────────────────────────────────────────────────────────────
// THE POINTS RULES — the single source of truth.
// Change a number here and the whole app (balances, ledger, "How points work"
// page) follows. Nothing about points is stored in the database: every balance
// is recalculated from the workout + spin logs, so it is always explainable.
// ─────────────────────────────────────────────────────────────────────────────
export const RULES = {
  pointsPerWorkout: 1,          // each logged workout
  maxCountedWorkoutsPerDay: 1,  // extra workouts on the same day earn 0 (stops double-logging)
  activeWeekThreshold: 3,       // workouts in one Mon–Sun week to earn the weekly bonus
  activeWeekBonus: 1,           // bonus for each week that hits the threshold
  monthlyWinnerBonus: 1,        // most workouts in a calendar month (ties: both get it)
  spinCost: 12,                 // points needed for one spin of the wheel
  maxBackdateDays: 7,           // how far back a workout can be logged (always flagged)
};

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
  'August', 'September', 'October', 'November', 'December'];

// ── Date helpers. Dates are plain 'YYYY-MM-DD' strings (local calendar days). ──
export function toDateStr(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}
function parseUTC(str) {
  const [y, m, d] = str.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}
export function addDays(str, n) {
  const dt = parseUTC(str);
  dt.setUTCDate(dt.getUTCDate() + n);
  return dt.toISOString().slice(0, 10);
}
export function weekStart(str) {            // Monday of that week
  const dow = (parseUTC(str).getUTCDay() + 6) % 7; // Mon=0 … Sun=6
  return addDays(str, -dow);
}
export const monthKey = (str) => str.slice(0, 7); // 'YYYY-MM'
export function nextMonthKey(mk) {
  let [y, m] = mk.split('-').map(Number);
  m += 1; if (m > 12) { m = 1; y += 1; }
  return `${y}-${String(m).padStart(2, '0')}`;
}
export function monthLabel(mk) {
  const [y, m] = mk.split('-').map(Number);
  return `${MONTHS[m - 1]} ${y}`;
}
export function shortDate(str) {
  const [, m, d] = str.split('-').map(Number);
  return `${d} ${MONTHS[m - 1].slice(0, 3)}`;
}

// A workout is "backdated" when the day it is for is earlier than the day it was logged.
export function isBackdated(workout) {
  return workout.workout_date < toDateStr(new Date(workout.logged_at));
}

// Order entries on the same day so the ledger reads naturally.
const KIND_ORDER = { workout: 0, extra: 1, week: 2, month: 3, spin: 4 };

/**
 * Turn the raw logs into a full points ledger per player.
 *
 * players:  [{ id, name }]
 * workouts: [{ id, user_id, workout_date, logged_at, deleted_at }]
 * spins:    [{ id, user_id, spun_at, cost, prize_name }]
 * today:    'YYYY-MM-DD' — months only get a winner once they are over.
 */
export function computePoints({ players, workouts, spins, today, rules = RULES }) {
  const ledgers = {};
  const ensure = (uid) => (ledgers[uid] ??= { entries: [], balance: 0, earned: 0, spent: 0 });
  players.forEach((p) => ensure(p.id));
  const nameOf = (uid) => players.find((p) => p.id === uid)?.name ?? 'Unknown';

  // 1) Workouts — at most N per user per day earn points.
  const live = workouts
    .filter((w) => !w.deleted_at)
    .sort((a, b) => a.workout_date.localeCompare(b.workout_date) || a.logged_at.localeCompare(b.logged_at));

  const counted = new Map();          // workout id -> true/false
  const perDay = new Map();           // `${uid}|${date}` -> count so far
  for (const w of live) {
    const key = `${w.user_id}|${w.workout_date}`;
    const n = perDay.get(key) ?? 0;
    perDay.set(key, n + 1);
    const isCounted = n < rules.maxCountedWorkoutsPerDay;
    counted.set(w.id, isCounted);
    ensure(w.user_id).entries.push(isCounted
      ? { date: w.workout_date, kind: 'workout', points: rules.pointsPerWorkout, label: 'Workout', ref: w.id }
      : { date: w.workout_date, kind: 'extra', points: 0, label: 'Extra workout same day (not counted)', ref: w.id });
  }
  const countedWorkouts = live.filter((w) => counted.get(w.id));

  // 2) Active weeks — bonus the moment the threshold is reached in a Mon–Sun week.
  const weekCount = new Map();        // `${uid}|${monday}` -> counted workouts
  for (const w of countedWorkouts) {
    const monday = weekStart(w.workout_date);
    const key = `${w.user_id}|${monday}`;
    const n = (weekCount.get(key) ?? 0) + 1;
    weekCount.set(key, n);
    if (n === rules.activeWeekThreshold && rules.activeWeekBonus) {
      ensure(w.user_id).entries.push({
        date: w.workout_date, kind: 'week', points: rules.activeWeekBonus,
        label: `Active week bonus (${n} workouts, week of ${shortDate(monday)})`,
      });
    }
  }

  // 3) Monthly winner — only for months that have finished.
  const months = [];
  if (countedWorkouts.length) {
    const currentMonth = monthKey(today);
    const counts = new Map();         // `${mk}|${uid}` -> workouts
    for (const w of countedWorkouts) {
      const key = `${monthKey(w.workout_date)}|${w.user_id}`;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    const uids = [...new Set([...players.map((p) => p.id), ...countedWorkouts.map((w) => w.user_id)])];
    for (let mk = monthKey(countedWorkouts[0].workout_date); mk < currentMonth; mk = nextMonthKey(mk)) {
      const byUser = Object.fromEntries(uids.map((u) => [u, counts.get(`${mk}|${u}`) ?? 0]));
      const max = Math.max(0, ...Object.values(byUser));
      const winners = max > 0 ? uids.filter((u) => byUser[u] === max) : [];
      months.push({ month: mk, counts: byUser, winners });
      if (!rules.monthlyWinnerBonus) continue;
      const tie = winners.length > 1;
      const others = uids.filter((u) => !winners.includes(u))
        .map((u) => `${nameOf(u)} ${byUser[u]}`).join(', ');
      for (const u of winners) {
        ensure(u).entries.push({
          date: `${nextMonthKey(mk)}-01`, kind: 'month', points: rules.monthlyWinnerBonus,
          label: `Monthly winner – ${monthLabel(mk)} (${max} workouts${tie ? ', tied' : ''}${others ? ` vs ${others}` : ''})`,
        });
      }
    }
  }

  // 4) Spins cost points.
  for (const s of spins) {
    ensure(s.user_id).entries.push({
      date: toDateStr(new Date(s.spun_at)), kind: 'spin', points: -(s.cost ?? rules.spinCost),
      label: `Spin → ${s.prize_name}`, ref: s.id,
    });
  }

  // 5) Sort and add a running balance.
  for (const ledger of Object.values(ledgers)) {
    ledger.entries.sort((a, b) => a.date.localeCompare(b.date) || KIND_ORDER[a.kind] - KIND_ORDER[b.kind]);
    let bal = 0;
    for (const e of ledger.entries) {
      bal += e.points;
      e.balance = bal;
      if (e.points > 0) ledger.earned += e.points; else ledger.spent -= e.points;
    }
    ledger.balance = bal;
  }

  return { ledgers, months, counted };
}
