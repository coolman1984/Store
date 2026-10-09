// Today: what happened, what needs doing now. Numbers that drive a decision only.
import { api } from '../api.js';
import { S, can, settle } from '../app.js';
import { t } from '../i18n.js';
import { $, html, put, icon, money, num, empty, skeleton, errorText, whatsapp, date } from '../ui.js';

export function areaChart(series, key = 'sales', { w = 640, h = 200 } = {}) {
  if (!series?.length) return '';
  const max = Math.max(1, ...series.map((d) => d[key]));
  const pad = 14, step = (w - pad * 2) / Math.max(1, series.length - 1);
  const pts = series.map((d, i) => [pad + i * step, h - 26 - (Math.max(0, d[key]) / max) * (h - 46)]);
  const line = pts.map((p, i) => (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1)).join(' ');
  const area = `${line} L ${pts[pts.length - 1][0].toFixed(1)} ${h - 26} L ${pts[0][0].toFixed(1)} ${h - 26} Z`;
  const every = Math.ceil(series.length / 7);
  const labels = series.filter((d, i) => i % every === 0 || i === series.length - 1).map((d) => html`<span class="num">${d.day.slice(8)}/${d.day.slice(5, 7)}</span>`);
  return html`<div class="chart-wrap"><svg class="chart" viewBox="0 0 ${w} ${h - 20}" preserveAspectRatio="none" role="img" aria-label="${t('home.chart')}">
    <defs><linearGradient id="g-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#c8743c" stop-opacity=".55"/><stop offset="1" stop-color="#c8743c" stop-opacity="0"/></linearGradient></defs>
    ${[0.25, 0.5, 0.75].map((f) => html`<line class="grid-line" x1="${pad}" x2="${w - pad}" y1="${(h - 26) * f + 10}" y2="${(h - 26) * f + 10}"/>`)}
    <path class="area" d="${area}"/><path class="line" d="${line}"/></svg><div class="chart-x">${labels}</div></div>`;
}

function greeting() {
  const h = new Date().getHours();
  return t(h < 12 ? 'home.morning' : h < 18 ? 'home.afternoon' : 'home.evening', { name: S.me.full_name.split(' ')[0] });
}

const ADV_ICON = { open_shift: 'cash', add_products: 'box', late_instalments: 'instal', low_stock: 'warehouse', watch: 'eye', upcoming_prices: 'tag',
  backup: 'download', licence_soon: 'key', slow_stock: 'clock' };

function advisor(items) {
  if (!items.length) return html`<div class="empty small">${icon('check-circle')}<b>${t('home.allGood')}</b><span>${t('home.allGoodHint')}</span></div>`;
  return html`<div class="advisor">${items.map((a) => html`<a class="adv ${a.level}" href="#/${a.go}${a.id === 'backup' || a.id === 'licence_soon' ? '?tab=' + (a.id === 'backup' ? 'backup' : 'licence') : ''}">
    <span class="ic">${icon(ADV_ICON[a.id] || 'info')}</span><span class="grow"><b>${t('adv.' + a.id, { n: a.n, amount: money(a.amount || a.value || 0), days: a.days, hours: a.hours ?? '—' })}</b>
    <span class="small">${t('adv.' + a.id + '.hint', { names: (a.names || []).join('، ') })}</span></span>${icon('chev-l', 'flip')}</a>`)}</div>`;
}

