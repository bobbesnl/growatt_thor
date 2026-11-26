/** Explicit installation-zone wall clocks; absolute timestamps always carry an offset. */
export function browserTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

export function localDateTimeInZone(date: Date, timeZone: string): string {
  const fields = Object.fromEntries(
    new Intl.DateTimeFormat('en-CA', {
      timeZone,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      hourCycle: 'h23',
    })
      .formatToParts(date)
      .map(({ type, value }) => [type, value]),
  );
  return `${fields.year}-${fields.month}-${fields.day}T${fields.hour}:${fields.minute}`;
}

export function calendarDay(timestamp: number, timeZone = 'UTC'): string {
  return localDateTimeInZone(new Date(timestamp), timeZone).slice(0, 10);
}

export function localTimeToUtc(value: string, timeZone: string): string | null {
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(value)) return null;
  const wall = Date.parse(`${value}Z`);
  if (!Number.isFinite(wall) || new Date(wall).toISOString().slice(0, 16) !== value) return null;
  // Offsets on either side of the date capture DST changes, including half-hour
  // transitions. Round trips reject gaps and more than one match rejects folds.
  const offsets = new Set<number>();
  for (const hours of [-36, -12, 0, 12, 36]) {
    const sample = wall + hours * 3600000;
    offsets.add(Date.parse(`${localDateTimeInZone(new Date(sample), timeZone)}Z`) - sample);
  }
  const candidates = [...offsets]
    .map((offset) => wall - offset)
    .filter((timestamp) => localDateTimeInZone(new Date(timestamp), timeZone) === value);
  return candidates.length === 1 ? new Date(candidates[0]).toISOString() : null;
}
