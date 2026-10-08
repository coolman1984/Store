// The shell: start-up, sign-in, first-run setup, licence screen, navigation, command palette, keyboard shortcuts.
import { api, on, isOnline, ApiError } from './api.js';
import { applyLang, lang, setLang, t } from './i18n.js';
import { apply as applyPrefs, prefs } from './prefs.js';
import { $, $$, html, icon, put, open, closeAll, anyOpen, toast, fail, run, initials, esc, money } from './ui.js';
import { transition, after, shake } from './motion.js';

export const S = { boot: null, me: null, lookups: null, route: 'home', params: {}, counts: {} };

// route -> view module loader + nav metadata (lazy: a page's code loads the first time it is opened)
export const ROUTES = {
  pos: { icon: 'cart', perm: ['pos.sell'], load: () => import('./views/pos.js'), hot: true },
  home: { icon: 'home', load: () => import('./views/home.js') },
  sales: { icon: 'receipt', perm: ['pos.sell', 'sales.view_all', 'sales.return'], load: () => import('./views/sales.js') },
  customers: { icon: 'users', perm: ['customers.edit', 'installments.collect'], load: () => import('./views/customers.js') },
  products: { icon: 'tag', load: () => import('./views/products.js') },
  stock: { icon: 'warehouse', load: () => import('./views/stock.js') },
  receive: { icon: 'truck', perm: ['stock.receive'], load: () => import('./views/receive.js') },
  cash: { icon: 'safe', perm: ['pos.sell', 'cash.safe', 'shifts.manage', 'cash.expense'], load: () => import('./views/cash.js') },
  watch: { icon: 'eye', perm: ['watch.view'], load: () => import('./views/watch.js') },
  reports: { icon: 'chart', perm: ['reports.view'], load: () => import('./views/reports.js') },
  settings: { icon: 'gear', load: () => import('./views/settings.js') },
  help: { icon: 'help', load: () => import('./views/help.js') },
};
const GROUPS = [['', ['pos', 'home']], ['nav.g.sell', ['sales', 'customers']], ['nav.g.goods', ['products', 'stock', 'receive']],
  ['nav.g.money', ['cash', 'watch', 'reports']], ['nav.g.shop', ['settings', 'help']]];

export const can = (...perms) => !!S.me && perms.some((p) => S.me.perms.includes(p));
const allowed = (r) => !ROUTES[r].perm || can(...ROUTES[r].perm);
export const fmtCount = (v, f) => (f === 'money' ? money(v, { whole: true }) : new Intl.NumberFormat('en-US').format(v));
/** call after a view puts content that arrived later (numbers count up, cards get depth, bars get their width) */
export const settle = (el) => after(el, fmtCount);

export function go(route, params = {}) {
  const q = new URLSearchParams(params).toString();
  location.hash = '#/' + route + (q ? '?' + q : '');
}

// ---------------------------------------------------------------- boot
async function boot() {
  applyPrefs();
  applyLang();
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', applyPrefs);
  on('auth', () => { if (S.me) { S.me = null; toast(t('auth.expired'), 'bad'); } showAuth(); });
  on('licence', (lic) => { if (lic) S.boot.licence = lic; renderBanners(); });
  on('online', renderBanners);
  try {
    S.boot = await api.get('/api/boot');
  } catch (e) {
    put(document.body, html`<main class="empty">${icon('alert')}<h3>${t('err.offline')}</h3></main>`);
    setTimeout(boot, 3000);
    return;
  }
  document.title = (S.boot.practice ? t('app.practice') + ' · ' : '') + t('app.name');
  if (S.boot.setup) return showSetup();
  if (!S.boot.user) return showAuth();
  S.me = S.boot.user;
  await startShell();
}

async function startShell() {
  try { S.lookups = await api.get('/api/lookups'); } catch (e) { fail(e); }
  renderShell();
  window.addEventListener('hashchange', route);
  route();
}

