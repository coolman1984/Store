// Settings: the shop, the licence, people and permissions, places, backups and export, this device's preferences.
import { api } from '../api.js';
import { S, can, licenceCard, renderBanners } from '../app.js';
import { t, lang, setLang } from '../i18n.js';
import { shake } from '../motion.js';
import { printHTML } from '../print.js';
import { prefs } from '../prefs.js';
import { CUR, raw, $, $$, html, put, icon, date, open, empty, skeleton, errorText, toast, run, confirm, seg, bindSeg, initials, download, parseMoney, showError, today } from '../ui.js';
import { signal } from '../guide.js';
import { makeNewCode } from '../recovery.js';

const TAB_GUIDE = { shop: 'settings.shop.tab', users: 'settings.users.tab', backup: 'settings.backup.tab' };
const TABS = [['shop', 'store', 'settings.edit'], ['licence', 'key', 'settings.edit'], ['users', 'users', 'users.manage'], ['places', 'warehouse', 'settings.edit'],
  ['backup', 'download', 'settings.edit'], ['support', 'help', 'settings.edit'], ['privacy', 'shield', null], ['device', 'sun', null]];

export default async function view(page, params) {
  const tabs = TABS.filter(([, , p]) => !p || can(p));
  const tab = tabs.find(([k]) => k === params.tab)?.[0] || tabs[0][0];
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.settings')}</h1><p>${t('settings.sub')}</p></div></div>
    <nav class="tabs" data-lab-scroll aria-label="${t('nav.sections')}">${tabs.map(([k, ic]) => html`<a href="#/settings?tab=${k}" data-guide="${TAB_GUIDE[k] || ''}" ${tab === k ? CUR : ''}>${icon(ic)}${t('settings.tab.' + k)}</a>`)}</nav><div id="set-body">${skeleton(5)}</div>`);
  const body = $('#set-body', page);
  const again = () => view(page, params);
  ({ shop, licence, users, places, backup, support, privacy, device })[tab](body, again);
}

// Cash is always on; these stay hidden everywhere until the owner ticks them.
const OPTIONAL_PAY = ['card', 'wallet', 'instapay', 'finance', 'account', 'installment'];

async function shop(body) {
  const d = await api.get('/api/settings').catch((e) => { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); });
  if (!d) return;
  const s = d.settings;
  const on = (...ms) => ms.some((m) => (s.pay_methods || []).includes(m));
  const f = (k, label, hint, type = 'text') => html`<div class="field"><label for="s-${k}">${label}</label><input id="s-${k}" class="input ${type === 'money' ? 'money-in' : ''}" data-k="${k}" data-type="${type}" data-guide="${k === 'shop_name' ? 'settings.shop.name' : ''}"
    value="${type === 'money' ? s[k] / 100 : s[k]}" ${type !== 'text' ? raw('inputmode="decimal"') : ''}>${hint ? html`<span class="hint">${hint}</span>` : ''}</div>`;
  put(body, html`<div class="stack"><div class="card form"><div class="card-head"><h2>${t('settings.shopInfo')}</h2></div>
      <div class="cols">${f('shop_name', t('setup.shop'))}${f('shop_phone', t('f.phone'))}${f('shop_address', t('f.address'))}${f('tax_number', t('settings.taxNo'), t('settings.taxNoHint'))}</div></div>
    <div class="card form"><div class="card-head"><h2>${t('settings.receipt')}</h2></div>
      <div class="field"><span class="label">${t('settings.paper')}</span>${seg('rw', [['80', '80 mm'], ['58', '58 mm']], s.receipt_width)}</div>
      <div class="cols">${f('receipt_footer', t('settings.footer'))}${on('wallet', 'instapay') ? f('wallet_number', t('settings.wallet'), t('settings.walletHint')) : ''}</div>
      <div class="cols">${f('return_days', t('settings.returnDays'), t('settings.returnDaysHint'), 'num')}${f('defect_days', t('settings.defectDays'), t('settings.defectDaysHint'), 'num')}</div></div>
    <div class="card form"><div class="card-head"><h2>${t('settings.pay')}</h2></div>
      <p class="small muted">${t('settings.payHint')}</p>
      <div class="row wrap"><label class="check"><input type="checkbox" checked disabled>${t('pay.cash')}</label>
      ${OPTIONAL_PAY.map((m) => html`<label class="check"><input type="checkbox" data-pay="${m}" ${on(m) ? 'checked' : ''}>${t('pay.' + m)}</label>`)}</div></div>
    ${on('installment', 'finance') ? html`<div class="card form"><div class="card-head"><h2>${t('settings.instalments')}</h2></div>
      <div class="cols">${on('installment') ? html`${f('min_down_payment_pct', t('settings.minDown'), '', 'num')}${f('instalment_markup_pct', t('settings.markup'), t('settings.markupHint'), 'num')}
      ${f('max_instalment_months', t('settings.maxMonths'), '', 'num')}` : ''}</div>
      ${on('finance') ? html`<div class="field"><label for="s-prov">${t('settings.providers')}</label><input id="s-prov" class="input" value="${(s.finance_providers || []).join('، ')}"><span class="hint">${t('settings.providersHint')}</span></div>` : ''}</div>` : ''}
    <div class="card form"><div class="card-head"><h2>${t('settings.watch')}</h2></div>
      <div class="cols">${f('large_expense', t('settings.largeExpense'), '', 'money')}${f('opening_hour', t('settings.open'), '', 'num')}${f('closing_hour', t('settings.close'), '', 'num')}</div></div>
    <div class="row"><button class="btn accent lg" data-save data-guide="settings.save">${icon('check')}${t('act.save')}</button></div></div>`);
  $('[data-save]', body).addEventListener('click', async (e) => {
    const out = { receipt_width: $('[data-seg="rw"] [aria-pressed="true"]', body).dataset.v,
      pay_methods: ['cash', ...$$('[data-pay]', body).filter((x) => x.checked).map((x) => x.dataset.pay)] };
    if ($('#s-prov', body)) out.finance_providers = $('#s-prov', body).value.split(/[,،]\s*/).map((x) => x.trim()).filter(Boolean);
    for (const inp of $$('[data-k]', body)) {
      const ty = inp.dataset.type;
      if (ty === 'money') { const v = parseMoney(inp.value); if (v === null) { shake(inp); return; } out[inp.dataset.k] = v; }
      else if (ty === 'num') { const v = Number(inp.value); if (!Number.isFinite(v) || v < 0) { shake(inp); return; } out[inp.dataset.k] = v; }
      else out[inp.dataset.k] = inp.value;
    }
    const r = await run(api.post('/api/settings/save', { settings: out }), t('saved'), e.currentTarget);
    if (r) {
      signal('settings.saved'); S.lookups = await api.get('/api/lookups').catch(() => S.lookups);
      if (out.pay_methods.join() !== (s.pay_methods || []).join()) shop(body);  // show or hide the instalment and wallet fields
    }
  });
}

async function licence(body, again) {
  const lic = await api.get('/api/licence').catch(() => S.boot.licence);
  const card = licenceCard(lic, () => again());
  put(body, html`<div class="two"><div class="card">${card.body}</div><div class="card"><div class="card-head"><h2>${t('lic.howTitle')}</h2></div>
    <ol class="steps">${[1, 2, 3, 4].map((n) => html`<li>${t('lic.how' + n)}</li>`)}</ol><p class="small muted">${t('lic.safe')}</p></div></div>`);
  card.mount(body);
  renderBanners();
}

// ---------------------------------------------------------------- people, profiles and permissions
// A profile is a named set of ticks (factory standard: docs/ACCESS_AND_ADMINISTRATION_STANDARD.md). Choosing a profile ticks
// the boxes; changing one tick makes the person "Custom". The owner profile always has everything. The server checks it all.
const pname = (p) => (p ? p.name || t('role.' + p.id) : t('users.customProfile'));
const same = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));

async function users(body, again) {
  let d;
  try { d = await api.get('/api/users'); } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  const profOf = (u) => d.profiles.find((p) => p.id === u.role);
  put(body, html`<div class="stack">${S.me?.recovery ? html`<div class="card"><div class="card-head"><h2>${icon('key')}${t('recovery.card')}</h2>
      <button class="btn" data-recovery>${t('recovery.new')}</button></div><p class="small muted">${t('recovery.cardHint')}</p></div>` : ''}
    <div class="row between wrap"><p class="muted">${t('users.sub')}</p>
      <div class="row wrap"><button class="btn" data-matrix>${icon('layers')}${t('users.matrix')}</button><button class="btn primary" data-new data-guide="users.add">${icon('plus')}${t('users.add')}</button></div></div>
    <div class="grid">${d.users.map((u) => html`<button class="card flat user-card" data-id="${u.id}"><div class="row"><span class="avatar">${initials(u.full_name)}</span>
      <span class="grow"><b>${u.full_name}</b><bdi class="small muted"> @${u.username}</bdi><div class="small">${pname(profOf(u))}${u.max_discount_pct ? ' · ' + t('users.discountN', { n: u.max_discount_pct }) : ''}</div></span>
      ${u.active ? '' : html`<span class="badge bad">${t('users.off')}</span>`}</div></button>`)}</div>
    <div class="card"><div class="card-head"><h2>${t('profiles.title')}</h2><button class="btn" data-newprof>${icon('plus')}${t('profiles.add')}</button></div>
      <p class="small muted">${t('profiles.hint')}</p>
      <div class="grid">${d.profiles.map((p) => html`<button class="card flat user-card" data-prof="${p.id}"><div class="row">${icon(p.locked ? 'lock' : 'shield')}
        <span class="grow"><b>${pname(p)}</b><div class="small muted">${p.builtin && !p.name ? t('role.' + p.id + '.hint') : t('profiles.nPerms', { n: p.perms.length })}</div>
        <div class="xs faint">${t('profiles.nPeople', { n: p.users })}</div></span></div></button>`)}</div></div></div>`);
  $('[data-recovery]', body)?.addEventListener('click', () => makeNewCode(S.lookups?.settings?.shop_name || ''));
  $('[data-new]', body).addEventListener('click', () => editUser(null, d, again));
  $('[data-newprof]', body).addEventListener('click', () => editProfile(null, d, again));
  $('[data-matrix]', body).addEventListener('click', () => matrix(d));
  $$('[data-id]', body).forEach((b) => b.addEventListener('click', () => editUser(d.users.find((u) => u.id === b.dataset.id), d, again)));
  $$('[data-prof]', body).forEach((b) => b.addEventListener('click', () => editProfile(d.profiles.find((p) => p.id === b.dataset.prof), d, again)));
}

/** The tick boxes, grouped like the server's list. The administrator group is shown apart and "Select all" never ticks it.
 *  Ticking an action ticks the page it needs; unticking a page unticks what needs it. */
function ticks(root, d, state, { locked = false, onChange = () => {} } = {}) {
  const groups = d.groups.map((g) => [g, d.permissions.filter((p) => p.group === g)]);
  const needs = (id) => d.permissions.find((p) => p.id === id)?.requires || [];
  const draw = () => {
    put(root, html`${locked ? html`<div class="tip">${icon('lock')}<div>${t('profiles.lockedHint')}</div></div>` : html`<div class="row wrap">
        <button type="button" class="btn sm" data-all>${t('perms.all')}</button><button type="button" class="btn sm ghost" data-none>${t('perms.none')}</button>
        <span class="small muted grow">${t('perms.count', { n: state.size, of: d.permissions.length })}</span></div>`}
      ${groups.map(([g, ps]) => html`<fieldset class="perm-group ${ps[0]?.admin ? 'admin' : ''}"><legend><label class="check"><input type="checkbox" data-g="${g}"
        ${ps.every((p) => state.has(p.id)) ? 'checked' : ''} ${locked ? 'disabled' : ''}><b>${t('permg.' + g)}</b></label></legend>
        ${ps[0]?.admin ? html`<p class="xs faint">${t('perms.adminHint')}</p>` : ''}
        ${ps.map((p) => html`<label class="check"><input type="checkbox" data-p="${p.id}" ${state.has(p.id) ? 'checked' : ''} ${locked ? 'disabled' : ''}>${t('perm.' + p.id)}</label>`)}</fieldset>`)}`);
    $$('[data-g]', root).forEach((c) => {
      const ps = groups.find(([g]) => g === c.dataset.g)[1];
      c.indeterminate = !c.checked && ps.some((p) => state.has(p.id));
      c.addEventListener('change', () => { ps.forEach((p) => set(p.id, c.checked)); changed(); });
    });
    $$('[data-p]', root).forEach((c) => c.addEventListener('change', () => { set(c.dataset.p, c.checked); changed(); }));
    $('[data-all]', root)?.addEventListener('click', () => { d.permissions.filter((p) => !p.admin).forEach((p) => state.add(p.id)); changed(); });
    $('[data-none]', root)?.addEventListener('click', () => { state.clear(); changed(); });
  };
  const set = (id, on) => {
    if (on) { state.add(id); needs(id).forEach((r) => state.add(r)); } else {
      state.delete(id);
      d.permissions.filter((p) => p.requires.includes(id)).forEach((p) => state.delete(p.id));
    }
  };
  const changed = () => { onChange(); draw(); };
  draw();
  return draw;
}

function editUser(u, d, again) {
  const usable = d.profiles;
  let role = u ? u.role : (usable.find((p) => p.id === 'cashier') || usable.find((p) => !p.locked) || usable[0]).id;
  const state = new Set(u ? u.perms : usable.find((p) => p.id === role).perms);
  const options = () => html`${usable.map((p) => html`<option value="${p.id}" ${p.id === role ? 'selected' : ''}>${pname(p)}</option>`)}
    ${role === 'custom' ? html`<option value="custom" selected>${t('users.customProfile')}</option>` : ''}`;
  open({
    title: u ? u.full_name : t('users.add'), kind: 'panel',
    body: html`<div class="form"><div class="cols"><div class="field"><label for="uf">${t('f.name')}</label><input id="uf" class="input" data-guide="user.name" value="${u?.full_name || ''}" autofocus></div>
      <div class="field"><label for="uu">${t('f.username')}</label><input id="uu" class="input num" value="${u?.username || ''}" ${u ? 'disabled' : ''} autocomplete="off"></div></div>
      <div class="field"><label for="ur">${t('users.profile')}</label><select id="ur" class="input" data-guide="user.profile">${options()}</select><span class="hint" id="ur-hint"></span></div>
      <div class="cols"><div class="field"><label for="ud">${t('users.maxDiscount')}</label><input id="ud" class="input num" inputmode="numeric" value="${u ? u.max_discount_pct : ''}" placeholder="${t('users.byRole')}"></div>
      <div class="field"><label for="up">${u ? t('users.newPassword') : t('f.password')}</label><input id="up" type="password" class="input" data-guide="user.password" autocomplete="new-password" placeholder="${u ? t('users.keepPassword') : ''}"></div></div>
      ${u ? html`<label class="check"><input type="checkbox" id="ua" ${u.active ? 'checked' : ''}>${t('users.active')}</label>` : ''}
      <details class="card flat" ${role === 'custom' ? 'open' : ''}><summary class="row"><b class="grow">${t('users.custom')}</b>${icon('chev-d')}</summary><p class="small muted">${t('users.customHint')}</p>
        <div id="perms" class="stack tight"></div></details></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok data-guide="user.save">${t('act.save')}</button>`,
    mount(box, close) {
      const sel = $('#ur', box);
      const hint = () => put($('#ur-hint', box), role === 'custom' ? t('users.customNow') : t('profiles.nPerms', { n: state.size }));
      let redraw;
      const draw = () => { redraw = ticks($('#perms', box), d, state, { locked: role === d.locked, onChange: follow }); hint(); };
      const follow = () => {  // a tick changed: the person still has the profile only if the ticks are exactly its ticks
        const match = usable.find((p) => !p.locked && same(new Set(p.perms), state));
        role = match ? match.id : 'custom';
        put(sel, options()); hint();
      };
      sel.addEventListener('change', () => {
        role = sel.value;
        const p = usable.find((x) => x.id === role);
        if (p) { state.clear(); p.perms.forEach((x) => state.add(x)); $('#ud', box).placeholder = String(p.max_discount_pct); }
        put(sel, options()); draw();
      });
      draw();
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const body = { id: u?.id, full_name: $('#uf', box).value, role, perms: [...state] };
        if (!u) body.username = $('#uu', box).value;
        if ($('#ud', box).value !== '') body.max_discount_pct = +$('#ud', box).value;
        if ($('#up', box).value) body.password = $('#up', box).value;
        else if (!u) { shake($('#up', box)); return; }
        if (u) body.active = $('#ua', box).checked;
        if (await run(api.post('/api/user/save', body), t('saved'), e.currentTarget)) { signal('user.saved'); close(); again(); }
      });
      void redraw;
    },
  });
}

function editProfile(p, d, again) {
  const state = new Set(p ? p.perms : []);
  const locked = !!p?.locked;
  open({
    title: p ? pname(p) : t('profiles.add'), kind: 'panel',
    body: html`<div class="form"><div class="cols"><div class="field"><label for="pn">${t('profiles.name')}</label>
        <input id="pn" class="input" value="${p?.name || ''}" placeholder="${p?.builtin ? t('role.' + p.id) : t('profiles.namePh')}" ${locked ? 'disabled' : ''} autofocus></div>
      <div class="field"><label for="pd">${t('users.maxDiscount')}</label><input id="pd" class="input num" inputmode="numeric" value="${p ? p.max_discount_pct : 0}" ${locked ? 'disabled' : ''}></div></div>
      ${p && p.users && !locked ? html`<label class="check"><input type="checkbox" id="pa" checked>${t('profiles.apply', { n: p.users })}</label>` : ''}
      <div id="pp" class="stack tight"></div></div>`,
    foot: locked ? html`<button class="btn primary" data-close>${t('act.close')}</button>`
      : html`${p ? html`<button class="btn danger ghost" data-del>${icon('trash')}${t('act.delete')}</button>` : ''}<span class="grow"></span>
        <button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      ticks($('#pp', box), d, state, { locked });
      if (locked) return;
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const body = { id: p?.id, name: $('#pn', box).value, max_discount_pct: +$('#pd', box).value || 0, perms: [...state], apply: $('#pa', box)?.checked ?? true };
        const res = await run(api.post('/api/profile/save', body), t('saved'), e.currentTarget);
        if (res) { if (res.updated) toast(t('profiles.updatedN', { n: res.updated })); close(); again(); }
      });
      $('[data-del]', box)?.addEventListener('click', async (e) => {
        if (!await confirm({ title: t('profiles.delete', { name: pname(p) }), text: t('profiles.deleteHint', { n: p.users }), ok: t('act.delete'), danger: true })) return;
        if (await run(api.post('/api/profile/delete', { id: p.id }), t('saved'), e.currentTarget)) { close(); again(); }
      });
    },
  });
}

