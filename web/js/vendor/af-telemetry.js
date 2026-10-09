/* Vendored from Apps-Factory packages/af-telemetry 0.2.0 - do not edit here. */
/* Update with: python scripts/vendor_telemetry.py <product repo> (from the Apps-Factory checkout) */
/* af-telemetry 0.1.0 (browser half). The browser never talks to the vendor: it hands events to the product's own server
   (POST /api/telemetry/events), which checks consent and the firm limits with af_telemetry.py. Also: a window error
   hook (file:line fingerprint only, never the message), and the problem-report dialog with a full preview.

     const tel = AFTelemetry.init({lang: 'ar', page: () => currentPage});
     tel.track('use.action', {action: 'sale.pay'});
     guide options: track: tel.track, onReport: ctx => tel.report(ctx)                                       */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AFTelemetry = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  const ID = /^[A-Za-z0-9][A-Za-z0-9_.:\-/]{0,79}$/;
  const WORDS = {
    ar: {title: 'أبلغ عن مشكلة', kind: 'النوع', problem: 'مشكلة', idea: 'اقتراح', question: 'سؤال',
      text: 'اكتب ما حدث بكلماتك', diag: 'أرفق معلومات الجهاز (أرقام وإصدارات فقط)', contact: 'كيف نتواصل معك؟',
      none: 'لا داعي', whatsapp: 'واتساب', call: 'مكالمة', in_app: 'داخل البرنامج', preview: 'معاينة ما سيُرسل',
      send: 'إرسال', cancel: 'إلغاء', sent: 'تم الإرسال. شكرًا لك.', failed: 'لم يتم الإرسال. حاول مرة أخرى.',
      note: 'سيُرسل النص كما في المعاينة. نحذف منه أرقام الهواتف والبريد وأرقام الهوية تلقائيًا.'},
    en: {title: 'Report a problem', kind: 'Type', problem: 'Problem', idea: 'Idea', question: 'Question',
      text: 'Write what happened in your own words', diag: 'Attach device info (numbers and versions only)',
      contact: 'How should we reach you?', none: 'No need', whatsapp: 'WhatsApp', call: 'Phone call', in_app: 'In the program',
      preview: 'Preview what will be sent', send: 'Send', cancel: 'Cancel', sent: 'Sent. Thank you.',
      failed: 'Not sent. Please try again.', note: 'The text is sent exactly as previewed. Phone numbers, e-mails and ID numbers are removed automatically.'}
  };

  // ---------------------------------------------------------------- pure helpers (node --test)
  function hash(s) {   // FNV-1a 32-bit, hex: enough to group the same browser error, says nothing about the person
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    // letters only (0-9 -> g-p), so a fingerprint never looks like a long number to the server's privacy guard
    return ('0000000' + h.toString(16)).slice(-8).replace(/[0-9]/g, d => 'ghijklmnop'[d]);
  }
  function errorEvent(filename, line, col, kind) {
    const file = String(filename || 'inline').split(/[?#]/)[0].split('/').pop() || 'inline';
    const where = (file + ':' + (line | 0)).replace(/[^A-Za-z0-9_.:\-/]/g, '_').slice(0, 80);
    return {code: (kind || 'Error').replace(/[^A-Za-z0-9_]/g, '').slice(0, 40) || 'Error', fingerprint: hash(where + ':' + (col | 0)), where};
  }
  function safe(data) {   // first line of defence only; the server is the gate
    const out = {};
    for (const [k, v] of Object.entries(data || {})) {
      if (typeof v === 'number' && isFinite(v)) out[k] = Math.round(v);
      else if (typeof v === 'boolean') out[k] = v;
      else if (typeof v === 'string' && ID.test(v) && !/\d{8,}/.test(v) && !v.includes('@')) out[k] = v;
    }
    return out;
  }

  // ---------------------------------------------------------------- browser
  function init(opts) {
    const o = Object.assign({endpoint: '/api/telemetry', lang: 'ar', flushMs: 15000, max: 200}, opts || {});
    const doc = root.document;
    const request = o.request || ((method, url, body) => root.fetch(url, {method, credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)}).then(r => (r.ok ? r.json() : Promise.reject(r.status))));
    const page = () => (typeof o.page === 'function' ? o.page() : o.page) || null;
    let queue = [];
    const W = () => WORDS[o.lang] || WORDS.en;
    function track(type, data) {
      if (queue.length >= o.max) queue.shift();
      queue.push({type, data: safe(data), page: page()});
    }
    function flush() {
      if (!queue.length) return Promise.resolve();
      const batch = queue;
      queue = [];
      return request('POST', o.endpoint + '/events', {events: batch}).catch(() => {});   // never retried from the browser
    }
    const timer = root.setInterval ? root.setInterval(flush, o.flushMs) : null;
    if (root.addEventListener) {
      root.addEventListener('error', e => track('err.client', errorEvent(e.filename, e.lineno, e.colno, e.error && e.error.name)));
      root.addEventListener('unhandledrejection', e => track('err.client', errorEvent('promise', 0, 0, e.reason && e.reason.name)));
      root.addEventListener('pagehide', flush);
    }
    function el(tag, attrs, ...kids) {
      const n = doc.createElement(tag);
      for (const [k, v] of Object.entries(attrs || {})) {
        if (v === null || v === undefined || v === false) continue;
        if (k === 'on') for (const [e, f] of Object.entries(v)) n.addEventListener(e, f);
        else if (k === 'text') n.textContent = v;
        else n.setAttribute(k, v === true ? '' : v);
      }
      for (const kid of kids.flat()) if (kid) n.append(kid.nodeType ? kid : doc.createTextNode(String(kid)));
      return n;
    }
    /** The problem-report dialog. ctx: {page, guide, problem, kind}. Works without tracking consent. */
    function report(ctx) {
      ctx = ctx || {};
      const w = W();
      const kind = el('select', {'data-aft': 'kind', 'aria-label': w.kind}, ['problem', 'idea', 'question'].map(k =>
        el('option', {value: k, selected: (ctx.kind || 'problem') === k || null, text: w[k]})));
      const text = el('textarea', {'data-aft': 'text', rows: '5', maxlength: '2000', 'aria-label': w.text, placeholder: w.text});
      const diag = el('input', {type: 'checkbox', 'data-aft': 'diag'});
      const contact = el('select', {'data-aft': 'contact', 'aria-label': w.contact}, ['none', 'whatsapp', 'call', 'in_app'].map(k => el('option', {value: k, text: w[k]})));
      const pre = el('pre', {class: 'aft-preview', 'data-aft': 'preview', hidden: true});
      const msg = el('p', {class: 'aft-msg', role: 'status', 'data-aft': 'msg'});
      const body = () => ({kind: kind.value, text: text.value, contact: contact.value, diagnostics: diag.checked,
        page: ctx.page || page(), guide: ctx.guide || null, problem: ctx.problem || null});
      let previewed = null;
      const send = el('button', {type: 'button', class: 'aft-btn', 'data-aft': 'send', disabled: true, text: w.send, on: {click: () => {
        send.disabled = true;
        request('POST', o.endpoint + '/feedback', Object.assign(body(), {confirm: previewed}))
          .then(() => { msg.textContent = w.sent; setTimeout(close, 1200); })
          .catch(() => { msg.textContent = w.failed; send.disabled = false; });
      }}});
      const previewBtn = el('button', {type: 'button', class: 'aft-btn aft-quiet', 'data-aft': 'preview-btn', text: w.preview, on: {click: () => {
        request('POST', o.endpoint + '/feedback/preview', body()).then(r => {
          previewed = r.digest;
          pre.textContent = JSON.stringify(r.event, null, 2);
          pre.hidden = false;
          send.disabled = false;
        }).catch(() => { msg.textContent = w.failed; });
      }}});
      [kind, text, diag, contact].forEach(n => n.addEventListener('input', () => { send.disabled = true; pre.hidden = true; }));
      const dlg = el('div', {class: 'aft-scrim', 'data-aft': 'dialog'},
        el('section', {class: 'aft-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'aft-title', lang: o.lang, dir: o.lang === 'ar' ? 'rtl' : 'ltr'},
          el('h2', {id: 'aft-title', text: w.title}), kind, text,
          el('label', {}, diag, ' ', w.diag), el('label', {}, w.contact + ' ', contact),
          el('p', {class: 'aft-note', text: w.note}), pre, msg,
          el('div', {class: 'aft-actions'}, previewBtn, send, el('button', {type: 'button', class: 'aft-btn aft-quiet', text: w.cancel, on: {click: () => close()}}))));
      function close() { dlg.remove(); }
      dlg.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
      doc.body.append(dlg);
      text.focus();
      return dlg;
    }
    return {track, flush, report, stop: () => timer && root.clearInterval(timer), _queue: () => queue.slice()};
  }
  return {version: '0.1.0', init, errorEvent, safe, hash, WORDS};
});
