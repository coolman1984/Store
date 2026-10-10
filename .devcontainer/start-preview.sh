#!/usr/bin/env bash
# This script runs ONLY when the owner creates/starts a GitHub Codespace.
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -z "${CODESPACE_NAME:-}" ]]; then
  echo "Not running inside GitHub Codespaces. No preview was started."
  exit 0
fi
if [[ ! "$CODESPACE_NAME" =~ ^[a-zA-Z0-9-]+$ ]]; then
  echo "Invalid Codespaces name. Refusing preview." >&2
  exit 1
fi

preview_home="${TMPDIR:-/tmp}/al-store-codespace-${CODESPACE_NAME}"
log="${TMPDIR:-/tmp}/al-store-preview-${CODESPACE_NAME}.log"
mkdir -p "$preview_home"

if python3 - <<'PY'
import json, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8097/api/boot', timeout=2) as response:
        obj = json.load(response)
    ok = obj.get('practice') is True
except Exception:
    ok = False
raise SystemExit(0 if ok else 1)
PY
then
  echo "Store practice is already running on port 8097."
  exit 0
fi

# Refuse to launch if some other process owns our preview port.
if python3 - <<'PY'
import socket
try:
    with socket.create_connection(('127.0.0.1', 8097), timeout=1):
        raise SystemExit(0)
except OSError:
    raise SystemExit(1)
PY
then
  echo "Port 8097 is already occupied by a non-practice service." >&2
  exit 1
fi

# Synthetic data and logs live ONLY in this Codespace, outside the repository.
# Never set a production home, sign licensing codes, or expose a public port.
nohup env ALSTORE_CODESPACES_PREVIEW=1 CODESPACE_NAME="$CODESPACE_NAME" \
  python3 server/app.py --practice --home "$preview_home" \
  --host 127.0.0.1 --port 8097 --no-browser > "$log" 2>&1 < /dev/null &
echo "$!" > "${TMPDIR:-/tmp}/al-store-preview-${CODESPACE_NAME}.pid"

for _ in $(seq 1 30); do
  if python3 - <<'PY'
import json, urllib.request
try:
    with urllib.request.urlopen('http://127.0.0.1:8097/api/boot', timeout=1) as response:
        data=json.load(response)
    raise SystemExit(0 if data.get('practice') is True else 1)
except Exception:
    raise SystemExit(1)
PY
  then
    echo "READY: Real Al-Store practice, port 8097, PRIVATE GitHub-authenticated URL."
    echo "Open the Ports panel and use the forwarded HTTPS link."
    exit 0
  fi
  sleep 1
done

echo "Preview failed to start. See $log" >&2
tail -40 "$log" >&2 || true
exit 1
