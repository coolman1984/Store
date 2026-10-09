// In-app guide, the first-sign-in consent card, and consented telemetry.
// The factory files in vendor/ are not edited. This module must not import app.js (app.js imports this).
import { api } from './api.js';
import { lang, t } from './i18n.js';

const BUILTINS = ['owner', 'manager', 'cashier', 'storekeeper'];

/** Same mapping as server/assist.py guide_role: a custom profile follows the closest built-in course. */
export function guideRole(role, perms) {
  if (BUILTINS.includes(role)) return role;
  const have = new Set(perms || []);
  if (have.has('settings.edit') || have.has('users.manage')) return 'owner';
  if (have.has('reports.view') || have.has('cash.safe') || have.has('shifts.manage')) return 'manager';
  if (have.has('pos.sell')) return 'cashier';
  if (have.has('stock.view') || have.has('products.view') || have.has('stock.receive')) return 'storekeeper';
  return 'cashier';
}

let files = null;
function loadFiles() {
  if (!files) {
    files = Promise.all([
      fetch('/guide/catalogue.json').then((r) => r.json()),
      fetch('/guide/ar.json').then((r) => r.json()),
      fetch('/guide/en.json').then((r) => r.json()),
    ]).then(([catalogue, ar, en]) => ({ catalogue, ar, en }));
  }
  return files;
}

let tel = null;
/** One telemetry client for the whole tab. A second init would stack error listeners. */
export function startTelemetry() {
  if (tel || !window.AFTelemetry) return tel;
  tel = window.AFTelemetry.init({
    lang: lang(),
    page: () => document.body.dataset.route || 'signin',
    request: (method, url, body) => (method === 'GET' ? api.get(url) : api.post(url, body)),
  });
  window.__aftel = tel;
  return tel;
}

let guideLive = false;

export function attachHelp() {
  const g = window.__afguide;
  if (!g) return;
  document.querySelectorAll('[data-guide-slot]').forEach((slot) => {
    slot.replaceChildren(g.helpButton());
  });
}

/**
 * Mount the coach. live=false on the sign-in and setup screens (no session yet).
 * A later mount drops the previous chrome; F1 is handled inside AFGuide.init.
 */
export async function mountGuide({ live, role, person, can, go }) {
  startTelemetry();
  const pack = await loadFiles();
  document.querySelectorAll('[data-afg]').forEach((n) => n.remove());
  const ctl = window.AFGuide.init({
    catalogue: pack.catalogue,
    texts: { ar: pack.ar, en: pack.en },
    role,
    person: person || 'me',
    ui: (key) => t(key),
    uiLang: () => lang(),
    route: () => document.body.dataset.route || 'signin',
    go: (page) => { if (go && page !== 'signin' && page !== 'setup') go(page); },
    can: (perm) => (can ? !!can(perm) : false),
    track: (type, data) => { if (tel) tel.track(type, data); },
    onReport: (ctx) => { if (tel) tel.report(ctx); },
    request: (method, url, body) => (method === 'GET' ? api.get(url) : api.post(url, body)),
    api: live ? '/api/guide' : null,
  });
  guideLive = !!live;
  window.__afguide = ctl;
  window.__afguideLive = guideLive;
  attachHelp();
  return ctl.ready;
}

export function onRoute(name) {
  if (window.__afguide) window.__afguide.routeChanged();
  if (tel && guideLive && name) tel.track('use.page', { page: name });
}

/** After the server confirms an action: move the coach, then refresh live states (setup, shift, first sale). */
export async function signal(name) {
  const g = window.__afguide;
  if (g) g.signal(name);
  if (!guideLive || !g) return;
  try {
    const st = await api.get('/api/guide/state');
    if (st && Array.isArray(st.states)) g.setStates(st.states);
  } catch { /* the coach already moved on the event */ }
}

/** The first-sign-in card. Two equal buttons; Esc does not decide (the factory card). */
export async function maybeConsent() {
  if (!guideLive || !window.AFConsent) return null;
  let p;
  try { p = await api.get('/api/consent/prompt', { lang: lang() }); } catch { return null; }
  if (!p || !p.ask) return null;
  return window.AFConsent.ask(p, (decision) => api.post('/api/consent/decide', {
    decision, text_id: p.text_id, lang: p.lang, scope: p.scope,
  }));
}
