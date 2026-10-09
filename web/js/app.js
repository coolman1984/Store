// The shell: start-up, sign-in, first-run setup, licence screen, navigation, command palette, keyboard shortcuts.
import { api, on, isOnline } from './api.js';
import { applyLang, has, lang, setLang, t } from './i18n.js';
import { apply as applyPrefs, prefs } from './prefs.js';
import { $, $$, html, icon, put, open, closeAll, anyOpen, toast, fail, run, initials, esc, money, showError, time, seg, bindSeg } from './ui.js';
import { transition, after, shake } from './motion.js';
import { mark } from './brand.js';
import { attachHelp, guideRole, maybeConsent, mountGuide, onRoute, signal } from './guide.js';
import { showRecoveryCode } from './recovery.js';

export const S = { boot: null, me: null, lookups: null, route: 'home', params: {}, counts: {} };

// route -> view module loader + nav metadata (lazy: a page's code loads the first time it is opened).
// `perm`: any one of them opens the page - the same table as the server's auth.PAGES (a test keeps them equal).
export const ROUTES = {
  pos: { icon: 'cart', perm: ['pos.sell'], load: () => import('./views/pos.js'), hot: true },
  home: { icon: 'home', load: () => import('./views/home.js') },
  sales: { icon: 'receipt', perm: ['pos.sell', 'sales.view_all', 'sales.return'], load: () => import('./views/sales.js') },
  customers: { icon: 'users', perm: ['customers.view'], load: () => import('./views/customers.js') },
  products: { icon: 'tag', perm: ['products.view'], load: () => import('./views/products.js') },
  stock: { icon: 'warehouse', perm: ['stock.view'], load: () => import('./views/stock.js') },
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
/** put() on document.body would drop the coach. Detach it first, then put it back. */
function replaceBody(content) {
  const keep = [...document.querySelectorAll('[data-afg="fab"], [data-afg="panel"], [data-afg="coach"], [data-afc="card"], [data-aft="dialog"]')];
  keep.forEach((n) => n.remove());
  put(document.body, content);
  keep.forEach((n) => document.body.appendChild(n));
  attachHelp();
}
export const fmtCount = (v, f) => (f === 'money' ? money(v, { whole: true }) : new Intl.NumberFormat('en-US').format(v));
/** call after a view puts content that arrived later (numbers count up, bars get their width) */
export const settle = (el) => { after(el, fmtCount); scrollables(el); };
/** a table that scrolls sideways must be reachable by keyboard (WCAG 2.1.1) */
function scrollables(root) {
  root.querySelectorAll('.table-wrap').forEach((w) => { if (!w.hasAttribute('tabindex')) { w.tabIndex = 0; w.setAttribute('role', 'region'); w.setAttribute('aria-label', t('a11y.table')); } });
}

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
    replaceBody(html`<main class="empty boot-error"><span class="brand-mark">${mark('light')}</span><h3>${t('err.offline')}</h3>
      <p>${t('err.retrying')}</p><span class="splash-bar"></span></main>`);
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
  await mountGuide({
    live: true, role: guideRole(S.me.role, S.me.perms), person: String(S.me.id), can: (p) => can(p), go,
  });
  window.removeEventListener('hashchange', route);
  window.addEventListener('hashchange', route);
  route();
  maybeConsent().catch(() => {});
}

// ---------------------------------------------------------------- sign-in, setup, licence
function lockup(tone, shop) {
  return html`<div class="brand"><span class="brand-mark">${mark(tone)}</span><div class="grow"><div class="brand-name">${t('app.name')}<small>${t('app.nameAlt')}</small></div>
    <div class="brand-shop ellipsis">${shop}</div></div></div>`;
}

