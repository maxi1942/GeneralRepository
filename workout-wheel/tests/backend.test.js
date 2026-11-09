// Tests the real google-sheets/Code.gs against an in-memory fake of Google's services.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { loadBackend } from './gas-mock.js';

function ready() {
  const b = loadBackend();
  b.ctx.setup();
  const players = b.sheets.get('Players').rows;
  players[1][2] = 'max-secret';
  players[2][2] = 'sam-secret';
  return b;
}
const today = () => new Date().toISOString().slice(0, 10);
const daysAgo = (n) => new Date(Date.now() - n * 864e5).toISOString().slice(0, 10);

test('setup creates the tabs, two players and starter prizes', () => {
  const b = ready();
  assert.deepEqual([...b.sheets.keys()].sort(), ['Players', 'Prizes', 'Spins', 'Workouts']);
  assert.equal(b.sheets.get('Players').rows.length, 3);
  assert.equal(b.sheets.get('Prizes').rows.length, 6);
  b.ctx.setup(); // running twice must not duplicate anything
  assert.equal(b.sheets.get('Players').rows.length, 3);
});

test('wrong or missing passcode is rejected; passcodes are never sent back', () => {
  const b = ready();
  assert.equal(b.post({ action: 'load' }).error, 'BAD_PASSCODE');
  assert.equal(b.post({ action: 'load', passcode: 'nope' }).error, 'BAD_PASSCODE');
  const { me } = b.post({ action: 'login', passcode: ' max-secret ' });
  assert.equal(me.name, 'Max');
  const state = b.post({ action: 'load', passcode: 'sam-secret' });
  assert.ok(!JSON.stringify(state).includes('secret'));
});

test('log, backdate limit, photo, and delete-own-only', () => {
  const b = ready();
  let s = b.post({ action: 'addWorkout', passcode: 'max-secret', workout_date: today(), activity: 'Gym', note: 'legs' });
  assert.equal(s.workouts.length, 1);
  assert.equal(s.workouts[0].workout_date, today());
  assert.equal(s.workouts[0].deleted_at, null);

  assert.match(b.post({ action: 'addWorkout', passcode: 'max-secret', workout_date: daysAgo(30) }).error, /within the last/);
  assert.match(b.post({ action: 'addWorkout', passcode: 'max-secret', workout_date: 'tomorrow' }).error, /Invalid date/);

  s = b.post({ action: 'addWorkout', passcode: 'max-secret', workout_date: daysAgo(3), photo: Buffer.from('jpegdata').toString('base64'), photo_mime: 'image/jpeg' });
  assert.equal(b.files.length, 1);
  assert.equal(b.files[0].sharing, 'link');
  assert.equal(s.workouts[1].photo_path, 'file1');

  const id = s.workouts[0].id;
  assert.match(b.post({ action: 'deleteWorkout', passcode: 'sam-secret', id }).error, /own workouts/);
  s = b.post({ action: 'deleteWorkout', passcode: 'max-secret', id });
  assert.ok(s.workouts[0].deleted_at);
});

test('prizes: add, odds, archive; spins and marking used', () => {
  const b = ready();
  let s = b.post({ action: 'addPrize', passcode: 'sam-secret', name: 'Lie-in', emoji: '😴' });
  const prize = s.prizes.find((p) => p.name === 'Lie-in');
  assert.equal(prize.weight, 1);
  assert.equal(prize.active, true);
  s = b.post({ action: 'updatePrize', passcode: 'sam-secret', id: prize.id, weight: 99 });
  assert.equal(s.prizes.find((p) => p.id === prize.id).weight, 10);
  s = b.post({ action: 'updatePrize', passcode: 'sam-secret', id: prize.id, active: false });
  assert.equal(s.prizes.find((p) => p.id === prize.id).active, false);

  s = b.post({ action: 'addSpin', passcode: 'sam-secret', prize_id: prize.id, cost: 12 });
  assert.equal(s.spins[0].prize_name, 'Lie-in');
  assert.equal(s.spins[0].cost, 12);
  assert.equal(s.spins[0].used_at, null);
  s = b.post({ action: 'setUsed', passcode: 'max-secret', id: s.spins[0].id, used: true });
  assert.ok(s.spins[0].used_at);
  s = b.post({ action: 'setUsed', passcode: 'max-secret', id: s.spins[0].id, used: false });
  assert.equal(s.spins[0].used_at, null);
});

test('a numeric passcode typed into the sheet still works', () => {
  const b = ready();
  b.sheets.get('Players').rows[1][2] = 482915; // Sheets may store it as a number
  assert.equal(b.post({ action: 'login', passcode: '482915' }).me.name, 'Max');
});