/** Who can do what: one row per permission, one column per profile. For the owner to check at a glance (and print). */
function matrix(d) {
  open({
    title: t('users.matrix'), kind: 'dialog', wide: true,
    body: html`<p class="small muted">${t('users.matrixHint')}</p><div class="table-wrap"><table class="t matrix"><thead><tr><th>${t('users.permission')}</th>
      ${d.profiles.map((p) => html`<th class="center">${pname(p)}</th>`)}</tr></thead><tbody>${d.groups.map((g) => html`<tr class="group-row"><th colspan="${d.profiles.length + 1}">${t('permg.' + g)}</th></tr>
      ${d.permissions.filter((x) => x.group === g).map((x) => html`<tr><td>${t('perm.' + x.id)}</td>${d.profiles.map((p) => html`<td class="center">${p.perms.includes(x.id)
        ? html`<span class="badge ok" aria-label="${t('users.yes')}">${icon('check')}</span>` : html`<span class="faint" aria-label="${t('users.no')}">–</span>`}</td>`)}</tr>`)}`)}</tbody></table></div>`,
    foot: html`<button class="btn ghost" data-print>${icon('print')}${t('act.print')}</button><button class="btn primary" data-close>${t('act.close')}</button>`,
    mount(box) {
      $('[data-print]', box).addEventListener('click', () => {  // A4 from the hidden print area, like the reports
        printHTML(html`<h2>${t('users.matrix')} · ${S.lookups?.settings?.shop_name || ''}</h2><p>${date(new Date().toISOString(), true)}</p>
          <table><thead><tr><th>${t('users.permission')}</th>${d.profiles.map((p) => html`<th>${pname(p)}</th>`)}</tr></thead><tbody>${d.groups.map((g) => html`
          <tr><th colspan="${d.profiles.length + 1}">${t('permg.' + g)}</th></tr>${d.permissions.filter((x) => x.group === g).map((x) => html`<tr><td>${t('perm.' + x.id)}</td>
          ${d.profiles.map((p) => html`<td>${p.perms.includes(x.id) ? '✓' : ''}</td>`)}</tr>`)}`)}</tbody></table>`, 'a4');
      });
    },
  });
}

