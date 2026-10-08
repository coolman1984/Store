// Customers and shop instalments: who owes what, who is late today, collect a payment, remind on WhatsApp (one by one).
import { api, key } from '../api.js';
import { S, can, settle } from '../app.js';
import { t } from '../i18n.js';
import { shake } from '../motion.js';
import { schedule, saleFile } from './sales.js';
import {
  CUR, $, $$, html, put, icon, money, moneyH, date, open, empty, skeleton, errorText, toast, parseMoney, whatsapp, confirm, run, seg, bindSeg,
} from '../ui.js';

export default async function view(page, params) {
  const tab = ['due', 'owing'].includes(params.tab) ? params.tab : 'all';
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.customers')}</h1><p>${t('cust.sub')}</p></div>
    <div class="actions">${can('customers.edit') ? html`<button class="btn primary" data-new>${icon('plus')}${t('customers.new')}</button>` : ''}</div></div>
    <nav class="tabs" data-lab-scroll aria-label="${t('nav.sections')}"><a href="#/customers" ${tab === 'all' ? CUR : ''}>${icon('users')}${t('cust.tab.all')}</a>
      <a href="#/customers?tab=owing" ${tab === 'owing' ? CUR : ''}>${icon('wallet')}${t('cust.tab.owing')}</a>
      <a href="#/customers?tab=due" ${tab === 'due' ? CUR : ''}>${icon('instal')}${t('cust.tab.due')}</a></nav>
    <div id="c-body"></div>`);
  $('[data-new]', page)?.addEventListener('click', () => editCustomer(null, () => view(page, params)));
  const body = $('#c-body', page);
  if (tab === 'due') return dueTab(body);
  put(body, html`<div class="toolbar"><input class="input" id="c-q" placeholder="${t('customers.search')}" autocomplete="off"></div><div id="c-list">${skeleton(5)}</div>`);
  const load = async (q = '') => {
    const box = $('#c-list', body);
    try {
      const rows = await api.get('/api/customers', { q, only: tab === 'owing' ? 'owing' : 'all' });
      if (!rows.length) { put(box, html`<div class="card">${empty('users', q ? t('cust.noneSearch') : t('cust.none'), t('cust.noneHint'))}</div>`); return; }
      const owe = rows.reduce((a, r) => a + Math.max(0, r.balance), 0);
      put(box, html`<div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.name')}</th><th>${t('f.phone')}</th>
        <th class="hide-phone">${t('cust.lastSale')}</th><th class="end">${t('cust.balance')}</th></tr></thead><tbody>${rows.map((r) => html`<tr class="click" data-id="${r.id}">
        <td class="name">${r.name}</td><td class="num">${r.phone}</td><td class="hide-phone num">${r.last_sale ? date(r.last_sale) : '—'}</td>
        <td class="end">${r.balance > 0 ? html`<span class="badge warn money">${money(r.balance)}</span>` : html`<span class="faint">—</span>`}</td></tr>`)}</tbody>
        <tfoot><tr><td colspan="3" class="muted">${t('cust.count', { n: rows.length })}</td><td class="end money num"><b>${money(owe)}</b></td></tr></tfoot></table></div></div>`);
      $$('tr[data-id]', box).forEach((tr) => tr.addEventListener('click', () => customerFile(tr.dataset.id, () => load($('#c-q', body).value))));
    } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
  };
  let timer;
  $('#c-q', body).addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => load(e.target.value.trim()), 200); });
  load();
  if (params.id) customerFile(params.id, () => load());
}

async function dueTab(body) {
  put(body, skeleton(5));
  let d;
  try { d = await api.get('/api/instalments'); } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  const shop = S.lookups?.settings?.shop_name || '';
  const total = d.due.reduce((a, r) => a + r.due_now, 0);
  put(body, html`<div class="stack enter">
    <div class="grid kpis"><div class="card flat kpi"><span class="label">${icon('alert')}${t('cust.lateCount')}</span><span class="value num" data-count="${d.due.length}">${d.due.length}</span></div>
      <div class="card flat kpi"><span class="label">${icon('wallet')}${t('cust.lateTotal')}</span><span class="value num" data-count="${total}" data-fmt="money">${money(total, { whole: true })}</span></div>
      <div class="card flat kpi"><span class="label">${icon('calendar')}${t('cust.next7')}</span><span class="value num">${d.upcoming.length}</span></div></div>
    <div class="card"><div class="card-head"><h2>${t('cust.dueList')}</h2></div>${d.due.length ? html`<div class="list">${d.due.map((x) => html`<div class="li">
      <span class="avatar">${icon('instal')}</span><button class="link-btn grow" data-open="${x.customer_id}"><b>${x.customer}</b></button>
      <span class="badge ${x.late_days > 30 ? 'bad' : 'warn'}">${x.late_days ? t('cust.lateDays', { n: x.late_days }) : t('cust.dueToday')}</span>
      <b class="money num">${money(x.due_now)}</b>
      ${x.phone ? html`<a class="icon-btn" target="_blank" rel="noopener" aria-label="WhatsApp" href="${whatsapp(x.phone, t('cust.remind', { name: x.customer, amount: money(x.due_now), shop }))}">${icon('message')}</a>` : ''}
      <button class="btn sm primary" data-collect="${x.customer_id}" data-plan="${x.plan_id}" data-amount="${x.due_now}">${t('cust.collect')}</button></div>`)}</div>`
      : empty('check-circle', t('cust.noLate'), t('cust.noLateHint'))}</div>
    ${d.upcoming.length ? html`<div class="card"><div class="card-head"><h2>${t('cust.upcoming')}</h2></div><div class="list">${d.upcoming.map((x) => html`<div class="li">
      <span class="grow"><b>${x.customer}</b> <span class="small muted num">${date(x.due)}</span></span><b class="money num">${money(x.amount)}</b>
      ${x.phone ? html`<a class="icon-btn" target="_blank" rel="noopener" aria-label="WhatsApp" href="${whatsapp(x.phone, t('cust.remindSoon', { name: x.customer, amount: money(x.amount), day: date(x.due), shop }))}">${icon('message')}</a>` : ''}</div>`)}</div></div>` : ''}
    <p class="small faint">${t('cust.waNote')}</p></div>`);
  $$('[data-open]', body).forEach((b) => b.addEventListener('click', () => customerFile(b.dataset.open, () => dueTab(body))));
  $$('[data-collect]', body).forEach((b) => b.addEventListener('click', () => collect(b.dataset.collect, b.dataset.plan, +b.dataset.amount, () => dueTab(body))));
  settle(body);
}

export async function customerFile(id, onChange) {
  let c;
  try { c = await api.get('/api/customer', { id }); } catch (e) { toast(errorText(e), 'bad'); return; }
  const shop = S.lookups?.settings?.shop_name || '';
  const kindLabel = (k) => t('ar.' + k);
  open({
    title: c.name,
    kind: 'panel',
    body: html`<div class="row wrap">${c.phone ? html`<a class="chip num" href="tel:${c.phone}">${icon('phone')}${c.phone}</a>` : ''}
        ${c.address ? html`<span class="chip">${icon('pin')}${c.address}</span>` : ''}${c.national_id ? html`<span class="chip">${icon('lock')}${c.national_id}</span>` : ''}</div>
      <div class="card ${c.balance > 0 ? 'ink-card' : 'flat'}"><div class="kpi"><span class="label">${t('cust.balance')}</span>
        <span class="value num">${money(c.balance)}</span>${c.credit_limit ? html`<span class="small muted">${t('pos.creditLimit', { l: money(c.credit_limit) })}</span>` : ''}</div>
        ${c.balance > 0 && can('installments.collect') ? html`<div class="row wrap"><button class="btn volt" data-collect>${icon('cash')}${t('cust.collect')}</button>
          ${c.phone ? html`<a class="btn" target="_blank" rel="noopener" href="${whatsapp(c.phone, t('cust.remind', { name: c.name, amount: money(c.balance), shop }))}">${icon('message')}${t('cust.remindBtn')}</a>` : ''}</div>` : ''}</div>
      ${c.plans.map((p) => html`<div class="card flat"><div class="card-head"><h2>${t('cust.plan')} <span class="num">${p.number}</span></h2>
        <span class="badge ${p.due_now ? 'bad' : p.remaining ? 'ok' : ''}">${p.remaining ? (p.due_now ? t('cust.dueNow', { m: money(p.due_now) }) : t('cust.onTrack')) : t('cust.planDone')}</span></div>
        <div class="row wrap small muted"><span>${t('cust.financed')}: ${money(p.financed)}</span><span>· ${t('pos.monthly')}: ${money(p.monthly)}</span>
        <span>· ${t('cust.remaining')}: <b>${money(p.remaining)}</b></span>${p.guarantor_name ? html`<span>· ${t('pos.guarantor')}: ${p.guarantor_name} <span class="num">${p.guarantor_phone}</span></span>` : ''}</div>
        ${schedule(p)}${p.remaining && can('installments.collect') ? html`<button class="btn sm" data-plan="${p.id}" data-amount="${p.due_now || p.next?.amount - (p.next?.paid || 0) || p.monthly}">${t('cust.collectPlan')}</button>` : ''}
        <button class="btn sm ghost" data-sale="${p.sale_id}">${icon('receipt')}${t('sales.openInvoice')}</button></div>`)}
      <div class="card flat"><div class="card-head"><h2>${t('cust.statement')}</h2></div>${c.entries.length ? html`<div class="timeline">${c.entries.map((e) => html`<div class="ev">
        <span class="badge ${e.amount < 0 ? 'ok' : 'warn'}">${kindLabel(e.kind)}</span><span class="small"><span class="num">${date(e.at, true)}</span> · ${e.note || e.ref_id} · ${e.by_name || ''}
        ${e.reversed ? html`<span class="badge bad">${t('state.reversed')}</span>` : ''}</span>
        <span class="row"><span class="money num">${money(e.amount, { sign: true })}</span>${e.kind === 'payment' && !e.reversed && can('shifts.manage') ? html`<button class="icon-btn sm" data-rev="${e.id}" aria-label="${t('act.reverse')}">${icon('return')}</button>` : ''}</span></div>`)}</div>`
        : html`<p class="muted small">${t('cust.noEntries')}</p>`}</div>`,
    foot: html`${can('customers.edit') ? html`<button class="btn" data-edit>${icon('edit')}${t('act.edit')}</button>` : ''}`,
    mount(box, close) {
      const refresh = () => { close(); customerFile(id, onChange); onChange && onChange(); };
      $('[data-collect]', box)?.addEventListener('click', () => collect(c.id, null, c.balance, refresh));
      $$('[data-plan]', box).forEach((b) => b.addEventListener('click', () => collect(c.id, b.dataset.plan, +b.dataset.amount, refresh)));
      $$('[data-sale]', box).forEach((b) => b.addEventListener('click', () => saleFile(b.dataset.sale)));
      $('[data-edit]', box)?.addEventListener('click', () => { close(); editCustomer(c, () => customerFile(id, onChange)); });
      $$('[data-rev]', box).forEach((b) => b.addEventListener('click', async () => {
        const why = await confirm({ title: t('cust.reverseTitle'), text: t('cust.reverseText'), ok: t('act.reverse'), danger: true, reason: true });
        if (why && await run(api.post('/api/collect/reverse', { id: b.dataset.rev, reason: why }), t('state.reversed'))) refresh();
      }));
    },
  });
}

function collect(customerId, planId, suggested, onDone) {
  const idem = key();
  open({
    title: t('cust.collect'),
    body: html`<div class="field"><label for="amt">${t('f.amount')}</label><input id="amt" class="input big money-in" inputmode="decimal" value="${(suggested || 0) / 100}" autofocus></div>
      <div class="field"><span class="label">${t('pos.method')}</span>${seg('cm', [['cash', t('pay.cash'), 'cash'], ['instapay', t('pay.instapay'), 'qr'], ['wallet', t('pay.wallet'), 'phone'], ['card', t('pay.card'), 'card']], 'cash')}</div>
      <div class="field"><label for="note">${t('f.note')}</label><input id="note" class="input"></div><p class="err small" id="cerr"></p>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn volt" data-ok>${icon('check')}${t('cust.collect')}</button>`,
    mount(box, close) {
      let method = 'cash';
      bindSeg(box, 'cm', (v) => { method = v; });
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const amount = parseMoney($('#amt', box).value);
        if (!amount) { shake($('#amt', box)); return; }
        const r = await run(api.post('/api/collect', { idem_key: idem, customer_id: customerId, plan_id: planId || undefined, amount, method, note: $('#note', box).value }),
          null, e.currentTarget);
        if (r) { close(); toast(t('cust.collected', { m: money(amount), b: money(r.balance) })); onDone && onDone(); }
      });
    },
  });
}

