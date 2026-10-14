import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createHash, createPrivateKey } from 'node:crypto';
import { newD1 } from './d1-mock.js';
import {
  handleLicence, approveRequest, refuseRequest, issueOfflineCustomer, derivePollToken, purgeStaleCodes,
  deviceKey, deviceLockKey, onlineDeviceLockKey, migrateLegacyTrialLocks, trialUsedForDevice,
  trialUsedOnline, REASON_PAID_IN_STUDIO, REASON_PAID_KEY_MISSING, offlineDeviceLockKey,
  hubCalendarSigned, hubTimeSigningMaterial, ownerCapabilities, loadSigningKeys, paidSigningKeyForProduct,
  offlineRequestId, storedGrantMatches, trialUsedForOfflineProduct, wouldDowngradeGrant,
  currentTerm,
} from '../src/licence-api.js';
import { importSigningKey } from '../src/afcodes.js';
import { calendarDateInTz } from '../src/calendar.js';

const SECRET = 'test-session-secret-0123456789abcdef';
const MACHINE_A = 'a'.repeat(64);
const MACHINE_B = 'b'.repeat(64);

function pollHash(token) {
  return createHash('sha256').update(token).digest('hex');
}

function pemFromSeed(seed32) {
  const seed = Buffer.from(seed32);
  const pk = createPrivateKey({
    key: Buffer.concat([Buffer.from('302e020100300506032b657004220420', 'hex'), seed]),
    format: 'der',
    type: 'pkcs8',
  });
  return pk.export({ type: 'pkcs8', format: 'pem' });
}

async function signingKeys(trialByte = 9, paidByte = null) {
  const keys = { trialKey: null, paidKey: null };
  if (trialByte !== null) keys.trialKey = await importSigningKey(pemFromSeed(Buffer.alloc(32, trialByte)));
  if (paidByte !== null) keys.paidKey = await importSigningKey(pemFromSeed(Buffer.alloc(32, paidByte)));
  return keys;
}

function env() {
  return {
    DB: newD1(),
    SESSION_SECRET: SECRET,
    LICENCE_PRODUCTS: 'trip-orders',
    TRIAL_DAYS: '14',
    LICENCE_CALENDAR_TZ: 'Africa/Cairo',
    PENDING_TTL_SEC: '900',
  };
}

