import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createPrivateKey } from 'node:crypto';
import { newD1 } from './d1-mock.js';
import {
  handleLicence, approveRequest, refuseRequest, issueOfflineCustomer, derivePollToken, purgeStaleCodes,
  deviceKey, deviceLockKey, machineLockKey, REASON_PAID_IN_STUDIO,
} from '../src/licence-api.js';
import { importSigningKey } from '../src/afcodes.js';

const SECRET = 'test-session-secret-0123456789abcdef';
const MACHINE_A = 'a'.repeat(64);
const MACHINE_B = 'b'.repeat(64);

function pemFromSeed(seed32) {
  const seed = Buffer.from(seed32);
  const pk = createPrivateKey({
    key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]),
    format: 'der',
    type: 'pkcs8',
  });
  return pk.export({ type: 'pkcs8', format: 'pem' });
}

function env() {
  return {
    DB: newD1(),
    SESSION_SECRET: SECRET,
    LICENCE_PRODUCTS: 'al-store',
    TRIAL_DAYS: '14',
    LICENCE_CALENDAR_TZ: 'Africa/Cairo',
    PENDING_TTL_SEC: '900',
  };
}

function body(over = {}) {
  return {
    product: 'al-store',
    kind: 'trial',
    device: '7KD2M-QX9TP',
    machine: MACHINE_A,
    nonce: 'nonce-' + crypto.randomUUID(),
    shop: 'Shop',
    ref: 'ref',
    version: '1.0',
    ...over,
  };
}

async function postRequest(e, payload) {
  const req = new Request('https://hub.test/licence/request', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'CF-Connecting-IP': '1.2.3.4' },
    body: JSON.stringify(payload),
  });
  const res = await handleLicence(req, e, new URL(req.url));
  return { res, data: await res.json() };
}

async function getStatus(e, id, poll) {
  const req = new Request('https://hub.test/licence/status?id=' + id, {
    method: 'GET',
    headers: { Authorization: 'Bearer ' + poll },
  });
  const res = await handleLicence(req, e, new URL(req.url));
  return { res, data: await res.json() };
}

test('monthly and permanent requests are refused at submit', async () => {
  const e = env();
  for (const kind of ['monthly', 'permanent']) {
    const { data } = await postRequest(e, body({ kind }));
    assert.equal(data.status, 'refused');
    assert.equal(data.reason, REASON_PAID_IN_STUDIO);
    assert.ok(data.poll_token);
  }
});

test('nonce replay returns the same poll token', async () => {
  const e = env();
  const payload = body();
  const first = await postRequest(e, payload);
  const second = await postRequest(e, payload);
  assert.equal(second.data.replay, true);
  assert.equal(second.data.poll_token, first.data.poll_token);
  assert.equal(second.data.id, first.data.id);
});

test('only one trial wins on concurrent approval for the same device', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 9)));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('a', 'h1', 'al-store', 'trial', device, dkey, MACHINE_A, 'n1', '', '', '', 'pending', t, t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('b', 'h2', 'al-store', 'trial', device, dkey, MACHINE_B, 'n2', '', '', '', 'pending', t, t).run();
  const [signedA, signedB] = await Promise.all([approveRequest(e, 'a', key), approveRequest(e, 'b', key)]);
  assert.ok(signedA?.code);
  assert.ok(signedB?.code);
  assert.equal(signedA.code, signedB.code);
  const fresh = [signedA, signedB].filter((s) => s?.code && !s?.conflict);
  assert.equal(fresh.length, 1);
  const rowA = await e.DB.prepare('SELECT status FROM licence_requests WHERE id = ?').bind('a').first();
  assert.equal(rowA.status, 'issued');
});

test('second online trial for same machine hash is refused after install_id wipe (new device code)', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 7)));
  const first = await postRequest(e, body({ device: '7KD2M-QX9TP', machine: MACHINE_A, nonce: 'n1' }));
  await approveRequest(e, first.data.id, key);
  const second = await postRequest(e, body({ device: 'ABCDE-FGHJK', machine: MACHINE_A, nonce: 'n2' }));
  assert.equal(second.data.status, 'refused');
  assert.equal(second.data.reason, 'already_used');
});

test('offline mint blocks later online trial for that device', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 11)));
  await issueOfflineCustomer(e, key, '7KD2M-QX9TP', 'Shop', 'al-store');
  const rows = await e.DB.prepare('SELECT machine FROM machine_trials').bind().all();
  assert.equal(rows.results[0].machine, deviceLockKey(deviceKey('7KD2M-QX9TP')));
  const online = await postRequest(e, body({ nonce: 'n3' }));
  assert.equal(online.data.reason, 'already_used');
});

