// The counter. Goal: one product, cash, receipt — under 10 seconds, keyboard or touch.
// F2 search · Enter add first result · + / − quantity of the last line · F4 pay · Esc clear search · F8 park the sale.
import { api, key } from '../api.js';
import { S, can, refreshShift, go } from '../app.js';
import { signal } from '../guide.js';
import { t } from '../i18n.js';
import { pop, tick, shake } from '../motion.js';
import { prefs } from '../prefs.js';
import { printReceipt } from '../print.js';
import {
  $, $$, html, put, icon, money, moneyH, parseMoney, parseQty, num, open, toast, fail, showError, withApproval, empty, whatsapp, today, errorText,
} from '../ui.js';

const CART_KEY = 'store.cart';
const PARK_KEY = 'store.parked';
let cart, results = [], focus = 0, root, searchTimer, lastQuote = null, searchSeq = 0, pending = null;

const blankCart = () => ({ lines: [], discount: 0, customer: null, location_id: null, note: '' });
function loadCart() { try { return JSON.parse(sessionStorage.getItem(CART_KEY)) || blankCart(); } catch { return blankCart(); } }
function saveCart() { try { sessionStorage.setItem(CART_KEY, JSON.stringify(cart)); } catch { /* memory only */ } }
const parked = () => { try { return JSON.parse(localStorage.getItem(PARK_KEY)) || []; } catch { return []; } };
const setParked = (v) => { try { localStorage.setItem(PARK_KEY, JSON.stringify(v)); } catch { /* ignore */ } };

const subtotal = () => cart.lines.reduce((a, l) => a + Math.round(l.qty * l.unit_price), 0);
const total = () => subtotal() - cart.discount;
// an unfinished payment keeps its key: if the answer was lost and the cashier presses Pay again, the server returns the same sale
function idemFor(body) {
  const sig = JSON.stringify(body);
  if (!pending || pending.sig !== sig) pending = { sig, key: key() };
  return pending.key;
}
const sellable = () => (S.lookups?.locations || []).filter((l) => l.sellable);

export default async function view(page) {
  root = page;
  cart = loadCart();
  if (!cart.location_id) cart.location_id = sellable()[0]?.id || null;
  const me = await api.get('/api/me').catch(() => S.me);
  if (!me.shift_id) {
    put(page, html`<div class="pos-noshift card accent-card">
      <div class="row">${icon('cash')}<h2>${t('pos.noShift.title')}</h2></div><p>${t('pos.noShift.text')}</p>
      <div class="row wrap"><input id="float" class="input big money-in" data-guide="shift.cash" inputmode="decimal" placeholder="0" aria-label="${t('cash.float')}">
      <button class="btn primary lg" data-open data-guide="shift.open">${t('cash.openShift')}</button></div></div>`);
    $('[data-open]', page).addEventListener('click', async (e) => {
      const amount = parseMoney($('#float', page).value || '0');
      if (amount === null) { shake($('#float', page)); return; }
      e.currentTarget.setAttribute('aria-busy', 'true');
      try { await api.post('/api/shift/open', { opening_float: amount }); signal('shift.opened'); await refreshShift(); view(page); } catch (err) { fail(err); e.currentTarget.removeAttribute('aria-busy'); }
    });
    return;
  }
  const cats = S.lookups?.categories || [];
  put(page, html`<h1 class="sr">${t('nav.pos')}</h1><div class="pos">
    <section class="pos-catalog">
      <div class="pos-search card flat">
        ${icon('barcode')}<input id="pos-q" class="input" data-guide="pos.search" autocomplete="off" placeholder="${t('pos.search')}" aria-label="${t('pos.search')}"
          aria-controls="pos-results" aria-autocomplete="list"><span class="kbd hide-phone">F2</span>
      </div>
      <div class="pos-cats" id="pos-cats" data-lab-scroll><button class="chip" aria-pressed="true" data-cat="">${t('pos.all')}</button>
        ${cats.map((c) => html`<button class="chip" aria-pressed="false" data-cat="${c.id}">${c.name}</button>`)}</div>
      <div class="pos-results" id="pos-results" data-lab-scroll role="listbox" aria-label="${t('pos.results')}">${Array.from({ length: 8 }, () => html`<div class="tile sk"></div>`)}</div>
    </section>
    <aside class="pos-cart" aria-label="${t('pos.cart')}">
      <div class="paper">
        <div class="paper-head row">
          <button class="chip grow" data-customer>${icon('user')}<span class="ellipsis" id="cust-name">${cart.customer?.name || t('pos.walkIn')}</span></button>
          ${sellable().length > 1 ? html`<select class="input sm-select" id="pos-loc" aria-label="${t('f.place')}">${sellable().map((l) =>
            html`<option value="${l.id}" ${l.id === cart.location_id ? 'selected' : ''}>${l.name}</option>`)}</select>` : ''}
          <button class="icon-btn" data-park aria-label="${t('pos.park')}" title="${t('pos.park')} (F8)">${icon('clock')}</button>
        </div>
        <div id="parked"></div>
        <div class="lines" id="lines" aria-live="polite"></div>
        <div class="paper-foot" id="totals"></div>
      </div>
    </aside></div>
    <div class="pos-mbar" id="pos-mbar" hidden><span class="badge" id="mbar-n"></span><b class="num grow" id="mbar-t"></b>
      <button class="btn sm" data-jump>${t('pos.cart')}</button><button class="btn accent sm" data-mpay>${t('pos.pay')}</button></div>`);
  $('[data-jump]', page).addEventListener('click', () => $('.pos-cart', page).scrollIntoView({ behavior: 'smooth' }));
  $('[data-mpay]', page).addEventListener('click', pay);
  bind();
  drawCart();
  drawParked();
  search('');
  setTimeout(() => $('#pos-q')?.focus(), 50);
}

