"""Verify signed calendar-day payloads from the shared licence hub."""
from __future__ import annotations

import base64

from ed25519 import verify as _ed_verify

HUB_TIME_KIDS = frozenset({'trial-hub', 'trial_hub', 'hub-trial', 'paid'})


def _b64url_decode(text: str) -> bytes:
    pad = '=' * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hub_time_message(calendar_day: str, kid: str) -> bytes:
    return f'AF-LICENCE-HUB-TIME/1|{calendar_day}|{kid}'.encode('utf-8')


def verify_hub_calendar(data, trusted_by_kid: dict[str, str]) -> str | None:
    """Return YYYY-MM-DD when signature is valid; otherwise None."""
    if not isinstance(data, dict):
        return None
    day = data.get('calendar_day')
    kid = str(data.get('kid') or '').strip().lower()
    sig = data.get('sig')
    if not isinstance(day, str) or len(day) != 10 or kid not in HUB_TIME_KIDS or not isinstance(sig, str) or not sig:
        return None
    public_b64 = trusted_by_kid.get(kid)
    if not public_b64:
        return None
    try:
        public = _b64url_decode(public_b64)
        signature = _b64url_decode(sig)
    except (ValueError, base64.binascii.Error):
        return None
    if not _ed_verify(public, hub_time_message(day, kid), signature):
        return None
    if day[4] != '-' or day[7] != '-':
        return None
    return day
