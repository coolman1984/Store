/** Calendar-day helpers — same semantics as the office reader (local business calendar, default Africa/Cairo). */

export const DEFAULT_CALENDAR_TZ = 'Africa/Cairo';

/** YYYY-MM-DD for the given instant in `timeZone` (IANA). */
export function calendarDateInTz(when = new Date(), timeZone = DEFAULT_CALENDAR_TZ) {
  const iso = when.toLocaleDateString('en-CA', { timeZone });
  const [y, m, d] = iso.split('-').map(Number);
  return { year: y, month: m - 1, day: d, iso };
}

/** Add whole calendar days to a YYYY-MM-DD string (no DST surprises for Cairo-style zones). */
export function addCalendarDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number);
  const t = Date.UTC(y, m - 1, d);
  const end = new Date(t + (days - 1) * 86400000);
  return end.toISOString().slice(0, 10);
}
