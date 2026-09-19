"""Ed25519 signatures in pure Python (RFC 8032, section 5.1).

The app ships with Pillow and nothing else, and every dependency has to be
pinned into the installers, so the one thing that needs a signature check (a
preview code, :mod:`.preview`) gets this rather than a crypto package.

It follows the RFC's own reference algorithm (section 6) line for line, in
extended twisted Edwards coordinates, and is tested against the RFC's section
7.1 vectors (``tests/test_ed25519.py``).  It is NOT constant time: fine for
checking a public signature in the app, and for signing on David's own PC with
``tools/preview_code.py``, which is the only place a private key is ever used.

The API is bytes in, bytes out:

* :func:`public_key` - the 32-byte public key of a 32-byte secret key
* :func:`sign` - the 64-byte signature of a message
* :func:`verify` - True or False, never raises on a malformed key or signature
"""
from __future__ import annotations

import hashlib

__all__ = ["public_key", "sign", "verify", "SECRET_SIZE", "PUBLIC_SIZE",
           "SIGNATURE_SIZE"]

SECRET_SIZE = 32
PUBLIC_SIZE = 32
SIGNATURE_SIZE = 64

#: the field prime 2^255 - 19
_P = 2 ** 255 - 19
#: the order of the base point
_Q = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x):
    return pow(x, _P - 2, _P)


#: the curve constant d = -121665/121666
_D = -121665 * _inv(121666) % _P
#: a square root of -1
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _sha512(data):
    return hashlib.sha512(data).digest()


def _sha512_modq(data):
    return int.from_bytes(_sha512(data), "little") % _Q


# ---- points: (X, Y, Z, T) with x = X/Z, y = Y/Z, x*y = T/Z ------------------------------
def _add(p1, p2):
    a = (p1[1] - p1[0]) * (p2[1] - p2[0]) % _P
    b = (p1[1] + p1[0]) * (p2[1] + p2[0]) % _P
    c = 2 * p1[3] * p2[3] * _D % _P
    d = 2 * p1[2] * p2[2] % _P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


def _double(p1):
    # RFC 8032 5.1.4's doubling (a = -1): cheaper than _add(p, p), same point
    a = p1[0] * p1[0] % _P
    b = p1[1] * p1[1] % _P
    c = 2 * p1[2] * p1[2] % _P
    h = a + b
    e = h - (p1[0] + p1[1]) * (p1[0] + p1[1]) % _P
    g = a - b
    f = c + g
    return (e * f % _P, g * h % _P, f * g % _P, e * h % _P)


_NEUTRAL = (0, 1, 1, 0)


def _mul(s, pt):
    q = _NEUTRAL
    while s > 0:
        if s & 1:
            q = _add(q, pt)
        pt = _double(pt)
        s >>= 1
    return q


def _equal(p1, p2):
    # x1/z1 == x2/z2 and y1/z1 == y2/z2, without dividing
    if (p1[0] * p2[2] - p2[0] * p1[2]) % _P != 0:
        return False
    return (p1[1] * p2[2] - p2[1] * p1[2]) % _P == 0


def _recover_x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * _inv(_D * y * y + 1)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P != 0:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P != 0:
        return None
    if (x & 1) != sign:
        x = _P - x
    return x


_GY = 4 * _inv(5) % _P
_GX = _recover_x(_GY, 0)
_G = (_GX, _GY, 1, _GX * _GY % _P)


def _compress(pt):
    zinv = _inv(pt[2])
    x = pt[0] * zinv % _P
    y = pt[1] * zinv % _P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(s):
    if len(s) != 32:
        return None
    y = int.from_bytes(s, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % _P)


def _expand(secret):
    if len(secret) != SECRET_SIZE:
        raise ValueError("an Ed25519 secret key is 32 bytes, not %d" % len(secret))
    h = _sha512(secret)
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


# ---- the API ------------------------------------------------------------------------------
def public_key(secret):
    """The 32-byte public key of the 32-byte *secret* key."""
    a, _prefix = _expand(bytes(secret))
    return _compress(_mul(a, _G))


def sign(secret, message):
    """The 64-byte Ed25519 signature of *message* under *secret*."""
    secret, message = bytes(secret), bytes(message)
    a, prefix = _expand(secret)
    pub = _compress(_mul(a, _G))
    r = _sha512_modq(prefix + message)
    rs = _compress(_mul(r, _G))
    h = _sha512_modq(rs + pub + message)
    s = (r + h * a) % _Q
    return rs + int.to_bytes(s, 32, "little")


def verify(public, message, signature):
    """True when *signature* is *public*'s signature of *message*. A key or a signature
    of the wrong size, or one that is not a point on the curve, is simply False."""
    try:
        public, message, signature = bytes(public), bytes(message), bytes(signature)
    except (TypeError, ValueError):
        return False
    if len(public) != PUBLIC_SIZE or len(signature) != SIGNATURE_SIZE:
        return False
    a_pt = _decompress(public)
    if a_pt is None:
        return False
    rs = signature[:32]
    r_pt = _decompress(rs)
    if r_pt is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _Q:
        return False
    h = _sha512_modq(rs + public + message)
    return _equal(_mul(s, _G), _add(r_pt, _mul(h, a_pt)))
