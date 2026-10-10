# Release notes

## 1.8.0
- **Fixed: the shop could stop answering until the program was restarted.** It happened when another program (a database viewer, a copy tool, an antivirus scan) held the shop's data for a moment. Now the person reads «بيانات المحل مشغولة دلوقتي، استنى لحظة وجرّب تاني» and the next press works.
- **Faster for a big shop:** the Customers page opened in 3 seconds with 4,000 customers and years of sales; it now opens at once. The safe's balance, a shift's summary and today's returns are faster too.
- **Fixed: the safe could show a negative amount.** Paying a supplier, an expense or a purchase from the safe is refused when the safe does not hold the money, and so is undoing a deposit or a collection that was already spent. The message says what to do: use the drawer, or record a deposit first.
- **Fixed: an instalment could be paid more than it owed.** A payment for a plan is limited to what is left on that plan.
- **Fixed: «This is more than what is owed (300000)»** is now written in pounds.
- **Fixed: the word «null» appeared in the guide's steps and in Settings → Privacy.**
- **Safer:** a person with no permissions can no longer take a return even when a manager types a password; every write is refused with «not allowed» before anything else is checked.
- **When the company agrees to your trial request, the screen says so** («الشركة وافقت على طلبك والكود بيتجهّز») while the code is prepared on the company's PC, then switches on by itself.
- Needs the company's relay with the owner's buttons switched on (Apps-Factory 0.14.0); without it nothing changes.

## 1.7.0
- **Practice with no fear, inside the program.** «المساعدة» now has a button that opens the practice shop (a made-up appliance shop with three weeks of history) beside the real one: its own folder, its own port, its own sign-in. Nothing from the real shop is copied into it and nothing from it can reach the real shop.
- **Three real problems to solve there**, each set up fresh with made-up goods and money: a fridge that comes back faulty (return as damaged, a manager approves, cash goes back); a drawer that is 15 pounds short (the forgotten tea-and-coffee expense, then close the shift with a zero difference); a shelf count that is two fans short (count, close with a reason, the books follow the shelf). «اتأكد من شغلي» reads the shop's own books and shows, check by check, what is right and what is still missing. «ابدأ من الأول» sets the same problem up again, and the owner can erase the whole practice shop and build a fresh one.
- **Kept apart on purpose:** a practice folder is never opened as a real shop and a real folder is never opened as the practice shop (the program stops with a plain message). Before this version, starting the practice shop while `STORE_HOME` was set pointed it at the real shop's own folder; it now sits beside it. The practice shop never sends telemetry or support data, whatever its settings say.
## 1.6.0
- **Ask for the trial from the licence screen.** «اطلب تجربة 14 يوم» sends a small request to the company (the device code, a fingerprint of this PC, the shop name and the version: «إيه اللي هيتبعت؟» shows it before anything goes out; no sales, customers or prices). The company's phone is told on Telegram, the company's licensing program signs a code for this device, and the program collects it, checks it with the company's public key and **switches itself on**, with nothing to copy. A PC gets one trial, even after a reinstall. A subscription or a permanent activation is requested the same way, and only goes out after the company has confirmed the payment.
- **No connection?** The screen says so, says when it will try again, and has a «حاول تاني دلوقتي» button. The manual way (device code out, code in) is always on the same screen and now names Telegram, not WhatsApp. The program keeps working in read / print / export / backup mode while it waits.
- **Safer:** a person with no permissions can no longer read a return or the warranty look-up (customer name and phone), and the export file leaves out purchase costs and national IDs for a person who may not see them. A sale put on the customer's account can no longer be returned in cash: what the customer still owes is taken off their account first, and only the rest is paid back. The practice shop no longer signs the real shop out of the same browser. Document headers (sales, returns, purchases, transfers, plans) are protected from edits like their lines.
- Needs the company to deploy the relay and write its address in `licence_relay.txt` (and the public key in `licence_keys.txt`) before a build. Without them only the manual way is offered.

## 1.5.0
- Activation codes come in three kinds:
  - a 14-day trial;
  - a monthly subscription: 30 days, then 3 days of grace by default (the vendor can change the days);
  - a permanent activation: it never ends, and it works on this PC only.