async function places(body, again) {
  const d = await api.get('/api/settings').catch(() => null);
  if (!d) return;
  put(body, html`<div class="stack"><div class="card"><div class="card-head"><h2>${t('places.title')}</h2></div><p class="small muted">${t('places.hint')}</p>
    <div class="list">${d.locations.map((l) => html`<div class="li">${icon(l.kind === 'warehouse' ? 'warehouse' : l.kind === 'damaged' ? 'alert' : 'store')}
      <input class="input grow" data-loc="${l.id}" data-kind="${l.kind}" value="${l.name}"><span class="badge">${t('place.' + l.kind)}</span>${l.sellable ? html`<span class="badge ok">${t('places.sellable')}</span>` : ''}</div>`)}</div></div>
    <div class="card form"><div class="card-head"><h2>${t('places.add')}</h2></div><div class="cols"><div class="field"><label for="ln">${t('f.name')}</label><input id="ln" class="input"></div>
      <div class="field"><span class="label">${t('places.kind')}</span>${seg('kind', [['warehouse', t('place.warehouse')], ['shop', t('place.shop')], ['damaged', t('place.damaged')]], 'warehouse')}</div></div>
      <button class="btn primary" data-add>${icon('plus')}${t('places.add')}</button></div></div>`);
  let kind = 'warehouse';
  bindSeg(body, 'kind', (v) => { kind = v; });
  $$('[data-loc]', body).forEach((inp) => inp.addEventListener('change', () => run(api.post('/api/location/save', { id: inp.dataset.loc, name: inp.value, kind: inp.dataset.kind }), t('saved'))));
  $('[data-add]', body).addEventListener('click', async (e) => {
    const name = $('#ln', body).value.trim();
    if (!name) { shake($('#ln', body)); return; }
    if (await run(api.post('/api/location/save', { name, kind }), t('saved'), e.currentTarget)) { S.lookups = await api.get('/api/lookups'); again(); }
  });
}