function authFrame(content) {
  replaceBody(html`<main class="auth">
    <section class="auth-art">
      ${lockup('dark', t('app.tag'))}
      <div class="auth-pitch"><p class="auth-line">${t('auth.tagline')}</p>
        <ul class="auth-points">${[['barcode', 'sell'], ['safe', 'drawer'], ['shield', 'offline']].map(([ic, k]) =>
          html`<li><span class="ic">${icon(ic)}</span><span><b>${t('auth.pt.' + k)}</b><span>${t('auth.pt.' + k + 'Hint')}</span></span></li>`)}</ul></div>
      <span class="auth-watermark" aria-hidden="true">${mark('dark')}</span>
    </section>
    <section class="auth-form">${content}
      <div class="auth-tools"><span data-guide-slot></span><button class="chip" data-lang>${icon('globe')}${lang() === 'ar' ? 'English' : 'العربية'}</button>
      ${S.boot?.practice ? html`<span class="chip accent">${icon('sparkle')}${t('app.practice')}</span>` : ''}</div>
    </section></main>`);
  $('[data-lang]').addEventListener('click', () => { setLang(lang() === 'ar' ? 'en' : 'ar'); boot(); });
}

function showAuth() {
  closeAll();
  document.body.dataset.route = 'signin';
  authFrame(html`<form class="card auth-card form" id="auth-form" autocomplete="on">
    <div><h1>${t('auth.welcome')}</h1><p class="muted">${t('auth.sub')}</p></div>
    ${S.boot?.practice ? html`<div class="tip">${icon('sparkle')}<div>${t('auth.practiceHint')}</div></div>` : ''}
    <div class="field"><label for="username">${t('f.username')}</label><input id="username" class="input big" data-guide="signin.user" autocomplete="username" required autofocus></div>
    <div class="field"><label for="password">${t('f.password')}</label><input id="password" type="password" class="input big" data-guide="signin.password" autocomplete="current-password" required></div>
    <p class="err small" id="auth-err" role="alert"></p>
    <button class="btn accent lg block" type="submit" data-guide="signin.submit">${t('auth.signIn')}${icon('chev-l', 'flip')}</button>
    ${S.boot?.practice ? '' : html`<button class="btn ghost sm" type="button" data-forgot>${icon('key')}${t('auth.forgot')}</button>`}
  </form>`);
  mountGuide({ live: false, role: 'guest', person: 'me', can: () => false, go });
  $('[data-forgot]')?.addEventListener('click', showRecover);
  $('#auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter;
    btn.setAttribute('aria-busy', 'true');
    try {
      const r = await api.post('/api/login', { username: $('#username').value, password: $('#password').value });
      S.me = r.user;
      S.boot = await api.get('/api/boot');
      await startShell();
      signal('session.started');
    } catch (err) {
      showError($('#auth-err'), err);
      shake($('#auth-form'));
      $('#password').select();
    } finally { btn.removeAttribute('aria-busy'); }
  });
}

/** Forgotten owner password: the paper code from setup sets a new one, then a new code is shown. */
function showRecover() {
  document.body.dataset.route = 'signin';  // the same page for the guide and its problem entries
  authFrame(html`<form class="card auth-card form" id="recover-form" autocomplete="off">
    <div><h1>${t('recover.title')}</h1><p class="muted">${t('recover.sub')}</p></div>
    <div class="field"><label for="rc-code">${t('recover.code')}</label><input id="rc-code" class="input big ltr" dir="ltr" autocomplete="off"
      autocapitalize="characters" spellcheck="false" placeholder="XXXX-XXXX-XXXX-XXXX" required autofocus></div>
    <div class="field"><label for="rc-new">${t('recover.newPassword')}</label><input id="rc-new" type="password" class="input big" autocomplete="new-password" required>
      <span class="hint">${t('setup.pwHint')}</span></div>
    <p class="err small" id="rc-err" role="alert"></p>
    <button class="btn accent lg block" type="submit">${t('recover.go')}</button>
    <button class="btn ghost sm" type="button" data-back>${t('recover.back')}</button>
  </form>`);
  mountGuide({ live: false, role: 'guest', person: 'me', can: () => false, go });
  $('[data-back]').addEventListener('click', showAuth);
  $('#recover-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter;
    btn.setAttribute('aria-busy', 'true');
    try {
      const r = await api.post('/api/recover', { code: $('#rc-code').value, password: $('#rc-new').value });
      S.me = r.user;
      S.boot = await api.get('/api/boot');
      await showRecoveryCode(r.recovery_code, S.boot.shop_name);
      await startShell();
      signal('session.started');
    } catch (err) {
      showError($('#rc-err'), err);
      shake($('#recover-form'));
    } finally { btn.removeAttribute('aria-busy'); }
  });
}

