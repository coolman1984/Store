# Al-Store: safe learn-by-doing Demo Mode, then Pixel Plus public demo
Owner roadmap • 9 October 2026 | Status: PLANNED, not a delivery claim.

## Existing foundation (do not rebuild)
- Store already has a separate synthetic practice shop via `python server/app.py --practice` / `practice.bat`.
- Guide has role courses, hints and saved progress. Reuse these.
- Keep the current cash-only first-shop pilot and license/security/recovery changes; do not disturb Opus 5.5's in-progress release or customer database.

## Local customer experience (first deliverable)
- Add one permanent **وضع التجربة / Demo Mode** entry to the Help/Guide screen, without adding a dangerous production-mode flag.
- Opening the entry launches **a physically separate practice DB and configuration** in its own isolated server/session/window. Returning brings the user back to the unchanged real shop. Clear banner, exit and **reset sample shop**.
- Choice: "اتعلّم خطوة خطوة" or "جرّب لوحدك". Role packs: owner, cashier, stock clerk, manager, with server-enforced role limits in demo.
- Real scenario A: cashier opens shift, sells a fan by barcode/keyboard, accepts cash, closes shift with an unexpected drawer shortage; guide helps diagnose.
- Real scenario B: stock clerk receives goods, notices incorrect quantities, fixes the stock through the intended audited correction workflow; then restores the seed to learn again.
- Real scenario C: owner reviews an excessive discount and a return with a linked receipt; manager authorization changes real demo records but nothing production.
- Every lesson has initial state, instructions, actual expected data change, possible mistake, hint, and a deterministic success check. "Show me" steps cannot mark a task done without verification.
- The exercise can delete/edit **only synthetic demo records**; reset makes a fresh demo instance. Never create real customers, send external WhatsApp/email, charge a payment instrument, use a production printer, or upload a customer's real backups.
- Include clean failure/restart, role switching through an authorized demo-only login, Arabic RTL and mobile layout tests; never ship static production demo credentials, and never let demo sessions hit real shop APIs.

## Future Pixel Plus online Store trial (separate phase)
- Launch from a dedicated Store product page: genuine product tour, live sandbox Try Now, 4 tier comparison (published only if actually offered), request quote and download Windows trial.
- Session-scoped seeded synthetic database (no public shared mutable demo data), reset and auto-expiry, quotas, rate-limits, no risky outbound network access, strict tenancy checks.
- Online demo must use authentic Store business rules, not clickable fake screenshots; Store's Python backend requires real isolated hosting and a measured cost/abuse review before enabling public access.
- The live demo site is NOT the actual paying customer's cloud business system. Do not ship plans 2–4 until each plan passes its distinct real tests.

## Gates
1. Existing Store paid-trial readiness unaffected: Windows installer checks, device-bound licensing, clean-PC restore and a real cashier/printer.
2. Demo-mode features pass negative tests: real production DB state unchanged before/after every simulated create/update/delete and reset; no real external side effects; permissions held, roles isolated; demo and production data directories can't be configured equal.
3. Website trial needs public isolation and load/cost protections and a customer-verified user journey. Label unavailable until actually deployed.
4. Stop the scope at 3 Store guided challenges and one isolated demo launcher first. Share with other products only after two products prove the same reusable interface.

Source of truth: `Apps-Factory/docs/PIXEL_PLUS_EXPERIENCE_ROADMAP.md` (companion PR). No pricing, contact details or host has been chosen.
