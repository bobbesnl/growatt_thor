import assert from 'node:assert/strict';
import { test } from 'node:test';
import { localTimeToUtc } from '../src/shared/time';
import { localDateTime, nextMinuteDateTime, futureStart } from '../src/targets/model';
import {
  formatSessionDate,
  formatSessionPeriod,
  formatSessionChartTick,
  sessionChartSpansDaysInZone,
  sessionTimestamp,
} from '../src/sessions/model';

test('HA time controls target entry, list, curve and events independently of browser zone', () => {
  const previous = process.env.TZ;
  try {
    for (const browser of ['Pacific/Honolulu', 'Asia/Tokyo', 'Europe/Berlin']) {
      process.env.TZ = browser;
      const instant = '2026-07-01T08:00:00Z';
      assert.equal(localTimeToUtc('2026-07-01T10:00', 'Europe/Berlin'), '2026-07-01T08:00:00.000Z');
      assert.equal(localDateTime(new Date(instant), 'Europe/Berlin'), '2026-07-01T10:00');
      assert.equal(nextMinuteDateTime(new Date(instant), 'Europe/Berlin'), '2026-07-01T10:01');
      assert.equal(futureStart('2026-07-01T10:01', Date.parse(instant), 'Europe/Berlin'), true);
      assert.match(formatSessionDate(instant, 'de', 'Europe/Berlin'), /10:00/);
      assert.equal(
        formatSessionChartTick(Date.parse(instant), 'de', false, 'Europe/Berlin'),
        '10:00',
      );
      const period = formatSessionPeriod(
        '2026-07-01T21:30:00Z',
        '2026-07-01T22:30:00Z',
        'de',
        'Europe/Berlin',
      );
      assert.equal(period.day, null);
      assert.equal(
        sessionChartSpansDaysInZone(
          'Europe/Berlin',
          [
            [Date.parse('2026-07-01T21:30:00Z'), 1],
            [Date.parse('2026-07-01T22:30:00Z'), 1],
          ],
          [],
        ),
        true,
      );
    }
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
});

test('local target input rejects nonexistent and ambiguous wall clocks', () => {
  assert.equal(localTimeToUtc('2026-03-29T02:30', 'Europe/Berlin'), null);
  assert.equal(localTimeToUtc('2026-10-25T02:30', 'Europe/Berlin'), null);
  assert.equal(localTimeToUtc('2026-02-30T12:00', 'Europe/Berlin'), null);
  assert.equal(localTimeToUtc('2026-01-01T10:00', 'Europe/Berlin'), '2026-01-01T09:00:00.000Z');
  assert.equal(localTimeToUtc('2026-10-04T02:15', 'Australia/Lord_Howe'), null);
});

test('session instants require an explicit offset while both DST fold offsets stay distinct', () => {
  assert.equal(sessionTimestamp('2026-10-25T02:30:00'), null);
  assert.equal(sessionTimestamp('2026-10-25 02:30:00'), null);
  assert.equal(
    sessionTimestamp('2026-10-25T02:30:00+01:00')! - sessionTimestamp('2026-10-25T02:30:00+02:00')!,
    3600000,
  );
});
