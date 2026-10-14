import { handleLicence, approveRequest, refuseRequest, issueOfflineCustomer, purgeStaleCodes, REASON_PAID_IN_STUDIO } from './licence-api.js';
import { importSigningKey } from './afcodes.js';
import {
  SESSION_COOKIE, CSRF_COOKIE, verifyPassword, parseCookies, cookieHeader, loadSession, createSession,
  destroySession, loginLimited, csrfOk,
} from './auth.js';

const HEADERS = {
  'X-Content-Type-Options': 'nosniff',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'self'; img-src 'self' data:; connect-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'",
  'Cache-Control': 'no-store',
};

const now = () => Math.floor(Date.now() / 1000);

function withSecurityHeaders(response) {
  const headers = new Headers(response.headers);
  Object.entries(HEADERS).forEach(([k, v]) => headers.set(k, v));
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function html(body, status = 200, extra = {}) {
  return new Response(body, { status, headers: { ...HEADERS, 'Content-Type': 'text/html; charset=utf-8', ...extra } });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), { status, headers: { ...HEADERS, 'Content-Type': 'application/json; charset=utf-8' } });
}

async function fetchOwnerAsset(env, request, url) {
  const res = await env.ASSETS.fetch(request);
  return withSecurityHeaders(res);
}

async function signingKey(env) {
  if (!env.LICENCE_SIGNING_KEY) throw new Error('no_signing_key');
  return importSigningKey(env.LICENCE_SIGNING_KEY);
}

async function resolvePaidSigningKey(env) {
  if (!env.LICENCE_PAID_SIGNING_KEY) return { key: null, invalid: false };
  try {
    return { key: await importSigningKey(env.LICENCE_PAID_SIGNING_KEY), invalid: false };
  } catch {
    return { key: null, invalid: true };
  }
}

async function ownerApi(request, env, url, session) {
  const path = url.pathname.replace(/^\/owner\/api/, '') || '/';

  if (path === '/session' && request.method === 'GET') {
    return json({ csrf: session.csrf, expires: session.expires_at });
  }
  if (path === '/pending' && request.method === 'GET') {
    const rows = await env.DB.prepare(
      "SELECT r.id, r.kind, r.shop, r.device, r.machine, r.version, r.created_at, CASE WHEN c.id IS NOT NULL THEN 1 ELSE 0 END AS has_customer FROM licence_requests r LEFT JOIN customers c ON c.device = r.device WHERE r.status IN ('pending', 'approved') ORDER BY r.created_at ASC LIMIT 50",
    ).all();
    return json({ items: rows.results || [] });
  }
  if (path === '/customers' && request.method === 'GET') {
    const rows = await env.DB.prepare('SELECT shop, device, kind, first_day, last_day, created_at FROM customers ORDER BY created_at DESC LIMIT 200').all();
    const items = (rows.results || []).map((r) => {
      let daysLeft = null;
      if (r.last_day) {
        const end = Date.parse(r.last_day + 'T12:00:00Z');
        daysLeft = Math.max(0, Math.floor((end - Date.now()) / 86400000) + 1);
      }
      return { ...r, days_left: daysLeft };
    });
    return json({ items });
  }

  if (request.method !== 'POST') return json({ error: 'method' }, 405);
  let body = {};
  try { body = await request.json(); } catch { body = {}; }
  if (!csrfOk(session, request, body)) return json({ error: 'csrf' }, 403);

  if (path === '/approve') {
    const key = await signingKey(env);
    const paid = await resolvePaidSigningKey(env);
    try {
      const signed = await approveRequest(env, body.id, key, {
        force: body.force === true,
        paidPrivateKey: paid.key,
        paidSigningInvalid: paid.invalid,
      });
      if (!signed) return json({ error: 'not_found' }, 404);
      if (signed.refused) {
        return json({ error: signed.reason || REASON_PAID_IN_STUDIO, message: 'paid_in_studio' }, 400);
      }
      if (signed.conflict) {
        return json({ error: 'already_used', code: signed.code, request_id: signed.existing_request_id }, 409);
      }
      return json({ ok: true, code: signed.code });
    } catch (e) {
      if (e?.message === 'bad_device_code') return json({ error: 'bad_device', message: e.message }, 400);
      throw e;
    }
  }
  if (path === '/refuse') {
    await refuseRequest(env, body.id, body.reason || 'refused');
    return json({ ok: true });
  }
  if (path === '/offline') {
    const device = String(body.device || '').trim();
    const shop = String(body.shop || '').trim();
    if (!device) return json({ error: 'device' }, 400);
    const key = await signingKey(env);
    try {
      const product = String(env.LICENCE_PRODUCTS || 'al-store').split(',')[0].trim() || 'al-store';
      const signed = await issueOfflineCustomer(env, key, device, shop, product, { force: body.force === true });
      if (signed.conflict) {
        return json({ error: 'already_used', code: signed.code, request_id: signed.existing_request_id }, 409);
      }
      return json({ ok: true, code: signed.code, device: signed.device });
    } catch (e) {
      if (e?.message === 'already_used') return json({ error: 'already_used' }, 400);
      if (e?.message === 'bad_device_code') return json({ error: 'bad_device' }, 400);
      throw e;
    }
  }
  return json({ error: 'not_found' }, 404);
}

