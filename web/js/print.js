// Paper: the 80 mm / 58 mm receipt and A4 pages. Printed from a hidden area; the page's print style shows only it.
import { S } from './app.js';
import { t } from './i18n.js';
import { barcodeSVG } from './barcode.js';
import { html, put, money, date, num, raw } from './ui.js';

function area() {
  let el = document.getElementById('print-area');
  if (!el) { el = document.createElement('div'); el.id = 'print-area'; document.body.appendChild(el); }
  return el;
}

export function printHTML(content, kind = 'receipt') {
  const el = area();
  const width = String(S.lookups?.settings?.receipt_width || '80');
  el.className = kind === 'receipt' ? `receipt w${width}` : kind === 'labels' ? 'labels' : 'a4';
  document.documentElement.dataset.print = kind === 'receipt' ? `r${width}` : kind === 'labels' ? 'labels' : 'a4';
  put(el, content);
  setTimeout(() => { window.print(); }, 60);
}

const METHOD = (m, p) => t('pay.' + m) + (p ? ` (${p})` : '');

export function receiptHTML(sale) {
  const cfg = S.lookups?.settings || {};
  const practice = S.boot?.practice;
  const warranty = sale.lines.filter((l) => l.warranty_until);
  return html`<div class="rc">
    ${practice ? html`<div class="rc-practice">${t('app.practice')} — ${t('print.notReceipt')}</div>` : ''}
    <div class="rc-head"><b class="rc-shop">${cfg.shop_name || ''}</b>
      ${cfg.shop_address ? html`<div>${cfg.shop_address}</div>` : ''}${cfg.shop_phone ? html`<div class="num">${cfg.shop_phone}</div>` : ''}
      ${cfg.tax_number ? html`<div>${t('print.taxNo')}: <span class="num">${cfg.tax_number}</span></div>` : ''}</div>
    <div class="rc-meta"><div><span>${t('print.invoice')}</span><b class="num">${sale.number}</b></div>
      <div><span>${t('f.date')}</span><span class="num">${date(sale.at, true)}</span></div>
      <div><span>${t('print.cashier')}</span><span>${sale.by_name}</span></div>
      ${sale.customer ? html`<div><span>${t('f.customer')}</span><span>${sale.customer}</span></div>` : ''}</div>
    <table class="rc-lines"><tbody>${sale.lines.map((l) => html`<tr><td colspan="3" class="rc-name">${l.name}${l.serial ? html` <span class="num">#${l.serial}</span>` : ''}</td></tr>
      <tr class="rc-calc"><td class="num">${num(l.qty)} × ${money(l.unit_price, { bare: true })}</td><td></td><td class="num end">${money(l.line_total, { bare: true })}</td></tr>`)}</tbody></table>
    <div class="rc-totals">
      <div><span>${t('pos.subtotal')}</span><span class="num">${money(sale.subtotal, { bare: true })}</span></div>
      ${sale.discount ? html`<div><span>${t('pos.discount')}</span><span class="num">−${money(sale.discount, { bare: true })}</span></div>` : ''}
      ${sale.fee ? html`<div><span>${t('pos.fee')}</span><span class="num">${money(sale.fee, { bare: true })}</span></div>` : ''}
      <div class="rc-total"><span>${t('pos.total')}</span><span class="num">${money(sale.total)}</span></div>
      ${sale.tenders.map((x) => html`<div><span>${METHOD(x.method, x.provider)}</span><span class="num">${money(x.amount, { bare: true })}</span></div>`)}
      ${sale.change ? html`<div><span>${t('pos.change')}</span><span class="num">${money(sale.change, { bare: true })}</span></div>` : ''}
    </div>
    ${sale.plan ? html`<div class="rc-box"><b>${t('print.plan')}</b><div>${t('print.planLine', { n: sale.plan.months, m: money(sale.plan.monthly), d: date(sale.plan.first_due) })}</div></div>` : ''}
    ${warranty.length ? html`<div class="rc-box"><b>${t('print.warranty')}</b>${warranty.map((l) =>
      html`<div>${l.name}${l.serial ? html` <span class="num">#${l.serial}</span>` : ''}: ${t('print.until')} <span class="num">${date(l.warranty_until)}</span></div>`)}</div>` : ''}
    <div class="rc-policy">${t('print.policy', { r: cfg.return_days ?? 14, d: cfg.defect_days ?? 30 })}</div>
    ${cfg.wallet_number ? html`<div class="rc-policy">${t('print.wallet')}: <span class="num">${cfg.wallet_number}</span></div>` : ''}
    <div class="rc-foot">${cfg.receipt_footer || ''}</div>
    <div class="rc-barcode">${raw(barcodeSVG(sale.number, { height: 36, module: 1.4 }))}<span class="num">${sale.number}</span></div>
  </div>`;
}

export function printReceipt(sale) { printHTML(receiptHTML(sale), 'receipt'); }

/** Sticker labels (4 across on A4): one per copy, or one per serial number for appliances. Barcode = the product's first barcode, else its SKU. */
export function labelsHTML(p, { copies = 1, serials = false } = {}) {
  const shop = S.lookups?.settings?.shop_name || '';
  const code = p.barcodes?.[0] || p.sku;
  const items = serials ? p.serials.map((x) => ({ code: x.serial, caption: x.serial })) : Array.from({ length: copies }, () => ({ code, caption: code }));
  return html`<div class="labels-sheet">${items.map((it) => html`<div class="label">
    <div class="label-shop ellipsis">${shop}</div><div class="label-name">${p.name}</div>
    <div class="label-price num">${money(p.prices.retail)}</div>
    <div class="label-code">${raw(barcodeSVG(it.code, { height: 30, module: 1.2 }))}<span class="num">${it.caption}</span></div></div>`)}</div>`;
}
export function printLabels(p, opts) { printHTML(labelsHTML(p, opts), 'labels'); }
