# Vendored from Apps-Factory packages/af-license 0.3.0 af_license/ed25519_verify.py - do not edit here.
# Update with: python scripts/vendor_licence.py <product repo> (from the Apps-Factory checkout)
"""Ed25519 signature *verification* (RFC 8032 §5.1.7) in pure standard-library Python.

For products that ship without third-party packages (the factory's stdlib-only local servers). It holds no secret and
never signs: signing stays with the vetted `cryptography` library on the vendor machine (constitution: no hand-written
crypto for secrets). Verification uses only public data, so timing is not a concern. Algorithms follow the RFC 8032
reference code; the cross-check test (tests/test_codes.py) signs with `cryptography` and verifies here, both ways round.

Vendored copies: products copy this file unchanged (`scripts/vendor_licence.py`), a header names the source version.
"""
import hashlib

_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)
_ZERO = (0, 1, 1, 0)


def _inv(x):
    return pow(x, _P - 2, _P)


def _add(a, b):
    A = (a[1] - a[0]) * (b[1] - b[0]) % _P
    B = (a[1] + a[0]) * (b[1] + b[0]) % _P
    C = 2 * a[3] * b[3] * _D % _P
    D = 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _double(a):
    A = a[0] * a[0] % _P
    B = a[1] * a[1] % _P
    C = 2 * a[2] * a[2] % _P
    H = A + B
    E = H - (a[0] + a[1]) * (a[0] + a[1]) % _P
    G = A - B
    F = C + G
    return (E * F % _P, G * H % _P, F * G % _P, E * H % _P)


def _mul(k, point):
    table = [_ZERO, point]
    for _ in range(14):
        table.append(_add(table[-1], point))
    result = _ZERO
    for i in range(63, -1, -1):
        result = _double(_double(_double(_double(result))))
        result = _add(result, table[(k >> (4 * i)) & 15])
    return result


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_BASE = (_GX, _GY, 1, _GX * _GY % _P)


def _decode(data):
    if len(data) != 32:
        return None
    y = int.from_bytes(data, 'little')
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % _P)


def _equal(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def verify(public, message, signature):
    """True only when `signature` (64 bytes) over `message` was made with the private key of `public` (32 bytes)."""
    try:
        if len(public) != 32 or len(signature) != 64:
            return False
        A, R = _decode(public), _decode(signature[:32])
        if A is None or R is None:
            return False
        s = int.from_bytes(signature[32:], 'little')
        if s >= _Q:
            return False
        k = int.from_bytes(hashlib.sha512(signature[:32] + public + message).digest(), 'little') % _Q
        return _equal(_mul(s, _BASE), _add(R, _mul(k, A)))
    except (TypeError, ValueError):
        return False
