# Vendored from Apps-Factory packages/af-license 0.3.0 af_license/codes.py - do not edit here.
# Update with: python scripts/vendor_licence.py <product repo> (from the Apps-Factory checkout)
"""Licence *codes*: a signed licence short enough to send on WhatsApp and paste into the program.

Why codes as well as JSON documents (core.py): a shop owner cannot copy a file to the shop PC, but can paste text.
A code is 26 bytes of terms + a 64-byte Ed25519 signature, written in Crockford base32 (no I, L, O, U; case-insensitive)
in groups of six: 144 characters. The signature covers every term, so changing one letter makes the code invalid.

Terms inside a code (format version 1):
  product tag (4 bytes of SHA-256 of the product id) · edition (trial / standard / pro / perpetual) · issued day · first day ·
  last day (inclusive) · grace days · device tag (6 bytes of the customer's device code, or zeros = any device) ·
  serial (random, the licence id) · seats · key tag (2 bytes of the signing key id)

The device code is shown by the program on the customer's PC (10 characters). Binding a code to it means the code does
not work on another PC, so a trial code cannot be passed around. Dates are whole days in the customer's local calendar.
A `perpetual` code never expires: its last day is stored as the largest day (65535) and a reader reports no last day.
It is always bound to one device: issuing one without a device fails, and a reader refuses an unbound one.
Older readers do not know edition 4 and refuse it (`unknown_edition`), so they never grant it by mistake.

Signing (vendor machine only) uses the vetted `cryptography` library, imported lazily so that products can vendor this
file and *verify* with the standard library only (`ed25519_verify.py`). The private key never ships.
"""
from __future__ import annotations

import base64
import hashlib
import os
import struct
from dataclasses import dataclass, field
from datetime import date, timedelta

try:  # inside the af_license package
    from .ed25519_verify import verify as _ed_verify
except ImportError:  # a vendored copy next to ed25519.py in a stdlib-only product
    from ed25519 import verify as _ed_verify  # type: ignore

VERSION = 1
EPOCH = date(2024, 1, 1)
ALPHABET = '0123456789ABCDEFGHJKMNPQRSTVWXYZ'  # Crockford base32
EDITIONS = {1: 'trial', 2: 'standard', 3: 'pro', 4: 'perpetual'}
FOREVER = 65535  # the last day of a perpetual code (2203-06-07): never reached
EDITION_IDS = {v: k for k, v in EDITIONS.items()}
DOMAIN = b'AF-LICENCE-CODE/1'  # domain separation: a code signature can never be reused as another document's
_LAYOUT = '>B4sBHHHB6s4sB2s'  # 26 bytes
PAYLOAD_LEN = struct.calcsize(_LAYOUT)
CODE_LEN = PAYLOAD_LEN + 64


# ------------------------------------------------------------------ text form
def _b32(data: bytes) -> str:
    bits = int.from_bytes(data, 'big')
    n = (len(data) * 8 + 4) // 5
    bits <<= n * 5 - len(data) * 8
    return ''.join(ALPHABET[(bits >> (5 * (n - 1 - i))) & 31] for i in range(n))


def _unb32(text: str, length: int) -> bytes:
    n = len(text)
    bits = 0
    for ch in text:
        bits = (bits << 5) | ALPHABET.index(ch)
    bits >>= n * 5 - length * 8
    return bits.to_bytes(length, 'big')


def normalize(text: str) -> str:
    """Upper case, no spaces or dashes, the usual reading mistakes fixed (O→0, I/L→1)."""
    if not isinstance(text, str):
        raise ValueError('bad_character')
    out = []
    for ch in text.upper():
        if ch in ' -_\t\r\n.':
            continue
        ch = {'O': '0', 'I': '1', 'L': '1'}.get(ch, ch)
        if ch not in ALPHABET:
            raise ValueError('bad_character')
        out.append(ch)
    return ''.join(out)


def group(text: str, size: int = 6) -> str:
    return '-'.join(text[i:i + size] for i in range(0, len(text), size))


# ------------------------------------------------------------------ device code
def device_code(*stable_parts: str) -> str:
    """10 characters the program shows on the customer's PC, e.g. 7KD2M-QX9TP. Same PC → same code; never personal data."""
    cleaned = [p.strip().lower() for p in stable_parts if p and p.strip()]
    if not cleaned:
        raise ValueError('device_code needs at least one stable value')
    digest = hashlib.sha256(b'AF-DEVICE/1|' + '|'.join(cleaned).encode('utf-8')).digest()
    return group(_b32(digest[:7])[:10], 5)


def _device_tag(code: str | None) -> bytes:
    if not code:
        return b'\0' * 6
    norm = normalize(code)
    if len(norm) != 10:
        raise ValueError('bad_device_code')
    return hashlib.sha256(b'AF-DEVICE-TAG/1|' + norm.encode('ascii')).digest()[:6]


def product_tag(product_id: str) -> bytes:
    return hashlib.sha256(b'AF-PRODUCT/1|' + product_id.encode('utf-8')).digest()[:4]


def key_tag(public_b64: str) -> bytes:
    raw = base64.urlsafe_b64decode(public_b64 + '=' * (-len(public_b64) % 4))
    return hashlib.sha256(raw).digest()[:2]


def _day(n: int) -> date:
    return EPOCH + timedelta(days=n)