async function support(body, again) {
  const d = await api.get('/api/support').catch((e) => { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); });
  if (!d) return;
  const last = d.last?.at ? html`<div class="tip ${d.last.ok ? 'ok' : 'warn'}">${icon(d.last.ok ? 'check-circle' : 'alert')}<div>${d.last.ok
    ? t('support.sentOk', { when: date(d.last.at, true) }) : t('support.sentFailed', { when: date(d.last.at, true), why: d.last.error })}</div></div>` : html`<p class="small muted">${t('support.never')}</p>`;
  put(body, html`<div class="two"><div class="card form"><div class="card-head"><h2>${t('support.title')}</h2></div><p class="small muted">${t('support.intro')}</p>
      <label class="check"><input type="checkbox" id="sp-on" ${d.enabled ? raw('checked') : ''}> ${t('support.enable')}</label>
      <div class="field"><label for="sp-url">${t('support.url')}</label><input id="sp-url" class="input ltr" dir="ltr" value="${d.url}" placeholder="https://"></div>
      <div class="field"><label for="sp-token">${t('support.token')}</label><input id="sp-token" class="input ltr" dir="ltr" type="password" autocomplete="off"
        placeholder="${d.has_token ? t('support.tokenKept') : ''}"></div>
      <div class="row wrap"><button class="btn accent" data-save>${icon('check')}${t('act.save')}</button><button class="btn" data-ping ${d.enabled ? '' : raw('disabled')}>${icon('refresh')}${t('support.ping')}</button></div>
      ${last}</div>
    <div class="card"><div class="card-head"><h2>${t('support.sends')}</h2></div><ul class="plain">${d.fields.map((f) => html`<li>${icon('check')} ${t('support.field.' + f)}</li>`)}</ul>
      <div class="tip">${icon('shield')}<div>${t('support.never_shared')}</div></div></div></div>`);
  $('[data-save]', body).addEventListener('click', async (e) => {
    const token = $('#sp-token', body).value.trim();
    const r = await run(api.post('/api/support/save', { enabled: $('#sp-on', body).checked, url: $('#sp-url', body).value, ...(token ? { token } : {}) }), t('saved'), e.currentTarget);
    if (r) again();
  });
  $('[data-ping]', body).addEventListener('click', async (e) => { if (await run(api.post('/api/support/ping'), t('support.pinged'), e.currentTarget)) again(); });
}

