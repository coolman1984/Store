// Receiving goods: from a supplier (paid now or owed) or opening stock; serial numbers scanned per piece; supplier accounts.
import { api, key } from '../api.js';
import { S, can, settle } from '../app.js';
import { t } from '../i18n.js';
import { shake } from '../motion.js';
import { linePicker } from './stock.js';
import { CUR, $, $$, html, put, icon, money, moneyH, date, open, empty, skeleton, errorText, toast, parseMoney, run, seg, bindSeg } from '../ui.js';

export default async function view(page, params) {
  const tab = ['history', 'suppliers'].includes(params.tab) ? params.tab : 'new';
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.receive')}</h1><p>${t('receive.sub')}</p></div></div>
    <nav class="tabs"><a href="#/receive" ${tab === 'new' ? CUR : ''}>${icon('truck')}${t('receive.tab.new')}</a>
      <a href="#/receive?tab=history" ${tab === 'history' ? CUR : ''}>${icon('receipt')}${t('receive.tab.history')}</a>
      <a href="#/receive?tab=suppliers" ${tab === 'suppliers' ? CUR : ''}>${icon('users')}${t('receive.tab.suppliers')}</a></nav>
    <div id="rc-body"></div>`);
  const body = $('#rc-body', page);
  if (tab === 'history') return history(body);
  if (tab === 'suppliers') return suppliers(body, params);
  return newReceipt(body, () => view(page, params));
}

async function newReceipt(body, again) {
  const sups = await api.get('/api/suppliers').catch(() => []);
  const locs = S.lookups?.locations || [];
  const store = locs.find((l) => l.kind === 'warehouse') || locs[0];
  const idem = key();
  put(body, html`<div class="two"><div class="card"><div class="card-head"><h2>${t('receive.lines')}</h2></div><div id="rlines"></div></div>
    <div class="stack"><div class="card form">
      <div class="field"><label for="rs">${t('receive.supplier')}</label><div class="row"><select id="rs" class="input grow"><option value="">${t('receive.noSupplier')}</option>
        ${sups.map((s) => html`<option value="${s.id}">${s.name}</option>`)}</select><button class="icon-btn" data-addsup aria-label="${t('receive.newSupplier')}">${icon('plus')}</button></div>
        <span class="hint">${t('receive.noSupplierHint')}</span></div>
      <div class="cols"><div class="field"><label for="rl">${t('receive.to')}</label><select id="rl" class="input">${locs.filter((l) => l.kind !== 'damaged').map((l) => html`<option value="${l.id}" ${l.id === store?.id ? 'selected' : ''}>${l.name}</option>`)}</select></div>
        <div class="field"><label for="rref">${t('receive.ref')}</label><input id="rref" class="input num"></div></div>
      <div class="field"><label for="rshelf">${t('receive.shelf')}</label><input id="rshelf" class="input num" placeholder="A-3"></div>
      <div class="tot-big"><span>${t('f.total')}</span><b class="num" id="rtotal">${money(0)}</b></div>
      ${can('cost.view') || can('suppliers.pay') ? html`<div class="cols"><div class="field"><label for="rpaid">${t('receive.paidNow')}</label><input id="rpaid" class="input money-in" inputmode="decimal" placeholder="0"></div>
        <div class="field"><span class="label">${t('receive.payFrom')}</span>${seg('from', [['safe', t('cash.safe')], ['drawer', t('cash.drawer')]], 'safe')}</div></div>` : ''}
      <div class="field"><label for="rnote">${t('f.note')}</label><input id="rnote" class="input"></div>
      <p class="err small" id="rerr" role="alert"></p>
      <button class="btn volt lg" data-save>${icon('check')}${t('receive.save')}</button></div>
      <div class="tip">${icon('info')}<div>${t('receive.tip')}</div></div></div></div>`);
  let from = 'safe';
  bindSeg(body, 'from', (v) => { from = v; });
  const lines = linePicker($('#rlines', body), { withCost: true, onChange: (ls) => { $('#rtotal', body).textContent = money(ls.reduce((a, l) => a + Math.round(l.qty * (l.unit_cost || 0)), 0)); } });
  $('[data-addsup]', body).addEventListener('click', () => editSupplier(null, async (id, name) => {
    const opt = document.createElement('option'); opt.value = id; opt.textContent = name; $('#rs', body).appendChild(opt); $('#rs', body).value = id;
  }));
  $('[data-save]', body).addEventListener('click', async (e) => {
    $('#rerr', body).textContent = '';
    if (!lines.length) { shake($('#lp-q', body)); $('#rerr', body).textContent = t('receive.addLines'); return; }
    for (const l of lines) if (l.track_serial && l.serials.length !== l.qty) { $('#rerr', body).textContent = t('receive.serialCount', { name: l.name }); return; }
    const paid = $('#rpaid', body) ? parseMoney($('#rpaid', body).value || '0') : 0;
    if (paid === null) { shake($('#rpaid', body)); return; }
    const total = lines.reduce((a, l) => a + Math.round(l.qty * (l.unit_cost || 0)), 0);
    const supplier = $('#rs', body).value || undefined;
    const r = await run(api.post('/api/purchase', { idem_key: idem, supplier_id: supplier, location_id: $('#rl', body).value, supplier_ref: $('#rref', body).value,
      shelf: $('#rshelf', body).value, note: $('#rnote', body).value, paid_now: supplier ? paid : (paid ? total : 0), pay_from: from,
      lines: lines.map((l) => ({ product_id: l.product_id, qty: l.qty, unit_cost: l.unit_cost || 0, serials: l.serials })) }), null, e.currentTarget);
    if (r) { toast(t('receive.done', { n: r.number })); again(); }
  });
}

async function history(body) {
  put(body, skeleton(4));
  try {
    const rows = await api.get('/api/purchases');
    put(body, rows.length ? html`<div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.number')}</th><th>${t('f.date')}</th><th>${t('receive.supplier')}</th>
      <th>${t('receive.to')}</th><th class="hide-phone">${t('receive.ref')}</th>${rows[0].total !== undefined ? html`<th class="end">${t('f.total')}</th>` : ''}</tr></thead>
      <tbody>${rows.map((r) => html`<tr class="click" data-id="${r.id}"><td class="num">${r.number}</td><td class="num">${date(r.at, true)}</td><td>${r.supplier || html`<span class="faint">${t('receive.opening')}</span>`}</td>
      <td>${r.place}</td><td class="hide-phone num">${r.supplier_ref}</td>${r.total !== undefined ? html`<td class="end money num">${money(r.total)}</td>` : ''}</tr>`)}</tbody></table></div></div>`
      : html`<div class="card">${empty('truck', t('receive.none'), t('receive.noneHint'))}</div>`);
    $$('tr[data-id]', body).forEach((tr) => tr.addEventListener('click', async () => {
      const p = await api.get('/api/purchase', { id: tr.dataset.id }).catch((e) => toast(errorText(e), 'bad'));
      if (!p) return;
      open({ title: html`${t('receive.invoice')} <span class="num">${p.number}</span>`, kind: 'panel',
        body: html`<p class="muted small">${date(p.at, true)} · ${p.supplier || t('receive.opening')} · ${p.place}</p>
          <div class="card flat pad-0"><table class="t"><tbody>${p.lines.map((l) => html`<tr><td><b>${l.name}</b>${JSON.parse(l.serials).length ? html`<div class="xs faint num">${JSON.parse(l.serials).join(' · ')}</div>` : ''}</td>
          <td class="num">${l.qty}</td><td class="end money num">${money(l.unit_cost)}</td></tr>`)}</tbody></table></div>` });
    }));
  } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}

async function suppliers(body, params) {
  put(body, skeleton(4));
  try {
    const rows = await api.get('/api/suppliers');
    const owe = rows.reduce((a, r) => a + r.balance, 0);
    put(body, html`<div class="stack enter"><div class="row between wrap"><div class="card flat kpi"><span class="label">${t('home.weOwe')}</span><span class="value num" data-count="${owe}" data-fmt="money">${money(owe, { whole: true })}</span></div>
      <button class="btn primary" data-new>${icon('plus')}${t('receive.newSupplier')}</button></div>
      ${rows.length ? html`<div class="card pad-0"><table class="t"><thead><tr><th>${t('f.name')}</th><th>${t('f.phone')}</th><th class="hide-phone">${t('receive.lastPurchase')}</th><th class="end">${t('receive.weOwe')}</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr class="click" data-id="${r.id}"><td class="name">${r.name}</td><td class="num">${r.phone}</td><td class="hide-phone num">${r.last_purchase ? date(r.last_purchase) : '—'}</td>
      <td class="end">${r.balance ? html`<span class="badge warn money">${money(r.balance)}</span>` : '—'}</td></tr>`)}</tbody></table></div>` : html`<div class="card">${empty('users', t('receive.noSuppliers'), '')}</div>`}</div>`);
    $('[data-new]', body).addEventListener('click', () => editSupplier(null, () => suppliers(body, params)));
    $$('tr[data-id]', body).forEach((tr) => tr.addEventListener('click', () => supplierFile(tr.dataset.id, () => suppliers(body, params))));
    settle(body);
  } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}

