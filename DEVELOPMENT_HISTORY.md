# Development history (newest first)

## 2026-10-08 — Design system v2: the Mizan (ميزان) identity across the whole program
**Why:** the program worked and passed its checks but did not look like software a shop would pay for next to international
products: weak hierarchy, 15-px text and 12-px tables, a neon "volt" green that failed contrast as text, floating glass,
3D tilt and pointer spotlights that cost frames on an old PC, inconsistent buttons and icon sizes.

**What:** a new identity and one design system, applied to every screen (details and rules in `docs/DESIGN.md`).
1. **Brand:** display name ميزان · Mizan (provisional — not legally cleared; program id, licence product, data folder and
   installer name deliberately unchanged so existing shops keep working). New mark (balanced bars on a fulcrum) used by the
   rail, sign-in, phone top bar, splash, favicon, manifest and the Windows icon; outlined logo files in `docs/brand/`
   (`tools/make_brand.py`).
2. **Tokens:** navy / ivory / copper palette for light and dark, 16-px body, 14-px data, 20-px icons, 44-px controls, 4-px
   rhythm, quiet shadows, 120–240 ms motion. `volt` renamed `accent` everywhere.
3. **Components rebuilt:** flush navy rail, sticky top bar, buttons, inputs, tabs, tables, KPIs (money never wraps — container
   query), dialogs, sheets, toasts, palette, empty/error states, a branded splash and a calmer "cannot reach the shop PC" screen.
