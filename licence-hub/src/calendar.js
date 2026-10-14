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

function daysInMonth(year, month1to12) {
  return new Date(Date.UTC(year, month1to12, 0)).getUTCDate();
}

/** True when `iso` is a real calendar date (rejects e.g. 2026-02-31). */
export function isValidCalendarIso(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
  const [y, m, d] = iso.split('-').map(Number);
  if (m < 1 || m > 12 || d < 1) return false;
  return d <= daysInMonth(y, m);
}

/** Add calendar months; clamp day to the last day of the target month (31 Jan + 1 → Feb 28/29). */
export function addCalendarMonths(iso, months) {
  const [y, m, d] = iso.split('-').map(Number);
  let year = y;
  let month = m - 1 + months;
  year += Math.floor(month / 12);
  month = ((month % 12) + 12) % 12;
  const last = daysInMonth(year, month + 1);
  const day = Math.min(d, last);
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}
