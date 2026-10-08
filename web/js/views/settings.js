// Settings: the shop, the licence, people and permissions, places, backups and export, this device's preferences.
import { api } from '../api.js';
import { S, can, licenceCard, renderBanners } from '../app.js';
import { t, lang, setLang } from '../i18n.js';
import { shake } from '../motion.js';
import { prefs } from '../prefs.js';
import { CUR, raw, $, $$, html, put, icon, date, open, empty, skeleton, errorText, toast, run, confirm, seg, bindSeg, initials, download, parseMoney } from '../ui.js';

const TABS = [['shop', 'store', 'settings.edit'], ['licence', 'key', 'settings.edit'], ['users', 'users', 'users.manage'], ['places', 'warehouse', 'settings.edit'],
  ['backup', 'download', 'settings.edit'], ['support', 'help', 'settings.edit'], ['device', 'sun', null]];

export default async function view(page, params) {
  const tabs = TABS.filter(([, , p]) => !p || can(p));
  const tab = tabs.find(([k]) => k === params.tab)?.[0] || tabs[0][0];
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.settings')}</h1><p>${t('settings.sub')}</p></div></div>
    <nav class="tabs" data-lab-scroll aria-label="${t('nav.sections')}">${tabs.map(([k, ic]) => html`<a href="#/settings?tab=${k}" ${tab === k ? CUR : ''}>${icon(ic)}${t('settings.tab.' + k)}</a>`)}</nav><div id="set-body">${skeleton(5)}</div>`);
  const body = $('#set-body', page);
  const again = () => view(page, params);
  ({ shop, licence, users, places, backup, support, device })[tab](body, again);
}

async function shop(body) {
  const d = await api.get('/api/settings').catch((e) => { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); });
  if (!d) return;
  const s = d.settings;
  const f = (k, label, hint, type = 'text') => html`<div class="field"><label for="s-${k}">${label}</label><input id="s-${k}" class="input ${type === 'money' ? 'money-in' : ''}" data-k="${k}" data-type="${type}"
    value="${type === 'money' ? s[k] / 100 : s[k]}" ${type !== 'text' ? raw('inputmode="decimal"') : ''}>${hint ? html`<span class="hint">${hint}</span>` : ''}</div>`;
  put(body, html`<div class="stack"><div class="card form"><div class="card-head"><h2>${t('settings.shopInfo')}</h2></div>
      <div class="cols">${f('shop_name', t('setup.shop'))}${f('shop_phone', t('f.phone'))}${f('shop_address', t('f.address'))}${f('tax_number', t('settings.taxNo'), t('settings.taxNoHint'))}</div></div>
    <div class="card form"><div class="card-head"><h2>${t('settings.receipt')}</h2></div>
      <div class="field"><span class="label">${t('settings.paper')}</span>${seg('rw', [['80', '80 mm'], ['58', '58 mm']], s.receipt_width)}</div>
      <div class="cols">${f('receipt_footer', t('settings.footer'))}${f('wallet_number', t('settings.wallet'), t('settings.walletHint'))}</div>
      <div class="cols">${f('return_days', t('settings.returnDays'), t('settings.returnDaysHint'), 'num')}${f('defect_days', t('settings.defectDays'), t('settings.defectDaysHint'), 'num')}</div></div>
    <div class="card form"><div class="card-head"><h2>${t('settings.instalments')}</h2></div>
      <div class="cols">${f('min_down_payment_pct', t('settings.minDown'), '', 'num')}${f('instalment_markup_pct', t('settings.markup'), t('settings.markupHint'), 'num')}
      ${f('max_instalment_months', t('settings.maxMonths'), '', 'num')}</div>
      <div class="field"><label for="s-prov">${t('settings.providers')}</label><input id="s-prov" class="input" value="${(s.finance_providers || []).join('، ')}"><span class="hint">${t('settings.providersHint')}</span></div></div>
    <div class="card form"><div class="card-head"><h2>${t('settings.watch')}</h2></div>
      <div class="cols">${f('large_expense', t('settings.largeExpense'), '', 'money')}${f('opening_hour', t('settings.open'), '', 'num')}${f('closing_hour', t('settings.close'), '', 'num')}</div></div>
    <div class="row"><button class="btn volt lg" data-save>${icon('check')}${t('act.save')}</button></div></div>`);
  $('[data-save]', body).addEventListener('click', async (e) => {
    const out = { receipt_width: $('[data-seg="rw"] [aria-pressed="true"]', body).dataset.v,
      finance_providers: $('#s-prov', body).value.split(/[,،]\s*/).map((x) => x.trim()).filter(Boolean) };
    for (const inp of $$('[data-k]', body)) {
      const ty = inp.dataset.type;
      if (ty === 'money') { const v = parseMoney(inp.value); if (v === null) { shake(inp); return; } out[inp.dataset.k] = v; }
      else if (ty === 'num') { const v = Number(inp.value); if (!Number.isFinite(v) || v < 0) { shake(inp); return; } out[inp.dataset.k] = v; }
      else out[inp.dataset.k] = inp.value;
    }
    const r = await run(api.post('/api/settings/save', { settings: out }), t('saved'), e.currentTarget);
    if (r) { S.lookups = await api.get('/api/lookups').catch(() => S.lookups); }
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

async function users(body, again) {
  let d;
  try { d = await api.get('/api/users'); } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  put(body, html`<div class="stack"><div class="row between wrap"><p class="muted">${t('users.sub')}</p><button class="btn primary" data-new>${icon('plus')}${t('users.add')}</button></div>
    <div class="grid">${d.users.map((u) => html`<button class="card flat spot user-card" data-id="${u.id}"><div class="row"><span class="avatar">${initials(u.full_name)}</span>
      <span class="grow"><b>${u.full_name}</b><bdi class="small muted"> @${u.username}</bdi><div class="small">${t('role.' + u.role)}${u.max_discount_pct ? ' · ' + t('users.discountN', { n: u.max_discount_pct }) : ''}</div></span>
      ${u.active ? '' : html`<span class="badge bad">${t('users.off')}</span>`}</div></button>`)}</div>
    <div class="card"><div class="card-head"><h2>${t('users.rolesTitle')}</h2></div><div class="grid">${Object.keys(d.roles).map((r) => html`<div><b>${t('role.' + r)}</b><p class="small muted">${t('role.' + r + '.hint')}</p></div>`)}</div></div></div>`);
  $('[data-new]', body).addEventListener('click', () => editUser(null, d, again));
  $$('[data-id]', body).forEach((b) => b.addEventListener('click', () => editUser(d.users.find((u) => u.id === b.dataset.id), d, again)));
}

function editUser(u, d, again) {
  const groups = {};
  d.permissions.forEach((p) => { (groups[p.group] = groups[p.group] || []).push(p); });
  const rolePerms = (role) => new Set(d.roles[role]?.perms || []);
  open({
    title: u ? u.full_name : t('users.add'), kind: 'panel',
    body: html`<div class="form"><div class="cols"><div class="field"><label for="uf">${t('f.name')}</label><input id="uf" class="input" value="${u?.full_name || ''}" autofocus></div>
      <div class="field"><label for="uu">${t('f.username')}</label><input id="uu" class="input num" value="${u?.username || ''}" ${u ? 'disabled' : ''} autocomplete="off"></div></div>
      <div class="field"><span class="label">${t('users.role')}</span>${seg('role', Object.keys(d.roles).map((r) => [r, t('role.' + r)]), u?.role || 'cashier')}</div>
      <div class="cols"><div class="field"><label for="ud">${t('users.maxDiscount')}</label><input id="ud" class="input num" inputmode="numeric" value="${u ? u.max_discount_pct : ''}" placeholder="${t('users.byRole')}"></div>
      <div class="field"><label for="up">${u ? t('users.newPassword') : t('f.password')}</label><input id="up" type="password" class="input" autocomplete="new-password" placeholder="${u ? t('users.keepPassword') : ''}"></div></div>
      ${u ? html`<label class="check"><input type="checkbox" id="ua" ${u.active ? 'checked' : ''}>${t('users.active')}</label>` : ''}
      <details class="card flat"><summary class="row"><b class="grow">${t('users.custom')}</b>${icon('chev-d')}</summary><p class="small muted">${t('users.customHint')}</p>
        <div id="perms" class="stack tight"></div></details></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      let role = u?.role || 'cashier';
      const extra = new Set(u?.extra_perms || []), denied = new Set(u?.denied_perms || []);
      const drawPerms = () => {
        const base = rolePerms(role);
        put($('#perms', box), html`${Object.entries(groups).map(([g, ps]) => html`<div><div class="nav-label">${t('permg.' + g)}</div>${ps.map((p) => {
          const on = (base.has(p.id) && !denied.has(p.id)) || extra.has(p.id);
          return html`<label class="check"><input type="checkbox" data-p="${p.id}" ${on ? 'checked' : ''}>${t('perm.' + p.id)}</label>`;
        })}</div>`)}`);
        $$('[data-p]', box).forEach((c) => c.addEventListener('change', () => {
          const id = c.dataset.p, inBase = rolePerms(role).has(id);
          extra.delete(id); denied.delete(id);
          if (c.checked && !inBase) extra.add(id);
          if (!c.checked && inBase) denied.add(id);
        }));
      };
      bindSeg(box, 'role', (v) => { role = v; extra.clear(); denied.clear(); drawPerms(); });
      drawPerms();
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const body = { id: u?.id, full_name: $('#uf', box).value, role, extra_perms: [...extra], denied_perms: [...denied] };
        if (!u) body.username = $('#uu', box).value;
        if ($('#ud', box).value !== '') body.max_discount_pct = +$('#ud', box).value;
        if ($('#up', box).value) body.password = $('#up', box).value;
        else if (!u) { shake($('#up', box)); return; }
        if (u) body.active = $('#ua', box).checked;
        if (await run(api.post('/api/user/save', body), t('saved'), e.currentTarget)) { close(); again(); }
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
      <div class="row wrap"><button class="btn volt" data-save>${icon('check')}${t('act.save')}</button><button class="btn" data-ping ${d.enabled ? '' : raw('disabled')}>${icon('refresh')}${t('support.ping')}</button></div>
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

async function backup(body, again) {
  const d = await api.get('/api/settings').catch(() => null);
  if (!d) return;
  const age = d.backup_age_hours;
  put(body, html`<div class="stack"><div class="two"><div class="card ${age !== null && age < 30 ? 'volt-card' : 'ink-card'}"><div class="kpi"><span class="label">${t('backup.last')}</span>
      <span class="value">${age === null ? t('backup.never') : t('backup.ago', { h: age })}</span><span class="small">${t('backup.auto')}</span></div>
      <div class="row wrap"><button class="btn primary" data-now>${icon('download')}${t('backup.now')}</button><button class="btn" data-export>${icon('upload')}${t('backup.export')}</button></div></div>
    <div class="card"><div class="card-head"><h2>${t('backup.where')}</h2></div><p class="small muted">${t('backup.whereHint')}</p>
      <div class="tip warn">${icon('alert')}<div>${t('backup.usb')}</div></div></div></div>
    <div class="card"><div class="card-head"><h2>${t('backup.list')}</h2></div>${d.backups.length ? html`<div class="list">${d.backups.map((b) => html`<div class="li">${icon('layers')}
      <span class="grow num">${b.name}</span><span class="small muted">${date(b.mtime, true)} · ${(b.size / 1048576).toFixed(1)} MB</span><button class="btn sm" data-restore="${b.name}">${t('backup.restore')}</button></div>`)}</div>`
      : html`<p class="muted">${t('backup.none')}</p>`}</div>
    <div class="card"><div class="card-head"><h2>${t('settings.devices')}</h2></div><p class="small muted">${t('settings.devicesHint')}</p>
      <div class="row wrap">${d.addresses.map((a) => html`<code class="chip num">${a}</code>`)}</div></div></div>`);
  $('[data-now]', body).addEventListener('click', async (e) => { if (await run(api.post('/api/backup/now'), t('backup.done'), e.currentTarget)) again(); });
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
