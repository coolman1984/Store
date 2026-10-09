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
2. Put the vendor's **public** key line(s) in `licence_keys.txt` (from Licence Studio → Keys). Never a private key. Put the licence relay's **https address** in `licence_relay.txt` (a public address, no token): with it the licence screen asks for the trial by itself; without it only the manual way is offered.
3. Merge to `main` (every push to main builds a tested installer artifact), push a tag `vX.Y.Z` for a release, or run the workflow `windows installer` by hand. It: checks the files → compiles with Nuitka (no readable source
   in the program folder) → builds `Al-Store-Setup-<version>.exe` with Inno Setup → starts the program folder and the installed copy and
   checks they serve pages → uninstalls and checks the shop's data survived.
4. Download the installer from the workflow's artifacts. Test on a clean PC: install, open, activate a trial code, sell, back up, restore.

Locally on Windows: `pip install nuitka ordered-set zstandard pillow`, install Inno Setup 6, `python tools/build_windows.py`.
Anywhere: `python tools/build_windows.py --check` (seconds) and `python tools/smoke_exe.py python server/app.py`.

Updating a shop: run the newer Setup on the same PC. Only the program in Program Files is replaced; `%ProgramData%\Al-Store` (data, backups, config) is never touched, and a newer database schema is migrated after a verified copy.
