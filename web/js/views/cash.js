// Cash: my shift's drawer (open with a float, expenses, hand cash to the safe, close by counting), all shifts, the main safe.
import { api, key } from '../api.js';
import { S, can, refreshShift, settle } from '../app.js';
import { t } from '../i18n.js';
import { shake } from '../motion.js';
import { CUR, $, $$, html, put, icon, money, moneyH, date, time, open, empty, skeleton, errorText, parseMoney, run, confirm, seg, bindSeg } from '../ui.js';

export default async function view(page, params) {
  const tabs = [['drawer', 'cash', can('pos.sell') || can('cash.expense')], ['shifts', 'clock', can('shifts.manage')], ['safe', 'safe', can('cash.safe')]].filter((x) => x[2]);
  const tab = tabs.find((x) => x[0] === params.tab)?.[0] || tabs[0]?.[0];
  put(page, html`<div class="page-head"><div class="titles"><h1>${t('nav.cash')}</h1><p>${t('cash.sub')}</p></div></div>
    <nav class="tabs">${tabs.map(([k, ic]) => html`<a href="#/cash?tab=${k}" ${tab === k ? CUR : ''}>${icon(ic)}${t('cash.tab.' + k)}</a>`)}</nav><div id="cash-body"></div>`);
  const body = $('#cash-body', page);
  const again = () => view(page, params);
  if (tab === 'shifts') return shifts(body);
  if (tab === 'safe') return safe(body, again);
  return drawer(body, again);
}

async function drawer(body, again) {
  put(body, skeleton(5));
  let s;
  try { s = await api.get('/api/shift'); } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  if (!s) {
    put(body, html`<div class="card volt-card tilt pos-noshift"><div class="row">${icon('cash')}<h2>${t('cash.openTitle')}</h2></div><p>${t('cash.openText')}</p>
      <div class="row wrap"><input id="fl" class="input big money-in" inputmode="decimal" placeholder="0" aria-label="${t('cash.float')}" autofocus>
      <button class="btn primary lg" data-open>${t('cash.openShift')}</button></div></div>`);
    $('[data-open]', body).addEventListener('click', async (e) => {
      const v = parseMoney($('#fl', body).value || '0');
      if (v === null) { shake($('#fl', body)); return; }
      if (await run(api.post('/api/shift/open', { opening_float: v }), t('cash.opened'), e.currentTarget)) { await refreshShift(); again(); }
    });
    return;
  }
  const k = s.by_kind;
  const nonCash = Object.entries(s.tenders).filter(([m]) => m !== 'cash');
  put(body, html`<div class="stack enter">
    <div class="hero"><div class="card ink-card tilt spot"><div class="row between"><span class="muted">${t('cash.inDrawer')}</span><span class="badge ok num">${s.number} · ${time(s.opened_at)}</span></div>
      <div class="hero-total"><div class="value num" data-count="${s.expected_now}" data-fmt="money">${money(s.expected_now, { whole: true })}</div></div>
      <div class="mini-stats"><div><span>${t('cash.float')}</span><b class="num">${money(k.float || 0)}</b></div><div><span>${t('cash.cashSales')}</span><b class="num">${money(k.sale || 0)}</b></div>
        <div><span>${t('cash.out')}</span><b class="num">${money((k.expense || 0) + (k.refund || 0) + (k.drop_out || 0) + (k.supplier || 0) + (k.purchase || 0))}</b></div></div></div>
      <div class="card"><div class="card-head"><h2>${t('cash.actions')}</h2></div><div class="stack tight">
        ${can('cash.expense') ? html`<button class="btn block" data-expense>${icon('wallet')}${t('cash.expense')}</button>` : ''}
        ${can('cash.safe') ? html`<button class="btn block" data-drop>${icon('safe')}${t('cash.drop')}</button>` : ''}
        <button class="btn volt block lg" data-close>${icon('lock')}${t('cash.closeShift')}</button></div>
        ${nonCash.length ? html`<div class="stack tight"><p class="small muted">${t('cash.nonCash')}</p>${nonCash.map(([m, v]) => html`<div class="stat-line small"><span>${t('pay.' + m)}</span>${moneyH(v)}</div>`)}</div>` : ''}</div></div>
    <div class="card"><div class="card-head"><h2>${t('cash.moves')}</h2></div>${s.moves.length ? html`<div class="timeline">${s.moves.map((m) => html`<div class="ev">
      <span class="badge ${m.amount < 0 ? 'warn' : 'ok'}">${t('cashk.' + m.kind)}</span><span class="small"><span class="num">${time(m.at)}</span> · ${m.category ? t('exp.' + m.category) + ' · ' : ''}${m.note} · ${m.by_name}</span>
      <span class="row"><span class="money num">${money(m.amount, { sign: true })}</span>${m.kind === 'expense' && !m.reverses ? html`<button class="icon-btn sm" data-rev="${m.id}" aria-label="${t('act.reverse')}">${icon('return')}</button>` : ''}</span></div>`)}</div>`
      : html`<p class="muted small">${t('cash.noMoves')}</p>`}</div></div>`);
  settle(body);
  $('[data-expense]', body)?.addEventListener('click', () => expense(again));
  $('[data-drop]', body)?.addEventListener('click', () => drop(s, again));
  $('[data-close]', body).addEventListener('click', () => closeShift(s, again));
  $$('[data-rev]', body).forEach((b) => b.addEventListener('click', async () => {
    const why = await confirm({ title: t('cash.reverseTitle'), ok: t('act.reverse'), danger: true, reason: true });
    if (why && await run(api.post('/api/cash/reverse', { id: b.dataset.rev, reason: why }), t('state.reversed'))) again();
  }));
}

