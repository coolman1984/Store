# Development history (newest first)

## 2026-10-08 — 1.0.0 pilot core
**What:** first version of Al-Store, built with the Apps Factory: research, spec, stdlib server, SQLite ledger, new design system,
licence codes from the factory's Licence Studio, practice shop, 63 automated checks including real-browser journeys.

**Why these choices:** Egyptian appliance shops live with fast price rises (bulk dated price change), shop instalments and
finance companies (separate methods with their own balances), serial-based warranty, and cashier leakage (approvals on the
same screen + the owner's eye). Offline first because power and internet cut.

**Mistakes found by the tests and fixed before the first commit (lessons for the factory):**
1. `$('[data-theme]')` matched `<html data-theme>` — the theme button's click handler was bound to the whole page and replaced
   the document on the first click anywhere. Lesson: never use a state attribute name (`data-theme`, `data-size`) as a hook.
2. `${x ? 'aria-current="page"' : ''}` inside the escaping template turned quotes into `&quot;` — the attribute silently got
   the value `"page"` with quotes. Lesson: attribute fragments must be `raw()`; a static test now refuses the pattern.
3. A manager's wrong password typed on the cashier's screen was counted inside the sale's transaction and rolled back with it,
   so approvals could be brute-forced. Lesson: verify credentials *before* opening the business transaction.
4. SQLite online backup inside an open write transaction on the same connection waits forever. Lesson: backups run outside
   transactions; the auto-backup thread takes the lock but never a transaction.
5. The measured layout sweep (factory UX-08) found the top bar 248 px wider than a 360 px phone and report bars spilling out
   of cards — none visible in desktop screenshots. Lesson: flex/grid children need `min-width: 0`; measure, don't eyeball.
6. Arabic money read backwards (`ج.م 1,250` vs `1,250 ج.م`) when the whole string was forced LTR. Lesson: isolate only the
   number (LRI…PDI) and let the paragraph direction come from the text.
