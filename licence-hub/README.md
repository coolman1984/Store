# Al-Store (الستور) — licence hub (**dev-only** local template)

> **Production:** online trial, monthly, and permanent licences for الستور use the **shared multi-product licence hub** in [`coolman1984/Yousef-Transportation`](https://github.com/coolman1984/Yousef-Transportation) (`feat/owner-panel-paid`, product id `al-store`). Customer builds point at that hub with `STORE_RELEASE_RELAY_URL` and `tools/relay_hosts_allowed.txt` — never a hard-coded production URL in git.

This folder is a **local Cloudflare Worker template** for developers to exercise the same `/licence/*` protocol offline. **Nothing here deploys from CI by default** — configure `wrangler.toml` and set secrets on Cloudflare only if you need a private sandbox.

The worker is **not** the factory telemetry relay (`/ingest`). For shop apps, put the hub `https://` address in `licence_relay.txt` (or `STORE_LICENCE_RELAY` / `STORE_RELEASE_RELAY_URL` at build time).

## What it does / ماذا يفعل

- Same shop protocol as `server/trial.py`: `POST /licence/request`, `GET /licence/status`, `POST /licence/ack`, `GET /licence/time` or `/licence/clock` (signed calendar when signing keys are set).
- Route prefixes `/licence/*`, `/api/licence/*`, and `/licence-hub/licence/*` are equivalent (matches the shared hub).
- Owner dashboard at `/owner` (Arabic, RTL) for local testing only.
- Signs trials (`LICENCE_SIGNING_KEY`, kid `trial-hub`) and paid/permanent (`PAID_SIGNING_KEY` or `LICENCE_PAID_SIGNING_KEY`, kid `paid`) — byte-compatible with `server/afcodes.py`.
- `LICENCE_PRODUCTS` must include `al-store` for Store requests (`product` field in `server/trial.py`).

**Licence Studio** on the owner PC is optional (`studio:` public key for manual paste only). Trial, monthly, and permanent for customers come from the **shared hub owner panel**, not Studio.

## Signing key tradeoff / مخاطر مفتاح التوقيع

| Convenience | Risk |
|---|---|
| Signing keys in Worker secrets → approve from anywhere | Compromised Cloudflare account could issue codes |
| Mitigations: kid `trial-hub` (≤14-day device trials only), kid `paid` for hub-paid codes, remove revoked public keys in the next installer, strong Cloudflare 2FA |

Never put a Licence Studio **paid** private key in `LICENCE_SIGNING_KEY`.

## Setup (documented only) / الإعداد (توثيق فقط)

See the shared hub README in Yousef-Transportation `licence-hub/README.md` for production deployment. For this dev copy:

```bash
cd licence-hub
npx wrangler d1 create al-store-licence-dev
# database_id in wrangler.toml, schema.sql, secrets (trial + paid keys, SESSION_SECRET, OWNER_PASSWORD_HASH)
npx wrangler deploy
```

Customer builds: `trial-hub:<public>` and `paid:<public>` via `python tools/build_windows.py --customer` (`STORE_RELEASE_RELAY_URL` + allowlist).

## Tests / الاختبارات

```bash
node --check licence-hub/src/worker.js
cd licence-hub && npm test
python -m unittest tests.test_licence_hub_signer tests.test_hub_time
```

See also `docs/HUB_SETUP.md`.
