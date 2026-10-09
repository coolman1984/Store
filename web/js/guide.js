// In-app guide, the first-sign-in consent card, and consented telemetry.
// The factory files in vendor/ are not edited. This module must not import app.js (app.js imports this).
import { api } from './api.js';
import { lang, t } from './i18n.js';
import { $, html, open, run } from './ui.js';

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
    files = Promise.all(['catalogue', 'ar', 'en'].map((name) => fetch('/guide/' + name + '.json').then((r) => {
        if (!r.ok) throw new Error('Guide unavailable');
        return r.json();
      }))).then(([catalogue, ar, en]) => ({ catalogue, ar, en })).catch((e) => { files = null; throw e; });
  }
  return files;
}

let tel = null;
let telemetryAllowed = false;
let sessionPerson = null;
let generation = 0;
let disposeGuide = () => {};

export async function refreshConsent() {
  const current = generation;
  telemetryAllowed = false;
  // Discard pre-consent events and anything left by the previous signed-in person.
  if (tel) await tel.flush();
  if (!guideLive) return;
  try {
    const status = await api.get('/api/consent/status');
    if (current === generation) telemetryAllowed = !!status.tracking;
  } catch { /* tracking stays off */ }
}
/** One telemetry client for the whole tab. A second init would stack error listeners. */
export function startTelemetry() {
  if (tel || !window.AFTelemetry) return tel;
  const client = window.AFTelemetry.init({
    lang: lang(),
    page: () => document.body.dataset.route || 'signin',
    request: (method, url, body) => {
      if (!telemetryAllowed || !guideLive || !sessionPerson) return Promise.resolve({ queued: 0 });
      return method === 'GET' ? api.get(url) : api.post(url, body);
    },
  });
  tel = { flush: client.flush, track: (type, data) => {
    if (telemetryAllowed && guideLive) client.track(type, data);
  }, report: reportProblem };
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
  const current = ++generation;
  disposeGuide();
  document.querySelectorAll('[data-afc="card"], [data-aft="dialog"]').forEach((n) => n.remove());
  guideLive = !!live;
  sessionPerson = live ? person : null;
  telemetryAllowed = false;
  window.__afguide = null;
  window.__afguideLive = guideLive;
  startTelemetry();
  if (tel) await tel.flush();
  let pack;
  try { pack = await loadFiles(); } catch { return null; }
  if (current !== generation || !window.AFGuide) return null;
  document.querySelectorAll('[data-afg]').forEach((n) => n.remove());
  let active = true;
  let pending = Promise.resolve();
  const options = {
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
    request: (method, url, body) => {
      if (!active) return Promise.resolve(null);
      if (method === 'GET') return api.get(url);
      pending = pending.catch(() => null).then(() => active ? api.post(url, body) : null);
      return pending;
    },
    api: live ? '/api/guide' : null,
  };
  // The factory exposes stop(), but no destroy(). Record its two global listeners during
  // synchronous init so remounting cannot leave an old person's F1 handler or coach alive.
  const listeners = [];
  const targets = [document, window];
  const originals = targets.map((target) => target.addEventListener);
  let ctl;
  try {
    targets.forEach((target, i) => {
      target.addEventListener = function (type, listener, opts) {
        listeners.push([target, type, listener, opts]);
        originals[i].call(target, type, listener, opts);
      };
    });
    ctl = window.AFGuide.init(options);
  } finally {
    targets.forEach((target, i) => { target.addEventListener = originals[i]; });
  }
  disposeGuide = () => {
    active = false;
    ctl.stop();
    listeners.forEach(([target, type, listener, opts]) => target.removeEventListener(type, listener, opts));
    document.querySelectorAll('[data-afg]').forEach((n) => n.remove());
  };
  window.__afguide = ctl;
  window.__afguideLive = guideLive;
  attachHelp();
  await ctl.ready;
  if (current === generation) await refreshConsent();
  return ctl;
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
  const current = generation;
  try { p = await api.get('/api/consent/prompt', { lang: lang() }); } catch { return null; }
  if (current !== generation || !p || !p.ask || document.querySelector('[data-afc="card"]')) return null;
  const answer = window.AFConsent.ask(p, async (decision) => {
    const card = document.querySelector('[data-afc="card"]');
    const buttons = card ? [...card.querySelectorAll('button')] : [];
    buttons.forEach((b) => { b.disabled = true; });
    try {
      if (current !== generation) return;
      await api.post('/api/consent/decide', { decision, text_id: p.text_id, lang: p.lang, scope: p.scope });
      if (current === generation) await refreshConsent();
    } catch {
      buttons.forEach((b) => { b.disabled = false; });
      let status = card.querySelector('[role="status"]');
      if (!status) { status = document.createElement('p'); status.setAttribute('role', 'status'); card.querySelector('section').append(status); }
      status.textContent = t('privacy.retry');
      // The factory removes its card only when the callback resolves.
      return new Promise(() => {});
    }
  });
  // This product displays a non-modal corner card; reflect that in the accessibility tree.
  document.querySelector('[data-afc="card"] section')?.setAttribute('aria-modal', 'false');
  return answer;
}