// ---------------------------------------------------------------- sign-in, setup, licence
function authFrame(content) {
  put(document.body, html`<main class="auth">
    <section class="auth-art" aria-hidden="true">
      <div class="brand"><div class="brand-mark">${icon('bolt')}</div><div><div class="brand-name">${t('app.name')}</div>
        <div class="brand-shop">${S.boot?.shop_name || ''}</div></div></div>
      <div class="floor">
        <div class="float f1"><span class="tag">${t('auth.art.sale')}</span><b class="num">12,450</b><small>${t('cur')}</small></div>
        <div class="float f2"><span class="tag ok">${t('auth.art.drawer')}</span><b>${t('auth.art.balanced')}</b></div>
        <div class="float f3"><span class="tag warn">${t('auth.art.instal')}</span><b class="num">3</b><small>${t('auth.art.today')}</small></div>
        <div class="float f4">${icon('shield')}<span>${t('auth.art.serial')}</span></div>
      </div>
      <p class="auth-line">${t('auth.tagline')}</p>
    </section>
    <section class="auth-form">${content}
      <div class="auth-tools"><button class="chip" data-lang>${icon('globe')}${lang() === 'ar' ? 'English' : 'العربية'}</button>
      ${S.boot?.practice ? html`<span class="chip volt">${icon('sparkle')}${t('app.practice')}</span>` : ''}</div>
    </section></main>`);
  $('[data-lang]').addEventListener('click', () => { setLang(lang() === 'ar' ? 'en' : 'ar'); boot(); });
}

function showAuth() {
  closeAll();
  authFrame(html`<form class="card auth-card form" id="auth-form" autocomplete="on">
    <div><h1>${t('auth.welcome')}</h1><p class="muted">${t('auth.sub')}</p></div>
    ${S.boot?.practice ? html`<div class="tip">${icon('sparkle')}<div>${t('auth.practiceHint')}</div></div>` : ''}
    <div class="field"><label for="username">${t('f.username')}</label><input id="username" class="input big" autocomplete="username" required autofocus></div>
    <div class="field"><label for="password">${t('f.password')}</label><input id="password" type="password" class="input big" autocomplete="current-password" required></div>
    <p class="err small" id="auth-err" role="alert"></p>
    <button class="btn volt lg block" type="submit">${t('auth.signIn')}${icon('chev-l', 'flip')}</button>
  </form>`);
  $('#auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter;
    btn.setAttribute('aria-busy', 'true');
    try {
      const r = await api.post('/api/login', { username: $('#username').value, password: $('#password').value });
      S.me = r.user;
      S.boot = await api.get('/api/boot');
      await startShell();
    } catch (err) {
      $('#auth-err').textContent = err instanceof ApiError ? err.human : String(err);
      shake($('#auth-form'));
      $('#password').select();
    } finally { btn.removeAttribute('aria-busy'); }
  });
}

function showSetup() {
  authFrame(html`<form class="card auth-card form" id="setup-form">
    <div><span class="badge volt">${t('setup.step')}</span><h1>${t('setup.title')}</h1><p class="muted">${t('setup.sub')}</p></div>
    <div class="field"><label for="shop">${t('setup.shop')}</label><input id="shop" class="input" required autofocus placeholder="${t('setup.shopHint')}"></div>
    <div class="cols"><div class="field"><label for="phone">${t('f.phone')}</label><input id="phone" class="input" inputmode="tel"></div>
    <div class="field"><label for="addr">${t('f.address')}</label><input id="addr" class="input"></div></div>
    <hr class="sep">
    <div class="cols"><div class="field"><label for="fn">${t('setup.ownerName')}</label><input id="fn" class="input" required></div>
    <div class="field"><label for="un">${t('f.username')}</label><input id="un" class="input" required autocomplete="username"></div></div>
    <div class="field"><label for="pw">${t('f.password')}</label><input id="pw" type="password" class="input" required autocomplete="new-password">
      <span class="hint">${t('setup.pwHint')}</span></div>
    <p class="err small" id="setup-err" role="alert"></p>
    <button class="btn volt lg block" type="submit">${t('setup.go')}</button></form>`);
  $('#setup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api.post('/api/setup', { shop_name: $('#shop').value, shop_phone: $('#phone').value, shop_address: $('#addr').value,
        full_name: $('#fn').value, username: $('#un').value, password: $('#pw').value });
      S.boot = await api.get('/api/boot');
      S.me = S.boot.user;
      await startShell();
      go('settings', { tab: 'licence' });
    } catch (err) { $('#setup-err').textContent = err instanceof ApiError ? err.human : String(err); shake($('#setup-form')); }
  });
}

