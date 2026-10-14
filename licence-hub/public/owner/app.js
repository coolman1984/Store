'use strict';

const CALENDAR_TZ = 'Africa/Cairo';

function calendarTodayCairo() {
  return new Date().toLocaleDateString('en-CA', { timeZone: CALENDAR_TZ });
}

function daysInMonth(year, month1to12) {
  return new Date(Date.UTC(year, month1to12, 0)).getUTCDate();
}

function addCalendarMonths(iso, months) {
  const [y, m, d] = iso.split('-').map(Number);
  let year = y;
  let month = m - 1 + months;
  year += Math.floor(month / 12);
  month = ((month % 12) + 12) % 12;
  const last = daysInMonth(year, month + 1);
  const day = Math.min(d, last);
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}

async function api(path, opts) {
  const r = await fetch('/owner/api' + path, { credentials: 'same-origin', ...opts });
  if (r.status === 401) { location.href = '/owner/login.html'; return null; }
  return r.json();
}

let csrf = '';
let paidAvailable = false;
let productCapabilities = {};
let productFilter = '';

/** Reissue confirm: cancel must not POST approve; force is only for explicit downgrade override (regression-tested). */
export function approveAfterReissueConfirm(hasCustomer, userConfirmed) {
  if (hasCustomer && !userConfirmed) return { abort: true, force: false };
  return { abort: false, force: false };
}

export function downgradeConfirmMessageAr(current) {
  const tier = String(current?.tier || '').trim().toLowerCase();
  let label = 'تجربة';
  if (tier === 'permanent') label = 'دائم';
  else if (tier === 'paid') {
    const until = String(current?.until || '').trim();
    label = until ? `مدفوع حتى ${until}` : 'مدفوع';
  }
  return `الترخيص الحالي: ${label}. تحذير: هذا الإجراء يخفّض الترخيص (مدفوع أو دائم إلى تجربة أو مدة أقصر). هل تريد المتابعة؟`;
}

export function defaultTierSelection(requestKind, paidAvailable = true) {
  if (!paidAvailable) return { tier: 'trial' };
  if (requestKind === 'permanent') return { tier: 'permanent' };
  if (requestKind === 'monthly') return { tier: 'paid', paidUntil: presetPaidUntil('1m') };
  return { tier: 'trial' };
}

export function customerTierLabelAr(item) {
  const tier = String(item.licence_tier || item.kind || '').trim().toLowerCase();
  if (tier === 'permanent') return 'دائم';
  if (tier === 'paid' || tier === 'monthly') {
    const until = String(item.licence_expiry || item.last_day || '').trim();
    return until ? ('مدفوع حتى ' + until) : 'مدفوع';
  }
  return 'تجربة';
}

export function productLabelAr(productId) {
  if (productId === 'trip-orders') return 'طلبات الرحلات (يوسف)';
  if (productId === 'al-store') return 'المتجر';
  return productId;
}

async function session() {
  const s = await api('/session');
  if (s) csrf = s.csrf || '';
  const cap = await api('/capabilities');
  if (cap) {
    paidAvailable = Boolean(cap.paid_available);
    productCapabilities = cap.products || {};
  }
  return s;
}

function paidForProduct(productId) {
  const id = productId || 'trip-orders';
  const row = productCapabilities[id];
  if (row) return Boolean(row.paid_available);
  return paidAvailable;
}

function headers() {
  return { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf };
}