function editCustomer(c, onDone) {
  open({
    title: c ? t('act.edit') + ' — ' + c.name : t('customers.new'),
    body: html`<div class="form"><div class="field"><label for="n">${t('f.name')}</label><input id="n" class="input" value="${c?.name || ''}" autofocus></div>
      <div class="cols"><div class="field"><label for="p">${t('f.phone')}</label><input id="p" class="input num" inputmode="tel" value="${c?.phone || ''}"></div>
      <div class="field"><label for="a">${t('f.address')}</label><input id="a" class="input" value="${c?.address || ''}"></div></div>
      ${can('pos.credit') ? html`<div class="field"><label for="cl">${t('cust.creditLimit')}</label><input id="cl" class="input money-in" inputmode="decimal" value="${c?.credit_limit ? c.credit_limit / 100 : ''}">
        <span class="hint">${t('cust.creditLimitHint')}</span></div>` : ''}
      ${can('customers.private') ? html`<div class="field"><label for="nid">${t('cust.nationalId')}</label><input id="nid" class="input num" inputmode="numeric" maxlength="14" value="${c?.national_id && c.national_id !== '•••' ? c.national_id : ''}">
        <span class="hint">${t('cust.nationalIdHint')}</span></div>` : ''}
      <div class="field"><label for="no">${t('f.note')}</label><textarea id="no" class="input">${c?.notes || ''}</textarea></div></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const body = { id: c?.id, name: $('#n', box).value, phone: $('#p', box).value, address: $('#a', box).value, notes: $('#no', box).value };
        if ($('#cl', box)) body.credit_limit = parseMoney($('#cl', box).value || '0') ?? 0;
        if ($('#nid', box)) body.national_id = $('#nid', box).value;
        if (await run(api.post('/api/customer/save', body), t('saved'), e.currentTarget)) { close(); onDone && onDone(); }
      });
    },
  });
}

export const _m = moneyH;
