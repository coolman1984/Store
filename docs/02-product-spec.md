# Al-Store (الستور) — product spec v1.0 (pilot core)

**Buyer:** owner of one household-goods & electrical-appliances shop in Egypt (first customer: Beni Suef), 1 main PC at the
counter, phones on the shop Wi-Fi, 2–6 staff. **Users are not technical.** Research: [01-research.md](01-research.md).

## The one paid journey
Open the shift with a float → sell by barcode/keyboard (serial for appliances) → take cash / card / wallet / InstaPay /
finance company / on account / shop instalments → print or WhatsApp the receipt → take a return linked to the original line
with a manager's approval → close the shift by counting → the owner sees differences in **the owner's eye**.
Everything in between (receiving with serials and cost, moving store → shop, shelves, counting, bulk price changes, customer
balances and instalment collection) exists to make that journey correct.

## Acceptance criteria (each has an automated test)
| # | Criterion | Test |
|---|---|---|
| A1 | A one-product cash sale with change takes under 10 s by keyboard and never records twice on retry | `test_e2e_browser.CoreJourney`, `test_domain.SellingTests.test_cash_sale_moves_stock_drawer_and_is_idempotent`, `test_api.test_full_sale_and_receipt_over_http` |
| A2 | Discounts above the seller's limit, prices under the minimum/under cost and going over a credit limit need another person's password; wrong tries count toward the lockout | `test_domain.SellingTests.*approval*`, `test_wrong_approval_password_counts_as_failed_login` |
| A3 | An appliance can only be sold with a serial that is really in stock in that place; warranty look-up by serial | `test_serial_rules`, `test_transfer_and_serial_location` |
| A4 | A return refunds at most what was paid for that line (after discount), puts goods back (good → shelf, damaged → damaged place) and is shown to the owner | `ReturnTests` |
| A5 | Shop instalments: fee, monthly amount rounded to pounds, schedule, late list, collections and reversals; down-payment minimum enforced | `CreditTests` |
| A6 | Drawer expected = float + cash in − cash out; closing records over/short with a reason and moves cash to the safe | `CashTests` |
| A7 | Money and stock are append-only (database triggers refuse UPDATE/DELETE); balances are computed | `test_ledger_rows_cannot_be_edited_or_deleted` |
| A8 | Bulk price change: preview, rounding, dated start, past sales unchanged | `PriceTests` |
| A9 | Without a valid licence code (none, other PC, expired, clock moved back) the shop can read, export and back up, but cannot sell or change data | `LicenceGateTests`, `test_e2e_browser.LicenceLock` |
| A10 | Cashier never sees cost/profit or the admin pages; every refusal is logged | `test_cashier_sees_no_cost_and_cannot_manage` |
| A11 | The owner decides per person which pages they see and what they may do (profiles + ticks); hidden pages are refused by the server; nobody can lock the shop out of its people screen; every change of ticks is audited | `test_access`, `test_e2e_browser.PeopleAndProfiles` |
| A11 | Arabic RTL and English LTR, light/dark/high-contrast, text size up to XL: no page wider than the screen, no text out of its card at 360 / 390 / 820 / 1366 px | `test_e2e_browser.LayoutSweep` |
| A12 | Strict CSP, Host and Origin checks, HttpOnly SameSite cookie | `test_boot_and_security_headers`, `test_dns_rebinding_and_cross_site_writes_refused` |

## Scope
**In v1.0:** everything above, plus practice shop (separate folder, demo accounts, PRACTICE on receipts), command palette,
advisor ("do this now"), reports (period, by category/brand/seller/product, payment methods, balances, year turnover for the
simplified tax regime), stock value and slow movers, CSV/zip export, automatic checked backups and restore.
**Not in v1.0 (decided, not forgotten):** ETA e-receipt integration (needs registration and certified device), multi-branch
sync, online store, delivery tracking, supplier returns, loyalty points, label printing, cheque register, Windows installer
(use `start.bat` + embedded Python; installer = the factory's next shared piece), the vendor support window (Control Center).

## Architecture
Python 3.11+ standard library server (`server/`), one SQLite file in WAL mode, plain ES-module front end (`web/`), no build step.
Connectivity tier `office_server`: the counter PC owns the data, phones open it on the LAN. UUIDv7 ids and org/branch columns
everywhere so a later `office_mesh` / `cloud_sync` tier never rewrites records. Licence: Ed25519 codes from the factory's
Licence Studio, verified here with the vendored stdlib checker (`server/afcodes.py`, `server/ed25519.py`).

## Data map (privacy by design)
Customer name, mobile, address (needed for instalments and delivery); national ID **optional**, only visible with
`customers.private`; guarantor name/mobile. Nothing leaves the PC unless the owner turns on optional remote help in Settings.
That help sends counts and ids only, and only after the shop and the person both agree. Passwords, typed text, screenshots,
names, phone numbers and amounts are never sent. Sending stays off until the owner sets a receiver address and a token.
Sessions, failed logins and every write are in the audit table. Backups contain personal data: keep them on the shop's own
disks (the program refuses nothing here; the guide says so).