test('offline concurrent mint only succeeds once', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 12)));
  const device = '7KD2M-QX9TP';
  const results = await Promise.allSettled([
    issueOfflineCustomer(e, key, device, 'A', 'al-store'),
    issueOfflineCustomer(e, key, device, 'B', 'al-store'),
  ]);
  const values = results.filter((r) => r.status === 'fulfilled').map((r) => r.value);
  assert.equal(values.length, 2);
  assert.equal(values[0].code, values[1].code);
  assert.equal(values.filter((v) => v.conflict).length, 1);
  const customers = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(customers.results.length, 1);
});

test('short device code is rejected at request', async () => {
  const e = env();
  const { res, data } = await postRequest(e, body({ device: 'ABC', nonce: 'short' }));
  assert.equal(res.status, 400);
  assert.equal(data.field, 'device');
});

test('malformed machine hash is rejected at request', async () => {
  const e = env();
  const { res, data } = await postRequest(e, body({ machine: 'not-a-valid-machine-tag', nonce: 'bad-machine' }));
  assert.equal(res.status, 400);
  assert.equal(data.field, 'machine');
});

test('open pending is limited to one row per device until TTL expires', async () => {
  const e = env();
  const first = await postRequest(e, body({ nonce: 'p1' }));
  assert.equal(first.data.status, 'pending');
  const second = await postRequest(e, body({ nonce: 'p2' }));
  assert.equal(second.res.status, 400);
  assert.equal(second.data.field, 'device');
  const old = Math.floor(Date.now() / 1000) - 2000;
  await e.DB.prepare('UPDATE licence_requests SET created_at = ?, updated_at = ? WHERE id = ?')
    .bind(old, old, first.data.id).run();
  const third = await postRequest(e, body({ nonce: 'p3' }));
  assert.equal(third.data.status, 'pending');
});

test('status returns calendar_day as YYYY-MM-DD string', async () => {
  const e = env();
  const { data } = await postRequest(e, body());
  const st = await getStatus(e, data.id, data.poll_token);
  assert.match(st.data.calendar_day, /^\d{4}-\d{2}-\d{2}$/);
});

test('ack clears stored activation code', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 2)));
  const { data } = await postRequest(e, body());
  await approveRequest(e, data.id, key);
  const poll = data.poll_token;
  const ackReq = new Request('https://hub.test/licence/ack', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + poll },
    body: JSON.stringify({ id: data.id }),
  });
  await handleLicence(ackReq, e, new URL(ackReq.url));
  const row = await e.DB.prepare('SELECT code, status FROM licence_requests WHERE id = ?').bind(data.id).first();
  assert.equal(row.code, null);
  assert.equal(row.status, 'delivered');
});

test('force on second pending request returns existing trial code', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 4)));
  const device = '7KD2M-QX9TP';
  const first = await postRequest(e, body({ nonce: 'f1' }));
  const issued = await approveRequest(e, first.data.id, key);
  const retry = await postRequest(e, body({ nonce: 'f2' }));
  assert.equal(retry.data.reason, 'already_used');
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('lost', 'hx', 'al-store', 'trial', device, deviceKey(device), MACHINE_A, 'n-lost', '', '', '', 'pending', 2, 2).run();
  const forced = await approveRequest(e, 'lost', key, { force: true });
  assert.equal(forced.code, issued.code);
  assert.equal(forced.conflict, true);
  const customers = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(customers.results.length, 1);
});

test('concurrent force approve on two pending same device yields one customer', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 15)));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('fc-a', 'h1', 'al-store', 'trial', device, dkey, MACHINE_A, 'n-fa', '', '', '', 'pending', t, t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('fc-b', 'h2', 'al-store', 'trial', device, dkey, MACHINE_A, 'n-fb', '', '', '', 'pending', t, t).run();
  const [a, b] = await Promise.all([
    approveRequest(e, 'fc-a', key, { force: true }),
    approveRequest(e, 'fc-b', key, { force: true }),
  ]);
  assert.ok(a?.code);
  assert.ok(b?.code);
  assert.equal(a.code, b.code);
  const customers = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(customers.results.length, 1);
});

