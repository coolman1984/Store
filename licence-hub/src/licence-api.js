import { issuePaidCode, issueTrialCode, normalize } from './afcodes.js';
import { hex } from './auth.js';
import { calendarDateInTz } from './calendar.js';

const enc = new TextEncoder();
const now = () => Math.floor(Date.now() / 1000);
const WINDOW = 600;

const REQUIRED = ['product', 'kind', 'device', 'machine', 'nonce', 'shop', 'ref', 'version'];
export const REASON_PAID_IN_STUDIO = 'paid_in_licence_studio';

const MAX_DEVICE = 32;
const MAX_MACHINE = 128;
const MAX_NONCE = 80;
const MAX_PENDING_PER_IP = 8;
const DEFAULT_PENDING_TTL_SEC = 900;

async function sha256Hex(data) {
  const buf = typeof data === 'string' ? enc.encode(data) : data;
  return hex(await crypto.subtle.digest('SHA-256', buf));
}

async function hmacHex(secret, msg) {
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  return hex(await crypto.subtle.sign('HMAC', key, enc.encode(msg)));
}

/** Deterministic poll token from nonce + server secret (safe to return on nonce replay). */
export async function derivePollToken(sessionSecret, nonce) {
  if (!sessionSecret) throw new Error('no_session_secret');
  const digest = await hmacHex(sessionSecret, `licence-poll/v1|${nonce}`);
  return `lp_${digest.slice(0, 48)}`;
}

async function limited(env, key, max) {
  const w = Math.floor(now() / WINDOW);
  const r = await env.DB.prepare('INSERT INTO rate(key, window, count) VALUES(?, ?, 1) ON CONFLICT(key, window) DO UPDATE SET count = count + 1 RETURNING count').bind(key, w).first();
  return r.count > max;
}

function products(env) {
  return new Set(String(env.LICENCE_PRODUCTS || 'al-store').split(',').map((s) => s.trim()).filter(Boolean));
}

function pendingTtl(env) {
  return Number(env.PENDING_TTL_SEC || DEFAULT_PENDING_TTL_SEC);
}

function json(data, status = 200, extra = {}) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', ...extra },
  });
}

/** Normalized 10-character device code — keys machine_trials and open-request checks. */
export function deviceKey(device) {
  const norm = normalize(String(device || ''));
  if (norm.length !== 10) throw new Error('bad_device_code');
  return norm;
}

export function deviceLockKey(dkey) {
  return `d:${dkey}`;
}

export function machineLockKey(machineHash) {
  return `h:${machineHash}`;
}

/** 64-hex SHA-256 machine tag from the office app, or null when malformed. */
export function normalizeMachineHash(machine) {
  const m = String(machine || '').toLowerCase();
  if (!/^[0-9a-f]{64}$/.test(m)) return null;
  return m;
}

function legacyLockRow(machine) {
  const s = String(machine || '');
  if (s.startsWith('d:') || s.startsWith('h:')) return s;
  return deviceLockKey(s);
}

async function trialLockRow(env, lockId) {
  const row = await env.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?').bind(lockId).first();
  if (row) return row;
  const legacy = legacyLockRow(lockId);
  if (legacy !== lockId) {
    return env.DB.prepare('SELECT request_id FROM machine_trials WHERE machine = ?').bind(legacy).first();
  }
  return null;
}

/** Offline path: one trial per normalized device code only. */
export async function trialUsedForDevice(env, deviceKeyNorm) {
  const row = await trialLockRow(env, deviceLockKey(deviceKeyNorm));
  return Boolean(row);
}

/** Online path: refuse when device code or stable machine hash was already used. */
export async function trialUsedOnline(env, deviceKeyNorm, machineHash) {
  if (await trialUsedForDevice(env, deviceKeyNorm)) return true;
  if (machineHash && (await trialLockRow(env, machineLockKey(machineHash)))) return true;
  return false;
}

async function expireStalePending(env) {
  const cutoff = now() - pendingTtl(env);
  const t = now();
  await env.DB.prepare(
    "UPDATE licence_requests SET status = 'expired', reason = 'pending_timeout', updated_at = ? WHERE status = 'pending' AND created_at < ?",
  ).bind(t, cutoff).run();
}

async function openRequestForDevice(env, deviceKeyNorm) {
  const cutoff = now() - pendingTtl(env);
  return env.DB.prepare(
    "SELECT id FROM licence_requests WHERE device_key = ? AND status IN ('pending', 'approved') AND created_at >= ? LIMIT 1",
  ).bind(deviceKeyNorm, cutoff).first();
}