async function privacy(body, again) {
  let status, prompt, cfg = { url: '', has_token: false, sending: false };
  try {
    [status, prompt] = await Promise.all([
      api.get('/api/consent/status'),
      api.get('/api/consent/prompt', { lang: lang() }),
    ]);
    if (can('settings.edit')) cfg = await api.get('/api/telemetry/config');
  } catch (e) {
    put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`);
    return;
  }
  const agreed = status.install && status.install.decision === 'agree';
  put(body, html`<div class="stack"><div class="card"><div class="card-head"><h2>${t('privacy.title')}</h2></div>
      <p class="muted">${t('privacy.lead')}</p><div id="privacy-box"></div>
      ${can('settings.edit') ? html`<div class="row wrap"><button class="btn" data-install>${agreed ? t('privacy.installWithdraw') : t('privacy.installAgree')}</button></div>` : ''}</div>
    ${can('settings.edit') ? html`<div class="card form"><div class="card-head"><h2>${t('privacy.receiver')}</h2></div>
      <p class="small muted">${cfg.sending ? t('privacy.configured') : t('privacy.off')}</p>
      <div class="field"><label for="tel-url">${t('privacy.receiver')}</label><input id="tel-url" class="input" value="${cfg.url || ''}" placeholder="https://" autocomplete="off"></div>
      <div class="field"><label for="tel-token">${t('privacy.token')}</label><input id="tel-token" class="input" type="password" autocomplete="off" placeholder="${cfg.has_token ? t('privacy.tokenKept') : ''}"></div>
      <div class="row wrap"><button class="btn accent" data-save>${t('privacy.save')}</button>
        ${cfg.has_token ? html`<button class="btn" data-clear>${t('privacy.clearToken')}</button>` : ''}</div></div>` : ''}</div>`);
  const decide = async (decision, scope) => {
    if (!await run(api.post('/api/consent/decide', { decision, text_id: prompt.text_id, lang: prompt.lang, scope }))) return;
    const { refreshConsent } = await import('../guide.js');
    await refreshConsent();
    again();
  };
  if (window.AFConsent) {
    window.AFConsent.settings($('#privacy-box', body), {
      status, prompt, decide: (d) => decide(d, 'person'),
      showSent: async () => {
        const rows = await api.get('/api/telemetry/sent').catch(() => []);
        const list = Array.isArray(rows) ? rows : [];
        open({ title: t('privacy.sentTitle'), body: list.length
          ? html`<div class="list">${list.map((r) => html`<div class="li"><b class="grow">${r.type || ''}</b><span class="small muted num">${r.page || ''} ${r.ts || ''}</span></div>`)}</div>`
          : html`<p class="muted">${t('privacy.sentEmpty')}</p>` });
      },
    });
    $('#privacy-box', body).lastElementChild.textContent = t('privacy.reportConsent');
  }
  $('[data-install]', body)?.addEventListener('click', () => decide(agreed ? 'withdraw' : 'agree', 'install'));
  $('[data-save]', body)?.addEventListener('click', async (e) => {
    const token = $('#tel-token', body).value.trim();
    const posted = { url: $('#tel-url', body).value.trim() };
    if (token) posted.token = token;
    if (await run(api.post('/api/telemetry/config', posted), t('saved'), e.currentTarget)) again();
  });
  $('[data-clear]', body)?.addEventListener('click', async (e) => {
    if (await run(api.post('/api/telemetry/config', { url: $('#tel-url', body).value.trim(), clear_token: true }), t('saved'), e.currentTarget)) again();
  });
}

async function backup(body, again) {
  const [d, o] = await Promise.all([api.get('/api/settings').catch(() => null), api.get('/api/offsite').catch(() => null)]);
  if (!d) return;
  const age = d.backup_age_hours;
  put(body, html`<div class="stack"><div class="two"><div class="card ${age !== null && age < 30 ? 'accent-card' : 'ink-card'}"><div class="kpi"><span class="label">${t('backup.last')}</span>
      <span class="value">${age === null ? t('backup.never') : t('backup.ago', { h: age })}</span><span class="small">${t('backup.auto')}</span></div>
      <div class="row wrap"><button class="btn primary" data-now data-guide="backup.now">${icon('download')}${t('backup.now')}</button><button class="btn" data-export>${icon('upload')}${t('backup.export')}</button></div></div>
    ${o && !o.practice ? offsiteCard(o) : html`<div class="card"><div class="card-head"><h2>${t('backup.where')}</h2></div><p class="small muted">${t('backup.whereHint')}</p>
      <div class="tip warn">${icon('alert')}<div>${t('backup.usb')}</div></div></div>`}</div>
    <div class="card"><div class="card-head"><h2>${t('backup.list')}</h2></div>${d.backups.length ? html`<div class="list">${d.backups.map((b) => html`<div class="li">${icon('layers')}
      <span class="grow num">${b.name}</span><span class="small muted">${date(b.mtime, true)} · ${(b.size / 1048576).toFixed(1)} MB</span><button class="btn sm" data-restore="${b.name}">${t('backup.restore')}</button></div>`)}</div>`
      : html`<p class="muted">${t('backup.none')}</p>`}</div>
    <div class="card"><div class="card-head"><h2>${t('settings.devices')}</h2></div><p class="small muted">${t('settings.devicesHint')}</p>
      <div class="row wrap">${d.addresses.map((a) => html`<code class="chip num">${a}</code>`)}</div></div></div>`);
  $('[data-now]', body).addEventListener('click', async (e) => { if (await run(api.post('/api/backup/now'), t('backup.done'), e.currentTarget)) { signal('backup.done'); again(); } });
  if (o && !o.practice) bindOffsite(body, o, again);
  $('[data-export]', body).addEventListener('click', async (e) => {
    const btn = e.currentTarget; btn.setAttribute('aria-busy', 'true');
    try { const res = await api.get('/api/export'); download(`al-store-${new Date().toISOString().slice(0, 10)}.zip`, await res.blob()); } catch (err) { toast(errorText(err), 'bad'); }
    btn.removeAttribute('aria-busy');
  });
  $$('[data-restore]', body).forEach((b) => b.addEventListener('click', () => open({
    title: t('backup.restoreTitle'),
    body: html`<div class="tip bad">${icon('alert')}<div>${t('backup.restoreText', { name: b.dataset.restore })}</div></div>
      <div class="field"><label for="rp">${t('backup.yourPassword')}</label><input id="rp" type="password" class="input" autofocus></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn danger" data-ok>${t('backup.restore')}</button>`,
    mount(box) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        if (await run(api.post('/api/backup/restore', { name: b.dataset.restore, password: $('#rp', box).value }), t('backup.restored'), e.currentTarget)) setTimeout(() => location.reload(), 900);
      });
    },
  })));
}

