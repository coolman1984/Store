// Products and prices: the catalogue, a product's file (prices with dates, stock per place and shelf, serials, moves),
// and the bulk price change that Egyptian shops need after every company price rise.
import { api } from '../api.js';
import { S, can, settle } from '../app.js';
import { t } from '../i18n.js';
import { shake } from '../motion.js';
import {
  $, $$, html, put, icon, money, num, date, open, empty, skeleton, errorText, toast, parseMoney, run, confirm, today, seg, bindSeg, segValue,
} from '../ui.js';

let filters = { q: '', category_id: '', brand_id: '' };

export default async function view(page, params) {
  const L = S.lookups || {};
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.products')}</h1><p>${t('products.sub')}</p></div>
    <div class="actions">${can('prices.change') ? html`<button class="btn" data-bulk>${icon('percent')}${t('products.bulk')}</button>` : ''}
    ${can('products.edit') ? html`<button class="btn primary" data-new>${icon('plus')}${t('products.add')}</button>` : ''}</div></div>
    <div class="toolbar"><input class="input" id="p-q" placeholder="${t('products.search')}" value="${filters.q}" autocomplete="off">
      <select class="input" id="p-cat" aria-label="${t('f.category')}"><option value="">${t('products.allCats')}</option>${(L.categories || []).map((c) => html`<option value="${c.id}" ${c.id === filters.category_id ? 'selected' : ''}>${c.name}</option>`)}</select>
      <select class="input" id="p-brand" aria-label="${t('f.brand')}"><option value="">${t('products.allBrands')}</option>${(L.brands || []).map((b) => html`<option value="${b.id}" ${b.id === filters.brand_id ? 'selected' : ''}>${b.name}</option>`)}</select></div>
    <div id="p-list">${skeleton(6)}</div>`);
  const load = async () => {
    const box = $('#p-list', page);
    try {
      const r = await api.get('/api/products', { ...filters, limit: 400, hidden: '1' });
      if (!r.items.length) {
        put(box, html`<div class="card">${empty('box', filters.q ? t('products.noneSearch') : t('products.none'), t('products.noneHint'),
          can('products.edit') ? html`<button class="btn primary" data-new2>${icon('plus')}${t('products.add')}</button>` : '')}</div>`);
        $('[data-new2]', box)?.addEventListener('click', () => editProduct(null, load));
        return;
      }
      const cost = can('cost.view');
      put(box, html`<div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.product')}</th><th class="hide-phone">${t('f.brand')}</th>
        <th class="end">${t('products.price')}</th>${cost ? html`<th class="end hide-phone">${t('products.cost')}</th><th class="end hide-phone">${t('products.margin')}</th>` : ''}
        <th class="end">${t('products.inStock')}</th></tr></thead><tbody>${r.items.map((p) => {
          const margin = cost && p.prices.retail && p.avg_cost ? Math.round((p.prices.retail - p.avg_cost) * 100 / p.prices.retail) : null;
          const low = p.reorder_level && p.on_hand <= p.reorder_level;
          return html`<tr class="click" data-id="${p.id}"><td class="name"><div class="row">${p.track_serial ? icon('shield') : ''}<span>${p.name}</span>${p.active ? '' : html`<span class="badge">${t('products.hidden')}</span>`}</div>
            <div class="xs faint num">${p.sku}${p.model ? ' · ' + p.model : ''}</div></td><td class="hide-phone">${p.brand || '—'}</td>
            <td class="end money num">${money(p.prices.retail)}</td>
            ${cost ? html`<td class="end money num hide-phone faint">${money(p.avg_cost)}</td><td class="end hide-phone">${margin !== null ? html`<span class="badge ${margin < 8 ? 'bad' : margin < 15 ? 'warn' : 'ok'}">${margin}%</span>` : '—'}</td>` : ''}
            <td class="end"><span class="badge ${p.on_hand <= 0 ? 'bad' : low ? 'warn' : 'ok'} num">${num(p.on_hand)}</span></td></tr>`;
        })}</tbody></table></div></div><p class="small faint">${t('products.count', { n: r.items.length })}</p>`);
      $$('tr[data-id]', box).forEach((tr) => tr.addEventListener('click', () => productFile(tr.dataset.id, load)));
    } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
  };
  let timer;
  $('#p-q', page).addEventListener('input', (e) => { clearTimeout(timer); timer = setTimeout(() => { filters.q = e.target.value.trim(); load(); }, 200); });
  $('#p-cat', page).addEventListener('change', (e) => { filters.category_id = e.target.value; load(); });
  $('#p-brand', page).addEventListener('change', (e) => { filters.brand_id = e.target.value; load(); });
  $('[data-new]', page)?.addEventListener('click', () => editProduct(null, load));
  $('[data-bulk]', page)?.addEventListener('click', () => bulkPrice(load));
  await load();
  if (params.new) editProduct(null, load);
  if (params.id) productFile(params.id, load);
}

export async function productFile(id, onChange) {
  let p;
  try { p = await api.get('/api/product', { id }); } catch (e) { toast(errorText(e), 'bad'); return; }
  const cost = p.cost;
  open({
    title: p.name,
    kind: 'panel',
    body: html`<div class="row wrap"><span class="chip num">${icon('tag')}${p.sku}</span>${p.brand ? html`<span class="chip">${p.brand}</span>` : ''}${p.category ? html`<span class="chip">${p.category}</span>` : ''}
        ${p.model ? html`<span class="chip num">${p.model}</span>` : ''}${p.warranty_months ? html`<span class="chip">${icon('shield')}${t('products.warrantyN', { n: p.warranty_months })}</span>` : ''}
        ${p.barcodes.map((b) => html`<span class="chip num">${icon('barcode')}${b}</span>`)}</div>
      <div class="grid kpis"><div class="card flat kpi"><span class="label">${t('products.price')}</span><span class="value num">${money(p.prices.retail)}</span>
        ${p.prices.trade ? html`<span class="small muted">${t('products.trade')}: ${money(p.prices.trade)}</span>` : ''}${p.prices.min ? html`<span class="small muted">${t('pos.minPrice')}: ${money(p.prices.min)}</span>` : ''}</div>
        <div class="card flat kpi"><span class="label">${t('products.inStock')}</span><span class="value num">${num(p.on_hand)}</span><span class="small muted">${t('products.sold30', { n: num(p.sold_30d) })}</span></div>
        ${cost ? html`<div class="card flat kpi"><span class="label">${t('products.cost')}</span><span class="value num">${money(cost.avg_cost)}</span><span class="small muted">${t('products.lastCost')}: ${money(cost.last_cost)}</span></div>` : ''}</div>
      ${p.upcoming.length ? html`<div class="tip warn">${icon('calendar')}<div>${p.upcoming.map((u) => html`<div>${t('products.upcoming', { k: t('price.' + u.kind), m: money(u.amount), d: date(u.starts_on) })}</div>`)}</div></div>` : ''}
      <div class="card flat"><div class="card-head"><h2>${t('products.places')}</h2></div>${p.places.map((pl) => html`<div class="place-row">
        <span>${icon(pl.kind === 'warehouse' ? 'warehouse' : pl.kind === 'damaged' ? 'alert' : 'store')} <b>${pl.name}</b></span>
        <span class="row">${icon('pin')}<input class="input shelf-in num" data-shelf="${pl.location_id}" value="${pl.shelf}" placeholder="—" aria-label="${t('f.shelf')}" ${can('stock.transfer') ? '' : 'disabled'}></span>
        <span class="badge num ${pl.qty < 0 ? 'bad' : ''}">${num(pl.qty)}</span></div>`)}</div>
      ${p.track_serial ? html`<div class="card flat"><div class="card-head"><h2>${t('products.serials')}</h2><span class="badge">${p.serials.length}</span></div>
        <div class="serial-list">${p.serials.map((s) => html`<span class="chip num">${s.serial}</span>`)}</div></div>` : ''}
      <details class="card flat"><summary class="row"><h2 class="grow">${t('products.priceHistory')}</h2>${icon('chev-d')}</summary><div class="timeline">${p.price_history.map((h) => html`<div class="ev">
        <span class="badge">${t('price.' + h.kind)}</span><span class="small"><span class="num">${date(h.starts_on)}</span> · ${h.reason || ''} · ${h.by_name || ''}</span><span class="money num">${money(h.amount)}</span></div>`)}</div></details>
      <details class="card flat"><summary class="row"><h2 class="grow">${t('products.moves')}</h2>${icon('chev-d')}</summary><div class="timeline">${p.moves.map((m) => html`<div class="ev">
        <span class="badge ${m.qty < 0 ? 'warn' : 'ok'}">${t('move.' + m.kind)}</span><span class="small"><span class="num">${date(m.at, true)}</span> · ${m.place}${m.serial ? html` · <span class="num">${m.serial}</span>` : ''} · ${m.by_name || ''}${m.note ? ' · ' + m.note : ''}</span>
        <b class="num">${m.qty > 0 ? '+' : ''}${num(m.qty)}</b></div>`)}</div></details>`,
    foot: html`${can('products.edit') ? html`<button class="btn" data-hide>${icon(p.active ? 'x' : 'check')}${p.active ? t('products.hide') : t('products.show')}</button>
      <button class="btn primary" data-edit>${icon('edit')}${t('act.edit')}</button>` : ''}`,
    mount(box, close) {
      $('[data-edit]', box)?.addEventListener('click', () => { close(); editProduct(p, () => { onChange && onChange(); productFile(id, onChange); }); });
      $('[data-hide]', box)?.addEventListener('click', async () => {
        if (p.active && !(await confirm({ title: t('products.hide'), text: t('products.hideText'), ok: t('products.hide') }))) return;
        if (await run(api.post('/api/product/active', { id, active: !p.active }), t('saved'))) { close(); onChange && onChange(); }
      });
      $$('[data-shelf]', box).forEach((inp) => inp.addEventListener('change', async () => {
        await run(api.post('/api/product/place', { product_id: id, location_id: inp.dataset.shelf, shelf: inp.value }), t('saved'));
      }));
    },
  });
}

export function editProduct(p, onDone) {
  const L = S.lookups || {};
  const priceDisabled = p && !can('prices.change');
  open({
    title: p ? t('act.edit') + ' — ' + p.name : t('products.add'),
    wide: true,
    body: html`<div class="form">
      <div class="cols"><div class="field"><label for="pn">${t('f.name')}</label><input id="pn" class="input" value="${p?.name || ''}" autofocus placeholder="${t('products.nameHint')}"></div>
        <div class="field"><label for="pm">${t('f.model')}</label><input id="pm" class="input num" value="${p?.model || ''}"></div></div>
      <div class="cols"><div class="field"><label for="pc">${t('f.category')}</label><input id="pc" class="input" list="cats" value="${p?.category || ''}"><datalist id="cats">${(L.categories || []).map((c) => html`<option value="${c.name}">`)}</datalist></div>
        <div class="field"><label for="pb">${t('f.brand')}</label><input id="pb" class="input" list="brands" value="${p?.brand || ''}"><datalist id="brands">${(L.brands || []).map((b) => html`<option value="${b.name}">`)}</datalist></div>
        <div class="field"><label for="pu">${t('f.unit')}</label><select id="pu" class="input">${(L.units || ['piece']).map((u) => html`<option value="${u}" ${u === (p?.unit || 'piece') ? 'selected' : ''}>${t('unit.' + u)}</option>`)}</select></div></div>
      <div class="cols"><div class="field"><label for="pr">${t('products.price')}</label><input id="pr" class="input money-in" inputmode="decimal" value="${p ? p.prices.retail / 100 : ''}" ${priceDisabled ? 'disabled' : ''}></div>
        <div class="field"><label for="pt">${t('products.trade')}</label><input id="pt" class="input money-in" inputmode="decimal" value="${p?.prices.trade ? p.prices.trade / 100 : ''}" ${priceDisabled ? 'disabled' : ''}>
          <span class="hint">${t('products.tradeHint')}</span></div>
        <div class="field"><label for="pmin">${t('pos.minPrice')}</label><input id="pmin" class="input money-in" inputmode="decimal" value="${p?.prices.min ? p.prices.min / 100 : ''}" ${priceDisabled ? 'disabled' : ''}>
          <span class="hint">${t('products.minHint')}</span></div></div>
      <div class="cols"><div class="field"><label for="pbc">${t('f.barcode')}</label><input id="pbc" class="input num" value="${(p?.barcodes || []).join(' ')}" placeholder="${t('products.barcodeHint')}"></div>
        <div class="field"><label for="pw">${t('products.warranty')}</label><input id="pw" class="input num" inputmode="numeric" value="${p?.warranty_months ?? ''}" placeholder="0"></div>
        <div class="field"><label for="pro">${t('products.reorder')}</label><input id="pro" class="input num" inputmode="decimal" value="${p?.reorder_level || ''}" placeholder="0"><span class="hint">${t('products.reorderHint')}</span></div></div>
      <div class="row wrap"><label class="check"><input type="checkbox" id="ps" ${p?.track_serial ? 'checked' : ''}>${t('products.serialToggle')}</label>
        <label class="check"><input type="checkbox" id="pf" ${p?.fractional ? 'checked' : ''}>${t('products.fractional')}</label></div>
      <p class="small faint">${t('products.serialHint')}</p>
      <div class="field"><label for="pno">${t('f.note')}</label><textarea id="pno" class="input">${p?.notes || ''}</textarea></div>
      <p class="err small" id="perr" role="alert"></p></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const body = { id: p?.id, name: $('#pn', box).value, model: $('#pm', box).value, category: $('#pc', box).value || undefined, brand: $('#pb', box).value || undefined,
          unit: $('#pu', box).value, barcodes: $('#pbc', box).value.split(/[\s,]+/).filter(Boolean), warranty_months: +($('#pw', box).value || 0),
          reorder_level: +($('#pro', box).value || 0), track_serial: $('#ps', box).checked, fractional: $('#pf', box).checked, notes: $('#pno', box).value };
        if (!priceDisabled) {
          for (const [k, id] of [['retail', '#pr'], ['trade', '#pt'], ['min', '#pmin']]) {
            const raw = $(id, box).value.trim();
            const v = raw ? parseMoney(raw) : 0;
            if (v === null) { shake($(id, box)); return; }
            body[k] = v;
          }
          if (!body.retail) { shake($('#pr', box)); $('#perr', box).textContent = t('products.needPrice'); return; }
        }
        const r = await run(api.post('/api/product/save', body), t('saved'), e.currentTarget);
        if (r) {
          close();
          S.lookups = await api.get('/api/lookups').catch(() => S.lookups);
          onDone && onDone(r);
        }
      });
    },
  });
}