function body(over = {}) {
  return {
    product: 'trip-orders',
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

test('monthly and permanent requests enter pending for owner approval', async () => {
  const e = env();
  for (const [kind, device] of [['monthly', '7KD2M-QX9TP'], ['permanent', 'ABCDE-FGHJK']]) {
    const { data } = await postRequest(e, body({ kind, nonce: 'n-' + kind, device }));
    assert.equal(data.status, 'pending');
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

test('losing concurrent approval never exposes issued code on status poll', async () => {
  const e = env();
  const keys = await signingKeys(19);
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const t = 1;
  const pollA = await derivePollToken(SECRET, 'n-a');
  const pollB = await derivePollToken(SECRET, 'n-b');
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('a', pollHash(pollA), 'trip-orders', 'trial', device, dkey, MACHINE_A, 'n-a', '', '', '', 'pending', t, t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('b', pollHash(pollB), 'trip-orders', 'trial', device, dkey, MACHINE_B, 'n-b', '', '', '', 'pending', t, t).run();
  const [signedA, signedB] = await Promise.all([approveRequest(e, 'a', keys), approveRequest(e, 'b', keys)]);
  const winners = [signedA, signedB].filter((s) => s?.code);
  assert.equal(winners.length, 1);
  const stB = await getStatus(e, 'b', pollB);
  const stA = await getStatus(e, 'a', pollA);
  const issued = [stA.data, stB.data].filter((d) => d.status === 'issued' && d.code);
  assert.equal(issued.length, 1);
});

test('only one trial wins on concurrent approval for the same device', async () => {
  const e = env();
  const keys = await signingKeys(9);
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('a', 'h1', 'trip-orders', 'trial', device, dkey, MACHINE_A, 'n1', '', '', '', 'pending', t, t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('b', 'h2', 'trip-orders', 'trial', device, dkey, MACHINE_B, 'n2', '', '', '', 'pending', t, t).run();
  const [signedA, signedB] = await Promise.all([approveRequest(e, 'a', keys), approveRequest(e, 'b', keys)]);
  const winners = [signedA, signedB].filter((s) => s?.code);
  assert.equal(winners.length, 1);
  const rowB = await e.DB.prepare('SELECT status, reason FROM licence_requests WHERE id = ?').bind('b').first();
  const rowA = await e.DB.prepare('SELECT status, reason FROM licence_requests WHERE id = ?').bind('a').first();
  const refused = [rowA, rowB].find((r) => r.status === 'refused');
  assert.ok(refused);
  assert.equal(refused.reason, 'already_used');
});

test('second online trial for same machine hash is refused after install_id wipe (new device code)', async () => {
  const e = env();
  const keys = await signingKeys(7);
  const first = await postRequest(e, body({ device: '7KD2M-QX9TP', machine: MACHINE_A, nonce: 'n1' }));
  await approveRequest(e, first.data.id, await signingKeys(9));
  const second = await postRequest(e, body({ device: 'ABCDE-FGHJK', machine: MACHINE_A, nonce: 'n2' }));
  assert.equal(second.data.status, 'refused');
  assert.equal(second.data.reason, 'already_used');
});

test('offline mint blocks later online trial for that device', async () => {
  const e = env();
  const keys = await signingKeys(11);
  await issueOfflineCustomer(e, keys, '7KD2M-QX9TP', 'Shop', 'trip-orders');
  const rows = await e.DB.prepare('SELECT machine FROM machine_trials').bind().all();
  const machines = (rows.results || []).map((r) => r.machine);
  assert.ok(machines.includes(deviceLockKey(deviceKey('7KD2M-QX9TP'))));
  const online = await postRequest(e, body({ nonce: 'n3' }));
  assert.equal(online.data.reason, 'already_used');
});

test('offline concurrent mint only succeeds once', async () => {
  const e = env();
  const keys = await signingKeys(12);
  const device = '7KD2M-QX9TP';
  const results = await Promise.allSettled([
    issueOfflineCustomer(e, keys, device, 'A', 'trip-orders'),
    issueOfflineCustomer(e, keys, device, 'B', 'trip-orders'),
  ]);
  const ok = results.filter((r) => r.status === 'fulfilled');
  assert.equal(ok.length, 2);
  const codes = ok.map((r) => r.value.code);
  assert.equal(codes[0], codes[1]);
});

test('short device code is rejected at request', async () => {
  const e = env();
  const { res, data } = await postRequest(e, body({ device: 'ABC', nonce: 'short' }));
  assert.equal(res.status, 400);
  assert.equal(data.field, 'device');
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

test('time returns signed hub calendar day without database access', async () => {
  for (const tz of [undefined, 'Pacific/Kiritimati', 'America/Los_Angeles']) {
    const e = {
      LICENCE_CALENDAR_TZ: tz,
      LICENCE_SIGNING_KEY: pemFromSeed(Buffer.alloc(32, 77)),
      get DB() { assert.fail('time must not access the database'); },
      get SESSION_SECRET() { assert.fail('time must not read session secret'); },
    };
    const req = new Request('https://hub.test/licence/time');
    const before = calendarDateInTz(new Date(), tz || 'Africa/Cairo').iso;
    const res = await handleLicence(req, e, new URL(req.url));
    const data = await res.json();
    const after = calendarDateInTz(new Date(), tz || 'Africa/Cairo').iso;
    assert.equal(res.status, 200);
    assert.equal(res.headers.get('Cache-Control'), 'no-store');
    assert.equal(data.kid, 'trial-hub');
    assert.ok(data.sig);
    assert.ok([before, after].includes(data.calendar_day));
  }
});

test('ack clears stored activation code', async () => {
  const e = env();
  const keys = await signingKeys(2);
  const { data } = await postRequest(e, body());
  await approveRequest(e, data.id, await signingKeys(9));
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

test('owner force reissue replaces device trial lock', async () => {
  const e = env();
  const keys = await signingKeys(4);
  const device = '7KD2M-QX9TP';
  const first = await postRequest(e, body({ nonce: 'f1' }));
  await approveRequest(e, first.data.id, await signingKeys(9));
  const retry = await postRequest(e, body({ nonce: 'f2' }));
  assert.equal(retry.data.reason, 'already_used');
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('lost', 'hx', 'trip-orders', 'trial', device, deviceKey(device), MACHINE_A, 'n-lost', '', '', '', 'pending', 2, 2).run();
  const forced = await approveRequest(e, 'lost', await signingKeys(9), { force: true });
  assert.ok(forced?.code);
});

test('issued row without machine lock is not returned until claim is repaired', async () => {
  const e = env();
  const keys = await signingKeys(6);
  const { data } = await postRequest(e, body({ nonce: 'orphan' }));
  await e.DB.prepare(
    "UPDATE licence_requests SET status = 'issued', code = 'FAKE-CODE' WHERE id = ?",
  ).bind(data.id).run();
  const out = await approveRequest(e, data.id, await signingKeys(9));
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
  ).bind('old', 'h', 'trip-orders', 'trial', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n', '', '', '', 'delivered', 'CODE-OLD', old, old).run();
  await purgeStaleCodes(e);
  const row = await e.DB.prepare('SELECT code FROM licence_requests WHERE id = ?').bind('old').first();
  assert.equal(row.code, null);
});

test('approve retry returns the same code', async () => {
  const e = env();
  const keys = await signingKeys(3);
  const { data } = await postRequest(e, body());
  const first = await approveRequest(e, data.id, keys);
  const second = await approveRequest(e, data.id, keys);
  assert.equal(first.code, second.code);
});

test('paid pending request needs PAID_SIGNING_KEY', async () => {
  const e = env();
  const keys = await signingKeys(5);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('id1', 'hash', 'trip-orders', 'monthly', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), 'm1', 'n-old', '', '', '', 'pending', 1, 1).run();
  const out = await approveRequest(e, 'id1', keys, { grant: 'paid', paid_until: '2027-01-01' });
  assert.equal(out.refused, true);
});

test('paidSigningKeyForProduct prefers PAID_SIGNING_KEY over LICENCE_PAID_SIGNING_KEY', () => {
  const a = pemFromSeed(Buffer.alloc(32, 1));
  const b = pemFromSeed(Buffer.alloc(32, 2));
  assert.equal(paidSigningKeyForProduct({ LICENCE_PAID_SIGNING_KEY: a }, 'trip-orders'), a);
  assert.equal(paidSigningKeyForProduct({ PAID_SIGNING_KEY: a, LICENCE_PAID_SIGNING_KEY: b }, 'trip-orders'), a);
  assert.equal(paidSigningKeyForProduct({ PAID_SIGNING_KEY_AL_STORE: b, LICENCE_PAID_SIGNING_KEY: a }, 'al-store'), b);
});

test('loadSigningKeys reads LICENCE_PAID_SIGNING_KEY when PAID_SIGNING_KEY is unset', async () => {
  const e = env();
  e.LICENCE_PAID_SIGNING_KEY = pemFromSeed(Buffer.alloc(32, 88));
  e.LICENCE_SIGNING_KEY = pemFromSeed(Buffer.alloc(32, 9));
  const keys = await loadSigningKeys(e, 'trip-orders');
  assert.ok(keys.paidKey);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('id-alias', 'hash', 'trip-orders', 'monthly', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n-alias', '', '', '', 'pending', 1, 1).run();
  const out = await approveRequest(e, 'id-alias', keys, { grant: 'paid', preset: '1m' });
  assert.ok(out.code);
});

test('owner can approve paid until date with PAID_SIGNING_KEY', async () => {
  const e = env();
  const keys = await signingKeys(5, 8);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('id2', 'hash', 'trip-orders', 'monthly', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n-paid', '', '', '', 'pending', 1, 1).run();
  const out = await approveRequest(e, 'id2', keys, { grant: 'paid', preset: '1m' });
  assert.ok(out.code);
});

test('legacy unprefixed machine_trials row blocks reuse after upgrade', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind(dkey, 'legacy-req', 1).run();
  assert.equal(await trialUsedForDevice(e, dkey), true);
  await migrateLegacyTrialLocks(e);
  assert.equal(await trialUsedForDevice(e, dkey), true);
});

test('offline issuance survives customer insert failure and retries same code', async () => {
  const e = env();
  const keys = await signingKeys(21);
  const device = '7KD2M-QX9TP';
  const origPrepare = e.DB.prepare.bind(e.DB);
  let failCustomers = true;
  e.DB.prepare = (sql) => {
    const stmt = origPrepare(sql);
    if (failCustomers && sql.includes('INSERT INTO customers')) {
      return {
        bind(...args) {
          return {
            run() { throw new Error('simulated-D1-error'); },
            first() { return stmt.bind(...args).first(); },
            all() { return stmt.bind(...args).all(); },
          };
        },
      };
    }
    return stmt;
  };
  await assert.rejects(() => issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders'), /simulated-D1-error/);
  failCustomers = false;
  const second = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders');
  assert.ok(second.code);
  const third = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders');
  assert.equal(third.code, second.code);
});

test('derivePollToken is stable for a nonce', async () => {
  const a = await derivePollToken(SECRET, 'fixed-nonce');
  const b = await derivePollToken(SECRET, 'fixed-nonce');
  assert.equal(a, b);
  assert.match(a, /^lp_[0-9a-f]+$/);
});

function wrapAsyncD1(syncDb) {
  return {
    prepare(sql) {
      const inner = syncDb.prepare(sql);
      return {
        bind(...args) {
          const bound = inner.bind(...args);
          return {
            run: () => Promise.resolve(bound.run()),
            first: () => Promise.resolve(bound.first()),
            all: () => Promise.resolve(bound.all()),
          };
        },
      };
    },
    batch: (stmts) => syncDb.batch(stmts),
  };
}

test('offline issuance awaits D1 run() like production', async () => {
  const e = env();
  e.DB = wrapAsyncD1(e.DB);
  const keys = await signingKeys(31);
  const signed = await issueOfflineCustomer(e, keys, '7KD2M-QX9TP', 'Shop', 'trip-orders');
  assert.ok(signed.code);
  const again = await issueOfflineCustomer(e, keys, '7KD2M-QX9TP', 'Shop', 'trip-orders');
  assert.equal(again.code, signed.code);
});

test('legacy migration backfills machine hash lock from delivered request', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('legacy-req', 'h', 'trip-orders', 'trial', device, dkey, MACHINE_A, 'n', '', '', '', 'issued', 'CODE', t, t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind(dkey, 'legacy-req', t).run();
  e.DB = wrapAsyncD1(e.DB);
  await migrateLegacyTrialLocks(e);
  const hlock = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?').bind('h:' + MACHINE_A).first();
  assert.equal(hlock.request_id, 'legacy-req');
  const second = await postRequest(e, body({ device: 'ABCDE-FGHJK', machine: MACHINE_A, nonce: 'n-hash' }));
  assert.equal(second.data.reason, 'already_used');
});

test('losing concurrent approval releases partial device locks', async () => {
  const e = env();
  const keys = await signingKeys(33);
  const hash = MACHINE_A;
  const devA = '7KD2M-QX9TP';
  const devB = 'ABCDE-FGHJK';
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('win', 'h1', 'trip-orders', 'trial', devA, deviceKey(devA), hash, 'n1', '', '', '', 'pending', t, t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('lose', 'h2', 'trip-orders', 'trial', devB, deviceKey(devB), hash, 'n2', '', '', '', 'pending', t, t).run();
  const [a, b] = await Promise.all([approveRequest(e, 'win', keys), approveRequest(e, 'lose', keys)]);
  const winners = [a, b].filter((s) => s?.code);
  assert.equal(winners.length, 1);
  const locks = await e.DB.prepare('SELECT machine, request_id FROM machine_trials').bind().all();
  const deviceLocks = (locks.results || []).filter((r) => r.machine.startsWith('d:'));
  assert.equal(deviceLocks.length, 1);
  const loserDevice = a?.code ? devB : devA;
  const winnerDevice = a?.code ? devA : devB;
  assert.equal(deviceLocks[0].machine, deviceLockKey(deviceKey(winnerDevice)));
  const online = await postRequest(e, body({ device: loserDevice, machine: MACHINE_B, nonce: 'n-free' }));
  assert.equal(online.data.status, 'pending');
});

test('offline issuance survives interrupted code write and retries same code', async () => {
  const e = env();
  const keys = await signingKeys(34);
  const device = '7KD2M-QX9TP';
  const origPrepare = e.DB.prepare.bind(e.DB);
  let failIssue = true;
  e.DB.prepare = (sql) => {
    const stmt = origPrepare(sql);
    if (failIssue && sql.includes('UPDATE licence_requests SET status = ?') && sql.includes('code = ?')) {
      return {
        bind(...args) {
          return {
            async run() { throw new Error('simulated-D1-error'); },
            first: () => stmt.bind(...args).first(),
            all: () => stmt.bind(...args).all(),
          };
        },
      };
    }
    return stmt;
  };
  await assert.rejects(() => issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders'), /simulated-D1-error/);
  failIssue = false;
  const second = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders');
  assert.ok(second.code);
});

test('request with empty, short or non-hex machine tag is rejected', async () => {
  const e = env();
  for (const machine of ['', 'abc', 'z'.repeat(64), 'a'.repeat(63), 'a'.repeat(65)]) {
    const r = await postRequest(e, body({ machine }));
    assert.equal(r.status ?? r.res?.status ?? 400, 400);
    assert.equal(r.data.field, 'machine');
  }
});

test('approval-race loser keeps no machine_trials rows and adds no customer', async () => {
  const e = env();
  const keys = await signingKeys(35);
  const devA = '7KD2M-QX9TP';
  const devB = 'ABCDE-FGHJK';
  for (const [id, dev, n] of [['w2', devA, 'm1'], ['l2', devB, 'm2']]) {
    await e.DB.prepare(
      'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(id, 'h' + id, 'trip-orders', 'trial', dev, deviceKey(dev), MACHINE_A, n, '', '', '', 'pending', 1, 1).run();
  }
  const [a, b] = await Promise.all([approveRequest(e, 'w2', keys), approveRequest(e, 'l2', keys)]);
  const winner = a?.code ? 'w2' : 'l2';
  assert.equal([a, b].filter((s) => s?.code).length, 1);
  const locks = (await e.DB.prepare('SELECT machine, request_id FROM machine_trials').bind().all()).results || [];
  assert.ok(locks.length > 0);
  assert.ok(locks.every((r) => r.request_id === winner));
  const cust = (await e.DB.prepare('SELECT id FROM customers').bind().all()).results || [];
  assert.equal(cust.length, 1);
});

test('concurrent approval of the same request keeps device locks and one code', async () => {
  const e = env();
  const keys = await signingKeys(41);
  const { data } = await postRequest(e, body());
  const [a, b] = await Promise.all([approveRequest(e, data.id, keys), approveRequest(e, data.id, keys)]);
  assert.ok(a?.code);
  assert.equal(a.code, b.code);
  const locks = (await e.DB.prepare('SELECT machine FROM machine_trials WHERE request_id = ?').bind(data.id).all()).results || [];
  assert.ok(locks.length >= 1);
  const cust = (await e.DB.prepare('SELECT id FROM customers').bind().all()).results || [];
  assert.equal(cust.length, 1);
});

test('separate offline queues on one database return the same issued code', async () => {
  const db = newD1();
  const mk = () => ({
    DB: db,
    SESSION_SECRET: SECRET,
    LICENCE_PRODUCTS: 'trip-orders',
    TRIAL_DAYS: '14',
    LICENCE_CALENDAR_TZ: 'Africa/Cairo',
    _offlineTails: new Map(),
  });
  const keys = await signingKeys(43);
  const device = '7KD2M-QX9TP';
  const [a, b] = await Promise.all([
    issueOfflineCustomer(mk(), keys, device, 'A', 'trip-orders'),
    issueOfflineCustomer(mk(), keys, device, 'B', 'trip-orders'),
  ]);
  assert.equal(a.code, b.code);
  const cust = (await db.prepare('SELECT id FROM customers').bind().all()).results || [];
  assert.equal(cust.length, 1);
});

test('owner approval migrates legacy hash lock before issuing second trial', async () => {
  const e = env();
  const keys = await signingKeys(44);
  const oldDev = '7KD2M-QX9TP';
  const newDev = 'ABCDE-FGHJK';
  const dkeyOld = deviceKey(oldDev);
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('legacy-del', 'h0', 'trip-orders', 'trial', oldDev, dkeyOld, MACHINE_A, 'n0', '', '', '', 'delivered', 'OLD-CODE', t, t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind(dkeyOld, 'legacy-del', t).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('pending-new', 'h9', 'trip-orders', 'trial', newDev, deviceKey(newDev), MACHINE_A, 'n9', '', '', '', 'pending', t, t).run();
  const out = await approveRequest(e, 'pending-new', await signingKeys(9));
  assert.equal(out, null);
  const row = await e.DB.prepare('SELECT status, reason FROM licence_requests WHERE id = ?').bind('pending-new').first();
  assert.equal(row.status, 'refused');
  assert.equal(row.reason, 'already_used');
});

test('TRIAL_DAYS above 14 refuses to sign offline trials', async () => {
  const e = { ...env(), TRIAL_DAYS: '30' };
  const keys = await signingKeys(55);
  await assert.rejects(
    () => issueOfflineCustomer(e, keys, '7KD2M-QX9TP', 'Shop', 'trip-orders'),
    /trial_days_out_of_range/,
  );
});

test('hub time signs with getter-bound LICENCE_SIGNING_KEY', async () => {
  const pem = pemFromSeed(Buffer.alloc(32, 88));
  const e = {
    LICENCE_CALENDAR_TZ: 'Africa/Cairo',
    get LICENCE_SIGNING_KEY() { return pem; },
  };
  const req = new Request('https://hub.test/licence/time');
  const res = await handleLicence(req, e, new URL(req.url));
  const data = await res.json();
  assert.equal(data.kid, 'trial-hub');
  assert.ok(data.sig);
  assert.ok(data.serverTime);
});

test('hub time uses paid key and kid when trial key missing', async () => {
  const pem = pemFromSeed(Buffer.alloc(32, 89));
  const e = { PAID_SIGNING_KEY: pem };
  const req = new Request('https://hub.test/licence/clock');
  const res = await handleLicence(req, e, new URL(req.url));
  const data = await res.json();
  assert.equal(data.kid, 'paid');
  assert.ok(data.sig);
});

test('re-issue with different grant signs a new code', async () => {
  const e = env();
  const keys = await signingKeys(5, 10);
  const device = '7KD2M-QX9TP';
  const t = 1;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, licence_tier, licence_expiry, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('paid1', 'h', 'trip-orders', 'monthly', device, deviceKey(device), MACHINE_A, 'n', '', '', '', 'issued', 'OLD-CODE', 'paid', '2027-06-01', t, t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind(deviceLockKey(deviceKey(device)), 'paid1', t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind('h:' + MACHINE_A, 'paid1', t).run();
  const out = await approveRequest(e, 'paid1', keys, { grant: 'paid', paid_until: '2028-01-01' });
  assert.ok(out.code);
  assert.notEqual(out.code, 'OLD-CODE');
});

test('re-issue with identical grant returns the same code', async () => {
  const e = env();
  const keys = await signingKeys(5, 11);
  const device = 'ABCDE-FGHJK';
  const t = 2;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, licence_tier, licence_expiry, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('paid2', 'h2', 'trip-orders', 'monthly', device, deviceKey(device), MACHINE_B, 'n2', '', '', '', 'issued', 'SAME-CODE', 'paid', '2027-06-01', t, t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind(deviceLockKey(deviceKey(device)), 'paid2', t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)').bind('h:' + MACHINE_B, 'paid2', t).run();
  const out = await approveRequest(e, 'paid2', keys, { grant: 'paid', paid_until: '2027-06-01' });
  assert.equal(out.code, 'SAME-CODE');
});

test('offline re-issue with different grant replaces trial code', async () => {
  const e = env();
  const keys = await signingKeys(5, 12);
  const device = '7KD2M-QX9TP';
  const trial = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', { grant: 'trial' });
  const paid = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', { grant: 'paid', paid_until: '2027-12-31' });
  assert.notEqual(paid.code, trial.code);
});

test('purgeStaleCodes keeps paid issued codes', async () => {
  const e = env();
  const old = Math.floor(Date.now() / 1000) - 20 * 86400;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, licence_tier, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('paid-old', 'h', 'trip-orders', 'monthly', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n', '', '', '', 'issued', 'PAID-CODE', 'paid', old, old).run();
  await purgeStaleCodes(e);
  const row = await e.DB.prepare('SELECT code FROM licence_requests WHERE id = ?').bind('paid-old').first();
  assert.equal(row.code, 'PAID-CODE');
});

test('request without product defaults to trip-orders', async () => {
  const e = env();
  const payload = body();
  delete payload.product;
  const { data } = await postRequest(e, payload);
  assert.equal(data.status, 'pending');
  const row = await e.DB.prepare('SELECT product FROM licence_requests WHERE id = ?').bind(data.id).first();
  assert.equal(row.product, 'trip-orders');
});

test('licence routes accept /api and /licence-hub prefixes', async () => {
  const e = env();
  const req = new Request('https://hub.test/api/licence/status?id=x', {
    headers: { Authorization: 'Bearer bad' },
  });
  const res = await handleLicence(req, e, new URL(req.url));
  assert.equal(res.status, 401);
});

test('bad paid_until calendar date is rejected', async () => {
  const e = env();
  const keys = await signingKeys(5, 13);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('bad-date', 'h', 'trip-orders', 'monthly', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n', '', '', '', 'pending', 1, 1).run();
  await assert.rejects(
    () => approveRequest(e, 'bad-date', keys, { grant: 'paid', paid_until: '2026-02-31' }),
    /bad_grant/,
  );
});

test('purgeStaleCodes keeps issued row when kind is trial but licence_tier is paid', async () => {
  const e = env();
  const old = Math.floor(Date.now() / 1000) - 20 * 86400;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, licence_tier, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('trial-kind-paid-tier', 'h', 'trip-orders', 'trial', '7KD2M-QX9TP', deviceKey('7KD2M-QX9TP'), MACHINE_A, 'n', '', '', '', 'issued', 'APPROVED-PAID', 'paid', old, old).run();
  await purgeStaleCodes(e);
  const row = await e.DB.prepare('SELECT code FROM licence_requests WHERE id = ?').bind('trial-kind-paid-tier').first();
  assert.equal(row.code, 'APPROVED-PAID');
});

test('hub calendar uses global signing keys only', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 88));
  assert.equal(hubTimeSigningMaterial(e), null);
  const out = await hubCalendarSigned(e);
  assert.equal(out.sig, undefined);
  e.LICENCE_SIGNING_KEY = pemFromSeed(Buffer.alloc(32, 87));
  const signed = await hubCalendarSigned(e);
  assert.ok(signed.sig);
  assert.equal(signed.kid, 'trial-hub');
});

test('ownerCapabilities reflects per-product paid key', () => {
  const e = {
    LICENCE_PRODUCTS: 'trip-orders,al-store',
    PAID_SIGNING_KEY_AL_STORE: pemFromSeed(Buffer.alloc(32, 89)),
  };
  const caps = ownerCapabilities(e);
  assert.equal(caps.paid_available, true);
  assert.equal(caps.trial_available, false);
  assert.equal(caps.products['trip-orders'].paid_available, false);
  assert.equal(caps.products['al-store'].paid_available, true);
});

test('storedGrantMatches requires matching product', () => {
  const row = { product: 'trip-orders', licence_tier: 'trial', kind: 'trial' };
  assert.equal(storedGrantMatches(row, { grant: 'trial' }, 'trip-orders'), true);
  assert.equal(storedGrantMatches(row, { grant: 'trial' }, 'al-store'), false);
});

test('offline manual activation is keyed per product and device', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY = pemFromSeed(Buffer.alloc(32, 90));
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 91));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keysTo = await loadSigningKeys(e, 'trip-orders');
  const keysAl = await loadSigningKeys(e, 'al-store');
  const trip = await issueOfflineCustomer(e, keysTo, device, 'Shop', 'trip-orders', { grant: 'trial' });
  const store = await issueOfflineCustomer(e, keysAl, device, 'Shop', 'al-store', { grant: 'trial' });
  assert.equal(trip.product, 'trip-orders');
  assert.equal(store.product, 'al-store');
  assert.notEqual(trip.code, store.code);
  const tripRow = await e.DB.prepare('SELECT id, product FROM licence_requests WHERE id = ?')
    .bind(offlineRequestId('trip-orders', dkey)).first();
  const storeRow = await e.DB.prepare('SELECT id, product FROM licence_requests WHERE id = ?')
    .bind(offlineRequestId('al-store', dkey)).first();
  assert.equal(tripRow.product, 'trip-orders');
  assert.equal(storeRow.product, 'al-store');
  assert.equal(await trialUsedForOfflineProduct(e, 'trip-orders', dkey), true);
  assert.equal(await trialUsedForOfflineProduct(e, 'al-store', dkey), true);
});

test('paid online request after issued trial upgrades without force and keeps trial lock', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const trialKeys = await signingKeys(30);
  const paidKeys = await signingKeys(30, 31);
  const trialReq = await postRequest(e, body({ nonce: 'trial-then-paid' }));
  const trialCode = await approveRequest(e, trialReq.data.id, trialKeys);
  assert.ok(trialCode?.code);
  const trialLock = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first();
  assert.equal(trialLock.request_id, trialReq.data.id);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('paid-after-trial', 'hp', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-paid', '', '', '', 'pending', 3, 3).run();
  const paidOut = await approveRequest(e, 'paid-after-trial', paidKeys, { grant: 'paid', paid_until: '2028-06-01' });
  assert.ok(paidOut?.code);
  assert.notEqual(paidOut.code, trialCode.code);
  const paidRow = await e.DB.prepare('SELECT status, reason FROM licence_requests WHERE id = ?').bind('paid-after-trial').first();
  assert.equal(paidRow.status, 'issued');
  assert.equal(paidRow.reason, '');
  const lockAfter = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first();
  assert.ok(lockAfter);
  assert.equal(await trialUsedForDevice(e, dkey), true);
  const retryTrial = await postRequest(e, body({ nonce: 'trial-blocked' }));
  assert.equal(retryTrial.data.status, 'refused');
  assert.equal(retryTrial.data.reason, 'already_used');
});

test('owner force reissue keeps one-trial lock so a second online trial is refused', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const first = await postRequest(e, body({ nonce: 'force-keep-1' }));
  await approveRequest(e, first.data.id, await signingKeys(32));
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('lost-keep', 'hx2', 'trip-orders', 'trial', device, dkey, MACHINE_A, 'n-lost2', '', '', '', 'pending', 4, 4).run();
  const forced = await approveRequest(e, 'lost-keep', await signingKeys(33), { force: true });
  assert.ok(forced?.code);
  assert.equal(await trialUsedForDevice(e, dkey), true);
  const retry = await postRequest(e, body({ nonce: 'force-keep-2' }));
  assert.equal(retry.data.reason, 'already_used');
});

test('legacy d: and offline: device rows block offline trip-orders trial', async () => {
  const e = env();
  const device = 'ABCDE-FGHJK';
  const dkey = deviceKey(device);
  const t = 1;
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)')
    .bind(deviceLockKey(dkey), 'legacy-off', t).run();
  assert.equal(await trialUsedForOfflineProduct(e, 'trip-orders', dkey), true);
  await e.DB.prepare('DELETE FROM machine_trials WHERE machine = ?').bind(deviceLockKey(dkey)).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)')
    .bind(`offline:${dkey}`, 'legacy-off', t).run();
  assert.equal(await trialUsedForOfflineProduct(e, 'trip-orders', dkey), true);
});

test('wouldDowngradeGrant blocks paid to trial and shorter paid term', () => {
  const paid = { code: 'X', licence_tier: 'paid', licence_expiry: '2028-06-01' };
  assert.equal(wouldDowngradeGrant(paid, { grant: 'trial' }), true);
  assert.equal(wouldDowngradeGrant(paid, { grant: 'paid', paid_until: '2027-01-01' }), true);
  assert.equal(wouldDowngradeGrant(paid, { grant: 'paid', paid_until: '2029-01-01' }), false);
  const perm = { code: 'Y', licence_tier: 'permanent' };
  assert.equal(wouldDowngradeGrant(perm, { grant: 'paid', paid_until: '2029-01-01' }), true);
});

test('offline paid reissue as trial without force is refused and keeps paid code', async () => {
  const e = env();
  const keys = await signingKeys(50, 51);
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const paid = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', {
    grant: 'paid', paid_until: '2028-06-01',
  });
  assert.ok(paid.code);
  await assert.rejects(
    () => issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', { grant: 'trial' }),
    /downgrade/,
  );
  const row = await e.DB.prepare('SELECT code, licence_tier FROM licence_requests WHERE id = ?')
    .bind(offlineRequestId('trip-orders', dkey)).first();
  assert.equal(row.code, paid.code);
  assert.equal(row.licence_tier, 'paid');
});

test('pending monthly approve as trial without force returns downgrade not refuse', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keys = await signingKeys(52, 53);
  await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', {
    grant: 'paid', paid_until: '2028-06-01',
  });
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('monthly-pending', 'hp', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-month', '', '', '', 'pending', 9, 9).run();
  await assert.rejects(() => approveRequest(e, 'monthly-pending', keys, { grant: 'trial' }), /downgrade/);
  const row = await e.DB.prepare('SELECT status, reason FROM licence_requests WHERE id = ?').bind('monthly-pending').first();
  assert.equal(row.status, 'pending');
  assert.equal(row.reason, '');
});

test('al-store offline trial does not write trip-orders d: lock or block trip-orders trial', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY = pemFromSeed(Buffer.alloc(32, 60));
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 61));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keysAl = await loadSigningKeys(e, 'al-store');
  const keysTo = await loadSigningKeys(e, 'trip-orders');
  await issueOfflineCustomer(e, keysAl, device, 'Shop', 'al-store', { grant: 'trial' });
  const legacyLock = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first();
  assert.ok(!legacyLock);
  assert.equal(await trialUsedForOfflineProduct(e, 'trip-orders', dkey), false);
  const trip = await issueOfflineCustomer(e, keysTo, device, 'Shop', 'trip-orders', { grant: 'trial' });
  assert.ok(trip.code);
});

test('signing failure on offline reissue leaves stored paid code', async () => {
  const e = env();
  const keys = await signingKeys(54, 55);
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const paid = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', {
    grant: 'paid', paid_until: '2028-06-01',
  });
  const keysNoTrial = { trialKey: null, paidKey: keys.paidKey };
  await assert.rejects(
    () => issueOfflineCustomer(e, keysNoTrial, device, 'Shop', 'trip-orders', { grant: 'trial', force: true }),
    /no_signing_key/,
  );
  const row = await e.DB.prepare('SELECT code FROM licence_requests WHERE id = ?')
    .bind(offlineRequestId('trip-orders', dkey)).first();
  assert.equal(row.code, paid.code);
});

test('currentTerm keeps paid term after ack clears stored code', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keys = await signingKeys(70, 71);
  const paid = await issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', {
    grant: 'paid', paid_until: '2028-06-01',
  });
  assert.ok(paid.code);
  const requestId = offlineRequestId('trip-orders', dkey);
  await e.DB.prepare(
    'UPDATE licence_requests SET status = ?, code = NULL, updated_at = ? WHERE id = ?',
  ).bind('delivered', 99, requestId).run();
  const term = await currentTerm(e, 'trip-orders', device);
  assert.deepEqual(term, { tier: 'paid', until: '2028-06-01' });
  await assert.rejects(
    () => issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', { grant: 'paid', paid_until: '2027-01-01' }),
    (err) => err.message === 'downgrade' && err.current?.tier === 'paid',
  );
});

