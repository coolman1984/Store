"""Sign hub calendar JSON like the shared licence hub (tests only)."""
import base64
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'server'))

import hub_time  # noqa: E402


def _pub_b64url(raw32: bytes) -> str:
    return base64.urlsafe_b64encode(raw32).decode().rstrip('=')


def sign_calendar_payload(private_pem: str, kid: str, day: str):
    """Return (payload dict, public key b64url) matching GET /licence/clock from the shared hub."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError('ed25519 only')
    msg = hub_time.hub_time_message(day, kid)
    sig = key.sign(msg)
    pub = key.public_key().public_bytes_raw()
    return {
        'calendar_day': day,
        'kid': kid,
        'sig': _pub_b64url(sig),
        'serverTime': day,
    }, _pub_b64url(pub)
