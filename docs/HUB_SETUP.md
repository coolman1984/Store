# Licence hub: online trial activation (الستور / Al-Store)

Al-Store can use **two different Cloudflare Workers** (different URLs). They are not interchangeable.

| Worker | Role | Typical URL config |
|---|---|---|
| **Telemetry relay** (`Apps-Factory/templates/telemetry-relay`) | Problem reports (`/ingest`), usage counts, crash fingerprints | Settings → Support / `hub_url` in `config.json` when the shop opted in |
| **Licence hub** (`licence-hub/` in this repository) | Online trial requests (`/licence/request`, `/licence/status`, `/licence/ack`) and the owner approval UI | `licence_relay.txt` next to `licence_keys.txt`, or `STORE_LICENCE_RELAY`, or `licence_relay` in `config.json` |

Nothing is sent until the shop has a relay address configured. The licence hub needs **no secret in the program**.

## What goes to the licence hub

| What | When | Needs |
|---|---|---|
| Licence request (`/licence/request`, `/licence/status`, `/licence/ack`) | the owner pressed «اطلب تجربة» (or monthly/permanent under Details) | **licence hub** `https://` address only |

Never sent: passwords, phone numbers, sales, customers, stock, amounts. A licence request may include the **shop name** from settings (`shop`, up to 60 characters) and the fields listed in `server/trial.py` (`SENT_FIELDS`). That name is not part of the signed activation code.

## Configure (nothing secret is committed to the repository)

- **Licence hub address:** `licence_relay.txt` (one `https://` line, no query string or token), or `STORE_LICENCE_RELAY`, or `"licence_relay"` in `config.json`.
- **Licence public keys:** one or more `kid:key` lines in `licence_keys.txt` (or `STORE_LICENCE_KEYS`). With no key the program answers `no_keys` and does not enforce codes.
- **Telegram (manual path only):** the company's public `@name` or `t.me` link in `config.json` as `vendor_telegram` on the installed PC — **not** in this public repository. Example placeholder used in tests: `@alstore_support`.

### Trial-only hub signing key (separate from Licence Studio)

The licence hub must **not** use the same private key as Licence Studio. Generate a dedicated Ed25519 pair for trials only:

```bash
# Example — run on the owner's PC; never commit the PEM or paste it in chat
openssl genpkey -algorithm ED25519 -out trial-hub.pem
openssl pkey -in trial-hub.pem -pubout -outform DER | tail -c 32 | base64 -w0
```

1. Deploy **licence hub** with `npx wrangler secret put LICENCE_SIGNING_KEY` ← PKCS#8 PEM of **trial-hub.pem** only (trials).
2. Generate a **second** Ed25519 pair for paid hub signing (`paid-hub.pem`). Set `npx wrangler secret put LICENCE_PAID_SIGNING_KEY` ← PKCS#8 PEM of **paid-hub.pem** only. The owner panel signs monthly (`standard` edition, 30 days + grace) and permanent codes with this key — same byte format as `server/afcodes.py`.
3. In customer `licence_keys.txt`, ship at least `trial-hub:<public>` and `paid:<public>` (optional `studio:<public>` for Licence Studio paste codes). Example:  
   `trial-hub:AbCdEfGh...` and `paid:XyZ...` (43-character unpadded base64url raw public keys).
4. Keep the Licence Studio **private** key off Cloudflare unless you also use Studio for manual paste; hub-paid codes use kid `paid`, not `studio`.

The shop checks every code on the PC with the public keys in `licence_keys.txt`, so a broken or hostile relay cannot invent a paid licence.

While the shop polls the relay (or calls public `GET /licence/clock` once per program run), the hub's `calendar_day` / `serverTime` is stored in the shop database (`licence_trusted_date` in `meta`). A local date before that is treated like a clock rollback; a hub date past the signed last day (plus grace) locks paid actions even if the PC clock lies. If the network is down, nothing new is written and the shop keeps working on the signed code and the local clock only (never-online edge case).

## Register the product (owner, once)

1. **Licence hub** (`licence-hub/`): deploy the Worker with `LICENCE_PRODUCTS` including `al-store` (`wrangler.toml` vars). Set `LICENCE_SIGNING_KEY` (trial-only) and `LICENCE_PAID_SIGNING_KEY` (monthly/permanent from the owner panel). Owner login secrets (`SESSION_SECRET`, `OWNER_PASSWORD_HASH`) and optional `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID`.
2. **Licence Studio** on the owner's trusted PC (optional): register product id `al-store` for manual paste codes (`studio:` public key).
3. Put `trial-hub:<public>`, `paid:<public>`, and any `studio:<public>` lines in `licence_keys.txt` of the customer build (task 2 — not committed here until the owner chooses).

## Simple activation (same as Trip Orders hub model)

Two paths use the **same** signed codes and rules.

| Path | What the shop owner does |
|---|---|
| **Online (relay configured)** | Licence screen → confirm what will be sent → press **Ask for a trial**. The program posts to `/licence/request`, shows waiting, polls `/licence/status`, activates with the signed code, then `/licence/ack`. |
| **Manual (no relay or refused)** | Copy the **device code**, contact the company (Telegram from `vendor_telegram`, WhatsApp, …), paste the **activation code** from Licence Studio, press activate. |

**Owner one-time setup** (not from CI; do not deploy from a customer PC):

1. Deploy `licence-hub/` and set secrets (see `licence-hub/README.md`).
2. Licence Studio on the owner's PC for paid editions and manual codes.
3. Customer installer gets `trial-hub:<public>`, `paid:<public>`, and the relay URL in `licence_relay.txt` (task 2).

Commercial tiers (trial, monthly, permanent) match the factory SMB model documented in `docs/04-commercial-tiers.md` for the one-PC pilot; cloud sync and mobile plans are not part of the trial hub.

## Proof still needed (not provable from the repository)

A deployed Worker, a real trial from a clean Windows PC, and Studio signatures on real device codes. Automated checks: `cd licence-hub && npm test`, `python -m unittest tests.test_licence_hub_signer tests.test_licence_hub_activation`, and `tests/test_trial.py` against `tests/fake_relay.py`.