async function supplierFile(id, onChange) {
  const s = await api.get('/api/supplier', { id }).catch((e) => toast(errorText(e), 'bad'));
  if (!s) return;
  open({
    title: s.name, kind: 'panel',
    body: html`<div class="card ${s.balance ? 'ink-card' : 'flat'} kpi"><span class="label">${t('receive.weOwe')}</span><span class="value num">${money(s.balance)}</span></div>
      <div class="card flat"><div class="card-head"><h2>${t('cust.statement')}</h2></div><div class="timeline">${s.entries.map((e) => html`<div class="ev"><span class="badge ${e.amount < 0 ? 'ok' : 'warn'}">${t('ap.' + e.kind)}</span>
        <span class="small num">${date(e.at, true)} · ${e.note}</span>${moneyH(e.amount, { sign: true })}</div>`)}</div></div>`,
    foot: html`<button class="btn" data-edit>${icon('edit')}${t('act.edit')}</button>${s.balance && can('suppliers.pay') ? html`<button class="btn volt" data-pay>${icon('cash')}${t('receive.pay')}</button>` : ''}`,
    mount(box, close) {
      $('[data-edit]', box).addEventListener('click', () => { close(); editSupplier(s, onChange); });
      $('[data-pay]', box)?.addEventListener('click', () => {
        close();
        const idem = key();
        open({ title: t('receive.pay') + ' — ' + s.name,
          body: html`<div class="field"><label for="pa">${t('f.amount')}</label><input id="pa" class="input big money-in" inputmode="decimal" value="${s.balance / 100}" autofocus></div>
            <div class="field"><span class="label">${t('receive.payFrom')}</span>${seg('src', [['safe', t('cash.safe')], ['drawer', t('cash.drawer')], ['bank', t('cash.bank')]], 'safe')}</div>
            <div class="field"><label for="pn">${t('f.note')}</label><input id="pn" class="input"></div>`,
          foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('receive.pay')}</button>`,
          mount(b2, close2) {
            let src = 'safe';
            bindSeg(b2, 'src', (v) => { src = v; });
            $('[data-ok]', b2).addEventListener('click', async (e) => {
              const amount = parseMoney($('#pa', b2).value);
              if (!amount) { shake($('#pa', b2)); return; }
              if (await run(api.post('/api/supplier/pay', { idem_key: idem, supplier_id: s.id, amount, source: src, note: $('#pn', b2).value }), t('saved'), e.currentTarget)) { close2(); onChange && onChange(); }
            });
          } });
      });
    },
  });
}

function editSupplier(s, onDone) {
  open({
    title: s ? s.name : t('receive.newSupplier'),
    body: html`<div class="form"><div class="field"><label for="sn">${t('f.name')}</label><input id="sn" class="input" value="${s?.name || ''}" autofocus></div>
      <div class="field"><label for="sp">${t('f.phone')}</label><input id="sp" class="input num" value="${s?.phone || ''}"></div>
      <div class="field"><label for="so">${t('f.note')}</label><textarea id="so" class="input">${s?.notes || ''}</textarea></div></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const name = $('#sn', box).value.trim();
        if (!name) { shake($('#sn', box)); return; }
        const r = await run(api.post('/api/supplier/save', { id: s?.id, name, phone: $('#sp', box).value, notes: $('#so', box).value }), t('saved'), e.currentTarget);
        if (r) { close(); onDone && onDone(r.id, name); }
      });
    },
  });
}