function expense(again) {
  const idem = key();
  const cats = S.lookups?.settings?.expense_categories || ['other'];
  open({
    title: t('cash.expense'),
    body: html`<div class="field"><label for="ea">${t('f.amount')}</label><input id="ea" class="input big money-in" inputmode="decimal" autofocus></div>
      <div class="field"><span class="label">${t('cash.category')}</span>${seg('cat', cats.map((c) => [c, t('exp.' + c)]), 'other')}</div>
      <div class="field"><label for="en">${t('cash.forWhat')}</label><input id="en" class="input" placeholder="${t('cash.forWhatHint')}"></div>
      ${can('cash.safe') ? html`<div class="field"><span class="label">${t('receive.payFrom')}</span>${seg('src', [['drawer', t('cash.drawer')], ['safe', t('cash.safe')]], 'drawer')}</div>` : ''}`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      let cat = 'other', src = 'drawer';
      bindSeg(box, 'cat', (v) => { cat = v; });
      bindSeg(box, 'src', (v) => { src = v; });
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const amount = parseMoney($('#ea', box).value);
        if (!amount) { shake($('#ea', box)); return; }
        if ($('#en', box).value.trim().length < 3) { shake($('#en', box)); $('#en', box).focus(); return; }
        if (await run(api.post('/api/cash/expense', { idem_key: idem, amount, category: cat, note: $('#en', box).value, source: src }), t('saved'), e.currentTarget)) { close(); again(); }
      });
    },
  });
}