function bind() {
  const q = $('#pos-q', root);
  q.addEventListener('input', () => { clearTimeout(searchTimer); searchTimer = setTimeout(() => search(q.value), 90); });
  q.addEventListener('keydown', async (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      const v = q.value.trim();
      if (!v && cart.lines.length) return pay();
      clearTimeout(searchTimer);
      await search(v);
      if (results[focus]) add(results[focus], true);
      else if (v) { tick(false); toast(t('pos.notFound', { q: v }), 'bad'); }
    } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      focus = Math.max(0, Math.min(results.length - 1, focus + (e.key === 'ArrowDown' ? 1 : -1)));
      drawResults();
    } else if (e.key === 'Escape') { q.value = ''; search(''); }
  });
  $('#pos-cats', root).addEventListener('click', (e) => {
    const b = e.target.closest('[data-cat]');
    if (!b) return;
    $$('[data-cat]', root).forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
    search(q.value, b.dataset.cat);
  });
  $('#pos-results', root).addEventListener('click', (e) => {
    const b = e.target.closest('[data-i]');
    if (b) add(results[+b.dataset.i]);
  });
  $('[data-customer]', root).addEventListener('click', pickCustomer);
  $('[data-park]', root).addEventListener('click', park);
  $('#pos-loc', root)?.addEventListener('change', (e) => { cart.location_id = e.target.value; saveCart(); search(q.value); });
  $('#lines', root).addEventListener('click', onLineClick);
  $('#lines', root).addEventListener('change', (e) => {
    const inp = e.target.closest('[data-qty]');
    if (!inp) return;
    const line = cart.lines[+inp.dataset.qty];
    const v = parseQty(inp.value);
    if (v === null || v <= 0 || (!line.fractional && !Number.isInteger(v))) { shake(inp); inp.value = line.qty; return; }
    line.qty = v; changed();
  });
  document.addEventListener('keydown', keys);
}

function keys(e) {
  if (!root || !document.body.contains(root) || document.body.dataset.route !== 'pos') { document.removeEventListener('keydown', keys); return; }
  if (document.querySelector('.scrim')) return;
  if (e.key === 'F4') { e.preventDefault(); pay(); }
  else if (e.key === 'F8') { e.preventDefault(); park(); }
  else if ((e.key === '+' || e.key === '-') && document.activeElement?.id === 'pos-q' && !$('#pos-q').value && cart.lines.length) {
    e.preventDefault();
    const line = cart.lines[cart.lines.length - 1];
    if (line.serial) return;
    line.qty = Math.max(1, line.qty + (e.key === '+' ? 1 : -1));
    changed();
  }
}