export default async function view(page) {
  put(page, html`<div class="page-head"><div class="titles"><h1 data-guide="home.today">${greeting()}</h1><p>${date(new Date().toISOString())} · ${S.lookups?.settings?.shop_name || ''}</p></div>
    <div class="actions">${can('pos.sell') ? html`<a class="btn accent" href="#/pos">${icon('cart')}${t('home.newSale')}</a>` : ''}
    ${can('stock.receive') ? html`<a class="btn" href="#/receive">${icon('truck')}${t('nav.receive')}</a>` : ''}</div></div>
    <div id="home-body">${skeleton(6)}</div>`);
  let d;
  try { d = await api.get('/api/home'); } catch (e) { put($('#home-body', page), html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  const s = d.summary, y = d.yesterday;
  const trend = s && y && y.net ? Math.round(((s.net - y.net) / Math.abs(y.net)) * 100) : null;
  const body = [];
  if (s) {
    body.push(html`<section class="hero">
      <div class="card ink-card hero-total">
        <div class="row between"><span class="muted">${t('home.todaySales')}</span>${trend !== null ? html`<span class="trend ${trend >= 0 ? 'up' : 'down'}">${icon(trend >= 0 ? 'arrow-up' : 'arrow-down')}${Math.abs(trend)}% ${t('home.vsYesterday')}</span>` : ''}</div>
        <div class="value num" data-count="${s.net}" data-fmt="money">${money(s.net, { whole: true })}</div>
        <div class="mini-stats"><div><span>${t('home.invoices')}</span><b class="num" data-count="${s.sales_count}">${s.sales_count}</b></div>
          <div><span>${t('home.avg')}</span><b class="num">${money(s.average_sale)}</b></div>
          ${s.gross_profit !== undefined ? html`<div><span>${t('home.profit')}</span><b class="num">${money(s.gross_profit)}</b></div>` : html`<div><span>${t('home.returns')}</span><b class="num">${money(s.returns)}</b></div>`}</div>
        ${areaChart(d.series)}
      </div>
      <div class="card"><div class="card-head"><h2>${t('home.doNow')}</h2><span class="badge">${d.advisor.length}</span></div>${advisor(d.advisor)}</div>
    </section>`);
    const b = d.balances;
    body.push(html`<section class="grid kpis">
      ${d.shift ? kpi('cash', t('home.drawer'), d.shift.expected_now, '#/cash') : ''}
      ${kpi('users', t('home.customersOwe'), b.customers_owe, '#/customers')}
      ${kpi('truck', t('home.weOwe'), b.shop_owes_suppliers, '#/receive?tab=suppliers')}
      ${can('cash.safe') ? kpi('safe', t('home.safe'), b.safe, '#/cash?tab=safe') : ''}
      ${b.finance_due ? kpi('instal', t('home.financeDue'), b.finance_due, '#/cash?tab=safe') : ''}
    </section>`);
  } else {
    body.push(html`<section class="hero"><div class="card ink-card">
      ${d.shift ? html`<div class="row between"><span class="muted">${t('home.myShift')}</span><span class="badge ok">${t('shift.open')}</span></div>
        <div class="hero-total"><div class="value num" data-count="${d.shift.expected_now}" data-fmt="money">${money(d.shift.expected_now, { whole: true })}</div>
        <span class="muted">${t('home.inDrawer')}</span></div>
        <div class="mini-stats"><div><span>${t('home.invoices')}</span><b class="num">${d.shift.sales_count}</b></div><div><span>${t('home.salesInShift')}</span><b class="num">${money(d.shift.sales_total)}</b></div></div>`
        : html`<h2>${t('home.noShift')}</h2><p class="muted">${t('home.noShiftHint')}</p><a class="btn accent" href="#/cash">${t('cash.openShift')}</a>`}</div>
      <div class="card"><div class="card-head"><h2>${t('home.doNow')}</h2></div>${advisor(d.advisor)}</div></section>`);
  }
  const lists = [];
  if (d.top?.length) {
    const max = Math.max(...d.top.map((x) => x.sales));
    lists.push(html`<div class="card"><div class="card-head"><h2>${t('home.topToday')}</h2><a class="btn sm ghost" href="#/reports">${t('act.more')}</a></div>
      <div class="bars">${d.top.map((x) => html`<div class="bar"><span class="ellipsis">${x.name}</span><span class="track"><span class="fill" data-w="${Math.round(x.sales / max * 100)}%"></span></span>
      <span class="money num">${money(x.sales)}</span></div>`)}</div></div>`);
  }
  if (d.due?.length) {
    lists.push(html`<div class="card"><div class="card-head"><h2>${t('home.dueToday')}</h2><a class="btn sm ghost" href="#/customers?tab=due">${t('act.more')}</a></div>
      <div class="list">${d.due.map((x) => html`<div class="li"><span class="avatar">${icon('instal')}</span><span class="grow"><b>${x.customer}</b>
        <span class="small muted"> · ${x.late_days ? t('cust.lateDays', { n: x.late_days }) : t('cust.dueToday')}</span></span>
        <b class="money num">${money(x.due_now)}</b>${x.phone ? html`<a class="icon-btn" target="_blank" rel="noopener" aria-label="WhatsApp"
        href="${whatsapp(x.phone, t('cust.remind', { name: x.customer, amount: money(x.due_now), shop: S.lookups?.settings?.shop_name || '' }))}">${icon('message')}</a>` : ''}</div>`)}</div></div>`);
  }
  if (!lists.length && can('pos.sell')) {
    lists.push(html`<div class="quick">
      <a class="accent" href="#/pos">${icon('cart')}<b>${t('home.q.sell')}</b><span class="small">${t('home.q.sellHint')}</span></a>
      <a href="#/sales?tab=warranty">${icon('shield')}<b>${t('home.q.warranty')}</b><span class="small muted">${t('home.q.warrantyHint')}</span></a>
      <a href="#/customers">${icon('users')}<b>${t('home.q.collect')}</b><span class="small muted">${t('home.q.collectHint')}</span></a>
      <a href="#/stock">${icon('warehouse')}<b>${t('home.q.find')}</b><span class="small muted">${t('home.q.findHint')}</span></a></div>`);
  }
  if (lists.length) body.push(html`<section class="grid">${lists}</section>`);
  const root = $('#home-body', page);
  root.className = 'stack enter';
  put(root, html`${body}`);
  settle(root);
}

function kpi(ic, label, value, href) {
  return html`<a class="card flat kpi-card" href="${href}"><div class="kpi"><span class="label">${icon(ic)}${label}</span>
    <span class="value num" data-count="${value}" data-fmt="money">${money(value, { whole: true })}</span></div></a>`;
}

export const _num = num;
