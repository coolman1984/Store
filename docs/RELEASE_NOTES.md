# Release notes

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