function showSetup() {
  document.body.dataset.route = 'setup';
  authFrame(html`<form class="card auth-card form" id="setup-form">
    <div><span class="badge accent">${t('setup.step')}</span><h1>${t('setup.title')}</h1><p class="muted">${t('setup.sub')}</p></div>
    <div class="field"><label for="shop">${t('setup.shop')}</label><input id="shop" class="input" data-guide="setup.shop" required autofocus placeholder="${t('setup.shopHint')}"></div>
    <div class="cols"><div class="field"><label for="phone">${t('f.phone')}</label><input id="phone" class="input" inputmode="tel"></div>
    <div class="field"><label for="addr">${t('f.address')}</label><input id="addr" class="input"></div></div>
    <hr class="sep">
    <div class="cols"><div class="field"><label for="fn">${t('setup.ownerName')}</label><input id="fn" class="input" data-guide="setup.owner" required></div>
    <div class="field"><label for="un">${t('f.username')}</label><input id="un" class="input" data-guide="setup.user" required autocomplete="username"></div></div>
    <div class="field"><label for="pw">${t('f.password')}</label><input id="pw" type="password" class="input" data-guide="setup.password" required autocomplete="new-password">
      <span class="hint">${t('setup.pwHint')}</span></div>
    <p class="err small" id="setup-err" role="alert"></p>
    <button class="btn accent lg block" type="submit" data-guide="setup.go">${t('setup.go')}</button></form>`);
  mountGuide({ live: false, role: 'owner', person: 'me', can: () => true, go });
  $('#setup-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const r = await api.post('/api/setup', { shop_name: $('#shop').value, shop_phone: $('#phone').value, shop_address: $('#addr').value,
        full_name: $('#fn').value, username: $('#un').value, password: $('#pw').value });
      await showRecoveryCode(r.recovery_code, $('#shop').value);
      S.boot = await api.get('/api/boot');
      S.me = S.boot.user;
      await startShell();
      signal('setup.done');
      go('settings', { tab: 'licence' });
    } catch (err) { showError($('#setup-err'), err); shake($('#setup-form')); }
  });
}

/** The licence card: ask the company from this screen (the code comes back and switches the program on), the device code for the manual
 *  way, a box to paste a code, and what keeps working without a code. */