test('online delivered row blocks shorter monthly approve without force', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keys = await signingKeys(72, 73);
  await e.DB.prepare(
    'INSERT INTO customers(id, shop, device, kind, licence_tier, licence_expiry, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)',
  ).bind('c-del', 'Shop', device, 'monthly', 'paid', '2028-06-01', 1).run();
  await e.DB.prepare(
    `INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version,
      status, code, licence_tier, licence_expiry, created_at, updated_at)
     VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)`,
  ).bind('delivered-online', 'hp', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-del', 'Shop', '', '', 'delivered', 'paid', '2028-06-01', 5, 5).run();
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('monthly-new', 'hp2', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-new', 'Shop', '', '', 'pending', 6, 6).run();
  await assert.rejects(
    () => approveRequest(e, 'monthly-new', keys, { grant: 'paid', paid_until: '2027-01-01' }),
    (err) => err.message === 'downgrade' && err.current?.until === '2028-06-01',
  );
  const pending = await e.DB.prepare('SELECT status FROM licence_requests WHERE id = ?').bind('monthly-new').first();
  assert.equal(pending.status, 'pending');
});

test('offline manual compares online delivered paid for same product', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keys = await signingKeys(74, 75);
  await e.DB.prepare(
    'INSERT INTO customers(id, shop, device, kind, licence_tier, licence_expiry, created_at) VALUES(?, ?, ?, ?, ?, ?, ?)',
  ).bind('c-on', 'Shop', device, 'monthly', 'paid', '2028-12-01', 1).run();
  await e.DB.prepare(
    `INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version,
      status, licence_tier, licence_expiry, created_at, updated_at)
     VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  ).bind('online-paid', 'hp', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-on', 'Shop', '', '', 'delivered', 'paid', '2028-12-01', 2, 2).run();
  await assert.rejects(
    () => issueOfflineCustomer(e, keys, device, 'Shop', 'trip-orders', { grant: 'paid', paid_until: '2027-06-01' }),
    /downgrade/,
  );
});

test('offline lock race does not return success with a different grant code', async () => {
  const e = env();
  const keys = await signingKeys(40, 41);
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const requestId = offlineRequestId('trip-orders', dkey);
  const lock = `od:trip-orders:${dkey}`;
  const t = 5;
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, licence_tier, licence_expiry, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind(requestId, 'offline', 'trip-orders', 'trial', device, dkey, '', 'offline-x', 'S', '', '', 'issued', 'WINNER-CODE', 'trial', '', t, t).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)')
    .bind(lock, 'other-request', t).run();
  await assert.rejects(
    () => issueOfflineCustomer(e, keys, device, 'S', 'trip-orders', { grant: 'paid', paid_until: '2028-01-01' }),
    /grant_conflict|already_used/,
  );
});

test('migrateLegacyTrialLocks leaves product-scoped pd and ph locks unchanged', async () => {
  const e = env();
  const dkey = deviceKey('7KD2M-QX9TP');
  const machine = MACHINE_A;
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)')
    .bind(onlineDeviceLockKey('al-store', dkey), 'req-al', 1).run();
  await e.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?)')
    .bind(`ph:al-store:${machine}`, 'req-al', 1).run();
  await migrateLegacyTrialLocks(e);
  const legacyD = await e.DB.prepare('SELECT 1 FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first();
  const legacyH = await e.DB.prepare('SELECT 1 FROM machine_trials WHERE machine = ?')
    .bind(`h:${machine}`).first();
  assert.ok(!legacyD);
  assert.ok(!legacyH);
});

test('online al-store trial does not block trip-orders trial on same device code', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 81));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const alReq = await postRequest(e, body({ nonce: 'al-online-1', product: 'al-store' }));
  assert.equal(alReq.data.status, 'pending');
  const keysAl = await loadSigningKeys(e, 'al-store');
  await approveRequest(e, alReq.data.id, keysAl);
  assert.ok(await e.DB.prepare('SELECT 1 FROM machine_trials WHERE machine = ?')
    .bind(onlineDeviceLockKey('al-store', dkey)).first());
  assert.ok(!await e.DB.prepare('SELECT 1 FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first());
  const toReq = await postRequest(e, body({ nonce: 'to-online-1' }));
  assert.equal(toReq.data.status, 'pending');
  assert.equal(await trialUsedOnline(e, 'trip-orders', dkey, MACHINE_A), false);
});

test('trip-orders permanent customer does not downgrade al-store trial approval', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 82));
  e.PAID_SIGNING_KEY = pemFromSeed(Buffer.alloc(32, 83));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const paidKeys = await signingKeys(null, 84);
  await issueOfflineCustomer(e, paidKeys, device, 'Shop', 'trip-orders', { grant: 'permanent' });
  const termAl = await currentTerm(e, 'al-store', device);
  assert.equal(termAl, null);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('al-pending', 'hp', 'al-store', 'trial', device, dkey, MACHINE_A, 'n-al', 'Shop', '', '', 'pending', 8, 8).run();
  const keysAl = await loadSigningKeys(e, 'al-store');
  const signed = await approveRequest(e, 'al-pending', keysAl, { grant: 'trial' });
  assert.ok(signed?.code);
});

test('pending trip-orders request does not block al-store request on same device', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  const device = '7KD2M-QX9TP';
  const toReq = await postRequest(e, body({ nonce: 'pend-to', kind: 'monthly' }));
  assert.equal(toReq.data.status, 'pending');
  const alReq = await postRequest(e, body({ nonce: 'pend-al', product: 'al-store' }));
  assert.equal(alReq.data.status, 'pending');
});

test('paid upgrade keeps trip-orders trial lock for in-flight status poll', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const trialKeys = await signingKeys(86);
  const paidKeys = await signingKeys(86, 87);
  const trialReq = await postRequest(e, body({ nonce: 'poll-keep-trial' }));
  const trialPoll = trialReq.data.poll_token;
  await approveRequest(e, trialReq.data.id, trialKeys);
  const trialLockBefore = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first();
  assert.equal(trialLockBefore.request_id, trialReq.data.id);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('paid-poll', 'hp', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-pp', '', '', '', 'pending', 10, 10).run();
  await approveRequest(e, 'paid-poll', paidKeys, { grant: 'paid', paid_until: '2028-06-01' });
  const trialLockAfter = await e.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?')
    .bind(deviceLockKey(dkey)).first();
  assert.equal(trialLockAfter.request_id, trialReq.data.id);
  const statusRes = await handleLicence(
    new Request(`http://x/licence/status?id=${trialReq.data.id}`, {
      headers: { Authorization: `Bearer ${trialPoll}` },
    }),
    e,
    new URL(`http://x/licence/status?id=${trialReq.data.id}`),
  );
  const statusBody = await statusRes.json();
  assert.equal(statusBody.status, 'issued');
  assert.ok(statusBody.code);
});

