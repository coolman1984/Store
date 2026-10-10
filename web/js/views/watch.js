// The owner's eye: everything that deserves a look, newest and most serious first. Marking "seen" changes nothing in the books.
import { api } from '../api.js';
import { settle } from '../app.js';
import { t } from '../i18n.js';
import { saleFile } from './sales.js';
import { $, $$, html, put, icon, money, date, empty, skeleton, errorText, run, open, seg, bindSeg } from '../ui.js';

const ICONS = { discount: 'percent', under_cost: 'alert', after_hours: 'clock', return: 'return', drawer_short: 'cash', drawer_over: 'cash', big_expense: 'wallet',
  reversal: 'refresh', withdraw: 'safe', price_change: 'tag', stock_loss: 'clipboard', negative_stock: 'box', payment_reversed: 'refresh', denied: 'lock' };

export default async function view(page, params) {
  let days = params.days || '7', all = false;
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.watch')}</h1><p>${t('watch.sub')}</p></div></div>
    <div class="toolbar">${seg('days', [['1', t('sales.today')], ['7', t('sales.week')], ['30', t('sales.month')]], days)}
    <label class="check"><input type="checkbox" id="w-all">${t('watch.showSeen')}</label></div><div id="w-list">${skeleton(5)}</div>`);
  const load = async () => {
    const box = $('#w-list', page);
    try {
      const items = await api.get('/api/watch', { days, all: all ? '1' : '' });
      if (!items.length) { put(box, html`<div class="card">${empty('eye', t('watch.none'), t('watch.noneHint'))}</div>`); return; }
      const bad = items.filter((i) => i.level === 'bad').length;
      put(box, html`<div class="stack enter"><div class="grid kpis"><div class="card flat kpi"><span class="label">${icon('alert')}${t('watch.serious')}</span><span class="value num" data-count="${bad}">${bad}</span></div>
        <div class="card flat kpi"><span class="label">${icon('eye')}${t('watch.total')}</span><span class="value num" data-count="${items.length}">${items.length}</span></div></div>
        ${items.map((i) => html`<div class="watch-item ${i.level} ${i.reviewed ? 'reviewed' : ''}"><span class="ic">${icon(ICONS[i.kind] || 'info')}</span>
          <div><b>${t('watch.k.' + i.kind, { ...i.detail, amount: money(i.amount) })}</b>
          <div class="small muted">${date(i.at, true)}${i.who ? ' · ' + i.who : ''}${i.detail.reason ? ' · ' + i.detail.reason : ''}${i.detail.note ? ' · ' + i.detail.note : ''}${i.detail.approver ? ' · ' + t('sales.approvedBy', { n: i.detail.approver }) : ''}
          ${i.reviewed ? html` · <span class="badge ok">${t('watch.seenBy', { note: i.reviewed.note })}</span>` : ''}</div></div>
          <div class="row">${i.amount ? html`<b class="money num">${money(i.amount)}</b>` : ''}${i.ref?.sale ? html`<button class="btn sm ghost" data-sale="${i.ref.sale}" aria-label="${t('sales.openInvoice')}">${icon('receipt')}</button>` : ''}
          ${i.reviewed ? html`<button class="btn sm ghost" data-seen="${i.key}" data-note="${i.reviewed.note}">${icon('edit')}${t('watch.editNote')}</button>`
            : html`<button class="btn sm" data-seen="${i.key}" data-note="">${icon('check')}${t('watch.seen')}</button>`}</div></div>`)}</div>`);
      $$('[data-sale]', box).forEach((b) => b.addEventListener('click', () => saleFile(b.dataset.sale)));
      $$('[data-seen]', box).forEach((b) => b.addEventListener('click', () => open({
        title: t('watch.seen'), body: html`<div class="field"><label for="wn">${t('watch.note')}</label><input id="wn" class="input" value="${b.dataset.note === '✓' ? '' : b.dataset.note}" placeholder="${t('watch.noteHint')}" autofocus></div>`,
        foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
        mount(dlg, close) { $('[data-ok]', dlg).addEventListener('click', async (e) => {
          if (await run(api.post('/api/watch/review', { key: b.dataset.seen, note: $('#wn', dlg).value }), null, e.currentTarget)) { close(); load(); }
        }); },
      })));
      settle(box);
    } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
  };
  bindSeg(page, 'days', (v) => { days = v; load(); });
  $('#w-all', page).addEventListener('change', (e) => { all = e.target.checked; load(); });
  load();
}
