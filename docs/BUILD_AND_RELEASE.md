# Build and release

**Windows CI update:** `.github/workflows/windows.yml` runs on pull requests into main as well as pushes to main. Require the exact `windows installer / installer` job in the repository ruleset/branch protection; a workflow alone does not prevent merging a failed build. The standalone clean-PC restore remains mandatory. Four-plan staged roadmap: [commercial tiers](04-commercial-tiers.md).


**Status:** `verified` by the workflow `windows installer` on a real Windows runner (build → start the program folder → silent install → start the installed program → uninstall keeps the data; first green run: Actions run 3 of 2026-10-08). A clean-PC install by a person is still a separate gate (factory DELIVERY_GATES).

Since 1.5.0 the same workflow also:
- runs the power-cut drill on Windows (`tests/test_release.py`);
- runs a **real shop journey** on the installed program (`tools/journey_exe.py first`): setup, licence, stock, cash sale, backup;
- installs the same Setup again over it, as an update, and checks the sale, the stock and the backup survived and the shop still sells (`journey_exe.py after`);
- writes `RELEASE-PROOF.txt` next to the installer artifact: the version, the source commit, the installer SHA-256 and the run link (factory OPS-01).

**Rollback:** run the previous Setup. Data is never touched by Setup. A newer database is refused by an older program, and the copy made before the upgrade (`…-before-upgrade.db`) can be restored from Settings → Backups.

1. Change `server/version.py` (VERSION) and describe the version in `docs/RELEASE_NOTES.md` (the build refuses otherwise).
2. Put the vendor's **public** key line(s) in `licence_keys.txt` (from Licence Studio → Keys, plus `trial-hub:<public>` for hub-signed trials). Never a private key. Put the licence relay's **https address** in `licence_relay.txt` (a public address, no token): with it the licence screen asks for the trial by itself; without it only the manual way is offered. Deploy the optional `licence-hub/` Worker from the owner's machine (`npx wrangler deploy` — **not** from CI); full steps in `docs/HUB_SETUP.md` and `licence-hub/README.md`. Telegram for the manual path: `vendor_telegram` in the shop's `config.json` on the installed PC (placeholder in tests: `@alstore_support`), not in this repository.
3. **Factory / CI installer** (empty `licence_keys.txt` and `licence_relay.txt` templates in git): every merge to `main` runs the `installer` job in `.github/workflows/windows.yml`. It builds with `python tools/build_windows.py`, runs the shop journey with a one-run test key in the environment, and writes `RELEASE-PROOF.txt` with `customer_licence: no`. That artifact is for regression only — a shop cannot activate from it.
4. **Customer installer** (pilot and field proofs): supply the vendor **public** key lines and the relay **https address** at build time only — never a private key in git or in Actions. **Public keys:** one or more `kid:key` lines with exactly one `trial-hub:` line (hub-signed trials only; the program still limits that key to device-bound trials of at most 14 days) and any number of `studio:` lines (Licence Studio paid codes). Duplicate kids or unknown kids are rejected. The relay **hostname** must match **exactly** one line in `tools/relay_hosts_allowed.txt` (comment-only in git until the owner adds the real Worker host) or one name in `STORE_RELEASE_ALLOWED_RELAY_HOSTS` (comma- or space-separated). Allowed paths after the host are only `` (none), `/api`, and `/licence-hub`; https only, no IP address, userinfo, query, fragment, or custom port. On the owner's PC you may put the key lines in `licence_keys.txt` and one address in `licence_relay.txt`, then `python tools/build_windows.py --customer`. In CI, set secrets `STORE_RELEASE_PUBLIC_KEY` (newline-separated `kid:key` lines), `STORE_RELEASE_RELAY_URL`, and `STORE_RELEASE_ALLOWED_RELAY_HOSTS` (the hostname from the relay URL, e.g. `al-store-licence.mycompany.workers.dev`); the optional `customer-installer` job runs when the key and relay URL secrets are set. The workflow never prints secret values.
5. Merge to `main`, push a tag `vX.Y.Z`, or run `windows installer` by hand. The main job: checks the files → Nuitka → Inno Setup → smoke and journey on the installed program → uninstall keeps data.
6. Download the right artifact. Test on a clean PC with the **customer** Setup: install, open, request a trial or paste a code, sell, back up, restore.

Locally on Windows: `pip install nuitka ordered-set zstandard pillow`, install Inno Setup 6, `python tools/build_windows.py` (factory) or `python tools/build_windows.py --customer` (shop copy).
Anywhere: `python tools/build_windows.py --check` (seconds; templates OK) and `python tools/build_windows.py --check --customer` with `STORE_RELEASE_*` or filled licence files; `python tools/smoke_exe.py python server/app.py`.

Updating a shop: run the newer Setup on the same PC. Only the program in Program Files is replaced; `%ProgramData%\Al-Store` (data, backups, config) is never touched, and a newer database schema is migrated after a verified copy.
