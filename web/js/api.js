// Talking to the shop server. Every error carries a dictionary key, so the person reads the reason in their language.
import { t, has } from './i18n.js';

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.error || 'error');
    this.status = status;
    this.key = body?.key || '';
    this.vars = body?.vars || {};
    this.body = body || {};
  }
  get human() {
    if (this.status === 0) return t('err.offline');
    if (this.key && has(this.key)) return t(this.key, this.vars);
    if (this.key && this.key.startsWith('lic.err.')) return t('lic.err.generic');
    return this.message || t('err.server');
  }
}

const listeners = { auth: [], licence: [], online: [] };
export function on(event, fn) { listeners[event].push(fn); }
function emit(event, data) { listeners[event].forEach((fn) => fn(data)); }

let online = true;
function setOnline(v) { if (v !== online) { online = v; emit('online', v); } }
export function isOnline() { return online; }

async function request(method, path, body) {
  let res;
  try {
    res = await fetch(path, {
      method, credentials: 'same-origin', cache: 'no-store',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    setOnline(false);
    throw new ApiError(0, { key: 'err.offline' });
  }
  setOnline(true);
  const type = res.headers.get('Content-Type') || '';
  if (!type.includes('json')) {
    if (!res.ok) throw new ApiError(res.status, {});
    return res;
  }
  const data = await res.json().catch(() => ({}));
  if (res.ok) return data;
  if (res.status === 401) emit('auth', data);
  if (res.status === 402) emit('licence', data.licence);
  throw new ApiError(res.status, data);
}

export const api = {
  get(path, params) {
    const q = params ? '?' + new URLSearchParams(Object.entries(params).filter(([, v]) => v !== undefined && v !== null && v !== '')) : '';
    return request('GET', path + q);
  },
  post(path, body = {}) { return request('POST', path, body); },
};

export function key() {
  return (crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36) + Math.random().toString(36).slice(2));
}

// a light ping so the offline bar clears by itself when the PC is back
setInterval(() => { if (!online) fetch('/api/boot', { cache: 'no-store' }).then(() => setOnline(true)).catch(() => {}); }, 4000);
