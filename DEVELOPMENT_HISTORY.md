# Development history (newest first)

## 2026-10-09 — 1.2.0 second pass: relogin and the person's own problem report
**Why:** browser verification became available, and the owner chose to restore factory free-text feedback while keeping the product's stricter consent requirement and every other first-pass safeguard.

**Relogin cause and fix:** `/api/logout` replied without consuming the browser's JSON body (`{}`). On an HTTP/1.1 connection reused for sign-in, those bytes prefixed the next request as `{}POST`, causing a 501 response and leaving the person on the sign-in screen. Consume the bounded body before ending the session. The browser regression also used the role name `storekeeper` instead of the practice account's username `store`; corrected that fixture input without changing its shell, one-controller, F1 or current-course assertions. A new HTTP regression proves logout, anonymous boot and relogin succeed on the same socket.

**Reports:** removed the in-memory taxonomy override that changed `feedback_text` into an ID and replaced the person's words with `user.report`. The factory redactor now prepares both the preview and stored report. Removed text-based pruning of legacy reports: existing reports survive startup, restore rebind and sending when both consent scopes still permit them. Reports without current consent are still purged. The dialog has a labelled text box and the complete canonical report preview; only pressing the send button queues it. Editing text or diagnostics invalidates confirmation, including edits while a preview request is pending. The preview uses LTR for readable JSON in Arabic, the text box follows the typed language, and the dialog keeps preview/send controls visible while its content scrolls. The server still checks the signed digest, the preview's diagnostic snapshot, both consent scopes and known page/guide/problem IDs. Usage and error telemetry retain their IDs/counts-only rules.

**Report access:** browser testing found a resumed/paused lesson card could cover the report button in the help panel. Product CSS now places the open help panel above the coach, with both still below shop dialogs. The report browser test exercises clicks while a coach is present; no forced clicks or hidden controls are used.

**Evidence:** updated redaction and confirmation regressions and added HTTP/browser round trips, preservation of consented factory reports, empty text/context validation and a delayed-preview regression. Guide text files, vendored factory files and workflows remain untouched. Full-suite validation is being completed in this session; final counts are recorded below after execution.

## 2026-10-09 — 1.2.0: in-app guide, consent, and consented telemetry (release candidate)
**Why:** shop owners, cashiers and storekeepers need short instructions inside the program. Optional remote help must respect both the shop's and the person's choices, and never collect business or personal records.

**What:** four role courses, simple formal Arabic («العربية الميسّرة») and English, live completion states, a coach showing step i of n, and an explanation for every server error. Custom profiles follow the closest course and permissions filter its lessons. F1 and the ? button open help. Schema 3 adds per-person `guide_progress` and append-only `consent_log`; the normal checked backup precedes migration.

**Consent and privacy:** a settings administrator answers for the installation on first sign-in; each other person is asked only after the installation agrees. The initial installation answer also records that administrator's personal answer if none exists. Later shop decisions preserve every existing personal decline or withdrawal. Both scopes must agree before personal telemetry or a report is queued. Decline/withdraw purges pending events, including reports. Settings can withdraw consent or disable the receiver with an expired licence. Reading help and saving guide progress stay available while locked; enabling a receiver still needs a valid licence and `settings.edit`.

**Reports and sending (first-pass behavior, superseded for report text above):** reports carried known page/lesson/problem IDs, a fixed report ID, and optional server-derived device counts/versions, with no free-text field. A signed preview must match the confirmed report, including the original diagnostics snapshot; the UI says it is queued locally, not delivered. The outbox stays on the PC until both receiver URL and token exist. Only HTTPS or exact localhost/127.0.0.1 HTTP endpoints are accepted; redirects are refused. Sending runs on the background timer. The factory's `send_once(post=...)` hook releases the queue lock during HTTP while a separate lock prevents simultaneous sends. Frozen merge rows give new counts new event IDs, so acknowledging an old batch cannot delete events collected during its send.

**Review bugs and fixes:**
1. The full-screen consent scrim covered shop controls, the guide button covered dialog footers, and the help button added 9px to the 360px top bar. Product CSS makes consent a nonmodal corner card, places guide chrome below shop dialogs, and tightens narrow top bars. Explicit `[hidden]` rules prevent factory display rules from exposing hidden coach chrome. All overrides live in `pages.css`.
2. Installing/re-enabling shop consent overwrote an existing personal refusal; invalid list/object decisions could crash before returning 400. Validate all decision fields before writing; preserve prior personal choices; audit consent and receiver changes without tokens.
3. Telemetry read the shared consent connection without the shop lock, exposing uncommitted decisions and racing restore. Use shop-lock then outbox-lock order. Restore rebinds consent before releasing the shop lock and prunes queued events whose consent disappeared. Startup also prunes stale/legacy free-text reports.
4. A receiver prefix such as `http://localhost.evil.example` passed the old check. Parse the URL and match its hostname exactly, refuse user-info/control characters and malformed ports, validate tokens, and disable redirects. Config writes are staged and atomically replaced; failed writes leave the previous in-memory config intact.
5. Free-text reports bypassed tracking consent, confirmation was optional, and client diagnostic strings could contain names. Product glue requires both consent scopes, IDs/counts only, mandatory signed confirmation, and server-derived diagnostics. Unknown context IDs, request paths, and malformed browser events cannot become personal data or a server error. The sent viewer shows only the current person's events.
6. Reinitializing the guide leaked F1/hash listeners and coach intervals across sign-ins. Dispose the previous controller and listeners, suppress its pending writes, serialize progress requests, cancel stale mounts/prompts, and discard pre-consent/previous-person telemetry. Guide-load failures can retry without preventing the shop from opening. Consent failures leave retry buttons and a visible message.
7. Rebuilding the shell detached every `data-afg`/`data-afc` descendant, spilling buttons out of the guide/card. Preserve only widget roots when changing language. Browser regressions cover this and relogin isolation.
8. Restore closed the live connection before its staging copy succeeded. Stage first and reopen/rebind even if the swap fails. Test fixtures now close the independent telemetry connection as well as the shop connection.
9. «عمل فاتورة» is now «إنشاء فاتورة بيع»; related guidance uses short, clear sentences.

