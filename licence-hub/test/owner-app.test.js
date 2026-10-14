import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  showIssuedCode, readGrant, tierPickerHtml, presetPaidUntil, mountOfflineTier, approveAfterReissueConfirm,
  defaultTierSelection, customerTierLabelAr, downgradeConfirmMessageAr,
} from '../public/owner/app.js';

function panelEl() {
  const listeners = {};
  return {
    hidden: true,
    innerHTML: '',
    dataset: {},
    querySelector(sel) {
      if (sel === '[data-copy]') return { addEventListener: (ev, fn) => { listeners.copy = fn; } };
      if (sel === '[data-dismiss]') return { addEventListener: (ev, fn) => { listeners.dismiss = fn; } };
      return null;
    },
    listeners,
  };
}

test('approveAfterReissueConfirm aborts when owner cancels reissue confirm', () => {
  assert.deepEqual(approveAfterReissueConfirm(true, false), { abort: true, force: false });
  assert.deepEqual(approveAfterReissueConfirm(true, true), { abort: false, force: false });
  assert.deepEqual(approveAfterReissueConfirm(false, false), { abort: false, force: false });
});

test('downgradeConfirmMessageAr includes current paid term', () => {
  const msg = downgradeConfirmMessageAr({ tier: 'paid', until: '2028-06-01' });
  assert.match(msg, /2028-06-01/);
  assert.match(msg, /الترخيص الحالي/);
});

test('issued code panel is outside the pending list and stays after refresh', () => {
  const pending = { innerHTML: '<li>old</li>' };
  const issued = panelEl();
  const host = {
    querySelector(sel) {
      if (sel === '[data-pending]') return pending;
      if (sel === '[data-issued]') return issued;
      return null;
    },
  };
  showIssuedCode(host, 'CODE-123', 'req-1');
  assert.equal(issued.hidden, false);
  assert.match(issued.innerHTML, /CODE-123/);
  pending.innerHTML = '<li class="muted">لا توجد طلبات معلّقة.</li>';
  assert.match(issued.innerHTML, /CODE-123/);
  assert.equal(issued.dataset.requestId, 'req-1');
});

test('tier picker preselects grant from request kind', () => {
  const monthly = tierPickerHtml(false, '', 'req-m', 'monthly');
  assert.match(monthly, /value="paid"[^>]*checked/);
  assert.doesNotMatch(monthly, /value="trial"[^>]*checked/);
  const perm = tierPickerHtml(false, '', 'req-p', 'permanent');
  assert.match(perm, /value="permanent"[^>]*checked/);
  assert.deepEqual(defaultTierSelection('monthly').tier, 'paid');
});

test('tier picker falls back to trial when paid radios are disabled', () => {
  const monthly = tierPickerHtml(true, '', 'req-m', 'monthly');
  assert.match(monthly, /value="trial"[^>]*checked/);
  assert.doesNotMatch(monthly, /value="paid"[^>]*checked/);
  assert.deepEqual(defaultTierSelection('monthly', false).tier, 'trial');
});

test('customerTierLabelAr shows trial paid and permanent', () => {
  assert.equal(customerTierLabelAr({ licence_tier: 'trial' }), 'تجربة');
  assert.equal(customerTierLabelAr({ licence_tier: 'paid', licence_expiry: '2028-01-15' }), 'مدفوع حتى 2028-01-15');
  assert.equal(customerTierLabelAr({ licence_tier: 'permanent' }), 'دائم');
});

test('tier picker uses unique radio group names per request', () => {
  const a = tierPickerHtml(false, '', 'req-a');
  const b = tierPickerHtml(false, '', 'req-b');
  assert.match(a, /name="tier-req-a"/);
  assert.match(b, /name="tier-req-b"/);
});

test('readGrant uses the checked radio inside its card', () => {
  const root = {
    querySelector(sel) {
      if (sel === '[data-tier-form]') return form;
      return null;
    },
  };
  const form = {
    querySelector(sel) {
      if (sel === 'input[type="radio"]:checked') return { value: 'paid' };
      if (sel === '[data-paid-until]') return { value: '2027-01-15' };
      return null;
    },
  };
  assert.deepEqual(readGrant(root), { grant: 'paid', paid_until: '2027-01-15' });
});

test('offline submit stays disabled until product list is loaded', async (t) => {
  t.mock.method(globalThis, 'fetch', async (url) => {
    const path = String(url);
    if (path.includes('/session')) return { status: 200, json: async () => ({ csrf: 'x' }) };
    if (path.includes('/capabilities')) return { status: 200, json: async () => ({ products: { 'trip-orders': { paid_available: true } } }) };
    if (path.includes('/products')) return { status: 200, json: async () => ({ products: ['trip-orders'] }) };
    return { status: 404, json: async () => ({}) };
  });
  const tierWrap = { innerHTML: '', querySelector: () => null };
  const slot = {
    querySelector(sel) {
      if (sel === '[data-tier-slot-tier]') return tierWrap;
      if (sel === '[name="product"]') return { value: 'trip-orders', addEventListener: () => {} };
      return null;
    },
    set innerHTML(_v) { /* slot filled */ },
    get innerHTML() { return ''; },
  };
  const submit = { disabled: true };
  const form = { querySelector: (sel) => (sel === 'button[type="submit"]' ? submit : null) };
  const host = {
    querySelector(sel) {
      if (sel === '[data-tier-slot]') return slot;
      if (sel === '#offline-form') return form;
      return null;
    },
  };
  mountOfflineTier(host);
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(submit.disabled, false);
});

test('presetPaidUntil clamps month overflow from Cairo today', () => {
  const orig = Date.prototype.toLocaleDateString;
  Date.prototype.toLocaleDateString = function (locales, opts) {
    if (opts && opts.timeZone === 'Africa/Cairo') return '2026-01-31';
    return orig.call(this, locales, opts);
  };
  assert.equal(presetPaidUntil('1m'), '2026-02-28');
  Date.prototype.toLocaleDateString = orig;
});