async function search(q, cat) {
  const catId = cat ?? $('[data-cat][aria-pressed="true"]', root)?.dataset.cat ?? '';
  const box = $('#pos-results', root);
  if (!box) return;
  const mine = ++searchSeq;  // a slow old answer must never replace a newer one (a scanner could then add the wrong product)
  try {
    const r = await api.get(q || !catId ? '/api/pos/search' : '/api/products', { q, location_id: cart.location_id, category_id: catId, limit: 24 });
    if (mine !== searchSeq) return;
    results = r.items;
    focus = 0;
    drawResults();
    if (r.exact && results.length === 1 && q && $('#pos-q').value.trim() === q) { /* a scanner's Enter adds it (handled in keydown) */ }
  } catch (e) { put(box, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}

function stockBadge(p) {
  const n = p.here;
  if (n <= 0) return html`<span class="badge bad">${t('pos.out')}</span>`;
  if (p.reorder_level && n <= p.reorder_level) return html`<span class="badge warn">${t('pos.left', { n: num(n) })}</span>`;
  return html`<span class="badge ok">${t('pos.left', { n: num(n) })}</span>`;
}

function drawResults() {
  const box = $('#pos-results', root);
  if (!results.length) {
    put(box, html`<div class="pos-empty">${empty('search', t('pos.noResults'), t('pos.noResultsHint'),
      can('products.edit') ? html`<a class="btn sm" href="#/products?new=1">${icon('plus')}${t('products.add')}</a>` : '')}</div>`);
    return;
  }
  put(box, html`${results.map((p, i) => html`<button class="tile ${i === focus ? 'focus' : ''}" role="option" aria-selected="${i === focus}" data-i="${i}">
    <span class="tile-top"><span class="tile-brand ellipsis">${p.brand || p.category || ''}</span>${p.track_serial ? icon('shield') : ''}</span>
    <span class="tile-name">${p.name}</span>
    <span class="tile-model ellipsis num">${p.model || p.sku}</span>
    <span class="tile-foot"><b class="tile-price money">${money(p.prices.retail)}</b>${stockBadge(p)}</span>
    ${p.shelves[cart.location_id] ? html`<span class="tile-shelf">${icon('pin')}${p.shelves[cart.location_id]}</span>` : ''}
  </button>`)}`);
  box.querySelector('.tile.focus')?.scrollIntoView({ block: 'nearest' });
}

async function add(p, fromKeyboard) {
  if (!p) return;
  let serial = null;
  if (p.track_serial) {
    serial = await chooseSerial(p);
    if (!serial) return;
    if (cart.lines.some((l) => l.serial === serial)) { toast(t('pos.serialInCart'), 'bad'); return; }
  }
  const same = !serial && cart.lines.find((l) => l.product_id === p.id && !l.serial);
  if (same) same.qty = Math.round((same.qty + 1) * 1000) / 1000;
  else cart.lines.push({ product_id: p.id, name: p.name, qty: 1, unit_price: p.prices.retail, list_price: p.prices.retail,
    min_price: p.prices.min, fractional: !!p.fractional, serial, unit: p.unit, warranty: p.warranty_months });
  if (prefs.get('sound')) tick(true);
  changed();
  const idx = same ? cart.lines.indexOf(same) : cart.lines.length - 1;
  pop($(`[data-line="${idx}"]`, root));
  if (fromKeyboard) { $('#pos-q').value = ''; search(''); }
  $('#pos-q')?.focus();
}

function chooseSerial(p) {
  return new Promise(async (resolve) => {
    const list = await api.get('/api/serials', { product_id: p.id, location_id: cart.location_id }).catch(() => []);
    const taken = new Set(cart.lines.map((l) => l.serial));
    const free = list.filter((s) => !taken.has(s.serial));
    open({
      title: t('pos.serialTitle', { name: p.name }),
      body: html`<p class="muted small">${t('pos.serialHint')}</p>
        <input class="input big num" id="sn" placeholder="${t('pos.serialScan')}" autocomplete="off" autofocus>
        ${free.length ? html`<div class="serial-list">${free.map((s) => html`<button class="chip num" data-sn="${s.serial}">${s.serial}</button>`)}</div>`
          : html`<div class="tip warn">${icon('alert')}<div>${t('pos.noSerials')}</div></div>`}`,
      mount(box, close) {
        const pick = (v) => {
          v = v.trim().toUpperCase();
          if (!free.some((s) => s.serial === v)) { shake($('#sn', box)); tick(false); toast(t('pos.serialNotFree', { s: v }), 'bad'); return; }
          close(v);
        };
        $('#sn', box).addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); pick(e.target.value); } });
        $$('[data-sn]', box).forEach((b) => b.addEventListener('click', () => pick(b.dataset.sn)));
      },
      onClose: (v) => resolve(v || null),
    });
  });
}

function onLineClick(e) {
  const b = e.target.closest('button[data-act]');
  if (!b) return;
  const i = +b.dataset.i, line = cart.lines[i];
  if (b.dataset.act === 'inc') line.qty = Math.round((line.qty + 1) * 1000) / 1000;
  else if (b.dataset.act === 'dec') line.qty = Math.max(line.fractional ? 0.001 : 1, Math.round((line.qty - 1) * 1000) / 1000);
  else if (b.dataset.act === 'del') cart.lines.splice(i, 1);
  else if (b.dataset.act === 'price') return priceDialog(i);
  changed();
}