function escape(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function kindLabelAr(kind) {
  if (kind === 'trial') return 'تجربة';
  if (kind === 'monthly') return 'اشتراك مدفوع';
  if (kind === 'permanent') return 'دائم';
  return kind;
}

export function tierPickerHtml(disabledPaid, customDate, requestId, requestKind) {
  const tierName = 'tier-' + (requestId || 'offline');
  const sel = defaultTierSelection(requestKind, !disabledPaid);
  const paidOff = disabledPaid ? ' disabled' : '';
  const paidMsg = disabledPaid
    ? '<p class="err">إصدار المدفوع غير متاح — أضف PAID_SIGNING_KEY في Cloudflare.</p>' : '';
  const trialChecked = sel.tier === 'trial' ? ' checked' : '';
  const paidChecked = sel.tier === 'paid' ? ' checked' : '';
  const permChecked = sel.tier === 'permanent' ? ' checked' : '';
  const paidBoxHidden = sel.tier === 'paid' ? '' : ' hidden';
  const dateVal = escape(customDate || sel.paidUntil || '');
  return paidMsg + '<fieldset class="tier-pick" data-tier-form>' +
    '<legend>نوع الترخيص</legend>' +
    '<label class="tier-opt"><input type="radio" name="' + escape(tierName) + '" value="trial"' + trialChecked + '> تجربة ١٤ يوماً</label>' +
    '<label class="tier-opt"><input type="radio" name="' + escape(tierName) + '" value="paid"' + paidOff + paidChecked + '> مدفوع حتى تاريخ</label>' +
    '<div class="tier-paid" data-paid-opts' + paidBoxHidden + '>' +
    '<div class="row wrap">' +
    '<button type="button" class="btn sm" data-preset="1m">شهر</button>' +
    '<button type="button" class="btn sm" data-preset="3m">٣ أشهر</button>' +
    '<button type="button" class="btn sm" data-preset="6m">٦ أشهر</button>' +
    '<button type="button" class="btn sm" data-preset="1y">سنة</button>' +
    '</div>' +
    '<div class="field"><label>تاريخ الانتهاء</label><input type="date" data-paid-until dir="ltr" value="' + dateVal + '"></div>' +
    '</div>' +
    '<label class="tier-opt"><input type="radio" name="' + escape(tierName) + '" value="permanent"' + paidOff + permChecked + '> دائم</label>' +
    '</fieldset>';
}

export function presetPaidUntil(preset) {
  const months = { '1m': 1, '3m': 3, '6m': 6, '1y': 12 }[preset];
  if (!months) return '';
  return addCalendarMonths(calendarTodayCairo(), months);
}

function wireTierForm(root) {
  const form = root.querySelector('[data-tier-form]');
  if (!form) return;
  const paidBox = form.querySelector('[data-paid-opts]');
  const tierRadios = form.querySelectorAll('input[type="radio"][value="trial"], input[type="radio"][value="paid"], input[type="radio"][value="permanent"]');
  tierRadios.forEach((radio) => {
    radio.addEventListener('change', () => {
      if (paidBox) paidBox.hidden = form.querySelector('input[value="paid"]:checked') == null;
    });
  });
  form.querySelectorAll('[data-preset]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const preset = btn.getAttribute('data-preset');
      const iso = presetPaidUntil(preset);
      const inp = form.querySelector('[data-paid-until]');
      if (inp) inp.value = iso;
      const paidRadio = form.querySelector('input[value="paid"]');
      if (paidRadio) paidRadio.checked = true;
      if (paidBox) paidBox.hidden = false;
    });
  });
}

export function readGrant(root) {
  const form = root.querySelector('[data-tier-form]');
  if (!form) return { grant: 'trial' };
  const tier = form.querySelector('input[type="radio"]:checked');
  const val = tier ? tier.value : 'trial';
  if (val === 'permanent') return { grant: 'permanent' };
  if (val === 'paid') {
    const until = form.querySelector('[data-paid-until]');
    return { grant: 'paid', paid_until: until ? until.value : '' };
  }
  return { grant: 'trial' };
}

export function showIssuedCode(host, code, requestId) {
  const panel = host.querySelector('[data-issued]');
  if (!panel) return;
  panel.hidden = false;
  panel.innerHTML = '<p class="muted">اقرأ هذا الكود للعميل:</p><p class="big-code" dir="ltr">' + escape(code) + '</p><button type="button" class="btn" data-copy>نسخ</button><button type="button" class="btn" data-dismiss>إغلاق</button>';
  panel.querySelector('[data-copy]').addEventListener('click', () => navigator.clipboard.writeText(code));
  panel.querySelector('[data-dismiss]').addEventListener('click', () => { panel.hidden = true; panel.innerHTML = ''; });
  if (requestId) panel.dataset.requestId = requestId;
}

export async function loadUndelivered(host) {
  await session();
  const data = await api('/undelivered');
  if (!data) return;
  const wrap = host.querySelector('[data-undelivered-wrap]');
  const ul = host.querySelector('[data-undelivered]');
  if (!wrap || !ul) return;
  ul.innerHTML = '';
  if (!data.items.length) {
    wrap.hidden = true;
    return;
  }
  wrap.hidden = false;
  data.items.forEach((item) => {
    const li = document.createElement('li');
    const when = new Date(item.updated_at * 1000).toLocaleString('ar-EG');
    const prod = productLabelAr(item.product || 'trip-orders');
    li.innerHTML = '<div><strong>' + escape(item.shop || '—') + '</strong><div class="muted">' + escape(prod) + '</div><div class="muted" dir="ltr">' + escape(item.device) + '</div><div class="muted">' + when + '</div></div>';
    const btn = document.createElement('button');
    btn.className = 'btn primary';
    btn.type = 'button';
    btn.textContent = 'عرض الكود';
    btn.addEventListener('click', () => showIssuedCode(host, item.code, item.id));
    li.append(btn);
    ul.append(li);
  });
}