// ---------------------------------------------------------------- the protected copy outside this PC (server/offsite.py)
const offsiteFresh = (o) => o.on && o.reachable && o.age_hours !== null && o.age_hours <= 48;

function offsiteCard(o) {
  if (!o.on) {
    return html`<div class="card" data-offsite><div class="card-head"><h2>${t('off.title')}</h2><span class="badge warn">${t('off.offBadge')}</span></div>
      <p class="small muted">${t('off.why')}</p><div class="tip">${icon('info')}<div>${t('off.how')}</div></div>
      <div class="row wrap"><button class="btn accent" data-off-change>${icon('shield')}${t('off.start')}</button></div></div>`;
  }
  return html`<div class="card ${offsiteFresh(o) ? 'accent-card' : ''}" data-offsite><div class="card-head"><h2>${t('off.title')}</h2>
      <span class="badge ${offsiteFresh(o) ? 'ok' : 'bad'}">${t(!o.reachable ? 'off.unreachable' : offsiteFresh(o) ? 'off.onBadge' : 'off.oldBadge')}</span></div>
    <p class="small"><span class="muted">${t('off.folder')}</span> <code class="wrap-any" dir="ltr">${o.dir}</code></p>
    <p class="small">${o.age_hours === null ? t('off.noneYet') : t('off.ago', { h: o.age_hours })} · ${t('off.count', { n: o.copies.length })}</p>
    ${!o.reachable ? html`<div class="tip bad">${icon('alert')}<div>${t('off.unreachableHint')}</div></div>` : ''}
    ${o.reachable && o.last && !o.last.ok ? html`<div class="tip bad">${icon('alert')}<div>${t('off.failed')}</div></div>` : ''}
    ${o.same_disk ? html`<div class="tip warn">${icon('alert')}<div>${t('off.sameDisk')}</div></div>` : ''}
    <div class="row wrap"><button class="btn primary" data-off-now>${icon('upload')}${t('off.now')}</button>
      <button class="btn" data-off-phrase>${icon('key')}${t('off.showPhrase')}</button>
      <button class="btn" data-off-restore>${icon('layers')}${t('off.restore')}</button>
      <button class="btn ghost" data-off-change>${t('off.change')}</button><button class="btn ghost" data-off-stop>${t('off.stop')}</button></div></div>`;
}