- The licence page shows which kind is active. When a subscription ends, the shop can still open, print, export and back up.
- Safer backups: a copy is written under a temporary name and only gets a backup name after it passes its check. A copy cut short by a power cut is never listed or offered for restore. Each copy is now one self-contained file, easy to put on a USB stick.
- A real shop refuses the practice shop's password and the passwords people try first (12345678, password…).
- Fixed: the home page showed «{hours}» in the backup reminder of a new shop.
- The Windows build check now runs a real shop on the installed program before and after an update. It sets up the shop, activates it, receives stock, sells for cash and makes a backup, then checks that the sale, the stock and the backup survive the update. It also runs the power-cut drill on Windows and saves a release proof: the source commit, the installer checksum and the run link.

## 1.4.0
- New: the owner's recovery code. When the shop is first set up, the program shows a code to print or write down. The owner cannot continue until they tick that it is kept. If the owner forgets the password, «نسيت كلمة السر؟» on the sign-in page takes the code and a new password. It also unlocks a locked account and signs out every old session. The code works once, then the program shows a new one. If the paper is lost, the owner can make a new code in Settings → People after typing their password; the old code stops working. There is no master password. Only the code's protected form is kept on the PC, and wrong codes are counted like wrong passwords. It works while the licence is locked.
- Fixed: the guide button on the sign-in page read «الدليلnull» (factory af-guide 0.1.2).

## 1.3.0
- Cash only: every shop, new or updated, takes cash only. The counter shows no payment choices, returns refund in cash, and collections are cash. Card, mobile wallet, InstaPay, finance companies, on account and shop instalments are hidden everywhere and refused by the server until the owner ticks them in Settings → Shop → How customers pay. Cash can never be turned off.
- Turning a way off never removes or hides old sales; they stay in the reports. A return on an old card or wallet sale is refunded in cash.
- The instalment settings and the wallet number on the receipt only show when those ways are turned on.
- Fixed: opening a page you are not allowed to see could be covered a moment later by the page that was still loading.

## 1.2.2
- Fixed: the Windows installer now includes the in-app guide and the privacy settings files, so the installed program starts and shows the guide. The build checks that every file the program needs is in the program folder.

## 1.2.1
- Problem reports: before you send, you now see a plain summary in your language. It shows what will be sent (your description with passwords and phone numbers removed, the program version, the problem type, and the page) and what will not be sent. The technical details are still available on request. Cancel closes the report without saving anything.

## 1.2.0 — release candidate
- New: Arabic and English in-app courses for owners, managers, cashiers and storekeepers, with per-person progress and a step-by-step coach. Custom profiles follow their permissions. Press F1 or the ? button for help.
- New: each server error has an explanation and a next action. Arabic guidance uses «العربية الميسّرة»; the sale lesson is «إنشاء فاتورة بيع».
- New: first-sign-in consent and Settings → Privacy and help. Both the shop and person must agree; changing the shop's choice preserves the person's previous refusal. Withdrawing removes pending events and reports.
- Restored: write a problem report in your own words. The factory redactor removes recognized secrets and phone-like strings before the complete preview and local storage. Both the shop and person must consent; only pressing Queue report saves it. Editing text or diagnostics requires a new preview. Existing free-text reports with current consent are kept. Usage/error telemetry still collects only allowed IDs/counts, without typed business input or screenshots.
- Nothing leaves this PC until a receiver address and token are configured. Sending runs in the background and does not block new event requests during the network timeout. HTTPS or exact local endpoints only; redirects are refused.
- Fixed: consent covering shop controls, guide chrome covering dialog buttons, and the narrow phone top bar. Guide controls remain inside their panel when changing language; old controllers and telemetry cannot follow someone into another account.
- Fixed: signing in again after logout could fail when the browser reused its connection. The server now reads the logout request body before replying.
- Fixed: the open help panel stays clickable above a paused or active lesson card, including its Report a problem button.
- Guide, progress and privacy withdrawal stay available while the licence is locked. Restore reconnects consent and removes pending events that no longer have permission to send.
- Automated verification complete in the socket-enabled session: **155 tests passed, 0 failures, 0 errors, 0 skips**, including all 16 browser tests. Relogin, report redaction/confirmation, preserved consented reports and the AR/EN report dialog are covered. Field acceptance checks in TASKS remain separate.

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
