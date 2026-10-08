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

## Next (in order)
- [ ] Field visit: 5 Beni Suef shops answer the 5 questions in docs/01-research.md §7 (owner) — **gate before selling**
- [x] Windows installer (Nuitka + Inno Setup): built, silently installed, started and uninstalled by the `windows installer` workflow on a real Windows runner (run 3 green). **Still to do by a person:** clean-PC install + restore drill
- [ ] Generate the vendor licence key in Licence Studio, put the public key in `licence_keys.txt`, build the pilot copy
- [ ] Receipt printer field test (80 mm and 58 mm, Arabic shaping on the actual printer driver)
- [x] Support heartbeat to the Vendor Control Center (opt-in, exact fields; Settings → Support). Still to do: a support grant/repair flow in the UI (factory SUP-02/03)
- [x] Barcode on the receipt + sticker labels (per copy or per serial) — Code 128, decoded by a real scanner library in the check
- [ ] Supplier returns, cheque register (after pilot feedback)
