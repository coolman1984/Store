# Licence hub: online activation (الستور / Al-Store)

Al-Store can use **two different Cloudflare Workers** (different URLs). They are not interchangeable.

| Worker | Role | Typical URL config |
|---|---|---|
| **Telemetry relay** (`Apps-Factory/templates/telemetry-relay`) | Problem reports (`/ingest`), usage counts, crash fingerprints | Settings → Support / `hub_url` in `config.json` when the shop opted in |
| **Shared licence hub** ([`Yousef-Transportation`](https://github.com/coolman1984/Yousef-Transportation) `licence-hub/`, branch `feat/owner-panel-paid`) | Online trial, monthly, and permanent requests + owner panel (`product`: `al-store`) | `licence_relay.txt`, `STORE_LICENCE_RELAY`, or `STORE_RELEASE_RELAY_URL` at build time + `tools/relay_hosts_allowed.txt` |

The copy under `licence-hub/` in **this** repository is **dev-only** (local protocol tests). Production shops use the shared multi-product hub, not a URL committed in git.

Nothing is sent until the shop has a relay address configured. The licence hub needs **no secret in the program**.

## What goes to the licence hub

| What | When | Needs |
|---|---|---|
| Licence request (`/licence/request`, `/licence/status`, `/licence/ack`) | Owner pressed «اطلب تجربة» or monthly/permanent | Hub `https://` base URL (optional path prefix `/api` or `/licence-hub`) |
| Hub calendar (`GET /licence/time` or `/licence/clock`, once per program run) | Background sync while online | Same URL; response must be **signed** (`calendar_day`, `kid`, `sig`) with a trusted `trial-hub` or `paid` public key |

Never sent: passwords, phone numbers, sales, customers, stock, amounts. Requests include `product` (`al-store`), `kind`, `device`, `machine`, `shop` (≤60 chars), and fields in `server/trial.py` (`SENT_FIELDS`).

## Configure (nothing secret is committed to the repository)

- **Hub address:** `licence_relay.txt` (one `https://` line), `STORE_LICENCE_RELAY`, `licence_relay` in `config.json`, or **`STORE_RELEASE_RELAY_URL`** when building `python tools/build_windows.py --customer`. Hostname must be on `tools/relay_hosts_allowed.txt` or `STORE_RELEASE_ALLOWED_RELAY_HOSTS`. Allowed path suffixes: `` (none), `/api`, `/licence-hub`.
- **Public keys in the installer:** `trial-hub:<public>` (14-day device trials only), `paid:<public>` (hub owner panel monthly/permanent), optional `studio:<public>` for manual Licence Studio paste.
- **Telegram (manual contact only):** `vendor_telegram` in the shop's `config.json` on the installed PC.

### Shared hub secrets (owner deploys on Cloudflare — not in git)

1. `LICENCE_SIGNING_KEY` — PKCS#8 PEM, trial-only, kid `trial-hub`.
2. `PAID_SIGNING_KEY` (or `LICENCE_PAID_SIGNING_KEY` on the dev template) — PKCS#8 PEM, kid `paid`, for monthly/permanent from the owner panel.
3. `LICENCE_PRODUCTS` includes `al-store` (and other products as needed).
4. Optional per-product overrides: `LICENCE_SIGNING_KEY_AL_STORE`, `PAID_SIGNING_KEY_AL_STORE` (activation codes only; hub calendar uses global trial/paid keys).

The shop verifies every activation code and hub calendar signature on the PC. A hostile relay cannot forge paid dates (paid end date comes only from the signed code) or unsigned calendar days.

While online, signed hub time is stored in `meta.licence_trusted_date`. Local date before that is clock rollback; hub date past signed `last_day` (+ grace) locks writes even if the PC clock lies. Offline or failed checks never lock; read/export/backup always work.

## Activation paths

| Path | What the shop owner does |
|---|---|
| **Online** | Licence screen → ask for trial / monthly / permanent → poll until the owner approves in the **shared hub owner panel** → code activates automatically. |
| **Manual** | Send device code to the company → paste code from the owner panel (or optional `studio:` Licence Studio code). |

## API assumptions (shared hub round 6)

| Route | Notes |
|---|---|
| `POST /licence/request` | Body includes `product: "al-store"`. Kinds: `trial`, `monthly`, `permanent`. |
| `GET /licence/status?id=` | Bearer poll token; may include signed calendar fields. |
| `POST /licence/ack` | After successful `licence.activate` on the PC. |
| `GET /licence/time` or `/licence/clock` | Signed business calendar; Store client uses `/licence/clock`. |

Prefixes `/api/licence/*` and `/licence-hub/licence/*` are equivalent to `/licence/*`.

## Proof still needed (field)

Deployed shared hub, clean Windows PC trial, and hub-paid codes on real device ids. Automated checks: `cd licence-hub && npm test`, `python -m unittest tests.test_licence_hub_signer tests.test_hub_time tests.test_trial`, and `tests/test_licence_online.py`.