export function licenceCard(lic, onDone) {
  const st = lic.state;
  const good = ['trial', 'active', 'grace', 'practice'].includes(st);
  return {
    body: html`<div class="lic ${good ? 'good' : ''}">
      <div class="lic-state">${icon(good ? 'shield' : 'key')}<div><b>${t('lic.state.' + st)}</b>
        ${lic.edition && st !== 'practice' ? html`<div class="small" data-lic-kind>${t('lic.kind.' + lic.edition)}</div>` : ''}
        ${lic.last_day ? html`<div class="small muted">${t('lic.until', { day: lic.last_day, n: lic.days_left })}</div>`
          : lic.edition === 'perpetual' && lic.full ? html`<div class="small muted">${t('lic.forever')}</div>` : ''}</div></div>
      ${st === 'practice' ? '' : html`<div class="lic-auto" id="lic-auto" aria-live="polite"></div>`}
      <div class="field"><span class="label">${t('lic.device')}</span>
        <div class="device"><code class="num" id="dev">${lic.device || ''}</code><button class="btn sm" data-copy>${icon('clipboard')}${t('act.copy')}</button></div>
        <span class="hint">${t('lic.deviceHint')}</span>
        ${lic.vendor_telegram ? html`<a class="btn sm" target="_blank" rel="noopener" href="${lic.vendor_telegram}">${icon('message')}${t('lic.telegram')}</a>` : ''}</div>
      <div class="field"><label for="lic-code">${t('lic.paste')}</label>
        <textarea id="lic-code" class="input code-box" spellcheck="false" autocomplete="off" placeholder="XXXXXX-XXXXXX-XXXXXX-…"></textarea>
        <span class="err small" id="lic-err" role="alert"></span></div>
      <button class="btn accent" data-activate>${icon('key')}${t('lic.activate')}</button>
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
      if ($('#lic-auto', box)) requestArea(box, lic, onDone);
    },
  };
}

/** Asking the company: one status line that is never silent (sending, waiting, no connection and when it tries again, refused and why,
 *  activated), a button for each way out, and what exactly would be sent before anything is sent. */
async function requestArea(box, lic, onDone) {
  const area = $('#lic-auto', box);
  let timer = null;
  const stop = () => { if (timer) { clearInterval(timer); timer = null; } };
  const reasonText = (r) => (has('lic.req.refused.' + r) ? t('lic.req.refused.' + r) : t('lic.req.refused.other', { r }));
  const offline = (q) => /^offline|^http_|^busy|^token|^relay_off/.test(q.error || '');
  const draw = (q) => {
    const wait = q.status === 'sending' || q.status === 'waiting' || (q.status === 'failed' && offline(q));
    let line = '';
    if (!q.available) line = html`<div class="tip">${icon('info')}<div>${t('lic.req.off')}</div></div>`;
    else if (q.status === 'sending') line = html`<div class="lic-line busy">${icon('clock')}<span>${t('lic.req.sending')}</span></div>`;
    else if (q.status === 'waiting' && !q.error) line = html`<div class="lic-line busy">${icon('clock')}<span>${t('lic.req.waiting')}</span></div>`;
    else if (wait) line = html`<div class="lic-line warn">${icon('alert')}<span>${t('lic.req.offline', { when: q.next_try ? time(q.next_try) : '' })}</span></div>`;
    else if (q.status === 'failed') line = html`<div class="lic-line warn">${icon('alert')}<span>${t('lic.req.codeBad', { r: q.reason || q.error || '' })}</span></div>`;
    else if (q.status === 'refused') line = html`<div class="lic-line bad">${icon('x')}<span>${reasonText(q.reason)}</span></div>`;
    else if (q.status === 'closed') line = html`<div class="lic-line warn">${icon('alert')}<span>${t('lic.req.closed')}</span></div>`;
    else if (q.status === 'activated') line = html`<div class="lic-line good">${icon('check')}<span>${t('lic.req.activated')}</span></div>`;
    put(area, html`${line}<div class="row wrap">
      ${q.available && q.status === 'none' && !lic.full ? html`<button class="btn accent" data-req="trial">${icon('message')}${t('lic.req.trial')}</button>` : ''}
      ${q.available && q.status === 'none' && !(lic.full && lic.edition !== 'trial') ? html`<button class="btn ${lic.full ? '' : 'ghost'}" data-req="paid">${icon('key')}${t('lic.req.paid')}</button>` : ''}
      ${wait ? html`<button class="btn" data-retry>${icon('refresh')}${t('lic.req.retry')}</button>` : ''}
      ${['refused', 'closed', 'activated', 'failed'].includes(q.status) && !wait ? html`<button class="btn" data-again>${icon('plus')}${t('lic.req.again')}</button>` : ''}
      ${q.available ? html`<button class="btn ghost sm" data-what>${icon('info')}${t('lic.req.what')}</button>` : ''}</div>`);
    $$('[data-req]', area).forEach((b) => b.addEventListener('click', () => (b.dataset.req === 'trial' ? send('trial') : paidDialog())));
    $('[data-retry]', area)?.addEventListener('click', async () => { try { draw(await api.post('/api/licence/request/retry')); } catch (e) { fail(e); } });
    $('[data-again]', area)?.addEventListener('click', async () => { try { draw(await api.post('/api/licence/request/clear')); } catch (e) { fail(e); } });
    $('[data-what]', area)?.addEventListener('click', () => whatDialog());
    if (['sending', 'waiting', 'failed'].includes(q.status) && !timer) timer = setInterval(look, 5000);
    if (!['sending', 'waiting', 'failed'].includes(q.status)) stop();
  };
  const send = async (kind, ref = '') => {
    try { draw(await api.post('/api/licence/request', { kind, ref })); } catch (e) { fail(e); }
  };
  const look = async () => {
    if (!document.body.contains(area)) { stop(); return; }
    try {
      const q = await api.get('/api/licence/request');
      if (q.status === 'activated') {
        stop();
        const fresh = await api.get('/api/licence');
        S.boot.licence = fresh;
        renderBanners();
        toast(t('lic.req.activated'));
        onDone && onDone(fresh);
        return;
      }
      draw(q);
    } catch { /* the next look tries again */ }
  };
  const whatDialog = async (kind = 'trial') => {
    let p;
    try { p = await api.get('/api/licence/preview', { kind }); } catch (e) { fail(e); return; }
    open({
      title: t('lic.req.whatTitle'),
      body: html`<p class="muted small">${t('lic.req.whatHint')}</p><div class="card flat">${['kind', 'product', 'device', 'machine', 'shop', 'version', 'ref'].filter((k) => p.sends[k] !== undefined && p.sends[k] !== '').map((k) =>
        html`<div class="stat-line small"><span>${t('lic.req.f.' + k)}</span><b class="num ltr">${k === 'machine' ? p.sends[k].slice(0, 12) + '…' : k === 'kind' ? t('lic.req.kind.' + p.sends[k]) : p.sends[k]}</b></div>`)}</div>`,
      foot: html`<button class="btn primary" data-close>${t('act.ok')}</button>`,
    });
  };
  const paidDialog = () => open({
    title: t('lic.req.paidTitle'),
    body: html`<p class="muted small">${t('lic.req.paidHint')}</p>
      <div class="field"><span class="label">${t('lic.req.kind')}</span>${seg('pk', [['monthly', t('lic.req.kind.monthly')], ['permanent', t('lic.req.kind.permanent')]], 'monthly')}</div>
      <div class="field"><label for="pref">${t('lic.req.ref')}</label><input id="pref" class="input" maxlength="60" autocomplete="off"></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${icon('message')}${t('lic.req.send')}</button>`,
    mount(dlg, close) {
      let kind = 'monthly';
      bindSeg(dlg, 'pk', (v) => { kind = v; });
      $('[data-ok]', dlg).addEventListener('click', async () => { close(); await send(kind, $('#pref', dlg).value.trim()); });
    },
  });
  try { draw(await api.get('/api/licence/request')); } catch { put(area, html``); }
}

// ---------------------------------------------------------------- shell
function navLink(r) {
  const count = S.counts[r];
  return html`<a href="#/${r}" data-route="${r}" class="${ROUTES[r].hot ? 'hot' : ''}">${icon(ROUTES[r].icon)}<span class="grow">${t('nav.' + r)}</span>
    ${ROUTES[r].hot ? html`<span class="kbd">F2</span>` : count ? html`<span class="count">${count}</span>` : ''}</a>`;
}

function renderShell() {
  const me = S.me;
  replaceBody(html`<div class="shell">
    <aside class="rail" aria-label="${t('nav.main')}"><div class="rail-in">
      ${lockup('dark', S.lookups?.settings?.shop_name || S.boot.shop_name)}
      <nav class="nav" id="nav" aria-label="${t('nav.main')}">${GROUPS.map(([g, rs]) => {
        const vis = rs.filter(allowed);
        return vis.length ? html`${g ? html`<div class="nav-label">${t(g)}</div>` : ''}${vis.map(navLink)}` : '';
      })}</nav>
      <div class="rail-foot"><div class="who"><span class="avatar">${initials(me.full_name)}</span><div class="grow"><div class="ellipsis small">${me.full_name}</div>
        <div class="xs faint">${t('role.' + me.role)}</div></div><button class="icon-btn" data-logout aria-label="${t('act.logout')}">${icon('logout', 'flip')}</button></div></div>
    </div></aside>
    <div class="main">
      <header class="top">
        <span class="mobile-mark">${mark('light', t('app.name'))}</span>
        <button class="search-pill" data-cmdk>${icon('search')}<span class="grow">${t('cmdk.placeholder')}</span><span class="kbd hide-phone">Ctrl K</span></button>
        <div class="top-end"><span data-guide-slot></span><span id="shift-chip"></span>
        <button class="icon-btn" data-theme-toggle aria-label="${t('pref.theme')}">${icon(document.documentElement.dataset.theme === 'night' ? 'sun' : 'moon')}</button>
        <button class="icon-btn" data-lang aria-label="${t('pref.lang')}"><span class="small">${lang() === 'ar' ? 'EN' : 'ع'}</span></button></div>
      </header>
      <section id="banners" aria-label="${t('nav.notices')}"></section>
      <main class="page" id="page" tabindex="-1"></main>
    </div>
    <nav class="dock" aria-label="${t('nav.quick')}">${['home', 'pos', 'sales', 'customers'].filter(allowed).map((r) =>
      html`<a href="#/${r}" data-route="${r}">${icon(ROUTES[r].icon)}<span>${t('nav.' + r)}</span></a>`)}
      <a href="#" data-more>${icon('dots-grid')}<span>${t('nav.more')}</span></a></nav>
  </div>`);
  $('[data-logout]').addEventListener('click', async () => { await api.post('/api/logout').catch(() => {}); S.me = null; try { sessionStorage.removeItem('store.cart'); } catch { /* ignore */ } location.hash = ''; showAuth(); });
  $('[data-cmdk]').addEventListener('click', palette);
  $('[data-theme-toggle]').addEventListener('click', () => {
    const night = document.documentElement.dataset.theme === 'night';
    prefs.set('theme', night ? 'day' : 'night');
    put($('[data-theme-toggle]'), icon(night ? 'moon' : 'sun'));
  });
  $('[data-lang]').addEventListener('click', () => {
    setLang(lang() === 'ar' ? 'en' : 'ar');
    if (window.__afguide) window.__afguide.setLang(lang());
    renderShell();
    route();
  });
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
  document.body.dataset.route = name;
  const token = Symbol(name);
  current = token;  // set before the permission check, so a page still loading cannot paint over the "not allowed" card
  if (!allowed(name)) {
    put(page, html`<div class="card">${emptyDenied()}</div>`);
    onRoute(name);
    return;
  }
  closeAll();
  let mod;
  try { mod = await ROUTES[name].load(); } catch (e) { fail(e); return; }
  if (current !== token) return;
  document.body.dataset.route = name;
  onRoute(name);
  await transition(() => {
    page.className = 'page enter';
    put(page, html``);
    return mod.default(page, S.params);
  });
  if (current !== token) return;
  settle(page);
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
      can('products.view', 'stock.view') ? api.get('/api/products', { q, limit: 6 }).catch(() => ({ items: [] })) : { items: [] },
      can('customers.view') ? api.get('/api/customers', { q }).catch(() => []) : [],
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