/** Plain-language summary of exactly what the preview will store. The raw payload stays behind a toggle. */
async function showReview(box, preview, typed) {
  const data = (preview.event && preview.event.data) || {};
  const l = lang();
  let texts = {};
  try { texts = (await loadFiles())[l] || {}; } catch { texts = {}; }
  const none = t('privacy.reviewNone');
  const pageName = data.page ? (t('nav.' + data.page) !== 'nav.' + data.page ? t('nav.' + data.page) : data.page) : none;
  const problem = data.problem ? (texts['problem.' + data.problem + '.see'] || data.problem) : none;
  const lesson = data.guide ? (texts['guide.' + data.guide + '.title'] || data.guide) : none;
  const rows = [
    [t('privacy.reviewText'), data.text || ''],
    [t('privacy.reviewVersion'), preview.version || ''],
    [t('privacy.reviewProblem'), problem],
    [t('privacy.reviewLesson'), lesson],
    [t('privacy.reviewPage'), pageName],
    [t('privacy.reviewDevice'), data.diagnostics ? t('privacy.reviewDeviceYes') : t('privacy.reviewDeviceNo')],
    [t('privacy.reviewIds'), t('privacy.reviewIdsText')],
  ];
  const facts = $('[data-report-facts]', box);
  facts.replaceChildren();
  rows.forEach(([label, value], i) => {
    const dt = document.createElement('dt'); dt.textContent = label;
    const dd = document.createElement('dd'); dd.textContent = value;
    if (i === 0) { dd.dir = 'auto'; dd.dataset.reportSentText = ''; }
    facts.append(dt, dd);
  });
  $('[data-report-redacted]', box).hidden = (data.text || '') === typed;
  $('[data-report-raw]', box).textContent = JSON.stringify(preview.event, null, 2);
  $('[data-report-tech]', box).open = false;
  $('[data-report-review]', box).hidden = false;
}

async function reportProblem(ctx = {}) {
  if (!guideLive) return;
  await refreshConsent();
  open({ title: t('privacy.reportTitle'), body: html`<p>${t('privacy.reportNote')}</p>
    ${!telemetryAllowed ? html`<p>${t('privacy.reportConsent')}</p>` : html`
      <div class="field"><label for="report-text">${t('privacy.reportText')}</label>
      <textarea class="input" id="report-text" data-report-text dir="auto" rows="4" maxlength="2000"></textarea></div>
      <label class="check"><input type="checkbox" data-report-diag>${t('privacy.reportDiagnostics')}</label>
      <section class="report-review" data-report-review hidden aria-live="polite">
        <h3>${t('privacy.reviewSent')}</h3>
        <dl class="report-facts" data-report-facts></dl>
        <p class="report-redacted" data-report-redacted hidden>${t('privacy.reviewRedacted')}</p>
        <h3>${t('privacy.reviewNotSent')}</h3>
        <ul class="report-not-sent">
          <li>${t('privacy.notSent.passwords')}</li><li>${t('privacy.notSent.people')}</li>
          <li>${t('privacy.notSent.money')}</li><li>${t('privacy.notSent.screen')}</li>
        </ul>
        <p class="muted">${t('privacy.reviewWhen')}</p>
        <details class="report-tech" data-report-tech><summary>${t('privacy.reviewTech')}</summary>
          <pre class="report-preview" data-report-raw dir="ltr"></pre></details>
      </section>`}`,
  foot: telemetryAllowed ? html`<button class="btn" data-report-cancel>${t('act.cancel')}</button>
    <button class="btn" data-report-check>${t('privacy.reportPreview')}</button>
    <button class="btn accent" data-report-send disabled>${t('privacy.reportSend')}</button>` : null,
  mount(box, close) {
    box.classList.add('report-dialog');
    if (!telemetryAllowed) return;
    const current = generation;
    let preview = null;
    let body = null;
    let revision = 0;
    const invalidate = () => {
      revision++;
      preview = null; $('[data-report-send]', box).disabled = true; $('[data-report-review]', box).hidden = true;
    };
    $('[data-report-cancel]', box).addEventListener('click', () => close());
    $('[data-report-text]', box).addEventListener('input', invalidate);
    $('[data-report-diag]', box).addEventListener('change', invalidate);
    $('[data-report-check]', box).addEventListener('click', async (e) => {
      invalidate();
      const requested = revision;
      const text = $('[data-report-text]', box).value.trim();
      if (!text) { $('[data-report-text]', box).focus(); return; }
      body = { kind: 'problem', page: ctx.page || document.body.dataset.route,
        text,
        guide: ctx.guide || null, problem: ctx.problem || null, diagnostics: $('[data-report-diag]', box).checked };
      const result = await run(api.post('/api/telemetry/feedback/preview', body), null, e.currentTarget);
      if (!result || requested !== revision || current !== generation || !box.isConnected) return;
      preview = result;
      await showReview(box, preview, text);
      if (requested !== revision || current !== generation || !box.isConnected) {
        // edited while the summary was being built: never leave a stale summary or an enabled send
        if (preview === null || preview === result) { preview = null; $('[data-report-review]', box).hidden = true; }
        return;
      }
      $('[data-report-send]', box).disabled = false;
    });
    $('[data-report-send]', box).addEventListener('click', async (e) => {
      if (!preview || current !== generation) return;
      const result = await run(api.post('/api/telemetry/feedback', { ...body,
        diagnostics: preview.event.data.diagnostics || false, confirm: preview.digest }), t('privacy.reportQueued'), e.currentTarget);
      if (result) close();
    });
  } });
}
