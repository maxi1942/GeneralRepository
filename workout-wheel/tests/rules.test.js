// Run with:  cd workout-wheel && node --test
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { computePoints, weekStart, addDays, RULES } from '../rules.js';

const players = [{ id: 'a', name: 'Max' }, { id: 'b', name: 'Sam' }];
let n = 0;
const w = (user_id, workout_date, extra = {}) => ({
  id: `w${++n}`, user_id, workout_date, logged_at: `${workout_date}T18:00:00`, deleted_at: null, ...extra,
});

test('date helpers: weeks start on Monday', () => {
  assert.equal(weekStart('2026-11-09'), '2026-11-09'); // Monday
  assert.equal(weekStart('2026-11-15'), '2026-11-09'); // Sunday
  assert.equal(addDays('2026-12-31', 1), '2027-01-01');
});

test('1 point per workout, max 1 per day', () => {
  const { ledgers } = computePoints({
    players, spins: [], today: '2026-11-20',
    workouts: [w('a', '2026-11-10'), w('a', '2026-11-10'), w('a', '2026-11-12')],
  });
  assert.equal(ledgers.a.balance, 2);
  assert.equal(ledgers.a.entries.filter((e) => e.kind === 'extra').length, 1);
});

test('active week bonus once when the 3rd workout lands, not again on the 4th', () => {
  const { ledgers } = computePoints({
    players, spins: [], today: '2026-11-20',
    workouts: ['2026-11-09', '2026-11-11', '2026-11-13', '2026-11-15'].map((d) => w('a', d)),
  });
  const weeks = ledgers.a.entries.filter((e) => e.kind === 'week');
  assert.equal(weeks.length, 1);
  assert.equal(weeks[0].date, '2026-11-13');
  assert.equal(ledgers.a.balance, 5);
});

test('deleted workouts earn nothing', () => {
  const { ledgers } = computePoints({
    players, spins: [], today: '2026-11-20',
    workouts: [w('a', '2026-11-10', { deleted_at: '2026-11-10T19:00:00' })],
  });
  assert.equal(ledgers.a.balance, 0);
});

test('monthly winner only for finished months; ties both win', () => {
  const workouts = [w('a', '2026-10-01'), w('a', '2026-10-02'), w('b', '2026-10-05'),
    w('a', '2026-11-03'), w('b', '2026-11-04')];
  const nov = computePoints({ players, workouts, spins: [], today: '2026-11-20' });
  assert.deepEqual(nov.months.map((m) => m.winners), [['a']]);   // October done, November not
  const dec = computePoints({ players, workouts, spins: [], today: '2026-12-01' });
  assert.deepEqual(dec.months[1].winners, ['a', 'b']);          // November tie
  assert.equal(dec.ledgers.b.entries.filter((e) => e.kind === 'month').length, 1);
});

test('spins subtract the spin cost', () => {
  const { ledgers } = computePoints({
    players, today: '2026-11-20', workouts: [w('a', '2026-11-10')],
    spins: [{ id: 's1', user_id: 'a', spun_at: '2026-11-11T10:00:00', cost: 12, prize_name: 'Massage' }],
  });
  assert.equal(ledgers.a.balance, -11);
  assert.equal(ledgers.a.spent, 12);
});

test('target: ~2.5 workouts/week ≈ 1 spin per month', () => {
  // Alternate 2 and 3 workouts per week through a 4-week month + remainder.
  const workouts = [];
  let monday = '2026-06-01';
  for (let wk = 0; wk < 52; wk++) {
    const days = wk % 2 ? [0, 2] : [0, 2, 4];
    days.forEach((d) => workouts.push(w('a', addDays(monday, d))));
    monday = addDays(monday, 7);
  }
  const { ledgers } = computePoints({ players: [players[0]], workouts, spins: [], today: '2027-06-01' });
  const perMonth = (ledgers.a.balance - 12 /* monthly wins, solo player */) / 12;
  const spinsPerMonth = perMonth / RULES.spinCost;
  assert.ok(spinsPerMonth > 0.95 && spinsPerMonth < 1.2, `got ${spinsPerMonth.toFixed(2)} spins/month`);
});