/** The licence card: device code to send to the vendor, a box to paste the code, what works without a code. */
export function licenceCard(lic, onDone) {
  const st = lic.state;
  const good = ['trial', 'active', 'grace', 'practice'].includes(st);
  return {
    body: html`<div class="lic ${good ? 'good' : ''}">
      <div class="lic-state">${icon(good ? 'shield' : 'key')}<div><b>${t('lic.state.' + st)}</b>
        ${lic.last_day ? html`<div class="small muted">${t('lic.until', { day: lic.last_day, n: lic.days_left })}</div>` : ''}</div></div>
      <div class="field"><span class="label">${t('lic.device')}</span>
        <div class="device"><code class="num" id="dev">${lic.device || ''}</code><button class="btn sm" data-copy>${icon('clipboard')}${t('act.copy')}</button></div>
        <span class="hint">${t('lic.deviceHint')}</span></div>
      <div class="field"><label for="lic-code">${t('lic.paste')}</label>
        <textarea id="lic-code" class="input code-box" spellcheck="false" autocomplete="off" placeholder="XXXXXX-XXXXXX-XXXXXX-…"></textarea>
        <span class="err small" id="lic-err" role="alert"></span></div>
      <button class="btn volt" data-activate>${icon('key')}${t('lic.activate')}</button>
      ${!good ? html`<div class="tip">${icon('info')}<div>${t('lic.readOnly')}</div></div>` : ''}</div>`,
    mount(box) {
      $('[data-copy]', box).addEventListener('click', async () => {
        try { await navigator.clipboard.writeText(lic.device); toast(t('act.copied')); } catch { getSelection().selectAllChildren($('#dev', box)); }
      });
      $('[data-activate]', box).addEventListener('click', async (e) => {
        const code = $('#lic-code', box).value.trim();
        if (!code) { $('#lic-code', box).focus(); return; }
        const r = await run(api.post('/api/licence/activate', { code }), t('lic.done'), e.currentTarget).catch(() => null);
        if (r) { S.boot.licence = r; renderBanners(); onDone && onDone(r); }
        else { shake($('#lic-code', box)); }
      });
    },
  };
}

// ---------------------------------------------------------------- shell
function navLink(r) {
  const count = S.counts[r];
  return html`<a href="#/${r}" data-route="${r}" class="${ROUTES[r].hot ? 'hot' : ''}">${icon(ROUTES[r].icon)}<span class="grow">${t('nav.' + r)}</span>
    ${ROUTES[r].hot ? html`<span class="kbd">F2</span>` : count ? html`<span class="count">${count}</span>` : ''}</a>`;
}

function renderShell() {
  const me = S.me;
  put(document.body, html`<div class="shell">
    <aside class="rail" aria-label="${t('nav.main')}"><div class="rail-in">
      <div class="brand"><div class="brand-mark">${icon('bolt')}</div><div class="grow"><div class="brand-name">${t('app.name')}</div>
        <div class="brand-shop ellipsis">${S.lookups?.settings?.shop_name || S.boot.shop_name}</div></div></div>
      <nav class="nav" id="nav">${GROUPS.map(([g, rs]) => {
        const vis = rs.filter(allowed);
        return vis.length ? html`${g ? html`<div class="nav-label">${t(g)}</div>` : ''}${vis.map(navLink)}` : '';
      })}</nav>
      <div class="rail-foot"><div class="who"><span class="avatar">${initials(me.full_name)}</span><div class="grow"><div class="ellipsis small">${me.full_name}</div>
        <div class="xs faint">${t('role.' + me.role)}</div></div><button class="icon-btn" data-logout aria-label="${t('act.logout')}">${icon('logout', 'flip')}</button></div></div>
    </div></aside>
    <div class="main">
      <header class="top">
        <button class="search-pill" data-cmdk>${icon('search')}<span class="grow">${t('cmdk.placeholder')}</span><span class="kbd hide-phone">Ctrl K</span></button>
        <span id="shift-chip"></span>
        <button class="icon-btn" data-theme-toggle aria-label="${t('pref.theme')}">${icon(document.documentElement.dataset.theme === 'night' ? 'sun' : 'moon')}</button>
        <button class="icon-btn" data-lang aria-label="${t('pref.lang')}"><span class="xs">${lang() === 'ar' ? 'EN' : 'ع'}</span></button>
      </header>
      <div id="banners"></div>
      <main class="page" id="page" tabindex="-1"></main>
    </div>
    <nav class="dock" aria-label="${t('nav.main')}">${['home', 'pos', 'sales', 'customers'].filter(allowed).map((r) =>
      html`<a href="#/${r}" data-route="${r}">${icon(ROUTES[r].icon)}<span>${t('nav.' + r)}</span></a>`)}
      <a href="#" data-more>${icon('dots-grid')}<span>${t('nav.more')}</span></a></nav>
  </div>`);
  $('[data-logout]').addEventListener('click', async () => { await api.post('/api/logout').catch(() => {}); S.me = null; location.hash = ''; showAuth(); });
  $('[data-cmdk]').addEventListener('click', palette);
  $('[data-theme-toggle]').addEventListener('click', () => {
    const night = document.documentElement.dataset.theme === 'night';
    prefs.set('theme', night ? 'day' : 'night');
    put($('[data-theme-toggle]'), icon(night ? 'moon' : 'sun'));
  });
  $('[data-lang]').addEventListener('click', () => { setLang(lang() === 'ar' ? 'en' : 'ar'); renderShell(); route(); });
  $('[data-more]').addEventListener('click', (e) => { e.preventDefault(); morePanel(); });
  renderBanners();
  refreshShift();
}