function productFilterHtml(items) {
  const ids = [...new Set(items.map((i) => i.product || 'trip-orders'))];
  if (ids.length < 2) return '';
  let opts = '<option value="">كل المنتجات</option>';
  ids.forEach((id) => {
    opts += '<option value="' + escape(id) + '">' + escape(productLabelAr(id)) + '</option>';
  });
  return '<div class="field"><label for="product-filter">المنتج</label><select id="product-filter" data-product-filter>' + opts + '</select></div>';
}

export async function loadPending(host) {
  await session();
  await loadUndelivered(host);
  const data = await api('/pending');
  if (!data) return;
  const ul = host.querySelector('[data-pending]');
  const filterSlot = host.querySelector('[data-product-filter-slot]');
  if (filterSlot) {
    filterSlot.innerHTML = productFilterHtml(data.items);
    const sel = filterSlot.querySelector('[data-product-filter]');
    if (sel) {
      sel.value = productFilter;
      sel.addEventListener('change', () => {
        productFilter = sel.value;
        renderPendingList(host, data.items.filter((i) => !productFilter || (i.product || 'trip-orders') === productFilter));
      });
    }
  }
  const filtered = productFilter
    ? data.items.filter((i) => (i.product || 'trip-orders') === productFilter)
    : data.items;
  renderPendingList(host, filtered);
}

function renderPendingList(host, items) {
  const ul = host.querySelector('[data-pending]');
  ul.innerHTML = '';
  if (!items.length) {
    ul.innerHTML = '<li class="muted">لا توجد طلبات معلّقة.</li>';
    return;
  }
  items.forEach((item) => {
    const disablePaid = !paidForProduct(item.product || 'trip-orders');
    const li = document.createElement('li');
    const when = new Date(item.created_at * 1000).toLocaleString('ar-EG');
    const kindLabel = kindLabelAr(item.kind);
    const prod = productLabelAr(item.product || 'trip-orders');
    const usedNote = item.has_customer ? '<div class="err">هذا الجهاز لديه عميل مسجّل — استخدم «إعادة إصدار» إن فُقد الكود.</div>' : '';
    li.innerHTML = '<div><strong>' + escape(item.shop || '—') + '</strong><div class="muted">' + escape(prod) + ' · ' + escape(kindLabel) + ' · <span dir="ltr">' + escape(item.device) + '</span></div>' + usedNote + '<div class="muted">' + when + '</div></div>';
    li.innerHTML += tierPickerHtml(disablePaid, '', item.id, item.kind);
    wireTierForm(li);
    const row = document.createElement('div');
    row.className = 'row';
    const ok = document.createElement('button');
    ok.className = 'btn primary';
    ok.type = 'button';
    ok.textContent = 'موافقة — إصدار الكود';
    ok.addEventListener('click', async () => {
      ok.disabled = true;
      const grant = readGrant(li);
      const opts = approveAfterReissueConfirm(item.has_customer, item.has_customer && confirm('إعادة إصدار لهذا الجهاز؟ (فقدان الكود فقط)'));
      if (opts.abort) {
        ok.disabled = false;
        return;
      }
      let force = opts.force;
      const approveBody = () => ({ id: item.id, csrf, force, ...grant });
      let res = await api('/approve', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify(approveBody()),
      });
      if (res && res.error === 'downgrade' && !force) {
        if (!confirm(downgradeConfirmMessageAr(res.current))) {
          ok.disabled = false;
          return;
        }
        force = true;
        res = await api('/approve', {
          method: 'POST',
          headers: headers(),
          body: JSON.stringify(approveBody()),
        });
      }
      if (res && (res.error === 'paid_key_missing' || res.message === 'paid_key_missing')) {
        alert('إصدار المدفوع غير متاح على الخادم — راجع PAID_SIGNING_KEY.');
        ok.disabled = false;
        return;
      }
      if (res && res.error === 'bad_device') {
        alert('رمز الجهاز غير صالح — ارفض الطلب.');
        ok.disabled = false;
        return;
      }
      if (res && res.error && !res.ok) {
        alert('تعذّرت الموافقة: ' + res.error);
        ok.disabled = false;
        return;
      }
      if (res && res.ok && res.code) showIssuedCode(host, res.code, item.id);
      loadPending(host);
    });
    const no = document.createElement('button');
    no.className = 'btn bad';
    no.type = 'button';
    no.textContent = 'رفض';
    no.addEventListener('click', async () => {
      no.disabled = true;
      await api('/refuse', { method: 'POST', headers: headers(), body: JSON.stringify({ id: item.id, csrf }) });
      loadPending(host);
    });
    row.append(ok, no);
    li.append(row);
    ul.append(li);
  });
}

