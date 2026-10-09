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

- [x] Design system v2 + Mizan (ميزان) identity on every screen, logo files, icon, splash; contrast and mark tests (docs/DESIGN.md)

- [x] 1.1.0 People, profiles and pages (factory access standard, BAMS model): editable profiles, page permissions, lock-out guard, who-can-do-what, audit of ticks; gate `afaccess` in tests
- [x] 1.2.0 implemented: role courses and coach, per-person progress, every server error explained, two-scope consent, IDs/counts-only usage/error telemetry and redacted free-text reports with explicit preview/send. Nothing leaves the PC without receiver URL and token; withdrawals work while licence-locked.
- [x] 1.2.0 automated release verification (2026-10-09 second pass): requested full browser-enabled command is green — **155 passed, 0 failures, 0 errors, 0 skips**, including all **16 browser tests**. No discovery changes or extra skips. Cause/fix report: `/workspace/grok-log/codex-report2.md`. Field checks below remain open.

- [x] 1.3.0 cash only everywhere (other ways hidden until the owner turns them on); ready-to-sell plan in `docs/03-ready-to-sell.md`

## Next (in order) — full list and reasons in docs/03-ready-to-sell.md
- [ ] Engineering gaps for the gate: owner password recovery (IAM-01), newer-data refusal test (DATA-06), kill-process drill (OPS-06), practice passwords refused in a real shop (IAM-06), secrets scan in CI (SEC-02), export formula test (SEC-07), drop `nuitka-4.2.2.tar.gz` from the repository
- [ ] Release-commit proofs: ui-lab rerun (PERF-01, A11Y-01 + a manual keyboard journey), Windows workflow run id and SHA in the release notes (OPS-01, OPS-07), upgrade 1.2.2 → 1.3.0 on a realistic copy (REL-03)
- [ ] Trademark/domain check for "Mizan / ميزان" in EG, SA, AE (owner) — **gate before renaming the installer and data folder**
- [ ] One-hour usability session with a real cashier on the new counter (owner)
- [ ] Field visit: 5 Beni Suef shops answer the 5 questions in docs/01-research.md §7 (owner) — **gate before selling**
- [x] Windows installer (Nuitka + Inno Setup): built, silently installed, started and uninstalled by the `windows installer` workflow on a real Windows runner (run 3 green). **Still to do by a person:** clean-PC install + restore drill
- [ ] Generate the vendor licence key in Licence Studio, put the public key in `licence_keys.txt`, build the pilot copy
- [ ] Receipt printer field test (80 mm and 58 mm, Arabic shaping on the actual printer driver)
- [x] Support heartbeat to the Vendor Control Center (opt-in, exact fields; Settings → Support). Still to do: a support grant/repair flow in the UI (factory SUP-02/03)
- [x] Barcode on the receipt + sticker labels (per copy or per serial) — Code 128, decoded by a real scanner library in the check
- [ ] Supplier returns, cheque register (after pilot feedback)
