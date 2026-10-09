# Codex report 1 — Al-Store 1.2.0 review

Date: 2026-10-09. Working directory: `/workspace/store-rollout`.

Implemented the review fixes, Arabic guide edits and consolidated 1.2.0 documentation. Release verification is **not complete**: the environment prohibits local sockets, so the HTTP/browser tests cannot start. No git commands were executed, no commits were made, no workflows were touched, and none of the prohibited vendored files were edited.

The requested destination `/workspace/grok-log/codex-report1.md` is outside the session's writable roots (`/workspace/store-rollout` and `/tmp`), and approval escalation is disabled. This complete report is saved at `/workspace/store-rollout/codex-report1.md` instead. Copying it to the requested destination remains undone.

Bugs, causes and fixes:

| Bug / cause | Fix and evidence |
| --- | --- |
| Full-screen consent intercepted shop clicks; floating guide painted above dialog footers; phone top bar had overflow. | Retained the existing product CSS corner-card/top-bar fixes; moved all guide chrome below shop dialogs and corrected the corner card's accessibility semantics to nonmodal. Added a browser regression exercising a shop dialog while consent remains unanswered and measuring the 360px document width. Browser execution is blocked here. |
| Factory `display: grid` could override a coach's HTML `hidden` state. | Explicit product `[hidden]` overrides in `web/css/pages.css`. |
| Shell replacement preserved every marked descendant, detaching buttons and step text from their panel/card. | `replaceBody` now preserves only the factory widget roots. Added a browser language-switch regression that checks controls stay inside the panel. Browser execution is blocked here. |
| Reinitializing a guide leaked document F1 handlers, window hash handlers and coach timers across account changes. | Stop/dispose the old controller, remove its registered global listeners, cancel stale asynchronous mounts/prompts, and suppress old pending progress writes. Added a browser relogin regression checking a storekeeper's current course and one guide instance. Browser execution is blocked here. |
| Progress POST responses could arrive in a different order, replacing newer local progress with older results. | Serialize progress requests within each controller. Old-controller writes are disabled on disposal. |
| Failed guide-file requests stayed cached forever and could prevent normal startup. | Check HTTP success, clear failed file promises, retry later and allow the shop shell to open without loaded guide assets. |
| Failed consent saves caused an unhandled rejected promise with no visible retry state; repeated clicks could race decisions. | Disable both choice buttons during save, restore them and show a translated retry message on failure. Cancel stale-session prompts. |
| Browser events queued before consent or under a prior account could later be submitted under another account. | Gate product telemetry on the current consent status/session, clear pending client batches before enabling consent or changing session, and refresh the gate after Settings changes. Server consent remains the final gate. |
| The no-op `inst = 'decline' if decision == 'decline' else decision` hid missing decision validation; list/object values could raise TypeError. | Remove the no-op and validate scope, decision, consent text ID and language before any transaction or purge. Real SQLite regression verifies no partial records or outbox changes. |
| Re-enabling installation consent overwrote the administrator's previous personal decline/withdrawal. | Record an initial personal answer only when no personal record exists; preserve all prior personal choices. Tests cover re-agreement, withdrawal, permission denial and prompt behavior. |
| Consent was read through the shared raw SQLite connection without the shop lock, allowing uncommitted decisions to be used by another thread. | Use consistent shop-lock then outbox-lock order around telemetry consent reads. A threaded rollback regression proves an event waits for the consent transaction and cannot be queued from a rolled-back agreement. |
| Remote sending held the outbox lock for the full HTTP timeout. Releasing it naively would let merged counts be deleted with the acknowledged old event. | Use the vendored `send_once(post=...)` hook: release/reacquire the queue lock only during transport, serialize sends with a separate send lock and clear in-flight merge keys so later counts get new event IDs. Concurrency tests prove event collection proceeds during blocked transport, new counts survive acknowledgment and offline failure preserves both batches. |
| Installation/person withdrawal left feedback queued because the factory exempts reports. | Product consent callbacks purge reports too. Restore/startup/send preparation prune events without current consent and legacy free-text reports. |
| Factory reports bypassed tracking consent and permitted free text; the original glue accepted optional confirmation and user-provided diagnostics. | Product reports require installation AND personal consent and mandatory signed preview confirmation. Reports contain known context IDs, the fixed `user.report` ID and optional server-derived counts/versions. The product taxonomy copy restricts the report text slot to a machine ID; no vendored taxonomy is edited. The UI has no free-text field and says reports are queued locally. Regression tests verify no names, amounts or passwords enter the report. |
| Recomputing live diagnostics at submission could differ from the preview, while accepting client diagnostic strings could admit names. | Preserve the original server-generated snapshot, authenticate the complete preview using HMAC and refuse changes/forged diagnostic values. A regression verifies the exact displayed snapshot is queued even when live diagnostics change. |
| Machine-ID syntax alone allowed an English name to be disguised as a page, lesson or error-path ID. | Validate browser/report contexts against the actual product catalogue/pages/permissions and known client error locations. Unknown server request paths become the fixed `server` location, with no message text. Tests cover fake names and phone-bearing URLs. |
| Malformed browser event type/data could escape factory validation as a TypeError. | Reject malformed entries before the factory batch API; return rejection counts without a server error. |
| Receiver URL prefix checks accepted `http://localhost.evil.example` or user-info pointing to another host, and normal redirects could forward the receiver token. | Parse and validate exact hostnames, schemes, ports, fragments and user-info; validate token/header characters; disable redirects in product transport. Tests exercise malicious prefixes, malformed settings and redirect handling without real network access. |
| Config writes could truncate `config.json`; failed saves could leave changed in-memory settings. | Stage, flush/fsync and atomically replace config; restore in-memory settings on I/O failure. Consent and config changes are audited without receiver tokens or personal records. |
| Licence-lock handling blocked even disabling the telemetry receiver. | Allow empty receiver/clear-token operations with an expired licence; enabling still requires a full licence and `settings.edit`. Guide progress, consent and event/report routes remain available with their existing authentication and consent checks. A direct-handler regression uses the real licence and SQLite logic without sockets. |
| Restore swapped the shop connection while telemetry retained the old connection; restored consent could disappear while the independent outbox survived. | Rebind consent and prune the outbox under the same shop lock before requests resume. A real backup/restore test verifies the new connection and consent-based purge. |
| Restore closed the live connection before staging succeeded, and a failed swap left the server connection closed. | Complete staging before closing the live connection; reopen and rebind in a finally block after the swap attempt. Tests simulate both copy and swap failures and prove the shop remains usable. |
| The sent-history route exposed other people's usage metadata. | Filter the public sent viewer to the signed-in person's pseudonymous subject. Regression covers owner/cashier separation. |
| New telemetry SQLite connections were not closed by shared test fixtures; importing the privacy module depended on previous discovery imports setting sys.path. | Close telemetry idempotently in Shop.cleanup/Server.stop, and import the harness before server modules in test_privacy.py. The privacy tests now run independently. |
| Guide title «عمل فاتورة» and some instructions were too colloquial or combined navigation/actions. | Use «إنشاء فاتورة بيع», correct the sign-in username instruction and shorten related guidance. The Arabic title regression and factory release checker pass. |
| History had separate partial 1.2.0 entries and TASKS marked it done despite missing browser verification. | Consolidate DEVELOPMENT_HISTORY.md into one 1.2.0 entry, update RELEASE_NOTES and mark implementation separately from the pending full release check in TASKS. |

