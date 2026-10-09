# Release notes

## 1.2.0 — release candidate
- New: Arabic and English in-app courses for owners, managers, cashiers and storekeepers, with per-person progress and a step-by-step coach. Custom profiles follow their permissions. Press F1 or the ? button for help.
- New: each server error has an explanation and a next action. Arabic guidance uses «العربية الميسّرة»; the sale lesson is «إنشاء فاتورة بيع».
- New: first-sign-in consent and Settings → Privacy and help. Both the shop and person must agree; changing the shop's choice preserves the person's previous refusal. Withdrawing removes pending events and reports.
- Reports include IDs and optional device counts/versions only, with a confirmed preview. No free text, passwords, typed input, screenshots, names, phones, amounts or business records are collected.
- Nothing leaves this PC until a receiver address and token are configured. Sending runs in the background and does not block new event requests during the network timeout. HTTPS or exact local endpoints only; redirects are refused.
- Fixed: consent covering shop controls, guide chrome covering dialog buttons, and the narrow phone top bar. Guide controls remain inside their panel when changing language; old controllers and telemetry cannot follow someone into another account.
- Guide, progress and privacy withdrawal stay available while the licence is locked. Restore reconnects consent and removes pending events that no longer have permission to send.
- Validation pending: the browser-enabled full suite could not start its HTTP servers in this sandbox (socket creation refused). Run it in a socket-enabled environment before releasing 1.2.0.

## 1.1.0
- New: **profiles** — ready-made sets of permissions you can rename, change (for everybody who has them at once) or delete, and
  your own new ones. The owner profile always has everything.
- New: choose per person which **pages** they see (Products, Stock, Customers have their own tick now); hidden pages disappear
  from the menu and the main PC refuses their data.
- New: **Who can do what** — every permission against every profile in one table, printable.
- Fixed: removing "People and permissions" from the only owner could lock the shop out of its own people screen. Now refused,
  and a shop already in that state is repaired at start.
- Every change of a person's or profile's permissions is in the activity log with what was added and removed.

## 1.0.2
- Fixed: a return listing the same sale line twice could refund twice; an empty licence box wiped the working code; the safe
  grew by the float at every shift; a sale after counting a product turned into a false surplus; the owing-customers list
  hid people past the 200th; many requests with strange values now get a calm message instead of "unexpected problem".
- Restore swaps the database file in one step (a power cut cannot leave half a file).
- New: Windows installer (tools/build_windows.py), `Al-Store.exe --version`.

## 1.0.1
- Measured by the factory's UI Lab: contrast, keyboard-reachable tables, no layout jump on phones, lighter side rail.

## 1.0.0
- First pilot version: counter, serial numbers, returns, shifts, safe, instalments, suppliers, owner's eye, checked backups,
  14-day device-bound licence codes, practice shop.
