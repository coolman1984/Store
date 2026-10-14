import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPrivateKey } from 'node:crypto';
import worker from '../src/worker.js';
import { newD1 } from './d1-mock.js';
import { importSigningKey } from '../src/afcodes.js';
import { signSession, SESSION_COOKIE } from '../src/auth.js';
import { deviceKey } from '../src/licence-api.js';

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

function pemFromSeed(seed32) {
  const seed = Buffer.from(seed32);
  const pk = createPrivateKey({
    key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]),
    format: 'der',
    type: 'pkcs8',
  });
  return pk.export({ type: 'pkcs8', format: 'pem' });
}

test('owner paid approve requires session and CSRF', async () => {
  const trialPem = pemFromSeed(Buffer.alloc(32, 1));
  const paidPem = pemFromSeed(Buffer.alloc(32, 2));
  const e = env({
    LICENCE_SIGNING_KEY: trialPem,
    LICENCE_PAID_SIGNING_KEY: paidPem,
  });
  const csrf = 'csrf-paid-approve';
  const exp = Math.floor(Date.now() / 1000) + 3600;
  await e.DB.prepare('INSERT INTO owner_sessions(id, csrf, expires_at) VALUES(?, ?, ?)').bind('s-paid', csrf, exp).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('req-paid', 'h', 'al-store', 'monthly', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), 'm', 'n', '', '', '', 'pending', 1, 1).run();
  const token = await signSession('sess', 's-paid');
  const bad = await worker.fetch(new Request('https://hub.test/owner/api/approve', {
    method: 'POST',
    headers: { Cookie: `${SESSION_COOKIE}=${encodeURIComponent(token)}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: 'req-paid' }),
  }), e);
  assert.equal(bad.status, 403);
  const ok = await worker.fetch(new Request('https://hub.test/owner/api/approve', {
    method: 'POST',
    headers: {
      Cookie: `${SESSION_COOKIE}=${encodeURIComponent(token)}`,
      'Content-Type': 'application/json',
      'X-CSRF-Token': csrf,
      Origin: 'https://hub.test',
    },
    body: JSON.stringify({ id: 'req-paid', csrf }),
  }), e);
  assert.equal(ok.status, 200);
  const data = await ok.json();
  assert.ok(data.ok && data.code);
});
