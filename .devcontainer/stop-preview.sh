#!/usr/bin/env bash
set -euo pipefail
if [[ -z "${CODESPACE_NAME:-}" || ! "$CODESPACE_NAME" =~ ^[a-zA-Z0-9-]+$ ]]; then
  echo "Use this only inside the Codespace." >&2
  exit 1
fi
pid_file="${TMPDIR:-/tmp}/al-store-preview-${CODESPACE_NAME}.pid"
home="${TMPDIR:-/tmp}/al-store-codespace-${CODESPACE_NAME}"
if [[ -f "$pid_file" ]]; then
  pid="$(cat "$pid_file")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && ps -p "$pid" -o args= 2>/dev/null | grep -Fq "server/app.py --practice --home $home"; then
    kill "$pid" || true
    sleep 1
  fi
  rm -f "$pid_file"
fi
# Only the known synthetic trial directory is removable by this script.
rm -rf -- "$home"
echo "Practice server stopped when owned; disposable demo database cleared."
