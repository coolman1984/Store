// Help: "Guide me" and "Solve a problem" in plain words, plus the keyboard keys. Contacting support lives in Settings.
import { t, lang } from '../i18n.js';
import { $, $$, html, put, icon } from '../ui.js';
import { mountTraining } from './training.js';
import ar from '../../i18n/help-ar.js';
import en from '../../i18n/help-en.js';

export default async function view(page) {
  const H = lang() === 'ar' ? ar : en;
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.help')}</h1><p>${t('help.sub')}</p></div></div>
    <div id="h-train"></div>
    <div class="toolbar"><input class="input" id="h-q" placeholder="${t('help.search')}" autocomplete="off"></div>
    <div class="two"><section class="stack"><h2>${t('help.guides')}</h2>${H.guides.map((g) => html`<details class="help-q" data-text="${g.title} ${g.steps.join(' ')}">
      <summary>${icon(g.icon)}<span class="grow">${g.title}</span>${icon('chev-d')}</summary><div><ol>${g.steps.map((s) => html`<li>${s}</li>`)}</ol></div></details>`)}</section>
    <section class="stack"><h2>${t('help.problems')}</h2>${H.problems.map((p) => html`<details class="help-q" data-text="${p.q} ${p.a.join(' ')}">
      <summary>${icon('help')}<span class="grow">${p.q}</span>${icon('chev-d')}</summary><div>${p.a.map((x) => html`<p>${x}</p>`)}</div></details>`)}
      <div class="card flat"><div class="card-head"><h2>${t('help.keys')}</h2></div>
        ${[['F2', 'help.k.f2'], ['Enter', 'help.k.enter'], ['F4', 'help.k.f4'], ['F8', 'help.k.f8'], ['Ctrl K', 'help.k.ctrlk'], ['Esc', 'help.k.esc']].map(([k, d]) =>
          html`<div class="stat-line"><span>${t(d)}</span><span class="kbd">${k}</span></div>`)}</div></section></div>`);
  mountTraining($('#h-train', page));
  $('#h-q', page).addEventListener('input', (e) => {
    const q = e.target.value.trim();
    $$('[data-text]', page).forEach((d) => { const hit = !q || d.dataset.text.includes(q); d.classList.toggle('hide', !hit); if (q && hit) d.open = true; });
  });
}