function morePanel() {
  open({ title: t('nav.more'), kind: 'sheet', body: html`<div class="more-grid">${Object.keys(ROUTES).filter(allowed).map((r) =>
    html`<a href="#/${r}" class="more-tile" data-close>${icon(ROUTES[r].icon)}<span>${t('nav.' + r)}</span></a>`)}</div>`,
  mount(box, close) { $$('a', box).forEach((a) => a.addEventListener('click', () => close())); } });
}

export async function refreshShift() {
  const el = $('#shift-chip');
  if (!el || !can('pos.sell')) return;
  try {
    const me = await api.get('/api/me');
    S.me = { ...S.me, ...me };
    put(el, me.shift_id
      ? html`<a class="chip ok hide-phone" href="#/cash"><span class="dot"></span>${t('shift.open')}</a>`
      : html`<a class="chip warn" href="#/cash"><span class="dot"></span>${t('shift.closed')}</a>`);
  } catch { /* the page shows its own error */ }
}

export function renderBanners() {
  const el = $('#banners');
  if (!el || !S.boot) return;
  const lic = S.boot.licence || {};
  const parts = [];
  if (!isOnline()) parts.push(html`<div class="banner offline" role="alert">${icon('alert')}${t('err.offlineBar')}</div>`);
  if (S.boot.practice) parts.push(html`<div class="banner practice">${icon('sparkle')}<b>${t('app.practice')}</b><span class="muted">${t('app.practiceBar')}</span></div>`);
  if (!['trial', 'active', 'grace', 'practice'].includes(lic.state)) {
    parts.push(html`<div class="banner licence bad" role="alert">${icon('lock')}<span class="grow">${t('lic.bar.' + (lic.state || 'none'))}</span>
      ${can('settings.edit') ? html`<a class="btn sm" href="#/settings?tab=licence">${t('lic.enter')}</a>` : ''}</div>`);
  } else if (lic.days_left !== null && lic.days_left !== undefined && lic.days_left <= 3) {
    parts.push(html`<div class="banner licence">${icon('clock')}<span class="grow">${t('lic.soon', { n: lic.days_left })}</span>
      ${can('settings.edit') ? html`<a class="btn sm" href="#/settings?tab=licence">${t('lic.enter')}</a>` : ''}</div>`);
  }
  put(el, html`${parts}`);
}

