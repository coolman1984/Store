// Building blocks every page uses: safe HTML, icons, money/date format, toasts, dialogs, side panels, sheets,
// confirmations with a reason, the manager's approval, empty and loading states.
import { t, lang } from './i18n.js';
import { ApiError } from './api.js';

// ---------------------------------------------------------------- safe HTML
export class Raw { constructor(s) { this.s = s; } toString() { return this.s; } }
export const raw = (s) => new Raw(String(s));
/** attribute marking the current tab/link (a plain string would be escaped inside a tag) */
export const CUR = new Raw('aria-current="page"');
const ESC = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
export const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ESC[c]);
function enc(v) {
  if (v === null || v === undefined || v === false) return '';
  if (v instanceof Raw) return v.s;
  if (Array.isArray(v)) return v.map(enc).join('');
  return esc(v);
}
export function html(strings, ...vals) {
  let out = '';
  strings.forEach((s, i) => { out += s; if (i < vals.length) out += enc(vals[i]); });
  return new Raw(out);
}
export function put(el, content) { el.innerHTML = content instanceof Raw ? content.s : enc(content); return el; }
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const icon = (name, cls = '') => raw(`<svg class="i ${cls}" aria-hidden="true"><use href="/img/icons.svg#${name}"/></svg>`);

// ---------------------------------------------------------------- numbers, money, dates
const nf = () => new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 });
export function num(n, digits = 0) {
  return new Intl.NumberFormat('en-US', { minimumFractionDigits: digits, maximumFractionDigits: Math.max(digits, 3) }).format(n || 0);
}
/** piasters → "1,250 ج.م" (decimals only when there are piasters) */
export function money(p, { sign = false, bare = false, whole = false } = {}) {
  const v = whole ? Math.round((p || 0) / 100) : (p || 0) / 100;
  const s = new Intl.NumberFormat('en-US', { minimumFractionDigits: Number.isInteger(v) ? 0 : 2, maximumFractionDigits: 2 }).format(Math.abs(v));
  const signed = (p < 0 ? '−' : sign && p > 0 ? '+' : '') + s;
  const n = `\u2066${signed}\u2069`; // the number keeps its own left-to-right order (sign, digits) inside Arabic text
  if (bare) return n;
  return lang() === 'ar' ? `${n} ${t('cur')}` : `${t('cur')} ${n}`;
}
export const moneyH = (p, opts) => html`<span class="money num">${money(p, opts)}</span>`;
/** "1250.5" or "١٢٥٠" → 125050 piasters, or null */
export function parseMoney(text) {
  if (text === null || text === undefined) return null;
  const s = String(text).trim().replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/[٫,]/g, (c) => (c === '٫' ? '.' : '')).replace(/\s/g, '');
  if (!s || !/^\d+(\.\d{0,2})?$/.test(s)) return null;
  return Math.round(parseFloat(s) * 100);
}
export function parseQty(text) {
  const s = String(text ?? '').trim().replace(/[٠-٩]/g, (d) => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace('٫', '.');
  if (!/^\d+(\.\d{1,3})?$/.test(s)) return null;
  return parseFloat(s);
}
const pad = (n) => String(n).padStart(2, '0');
export function date(iso, withTime = false) {
  if (!iso) return '';
  const d = iso.length === 10 ? new Date(iso + 'T00:00:00') : new Date(iso);
  const s = `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()}`;
  return withTime ? `${s} ${pad(d.getHours())}:${pad(d.getMinutes())}` : s;
}
export const time = (iso) => { const d = new Date(iso); return `${pad(d.getHours())}:${pad(d.getMinutes())}`; };
export function ago(iso) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return t('time.now');
  if (s < 3600) return t('time.min', { n: Math.round(s / 60) });
  if (s < 86400) return t('time.hour', { n: Math.round(s / 3600) });
  return t('time.day', { n: Math.round(s / 86400) });
}
export function today() { const d = new Date(); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
export function addDays(day, n) { const d = new Date(day + 'T12:00:00'); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`; }
export const initials = (name) => (name || '?').trim().split(/\s+/).slice(0, 2).map((w) => w[0]).join('');
export const _nf = nf;

// ---------------------------------------------------------------- feedback
let toastBox;
export function toast(text, kind = 'ok', ms = 2600) {
  toastBox = toastBox || document.body.appendChild(Object.assign(document.createElement('div'), { className: 'toasts', role: 'status' }));
  toastBox.setAttribute('aria-live', 'polite');
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  put(el, html`${icon(kind === 'bad' ? 'alert' : 'check-circle')}<span>${text}</span>`);
  toastBox.appendChild(el);
  setTimeout(() => { el.classList.add('out'); setTimeout(() => el.remove(), 260); }, ms);
}
export function errorText(e) { return e instanceof ApiError ? e.human : (e?.message || t('err.server')); }
export function fail(e) { toast(errorText(e), 'bad', 4200); }

/** run a save: busy button, toast on success, the reason on failure, button back. Returns the result or undefined. */
export async function run(promise, okText, btn) {
  if (btn) { btn.setAttribute('aria-busy', 'true'); btn.disabled = true; }
  try {
    const r = await promise;
    if (okText) toast(okText);
    return r;
  } catch (e) {
    fail(e);
    return undefined;
  } finally {
    if (btn) { btn.removeAttribute('aria-busy'); btn.disabled = false; }
  }
}

// ---------------------------------------------------------------- overlays
const stack = [];
function trapKeys(e) {
  const top = stack[stack.length - 1];
  if (!top) return;
  if (e.key === 'Escape' && !top.sticky) { e.preventDefault(); top.close(); }
  if (e.key === 'Tab') {
    const f = $$('button:not([disabled]), [href], input:not([disabled]), select, textarea, [tabindex]:not([tabindex="-1"])', top.box)
      .filter((x) => x.offsetParent !== null);
    if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { last.focus(); e.preventDefault(); }
    else if (!e.shiftKey && document.activeElement === last) { first.focus(); e.preventDefault(); }
  }
}
document.addEventListener('keydown', trapKeys, true);

/**
 * Open a dialog / side panel / bottom sheet.
 * opts: {title, body (Raw), foot (Raw), kind: 'dialog'|'panel'|'sheet', wide, sticky, mount(box, close), onClose}
 */
export function open(opts) {
  const kind = opts.kind || 'dialog';
  const scrim = document.createElement('div');
  scrim.className = 'scrim' + (kind === 'panel' ? ' side' : kind === 'sheet' ? ' sheet' : '');
  const boxCls = kind === 'panel' ? 'panel' : kind === 'sheet' ? 'sheet-box' : 'dialog' + (opts.wide ? ' wide' : '');
  const titleId = 'dlg-' + Math.random().toString(36).slice(2, 8);
  put(scrim, html`<div class="${boxCls}" role="dialog" aria-modal="true" aria-labelledby="${titleId}">
    <div class="dialog-head"><h2 id="${titleId}">${opts.title || ''}</h2>
      ${opts.sticky ? '' : html`<button class="icon-btn" data-close aria-label="${t('act.close')}">${icon('x')}</button>`}</div>
    <div class="dialog-body">${opts.body || ''}</div>${opts.foot ? html`<div class="dialog-foot">${opts.foot}</div>` : ''}</div>`);
  const box = scrim.firstElementChild;
  const before = document.activeElement;
  const entry = {
    box, sticky: !!opts.sticky,
    close(value) {
      const i = stack.indexOf(entry);
      if (i >= 0) stack.splice(i, 1);
      scrim.remove();
      if (before && before.focus) before.focus();
      opts.onClose && opts.onClose(value);
    },
  };
  stack.push(entry);
  scrim.addEventListener('mousedown', (e) => { if (e.target === scrim && !opts.sticky) entry.close(); });
  $$('[data-close]', box).forEach((b) => b.addEventListener('click', () => entry.close()));
  document.body.appendChild(scrim);
  opts.mount && opts.mount(box, entry.close);
  const auto = $('[autofocus]', box) || $('input, select, textarea, button.primary, button.volt', box);
  setTimeout(() => auto && auto.focus(), 30);
  return entry;
}
export function closeAll() { while (stack.length) stack[stack.length - 1].close(); }
export const anyOpen = () => stack.length > 0;

/** Yes/no question. With reason:true the person must write why (3+ letters) – used for anything that reverses money or data. */
export function confirm({ title, text, ok, danger = false, reason = false }) {
  return new Promise((resolve) => {
    open({
      title,
      body: html`${text ? html`<p class="muted">${text}</p>` : ''}${reason ? html`<div class="field"><label for="why">${t('f.reason')}</label>
        <textarea id="why" class="input" required minlength="3" placeholder="${t('f.reasonHint')}"></textarea></div>` : ''}`,
      foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button>
        <button class="btn ${danger ? 'danger' : 'primary'}" data-ok>${ok || t('act.ok')}</button>`,
      mount(box, close) {
        $('[data-ok]', box).addEventListener('click', () => {
          const why = reason ? $('#why', box).value.trim() : true;
          if (reason && why.length < 3) { $('#why', box).setAttribute('aria-invalid', 'true'); $('#why', box).focus(); return; }
          close(why);
        });
      },
      onClose: (v) => resolve(v || false),
    });
  });
}