Exact final requested command:

```sh
cd /workspace/store-rollout/tests
STORE_CHROMIUM=/home/box/.cache/ms-playwright/chromium-1194/chrome-linux/chrome /workspace/.venv-store/bin/python -m unittest discover
```

Output was captured without changing discovery or skipping tests. Final result:

```text
Ran 102 tests in 9.944s
FAILED (errors=19)
```

Exit code: 1. There were **0 assertion failures and 0 skips**. All 19 errors were `PermissionError: [Errno 1] Operation not permitted` from `socket.socket()` in the server test harness: **12 setUpClass errors and 7 individual test setup errors**. The full suite discovers **149 test cases**, including **14 browser tests**; those browser tests never started. Failed class setup prevents unittest from running the class's cases, so `102` is not the number of discovered tests and `102 - 19` is not a valid passed-test count. Full output remains in `/tmp/store-rollout-suite-final.log`.

Separate executed socket-free selection:

```sh
cd /workspace/store-rollout/tests
/workspace/.venv-store/bin/python -m unittest test_access.Catalogue test_access.Guards test_access.Profiles test_access.CarryOver test_access.Upgrade test_console test_domain test_frontend test_guide.Catalogue test_guide.LiveStates test_privacy.GluePrivacy
```

```text
Ran 95 tests in 10.297s
OK
```

That includes all **19 new glue regressions**, the guide's real-product release checker and CLI release check, Arabic title regression, domain ledger tests and frontend/static checks. Raw selection output is in `/tmp/store-rollout-local-final.log`. Two SQLite ResourceWarnings remain from upgrade fixtures; they do not fail the tests. No existing tests were weakened, deleted or skipped.

Also executed: Node module syntax checks on `guide.js`, `app.js`, `views/settings.js` and both dictionaries; Python compilation of `assist.py`, `app.py`, both guide/privacy test modules, browser tests and harness. All passed.

Left undone / limitations:

- A green full suite and real browser validation, including the former click timeouts, phone overflow and GuideCoach advancement, require an environment that permits local sockets. The 14 browser tests remain unverified; do not release on the basis of the socket-free selection alone.
- Existing HTTP/security, fuzz and mutation tests also require that socket-enabled full run. Their class setup errors were not converted to skips.
- Writing this report to `/workspace/grok-log/codex-report1.md` is blocked by filesystem permissions; this workspace copy is complete.
- The suggested git log/diff inspection was not performed because the explicit instruction forbids all git commands. Review used the current files, local factory sources and executable tests. The owner commits.
- Withdrawing consent or disabling the receiver prevents future queued sends and purges pending data. It cannot retract bytes already in an HTTP request that started before the withdrawal; no new request is started for purged data.
