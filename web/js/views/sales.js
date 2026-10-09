// Sales: today's invoices, any day, search by number / customer / serial; the sale file with returns; warranty look-up.
import { api, key } from '../api.js';
import { S, can, go, settle } from '../app.js';
import { signal } from '../guide.js';
import { t } from '../i18n.js';
import { printReceipt } from '../print.js';
import {
  CUR, $, $$, html, put, icon, money, moneyH, num, date, time, open, empty, skeleton, errorText, showError, withApproval, toast, today, addDays, parseQty, seg, bindSeg,
} from '../ui.js';
import { shake } from '../motion.js';

export default async function view(page, params) {
  const tab = params.tab === 'warranty' ? 'warranty' : 'list';
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.sales')}</h1><p>${t('sales.sub')}</p></div>
    <div class="actions">${can('pos.sell') ? html`<a class="btn accent" href="#/pos">${icon('cart')}${t('home.newSale')}</a>` : ''}</div></div>
    <nav class="tabs" data-lab-scroll aria-label="${t('nav.sections')}"><a href="#/sales" ${tab === 'list' ? CUR : ''}>${icon('receipt')}${t('sales.tab.list')}</a>
    <a href="#/sales?tab=warranty" ${tab === 'warranty' ? CUR : ''}>${icon('shield')}${t('sales.tab.warranty')}</a></nav>
    <div id="sales-body"></div>`);
  const body = $('#sales-body', page);
  if (tab === 'warranty') return warrantyTab(body, params);
  let range = params.q ? 'search' : 'today', q = params.q || '';
  put(body, html`<div class="toolbar">${seg('range', [['today', t('sales.today')], ['yesterday', t('sales.yesterday')], ['week', t('sales.week')], ['month', t('sales.month')]], range)}
    <input class="input" id="s-q" placeholder="${t('sales.search')}" value="${q}" autocomplete="off"></div><div id="s-list"></div>`);
  const load = async () => {
    const box = $('#s-list', body);
    put(box, skeleton(5));
    const d = today();
    const from = { today: d, yesterday: addDays(d, -1), week: addDays(d, -6), month: addDays(d, -29) }[range] || d;
    const to = range === 'yesterday' ? addDays(d, -1) : d;
    try {
      const rows = await api.get('/api/sales', q ? { q } : { from, to });
      if (!rows.length) { put(box, html`<div class="card">${empty('receipt', t('sales.none'), q ? t('sales.noneSearch') : t('sales.noneHint'))}</div>`); return; }
      const tot = rows.reduce((a, r) => a + r.total, 0);
      put(box, html`<div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.number')}</th><th>${t('f.time')}</th>
        <th>${t('f.customer')}</th><th class="hide-phone">${t('sales.by')}</th><th class="hide-phone">${t('pos.method')}</th><th class="end">${t('pos.total')}</th></tr></thead>
        <tbody>${rows.map((r) => html`<tr class="click" data-id="${r.id}"><td class="num name">${r.number}${r.returns ? html` <span class="badge warn">${t('sales.returned')}</span>` : ''}</td>
          <td class="num">${range === 'today' && !q ? time(r.at) : date(r.at, true)}</td><td>${r.customer || html`<span class="faint">${t('pos.walkIn')}</span>`}</td>
          <td class="hide-phone">${r.by_name}</td><td class="hide-phone">${(r.methods || '').split(',').filter(Boolean).map((m) => html`<span class="badge">${t('pay.' + m)}</span> `)}</td>
          <td class="end money num">${money(r.total)}</td></tr>`)}</tbody>
        <tfoot><tr><td colspan="5" class="muted">${t('sales.count', { n: rows.length })}</td><td class="end money num"><b>${money(tot)}</b></td></tr></tfoot></table></div></div>`);
      $$('tr[data-id]', box).forEach((tr) => tr.addEventListener('click', () => saleFile(tr.dataset.id, load)));
      settle(box);
    } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
  };
  bindSeg(body, 'range', (v) => { range = v; q = ''; $('#s-q', body).value = ''; load(); });
  let timer;
  $('#s-q', body).addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { q = e.target.value.trim(); load(); }, 250); });
  load();
  if (params.id) saleFile(params.id, load);
}

export async function saleFile(id, onChange) {
  let s;
  try { s = await api.get('/api/sale', { id }); } catch (e) { toast(errorText(e), 'bad'); return; }
  const returnable = s.lines.some((l) => l.qty - l.returned > 0);
  open({
    title: html`${t('sales.invoice')} <span class="num">${s.number}</span>`,
    kind: 'panel',
    body: html`<div class="row wrap small muted">${icon('clock')}${date(s.at, true)} · ${s.by_name}${s.approved_name ? html` · <span class="badge warn">${t('sales.approvedBy', { n: s.approved_name })}</span>` : ''}</div>
      ${s.customer ? html`<a class="chip" href="#/customers?id=${s.customer_id}">${icon('user')}${s.customer} <span class="num">${s.customer_phone || ''}</span></a>` : ''}
      <div class="card flat pad-0"><table class="t"><tbody>${s.lines.map((l) => html`<tr><td><b>${l.name}</b>${l.serial ? html`<div class="small num muted">${icon('shield')} ${l.serial}${l.warranty_until ? ' · ' + t('print.until') + ' ' + date(l.warranty_until) : ''}</div>` : ''}
        ${l.returned ? html`<div><span class="badge warn">${t('sales.returnedN', { n: num(l.returned) })}</span></div>` : ''}</td>
        <td class="num">${num(l.qty)} × ${money(l.unit_price)}</td><td class="end money num">${money(l.line_total)}</td></tr>`)}</tbody></table></div>
      <div class="card flat">
        <div class="stat-line"><span>${t('pos.subtotal')}</span>${moneyH(s.subtotal)}</div>
        ${s.discount ? html`<div class="stat-line"><span>${t('pos.discount')}</span><span class="money num bad-ink">−${money(s.discount)}</span></div>` : ''}
        ${s.fee ? html`<div class="stat-line"><span>${t('pos.fee')}</span>${moneyH(s.fee)}</div>` : ''}
        <div class="stat-line"><b>${t('pos.total')}</b><b>${moneyH(s.total)}</b></div>
        ${s.tenders.map((x) => html`<div class="stat-line small"><span>${t('pay.' + x.method)}${x.provider ? ' · ' + x.provider : ''}</span>${moneyH(x.amount)}</div>`)}
        ${s.cost_total !== undefined ? html`<div class="stat-line small muted"><span>${t('sales.profit')}</span>${moneyH(s.total - s.cost_total)}</div>` : ''}
      </div>
      ${s.plan ? html`<div class="card flat"><div class="card-head"><h2>${t('cust.plan')} <span class="num">${s.plan.number}</span></h2>
        <span class="badge ${s.plan.due_now ? 'bad' : 'ok'}">${s.plan.due_now ? t('cust.dueNow', { m: money(s.plan.due_now) }) : t('cust.onTrack')}</span></div>${schedule(s.plan)}</div>` : ''}
      ${s.returns.length ? html`<div class="card flat"><div class="card-head"><h2>${t('sales.returns')}</h2></div>${s.returns.map((r) =>
        html`<div class="stat-line small"><span><b class="num">${r.number}</b> · ${date(r.at, true)} · ${r.reason}</span>${moneyH(-r.total)}</div>`)}</div>` : ''}
      ${s.days_since <= (S.lookups?.settings?.return_days ?? 14) ? html`<div class="tip ok">${icon('info')}<div>${t('sales.inWindow', { d: s.days_since, r: S.lookups?.settings?.return_days ?? 14 })}</div></div>`
        : s.days_since <= (S.lookups?.settings?.defect_days ?? 30) ? html`<div class="tip warn">${icon('info')}<div>${t('sales.defectWindow', { d: s.days_since, r: S.lookups?.settings?.defect_days ?? 30 })}</div></div>` : ''}`,
    foot: html`<button class="btn" data-print>${icon('print')}${t('pos.print')}</button>
      ${returnable && (can('sales.return') || can('pos.sell')) ? html`<button class="btn" data-return data-guide="sales.return">${icon('return')}${t('sales.return')}</button>` : ''}`,
    mount(box, close) {
      $('[data-print]', box).addEventListener('click', () => printReceipt(s));
      $('[data-return]', box)?.addEventListener('click', () => { close(); returnDialog(s, onChange); });
    },
  });
}

export function schedule(plan) {
  return html`<div class="sched">${plan.rows.map((r) => html`<div class="${r.state}"><span class="faint">#${r.n} · <span class="num">${date(r.due)}</span></span>
    <b class="num">${money(r.amount)}</b><span class="xs">${t('plan.' + r.state)}${r.paid && r.paid < r.amount ? ' · ' + money(r.paid) : ''}</span></div>`)}</div>`;
}

function returnDialog(s, onChange) {
  const idem = key();
  const methods = s.refund_methods || ['cash'];
  const paidBy = s.tenders.map((x) => x.method);
  const want = paidBy.includes('installment') || paidBy.includes('account') ? 'account' : paidBy.includes('cash') ? 'cash' : (paidBy[0] || 'cash');
  const def = methods.includes(want) ? want : methods[0];
  open({
    title: t('sales.returnTitle', { n: s.number }),
    wide: true,
    body: html`<p class="muted small">${t('sales.returnHint')}</p>
      <div class="card flat pad-0"><table class="t"><thead><tr><th>${t('f.product')}</th><th>${t('sales.canReturn')}</th><th>${t('f.qty')}</th><th>${t('sales.condition')}</th></tr></thead>
      <tbody>${s.lines.filter((l) => l.qty - l.returned > 0).map((l) => html`<tr><td>${l.name}${l.serial ? html`<div class="small num muted">${l.serial}</div>` : ''}</td>
        <td class="num">${num(l.qty - l.returned)}</td><td><input class="input q-in num" data-rq="${l.id}" data-max="${l.qty - l.returned}" value="0" inputmode="decimal"></td>
        <td><select class="input" data-rc="${l.id}"><option value="good">${t('sales.good')}</option><option value="damaged">${t('sales.damaged')}</option></select></td></tr>`)}</tbody></table></div>
      ${methods.length > 1 ? html`<div class="field"><span class="label">${t('sales.refundBy')}</span>${seg('refund', methods.map((m) => [m, t('pay.' + m)]), def)}</div>` : ''}
      <div class="field"><label for="r-why">${t('f.reason')}</label><textarea id="r-why" class="input" data-guide="return.reason" placeholder="${t('sales.reasonHint')}"></textarea></div>
      <p class="err small" id="r-err" role="alert"></p>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok data-guide="return.save">${icon('return')}${t('sales.doReturn')}</button>`,
    mount(box, close) {
      let refund = def;
      bindSeg(box, 'refund', (v) => { refund = v; });
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const lines = [];
        for (const inp of $$('[data-rq]', box)) {
          const v = parseQty(inp.value || '0');
          if (v === null || v > +inp.dataset.max) { shake(inp); return; }
          if (v > 0) lines.push({ sale_line_id: inp.dataset.rq, qty: v, condition: $(`[data-rc="${inp.dataset.rq}"]`, box).value });
        }
        if (!lines.length) { $('#r-err', box).textContent = t('sales.pickLines'); return; }
        const reason = $('#r-why', box).value.trim();
        if (reason.length < 3) { $('#r-why', box).setAttribute('aria-invalid', 'true'); $('#r-why', box).focus(); return; }
        const btn = e.currentTarget;
        btn.setAttribute('aria-busy', 'true');
        try {
          const r = await withApproval((approval) => api.post('/api/return', { idem_key: idem, sale_id: s.id, lines, reason, refund_method: refund, approval }));
          close();
          signal('return.done');
          toast(t('sales.returnDone', { n: r.number, m: money(r.total) }));
          onChange && onChange();
        } catch (err) { if (!err.cancelled) showError($('#r-err', box), err); } finally { btn.removeAttribute('aria-busy'); }
      });
    },
  });
}

function warrantyTab(body, params) {
  put(body, html`<div class="card"><div class="stack"><h2>${t('sales.warrantyTitle')}</h2><p class="muted">${t('sales.warrantyHint')}</p>
    <div class="row wrap"><input class="input big num grow" id="w-q" placeholder="${t('pos.serialScan')}" value="${params.serial || ''}" autocomplete="off" autofocus>
    <button class="btn primary lg" data-find>${icon('search')}${t('act.search')}</button></div></div></div><div id="w-out" class="stack"></div>`);
  const find = async () => {
    const q = $('#w-q', body).value.trim();
    if (!q) return;
    const out = $('#w-out', body);
    put(out, skeleton(3));
    try {
      const w = await api.get('/api/warranty', { serial: q });
      const ok = w.warranty_days_left !== null && w.warranty_days_left !== undefined && w.warranty_days_left >= 0;
      put(out, html`<div class="card ${w.sale_id ? (ok ? 'accent-card' : '') : ''}">
        <div class="row between wrap"><h2>${w.product || ''}</h2><span class="badge num">${w.serial}</span></div>
        ${w.sale_id ? html`<div class="grid kpis">
          <div class="kpi"><span class="label">${t('sales.soldOn')}</span><span class="value num">${date(w.sold_at)}</span></div>
          <div class="kpi"><span class="label">${t('f.customer')}</span><span class="value">${w.customer_hidden ? '—' : (w.customer || t('pos.walkIn'))}</span></div>
          <div class="kpi"><span class="label">${t('sales.warrantyLeft')}</span><span class="value">${w.warranty_until ? (ok ? t('sales.daysLeft', { n: w.warranty_days_left }) : t('sales.warrantyOver')) : t('sales.noWarranty')}</span></div></div>
          <div class="row wrap"><button class="btn" data-sale="${w.sale_id}">${icon('receipt')}${t('sales.openInvoice')} <span class="num">${w.sale_number}</span></button></div>`
          : html`<p>${w.state?.in_stock ? t('sales.inStockNotSold') : t('sales.notSoldHere')}</p>`}</div>`);
      $('[data-sale]', out)?.addEventListener('click', (e) => saleFile(e.currentTarget.dataset.sale));
      settle(out);
    } catch (e) { put(out, html`<div class="card">${empty('shield', t('sales.serialUnknown'), errorText(e))}</div>`); }
  };
  $('[data-find]', body).addEventListener('click', find);
  $('#w-q', body).addEventListener('keydown', (e) => { if (e.key === 'Enter') find(); });
  if (params.serial) find();
}

export const _go = go;