function priceDialog(i) {
  const line = cart.lines[i];
  const max = S.me.max_discount_pct;
  open({
    title: line.name,
    body: html`<div class="cols form">
      <div class="field"><label for="np">${t('pos.unitPrice')}</label><input id="np" class="input big money-in" inputmode="decimal" value="${line.unit_price / 100}"></div>
      <div class="field"><label for="pct">${t('pos.discountPct')}</label><input id="pct" class="input big money-in" inputmode="decimal" placeholder="0"></div></div>
      <div class="row wrap small muted"><span>${t('pos.listPrice')}: ${moneyH(line.list_price)}</span>
        ${line.min_price ? html`<span>• ${t('pos.minPrice')}: ${moneyH(line.min_price)}</span>` : ''}
        <span>• ${t('pos.yourLimit', { n: max })}</span></div>
      <div class="tip">${icon('info')}<div>${t('pos.priceNote')}</div></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.apply')}</button>`,
    mount(box, close) {
      const np = $('#np', box), pct = $('#pct', box);
      pct.addEventListener('input', () => {
        const v = parseFloat(pct.value);
        if (v >= 0 && v < 100) np.value = (Math.round(line.list_price * (1 - v / 100)) / 100).toFixed(2).replace(/\.00$/, '');
      });
      const ok = () => {
        const v = parseMoney(np.value);
        if (v === null || v <= 0) { shake(np); return; }
        line.unit_price = v; close(); changed();
      };
      $('[data-ok]', box).addEventListener('click', ok);
      np.addEventListener('keydown', (e) => { if (e.key === 'Enter') ok(); });
    },
  });
}

function changed() { lastQuote = null; saveCart(); drawCart(); }

function drawCart() {
  const box = $('#lines', root);
  if (!box) return;
  if (!cart.lines.length) {
    put(box, html`<div class="cart-empty">${icon('cart')}<b>${t('pos.cartEmpty')}</b><span class="small muted">${t('pos.cartEmptyHint')}</span>
      <div class="keys small"><span><span class="kbd">F2</span> ${t('pos.k.search')}</span><span><span class="kbd">Enter</span> ${t('pos.k.add')}</span>
      <span><span class="kbd">F4</span> ${t('pos.k.pay')}</span><span><span class="kbd">F8</span> ${t('pos.park')}</span></div></div>`);
  } else {
    put(box, html`${cart.lines.map((l, i) => {
      const changedPrice = l.unit_price !== l.list_price;
      return html`<div class="line" data-line="${i}">
        <div class="line-main"><div class="line-name">${l.name}</div>
          <div class="line-sub">${l.serial ? html`<span class="badge info num">${icon('shield')}${l.serial}</span>` : ''}
          <button class="link-btn ${changedPrice ? 'changed' : ''}" data-act="price" data-i="${i}">${money(l.unit_price)}${changedPrice ? html` <s class="faint">${money(l.list_price)}</s>` : ''}</button></div></div>
        <div class="qty">${l.serial ? html`<span class="num qty-fixed">1</span>` : html`
          <button class="q-btn" data-act="dec" data-i="${i}" aria-label="${t('pos.less')}">${icon('minus')}</button>
          <input class="q-in num" data-qty="${i}" value="${num(l.qty)}" inputmode="decimal" aria-label="${t('f.qty')}">
          <button class="q-btn" data-act="inc" data-i="${i}" aria-label="${t('pos.more')}">${icon('plus')}</button>`}</div>
        <div class="line-total money num">${money(Math.round(l.qty * l.unit_price))}</div>
        <button class="icon-btn sm del" data-act="del" data-i="${i}" aria-label="${t('act.remove')}">${icon('trash')}</button>
      </div>`;
    })}`);
  }
  const sub = subtotal();
  const bar = $('#pos-mbar', root);
  if (bar) { bar.hidden = !cart.lines.length; $('#mbar-n', root).textContent = String(cart.lines.length); $('#mbar-t', root).textContent = money(total()); }
  put($('#totals', root), html`
    <div class="tot-row"><span>${t('pos.subtotal')}</span>${moneyH(sub)}</div>
    <div class="tot-row"><button class="link-btn" data-disc>${icon('percent')}${cart.discount ? t('pos.discount') : t('pos.addDiscount')}</button>
      ${cart.discount ? html`<span class="money num bad-ink">−${money(cart.discount)}</span>` : ''}</div>
    <div class="tot-big"><span>${t('pos.total')}</span><b class="num" id="grand">${money(total())}</b></div>
    <div class="row pay-row">
      ${cart.lines.length ? html`<button class="btn ghost" data-clear aria-label="${t('pos.clear')}">${icon('trash')}</button>` : ''}
      <button class="btn accent lg grow" data-pay data-guide="pos.pay" ${cart.lines.length ? '' : 'disabled'}>${t('pos.pay')}<span class="kbd">F4</span></button>
    </div>`);
  $('[data-pay]', root)?.addEventListener('click', pay);
  $('[data-disc]', root)?.addEventListener('click', discountDialog);
  $('[data-clear]', root)?.addEventListener('click', () => { cart = { ...blankCart(), location_id: cart.location_id }; changed(); $('#cust-name').textContent = t('pos.walkIn'); });
}