export async function loadCustomers(host) {
  await session();
  const data = await api('/customers');
  if (!data) return;
  const ul = host.querySelector('[data-customers]');
  ul.innerHTML = '';
  data.items.forEach((item) => {
    const li = document.createElement('li');
    const tierLabel = customerTierLabelAr(item);
    const left = item.days_left != null ? (' · باقي ' + item.days_left + ' يوم') : '';
    const prod = productLabelAr(item.product || 'trip-orders');
    li.innerHTML = '<div><strong>' + escape(item.shop) + '</strong><div class="muted">' + escape(prod) + ' · ' + escape(tierLabel) + '</div><div class="muted" dir="ltr">' + escape(item.device) + left + '</div></div>';
    ul.append(li);
  });
}

export function wireOffline(form, out, tierHost) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const submitBtn = form.querySelector('button[type="submit"]');
    if (submitBtn && submitBtn.disabled) return;
    await session();
    out.hidden = true;
    const device = form.device.value.trim();
    const shop = form.shop.value.trim();
    const productEl = form.querySelector('[name="product"]');
    const product = productEl ? productEl.value : 'trip-orders';
    const grant = readGrant(tierHost || form.closest('.card') || document);
    const offlineBody = (force) => ({ device, shop, product, csrf, force, ...grant });
    let data = await api('/offline', {
      method: 'POST',
      headers: headers(),
      body: JSON.stringify(offlineBody(false)),
    });
    if (data && data.error === 'downgrade') {
      if (!confirm(downgradeConfirmMessageAr(data.current))) {
        return;
      }
      data = await api('/offline', {
        method: 'POST',
        headers: headers(),
        body: JSON.stringify(offlineBody(true)),
      });
    }
    if (!data || !data.ok) {
      out.textContent = data && data.error === 'paid_key_missing'
        ? 'إصدار المدفوع غير متاح — أضف PAID_SIGNING_KEY.'
        : 'تعذّر إصدار الكود.';
      out.hidden = false;
      return;
    }
    out.innerHTML = '<p class="muted">اقرأ هذا الكود للعميل:</p><p class="big-code" id="issued-code"></p><button type="button" class="btn" data-copy>نسخ</button>';
    out.querySelector('#issued-code').textContent = data.code;
    out.querySelector('[data-copy]').addEventListener('click', () => navigator.clipboard.writeText(data.code));
    out.hidden = false;
  });
}

function renderOfflineTierSlot(slot, form, selectedProduct) {
  const product = selectedProduct || 'trip-orders';
  const tierOnly = slot.querySelector('[data-tier-slot-tier]');
  const html = tierPickerHtml(!paidForProduct(product), '', 'offline');
  if (tierOnly) {
    tierOnly.innerHTML = html;
    wireTierForm(tierOnly);
    return;
  }
  slot.innerHTML = html;
  wireTierForm(slot);
}

export function mountOfflineTier(host) {
  const slot = host.querySelector('[data-tier-slot]');
  if (!slot) return;
  const form = host.querySelector('#offline-form') || document.getElementById('offline-form');
  const submitBtn = form ? form.querySelector('button[type="submit"]') : null;
  if (submitBtn) submitBtn.disabled = true;
  session().then(async () => {
    const products = await api('/products');
    const loaded = Boolean(products && Array.isArray(products.products));
    if (!loaded) return;
    let productField = '';
    let selected = 'trip-orders';
    if (products.products.length) {
      selected = products.products.includes('trip-orders') ? 'trip-orders' : products.products[0];
      const opts = products.products.map((p) =>
        '<option value="' + escape(p) + '"' + (p === selected ? ' selected' : '') + '>' + escape(productLabelAr(p)) + '</option>',
      ).join('');
      productField = '<div class="field"><label for="product">المنتج</label><select id="product" name="product">' + opts + '</select></div>';
    }
    slot.innerHTML = productField + '<div data-tier-slot-tier></div>';
    const tierWrap = slot.querySelector('[data-tier-slot-tier]');
    renderOfflineTierSlot(tierWrap || slot, form, selected);
    const productEl = slot.querySelector('[name="product"]');
    if (productEl) {
      productEl.addEventListener('change', () => {
        renderOfflineTierSlot(tierWrap || slot, form, productEl.value);
      });
    }
    if (submitBtn) submitBtn.disabled = false;
  });
}
