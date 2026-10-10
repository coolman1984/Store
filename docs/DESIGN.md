# Al-Store (الستور) — design system v2 and redesign record

Source standard: `Apps-Factory/design-factory/DESIGN.md` v2 (2026-10-08) and `DESIGN_CONSTITUTION.md`. This file supersedes the
specification-only draft on branch `feat/store-world-class-design-spec-20261008`: everything that draft asked for is now built.

## 1. Brand

**Name: الستور · Al-Store.** From 2026-10-08 to 2026-10-10 the display name was «ميزان · Mizan». It is **withdrawn**: `Accounting-sys`
is the owner's accounting product and is already called Mizan, so two products under one name would confuse customers, licences,
support and any future link between them (found by the review of the factory's PR #9). The Store goes back to the name its
installer, data folder, repository and licence product id already use. This is a working resolution, not a brand decision: any new
brand name is the owner's choice after a trademark and domain search (EG, SA, AE); «قسطاس · Qistas» was noted earlier as a candidate and is not decided.

- **What changed in the product:** only the *display* name (`app.name` in both dictionaries), the web manifest, the page title, the splash label and the logo
  files. The mark, the colours, the favicon and the Windows icon are the same: the visual identity does not depend on the name. The program id `al-store`,
  licence codes, the data folder `%ProgramData%\Al-Store`, the installer file name and the server's `version.PRODUCT` never changed.
- **Mark:** two equal bars (books that balance) resting on a fulcrum (the scale). Drawn on a 48-unit grid; one geometry in
  `web/js/brand.js`, `web/index.html` (splash), `web/img/icon.svg` and `tools/make_icon.py` — a test keeps them identical.
  It stays legible at 16 px (checked as a Windows icon at 16/32/48/256).
- **Logo files:** `docs/brand/` — mark on light/dark, lockup on light/dark with the words as outlines (built by
  `tools/make_brand.py` from the bundled fonts, so they print identically anywhere). In the app the lockup is live text.
- **Voice:** calm, exact, Egyptian Arabic first. No exclamation marks on money.

## 2. Direction (three explored, one chosen)

| Direction | Idea | Verdict |
|---|---|---|
| A. **Ledger** | midnight navy structure, warm ivory paper, one copper action | **chosen** — trust and money; distinctive in Egyptian retail where software is either blue-generic or neon |
| B. Market | terracotta + sand, rounded, friendly | rejected — reads as a consumer shop, not a back office |
| C. Showroom (1.0) | graphite + neon volt, floating glass, 3D tilt | retired — striking in a demo, tiring at a counter for 10 hours; volt failed contrast as text |

## 3. Tokens (`web/css/tokens.css`) — the only place a colour, size or duration is written

- **Colour.** Navy `--brand #13213c` (rail `#101c33`), ivory canvas `#f5f3ee`, copper `--accent #a4531c` (white text 5.5:1).
  Dark theme: canvas `#0a101c`, surfaces `#111a2b…#1b2740`, copper `#e08a4c` with dark text (7.1:1). Trust colours
  ok/warn/bad/info mean one thing each. High-contrast theme kept. **Copper = the one action that matters on a screen**
  (Sell, Pay, Save, Close shift); navy = structure and secondary primary; everything else is neutral.
- **Contrast.** Every text/background pair used is ≥ 4.5:1 in both themes — enforced by `tests/test_frontend.py::DesignSystem`.
- **Type.** Readex Pro (UI, numbers, tabular figures) + Alexandria (headings), both bundled, OFL. Body 16 px / 1.55;
  dense data 14 px; table headers 13 px semibold; page title 30 px; card title 17 px. Text size preference S/M/L/XL = 15/16/17/19.
- **Space.** 4-px rhythm: 4, 8, 12, 16, 20, 24, 32, 40, 48. Cards pad 24 (16 on phones); grid gutter 16; sections 16–24.
- **Icons.** One hand-drawn 24-unit set (`web/img/icons.svg`), 1.75 stroke, round joins. Sizes: 16 inline/table, 18 in
  buttons, 20 standard, 22–24 navigation emphasis. Icon-only buttons have `aria-label`.
- **Shape and depth.** Radii 6/8/10/14/20. Structure from 1-px hairlines; shadows only lift what floats (dialogs, sheets, toasts).
- **Motion.** 120/180/240 ms, ease-out, no 3D tilt, no pointer spotlights, no blur-in. One 200-ms fade-up on page enter.
  Reduced-motion and the in-app "motion off" remove all travel.
- **Targets.** Controls 44 px (`--tap`), primary/touch 52–56 px, pay button 56 px; chips 36 px.

## 4. Components (`web/css/base.css`)

Shell (navy rail with grouped nav and copper active marker; sticky translucent top bar; phone bottom dock with Sell
highlighted), page head, banner, card / ink-card (navy hero) / accent-card, KPI (container-query sized so money never wraps),
buttons (default, primary, accent, ghost, danger, sm, lg, busy, disabled), field/input/select/textarea (visible label,
hint, error, blue focus ring), segmented control, chips, badges, tips, tables (sticky header, 52-px rows, horizontal scroll
inside the card on phones — never page overflow), lists, empty / skeleton / error states, dialog, side panel, bottom sheet
(confirm button sticky), toast, command palette, splash and boot-error screen.

## 5. Screens

Sign-in (navy brand panel: promise + three proof points; ivory form), Today, Counter (search, categories, product tiles,
receipt paper with navy/copper edge, pay sheet, sale-done), Sales/returns/warranty, Customers & instalments, Products &
prices, Stock & shelves, Receiving & suppliers, Cash/shifts/safe, Owner's eye, Reports, Settings, Help — all built only from
the tokens and components above, in Arabic RTL and English LTR, light, dark and high contrast.

## 6. Rules for the next change

1. A view never writes a colour, size or duration. Add a token if one is missing.
2. One copper button per screen region. Two copper buttons side by side means one of them is wrong.
3. Money and counts use `.num`/`.money` (tabular, never wrap). KPI values shrink rather than wrap.
4. A table always lives in `.table-wrap` or a `.card.pad-0`.
5. A dialog's confirm stays visible (sticky footer) on a phone.
6. Before a PR: `python -m unittest discover -s tests` (includes the measured layout sweep at 360/820/1366 px and the
   contrast/mark checks) and look at screenshots in both languages and both themes.

## 7. Evidence (2026-10-08)

Before/after screenshots: `docs/design/screens/` (practice shop, made-up data). Captured with Playwright + Chromium at
1440×900, 768×1024 and 390×844, Arabic/English × light/dark, from the running server.
Not yet verified by a person: real cashier usability session, physical receipt printer, Windows 7/old-Chromium rendering of
`:has()` and container queries (both degrade safely: a table overflows its card edge, a KPI number wraps).
