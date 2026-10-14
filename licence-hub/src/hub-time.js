/** Signed hub business calendar day — verified by the shop app (trial-hub or paid kid). */
const enc = new TextEncoder();

function b64url(buf) {
  const b = typeof buf === 'string' ? enc.encode(buf) : buf;
  let s = '';
  for (const byte of b) s += String.fromCharCode(byte);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

export function hubTimeMessage(calendarDay, kid) {
  return `AF-LICENCE-HUB-TIME/1|${calendarDay}|${kid}`;
}

/** @returns {{ calendar_day: string, kid: string, sig: string }} */
export async function signHubCalendar(privateKey, kid, calendarDay) {
  const msg = enc.encode(hubTimeMessage(calendarDay, kid));
  const sig = new Uint8Array(await crypto.subtle.sign('Ed25519', privateKey, msg));
  return { calendar_day: calendarDay, kid, sig: b64url(sig) };
}