4. **Screens:** new sign-in (promise + three proof points), navy "today" hero with a copper chart, counter with a sticky pay
   button on phones (the pay sheet's confirm no longer scrolls away), clearer pay methods and sale-done, spacing fixes in
   cash, reports (six KPIs in one row, Arabic names cut at their own end in English mode).
5. **Removed:** 3D tilt, pointer spotlight, blur-in, background glows (decoration with a per-frame cost).

**Review fixes (Codex, PR #2):** the new top bar had brought back a backdrop blur (the 1.0.1 UI Lab measured ~20 ms a
frame for it on an old PC) — the bar is opaque again; the splash/boot-error bar kept moving with "reduce motion" on — it
stops now. Both are guarded by tests (`no backdrop-filter`; every endless animation has an off switch for the system
setting and the in-app "motion off").

**Bugs found while doing it:** the suppliers table had no scroll wrapper and spilled out of its card on a 360-px phone (the
layout sweep caught it once text became readable) — wrapped, and any bare table in a card now scrolls inside it.

**UI Lab (same machine, main → this change, 1366 px):** all 20 page/screen runs within budget, 0 accessibility findings;
first paint 300–440 → 72–136 ms (the splash draws before any script); largest paint equal or better on most pages (stock
840 → 404, watch 832 → 372, customers 772 → 368, reports 792 → 380 ms); frames stay at 60 fps.

**Behaviour:** no server, database, money or stock logic changed. **Tests:** new `DesignSystem` checks (WCAG AA contrast of
every token pair in both themes, one mark geometry in four places, no leftover of the old identity, base geometry);
full suite including the browser journey and layout sweep passes.

## 2026-10-08 — 1.0.2 review round: the junk-input test
**What:** a new test (`tests/test_fuzz.py`) sends junk to every write route (wrong types, huge numbers, lists where an id
belongs, bad dates, 1,500-letter texts) — first everywhere at once, then one field at a time inside a valid sale, return,
purchase, transfer… It found 20 places where a strange request made the server answer "unexpected problem" (500).

**Real bugs fixed:**
1. **Double refund:** the same sale line written twice in one return request was checked against the old returned quantity,
   so 2 pieces could be refunded twice. Now each line's earlier rows in the same request count. Test added.
2. **Poisoned settings:** any value could be saved for any setting (`instalment_markup_pct = "abc"` would crash every later
   instalment sale). Settings are now type-checked.
3. A list or object where an id belongs reached SQLite and crashed; huge numbers overflowed SQLite. The database layer now
   refuses them as bad input (400).
4. A non-object JSON body, a non-list `lines`, a bad date (`first_due`, report range), `NaN` quantities, bad barcodes, bad
   warranty/rounding numbers, an empty watch-review key: each now gives a calm, translated message.
5. Restore wrote the database file in place — a power cut mid-copy could leave half a file. It now copies beside it and swaps
   in one step; the backup name must match the pattern exactly (the old `$` allowed a trailing newline).
6. Receipt code had an unused variable; one unused import removed.
7. **Empty code wiped the licence:** pressing "Activate" with an empty box saved an empty code over the working one and locked
   the shop. An empty box is now refused ("type the code first"); the factory's code reader also refuses non-text input.
8. **The safe grew from nothing:** a shift's opening float appeared in the drawer without leaving the safe, so every shift
   inflated the safe by the float. Now the float comes out of the safe (if the safe holds less, the owner is adding the rest).
9. **Stock count + a sale = false surplus:** a product sold after it was counted turned into a phantom +N when the count was
   closed. "Expected" is now what the books said at the moment of counting.
10. **"Owing customers" list hid people past the 200th:** the filter ran after the page limit; now it runs in the query.
11. A serial written on two lines of one purchase put one piece in stock twice; a customer's phone could be duplicated by
    editing; the daily profit chart ignored the cost of returned goods (the summary did not); huge `days`/`limit` in the
    address could hang the PC (now clamped).

12. **The first Windows build stopped at start-up:** printing the Arabic "running now" line to a redirected Windows console
    (code page 1252) raised `UnicodeEncodeError` and the server exited. Found only because the Windows workflow starts the
    built program. Output now goes through `say()` (UTF-8, falls back to ASCII, tolerates no console at all).
13. **Counter:** a slow old search answer could replace a newer one (a scanner could add the wrong product); an unfinished
    payment now keeps its key so "press Pay again after a lost answer" can never sell twice; the instalment quote is awaited
    before paying; the cart is cleared at sign-out; dialogs no longer steal focus 30 ms after opening (it moved typed text
    from the password box into the user-name box — caught as a 1-in-4 flaky test).
14. **Backups:** the safety copy made before every restore (`…-before-restore.db`) did not match the file-name pattern, so it
    was never listed, could not be restored from the page and was never cleaned; two copies in the same second overwrote each
    other (a restore right after a backup destroyed the safety copy); the USB copy could be left half-written under a real name.
    Fixed, and a restore round trip over HTTP (backup → change → restore → restore the safety copy) is now a test.
15. A product's serial tracking could be switched on or off after goods were received (pieces without serials); now locked.
16. **New:** Windows installer pipeline, opt-in support heartbeat, Code 128 barcode on the receipt and sticker labels.

**Lesson:** validate at the edge, once (`core.whole / rows / obj / day`, `db._plain`), then let the rules work with clean
data. The junk test costs 40 s and is worth keeping in every product (factory QA-01).

## 2026-10-08 — 1.0.1 measured by the factory's UI Lab
**What:** every main page measured cold, with the CPU slowed ×4 (an old shop PC), at 1366 px and 390 px: first paint
~0.35–0.45 s, LCP ≤ 1.1 s (products on a phone 2.1 s), CLS ≤ 0.01, no long blocking, 30–60 fps while scrolling, zero serious
accessibility findings, ≤ 53 kB JavaScript per page. Report: docs/ui-lab/REPORT.md.

**Fixed because the lab found it:** grey hint text (`--ink-3`) was 3.9:1 contrast → darkened to 5.2:1; an icon-only button had no
name; sideways-scrolling tables were not reachable by keyboard; two navigation landmarks had the same name; the counter had no
page heading; on phones the receipt jumped down while results loaded (CLS 0.57 → 0) — results now scroll inside their own
area; backdrop blur on the side rail and top bar cost ~20 ms a frame → replaced by an opaque gradient.

**Lesson:** a design that "looks premium" in a screenshot can still be slow and unreadable; the factory now measures both
before a release (factory PERF-01, A11Y-01).

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
