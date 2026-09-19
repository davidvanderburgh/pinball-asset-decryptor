"""PREVIEW FEATURES: a switch in the app, unlocked by a personal code.

Some work ships to main before it ships to everyone (the mode maker first). It is in
every copy of the app, and switched off. A person David chooses gets a PREVIEW CODE: a
line of text naming them, what it unlocks and until when, signed with David's private
key (``tools/preview_code.py``). Help > Preview features takes the code; this module
checks the signature against the public key below, so nobody can make a code, or edit
one (a later date, another name, another feature), without that private key. The repo
is public, so there is no hidden setting to flip instead: settings.json holds the codes
themselves, and a code that does not check out turns nothing on.

THE CODE is ``PAD-PREVIEW-`` and then base32 (RFC 4648, no padding) of a compact JSON
payload followed by its 64-byte Ed25519 signature. Base32 because it survives being
retyped, upper- or lower-cased, and wrapped by a mail client: whitespace, line breaks
and dashes after the prefix are ignored. The payload::

    {"v": 1, "f": ["modes"], "n": "Test Person", "i": "2026-09-18", "e": "2026-12-17",
     "id": "3f9a1c"}

``f`` the features, ``n`` the person's name, ``i`` the issue date and ``e`` the last
day it works (both UTC dates), ``id`` a short random id. What is signed is
:data:`CONTEXT` followed by the payload bytes, so a signature made for anything else
with the same key can never pass as a code.

WHEN IT IS CHECKED: once at start-up (:func:`load`, from the app, which caches the
result for the whole run - the check is pure Python and takes a few milliseconds per
code) and when a code is unlocked in the dialog (:func:`check`). An expired code turns
its feature off at the next start. :func:`enabled` is what every gated place asks.
"""
from __future__ import annotations

import base64
import binascii
import datetime as _dt
import json
import re
import threading
import time
from dataclasses import dataclass, field

from . import ed25519

#: What every code starts with.
PREFIX = "PAD-PREVIEW-"
#: Signed in front of the payload (never part of the code itself).
CONTEXT = b"pinball_decryptor preview code v1\n"
#: The settings.json key that holds the codes (a list of strings).
SETTINGS_KEY = "preview_codes"
#: The payload version this app reads.
VERSION = 1

#: THE PUBLIC KEYS a code may be signed with (hex). Generated on David's PC with
#: ``python tools/preview_code.py init`` on 2026-09-18; the private half never leaves
#: that PC (``%APPDATA%\\pinball_decryptor_signing\\preview_signing_key.txt``).
#: A tuple so a key can be rotated in without voiding every code already issued.
PUBLIC_KEYS = (
    "4ab79858885d99790be95d46fc0855085df3ab4cff77191a51339fe3e1005e6c",
)

#: The preview features this version of the app has, by id, with the name people see.
FEATURES = {
    "modes": "Mode maker",
}

_NAME_MAX = 64
_ID_RE = re.compile(r"^[0-9a-z]{4,16}$")


class PreviewCodeError(ValueError):
    """A code that turns nothing on. The message is a sentence for the person."""


@dataclass(frozen=True)
class Grant:
    """What a code that checked out says."""

    code: str
    id: str
    name: str
    features: tuple
    issued: _dt.date
    expires: _dt.date

    def expired(self, today=None):
        return (today or utc_today()) > self.expires

    def known_features(self):
        return tuple(f for f in self.features if f in FEATURES)


@dataclass
class Status:
    """One stored code as the dialog lists it."""

    code: str
    grant: Grant = None
    active: bool = False
    lines: list = field(default_factory=list)
    error: str = ""


def utc_today():
    return _dt.datetime.now(_dt.timezone.utc).date()


def _date(s):
    return _dt.date.fromisoformat(str(s))


# ---- the code's text -------------------------------------------------------------------
def payload_bytes(features, name, issued, expires, code_id):
    """The compact JSON a code carries (keys sorted, no spaces, UTF-8)."""
    data = {"v": VERSION, "f": list(features), "n": str(name),
            "i": issued.isoformat(), "e": expires.isoformat(), "id": str(code_id)}
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def encode(payload, signature):
    """``PAD-PREVIEW-`` + base32 of *payload* + *signature*."""
    body = base64.b32encode(bytes(payload) + bytes(signature)).decode("ascii").rstrip("=")
    return PREFIX + body


def normalise(text):
    """The code in *text* as ``PAD-PREVIEW-<BASE32>``: whitespace and line breaks
    anywhere, case, and dashes after the prefix do not matter. Raises
    :class:`PreviewCodeError` for text that is not a preview code at all."""
    squashed = re.sub(r"\s+", "", str(text or "")).upper()
    if not squashed.startswith(PREFIX):
        raise PreviewCodeError(
            "That is not a preview code. A preview code starts with %s." % PREFIX)
    body = squashed[len(PREFIX):].replace("-", "").rstrip("=")
    if not body or not re.fullmatch(r"[A-Z2-7]+", body):
        raise PreviewCodeError(
            "That preview code is incomplete or mistyped. Paste the whole code again.")
    return PREFIX + body


def _split(norm):
    body = norm[len(PREFIX):]
    try:
        raw = base64.b32decode(body + "=" * (-len(body) % 8))
    except (binascii.Error, ValueError):
        raise PreviewCodeError(
            "That preview code is incomplete or mistyped. Paste the whole code again.") from None
    if len(raw) <= ed25519.SIGNATURE_SIZE + 2:
        raise PreviewCodeError(
            "That preview code is incomplete or mistyped. Paste the whole code again.")
    return raw[:-ed25519.SIGNATURE_SIZE], raw[-ed25519.SIGNATURE_SIZE:]