function hubCalendarDay(env) {
  const tz = env.LICENCE_CALENDAR_TZ || 'Africa/Cairo';
  return calendarDateInTz(new Date(), tz).iso;
}

async function locksOwnedByRequest(env, dkey, machineHash, requestId) {
  const locks = [deviceLockKey(dkey)];
  if (machineHash) locks.push(machineLockKey(machineHash));
  for (const lock of locks) {
    const row = await trialLockRow(env, lock);
    if (!row || row.request_id !== requestId) return false;
  }
  return true;
}

/** Licence request that already issued a trial and owns a device or machine lock. */
async function issuedRequestForLock(env, lockId) {
  const trialRow = await trialLockRow(env, lockId);
  if (!trialRow) return null;
  return env.DB.prepare(
    "SELECT * FROM licence_requests WHERE id = ? AND status = 'issued' AND code IS NOT NULL",
  ).bind(trialRow.request_id).first();
}

export async function findIssuedTrialForLocks(env, dkey, machineHash) {
  const locks = [deviceLockKey(dkey)];
  if (machineHash) locks.push(machineLockKey(machineHash));
  const seen = new Set();
  for (const lock of locks) {
    const req = await issuedRequestForLock(env, lock);
    if (req && !seen.has(req.id)) {
      seen.add(req.id);
      return req;
    }
  }
  return null;
}

function existingTrialResponse(req, forRequestId) {
  const out = signedFromRow(req);
  if (req.id !== forRequestId) {
    out.conflict = true;
    out.existing_request_id = req.id;
  }
  return out;
}

