import { test } from 'node:test';
import assert from 'node:assert/strict';
import { addCalendarMonths, isValidCalendarIso } from '../src/calendar.js';

test('addCalendarMonths clamps Jan 31 to February end', () => {
  assert.equal(addCalendarMonths('2026-01-31', 1), '2026-02-28');
  assert.equal(addCalendarMonths('2024-01-31', 1), '2024-02-29');
});

test('isValidCalendarIso rejects impossible dates', () => {
  assert.equal(isValidCalendarIso('2026-02-31'), false);
  assert.equal(isValidCalendarIso('2026-02-28'), true);
});
