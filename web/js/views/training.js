// Learning by doing. In the real shop: one button opens the practice shop (made-up data, its own folder and port). In the practice shop:
// three exercises, each set up fresh, then checked from the shop's own books; and the whole made-up shop can be rebuilt.
import { api } from '../api.js';
import { S, can, refreshShift } from '../app.js';
import { t, lang } from '../i18n.js';
import { $, $$, html, put, icon, money, num, run, confirm, toast } from '../ui.js';
import ar from '../../i18n/training-ar.js';
import en from '../../i18n/training-en.js';

const STATE = { new: 'tr.s.new', open: 'tr.s.open', done: 'tr.s.done' };
const BADGE = { new: '', open: 'warn', done: 'ok' };
const fill = (text, vars) => text.replace(/\{(\w+)\}/g, (_, k) => vars[k] ?? '');

export async function mountTraining(host) {
  if (S.boot?.practice) await practiceBox(host);
  else realBox(host);
}

function realBox(host) {
  put(host, html`<div class="card"><div class="card-head"><h2>${icon('sparkle')}${t('tr.realTitle')}</h2></div><p class="muted">${t('tr.realText')}</p>
    <div class="row wrap"><button class="btn primary" data-open-practice>${icon('sparkle')}${t('tr.openBtn')}</button><span class="small muted" id="tr-msg" role="status" aria-live="polite"></span></div></div>`);
  const msg = $('#tr-msg', host);
  $('[data-open-practice]', host).addEventListener('click', async (e) => {
    const r = await run(api.post('/api/practice/open'), null, e.currentTarget);
    if (!r) return;
    if (r.state === 'remote') { put(msg, html`${t('tr.remote')}`); return; }
    put(msg, html`${t('tr.starting')}`);
    for (let i = 0; i < 60; i += 1) {
      let st;
      try { st = await api.get('/api/practice'); } catch { st = null; }
      if (st?.state === 'running') {
        put(msg, html`${t('tr.ready')} <a class="btn sm primary" href="${st.url}" target="_blank" rel="noopener">${t('tr.go')}</a>`);
        window.open(st.url, '_blank', 'noopener');
        return;
      }
      await new Promise((ok) => setTimeout(ok, 1000));
    }
    put(msg, html`${t('tr.failed')}`);
  });
}

function vars(l, v) {
  const d = l.data || {};
  const count = l.id === 'count';
  return { user: l.account, password: v.password, approver: v.approver, customer: d.customer, number: d.number, product: d.product, place: d.place,
    total: money(d.total || 0), expected: count ? num(d.expected) : money(d.expected || 0), physical: count ? num(d.physical) : money(d.physical || 0),
    missing: count ? num(d.missing) : money(d.missing || 0) };
}

async function practiceBox(host) {
  const T = lang() === 'ar' ? ar : en;
  const draw = async () => {
    const v = await api.get('/api/training');
    put(host, html`<div class="stack"><div class="card"><div class="card-head"><h2>${icon('sparkle')}${t('tr.head')}</h2></div><p class="muted">${t('tr.headText')}</p></div>
      ${v.lessons.map((l) => {
        const c = T[l.id], x = vars(l, v), ok = l.checks.filter((k) => k.ok).length;
        return html`<article class="card" data-lesson="${l.id}"><div class="card-head"><h2>${icon(c.icon)}${c.title}</h2>
          <span class="badge ${BADGE[l.state]}" data-state="${l.state}">${t(STATE[l.state])}</span></div>
          ${l.state === 'new' ? html`<p class="muted small">${t('tr.needUser', { user: l.account })}</p>` : html`<p>${fill(c.story, x)}</p>
            <details class="help-q" ${l.state === 'open' ? html`open` : ''}><summary>${icon('help')}<span class="grow">${t('tr.steps')}</span>${icon('chev-d')}</summary>
              <div><ol>${c.steps.map((s) => html`<li>${fill(s, x)}</li>`)}</ol></div></details>
            <ul class="train-checks" role="status">${l.checks.map((k) => html`<li class="${k.ok ? 'ok' : ''}" data-check-key="${k.key}">${icon(k.ok ? 'check-circle' : 'clock')}<span>${fill(c.checks[k.key], x)}</span></li>`)}</ul>
            <p class="small muted">${t('tr.progress', { n: ok, of: l.checks.length })} · ${t('tr.attempt', { n: l.attempt })}${S.me.username === l.account ? html` · ${t('tr.you', { user: l.account })}` : ''}</p>
            ${l.state === 'done' ? html`<div class="tip ok">${icon('check-circle')}<div><b>${t('tr.done')}</b> ${c.tip}</div></div>` : ''}`}
          <div class="row wrap">${l.state === 'new' ? html`<button class="btn primary" data-start="${l.id}">${t('tr.start')}</button>`
            : html`<button class="btn primary" data-check="${l.id}">${icon('check')}${t('tr.check')}</button><button class="btn ghost" data-restart="${l.id}">${icon('refresh')}${t('tr.restart')}</button>`}
            ${S.me.username !== l.account ? html`<button class="btn ghost" data-switch>${icon('logout', 'flip')}${t('tr.switch')}</button>` : ''}</div></article>`;
      })}
      ${can('settings.edit') ? html`<div class="card flat"><div class="card-head"><h2>${t('tr.resetTitle')}</h2></div><p class="muted small">${t('tr.resetText')}</p>
        <button class="btn danger" data-reset>${icon('trash')}${t('tr.resetBtn')}</button></div>` : ''}</div>`);
    $$('[data-start]', host).forEach((b) => b.addEventListener('click', async () => {
      if (await run(api.post('/api/training/start', { lesson: b.dataset.start }), null, b)) { await refreshShift(); draw(); }
    }));
    $$('[data-check]', host).forEach((b) => b.addEventListener('click', async () => {
      await draw();
      if ($(`[data-lesson="${b.dataset.check}"] [data-state="done"]`, host)) toast(t('tr.done'));
    }));
    $$('[data-restart]', host).forEach((b) => b.addEventListener('click', async () => {
      if (!await confirm({ title: t('tr.restart'), text: t('tr.restartAsk'), ok: t('tr.restart') })) return;
      if (await run(api.post('/api/training/start', { lesson: b.dataset.restart, restart: true }), null, b)) { await refreshShift(); draw(); }
    }));
    $$('[data-switch]', host).forEach((b) => b.addEventListener('click', async () => { await api.post('/api/logout').catch(() => {}); location.hash = ''; location.reload(); }));
    $('[data-reset]', host)?.addEventListener('click', async (e) => {
      if (!await confirm({ title: t('tr.resetTitle'), text: t('tr.resetAsk'), ok: t('tr.resetBtn'), danger: true })) return;
      if (await run(api.post('/api/practice/reset'), t('tr.resetDone'), e.currentTarget)) { location.hash = ''; location.reload(); }
    });
  };
  try { await draw(); } catch (e) { put(host, html``); }
}