function discountDialog() {
  open({
    title: t('pos.orderDiscount'),
    body: html`${moneyH(subtotal())}<div class="cols form"><div class="field"><label for="d-amt">${t('f.amount')}</label>
      <input id="d-amt" class="input big money-in" inputmode="decimal" value="${cart.discount ? cart.discount / 100 : ''}"></div>
      <div class="field"><label for="d-pct">%</label><input id="d-pct" class="input big money-in" inputmode="decimal"></div></div>
      <p class="small muted">${t('pos.yourLimit', { n: S.me.max_discount_pct })}</p>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.apply')}</button>`,
    mount(box, close) {
      $('#d-pct', box).addEventListener('input', (e) => {
        const v = parseFloat(e.target.value);
        if (v >= 0 && v <= 100) $('#d-amt', box).value = (Math.round(subtotal() * v / 100) / 100).toString();
      });
      $('[data-ok]', box).addEventListener('click', () => {
        const v = parseMoney($('#d-amt', box).value || '0');
        if (v === null || v > subtotal()) { shake($('#d-amt', box)); return; }
        cart.discount = v; close(); changed();
      });
    },
  });
}

// ---------------------------------------------------------------- customers
function pickCustomer() {
  let found = [];
  open({
    title: t('pos.customer'),
    kind: 'panel',
    body: html`<input class="input big" id="c-q" placeholder="${t('customers.search')}" autofocus autocomplete="off">
      <div class="list" id="c-list"></div>
      ${cart.customer ? html`<button class="btn ghost" data-walkin>${icon('x')}${t('pos.walkIn')}</button>` : ''}
      <details class="card flat"><summary class="row">${icon('plus')}<b>${t('customers.new')}</b></summary>
        <div class="form"><div class="field"><label for="c-n">${t('f.name')}</label><input id="c-n" class="input"></div>
        <div class="field"><label for="c-p">${t('f.phone')}</label><input id="c-p" class="input num" inputmode="tel"></div>
        <div class="field"><label for="c-a">${t('f.address')}</label><input id="c-a" class="input"></div>
        <button class="btn primary" data-new>${t('act.save')}</button></div></details>`,
    mount(box, close) {
      const draw = () => put($('#c-list', box), html`${found.map((c, i) => html`<button class="li" data-c="${i}">${icon('user')}<span class="grow">
        <b>${c.name}</b><span class="small muted num"> ${c.phone}</span></span>${c.balance ? html`<span class="badge warn">${money(c.balance)}</span>` : ''}</button>`)}`);
      let timer;
      $('#c-q', box).addEventListener('input', (e) => {
        clearTimeout(timer);
        timer = setTimeout(async () => { found = (await api.get('/api/customers', { q: e.target.value }).catch(() => [])).slice(0, 30); draw(); }, 150);
      });
      $('#c-list', box).addEventListener('click', (e) => {
        const b = e.target.closest('[data-c]');
        if (!b) return;
        const c = found[+b.dataset.c];
        cart.customer = { id: c.id, name: c.name, phone: c.phone, balance: c.balance, credit_limit: c.credit_limit };
        saveCart(); $('#cust-name').textContent = c.name; close();
      });
      $('[data-walkin]', box)?.addEventListener('click', () => { cart.customer = null; saveCart(); $('#cust-name').textContent = t('pos.walkIn'); close(); });
      $('[data-new]', box).addEventListener('click', async (e) => {
        const name = $('#c-n', box).value.trim();
        if (!name) { shake($('#c-n', box)); return; }
        try {
          const r = await api.post('/api/customer/save', { name, phone: $('#c-p', box).value, address: $('#c-a', box).value });
          cart.customer = { id: r.id, name, phone: $('#c-p', box).value, balance: 0, credit_limit: 0 };
          saveCart(); $('#cust-name').textContent = name; toast(t('saved')); close();
        } catch (err) { fail(err); }
      });
      api.get('/api/customers').then((r) => { found = r.slice(0, 30); draw(); }).catch(() => {});
    },
  });
}

// ---------------------------------------------------------------- parking a sale
function park() {
  if (!cart.lines.length) { toast(t('pos.nothingToPark'), 'bad'); return; }
  const list = parked();
  list.unshift({ at: Date.now(), cart, label: cart.customer?.name || money(total()) });
  setParked(list.slice(0, 8));
  cart = { ...blankCart(), location_id: cart.location_id };
  changed();
  $('#cust-name').textContent = t('pos.walkIn');
  drawParked();
  toast(t('pos.parked'));
}
function drawParked() {
  const list = parked();
  const box = $('#parked', root);
  if (!box) return;
  put(box, list.length ? html`<div class="parked">${icon('clock')}${list.map((p, i) => html`<button class="chip" data-unpark="${i}">${p.label}</button>`)}</div>` : '');
  $$('[data-unpark]', box).forEach((b) => b.addEventListener('click', () => {
    const l = parked();
    const [p] = l.splice(+b.dataset.unpark, 1);
    if (cart.lines.length) l.unshift({ at: Date.now(), cart, label: cart.customer?.name || money(total()) });
    setParked(l);
    cart = p.cart;
    changed();
    $('#cust-name').textContent = cart.customer?.name || t('pos.walkIn');
    drawParked();
  }));
}