// ---------------------------------------------------------------- routing
let current = null;
async function route() {
  if (!S.me) return;
  const [path, query] = (location.hash.replace(/^#\/?/, '') || 'home').split('?');
  const name = ROUTES[path] ? path : 'home';
  S.route = name;
  S.params = Object.fromEntries(new URLSearchParams(query || ''));
  $$('[data-route]').forEach((a) => { if (a.dataset.route === name) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current'); });
  const page = $('#page');
  if (!allowed(name)) {
    put(page, html`<div class="card">${emptyDenied()}</div>`);
    return;
  }
  closeAll();
  const token = Symbol(name);
  current = token;
  let mod;
  try { mod = await ROUTES[name].load(); } catch (e) { fail(e); return; }
  if (current !== token) return;
  document.body.dataset.route = name;
  await transition(() => {
    page.className = 'page enter';
    put(page, html``);
    return mod.default(page, S.params);
  });
  if (current !== token) return;
  after(page, fmtCount);
  page.focus({ preventScroll: true });
  window.scrollTo({ top: 0 });
  document.title = t('nav.' + name) + ' · ' + t('app.name');
}
export function reload() { route(); }

function emptyDenied() {
  return html`<div class="empty"><div class="art">${icon('lock')}</div><h3>${t('state.denied')}</h3><p>${t('state.deniedHint')}</p></div>`;
}

// ---------------------------------------------------------------- command palette (Ctrl+K): pages, products, sales, customers
function palette() {
  if (anyOpen()) return;
  let items = [], sel = 0, timer;
  const pages = Object.keys(ROUTES).filter(allowed).map((r) => ({ group: t('cmdk.pages'), label: t('nav.' + r), icon: ROUTES[r].icon, go: () => go(r) }));
  const actions = [
    can('pos.sell') && { group: t('cmdk.actions'), label: t('cmdk.newSale'), icon: 'cart', go: () => go('pos') },
    can('stock.receive') && { group: t('cmdk.actions'), label: t('cmdk.receive'), icon: 'truck', go: () => go('receive') },
    can('products.edit') && { group: t('cmdk.actions'), label: t('cmdk.newProduct'), icon: 'plus', go: () => go('products', { new: 1 }) },
    { group: t('cmdk.actions'), label: t('cmdk.warranty'), icon: 'shield', go: () => go('sales', { tab: 'warranty' }) },
  ].filter(Boolean);
  const scrim = document.createElement('div');
  scrim.className = 'scrim';
  put(scrim, html`<div class="cmdk" role="dialog" aria-modal="true" aria-label="${t('cmdk.placeholder')}">
    <input class="input" id="cmdk-q" placeholder="${t('cmdk.placeholder')}" autocomplete="off" aria-controls="cmdk-list">
    <div class="cmdk-list" id="cmdk-list" role="listbox"></div></div>`);
  document.body.appendChild(scrim);
  const input = $('#cmdk-q', scrim), list = $('#cmdk-list', scrim);
  const close = () => { scrim.remove(); document.removeEventListener('keydown', keys, true); };
  const draw = () => {
    let last = '';
    put(list, html`${items.length ? items.map((it, i) => {
      const head = it.group !== last ? html`<div class="cmdk-group">${it.group}</div>` : '';
      last = it.group;
      return html`${head}<button class="cmdk-item" role="option" data-i="${i}" aria-selected="${i === sel}">${icon(it.icon)}<span class="grow ellipsis">${it.label}</span>
        ${it.meta ? html`<span class="small muted num">${it.meta}</span>` : ''}</button>`;
    }) : html`<div class="empty small">${t('cmdk.none')}</div>`}`);
    list.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: 'nearest' });
  };
  const choose = (i) => { const it = items[i]; if (it) { close(); it.go(); } };
  const search = async () => {
    const q = input.value.trim();
    const base = [...actions, ...pages].filter((x) => !q || x.label.includes(q));
    items = base; sel = 0; draw();
    if (q.length < 2) return;
    const found = [];
    const [p, c] = await Promise.all([
      api.get('/api/products', { q, limit: 6 }).catch(() => ({ items: [] })),
      can('customers.edit', 'installments.collect') ? api.get('/api/customers', { q }).catch(() => []) : [],
    ]);
    p.items.forEach((x) => found.push({ group: t('cmdk.products'), label: x.name, meta: money(x.prices.retail), icon: 'box', go: () => go('products', { id: x.id }) }));
    c.slice(0, 5).forEach((x) => found.push({ group: t('cmdk.customers'), label: x.name, meta: x.phone, icon: 'user', go: () => go('customers', { id: x.id }) }));
    if (/^[A-Za-z]-?\d+$/.test(q) || /^\d{3,}$/.test(q)) found.unshift({ group: t('cmdk.actions'), label: t('cmdk.findSale', { q }), icon: 'receipt', go: () => go('sales', { q }) });
    if (input.value.trim() === q) { items = [...found, ...base]; draw(); }
  };
  function keys(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(items.length - 1, sel + 1); draw(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); draw(); }
    else if (e.key === 'Enter') { e.preventDefault(); choose(sel); }
  }
  document.addEventListener('keydown', keys, true);
  input.addEventListener('input', () => { clearTimeout(timer); timer = setTimeout(search, 120); });
  list.addEventListener('click', (e) => { const b = e.target.closest('[data-i]'); if (b) choose(+b.dataset.i); });
  scrim.addEventListener('mousedown', (e) => { if (e.target === scrim) close(); });
  search();
  input.focus();
}

// ---------------------------------------------------------------- global keys
document.addEventListener('keydown', (e) => {
  if (!S.me) return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); palette(); }
  else if (e.key === 'F2' && can('pos.sell') && !anyOpen()) { e.preventDefault(); if (S.route !== 'pos') go('pos'); else $('#pos-q')?.focus(); }
});

export const _esc = esc;
boot();
