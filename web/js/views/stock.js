// Stock: how much of each product is in each place and on which shelf; move goods store → shop; count and settle.
import { api, key } from '../api.js';
import { S, can, settle } from '../app.js';
import { t } from '../i18n.js';
import { shake } from '../motion.js';
import { productFile } from './products.js';
import { CUR, $, $$, html, put, icon, money, num, date, open, empty, skeleton, errorText, toast, parseQty, run, confirm, seg, bindSeg } from '../ui.js';

export default async function view(page, params) {
  const tab = ['transfer', 'count', 'value'].includes(params.tab) ? params.tab : 'stock';
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.stock')}</h1><p>${t('stock.sub')}</p></div>
    <div class="actions">${can('stock.transfer') ? html`<button class="btn primary" data-move>${icon('swap')}${t('stock.move')}</button>` : ''}</div></div>
    <nav class="tabs" data-lab-scroll><a href="#/stock" ${tab === 'stock' ? CUR : ''}>${icon('warehouse')}${t('stock.tab.stock')}</a>
      ${can('stock.transfer') ? html`<a href="#/stock?tab=transfer" ${tab === 'transfer' ? CUR : ''}>${icon('swap')}${t('stock.tab.transfer')}</a>` : ''}
      ${can('stock.count') ? html`<a href="#/stock?tab=count" ${tab === 'count' ? CUR : ''}>${icon('clipboard')}${t('stock.tab.count')}</a>` : ''}
      ${can('cost.view') ? html`<a href="#/stock?tab=value" ${tab === 'value' ? CUR : ''}>${icon('chart')}${t('stock.tab.value')}</a>` : ''}</nav>
    <div id="st-body"></div>`);
  const body = $('#st-body', page);
  $('[data-move]', page)?.addEventListener('click', () => transferDialog(() => view(page, params)));
  if (tab === 'transfer') return transfers(body);
  if (tab === 'count') return counts(body, params);
  if (tab === 'value') return value(body);
  const locs = S.lookups?.locations || [];
  let only = params.only || 'all', q = '';
  put(body, html`<div class="toolbar">${seg('only', [['all', t('stock.all')], ['low', t('stock.low')], ['out', t('stock.out')]], only)}
    <input class="input" id="st-q" placeholder="${t('products.search')}" autocomplete="off"></div><div id="st-list">${skeleton(6)}</div>`);
  const load = async () => {
    const box = $('#st-list', body);
    try {
      const rows = await api.get('/api/stock', { q, only });
      if (!rows.length) { put(box, html`<div class="card">${empty('warehouse', t('stock.none'), only === 'all' ? t('stock.noneHint') : t('stock.noneFilter'))}</div>`); return; }
      put(box, html`<div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.product')}</th>
        ${locs.map((l) => html`<th class="end">${l.name}</th>`)}<th class="end">${t('stock.forSale')}</th></tr></thead>
        <tbody>${rows.map((p) => html`<tr class="click" data-id="${p.id}"><td class="name">${p.name}<div class="xs faint num">${p.sku}</div></td>
          ${locs.map((l) => html`<td class="end"><span class="num">${num(p.stock[l.id] || 0)}</span>${p.shelves[l.id] ? html`<div class="shelf-tag">${icon('pin')}${p.shelves[l.id]}</div>` : ''}</td>`)}
          <td class="end"><span class="badge num ${p.on_hand <= 0 ? 'bad' : p.reorder_level && p.on_hand <= p.reorder_level ? 'warn' : 'ok'}">${num(p.on_hand)}</span></td></tr>`)}</tbody></table></div></div>`);
      $$('tr[data-id]', box).forEach((tr) => tr.addEventListener('click', () => productFile(tr.dataset.id, load)));
    } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
  };
  bindSeg(body, 'only', (v) => { only = v; load(); });
  let timer;
  $('#st-q', body).addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { q = e.target.value.trim(); load(); }, 200); });
  load();
}

/** A line picker shared by transfers and receiving: search a product, then fill qty (and serials). */
export function linePicker(box, { withCost = false, from = null, onChange }) {
  const lines = [];
  put(box, html`<div class="row"><input class="input grow" id="lp-q" placeholder="${t('pos.search')}" autocomplete="off"><span class="kbd hide-phone">Enter</span></div>
    <div class="list" id="lp-hits"></div><div id="lp-lines" class="stack tight"></div>`);
  let hits = [];
  const draw = () => {
    put($('#lp-lines', box), lines.length ? html`<div class="card flat pad-0"><table class="t"><thead><tr><th>${t('f.product')}</th><th>${t('f.qty')}</th>
      ${withCost ? html`<th>${t('receive.unitCost')}</th><th class="end">${t('f.total')}</th>` : ''}<th></th></tr></thead><tbody>${lines.map((l, i) => html`<tr>
      <td><b>${l.name}</b>${l.track_serial ? html`<textarea class="input num serial-in" data-sn="${i}" placeholder="${t('receive.serialsHint')}">${l.serials.join('\n')}</textarea>` : ''}${from && l.track_serial ? html`<div class="xs faint">${t('stock.serialsFrom')}</div>` : ''}</td>
      <td><input class="input q-in num" data-q="${i}" value="${l.qty}" inputmode="decimal"></td>
      ${withCost ? html`<td><input class="input money-in cost-in" data-c="${i}" value="${l.unit_cost ? l.unit_cost / 100 : ''}" inputmode="decimal"></td><td class="end money num">${money(Math.round(l.qty * (l.unit_cost || 0)))}</td>` : ''}
      <td><button class="icon-btn sm" data-x="${i}" aria-label="${t('act.remove')}">${icon('trash')}</button></td></tr>`)}</tbody></table></div>`
      : html`<p class="small faint">${t('receive.addLines')}</p>`);
    $$('[data-q]', box).forEach((inp) => inp.addEventListener('change', () => {
      const v = parseQty(inp.value); const l = lines[+inp.dataset.q];
      if (v === null || v <= 0) { shake(inp); inp.value = l.qty; return; }
      l.qty = v; draw(); onChange && onChange(lines);
    }));
    $$('[data-c]', box).forEach((inp) => inp.addEventListener('change', () => {
      const v = Math.round(parseFloat(inp.value || '0') * 100); const l = lines[+inp.dataset.c];
      if (!(v >= 0)) { shake(inp); return; }
      l.unit_cost = v; draw(); onChange && onChange(lines);
    }));
    $$('[data-sn]', box).forEach((ta) => ta.addEventListener('change', () => {
      const l = lines[+ta.dataset.sn];
      l.serials = ta.value.split(/[\s,]+/).map((s) => s.trim().toUpperCase()).filter(Boolean);
      l.qty = l.serials.length || l.qty; draw(); onChange && onChange(lines);
    }));
    $$('[data-x]', box).forEach((b) => b.addEventListener('click', () => { lines.splice(+b.dataset.x, 1); draw(); onChange && onChange(lines); }));
  };
  const addHit = (p) => {
    if (!p) return;
    const ex = lines.find((l) => l.product_id === p.id);
    if (ex && !p.track_serial) ex.qty += 1;
    else if (!ex) lines.push({ product_id: p.id, name: p.name, qty: p.track_serial ? 0 : 1, unit_cost: p.avg_cost || 0, track_serial: !!p.track_serial, serials: [] });
    $('#lp-q', box).value = ''; put($('#lp-hits', box), ''); hits = [];
    draw(); onChange && onChange(lines);
    setTimeout(() => (p.track_serial ? $(`[data-sn="${lines.findIndex((l) => l.product_id === p.id)}"]`, box) : $('#lp-q', box))?.focus(), 30);
  };
  let timer;
  $('#lp-q', box).addEventListener('input', (e) => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = e.target.value.trim();
      if (!q) { put($('#lp-hits', box), ''); hits = []; return; }
      hits = (await api.get('/api/products', { q, limit: 8 }).catch(() => ({ items: [] }))).items;
      put($('#lp-hits', box), html`${hits.map((p, i) => html`<button class="li" data-h="${i}">${icon(p.track_serial ? 'shield' : 'box')}<span class="grow">${p.name} <span class="xs faint num">${p.sku}</span></span>
        <span class="badge num">${num(p.on_hand)}</span></button>`)}`);
      $$('[data-h]', box).forEach((b) => b.addEventListener('click', () => addHit(hits[+b.dataset.h])));
    }, 150);
  });
  $('#lp-q', box).addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); addHit(hits[0]); } });
  draw();
  return lines;
}

function transferDialog(onDone) {
  const locs = S.lookups?.locations || [];
  const store = locs.find((l) => l.kind === 'warehouse') || locs[0];
  const shop = locs.find((l) => l.kind === 'shop') || locs[1];
  const idem = key();
  let lines;
  open({
    title: t('stock.move'),
    wide: true,
    body: html`<div class="cols form"><div class="field"><label for="tf">${t('stock.from')}</label><select id="tf" class="input">${locs.map((l) => html`<option value="${l.id}" ${l.id === store?.id ? 'selected' : ''}>${l.name}</option>`)}</select></div>
      <div class="field"><label for="tt">${t('stock.to')}</label><select id="tt" class="input">${locs.map((l) => html`<option value="${l.id}" ${l.id === shop?.id ? 'selected' : ''}>${l.name}</option>`)}</select></div></div>
      <div id="tlines"></div><div class="field"><label for="tn">${t('f.note')}</label><input id="tn" class="input"></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${icon('swap')}${t('stock.doMove')}</button>`,
    mount(box, close) {
      lines = linePicker($('#tlines', box), { from: true });
      $('[data-ok]', box).addEventListener('click', async (e) => {
        if (!lines.length) { shake($('#lp-q', box)); return; }
        const r = await run(api.post('/api/transfer', { idem_key: idem, from_id: $('#tf', box).value, to_id: $('#tt', box).value, note: $('#tn', box).value,
          lines: lines.map((l) => ({ product_id: l.product_id, qty: l.track_serial ? l.serials.length : l.qty, serials: l.serials })) }), null, e.currentTarget);
        if (r) { close(); toast(t('stock.moved', { n: r.number })); onDone && onDone(); }
      });
    },
  });
}

async function transfers(body) {
  put(body, skeleton(4));
  try {
    const rows = await api.get('/api/transfers');
    put(body, rows.length ? html`<div class="card pad-0"><table class="t"><thead><tr><th>${t('f.number')}</th><th>${t('f.date')}</th><th>${t('stock.from')}</th><th>${t('stock.to')}</th><th class="hide-phone">${t('sales.by')}</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr><td class="num">${r.number}</td><td class="num">${date(r.at, true)}</td><td>${r.from_name}</td><td>${r.to_name}</td><td class="hide-phone">${r.by_name}</td></tr>`)}</tbody></table></div>`
      : html`<div class="card">${empty('swap', t('stock.noTransfers'), t('stock.noTransfersHint'))}</div>`);
  } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}