const PUBLIC_OWNER_PATHS = new Set([
  '/owner/login.html',
  '/owner/login.js',
  '/owner/style.css',
]);

async function ownerPages(request, env, url) {
  const sessionSecret = env.SESSION_SECRET;
  if (!sessionSecret) return html('<p>SESSION_SECRET missing</p>', 503);

  if (url.pathname === '/owner/login' && request.method === 'POST') {
    const ip = request.headers.get('CF-Connecting-IP') || 'local';
    if (await loginLimited(env, ip)) return html('<p>Too many attempts</p>', 429);
    const form = await request.formData();
    const password = String(form.get('password') || '');
    if (!env.OWNER_PASSWORD_HASH || !(await verifyPassword(password, env.OWNER_PASSWORD_HASH))) {
      return Response.redirect(new URL('/owner/login.html?bad=1', url.origin).toString(), 303);
    }
    const hours = Number(env.SESSION_HOURS || 8);
    const sess = await createSession(env, sessionSecret, hours);
    const loginHeaders = new Headers({ Location: '/owner/' });
    loginHeaders.append('Set-Cookie', cookieHeader(SESSION_COOKIE, sess.signed, hours * 3600));
    loginHeaders.append('Set-Cookie', cookieHeader(CSRF_COOKIE, sess.csrf, hours * 3600, false));
    return new Response(null, { status: 303, headers: loginHeaders });
  }

  if (url.pathname === '/owner/logout' && request.method === 'POST') {
    const session = await loadSession(env, sessionSecret, request);
    if (session) await destroySession(env, session.id);
    const headers = { Location: '/owner/login.html' };
    if (session) headers['Set-Cookie'] = cookieHeader(SESSION_COOKIE, '', 0);
    return new Response(null, { status: 303, headers });
  }

  if (url.pathname.startsWith('/owner/api/')) {
    const session = await loadSession(env, sessionSecret, request);
    if (!session) return json({ error: 'auth' }, 401);
    return ownerApi(request, env, url, session);
  }

  if (url.pathname === '/owner/index.html') {
    return Response.redirect(new URL('/owner/', url.origin).toString(), 308);
  }

  if (url.pathname === '/owner/' || url.pathname === '/owner/customers.html' || url.pathname === '/owner/offline.html') {
    const session = await loadSession(env, sessionSecret, request);
    if (!session) return Response.redirect(new URL('/owner/login.html', url.origin).toString(), 302);
    const assetPath = url.pathname === '/owner/' ? '/owner/index.html' : url.pathname;
    return fetchOwnerAsset(env, new Request(new URL(assetPath, url.origin)), url);
  }

  if (url.pathname.startsWith('/owner/')) {
    if (PUBLIC_OWNER_PATHS.has(url.pathname)) {
      return fetchOwnerAsset(env, request, url);
    }
    const session = await loadSession(env, sessionSecret, request);
    if (!session) return Response.redirect(new URL('/owner/login.html', url.origin).toString(), 302);
    return fetchOwnerAsset(env, request, url);
  }
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    try {
      if (url.pathname.startsWith('/licence/')) {
        const res = await handleLicence(request, env, url);
        if (res) {
          Object.entries(HEADERS).forEach(([k, v]) => res.headers.set(k, v));
          return res;
        }
      }
      const owner = await ownerPages(request, env, url);
      if (owner) return owner;
      if (url.pathname === '/') return html('<p>Trip Orders licence hub</p>');
      return new Response('Not found', { status: 404, headers: HEADERS });
    } catch (e) {
      return json({ error: 'server' }, 500);
    }
  },
  async scheduled(event, env) {
    await purgeStaleCodes(env);
  },
};
