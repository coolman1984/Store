# Al-Store (الستور) — rules for every change

Owner: Mohamed. Users are shop owners, cashiers and storekeepers who are **not technical**.
Built by the owner's Apps Factory (`coolman1984/Apps-Factory`): read its `AGENTS.md` and `FACTORY_CONSTITUTION.md` first,
then `docs/02-product-spec.md` here, then `TASKS.md` (where to continue) and `DEVELOPMENT_HISTORY.md` (what happened and why).

## Always
1. Same commit: code + test + **both** dictionaries (`web/i18n/ar.js`, `web/i18n/en.js`) + docs + a `DEVELOPMENT_HISTORY.md` entry.
2. Server: Python standard library only. Browser: plain ES modules, no framework, no build step, no CDN.
3. Every write: permission checked on the server, inside one transaction, audited, idempotent when it moves money or goods.
4. Run before every push: `python -m unittest discover -s tests` (Playwright tests skip themselves if no browser).
5. Replies to the owner: simple Egyptian Arabic, conclusion first.

## Never
- Never edit or delete a money/stock row: the ledger tables have triggers that refuse it. Correct with a reversing row and a reason.
- Never store a balance (stock, drawer, safe, customer, supplier): compute it from the rows.
- Never write an inline `style=""` or inline script: the CSP forbids them (use classes, `data-w` + `hydrate`, or CSSOM).
- Never put a quoted attribute string inside `html\`\``: it gets escaped — use `raw()` / `CUR`.
- Never let an expired licence hide, lock or delete data: reading, export and backup always work.
- Never commit a private key, a real customer's data or a real phone number (this repository is public).
- Never push to `main` or force-push.

## Map
`server/app.py` HTTP + security · `auth.py` people/permissions · `catalog.py` products/prices · `stock.py` places/serials/receiving/
transfers/counts · `sales.py` counter/returns/warranty · `money.py` shifts/drawer/safe/customers/instalments/suppliers ·
`reports.py` reports/advisor/owner's eye · `licence.py` + vendored `afcodes.py`/`ed25519.py` · vendored `afaccess.py` (factory access gate, `tests/test_access.py`) · `backup.py` · `sample.py` practice shop.
Design: `docs/DESIGN.md` (Mizan design system v2 — tokens only, rules §6) · `web/js/brand.js` the mark.
`web/js/app.js` shell/router/palette · `ui.js` safe HTML, dialogs, approvals · `motion.js` · `views/*.js` one file per page.
