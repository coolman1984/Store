# Where to continue

## Done in 1.0.0 (2026-10-08)
- [x] Market research (docs/01-research.md) and spec with acceptance tests (docs/02-product-spec.md)
- [x] Server: catalogue, dated prices + bulk change, places/shelves, serials, receiving with moving-average cost, transfers, counts
- [x] Counter: keyboard sale, 7 payment methods + split, shop instalments, on-account, finance companies, approvals, park/resume
- [x] Returns linked to sale lines; warranty look-up by serial
- [x] Shifts, drawer, safe, expenses, over/short; customers & suppliers ledgers; instalment due list + WhatsApp one-by-one
- [x] Reports, advisor, owner's eye; backups (checked), restore with password, CSV export
- [x] Licence codes (14-day trial, device-bound, read/export/backup when locked, clock rollback guard)
- [x] New "Showroom" design system: layered surfaces, Readex Pro + Alexandria, motion, AR/EN, light/dark/contrast, phone dock
- [x] Tests: domain, HTTP/security, licence gate, static page checks, browser journey + measured layout sweep (4 sizes)

- [x] Design system v2 identity on every screen, logo files, icon, splash; contrast and mark tests (docs/DESIGN.md). Its display name «Mizan» was withdrawn on 2026-10-10 (the owner's accounting product is Mizan): the Store shows الستور / Al-Store

- [x] 1.1.0 People, profiles and pages (factory access standard, BAMS model): editable profiles, page permissions, lock-out guard, who-can-do-what, audit of ticks; gate `afaccess` in tests
- [x] 1.2.0 implemented: role courses and coach, per-person progress, every server error explained, two-scope consent, IDs/counts-only usage/error telemetry and redacted free-text reports with explicit preview/send. Nothing leaves the PC without receiver URL and token; withdrawals work while licence-locked.
- [x] 1.2.0 automated release verification (2026-10-09 second pass): requested full browser-enabled command is green — **155 passed, 0 failures, 0 errors, 0 skips**, including all **16 browser tests**. No discovery changes or extra skips. Cause/fix report: `/workspace/grok-log/codex-report2.md`. Field checks below remain open.

- [x] 1.3.0 cash only everywhere (other ways hidden until the owner turns them on); ready-to-sell plan in `docs/03-ready-to-sell.md`

- [x] 1.4.0 owner recovery code (IAM-01): paper code at setup, «نسيت كلمة السر؟», new code from Settings → People

- [x] 1.5.0 three activation kinds (trial 14 days, monthly, permanent); release proofs: DATA-06, REL-03, OPS-06 (Linux + Windows), IAM-06, SEC-02, SEC-07, OPS-01/OPS-07 (real shop journey + update on Windows, RELEASE-PROOF.txt), PERF-01 rerun

- [x] Windows installer (Nuitka + Inno Setup): built, silently installed, started and uninstalled by the `windows installer` workflow on a real Windows runner
- [x] Support heartbeat to the Vendor Control Center (opt-in, exact fields; Settings → Support)
- [x] Barcode on the receipt + sticker labels (per copy or per serial) — Code 128, decoded by a real scanner library in the check

- [x] 1.7.0 practice shop opened from Help + three hands-on exercises checked from the books + rebuild; practice and real folders can never be mixed (`server/practice.py`, `server/training.py`, `tests/test_training.py`)
- [x] 1.6.0 ask for the trial from the licence screen; the signed code switches the program on by itself (Telegram to the owner, owner-approved policy in the Licence Studio); independent review fixes: read leaks, refund by tender, practice cookie, header triggers

- [x] 1.8.0 independent audit round: random shop days with the books checked after every step, a real-browser sweep of every page/role/language/size, probes of the write routes and the database layer; 10 defects fixed (see DEVELOPMENT_HISTORY); the owner's Telegram buttons on the licence screen

- [x] 1.9.1 the trial's length is the company's per-product setting (labels no longer say 14; trials of 7, 30 and 60 days tested against signed codes)
- [x] 1.9.0 the name الستور again (Mizan withdrawn), the 320 px phone, a fourth practice exercise for the owner (the Owner's eye), licence-kind tests against codes signed by the factory's own tool (`tests/test_licence_types.py`), a network-failure browser test (factory UX-04)

### The learn-by-doing roadmap of 2026-10-09 (the old PR #13, which only held a plan): where it stands
- Done (1.7.0, 1.9.0): a separate practice shop opened from Help (own folder, own port, banner), four hands-on exercises for the cashier, the storekeeper and the owner that are checked from the books and can be started over, a full rebuild of the practice shop, no way to mix the practice and real folders (`tests/test_training.py`, `TrainingByClicking`). In the practice shop everything can be added, edited and deleted, and the rebuild brings it back.
- Not done, and not started: a role-limited demo login picker beyond the four practice accounts, a manager-approval exercise, and the public online trial site (needs isolated hosting and a cost and abuse review; the owner decides, nothing is chosen).

## Next (in order) — full list and reasons in docs/03-ready-to-sell.md
- [ ] Vendor licence key from Licence Studio → public key in `licence_keys.txt`, build the pilot copy (owner)
- [ ] Prices for the monthly and permanent codes, and who pays for support → DECISIONS.md (owner)
- [ ] Deploy the licence relay and write its address in `licence_relay.txt`; the company's Telegram contact in `config.json` (`vendor_telegram`) for the manual way — not in this public repository (owner; steps in Apps-Factory `docs/LICENCE_ACTIVATION.md` §9)
- [ ] Trademark/domain check for the name the Store will be sold under (today: الستور / Al-Store) in EG, SA, AE (owner) — gate before selling; a new brand name is the owner's choice
- [ ] Clean-PC install + restore on a second clean PC (DATA-05, clean_device_restore) (field)
- [ ] One-hour session with a real cashier, including a keyboard-only journey (A11Y-01) (field)
- [ ] Receipt printer field test, 80 mm and 58 mm, Arabic shaping on the real driver (field)
- [ ] Two weeks at the first shop, cash only; owner's signed acceptance (core_user_acceptance) (field)
- [ ] Field visit: 5 Beni Suef shops answer docs/01-research.md §7 (owner) — gate before selling
- [ ] Support grant/repair flow in the UI (factory SUP-02/03, reference control)
- [ ] Supplier returns, cheque register (after pilot feedback)
