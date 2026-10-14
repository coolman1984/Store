import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPrivateKey } from 'node:crypto';
import worker from '../src/worker.js';
import { newD1 } from './d1-mock.js';
import { CSRF_COOKIE, signSession } from '../src/auth.js';
import { deviceKey } from '../src/licence-api.js';

function pemFromSeed(seed32) {
  const seed = Buffer.from(seed32);
  const pk = createPrivateKey({
    key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]),
    format: 'der',
    type: 'pkcs8',
  });
  return pk.export({ type: 'pkcs8', format: 'pem' });
}

async function ownerFetch(e, path, { method = 'GET', body = null, csrf = 'owner-csrf' } = {}) {
  const exp = Math.floor(Date.now() / 1000) + 3600;
  await e.DB.prepare('INSERT OR REPLACE INTO owner_sessions(id, csrf, expires_at) VALUES(?, ?, ?)').bind('sess1', csrf, exp).run();
  const token = await signSession(e.SESSION_SECRET, 'sess1');
  const headers = {
    Cookie: `lh_session=${encodeURIComponent(token)}`,
    'Sec-Fetch-Site': 'same-origin',
  };
  if (body) {
    headers['Content-Type'] = 'application/json';
    body.csrf = csrf;
  }
  return worker.fetch(new Request(`https://hub.test${path}`, { method, headers, body: body ? JSON.stringify(body) : undefined }), e);
}

const HEADERS_CHECK = ['Content-Security-Policy', 'Cache-Control', 'X-Content-Type-Options'];

function mockAssets() {
  return {
    fetch(req) {
      const path = new URL(req.url).pathname;
      const body = path.includes('index.html') ? '<html><script src="/owner/index-boot.js"></script></html>' : '/* css */';
      return new Response(body, { headers: { 'Content-Type': 'text/html' } });
    },
  };
}

function env(over = {}) {
  return {
    DB: newD1(),
    ASSETS: mockAssets(),
    SESSION_SECRET: 'sess',
    ...over,
  };
}

test('owner dashboard is served at /owner/ with security headers', async () => {
  const e = env();
  await e.DB.prepare('INSERT INTO owner_sessions(id, csrf, expires_at) VALUES(?, ?, ?)').bind('s1', 'c', Math.floor(Date.now() / 1000) + 3600).run();
  const token = await import('../src/auth.js').then((m) => m.signSession('sess', 's1'));
  const req = new Request('https://hub.test/owner/', {
    headers: { Cookie: `lh_session=${encodeURIComponent(token)}` },
  });
  const res = await worker.fetch(req, e);
  assert.equal(res.status, 200);
  for (const h of HEADERS_CHECK) assert.ok(res.headers.get(h), h);
  assert.ok(!String(await res.text()).includes('import {'), 'no inline module bootstrap');
});

test('logout without session does not send clearing Set-Cookie', async () => {
  const e = env();
  const res = await worker.fetch(new Request('https://hub.test/owner/logout', { method: 'POST' }), e);
  assert.equal(res.status, 303);
  assert.equal(res.headers.get('Set-Cookie'), null);
});

test('/owner/index.html redirects to /owner/', async () => {
  const e = env();
  const res = await worker.fetch(new Request('https://hub.test/owner/index.html'), e);
  assert.equal(res.status, 308);
  assert.equal(res.headers.get('Location'), 'https://hub.test/owner/');
});

test('public calendar limits each IP to 120 requests per ten minutes without D1 or secrets', async (t) => {
  let nowMs = 600 * 1000 * 3000000 + 1000;
  t.mock.method(Date, 'now', () => nowMs);
  const e = {
    get DB() { assert.fail('time must not use D1'); },
    get SESSION_SECRET() { assert.fail('time must not read session secrets'); },
  };
  const request = (ip, suffix = '') => new Request('https://hub.test/licence/time' + suffix, {
    headers: { 'CF-Connecting-IP': ip, 'X-Forwarded-For': crypto.randomUUID() },
  });
  for (let i = 0; i < 120; i++) {
    const res = await worker.fetch(request('192.0.2.1'), e);
    assert.equal(res.status, 200);
    const body = await res.json();
    assert.ok(body.calendar_day);
    assert.ok('kid' in body || !('sig' in body));
  }
  const blocked = await worker.fetch(request('192.0.2.1', '?retry=1'), e);
  assert.equal(blocked.status, 429);
  assert.deepEqual(await blocked.json(), { error: 'rate' });
  assert.equal(blocked.headers.get('Retry-After'), '599');
  for (const h of HEADERS_CHECK) assert.ok(blocked.headers.get(h), h);
  assert.equal(blocked.headers.get('Cache-Control'), 'no-store');
  assert.equal((await worker.fetch(request('192.0.2.2'), e)).status, 200);
  nowMs += 598 * 1000;
  assert.equal((await worker.fetch(request('192.0.2.1'), e)).status, 429);
  nowMs += 1000;
  assert.equal((await worker.fetch(request('192.0.2.1'), e)).status, 200);
});