// ---------------------------------------------------------------- paying
const METHODS = [['cash', 'cash'], ['card', 'card'], ['wallet', 'phone'], ['instapay', 'qr'], ['finance', 'instal'], ['account', 'user'], ['installment', 'calendar'], ['split', 'layers']];

function pay() {
  if (!cart.lines.length || document.querySelector('.scrim')) return;
  const cfg = S.lookups?.settings || {};
  const state = { method: 'cash', received: null, provider: (cfg.finance_providers || [])[0] || '', months: 12, down: null, first_due: null,
    guarantor: {}, split: [{ method: 'cash', amount: null }, { method: 'card', amount: null }] };
  const methods = METHODS.filter(([m]) => (['account', 'installment'].includes(m) ? can('pos.credit') : true));
  open({
    title: t('pos.payTitle'),
    kind: 'sheet',
    body: html`<div class="pay">
      <div class="pay-total"><span>${t('pos.total')}</span><b class="num" id="pay-total">${money(total())}</b></div>
      <div class="pay-methods" role="radiogroup" aria-label="${t('pos.method')}">${methods.map(([m, ic]) =>
        html`<button class="pm" role="radio" data-m="${m}" aria-checked="${m === 'cash'}">${icon(ic)}<span>${t('pay.' + m)}</span></button>`)}</div>
      <div id="pay-body"></div>
      <p class="err small" id="pay-err" role="alert"></p>
    </div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.back')}</button><button class="btn accent lg grow" data-confirm data-guide="pos.confirm">${icon('check')}${t('pos.confirm')}</button>`,
    mount(box, close) {
      const body = $('#pay-body', box);
      const draw = async () => {
        const m = state.method;
        if (m === 'cash') {
          const tot = total();
          const quick = [...new Set([tot, Math.ceil(tot / 5000) * 5000, Math.ceil(tot / 10000) * 10000, Math.ceil(tot / 20000) * 20000])].slice(0, 4);
          put(body, html`<div class="stack"><div class="field"><label for="recv">${t('pos.received')}</label>
            <input id="recv" class="input big money-in" data-guide="pos.received" inputmode="decimal" placeholder="${(tot / 100).toString()}" autofocus></div>
            <div class="row wrap">${quick.map((v) => html`<button class="chip num" data-q="${v}">${money(v)}</button>`)}</div>
            <div class="change"><span>${t('pos.change')}</span><b class="num" id="change" data-guide="pos.change">—</b></div></div>`);
          const recv = $('#recv', body);
          const upd = () => {
            const v = parseMoney(recv.value);
            state.received = v;
            $('#change', body).textContent = v !== null && v >= tot ? money(v - tot) : '—';
            $('#change', body).parentElement.classList.toggle('short', v !== null && v < tot);
          };
          recv.addEventListener('input', upd);
          recv.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); confirmPay(); } });
          $$('[data-q]', body).forEach((b) => b.addEventListener('click', () => { recv.value = (+b.dataset.q / 100).toString(); upd(); }));
          setTimeout(() => recv.focus(), 30);
        } else if (m === 'finance') {
          put(body, html`<div class="field"><label for="prov">${t('pos.provider')}</label><select id="prov" class="input big">${(cfg.finance_providers || []).map((p) =>
            html`<option ${p === state.provider ? 'selected' : ''}>${p}</option>`)}</select></div>
            <div class="tip">${icon('info')}<div>${t('pos.financeNote')}</div></div>`);
          $('#prov', body).addEventListener('change', (e) => { state.provider = e.target.value; });
        } else if (m === 'account') {
          put(body, cart.customer ? html`<div class="tip">${icon('user')}<div><b>${cart.customer.name}</b> — ${t('pos.accountNote', { b: money(cart.customer.balance || 0) })}
            ${cart.customer.credit_limit ? html`<br>${t('pos.creditLimit', { l: money(cart.customer.credit_limit) })}` : ''}</div></div>`
            : html`<div class="tip warn">${icon('alert')}<div>${t('pos.needCustomer')}</div></div><button class="btn" data-pickc>${icon('user')}${t('pos.chooseCustomer')}</button>`);
          $('[data-pickc]', body)?.addEventListener('click', () => { close(); pickCustomer(); });
        } else if (m === 'installment') {
          if (!cart.customer) {
            put(body, html`<div class="tip warn">${icon('alert')}<div>${t('pos.needCustomer')}</div></div><button class="btn" data-pickc>${icon('user')}${t('pos.chooseCustomer')}</button>`);
            $('[data-pickc]', body).addEventListener('click', () => { close(); pickCustomer(); });
            return;
          }
          const minDown = Math.ceil(total() * (cfg.min_down_payment_pct || 0) / 100 / 100) * 100;
          if (state.down === null) state.down = minDown;
          if (!state.first_due) { const d = new Date(); d.setMonth(d.getMonth() + 1); state.first_due = d.toISOString().slice(0, 10); }
          const opts = [3, 6, 10, 12, 18, 24].filter((n) => n <= (cfg.max_instalment_months || 24));
          put(body, html`<div class="form">
            <div class="field"><span class="label">${t('pos.months')}</span><div class="seg">${opts.map((n) =>
              html`<button type="button" data-months="${n}" aria-pressed="${n === state.months}">${n}</button>`)}</div></div>
            <div class="cols"><div class="field"><label for="down">${t('pos.down')}</label><input id="down" class="input big money-in" inputmode="decimal" value="${state.down / 100}">
              <span class="hint">${t('pos.minDown', { p: cfg.min_down_payment_pct, m: money(minDown) })}</span></div>
            <div class="field"><label for="fdue">${t('pos.firstDue')}</label><input id="fdue" type="date" class="input big" value="${state.first_due}" min="${today()}"></div></div>
            <div class="cols"><div class="field"><label for="g-n">${t('pos.guarantor')}</label><input id="g-n" class="input" value="${state.guarantor.name || ''}"></div>
            <div class="field"><label for="g-p">${t('pos.guarantorPhone')}</label><input id="g-p" class="input num" inputmode="tel" value="${state.guarantor.phone || ''}"></div></div>
            <div class="plan-sum" id="plan-sum">${t('state.loading')}</div></div>`);
          const recalc = () => { state.quoting = requote(); return state.quoting; };
          const requote = async () => {
            state.down = parseMoney($('#down', body).value || '0') ?? 0;
            try {
              lastQuote = await api.post('/api/pos/quote', { lines: payloadLines(), discount: cart.discount, location_id: cart.location_id,
                instalment: { months: state.months, down: state.down } });
              put($('#plan-sum', body), html`<div class="plan-grid"><div><span>${t('pos.financed')}</span><b class="num">${money(lastQuote.total - lastQuote.fee - state.down)}</b></div>
                <div><span>${t('pos.fee')}</span><b class="num">${money(lastQuote.fee)}</b></div>
                <div><span>${t('pos.monthly')}</span><b class="num">${money(lastQuote.monthly)}</b></div>
                <div><span>${t('pos.totalWithFee')}</span><b class="num">${money(lastQuote.total)}</b></div></div>`);
              $('#pay-total', box).textContent = money(lastQuote.total);
            } catch (e) { put($('#plan-sum', body), html`<span class="err">${errorText(e)}</span>`); }
          };
          $$('[data-months]', body).forEach((b) => b.addEventListener('click', () => { state.months = +b.dataset.months; $$('[data-months]', body).forEach((x) => x.setAttribute('aria-pressed', String(x === b))); recalc(); }));
          $('#down', body).addEventListener('change', recalc);
          $('#fdue', body).addEventListener('change', (e) => { state.first_due = e.target.value; });
          $('#g-n', body).addEventListener('input', (e) => { state.guarantor.name = e.target.value; });
          $('#g-p', body).addEventListener('input', (e) => { state.guarantor.phone = e.target.value; });
          recalc();
        } else if (m === 'split') {
          const drawSplit = () => {
            const paid = state.split.reduce((a, r) => a + (r.amount || 0), 0);
            put(body, html`<div class="stack tight">${state.split.map((r, i) => html`<div class="row">
              <select class="input" data-sm="${i}">${['cash', 'card', 'wallet', 'instapay', 'finance', ...(can('pos.credit') ? ['account'] : [])].map((mm) =>
                html`<option value="${mm}" ${mm === r.method ? 'selected' : ''}>${t('pay.' + mm)}</option>`)}</select>
              <input class="input money-in" data-sa="${i}" inputmode="decimal" value="${r.amount !== null ? r.amount / 100 : ''}" placeholder="0">
              <button class="icon-btn" data-sx="${i}" aria-label="${t('act.remove')}">${icon('x')}</button></div>`)}
              <button class="btn sm ghost" data-sadd>${icon('plus')}${t('pos.addMethod')}</button>
              <div class="change ${paid === total() ? '' : 'short'}"><span>${t('pos.remaining')}</span><b class="num">${money(total() - paid)}</b></div></div>`);
            $$('[data-sm]', body).forEach((s) => s.addEventListener('change', (e) => { state.split[+e.target.dataset.sm].method = e.target.value; }));
            $$('[data-sa]', body).forEach((s) => s.addEventListener('change', (e) => { state.split[+e.target.dataset.sa].amount = parseMoney(e.target.value || '0'); drawSplit(); }));
            $$('[data-sx]', body).forEach((s) => s.addEventListener('click', () => { state.split.splice(+s.dataset.sx, 1); drawSplit(); }));
            $('[data-sadd]', body).addEventListener('click', () => {
              const paid2 = state.split.reduce((a, r) => a + (r.amount || 0), 0);
              state.split.push({ method: 'cash', amount: Math.max(0, total() - paid2) }); drawSplit();
            });
          };
          if (state.split[0].amount === null) state.split[0].amount = total();
          drawSplit();
        } else {
          put(body, html`<div class="tip">${icon('info')}<div>${t('pos.nonCashNote')}</div></div>`);
        }
        if (m !== 'installment') { lastQuote = null; $('#pay-total', box).textContent = money(total()); }
      };
      $$('.pm', box).forEach((b) => b.addEventListener('click', () => {
        state.method = b.dataset.m;
        $$('.pm', box).forEach((x) => x.setAttribute('aria-checked', String(x === b)));
        draw();
      }));
      const confirmPay = async () => {
        const btn = $('[data-confirm]', box);
        if (btn.getAttribute('aria-busy')) return;
        $('#pay-err', box).textContent = '';
        const tot = total();
        let payments, extra = {};
        const m = state.method;
        if (m === 'cash') {
          if (state.received !== null && state.received < tot) { $('#pay-err', box).textContent = t('pos.receivedShort'); shake($('#recv', box)); return; }
          payments = [{ method: 'cash', amount: tot }];
          extra.cash_received = state.received ?? tot;
        } else if (m === 'finance') payments = [{ method: 'finance', provider: state.provider, amount: tot }];
        else if (m === 'installment') {
          if (!cart.customer) return;
          await state.quoting;  // the down payment may have just been edited: use the quote that matches it
          if (!lastQuote) { $('#pay-err', box).textContent = t('state.loading'); return; }
          payments = [...(state.down ? [{ method: 'cash', amount: state.down }] : []), { method: 'installment', amount: lastQuote.total - state.down }];
          extra.instalment = { months: state.months, first_due: state.first_due, guarantor: state.guarantor };
        } else if (m === 'split') {
          payments = state.split.filter((r) => r.amount).map((r) => ({ method: r.method, amount: r.amount, provider: r.method === 'finance' ? state.provider : undefined }));
          if (payments.reduce((a, r) => a + r.amount, 0) !== tot) { $('#pay-err', box).textContent = t('pos.splitMismatch'); return; }
        } else payments = [{ method: m, amount: tot }];
        btn.setAttribute('aria-busy', 'true');
        try {
          const base = { lines: payloadLines(), discount: cart.discount, payments, customer_id: cart.customer?.id,
            location_id: cart.location_id, ...(extra.instalment ? { instalment: extra.instalment } : {}) };
          const idem = idemFor(base);
          const r = await withApproval((approval) => api.post('/api/pos/sell', { idem_key: idem, ...base, approval, ...extra }));
          close();
          signal('sale.done');
          done(r, extra.cash_received);
        } catch (e) {
          if (!e.cancelled) showError($('#pay-err', box), e);
        } finally { btn.removeAttribute('aria-busy'); }
      };
      $('[data-confirm]', box).addEventListener('click', confirmPay);
      draw();
    },
  });
}