/** A manager types their own user name and password on this screen. Resolves {username, password} or null. */
export function askApproval(needs = [], pct) {
  const why = needs.map((n) => t('approve.' + n, { pct })).join(' • ');
  return new Promise((resolve) => {
    open({
      title: t('approve.title'),
      body: html`<div class="tip warn">${icon('lock')}<div>${why || t('approve.generic')}</div></div>
        <div class="cols form"><div class="field"><label for="ap-u">${t('f.username')}</label><input id="ap-u" class="input" autocomplete="off" autofocus></div>
        <div class="field"><label for="ap-p">${t('f.password')}</label><input id="ap-p" type="password" class="input" autocomplete="off"></div></div>
        <p class="xs faint">${t('approve.note')}</p>`,
      foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('approve.ok')}</button>`,
      mount(box, close) {
        const go = () => {
          const username = $('#ap-u', box).value.trim(), password = $('#ap-p', box).value;
          if (!username || !password) return;
          close({ username, password });
        };
        $('[data-ok]', box).addEventListener('click', go);
        $('#ap-p', box).addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
      },
      onClose: (v) => resolve(v || null),
    });
  });
}

/** Call fn(approval). If the server answers "needs approval", ask for the manager and try again with the same body. */
export async function withApproval(fn) {
  let approval;
  for (let i = 0; i < 4; i++) {
    try {
      return await fn(approval);
    } catch (e) {
      if (e instanceof ApiError && e.status === 403 && ['err.needsApproval', 'err.approverLimit', 'err.selfApproval', 'err.forbidden'].includes(e.key) && (e.key === 'err.needsApproval' || approval)) {
        if (approval) toast(e.human, 'bad', 3500);
        approval = await askApproval(e.vars.needs || [], e.vars.pct);
        if (!approval) throw Object.assign(new Error(t('approve.cancelled')), { cancelled: true });
        continue;
      }
      if (e instanceof ApiError && e.key && e.key.startsWith('auth.err.') && approval) {
        toast(e.human, 'bad', 3500);
        approval = await askApproval([], 0);
        if (!approval) throw Object.assign(new Error(t('approve.cancelled')), { cancelled: true });
        continue;
      }
      throw e;
    }
  }
  throw new Error(t('approve.cancelled'));
}

// ---------------------------------------------------------------- states
export function empty(iconName, title, hint, action) {
  return html`<div class="empty"><div class="art">${icon(iconName)}</div><h3>${title}</h3>${hint ? html`<p>${hint}</p>` : ''}${action || ''}</div>`;
}
export function skeleton(rows = 4) {
  return html`<div class="stack" aria-busy="true" aria-label="${t('state.loading')}">${Array.from({ length: rows }, (_, i) =>
    html`<div class="sk sk-${i % 4}"></div>`)}</div>`;
}
export function seg(name, options, value) {
  return html`<div class="seg" role="group" data-seg="${name}">${options.map(([v, label, ic]) =>
    html`<button type="button" data-v="${v}" aria-pressed="${String(v) === String(value)}">${ic ? icon(ic) : ''}${label}</button>`)}</div>`;
}
export function bindSeg(root, name, onChange) {
  const g = $(`[data-seg="${name}"]`, root);
  if (!g) return;
  g.addEventListener('click', (e) => {
    const b = e.target.closest('button[data-v]');
    if (!b) return;
    $$('button', g).forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    onChange(b.dataset.v);
  });
}
export const segValue = (root, name) => $(`[data-seg="${name}"] [aria-pressed="true"]`, root)?.dataset.v;

/** WhatsApp link (one person at a time, never bulk: bulk sending gets the shop's number banned) */
export function whatsapp(phone, text) {
  let p = String(phone || '').replace(/\D/g, '');
  if (p.startsWith('0')) p = '2' + p;
  return `https://wa.me/${p}?text=${encodeURIComponent(text)}`;
}

export function download(name, blob) {
  const a = Object.assign(document.createElement('a'), { href: URL.createObjectURL(blob), download: name });
  document.body.appendChild(a); a.click(); setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 500);
}