**First-pass validation:** the guide's real-product release checker passed; the socket-free domain/access/privacy/frontend selection passed **95 tests**. The complete requested browser-enabled command was run, but that sandbox refused `socket.socket()` with `PermissionError: [Errno 1] Operation not permitted`: **102 tests run, 19 errors, 0 assertion failures, 0 skips**. Twelve class setups and seven individual tests failed before their server could start; all fourteen browser tests were unverified at that stage. Second-pass verification is recorded above. Vendored factory files, workflows, and money/stock rows were not changed; no git commands were run.

## 2026-10-09 — 1.1.0: people, profiles and pages, the BAMS way (factory access standard)
**Why:** the owner asked that every product let the administrator decide, person by person, which pages they see and what
they may do, learned from BAMS (Mr.Ayman-HR) and made a factory standard first (`Apps-Factory/docs/ACCESS_AND_ADMINISTRATION_STANDARD.md`,
gate `packages/af-access`, controls IAM-08…IAM-12). Al-Store had four roles fixed in code with per-person extra/removed ticks.

**What:**
1. **Profiles** (named sets of ticks) replace fixed roles: the four ready-made ones (owner, manager, cashier, storekeeper) can be
   renamed, changed — optionally for everybody who has them — or deleted (people keep their ticks, shown as *Custom*), and the
   owner can make new ones ("Senior cashier"). The **owner profile is locked**: always every permission.
2. **Page permissions:** Products, Stock and Customers pages each have their own tick (before they were open to everybody, and
   their data was readable by any signed-in person through the API). The menu, the dock, the palette and the server use one
   table (`auth.PAGES`; a test keeps `app.js` equal to it). An action ticks the page it needs (`REQUIRES`).
3. **Administrator group** (people and permissions; settings, backups and licence) shown apart in orange; *Select all* never ticks it.
4. **Who can do what:** a table of every permission against every profile, printable on A4.
5. **Audit:** every save of a person or profile records the ticks added and removed (never a password).
6. **The person window** now shows the profile picker and the grouped ticks with group ticks, *Select all*, *Clear all*;
   changing a tick shows *Custom* (or the profile whose ticks match exactly).

**Bug found and fixed (lock-out):** 1.0's "last owner" guard looked at the role *name*. Removing the tick "People and permissions"
from the only owner (a per-person removed tick) was accepted — after that nobody could manage people any more. The guard now
protects the *right*: no save may leave no active person with `users.manage`, and nobody can remove their own right or switch
themself off (`afaccess.admin_safety`). A shop already locked out by 1.0 is repaired once at start: its 1.0 owners get the owner
profile back. Regression tests: `test_access.Guards`, `CarryOver`.

**Own review:** the home page's advisor cards and the due-instalments list pointed to pages a person may now not open (they
only checked the action, e.g. collecting instalments). Each card now also needs the page it opens; tested in `test_access.Http`.

**Upgrade (schema 2):** a `profiles` table and a `perms` column. At first start every 1.0 person gets their own ticks once, equal
to what they could do before (plus the pages that were open to everybody then), so nobody gains or loses anything; a verified
copy of the database is made before the migration as always.

**Mistakes on the way:** the first "who can do what" print button called the browser print, which printed a blank page (the
print style shows only the hidden print area) — caught while checking screenshots; it now prints through `printHTML(…, 'a4')`
and the browser test checks the printed table. A first carry-over draft tried to repair lock-outs with a confusing condition;
rewritten to "only the 1.0 owners, only if nobody can manage people".

**Review fixes (Codex, PR #3):** (1) the copy made before a schema upgrade was a plain file copy named `before-schema-N.db`:
it could miss rows still in the write-ahead log and was not listed for restore. It is now made with SQLite's backup, checked,
and named like every backup (`store-…-before-upgrade.db`, kept by pruning). (2) A new profile could be called "Cashier" or
"كاشير" while the ready-made one still showed that name; ready-made names (`auth.BUILTIN_NAMES`, equal to the dictionaries by
test) are now taken. (3) The browser receipt test opened "today's" sales, which are empty before the practice shop's 10:05
opening (it failed on CI and here at 04:00 UTC); it now opens the week and prints the sale it clicked.

**Tests:** `tests/test_access.py` (factory gate with Arabic words, menu = server page table, lock-out guards, profiles, carry-over,
HTTP page guards and audit), browser `PeopleAndProfiles` (owner makes a profile, takes pages from the cashier; the cashier's menu
and the server follow). The full suite is green (110 tests).

## 2026-10-08 — Stock count: a sale in the same millisecond as the count line made a phantom surplus
**Found by:** the GitHub runner failing `test_sale_after_counting_a_product_is_not_a_false_surplus` on PR #2 (it passed on
slower PCs by luck). **Why:** times have millisecond precision; when the count line and the sale fell in the same
millisecond, `m.at <= cl.at` counted the sale as *before* the count, so closing the count added a false +2.
**Fix:** `ids.iso()` ("now") is strictly increasing inside the program — a second record in the same millisecond gets the
next millisecond; a clock moved back by more than a second is believed, so time never freezes. No schema or stock-logic
change. **Tests:** the count scenario and the ordering run under a frozen clock (both failed before the fix).

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