def decode(text, public_keys=None):
    """The :class:`Grant` in *text*, whose signature checks out against one of
    *public_keys* (default :data:`PUBLIC_KEYS`). Expiry and features are NOT judged here
    (:func:`check` does). Raises :class:`PreviewCodeError` with a sentence."""
    norm = normalise(text)
    payload, sig = _split(norm)
    keys = PUBLIC_KEYS if public_keys is None else public_keys
    good = False
    for k in keys:
        try:
            pub = bytes.fromhex(k)
        except ValueError:
            continue
        if ed25519.verify(pub, CONTEXT + payload, sig):
            good = True
            break
    if not good:
        raise PreviewCodeError(
            "That preview code was not issued for this app: its signature does not check "
            "out. Ask for a new code, and paste it exactly as it was sent.")
    try:
        data = json.loads(payload.decode("utf-8"))
        if not isinstance(data, dict) or int(data.get("v", 0)) != VERSION:
            raise ValueError("version")
        feats = data["f"]
        if not isinstance(feats, list) or not all(isinstance(f, str) for f in feats):
            raise ValueError("features")
        name = str(data["n"]).strip()
        if not name or len(name) > _NAME_MAX:
            raise ValueError("name")
        code_id = str(data["id"])
        if not _ID_RE.match(code_id):
            raise ValueError("id")
        grant = Grant(code=norm, id=code_id, name=name, features=tuple(feats),
                      issued=_date(data["i"]), expires=_date(data["e"]))
    except (ValueError, KeyError, TypeError, UnicodeDecodeError):
        raise PreviewCodeError(
            "That preview code was made for another version of the app, and this one "
            "cannot read it.") from None
    return grant


def check(text, today=None, public_keys=None):
    """:func:`decode`, and also: not expired, and it unlocks something this version of
    the app has. Returns the :class:`Grant`; raises :class:`PreviewCodeError`."""
    grant = decode(text, public_keys)
    if grant.expired(today):
        raise PreviewCodeError(
            "That preview code for %s ended on %s. Ask for a new one."
            % (grant.name, grant.expires.isoformat()))
    if not grant.known_features():
        raise PreviewCodeError(
            "That preview code unlocks a preview this version of the app does not have "
            "(%s)." % ", ".join(grant.features or ("nothing",)))
    return grant


def describe(grant, today=None):
    """The dialog's lines for *grant*: ``Mode maker: on for <name>, until <date>`` per
    feature, or ``... ended on <date>`` once it has expired."""
    out = []
    ended = grant.expired(today)
    for f in grant.features:
        label = FEATURES.get(f)
        if label is None:
            out.append("%s: not in this version of the app (code for %s)" % (f, grant.name))
        elif ended:
            out.append("%s: expired on %s (code for %s)"
                       % (label, grant.expires.isoformat(), grant.name))
        else:
            out.append("%s: on for %s, until %s"
                       % (label, grant.name, grant.expires.isoformat()))
    return out


# ---- this run's state -----------------------------------------------------------------
_lock = threading.Lock()
_active = frozenset()
_statuses = []
_load_ms = 0.0


def enabled(feature):
    """Is preview *feature* switched on in this run? Off until :func:`load` found a code
    for it that checked out and had not expired."""
    return feature in _active


def active_features():
    return _active


def statuses():
    """The codes :func:`load` last judged, as :class:`Status` rows."""
    return list(_statuses)


def load_ms():
    """How long the last :func:`load` took, in milliseconds (the start-up cost)."""
    return _load_ms


def judge(codes, today=None, public_keys=None):
    """``(active features, [Status])`` for the stored *codes*, without changing this
    run's state."""
    today = today or utc_today()
    rows, active, seen = [], set(), set()
    for text in codes or ():
        if not isinstance(text, str) or not text.strip():
            continue
        st = Status(code=text.strip())
        try:
            g = decode(text, public_keys)
        except PreviewCodeError as e:
            st.error = str(e)
            st.lines = ["Not valid: %s" % e]
            rows.append(st)
            continue
        if g.id in seen:
            continue
        seen.add(g.id)
        st.grant, st.lines = g, describe(g, today)
        if not g.expired(today):
            known = set(g.known_features())
            active |= known
            st.active = bool(known)
        rows.append(st)
    return frozenset(active), rows


def load(codes, today=None, public_keys=None):
    """Judge the stored *codes* and make the result this run's state (cached: nothing
    re-checks a signature until the next :func:`load`). Returns the :class:`Status`
    rows. Never raises."""
    global _active, _statuses, _load_ms
    t0 = time.perf_counter()
    try:
        active, rows = judge(codes, today, public_keys)
    except Exception:                   # noqa: BLE001 - a bad settings file turns nothing on
        active, rows = frozenset(), []
    with _lock:
        _active, _statuses = active, rows
        _load_ms = (time.perf_counter() - t0) * 1000.0
    return list(rows)


def add_code(codes, text, today=None, public_keys=None):
    """``(new code list, Grant)``: *text* checked (:func:`check`) and added to the stored
    *codes*, replacing an earlier copy of the same code id. Raises
    :class:`PreviewCodeError`."""
    grant = check(text, today, public_keys)
    kept = []
    for c in codes or ():
        try:
            if decode(c, public_keys).id == grant.id:
                continue
        except PreviewCodeError:
            pass
        kept.append(c)
    return kept + [grant.code], grant


def remove_code(codes, code):
    """The stored *codes* without *code* (compared as normalised text)."""
    try:
        target = normalise(code)
    except PreviewCodeError:
        target = str(code).strip()
    out = []
    for c in codes or ():
        try:
            same = normalise(c) == target
        except PreviewCodeError:
            same = str(c).strip() == target
        if not same:
            out.append(c)
    return out
