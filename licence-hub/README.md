# Al-Store (الستور) — licence hub (Cloudflare Worker template)

قالب Worker لاستقبال طلبات التفعيل عبر الإنترنت ولوحة موافقة للمالك. **لا يُنشر من هذا المستودع تلقائيًا** — املأ `wrangler.toml` وضَع الأسرار على Cloudflare فقط.

Template Cloudflare Worker for online licence requests and an owner approval dashboard. **Nothing here deploys from CI by default** — configure `wrangler.toml` and set secrets in Cloudflare only.

This worker is **not** the factory telemetry relay (`/ingest`). Deploy it on its own URL; put that `https://` address in `licence_relay.txt` (or `STORE_LICENCE_RELAY`) for customer builds so the shop can ask for a trial online.

## What it does / ماذا يفعل

- نفس بروتوكول البرنامج: `POST /licence/request`, `GET /licence/status`, `POST /licence/ack` (حقول `server/trial.py`, اختبار `tests/test_trial.py` و`tests/fake_relay.py`).
- Same protocol as the shop app (`server/trial.py`, exercised by `tests/test_trial.py` and `tests/fake_relay.py`).
- لوحة المالك على `/owner` (عربي، RTL): موافقة على الطلبات (يُعرض الكود بعد الموافقة)، تفعيل يدوي برقم الجهاز، قائمة العملاء.
- Owner dashboard at `/owner` (Arabic, RTL): pending requests (issued code shown on approve), offline device entry, customer list.
- توقيع تجربة 14 يومًا بـ `LICENCE_SIGNING_KEY` واشتراك شهري/دائم من لوحة المالك بـ `LICENCE_PAID_SIGNING_KEY` — متوافق مع `server/afcodes.py`.
- Signs trials with `LICENCE_SIGNING_KEY` and **monthly/permanent** from the owner panel with `LICENCE_PAID_SIGNING_KEY` (`al-store`) — byte-compatible with `server/afcodes.py`. Customer builds trust `trial-hub:` and `paid:` public keys (kid `paid` for hub-paid codes; optional `studio:` for Licence Studio paste codes).
- One trial per PC online: locks both the normalized device code and the stable `machine` hash the app sends. Pending requests expire after a short TTL so a squatted poll token cannot block the real customer forever.

**بديل التوقيع:** Licence Studio على جهاز المالك يبقى الطريقة الأكثر أمانًا للتوقيع؛ هذا القالب يوازن بين الراحة (موافقة من الهاتف) ومخاطر سر التوقيع على Cloudflare (انظر أدناه).

**Alternative signer:** Licence Studio on the owner PC remains the strongest option; this template trades convenience for signing-key exposure on Cloudflare (see tradeoff).

## Signing key tradeoff / مخاطر مفتاح التوقيع

| Convenience | Risk |
|---|---|
| `LICENCE_SIGNING_KEY` في Worker secret → موافقة من أي مكان | إذا اُخترق حساب Cloudflare يمكن إصدار أكواد |
| Mitigations: **kid منفصل** (`trial-hub`) — البرنامج يقبل من هذا المفتاح تجربة ≤14 يوم فقط؛ إزالة المفتاح العام من `licence_keys` في الإصدار التالي؛ كلمة مرور قوية + 2FA على Cloudflare؛ أو الإبقاء على التوقيع في Licence Studio فقط |

Never put the Licence Studio **paid** private key in `LICENCE_SIGNING_KEY`. Generate a dedicated trial key pair; customers trust only `trial-hub:<public>` for hub-signed trials.

## Setup (documented only) / الإعداد (توثيق فقط)

```bash
cd licence-hub
npx wrangler d1 create al-store-licence
# Put database_id in wrangler.toml
npx wrangler d1 execute al-store-licence --file=schema.sql

# Trial-only Ed25519 key (example — run locally, do not commit trial-hub.pem):
openssl genpkey -algorithm ED25519 -out trial-hub.pem

# Hash the owner password (example — run locally, do not commit output):
# python3 -c "import hashlib,secrets; s=secrets.token_hex(16); print('pbkdf2-sha256:100000:'+s+':'+hashlib.pbkdf2_hmac('sha256', b'YOUR_PASSWORD', bytes.fromhex(s), 100000).hex())"

npx wrangler secret put LICENCE_SIGNING_KEY       # PKCS#8 PEM of trial-hub.pem ONLY
npx wrangler secret put LICENCE_PAID_SIGNING_KEY  # PKCS#8 PEM of paid-hub.pem ONLY (owner panel monthly/permanent)
npx wrangler secret put SESSION_SECRET
npx wrangler secret put OWNER_PASSWORD_HASH
# Optional:
npx wrangler secret put TELEGRAM_BOT_TOKEN
npx wrangler secret put TELEGRAM_CHAT_ID

npx wrangler deploy
```

ضع في `licence_keys.txt` سطر `trial-hub:<public>` و`paid:<public>` (واختياريًا `studio:<public>` لأكواد Licence Studio اليدوية).

Put `trial-hub:<public>` and `paid:<public>` in `licence_keys.txt` for customer builds (optional `studio:<public>` for manual Studio codes). Revoke a Worker key by removing its public line in the next release.

See also `docs/HUB_SETUP.md` for how this worker differs from the telemetry relay.

## Tests / الاختبارات

```bash
node --check licence-hub/src/worker.js
cd licence-hub && npm test
cd tests && python3 -m unittest test_licence_hub_signer.py
```

No runtime npm dependencies — only Node built-ins and `node --test`.