const pwField = (id) => html`<div class="field"><label for="${id}">${t('backup.yourPassword')}</label><input id="${id}" type="password" class="input" autocomplete="current-password"></div>`;

/** The phrase on screen and on paper. `first`: right after it was made, the person must tick that it is written down. */
function showPhrase(phrase, first) {
  const shop = S.boot.shop_name || '';
  const paper = html`<div class="recovery-paper"><h1>${t('off.phraseTitle')}</h1><p>${shop}</p><p class="recovery-code" dir="ltr">${phrase}</p>
    <p>${t('off.phraseWhy')}</p><p>${t('off.phraseLost')}</p><p>${date(today())}</p></div>`;
  open({
    title: t('off.phraseTitle'),
    sticky: first,
    body: html`<p class="muted">${t('off.phraseWhy')}</p><p class="recovery-code" dir="ltr" data-offsite-phrase>${phrase}</p>
      <div class="tip warn">${icon('alert')}<div>${t('off.phraseLost')}</div></div>
      ${first ? html`<label class="check"><input type="checkbox" id="op-kept">${t('recovery.kept')}</label>` : ''}`,
    foot: html`<button class="btn" data-print>${icon('print')}${t('act.print')}</button>
      <button class="btn accent grow" data-ok ${first ? 'disabled' : ''}>${t('recovery.continue')}</button>`,
    mount(box, close) {
      $('[data-print]', box).addEventListener('click', () => printHTML(paper, 'a4'));
      if (first) $('#op-kept', box).addEventListener('change', (e) => { $('[data-ok]', box).disabled = !e.target.checked; });
      $('[data-ok]', box).addEventListener('click', () => close());
    },
  });
}

