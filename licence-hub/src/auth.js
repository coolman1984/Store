const enc = new TextEncoder();
const SESSION_COOKIE = 'lh_session';
const CSRF_COOKIE = 'lh_csrf';

export { SESSION_COOKIE, CSRF_COOKIE };

const now = () => Math.floor(Date.now() / 1000);

export function hex(buf) {
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

async function hmac(secret, msg) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', key, enc.encode(msg)));
}

export async function verifyPassword(password, stored) {
  const parts = String(stored || '').split(':');
  if (parts.length !== 4 || parts[0] !== 'pbkdf2-sha256') return false;
  const iter = Number(parts[1]);
  const salt = Uint8Array.from(parts[2].match(/.{2}/g).map((h) => parseInt(h, 16)));
  const expect = parts[3].toLowerCase();
  const key = await crypto.subtle.importKey('raw', enc.encode(password), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', salt, iterations: iter, hash: 'SHA-256' }, key, 256);
  const got = hex(bits);
  if (got.length !== expect.length) return false;
  let d = 0;
  for (let i = 0; i < got.length; i++) d |= got.charCodeAt(i) ^ expect.charCodeAt(i);
  return d === 0;
}

export function parseCookies(request) {
  const out = {};
  const raw = request.headers.get('Cookie') || '';
  raw.split(';').forEach((p) => {
    const i = p.indexOf('=');
    if (i > 0) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}

export function cookieHeader(name, value, maxAge, secure = true) {
  const bits = [`${name}=${encodeURIComponent(value)}`, 'Path=/', 'HttpOnly', 'SameSite=Strict'];
  if (secure) bits.push('Secure');
  if (maxAge != null) bits.push(`Max-Age=${maxAge}`);
  return bits.join('; ');
}

export async function signSession(sessionSecret, sessionId) {
  return `${sessionId}.${await hmac(sessionSecret, sessionId)}`;
}

export async function verifySession(sessionSecret, token) {
  if (!token || !token.includes('.')) return null;
  const [id, sig] = token.split('.', 2);
  const expect = await hmac(sessionSecret, id);
  if (sig.length !== expect.length) return null;
  let d = 0;
  for (let i = 0; i < sig.length; i++) d |= sig.charCodeAt(i) ^ expect.charCodeAt(i);
  return d === 0 ? id : null;
}

export async function loginLimited(env, ip) {
  const w = Math.floor(now() / 3600);
  const r = await env.DB.prepare('INSERT INTO login_attempts(ip, window, count) VALUES(?, ?, 1) ON CONFLICT(ip, window) DO UPDATE SET count = count + 1 RETURNING count').bind(ip, w).first();
  return r.count > 20;
}

export async function loadSession(env, sessionSecret, request) {
  const cookies = parseCookies(request);
  const id = await verifySession(sessionSecret, cookies[SESSION_COOKIE]);
  if (!id) return null;
  const row = await env.DB.prepare('SELECT id, csrf, expires_at FROM owner_sessions WHERE id = ?').bind(id).first();
  if (!row || row.expires_at < now()) return null;
  return row;
}

export function originAllowed(request) {
  const url = new URL(request.url);
  const origin = request.headers.get('Origin');
  if (origin) return origin === url.origin;
  const site = request.headers.get('Sec-Fetch-Site');
  if (site === 'same-origin' || site === 'same-site') return true;
  const referer = request.headers.get('Referer');
  if (referer) {
    try {
      return new URL(referer).origin === url.origin;
    } catch {
      return false;
    }
  }
  return false;
}

/** CSRF token must be in header or JSON body; cookie alone is not enough. */
export function csrfOk(session, request, body) {
  const header = request.headers.get('X-CSRF-Token') || '';
  const form = body && typeof body.csrf === 'string' ? body.csrf : '';
  const token = header || form;
  if (!token || !session.csrf || token !== session.csrf) return false;
  return originAllowed(request);
}

export async function createSession(env, sessionSecret, hours) {
  const id = crypto.randomUUID();
  const csrf = hex(crypto.getRandomValues(new Uint8Array(16)));
  const expires = now() + hours * 3600;
  await env.DB.prepare('INSERT INTO owner_sessions(id, csrf, expires_at) VALUES(?, ?, ?)').bind(id, csrf, expires).run();
  const signed = await signSession(sessionSecret, id);
  return { signed, csrf, expires };
}

export async function destroySession(env, sessionId) {
  await env.DB.prepare('DELETE FROM owner_sessions WHERE id = ?').bind(sessionId).run();
}