async function counts(body, params) {
  if (params.id) return countSheet(body, params.id);
  put(body, skeleton(4));
  const locs = S.lookups?.locations || [];
  try {
    const rows = await api.get('/api/counts');
    put(body, html`<div class="card"><div class="card-head"><h2>${t('stock.newCount')}</h2></div><p class="muted small">${t('stock.countHint')}</p>
      <div class="row wrap"><select class="input" id="cl">${locs.map((l) => html`<option value="${l.id}">${l.name}</option>`)}</select>
      <button class="btn primary" data-start>${icon('clipboard')}${t('stock.startCount')}</button></div></div>
      ${rows.length ? html`<div class="card pad-0"><table class="t"><thead><tr><th>${t('f.number')}</th><th>${t('f.place')}</th><th>${t('f.date')}</th><th>${t('state.status')}</th></tr></thead>
      <tbody>${rows.map((r) => html`<tr class="click" data-id="${r.id}"><td class="num">${r.number}</td><td>${r.place}</td><td class="num">${date(r.started_at, true)}</td>
      <td>${r.closed_at ? html`<span class="badge ok">${t('stock.closed')}</span>` : html`<span class="badge warn">${t('stock.open')}</span>`}</td></tr>`)}</tbody></table></div>` : ''}`);
    $('[data-start]', body).addEventListener('click', async (e) => {
      const r = await run(api.post('/api/count/start', { location_id: $('#cl', body).value }), null, e.currentTarget);
      if (r) location.hash = '#/stock?tab=count&id=' + r.id;
    });
    $$('tr[data-id]', body).forEach((tr) => tr.addEventListener('click', () => { location.hash = '#/stock?tab=count&id=' + tr.dataset.id; }));
  } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}

