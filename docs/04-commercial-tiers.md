# Al-Store: four small-business plans (owner decision 2026-10-09)

**This is a staged commercial roadmap, not a claim that cloud sync or mobile apps already work.** The one-PC cash-only pilot remains the core priority, with no destructive data migration or new payment methods switched on automatically. Factory source of truth: `coolman1984/Apps-Factory/docs/SMB_COMMERCIAL_TIERS.md`.

| Plan | What the buyer gets | Store state |
| --- | --- | --- |
| 1 Solo | One Windows shop PC with SQLite, works offline; encrypted automatic **off-PC cloud backups**, plus local restore points | Core shop app built. Encrypted cloud backup, restore-on-different-PC, backup age warning **not yet verified/built**. Do NOT claim sale-ready or loss-proof |
| 2 Connected | More than one shop PC, offline-first sync via authenticated cloud hub; ONLY the shop owner sees read-only live metrics on installed Android/iPhone web app | Planned; no verified multi-PC cloud sync or owner app |
| 3 Mobile Operations | Plan 2 plus permissioned users selling, viewing stock, scanning barcode and running approved operations from installed mobile PWA | Planned; do not reuse browser screen as evidence of operational mobile client |
| 4 Cloud Business | Hosted core; authorized browser, mobile web app and Windows clients with exports/backups | Planned; do not build a large SaaS platform before demand |

**Separation:** solo cloud backup is NOT cloud sync. Shop data is always authoritative locally in plan 1; uploading backup copies must not allow accidental overwrite on another device. Clients never query cloud databases directly. Only the shop owner has a mobile seat in plan 2; plan 3 introduces explicitly entitled employee seats. Prices, hosting region, retention and mobile actions require recorded owner decisions.

## Windows release is mandatory first

The Windows CI workflow `.github/workflows/windows.yml` must run on PR and main, build the installer and test installed app start, stop and uninstall data retention. A failing/pending workflow must block merges via GitHub branch protection/ruleset required status. Windows GitHub VM is still no substitute for a separate clean-PC install and physical 58/80mm Arabic receipt printer + scanner checks. Record run link and installer SHA at the exact release commit.

## Work in order, without scope explosion

- **W0 (before any sale):** PR Windows job green for release candidate; all 32 applicable factory controls, real manual keyboard/cashier acceptance, no demo login, backup+restore on another PC and receipt printer check. Existing cash-only checkout must not regress.
- **D1 (required for advertised Solo cloud-protected plan):** safe SQLite backup snapshots, encrypted/versioned off-device upload, customer-controlled key recovery, bounded retry queue, backup-age UI/warnings, three separate recoverable copies, forced-failure test and restore on different PC. Customer approves storage and residency before first upload. Until D1 verified, label cloud backup as NOT AVAILABLE and offer explicit provisional on-site pilot/backup arrangement; do not claim the desired Tier 1 delivered.
- **S2 (after paid Solo field acceptance):** cloud hub shared by PCs, scoped enrollment, conflict and stock/payment pending states, separate backup system; owner-only mobile read endpoints with server-enforced read-only.
- **M3 (only after plan 2 works):** HTTPS hosted installable PWA with install/standalone test on Android/iOS; safe sales, staff roles, barcode camera detection with manual/HID fallback, retry+duplicate protection and manual device checks.
- **C4 (only with buyer demand):** hosted web-first deployment with per-tenant access, backups, migration, offline limitations explicitly stated and cost accounting.

**Acceptance for each tier:** verified at targeted Git SHA + green Windows CI + restored external backup + actual customer journey on target PCs/phones. Keep scope and commercial decisions in release docs. Never advertise "no data loss", "mobile installed", "automatic cloud sync" without actual evidence.

Sources: https://sqlite.org/backup.html · https://web.dev/learn/pwa/installation · https://developer.mozilla.org/en-US/docs/Web/API/Barcode_Detection_API