def _num(d: date) -> int:
    n = (d - EPOCH).days
    if not 0 <= n <= 65535:
        raise ValueError('date_out_of_range')
    return n


# ------------------------------------------------------------------ vendor side
def issue_code(private_pem: bytes, product_id: str, edition: str, first_day: date, days: int, device: str | None = None,
               grace_days: int = 0, seats: int = 1, issued: date | None = None, serial: bytes | None = None) -> dict:
    """Sign a code. Returns {'code': grouped text, 'serial': hex, 'first_day', 'last_day', ...}. Vendor machine only.
    For a perpetual code `days` and `grace_days` are ignored and `last_day` is None."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if edition not in EDITION_IDS:
        raise ValueError('unknown_edition')
    perpetual = edition == 'perpetual'
    if perpetual:
        if not device:
            raise ValueError('device_required')  # a code that never ends must never travel to another PC
        days, grace_days = 1, 0
    if not 1 <= int(days) <= 3660:
        raise ValueError('days_out_of_range')
    if not 0 <= int(grace_days) <= 60 or not 1 <= int(seats) <= 255:
        raise ValueError('grace_or_seats_out_of_range')
    private = serialization.load_pem_private_key(private_pem, password=None)
    if not isinstance(private, Ed25519PrivateKey):
        raise ValueError('signing key must be Ed25519')
    public_raw = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    last_day = _day(FOREVER) if perpetual else first_day + timedelta(days=int(days) - 1)
    serial = serial or os.urandom(4)
    payload = struct.pack(_LAYOUT, VERSION, product_tag(product_id), EDITION_IDS[edition], _num(issued or date.today()),
                          _num(first_day), _num(last_day), int(grace_days), _device_tag(device), serial, int(seats),
                          hashlib.sha256(public_raw).digest()[:2])
    signature = private.sign(DOMAIN + payload)
    return {'code': group(_b32(payload + signature)), 'serial': serial.hex().upper(), 'edition': edition,
            'first_day': first_day.isoformat(), 'last_day': None if perpetual else last_day.isoformat(), 'grace_days': int(grace_days),
            'device': device and group(normalize(device), 5), 'seats': int(seats), 'product': product_id}


# ------------------------------------------------------------------ product side
@dataclass
class CodeResult:
    valid: bool
    state: str  # active | grace | expired | not_yet_valid | invalid
    reason: str = ''
    terms: dict = field(default_factory=dict)

    @property
    def full_access(self) -> bool:
        return self.valid and self.state in ('active', 'grace')


def read_code(text: str, trusted_public_keys: list[str], product_id: str, device: str | None = None,
              today: date | None = None) -> CodeResult:
    """Check a pasted code. Never raises on bad input. `trusted_public_keys`: base64url raw Ed25519 public keys."""
    bad = lambda reason: CodeResult(False, 'invalid', reason)  # noqa: E731
    try:
        norm = normalize(text)
    except ValueError:
        return bad('bad_character')
    expected_chars = (CODE_LEN * 8 + 4) // 5
    if len(norm) != expected_chars:
        return bad('wrong_length')
    try:
        raw = _unb32(norm, CODE_LEN)
    except ValueError:
        return bad('bad_character')
    payload, signature = raw[:PAYLOAD_LEN], raw[PAYLOAD_LEN:]
    (version, ptag, edition, issued, first, last, grace, dtag, serial, seats, ktag) = struct.unpack(_LAYOUT, payload)
    if version != VERSION:
        return bad('unknown_version')
    keys = {key_tag(k): k for k in trusted_public_keys}
    if ktag not in keys:
        return bad('unknown_key')
    public = base64.urlsafe_b64decode(keys[ktag] + '=' * (-len(keys[ktag]) % 4))
    if not _ed_verify(public, DOMAIN + payload, signature):
        return bad('bad_signature')
    if ptag != product_tag(product_id):
        return bad('wrong_product')
    if edition not in EDITIONS:
        return bad('unknown_edition')
    terms = {'edition': EDITIONS[edition], 'issued': _day(issued).isoformat(), 'first_day': _day(first).isoformat(),
             'last_day': _day(last).isoformat(), 'grace_days': grace, 'seats': seats, 'serial': serial.hex().upper(),
             'device_bound': dtag != b'\0' * 6}
    if terms['device_bound']:
        try:
            if not device or _device_tag(device) != dtag:
                return CodeResult(False, 'invalid', 'other_device', terms)
        except ValueError:
            return CodeResult(False, 'invalid', 'other_device', terms)
    today = today or date.today()
    if terms['edition'] == 'perpetual':
        terms['last_day'] = terms['days_left'] = None
        if not terms['device_bound']:  # never issued by this module; refused if another tool ever signs one
            return CodeResult(False, 'invalid', 'unbound_perpetual', terms)
        if today < _day(first):
            return CodeResult(True, 'not_yet_valid', 'starts_later', terms)
        return CodeResult(True, 'active', '', terms)
    last_day = _day(last)
    terms['days_left'] = (last_day - today).days + 1
    if today < _day(first):
        return CodeResult(True, 'not_yet_valid', 'starts_later', terms)
    if today <= last_day:
        return CodeResult(True, 'active', '', terms)
    if today <= last_day + timedelta(days=grace):
        return CodeResult(True, 'grace', 'renew_soon', terms)
    return CodeResult(True, 'expired', 'renew_to_unlock_paid_actions', terms)