test('GET /owner/api/products is allowed before POST-only gate', async () => {
  const e = env({ LICENCE_PRODUCTS: 'trip-orders,al-store' });
  const res = await ownerFetch(e, '/owner/api/products');
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.deepEqual([...data.products].sort(), ['al-store', 'trip-orders']);
});

test('GET /owner/api/capabilities returns per-product paid flags', async () => {
  const e = env({
    LICENCE_PRODUCTS: 'trip-orders,al-store',
    PAID_SIGNING_KEY_AL_STORE: pemFromSeed(Buffer.alloc(32, 93)),
  });
  const res = await ownerFetch(e, '/owner/api/capabilities');
  const data = await res.json();
  assert.equal(data.products['trip-orders'].paid_available, false);
  assert.equal(data.products['al-store'].paid_available, true);
});

test('GET /owner/api/customers lists one row per device and product', async () => {
  const e = env({ LICENCE_PRODUCTS: 'trip-orders,al-store' });
  const device = 'ABCD2EFGH3';
  const dkey = deviceKey(device);
  const t = 10;
  for (const [cid, product] of [['cust-to', 'trip-orders'], ['cust-al', 'al-store']]) {
    await e.DB.prepare(
      'INSERT INTO customers(id, product, shop, device, kind, licence_tier, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)',
    ).bind(cid, product, 'Shop', device, 'trial', 'trial', t).run();
  }
  for (const [id, product] of [['c1', 'trip-orders'], ['c2', 'al-store']]) {
    await e.DB.prepare(
      'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, licence_tier, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(id, 'h' + id, product, 'trial', device, dkey, 'a'.repeat(64), 'n' + id, 'Shop', '', '', 'issued', 'CODE-' + product, 'trial', t, t + 1).run();
  }
  const res = await ownerFetch(e, '/owner/api/customers');
  const data = await res.json();
  const products = (data.items || []).filter((i) => i.device === device).map((i) => i.product).sort();
  assert.deepEqual(products, ['al-store', 'trip-orders']);
});

test('owner offline API signs with the product sent in the body', async () => {
  const e = env({
    LICENCE_PRODUCTS: 'trip-orders,al-store',
    LICENCE_SIGNING_KEY_AL_STORE: pemFromSeed(Buffer.alloc(32, 92)),
  });
  const res = await ownerFetch(e, '/owner/api/offline', {
    method: 'POST',
    body: {
      device: 'ABCD2EFGH3',
      shop: 'متجر',
      product: 'al-store',
      grant: 'trial',
    },
  });
  assert.equal(res.status, 200);
  const data = await res.json();
  assert.ok(data.code);
  const row = await e.DB.prepare('SELECT product FROM licence_requests WHERE device_key = ? ORDER BY created_at DESC LIMIT 1')
    .bind(deviceKey('ABCD2EFGH3')).first();
  assert.equal(row.product, 'al-store');
});

test('owner approve paid without PAID_SIGNING_KEY returns 503 and keeps pending', async () => {
  const e = env({ LICENCE_SIGNING_KEY: pemFromSeed(Buffer.alloc(32, 97)) });
  const device = 'ABCD2EFGH3';
  const dkey = deviceKey(device);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('req-paid-miss', 'h', 'trip-orders', 'monthly', device, dkey, 'a'.repeat(64), 'n', 'Shop', '', '', 'pending', 1, 1).run();
  const res = await ownerFetch(e, '/owner/api/approve', {
    method: 'POST',
    body: { id: 'req-paid-miss', grant: 'paid', paid_until: '2028-06-01' },
  });
  assert.equal(res.status, 503);
  assert.deepEqual(await res.json(), { error: 'paid_key_missing' });
  const row = await e.DB.prepare('SELECT status FROM licence_requests WHERE id = ?').bind('req-paid-miss').first();
  assert.equal(row.status, 'pending');
});

test('calendar limiter bounds stored IPs and frees them at the next window', async (t) => {
  let nowMs = 600 * 1000 * 3000010;
  t.mock.method(Date, 'now', () => nowMs);
  const request = (ip) => new Request('https://hub.test/licence/time', {
    headers: { 'CF-Connecting-IP': ip },
  });
  for (let i = 0; i < 5000; i++) {
    assert.equal((await worker.fetch(request(`test-ip-${i}`), {})).status, 200);
  }
  assert.equal((await worker.fetch(request('new-ip'), {})).status, 429);
  assert.equal((await worker.fetch(request('test-ip-0'), {})).status, 200);
  nowMs += 600 * 1000;
  assert.equal((await worker.fetch(request('new-ip'), {})).status, 200);
});