function bindOffsite(body, o, again) {
  const on = (sel, fn) => { const el = $(sel, body); if (el) el.addEventListener('click', fn); };
  on('[data-off-now]', async (e) => {
    const btn = e.currentTarget; btn.setAttribute('aria-busy', 'true');
    try { const r = await api.post('/api/offsite/now'); toast(r.ok ? t('off.done') : t('off.failed'), r.ok ? 'ok' : 'bad'); again(); } catch (err) { toast(errorText(err), 'bad'); }
    btn.removeAttribute('aria-busy');
  });
  on('[data-off-change]', () => open({
    title: o.on ? t('off.change') : t('off.start'),
    body: html`<p class="small muted">${t('off.chooseHint')}</p>
      ${o.places.length ? html`<div class="row wrap">${o.places.map((p) => html`<button class="chip" data-place="${p.dir}">${icon(p.kind === 'drive' ? 'download' : 'upload')}${t('off.kind.' + p.kind)} <span class="wrap-any" dir="ltr">${p.dir}</span></button>`)}</div>`
        : html`<div class="tip">${icon('info')}<div>${t('off.noPlaces')}</div></div>`}
      <div class="field"><label for="od">${t('off.folder')}</label><input id="od" class="input num" dir="ltr" value="${o.dir || ''}" placeholder="E:\Al-Store-Backup"></div>
      ${pwField('opw')}<p class="err small" id="od-err" role="alert"></p>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn accent" data-ok>${icon('shield')}${t('off.save')}</button>`,
    mount(box, close) {
      $$('[data-place]', box).forEach((b) => b.addEventListener('click', () => { $('#od', box).value = b.dataset.place; }));
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const btn = e.currentTarget; btn.setAttribute('aria-busy', 'true');
        try {
          const r = await api.post('/api/offsite/enable', { dir: $('#od', box).value, password: $('#opw', box).value });
          close();
          toast(r.copy && r.copy.ok ? t('off.done') : t('off.failed'), r.copy && r.copy.ok ? 'ok' : 'bad');
          if (r.phrase) showPhrase(r.phrase, true);
          again();
        } catch (err) { showError($('#od-err', box), err); } finally { btn.removeAttribute('aria-busy'); }
      });
    },
  }));
  const withPassword = (title, text, url, done) => () => open({
    title,
    body: html`${text ? html`<p class="muted">${text}</p>` : ''}${pwField('xpw')}<p class="err small" id="x-err" role="alert"></p>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.ok')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const btn = e.currentTarget; btn.setAttribute('aria-busy', 'true');
        try { const r = await api.post(url, { password: $('#xpw', box).value }); close(); done(r); } catch (err) { showError($('#x-err', box), err); } finally { btn.removeAttribute('aria-busy'); }
      });
    },
  });
  on('[data-off-phrase]', withPassword(t('off.showPhrase'), '', '/api/offsite/phrase', (r) => showPhrase(r.phrase, false)));
  on('[data-off-stop]', withPassword(t('off.stop'), t('off.stopHint'), '/api/offsite/disable', () => { toast(t('saved'), 'ok'); again(); }));
  on('[data-off-restore]', async () => {
    const found = await api.get('/api/offsite/find').catch(() => ({ copies: [] }));
    open({
      title: t('off.restore'), wide: true,
      body: html`<div class="tip bad">${icon('alert')}<div>${t('off.restoreText')}</div></div>
        ${copyPicker(found.copies)}<div class="field"><label for="ofr">${t('off.phrase')}</label><input id="ofr" class="input num" dir="ltr" autocomplete="off"></div>
        ${pwField('orpw')}<p class="err small" id="or-err" role="alert"></p>`,
      foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn danger" data-ok>${t('backup.restore')}</button>`,
      mount(box) {
        bindCopyPicker(box);
        $('[data-ok]', box).addEventListener('click', async (e) => {
          const btn = e.currentTarget; btn.setAttribute('aria-busy', 'true');
          try {
            await api.post('/api/offsite/restore', { path: $('#ofp', box).value.trim(), phrase: $('#ofr', box).value, password: $('#orpw', box).value });
            toast(t('backup.restored'), 'ok'); setTimeout(() => location.reload(), 900);
          } catch (err) { showError($('#or-err', box), err); btn.removeAttribute('aria-busy'); }
        });
      },
    });
  });
}

/** The protected copies the program found (OneDrive, Google Drive, USB sticks), and a box for a file path it did not find. Also used by setup. */
export function copyPicker(copies) {
  return html`${copies.length ? html`<div class="list" data-copies>${copies.map((c, i) => html`<label class="li check"><input type="radio" name="ofc" value="${c.path}" ${i === 0 ? 'checked' : ''}>
      <span class="grow num ellipsis" dir="ltr">${c.path}</span><span class="small muted">${date(c.made_at, true)} · ${(c.size / 1048576).toFixed(1)} MB</span></label>`)}</div>`
    : html`<div class="tip">${icon('info')}<div>${t('off.noneFound')}</div></div>`}
    <div class="field"><label for="ofp">${t('off.file')}</label><input id="ofp" class="input num" dir="ltr" value="${copies[0]?.path || ''}" placeholder="E:\Al-Store-Backup\alstore-….alstore"></div>`;
}

export function bindCopyPicker(box) {
  $$('input[name="ofc"]', box).forEach((r) => r.addEventListener('change', () => { $('#ofp', box).value = r.value; }));
}

function device(body) {
  const p = prefs.all();
  put(body, html`<div class="card form"><div class="card-head"><h2>${t('pref.title')}</h2></div><p class="small muted">${t('pref.hint')}</p>
    <div class="field"><span class="label">${t('pref.lang')}</span>${seg('lang', [['ar', 'العربية'], ['en', 'English']], lang())}</div>
    <div class="field"><span class="label">${t('pref.theme')}</span>${seg('theme', [['auto', t('pref.auto'), 'layers'], ['day', t('pref.day'), 'sun'], ['night', t('pref.night'), 'moon'], ['contrast', t('pref.contrast'), 'eye']], p.theme)}</div>
    <div class="field"><span class="label">${t('pref.size')}</span>${seg('size', [['s', 'A−'], ['m', 'A'], ['l', 'A+'], ['xl', 'A++']], p.size)}</div>
    <div class="field"><span class="label">${t('pref.motion')}</span>${seg('motion', [['auto', t('pref.auto')], ['off', t('pref.motionOff')]], p.motion)}</div>
    <div class="field"><span class="label">${t('pref.sound')}</span>${seg('sound', [['1', t('pref.on')], ['0', t('pref.off')]], p.sound ? '1' : '0')}</div>
    <p class="small faint">${t('about.version', { v: S.boot.version })}</p></div>`);
  bindSeg(body, 'lang', (v) => { setLang(v); location.reload(); });
  bindSeg(body, 'theme', (v) => prefs.set('theme', v));
  bindSeg(body, 'size', (v) => prefs.set('size', v));
  bindSeg(body, 'motion', (v) => prefs.set('motion', v));
  bindSeg(body, 'sound', (v) => prefs.set('sound', v === '1'));
}

export const _c = confirm;