function drop(s, again) {
  open({
    title: t('cash.drop'),
    body: html`<p class="muted small">${t('cash.dropHint')}</p><div class="field"><label for="da">${t('f.amount')}</label><input id="da" class="input big money-in" inputmode="decimal" autofocus></div>
      <div class="field"><label for="dn">${t('f.note')}</label><input id="dn" class="input"></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('cash.drop')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const amount = parseMoney($('#da', box).value);
        if (!amount || amount > s.expected_now) { shake($('#da', box)); return; }
        if (await run(api.post('/api/cash/safe', { kind: 'drop', amount, note: $('#dn', box).value }), t('saved'), e.currentTarget)) { close(); again(); }
      });
    },
  });
}

function closeShift(s, again) {
  const notes = [20000, 10000, 5000, 2000, 1000, 500, 100, 50, 25];
  open({
    title: t('cash.closeShift'),
    wide: true,
    body: html`<p class="muted small">${t('cash.closeHint')}</p>
      <div class="two"><div class="card flat"><div class="card-head"><h2>${t('cash.countNotes')}</h2></div><div class="stack tight">${notes.map((n) => html`<div class="row">
        <span class="badge num">${money(n)}</span><span class="grow"></span>×<input class="input q-in num" data-note="${n}" inputmode="numeric" placeholder="0"></div>`)}</div></div>
      <div class="stack"><div class="field"><label for="cc">${t('cash.counted')}</label><input id="cc" class="input big money-in" inputmode="decimal" autofocus></div>
        <div class="change" id="cdiff"><span>${t('cash.difference')}</span><b class="num">—</b></div>
        <div class="field"><label for="cn">${t('cash.closeNote')}</label><textarea id="cn" class="input" placeholder="${t('cash.closeNoteHint')}"></textarea></div>
        <p class="small faint">${t('cash.blind')}</p></div></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn volt" data-ok>${icon('lock')}${t('cash.closeShift')}</button>`,
    mount(box, close) {
      const upd = () => {
        const v = parseMoney($('#cc', box).value);
        const d = $('#cdiff', box);
        if (v === null) { $('b', d).textContent = '—'; d.className = 'change'; return; }
        const diff = v - s.expected_now;
        $('b', d).textContent = diff === 0 ? t('cash.exact') : money(diff, { sign: true });
        d.className = 'change' + (diff === 0 ? '' : ' short');
      };
      $$('[data-note]', box).forEach((inp) => inp.addEventListener('input', () => {
        const sum = $$('[data-note]', box).reduce((a, x) => a + (+x.value || 0) * +x.dataset.note, 0);
        $('#cc', box).value = (sum / 100).toString(); upd();
      }));
      $('#cc', box).addEventListener('input', upd);
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const counted = parseMoney($('#cc', box).value);
        if (counted === null) { shake($('#cc', box)); return; }
        const r = await run(api.post('/api/shift/close', { shift_id: s.id, counted, note: $('#cn', box).value }), null, e.currentTarget);
        if (r) {
          close();
          open({ title: t('cash.closedTitle'), body: html`<div class="done"><div class="done-mark">${icon('check')}</div>
            <div class="grid kpis"><div class="kpi"><span class="label">${t('cash.expected')}</span><span class="value num">${money(r.expected)}</span></div>
            <div class="kpi"><span class="label">${t('cash.counted')}</span><span class="value num">${money(r.counted)}</span></div>
            <div class="kpi"><span class="label">${t('cash.difference')}</span><span class="value num ${r.difference < 0 ? 'bad-ink' : ''}">${r.difference ? money(r.difference, { sign: true }) : t('cash.exact')}</span></div></div>
            <p class="muted small">${t('cash.toSafe')}</p></div>`, foot: html`<button class="btn primary" data-close>${t('act.ok')}</button>` });
          await refreshShift(); again();
        }
      });
    },
  });
}

async function shifts(body) {
  put(body, skeleton(5));
  try {
    const rows = await api.get('/api/shifts');
    put(body, rows.length ? html`<div class="card pad-0"><div class="table-wrap"><table class="t"><thead><tr><th>${t('f.number')}</th><th>${t('cash.person')}</th><th>${t('cash.openedAt')}</th>
      <th>${t('cash.closedAt')}</th><th class="end">${t('cash.expected')}</th><th class="end">${t('cash.counted')}</th><th class="end">${t('cash.difference')}</th></tr></thead>
      <tbody>${rows.map((r) => { const d = r.closed_at ? r.counted - r.expected : null; return html`<tr class="click" data-id="${r.id}"><td class="num">${r.number}</td><td>${r.user_name}</td><td class="num">${date(r.opened_at, true)}</td>
        <td class="num">${r.closed_at ? date(r.closed_at, true) : html`<span class="badge ok">${t('shift.open')}</span>`}</td><td class="end money num">${money(r.closed_at ? r.expected : r.drawer_now)}</td>
        <td class="end money num">${r.closed_at ? money(r.counted) : '—'}</td><td class="end">${d === null ? '—' : d === 0 ? html`<span class="badge ok">${t('cash.exact')}</span>` : html`<span class="badge ${d < 0 ? 'bad' : 'warn'} num">${money(d, { sign: true })}</span>`}</td></tr>`; })}</tbody></table></div></div>`
      : html`<div class="card">${empty('clock', t('cash.noShifts'), '')}</div>`);
    $$('tr[data-id]', body).forEach((tr) => tr.addEventListener('click', async () => {
      const s = await api.get('/api/shift/view', { id: tr.dataset.id }).catch(() => null);
      if (!s) return;
      const canClose = !s.closed_at && can('shifts.manage');
      open({ title: html`${t('cash.shift')} <span class="num">${s.number}</span> · ${s.user_name}`, kind: 'panel',
        body: html`<div class="grid kpis"><div class="card flat kpi"><span class="label">${t('cash.inDrawer')}</span><span class="value num">${money(s.expected_now)}</span></div>
          <div class="card flat kpi"><span class="label">${t('home.invoices')}</span><span class="value num">${s.sales_count}</span></div></div>
          ${s.close_note ? html`<div class="tip warn">${icon('info')}<div>${s.close_note}</div></div>` : ''}
          <div class="timeline">${s.moves.map((m) => html`<div class="ev"><span class="badge">${t('cashk.' + m.kind)}</span><span class="small"><span class="num">${time(m.at)}</span> · ${m.note}</span>${moneyH(m.amount, { sign: true })}</div>`)}</div>`,
        foot: canClose ? html`<button class="btn volt" data-cl>${t('cash.closeShift')}</button>` : '',
        mount(box, close) { $('[data-cl]', box)?.addEventListener('click', () => { close(); closeShift(s, () => shifts(body)); }); } });
    }));
  } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); }
}