function bulkPrice(onDone) {
  const L = S.lookups || {};
  let preview = null;
  open({
    title: t('products.bulk'),
    wide: true,
    body: html`<p class="muted small">${t('products.bulkHint')}</p>
      <div class="cols form"><div class="field"><label for="bb">${t('f.brand')}</label><select id="bb" class="input"><option value="">—</option>${(L.brands || []).map((b) => html`<option value="${b.id}">${b.name}</option>`)}</select></div>
        <div class="field"><label for="bc">${t('f.category')}</label><select id="bc" class="input"><option value="">—</option>${(L.categories || []).map((c) => html`<option value="${c.id}">${c.name}</option>`)}</select></div>
        <div class="field"><label for="bp">${t('products.percent')}</label><input id="bp" class="input money-in" inputmode="decimal" placeholder="+10 / -5"></div>
        <div class="field"><label for="bd">${t('products.startsOn')}</label><input id="bd" type="date" class="input" value="${today()}" min="${today()}"></div></div>
      <div class="field"><span class="label">${t('products.roundTo')}</span>${seg('round', [['100', t('round.1')], ['500', t('round.5')], ['1000', t('round.10')], ['5000', t('round.50')]], '500')}</div>
      <div class="field"><label for="br">${t('f.reason')}</label><input id="br" class="input" placeholder="${t('products.bulkReason')}"></div>
      <div id="bprev"></div>`,
    foot: html`<button class="btn" data-preview>${icon('eye')}${t('products.preview')}</button><button class="btn primary" data-apply disabled>${icon('check')}${t('products.apply')}</button>`,
    mount(box, close) {
      const body = () => ({ brand_id: $('#bb', box).value || undefined, category_id: $('#bc', box).value || undefined,
        percent: parseFloat(($('#bp', box).value || '').replace('+', '')), round_to: +segValue(box, 'round'), starts_on: $('#bd', box).value,
        reason: $('#br', box).value, kinds: ['retail', 'trade', 'min'] });
      bindSeg(box, 'round', () => { preview = null; $('[data-apply]', box).disabled = true; });
      $('[data-preview]', box).addEventListener('click', async (e) => {
        const b = body();
        if (!b.percent) { shake($('#bp', box)); return; }
        preview = await run(api.post('/api/prices/bulk', b), null, e.currentTarget);
        if (!preview) return;
        put($('#bprev', box), preview.items.length ? html`<div class="card flat pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.product')}</th><th class="end">${t('products.now')}</th><th class="end">${t('products.after')}</th></tr></thead>
          <tbody>${preview.items.map((it) => html`<tr><td>${it.name}</td><td class="end money num faint">${money(it.old.retail)}</td><td class="end money num"><b>${money(it.new.retail || it.old.retail)}</b></td></tr>`)}</tbody></table></div></div>
          <p class="small muted">${t('products.previewCount', { n: preview.items.length })}</p>` : empty('search', t('products.bulkNone'), ''));
        $('[data-apply]', box).disabled = !preview.items.length;
      });
      $('[data-apply]', box).addEventListener('click', async (e) => {
        if (!(await confirm({ title: t('products.apply'), text: t('products.applyText', { n: preview.items.length, d: date($('#bd', box).value) }), ok: t('products.apply') }))) return;
        const r = await run(api.post('/api/prices/bulk', { ...body(), apply: true }), t('products.applied'), e.currentTarget);
        if (r) { close(); onDone && onDone(); }
      });
    },
  });
}

export const _settle = settle;