test('offline force after online trial returns stored code', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 16)));
  const device = '7KD2M-QX9TP';
  const { data } = await postRequest(e, body({ nonce: 'on-off' }));
  const online = await approveRequest(e, data.id, key);
  const offline = await issueOfflineCustomer(e, key, device, 'Shop', 'al-store', { force: true });
  assert.equal(offline.code, online.code);
  assert.equal(offline.conflict, true);
  const customers = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(customers.results.length, 1);
});

test('issued row without machine lock is not returned until claim is repaired', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 6)));
  const { data } = await postRequest(e, body({ nonce: 'orphan' }));
  await e.DB.prepare(
    "UPDATE licence_requests SET status = 'issued', code = 'FAKE-CODE' WHERE id = ?",
  ).bind(data.id).run();
  const out = await approveRequest(e, data.id, key);
  assert.ok(out?.code);
  assert.notEqual(out.code, 'FAKE-CODE');
  assert.match(out.code, /^[0-9A-Z-]+$/);
  const lock = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(deviceKey('7KD2M-QX9TP'))).first();
  assert.equal(lock.request_id, data.id);
});

test('purgeStaleCodes blanks old issued rows', async () => {
  const e = env();
  const old = Math.floor(Date.now() / 1000) - 20 * 86400;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('old', 'h', 'al-store', 'trial', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n', '', '', '', 'delivered', 'CODE-OLD', old, old).run();
  await purgeStaleCodes(e);
  const row = await e.DB.prepare('SELECT code FROM licence_requests WHERE id = ?').bind('old').first();
  assert.equal(row.code, null);
});

test('approve retry returns the same code', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 3)));
  const { data } = await postRequest(e, body());
  const first = await approveRequest(e, data.id, key);
  const second = await approveRequest(e, data.id, key);
  assert.equal(first.code, second.code);
});

test('concurrent approve on one request yields one code and one customer', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 13)));
  const { data } = await postRequest(e, body({ nonce: 'dbl-conc' }));
  const [a, b] = await Promise.all([approveRequest(e, data.id, key), approveRequest(e, data.id, key)]);
  assert.ok(a?.code);
  assert.ok(b?.code);
  assert.equal(a.code, b.code);
  const customers = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(customers.results.length, 1);
});

test('force with existing issued code returns stored code without extra customer', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 14)));
  const { data } = await postRequest(e, body({ nonce: 'force-stored' }));
  const first = await approveRequest(e, data.id, key);
  const forced = await approveRequest(e, data.id, key, { force: true });
  assert.equal(forced.code, first.code);
  const customers = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(customers.results.length, 1);
});

test('approve retry does not add a second customer row', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 8)));
  const { data } = await postRequest(e, body({ nonce: 'cust-once' }));
  await approveRequest(e, data.id, key);
  await approveRequest(e, data.id, key);
  const rows = await e.DB.prepare('SELECT id FROM customers').bind().all();
  assert.equal(rows.results.length, 1);
});

test('losing concurrent approval releases machine locks for a later request', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 10)));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('race-a', 'h1', 'al-store', 'trial', device, dkey, MACHINE_A, 'n1', '', '', '', 'pending', t, t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('race-b', 'h2', 'al-store', 'trial', device, dkey, MACHINE_B, 'n2', '', '', '', 'pending', t, t).run();
  await Promise.all([approveRequest(e, 'race-a', key), approveRequest(e, 'race-b', key)]);
  const orphan = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(machineLockKey(MACHINE_B)).first();
  assert.equal(orphan, null);
  const later = await postRequest(e, body({ device: 'ABCDE-FGHJK', machine: MACHINE_B, nonce: 'n-after-race' }));
  assert.equal(later.data.status, 'pending');
});

test('paid pending request approval is refused', async () => {
  const e = env();
  const key = await importSigningKey(pemFromSeed(Buffer.alloc(32, 5)));
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('id1', 'hash', 'al-store', 'monthly', '7KD2M-QX9TP', 'm1', 'n-old', '', '', '', 'pending', 1, 1).run();
  const out = await approveRequest(e, 'id1', key);
  assert.equal(out.refused, true);
  assert.equal(out.reason, REASON_PAID_IN_STUDIO);
});

test('derivePollToken is stable for a nonce', async () => {
  const a = await derivePollToken(SECRET, 'fixed-nonce');
  const b = await derivePollToken(SECRET, 'fixed-nonce');
  assert.equal(a, b);
  assert.match(a, /^lp_[0-9a-f]+$/);
});