export async function handleLicence(request, env, url) {
  const ip = request.headers.get('CF-Connecting-IP') || 'local';
  if (await limited(env, 'lic:ip:' + ip, 120)) return json({ error: 'rate' }, 429);
  if (!env.SESSION_SECRET) return json({ error: 'config' }, 503);

  await expireStalePending(env);

  if (url.pathname === '/licence/clock' && request.method === 'GET') {
    const calendarDay = hubCalendarDay(env);
    return json({ calendar_day: calendarDay, serverTime: calendarDay });
  }

  if (url.pathname === '/licence/request' && request.method === 'POST') {
    let body;
    try { body = await request.json(); } catch { return json({ error: 'json' }, 400); }
    for (const f of REQUIRED) {
      if (typeof body[f] !== 'string') return json({ field: f }, 400);
    }
    if (body.device.length > MAX_DEVICE || body.machine.length > MAX_MACHINE || body.nonce.length > MAX_NONCE) {
      return json({ field: 'device' }, 400);
    }
    if (!products(env).has(body.product)) return json({ field: 'product' }, 400);
    if (!['trial', 'monthly', 'permanent'].includes(body.kind)) return json({ field: 'kind' }, 400);
    let dkey;
    try { dkey = deviceKey(body.device); } catch { return json({ field: 'device' }, 400); }
    const machineHash = normalizeMachineHash(body.machine);
    if (!machineHash) return json({ field: 'machine' }, 400);

    const poll = await derivePollToken(env.SESSION_SECRET, body.nonce);
    const pollHash = await sha256Hex(poll);

    const existing = await env.DB.prepare('SELECT id, poll_token_hash, status, reason FROM licence_requests WHERE nonce = ?').bind(body.nonce).first();
    if (existing) {
      if (existing.poll_token_hash !== pollHash) return json({}, 401);
      return json({
        replay: true,
        id: existing.id,
        poll_token: poll,
        status: existing.status,
        reason: existing.reason || '',
      });
    }

    const id = crypto.randomUUID();
    const t = now();

    if (body.kind === 'trial' && await trialUsedOnline(env, dkey, machineHash)) {
      await env.DB.prepare(
        'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, reason, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
      ).bind(id, pollHash, body.product, body.kind, body.device, dkey, body.machine, body.nonce, body.shop.slice(0, 60), body.ref.slice(0, 60), body.version.slice(0, 40), 'refused', 'already_used', t, t).run();
      return json({ id, poll_token: poll, status: 'refused', reason: 'already_used' });
    }

    if (await openRequestForDevice(env, dkey)) {
      return json({ field: 'device' }, 400);
    }

    if (await limited(env, 'lic:pending:' + ip, MAX_PENDING_PER_IP)) return json({ error: 'rate' }, 429);

    await env.DB.prepare(
      'INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(id, pollHash, body.product, body.kind, body.device, dkey, body.machine, body.nonce, body.shop.slice(0, 60), body.ref.slice(0, 60), body.version.slice(0, 40), 'pending', t, t).run();

    await notifyOwner(env, body);
    return json({ id, poll_token: poll, status: 'pending' });
  }

  if (url.pathname === '/licence/status' && request.method === 'GET') {
    const id = url.searchParams.get('id') || '';
    const auth = request.headers.get('Authorization') || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
    if (!id || !token) return json({}, 401);
    const pollHash = await sha256Hex(token);
    const row = await env.DB.prepare('SELECT * FROM licence_requests WHERE id = ? AND poll_token_hash = ?').bind(id, pollHash).first();
    if (!row) return json({}, 401);
    const calendarDay = hubCalendarDay(env);
    const time = { calendar_day: calendarDay, serverTime: calendarDay };
    if (row.status === 'pending') return json({ status: 'pending', stage: row.stage || '', ...time });
    if (row.status === 'approved') return json({ status: 'pending', stage: 'approved', ...time });
    if (row.status === 'issued' && row.code) return json({ status: 'issued', code: row.code, ...time });
    if (row.status === 'refused') return json({ status: 'refused', reason: row.reason || 'refused', ...time });
    if (row.status === 'expired') return json({ status: 'expired', ...time });
    if (row.status === 'delivered') return json({ status: 'delivered', ...time });
    return json({ status: row.status, ...time });
  }

  if (url.pathname === '/licence/ack' && request.method === 'POST') {
    let body;
    try { body = await request.json(); } catch { return json({ error: 'json' }, 400); }
    const id = body.id || '';
    const auth = request.headers.get('Authorization') || '';
    const token = auth.startsWith('Bearer ') ? auth.slice(7) : '';
    if (!id || !token) return json({}, 401);
    const pollHash = await sha256Hex(token);
    await env.DB.prepare(
      'UPDATE licence_requests SET status = ?, code = NULL, updated_at = ? WHERE id = ? AND poll_token_hash = ?',
    ).bind('delivered', now(), id, pollHash).run();
    return json({ ok: true });
  }

  return null;
}

async function notifyOwner(env, body) {
  const token = env.TELEGRAM_BOT_TOKEN;
  const chat = env.TELEGRAM_CHAT_ID;
  if (!token || !chat) return;
  const text = `طلب ترخيص جديد\n${body.kind} · ${body.shop || '—'}\nجهاز: ${body.device}`;
  try {
    await fetch(`https://api.telegram.org/bot${token}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: chat, text }),
    });
  } catch { /* optional */ }
}

function signedFromRow(row, signed = null) {
  if (signed) return signed;
  return {
    code: row.code,
    serial: '',
    first_day: '',
    last_day: '',
    edition: 'trial',
    product: row.product,
    device: row.device,
  };
}

/** Drop any trial locks this request claimed but did not complete (lost race or failed issue). */
async function releaseLocksForRequest(env, requestId) {
  await env.DB.prepare('DELETE FROM machine_trials WHERE request_id = ?').bind(requestId).run();
}

/** @returns {{ outcome: 'won' | 'concurrent' | 'lost' }} */
async function claimAndIssue(env, requestId, dkey, machineHash, signed, t) {
  const locks = [deviceLockKey(dkey)];
  if (machineHash) locks.push(machineLockKey(machineHash));

  const stmts = locks.map((lock) =>
    env.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?) ON CONFLICT(machine) DO NOTHING').bind(lock, requestId, t),
  );
  const lockPlaceholders = locks.map(() => '?').join(',');
  const issueBind = [signed.code, t, requestId, ...locks, requestId, locks.length];
  stmts.push(
    env.DB.prepare(
      `UPDATE licence_requests SET status = ?, stage = ?, code = ?, updated_at = ?
       WHERE id = ? AND code IS NULL AND status NOT IN ('refused', 'delivered')
       AND (SELECT COUNT(*) FROM machine_trials WHERE machine IN (${lockPlaceholders}) AND request_id = ?) = ?`,
    ).bind('issued', 'approved', ...issueBind),
  );
  const results = await env.DB.batch(stmts);
  const issueChanges = results[results.length - 1]?.meta?.changes ?? 0;

  if (issueChanges > 0) return { outcome: 'won' };

  const after = await env.DB.prepare('SELECT code, status FROM licence_requests WHERE id = ?').bind(requestId).first();
  if (after?.status === 'issued' && after?.code) {
    return { outcome: 'concurrent' };
  }

  await releaseLocksForRequest(env, requestId);
  await env.DB.prepare(
    'UPDATE licence_requests SET status = ?, reason = ?, code = NULL, updated_at = ? WHERE id = ? AND status NOT IN (?, ?, ?)',
  ).bind('refused', 'already_used', t, requestId, 'issued', 'delivered', 'refused').run();
  return { outcome: 'lost' };
}

async function approvePaidRequest(env, row, paidPrivateKey, options = {}) {
  const force = options.force === true;
  if (row.status === 'issued' && row.code) {
    return signedFromRow(row);
  }
  let dkey;
  try {
    dkey = deviceKey(row.device_key || row.device);
  } catch {
    await refuseRequest(env, row.id, 'bad_device');
    throw new Error('bad_device_code');
  }
  const t = now();
  const tz = env.LICENCE_CALENDAR_TZ || 'Africa/Cairo';
  const monthlyDays = Number(env.MONTHLY_DAYS || 30);
  const monthlyGrace = Number(env.MONTHLY_GRACE || 3);
  let signed;
  try {
    signed = await issuePaidCode(paidPrivateKey, row.product, row.device, row.kind, new Date(), tz, { monthlyDays, monthlyGrace });
  } catch (e) {
    if (e?.message === 'bad_device_code') {
      await refuseRequest(env, row.id, 'bad_device');
    }
    throw e;
  }
  const updated = await env.DB.prepare(
    'UPDATE licence_requests SET status = ?, stage = ?, code = ?, updated_at = ? WHERE id = ? AND code IS NULL AND status NOT IN (?, ?)',
  ).bind('issued', 'approved', signed.code, t, row.id, 'refused', 'delivered').run();
  if (!updated.meta?.changes) {
    const existing = await env.DB.prepare('SELECT * FROM licence_requests WHERE id = ?').bind(row.id).first();
    if (existing?.code) return signedFromRow(existing, signed);
    return null;
  }
  const existingCustomer = await env.DB.prepare(
    'SELECT id FROM customers WHERE device = ? AND serial = ? LIMIT 1',
  ).bind(signed.device, signed.serial).first();
  if (!existingCustomer) {
    await env.DB.prepare(
      'INSERT INTO customers(id, shop, device, kind, serial, first_day, last_day, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
    ).bind(crypto.randomUUID(), row.shop || '—', signed.device, row.kind, signed.serial, signed.first_day, signed.last_day, t).run();
  }
  return signed;
}

export async function approveRequest(env, requestId, privateKey, options = {}) {
  const force = options.force === true;
  const paidPrivateKey = options.paidPrivateKey || null;
  const row = await env.DB.prepare('SELECT * FROM licence_requests WHERE id = ?').bind(requestId).first();
  if (!row || row.status === 'refused' || row.status === 'delivered') return null;

  if (row.kind !== 'trial') {
    if (!paidPrivateKey) {
      await refuseRequest(env, requestId, REASON_PAID_IN_STUDIO);
      return { refused: true, reason: REASON_PAID_IN_STUDIO };
    }
    try {
      return await approvePaidRequest(env, row, paidPrivateKey, options);
    } catch (e) {
      if (e?.message === 'bad_device_code') throw e;
      throw e;
    }
  }

  let dkey;
  try {
    dkey = deviceKey(row.device_key || row.device);
  } catch {
    await refuseRequest(env, requestId, 'bad_device');
    throw new Error('bad_device_code');
  }
  const machineHash = normalizeMachineHash(row.machine);

  if (row.status === 'issued' && row.code) {
    if (force) return signedFromRow(row);
    if (await locksOwnedByRequest(env, dkey, machineHash, requestId)) {
      return signedFromRow(row);
    }
    await env.DB.prepare('UPDATE licence_requests SET code = NULL, status = ?, updated_at = ? WHERE id = ?')
      .bind('pending', now(), requestId).run();
    row.status = 'pending';
    row.code = null;
  }

  const existingIssued = await findIssuedTrialForLocks(env, dkey, machineHash);
  if (existingIssued) {
    return existingTrialResponse(existingIssued, requestId);
  }

  if (await trialUsedOnline(env, dkey, machineHash)) {
    await refuseRequest(env, requestId, 'already_used');
    return null;
  }

  const t = now();
  const days = Number(env.TRIAL_DAYS || 14);
  const tz = env.LICENCE_CALENDAR_TZ || 'Africa/Cairo';
  let signed;
  try {
    signed = await issueTrialCode(privateKey, row.product, row.device, days, new Date(), tz);
  } catch (e) {
    if (e?.message === 'bad_device_code') {
      await refuseRequest(env, requestId, 'bad_device');
    }
    throw e;
  }

  const claim = await claimAndIssue(env, requestId, dkey, machineHash, signed, t);

  if (claim.outcome === 'won') {
    const issued = await env.DB.prepare('SELECT * FROM licence_requests WHERE id = ?').bind(requestId).first();
    const existing = await env.DB.prepare(
      'SELECT id FROM customers WHERE device = ? AND serial = ? LIMIT 1',
    ).bind(signed.device, signed.serial).first();
    if (!existing) {
      await env.DB.prepare(
        'INSERT INTO customers(id, shop, device, kind, serial, first_day, last_day, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
      ).bind(crypto.randomUUID(), row.shop || '—', signed.device, row.kind, signed.serial, signed.first_day, signed.last_day, t).run();
    }
    return signedFromRow(issued, signed);
  }

  if (claim.outcome === 'concurrent') {
    const issued = await env.DB.prepare('SELECT * FROM licence_requests WHERE id = ?').bind(requestId).first();
    return signedFromRow(issued);
  }

  const afterLoss = await findIssuedTrialForLocks(env, dkey, machineHash);
  if (afterLoss) return existingTrialResponse(afterLoss, requestId);

  return null;
}

export async function refuseRequest(env, requestId, reason = 'refused') {
  await env.DB.prepare('UPDATE licence_requests SET status = ?, reason = ?, updated_at = ? WHERE id = ?')
    .bind('refused', reason, now(), requestId).run();
}

export async function issueOfflineCustomer(env, privateKey, device, shop, productId, options = {}) {
  const dkey = deviceKey(device);
  const existingIssued = await findIssuedTrialForLocks(env, dkey, null);
  if (existingIssued) {
    const out = existingTrialResponse(existingIssued, 'offline');
    return out;
  }
  if (await trialUsedForDevice(env, dkey)) {
    throw new Error('already_used');
  }
  const days = Number(env.TRIAL_DAYS || 14);
  const tz = env.LICENCE_CALENDAR_TZ || 'Africa/Cairo';
  const signed = await issueTrialCode(privateKey, productId, device, days, new Date(), tz);
  const t = now();
  const requestId = 'offline:' + crypto.randomUUID();
  const lock = deviceLockKey(dkey);
  const shopName = shop.slice(0, 60) || '—';

  const stmts = [
    env.DB.prepare('INSERT INTO machine_trials(machine, request_id, at) VALUES(?, ?, ?) ON CONFLICT(machine) DO NOTHING').bind(lock, requestId, t),
    env.DB.prepare(
      `INSERT INTO licence_requests(id, poll_token_hash, product, kind, device, device_key, machine, nonce, shop, ref, version, status, code, created_at, updated_at)
       SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
       WHERE (SELECT COUNT(*) FROM machine_trials WHERE machine = ? AND request_id = ?) = 1
       AND NOT EXISTS (SELECT 1 FROM licence_requests WHERE device_key = ? AND status = 'issued' AND code IS NOT NULL)`,
    ).bind(requestId, 'offline', productId, 'trial', device, dkey, '', 'offline', shopName, '', '', 'issued', signed.code, t, t, lock, requestId, dkey),
  ];
  const results = await env.DB.batch(stmts);
  const issuedChanges = results[1]?.meta?.changes ?? 0;
  if (issuedChanges === 0) {
    const again = await findIssuedTrialForLocks(env, dkey, null);
    if (again) return existingTrialResponse(again, 'offline');
    throw new Error('already_used');
  }
  await env.DB.prepare(
    'INSERT INTO customers(id, shop, device, kind, serial, first_day, last_day, created_at) VALUES(?, ?, ?, ?, ?, ?, ?, ?)',
  ).bind(crypto.randomUUID(), shopName, signed.device, 'trial', signed.serial, signed.first_day, signed.last_day, t).run();
  return signed;
}

/** Drop activation codes from delivered rows older than TRIAL_DAYS (scheduled). */
export async function purgeStaleCodes(env) {
  const days = Number(env.TRIAL_DAYS || 14);
  const cutoff = now() - days * 86400;
  await expireStalePending(env);
  await env.DB.prepare(
    "UPDATE licence_requests SET code = NULL WHERE code IS NOT NULL AND updated_at < ? AND status IN ('delivered', 'issued')",
  ).bind(cutoff).run();
}