test('al-store offline trial blocks online trial on same device', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 94));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keysAl = await loadSigningKeys(e, 'al-store');
  await issueOfflineCustomer(e, keysAl, device, 'Shop', 'al-store', { grant: 'trial' });
  assert.ok(await e.DB.prepare('SELECT 1 FROM machine_trials WHERE machine = ?')
    .bind(offlineDeviceLockKey('al-store', dkey)).first());
  assert.equal(await trialUsedOnline(e, 'al-store', dkey, MACHINE_A), true);
  const online = await postRequest(e, body({ nonce: 'al-off-then-on', product: 'al-store' }));
  assert.equal(online.data.status, 'refused');
  assert.equal(online.data.reason, 'already_used');
});

test('al-store online trial blocks offline trial on same device', async () => {
  const e = env();
  e.LICENCE_PRODUCTS = 'trip-orders,al-store';
  e.LICENCE_SIGNING_KEY_AL_STORE = pemFromSeed(Buffer.alloc(32, 95));
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const alReq = await postRequest(e, body({ nonce: 'al-on-then-off', product: 'al-store' }));
  const keysAl = await loadSigningKeys(e, 'al-store');
  await approveRequest(e, alReq.data.id, keysAl);
  assert.ok(await e.DB.prepare('SELECT 1 FROM machine_trials WHERE machine = ?')
    .bind(onlineDeviceLockKey('al-store', dkey)).first());
  assert.equal(await trialUsedForOfflineProduct(e, 'al-store', dkey), true);
  await assert.rejects(
    () => issueOfflineCustomer(e, keysAl, device, 'Shop', 'al-store', { grant: 'trial' }),
    /already_used/,
  );
});

test('approve paid without PAID_SIGNING_KEY keeps pending request', async () => {
  const e = env();
  const device = '7KD2M-QX9TP';
  const dkey = deviceKey(device);
  const keys = await signingKeys(96);
  await e.DB.prepare(
    'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind('paid-miss', 'hp', 'trip-orders', 'monthly', device, dkey, MACHINE_A, 'n-pm', 'Shop', '', '', 'pending', 1, 1).run();
  const out = await approveRequest(e, 'paid-miss', keys, { grant: 'paid', paid_until: '2028-06-01' });
  assert.equal(out.refused, true);
  assert.equal(out.reason, REASON_PAID_KEY_MISSING);
  const row = await e.DB.prepare('SELECT status, reason FROM licence_requests WHERE id = ?').bind('paid-miss').first();
  assert.equal(row.status, 'pending');
  assert.notEqual(row.reason, REASON_PAID_KEY_MISSING);
});