async function safe(body, again) {
  put(body, skeleton(5));
  let d;
  try { d = await api.get('/api/safe'); } catch (e) { put(body, html`<div class="card">${empty('alert', t('err.title'), errorText(e))}</div>`); return; }
  put(body, html`<div class="stack enter"><div class="hero"><div class="card ink-card tilt spot"><span class="muted">${t('cash.safeBalance')}</span>
      <div class="hero-total"><div class="value num" data-count="${d.balance}" data-fmt="money">${money(d.balance, { whole: true })}</div></div>
      <div class="row wrap"><button class="btn volt" data-k="withdraw">${icon('arrow-up')}${t('cash.withdraw')}</button><button class="btn" data-k="deposit">${icon('arrow-down')}${t('cash.deposit')}</button></div></div>
    <div class="card"><div class="card-head"><h2>${t('cash.financeDue')}</h2></div>${d.finance_due.length ? html`<div class="list">${d.finance_due.map((f) => html`<div class="li"><b class="grow">${f.provider}</b>
      <span class="money num">${money(f.amount)}</span><button class="btn sm" data-settle="${f.provider}" data-amount="${f.amount}">${t('cash.settle')}</button></div>`)}</div>`
      : html`<p class="muted small">${t('cash.noFinanceDue')}</p>`}</div></div>
    <div class="card"><div class="card-head"><h2>${t('cash.safeMoves')}</h2></div><div class="timeline">${d.moves.map((m) => html`<div class="ev">
      <span class="badge ${m.amount < 0 ? 'warn' : 'ok'}">${t('cashk.' + m.kind)}</span><span class="small"><span class="num">${date(m.at, true)}</span> · ${m.note} · ${m.by_name}${m.reversed ? html` <span class="badge bad">${t('state.reversed')}</span>` : ''}</span>
      <span class="row"><span class="money num">${money(m.amount, { sign: true })}</span>${['withdraw', 'deposit', 'expense'].includes(m.kind) && !m.reversed ? html`<button class="icon-btn sm" data-rev="${m.id}" aria-label="${t('act.reverse')}">${icon('return')}</button>` : ''}</span></div>`)}</div></div></div>`);
  settle(body);
  $$('[data-k]', body).forEach((b) => b.addEventListener('click', () => open({
    title: t('cash.' + b.dataset.k),
    body: html`<div class="field"><label for="sa">${t('f.amount')}</label><input id="sa" class="input big money-in" inputmode="decimal" autofocus></div>
      <div class="field"><label for="sn">${t('f.note')}</label><input id="sn" class="input"></div>`,
    foot: html`<button class="btn ghost" data-close>${t('act.cancel')}</button><button class="btn primary" data-ok>${t('act.save')}</button>`,
    mount(box, close) {
      $('[data-ok]', box).addEventListener('click', async (e) => {
        const amount = parseMoney($('#sa', box).value);
        if (!amount) { shake($('#sa', box)); return; }
        if (await run(api.post('/api/cash/safe', { kind: b.dataset.k, amount, note: $('#sn', box).value }), t('saved'), e.currentTarget)) { close(); again(); }
      });
    },
  })));
  $$('[data-settle]', body).forEach((b) => b.addEventListener('click', async () => {
    const ok = await confirm({ title: t('cash.settle') + ' — ' + b.dataset.settle, text: t('cash.settleText', { m: money(+b.dataset.amount) }), ok: t('cash.settle') });
    if (ok && await run(api.post('/api/finance/settle', { provider: b.dataset.settle, amount: +b.dataset.amount }), t('saved'))) again();
  }));
  $$('[data-rev]', body).forEach((b) => b.addEventListener('click', async () => {
    const why = await confirm({ title: t('cash.reverseTitle'), ok: t('act.reverse'), danger: true, reason: true });
    if (why && await run(api.post('/api/cash/reverse', { id: b.dataset.rev, reason: why }), t('state.reversed'))) again();
  }));
}
