// The owner's recovery code: shown once on paper at setup, after a recovery, or when the owner makes a new one.
import { api } from './api.js';
import { t } from './i18n.js';
import { printHTML } from './print.js';
import { $, html, icon, open, showError, date, today } from './ui.js';

const paper = (code, shop) => html`<div class="recovery-paper"><h1>${t('recovery.title')}</h1><p>${shop}</p>
  <p class="recovery-code" dir="ltr">${code}</p><p>${t('recovery.why')}</p><p>${t('recovery.once')}</p><p>${date(today())}</p></div>`;

/** Shows the code until the person ticks "I wrote it down". Resolves when they continue. */
export function showRecoveryCode(code, shop = '') {
  return new Promise((resolve) => {
    open({
      title: t('recovery.title'),
      sticky: true,
      body: html`<p class="muted">${t('recovery.why')}</p>
        <p class="recovery-code" dir="ltr" data-recovery-code>${code}</p>
        <div class="tip">${icon('info')}<div>${t('recovery.once')}</div></div>
        <label class="check"><input type="checkbox" id="rc-kept">${t('recovery.kept')}</label>`,
      foot: html`<button class="btn" data-print>${icon('print')}${t('act.print')}</button>
        <button class="btn accent grow" data-ok disabled>${t('recovery.continue')}</button>`,
      mount(box, close) {
        $('[data-print]', box).addEventListener('click', () => printHTML(paper(code, shop), 'a4'));
        $('#rc-kept', box).addEventListener('change', (e) => { $('[data-ok]', box).disabled = !e.target.checked; });
        $('[data-ok]', box).addEventListener('click', () => close(true));
      },
      onClose: () => resolve(),
    });
  });
}

/** Settings: the holder types the password again and gets a new code (the old paper stops working). */
export function makeNewCode(shop) {
  open({
    title: t('recovery.new'),
    body: html`<p class="muted">${t('recovery.cardHint')}</p>
      <div class="field"><label for="rc-pw">${t('recovery.confirmPw')}</label><input id="rc-pw" type="password" class="input" autocomplete="current-password" autofocus></div>
      <p class="err small" id="rc-err" role="alert"></p>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('recovery.new')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        btn.setAttribute('aria-busy', 'true');
        try {
          const r = await api.post('/api/recovery/new', { password: $('#rc-pw', box).value });
          close();
          await showRecoveryCode(r.recovery_code, shop);
        } catch (err) { showError($('#rc-err', box), err); } finally { btn.removeAttribute('aria-busy'); }
      });
    },
  });
}
