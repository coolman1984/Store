// Reports: a period's sales, profit, payment methods, what sold, who sold, money owed both ways, the year's turnover
// (what the simplified tax regime of law 6/2025 is measured on), stock value and money sleeping on the shelf.
import { api } from '../api.js';
import { can, settle } from '../app.js';
import { t } from '../i18n.js';
import { areaChart } from './home.js';
import { $, raw, html, put, icon, money, num, empty, skeleton, errorText, today, addDays, seg, bindSeg, download } from '../ui.js';
import { printHTML } from '../print.js';

export default async function view(page) {
  let range = 'month';
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.reports')}</h1><p>${t('reports.sub')}</p></div>
    <div class="actions"><button class="btn" data-print>${icon('print')}${t('reports.print')}</button><button class="btn" data-csv>${icon('download')}${t('reports.csv')}</button></div></div>
    <div class="toolbar">${seg('range', [['today', t('sales.today')], ['week', t('sales.week')], ['month', t('sales.month')], ['quarter', t('reports.quarter')]], range)}</div>
    <div id="r-body">${skeleton(8)}</div>`);
  let data;
  const load = async () => {
    const box = $('#r-body', page);
    const d = today();
    const from = { today: d, week: addDays(d, -6), month: addDays(d, -29), quarter: addDays(d, -89) }[range];
    try {
      data = await api.get('/api/reports', { from, to: d, days: range === 'quarter' ? 90 : range === 'today' ? 14 : range === 'week' ? 14 : 30 });
    } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
    const s = data.summary, b = data.balances, y = data.year;
    const bars = (rows, key = 'sales') => {
      const max = Math.max(1, ...rows.map((r) => r[key]));
      return rows.length ? html`<div class="bars">${rows.slice(0, 10).map((r) => html`<div class="bar"><span class="ellipsis">${r.name}</span>
        <span class="track"><span class="fill" data-w="${Math.max(2, Math.round(r[key] / max * 100))}%"></span></span>
        <span class="money num">${money(r[key])}${r.profit !== undefined ? html` <span class="xs faint">${t('reports.profitShort', { m: money(r.profit) })}</span>` : ''}</span></div>`)}</div>`
        : html`<p class="muted small">${t('reports.noData')}</p>`;
    };
    put(box, html`<div class="stack enter">
      <div class="grid kpis">
        ${kpi('receipt', t('reports.net'), s.net)}${kpi('cart', t('home.invoices'), s.sales_count, false)}
        ${s.gross_profit !== undefined ? kpi('chart', t('home.profit'), s.gross_profit, true, `${s.margin_pct}%`) : ''}
        ${kpi('percent', t('reports.discounts'), s.discount)}${kpi('return', t('reports.returns'), s.returns)}${kpi('wallet', t('reports.expenses'), s.expenses)}
      </div>
      <div class="card ink-card"><div class="row between"><h2>${t('reports.daily')}</h2><span class="muted small">${t('reports.days', { n: data.series.length })}</span></div>${areaChart(data.series)}</div>
      <div class="grid">
        <div class="card"><div class="card-head"><h2>${t('reports.byMethod')}</h2></div>${Object.keys(s.methods).length ? html`<div class="list">${Object.entries(s.methods).map(([m, v]) =>
          html`<div class="li"><span class="grow">${t('pay.' + m)}</span><b class="money num">${money(v)}</b></div>`)}</div>` : html`<p class="muted small">${t('reports.noData')}</p>`}</div>
        <div class="card"><div class="card-head"><h2>${t('reports.byCategory')}</h2></div>${bars(data.by_category)}</div>
        <div class="card"><div class="card-head"><h2>${t('reports.byBrand')}</h2></div>${bars(data.by_brand)}</div>
        <div class="card"><div class="card-head"><h2>${t('reports.byUser')}</h2></div>${bars(data.by_user)}</div>
      </div>
      <div class="card"><div class="card-head"><h2>${t('reports.topProducts')}</h2></div>${data.by_product.length ? html`<div class="table-wrap"><table class="t"><thead><tr><th>${t('f.product')}</th>
        <th class="end">${t('f.qty')}</th><th class="end">${t('reports.sales')}</th>${data.by_product[0].profit !== undefined ? html`<th class="end">${t('home.profit')}</th>` : ''}</tr></thead>
        <tbody>${data.by_product.map((r) => html`<tr><td>${r.name}</td><td class="end num">${num(r.qty)}</td><td class="end money num">${money(r.sales)}</td>
        ${r.profit !== undefined ? html`<td class="end money num">${money(r.profit)}</td>` : ''}</tr>`)}</tbody></table></div>` : html`<p class="muted small">${t('reports.noData')}</p>`}</div>
      <div class="grid">
        <div class="card"><div class="card-head"><h2>${t('reports.balances')}</h2></div>
          <div class="stat-line"><span>${t('home.customersOwe')}</span><b class="money num">${money(b.customers_owe)}</b></div>
          <div class="stat-line"><span>${t('home.weOwe')}</span><b class="money num">${money(b.shop_owes_suppliers)}</b></div>
          <div class="stat-line"><span>${t('home.financeDue')}</span><b class="money num">${money(b.finance_due)}</b></div>
          <div class="stat-line"><span>${t('home.safe')}</span><b class="money num">${money(b.safe)}</b></div>
          <div class="stat-line"><span>${t('reports.drawers')}</span><b class="money num">${money(b.drawers)}</b></div>
          ${data.stock_value !== undefined ? html`<div class="stat-line"><span>${t('stock.value')}</span><b class="money num">${money(data.stock_value)}</b></div>` : ''}</div>
        <div class="card volt-card"><div class="card-head"><h2>${t('reports.year', { y: y.year })}</h2></div><div class="kpi"><span class="value num">${money(y.turnover)}</span>
          <span class="small">${t('reports.yearHint')}</span></div></div>
        ${data.slow ? html`<div class="card"><div class="card-head"><h2>${t('stock.slow')}</h2></div>${data.slow.length ? html`<div class="list">${data.slow.slice(0, 8).map((r) =>
          html`<div class="li"><span class="grow ellipsis">${r.name}</span><span class="badge num">${num(r.on_hand)}</span><span class="money num">${money(r.value)}</span></div>`)}</div>` : html`<p class="muted small">${t('stock.noSlow')}</p>`}</div>` : ''}
      </div></div>`);
    settle(box);
  };
  bindSeg(page, 'range', (v) => { range = v; load(); });
  $('[data-print]', page).addEventListener('click', () => {
    if (!data) return;
    const s = data.summary;
    printHTML(html`<h2>${t('nav.reports')} ${s.from} → ${s.to}</h2><table><tbody>
      <tr><th>${t('reports.net')}</th><td>${money(s.net)}</td></tr><tr><th>${t('home.invoices')}</th><td>${s.sales_count}</td></tr>
      ${s.gross_profit !== undefined ? html`<tr><th>${t('home.profit')}</th><td>${money(s.gross_profit)} (${s.margin_pct}%)</td></tr>` : ''}
      <tr><th>${t('reports.discounts')}</th><td>${money(s.discount)}</td></tr><tr><th>${t('reports.returns')}</th><td>${money(s.returns)}</td></tr>
      <tr><th>${t('reports.expenses')}</th><td>${money(s.expenses)}</td></tr></tbody></table>
      <h3>${t('reports.topProducts')}</h3><table><tbody>${data.by_product.map((r) => html`<tr><td>${r.name}</td><td>${num(r.qty)}</td><td>${money(r.sales)}</td></tr>`)}</tbody></table>`, 'a4');
  });
  $('[data-csv]', page).addEventListener('click', () => {
    if (!data) return;
    const rows = [['day', 'sales', ...(can('cost.view') ? ['profit'] : [])], ...data.series.map((d) => [d.day, d.sales / 100, ...(d.profit !== undefined ? [d.profit / 100] : [])])];
    download(`report-${today()}.csv`, new Blob(['﻿' + rows.map((r) => r.join(',')).join('\n')], { type: 'text/csv' }));
  });
  load();
}

function kpi(ic, label, value, isMoney = true, extra) {
  return html`<div class="card flat spot kpi"><span class="label">${icon(ic)}${label}</span>
    <span class="value num" data-count="${value}" ${isMoney ? raw('data-fmt="money"') : ''}>${isMoney ? money(value, { whole: true }) : num(value)}</span>${extra ? html`<span class="small muted">${extra}</span>` : ''}</div>`;
}