async function countSheet(body, id) {
  let c;
  try { c = await api.get('/api/count', { id }); } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  const closed = !!c.closed_at;
  put(body, html`<div class="card"><div class="row between wrap"><div><h2>${t('stock.countOf', { place: c.location })} <span class="num faint">${c.number}</span></h2>
    <p class="small muted">${t('stock.counted', { n: c.done, of: c.lines.length })}</p></div>
    ${closed ? html`<span class="badge ok">${t('stock.closed')}</span>` : html`<button class="btn primary" data-close-count>${icon('check')}${t('stock.closeCount')}</button>`}</div></div>
    <div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.shelf')}</th><th>${t('f.product')}</th><th class="end">${t('stock.expected')}</th>
      <th>${t('stock.countedQ')}</th><th class="end">${t('stock.diff')}</th></tr></thead><tbody>${c.lines.map((l) => html`<tr>
      <td class="num">${l.shelf || '—'}</td><td class="name">${l.name}</td><td class="end num">${num(l.expected)}</td>
      <td><input class="input q-in num" data-cnt="${l.id}" value="${l.counted ?? ''}" inputmode="decimal" ${closed ? 'disabled' : ''}></td>
      <td class="end">${l.diff === null ? '—' : html`<span class="badge num ${l.diff < 0 ? 'bad' : l.diff > 0 ? 'warn' : 'ok'}">${l.diff > 0 ? '+' : ''}${num(l.diff)}</span>${l.diff_value ? html`<div class="xs faint money">${money(l.diff_value)}</div>` : ''}`}</td></tr>`)}</tbody></table></div></div>`);
  $$('[data-cnt]', body).forEach((inp) => inp.addEventListener('change', async () => {
    const v = parseQty(inp.value);
    if (v === null) { shake(inp); return; }
    if (await run(api.post('/api/count/line', { count_id: id, product_id: inp.dataset.cnt, counted: v }))) countSheet(body, id);
  }));
  $('[data-close-count]', body)?.addEventListener('click', async () => {
    const why = await confirm({ title: t('stock.closeCount'), text: t('stock.closeText'), ok: t('stock.closeCount'), reason: true });
    if (why && await run(api.post('/api/count/close', { count_id: id, reason: why }), t('stock.countClosed'))) countSheet(body, id);
  });
}

async function value(body) {
  put(body, skeleton(4));
  try {
    const d = await api.get('/api/stock/value');
    put(body, html`<div class="stack enter"><div class="grid kpis"><div class="card ink-card kpi"><span class="label">${t('stock.value')}</span>
      <span class="value num" data-count="${d.value}" data-fmt="money">${money(d.value, { whole: true })}</span></div>
      <div class="card flat kpi"><span class="label">${t('stock.sleeping')}</span><span class="value num">${money(d.slow.reduce((a, r) => a + r.value, 0))}</span></div></div>
      <div class="card"><div class="card-head"><h2>${t('stock.slow')}</h2></div><p class="small muted">${t('stock.slowHint')}</p>
      ${d.slow.length ? html`<div class="list">${d.slow.map((r) => html`<div class="li"><span class="grow"><b>${r.name}</b> <span class="xs faint">${r.last_sale ? t('stock.lastSold', { d: date(r.last_sale) }) : t('stock.neverSold')}</span></span>
        <span class="badge num">${num(r.on_hand)}</span><span class="money num">${money(r.value)}</span></div>`)}</div>` : html`<p class="muted">${t('stock.noSlow')}</p>`}</div></div>`);
    settle(body);
  } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}
