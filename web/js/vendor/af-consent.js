/* Vendored from Apps-Factory packages/af-consent 0.1.1 - do not edit here. */
/* Update with: python scripts/vendor_consent.py <product repo> (from the Apps-Factory checkout) */
/* af-consent 0.1.1: the first sign-in consent card and the «الخصوصية والمساعدة» settings block.
   No dependencies, textContent only. The server owns the record (af_consent.py); this only asks and shows.

     const p = await fetch('/api/consent/prompt').then(r => r.json());     // af_consent.prompt(lang, vendor)
     if (p.ask) await AFConsent.ask(p, decision => post('/api/consent', {decision, text_id: p.text_id, lang: p.lang}));
     AFConsent.settings(box, {status, prompt: p, decide: d => post(...), showSent: () => openViewer()});    */
(function (root, factory) {
  const api = factory(root);
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.AFConsent = api;
})(typeof window !== 'undefined' ? window : globalThis, function (root) {
  'use strict';
  const WORDS = {
    ar: {title: 'المساعدة عن بُعد', on: 'المساعدة عن بُعد مفعّلة لك.', off: 'المساعدة عن بُعد غير مفعّلة لك.',
      withdraw: 'سحب الموافقة', agreeNow: 'أوافق الآن', sent: 'ماذا أُرسل؟', install: 'المنشأة لم توافق بعد.',
      feedback: 'تستطيع دائمًا إرسال مشكلة أو اقتراح بنفسك من زر «الدليل».'},
    en: {title: 'Remote help', on: 'Remote help is on for you.', off: 'Remote help is off for you.',
      withdraw: 'Withdraw consent', agreeNow: 'Agree now', sent: 'What was sent?', install: 'The business has not agreed yet.',
      feedback: 'You can always send a problem or an idea yourself from the Guide button.'}
  };
  function el(doc, tag, attrs, ...kids) {
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
  /** Show the card; resolves with 'agree' or 'decline' after decide() succeeded. Esc does not decide. */
  function ask(prompt, decide, opts) {
    const doc = (opts && opts.document) || root.document;
    return new Promise(resolve => {
      const dir = prompt.lang === 'ar' ? 'rtl' : 'ltr';
      const pick = d => Promise.resolve(decide(d)).then(() => { box.remove(); resolve(d); });
      const box = el(doc, 'div', {class: 'afc-scrim', 'data-afc': 'card'},
        el(doc, 'section', {class: 'afc-card', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'afc-text', lang: prompt.lang, dir},
          el(doc, 'p', {id: 'afc-text', class: 'afc-text', text: prompt.text}),
          el(doc, 'p', {class: 'afc-more', text: prompt.more}),
          el(doc, 'div', {class: 'afc-actions'},
            el(doc, 'button', {type: 'button', class: 'afc-btn', 'data-afc': 'agree', on: {click: () => pick('agree')}, text: prompt.agree}),
            el(doc, 'button', {type: 'button', class: 'afc-btn', 'data-afc': 'decline', on: {click: () => pick('decline')}, text: prompt.decline}))));
      doc.body.append(box);
      box.querySelector('[data-afc="agree"]').focus();
    });
  }
  /** Settings block «الخصوصية والمساعدة»: current state, change it, and the optional «ماذا أُرسل؟» viewer. */
  function settings(container, opts) {
    const doc = container.ownerDocument;
    const lang = (opts.prompt && opts.prompt.lang) || 'ar';
    const W = WORDS[lang] || WORDS.en;
    const s = opts.status || {};
    const on = !!s.tracking;
    const installOk = s.install && s.install.decision === 'agree';
    // `replaceChildren(a, null, b)` prints the null as the word "null" (Settings -> Privacy showed «nullnull»): only real nodes go in
    container.replaceChildren(...[el(doc, 'h3', {text: W.title}),
      el(doc, 'p', {'data-afc': 'state', text: installOk ? (on ? W.on : W.off) : W.install}),
      s.person ? el(doc, 'p', {class: 'afc-more', text: s.person.label + ' · ' + s.person.at}) : null,
      installOk ? el(doc, 'button', {type: 'button', class: 'afc-btn', 'data-afc': on ? 'withdraw' : 'agree-now',
        on: {click: () => opts.decide(on ? 'withdraw' : 'agree')}, text: on ? W.withdraw : W.agreeNow}) : null,
      opts.showSent ? el(doc, 'button', {type: 'button', class: 'afc-btn afc-quiet', 'data-afc': 'sent', on: {click: opts.showSent}, text: W.sent}) : null,
      el(doc, 'p', {class: 'afc-more', text: W.feedback})].filter(Boolean));
    container.setAttribute('lang', lang);
    container.setAttribute('dir', lang === 'ar' ? 'rtl' : 'ltr');
  }
  return {version: '0.1.1', ask, settings, WORDS};
});
