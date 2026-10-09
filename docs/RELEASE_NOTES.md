# Release notes

## 1.2.0
- New: an in-app guide. Each person sees a short course for their profile (owner, manager, cashier, storekeeper). The coach shows step i of n. Press ? or F1 on any page.
- New: every error the program can show has a plain explanation: what you see, why, and what to do.
- New: the first time someone signs in, a card asks about remote help. The two buttons are equal. Settings → Privacy and help can change or withdraw that choice.
- Remote help is off unless the owner sets a receiver address and a token. Until then nothing leaves this PC. Passwords, names, phone numbers and amounts are never included.

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