const payloadLines = () => cart.lines.map((l) => ({ product_id: l.product_id, qty: l.qty, unit_price: l.unit_price, serial: l.serial || undefined }));

async function done(r, received) {
  pending = null;
  const customer = cart.customer;
  cart = { ...blankCart(), location_id: cart.location_id };
  changed();
  $('#cust-name').textContent = t('pos.walkIn');
  const sale = await api.get('/api/sale', { id: r.id }).catch(() => null);
  if (sale) sale.change = r.change;
  open({
    title: '',
    body: html`<div class="done">
      <div class="done-mark">${icon('check')}</div>
      <h2>${t('pos.done')}</h2><p class="muted num">${r.number}</p>
      <div class="done-total num">${money(r.total)}</div>
      ${r.change ? html`<div class="done-change"><span>${t('pos.change')}</span><b class="num">${money(r.change)}</b></div>` : ''}
    </div>`,
    foot: html`${customer?.phone && sale ? html`<a class="btn" target="_blank" rel="noopener" href="${whatsapp(customer.phone, t('pos.waText', { n: r.number, tot: money(r.total), shop: S.lookups?.settings?.shop_name || '' }))}">${icon('message')}${t('pos.whatsapp')}</a>` : ''}
      <button class="btn" data-print>${icon('print')}${t('pos.print')}<span class="kbd">P</span></button>
      <button class="btn accent grow" data-close autofocus>${t('pos.next')}<span class="kbd">Enter</span></button>`,
    mount(box, close) {
      $('[data-print]', box).addEventListener('click', () => sale && printReceipt(sale));
      box.addEventListener('keydown', (e) => { if (e.key.toLowerCase() === 'p' && sale) { e.preventDefault(); printReceipt(sale); } });
    },
    onClose: () => { $('#pos-q')?.focus(); search(''); },
  });
  void received;
}

export const _go = go;
