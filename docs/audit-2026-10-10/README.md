# Audit round of 2026-10-10 (Al-Store 1.8.0): evidence

Screens taken in a real browser (Chromium, the practice shop, English, signed in as the cashier). Each pair is the same screen on 1.7.0 and on 1.8.0.

| File | What it shows |
|---|---|
| `before-guide-coach-en.png` / `after-guide-coach-en.png` | The guide's coach on step 1 of the first lesson: «nullnull» between the instruction and «I will move on by myself…» (1.7.0, every step) and the clean card (1.8.0). |
| `before-settings-privacy-cashier-en.png` / `after-settings-privacy-cashier-en.png` | Settings → Privacy for a person who cannot change settings: «nullnull» before «What was sent?» (1.7.0) and the clean block (1.8.0). |

The cause, the fix and the test that fails on 1.7.0 are in `DEVELOPMENT_HISTORY.md` (entry of 2026-10-10). The UI Lab report of this version is `docs/ui-lab/REPORT.md`.
