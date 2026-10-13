import { test } from 'node:test';
import assert from 'node:assert/strict';
import worker from '../src/worker.js';
import { newD1 } from './d1-mock.js';

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
