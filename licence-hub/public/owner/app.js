'use strict';

async function api(path, opts) {
  const r = await fetch('/owner/api' + path, { credentials: 'same-origin', ...opts });
  if (r.status === 401) { location.href = '/owner/login.html'; return null; }
  return r.json();
}

let csrf = '';

async function session() {
  const s = await api('/session');
  if (s) csrf = s.csrf || '';
  return s;
}

function headers() {
  return { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf };
}

export async function loadPending(host) {
  await session();
  const data = await api('/pending');
  if (!data) return;
  const ul = host.querySelector('[data-pending]');
  ul.innerHTML = '';
  if (!data.items.length) {
    ul.innerHTML = '<li class="muted">لا توجد طلبات معلّقة.</li>';
    return;
  }
  data.items.forEach((item) => {
    const li = document.createElement('li');
    const when = new Date(item.created_at * 1000).toLocaleString('ar-EG');
    const kindLabel = kindLabelAr(item.kind);
    const usedNote = item.kind === 'trial' && item.has_customer
      ? '<div class="err">هذا الجهاز لديه عميل مسجّل — الموافقة العادية مرفوضة؛ استخدم «إعادة إصدار» إن فُقد الكود.</div>'
      : '';
    li.innerHTML = '<div><strong>' + escape(item.shop || '—') + '</strong><div class="muted">' + escape(kindLabel) + ' · ' + escape(item.device) + '</div>' + usedNote + '<div class="muted">' + when + '</div></div>';
    const row = document.createElement('div');
    row.className = 'row';
    const ok = document.createElement('button');
    ok.className = 'btn primary';
    ok.type = 'button';
    ok.textContent = item.kind === 'trial' ? 'موافق — تجربة' : (item.kind === 'monthly' ? 'موافق — شهري' : 'موافق — دائم');
    ok.addEventListener('click', async () => {
      let force = false;
      if (item.kind === 'trial' && item.has_customer) {
        if (!confirm('إعادة إصدار تجربة لهذا الجهاز؟ (فقدان الكود فقط)')) return;
        force = true;
      } else if (item.kind !== 'trial' && item.has_customer) {
        if (!confirm('إصدار ترخيص مدفوع لهذا الجهاز رغم وجود عميل مسجّل؟')) return;
        force = true;
      }
      ok.disabled = true;
      const res = await api('/approve', { method: 'POST', headers: headers(), body: JSON.stringify({ id: item.id, csrf, force }) });
      if (res && res.error === 'paid_in_licence_studio') {
        alert('مفتاح التوقيع المدفوع غير مضبوط على الوسيط (LICENCE_PAID_SIGNING_KEY).');
      } else if (res && res.error === 'bad_device') {
        alert('رمز الجهاز غير صالح — ارفض الطلب.');
        ok.disabled = false;
        return;
      } else if (res && res.error && !res.ok) {
        alert('تعذّرت الموافقة: ' + res.error);
        ok.disabled = false;
        return;
      }
      if (res && res.ok && res.code) {
        const box = document.createElement('div');
        box.className = 'issued-box';
        box.innerHTML = '<p class="muted">اقرأ هذا الكود للعميل:</p><p class="big-code" dir="ltr">' + escape(res.code) + '</p><button type="button" class="btn" data-copy>نسخ</button>';
        box.querySelector('[data-copy]').addEventListener('click', () => navigator.clipboard.writeText(res.code));
        li.append(box);
      }
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
    const left = item.days_left != null ? (' · باقي ' + item.days_left + ' يوم') : '';
    li.innerHTML = '<div><strong>' + escape(item.shop) + '</strong><div class="muted" dir="ltr">' + escape(item.device) + left + '</div></div>';
    ul.append(li);
  });
}

export function wireOffline(form, out) {
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    await session();
    out.hidden = true;
    const device = form.device.value.trim();
    const shop = form.shop.value.trim();
    const data = await api('/offline', { method: 'POST', headers: headers(), body: JSON.stringify({ device, shop, csrf }) });
    if (!data || !data.ok) {
      out.textContent = 'تعذّر إصدار الكود.';
      out.hidden = false;
      return;
    }
    out.innerHTML = '<p class="muted">اقرأ هذا الكود للعميل:</p><p class="big-code" id="issued-code"></p><button type="button" class="btn" id="copy-code">نسخ</button>';
    out.querySelector('#issued-code').textContent = data.code;
    out.querySelector('#copy-code').addEventListener('click', () => {
      navigator.clipboard.writeText(data.code);
    });
    out.hidden = false;
  });
}

function escape(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function kindLabelAr(kind) {
  if (kind === 'trial') return 'تجربة';
  if (kind === 'monthly') return 'شهري';
  if (kind === 'permanent') return 'دائم';
  return kind;
}
