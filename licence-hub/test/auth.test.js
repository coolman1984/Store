import { test } from 'node:test';
import assert from 'node:assert/strict';
import { csrfOk, originAllowed, CSRF_COOKIE, parseCookies } from '../src/auth.js';

const session = { csrf: 'abc123' };

function req(url, headers = {}, body = null) {
  return {
    url,
    headers: new Map(Object.entries(headers)),
    get(h) { return this.headers.get(h) ?? null; },
  };
}

test('csrf rejects cookie-only token', () => {
  const r = req('https://hub.example/owner/api/approve', { Cookie: `${CSRF_COOKIE}=abc123` });
  assert.equal(csrfOk(session, r, {}), false);
});

test('csrf accepts header with same-origin', () => {
  const r = req('https://hub.example/owner/api/approve', {
    Origin: 'https://hub.example',
    'X-CSRF-Token': 'abc123',
  });
  assert.equal(csrfOk(session, r, {}), true);
});

test('csrf accepts body token with Sec-Fetch-Site same-origin', () => {
  const r = req('https://hub.example/owner/api/refuse', { 'Sec-Fetch-Site': 'same-origin' });
  assert.equal(csrfOk(session, r, { csrf: 'abc123' }), true);
});

test('csrf rejects cross-origin without matching Origin', () => {
  const r = req('https://hub.example/owner/api/approve', {
    Origin: 'https://evil.example',
    'X-CSRF-Token': 'abc123',
  });
  assert.equal(csrfOk(session, r, {}), false);
});

test('originAllowed matches Origin header', () => {
  const r = req('https://hub.example/x', { Origin: 'https://hub.example' });
  assert.equal(originAllowed(r), true);
});
