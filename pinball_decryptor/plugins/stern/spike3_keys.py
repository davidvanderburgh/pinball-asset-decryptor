"""Where a Spike 3 partition's decryption key comes from.

**This module contains NO key material.**  Spike 3 keys stay out of the public
repo; the user supplies them at runtime, and this class only *loads* what they
point us at.  Two kinds of key unlock a Spike 3 LUKS partition:

* an **unlock keyfile** — the 32-byte BCM2711 customer-OTP value the machine's
  initramfs feeds to ``cryptsetup``.  It is fleet-wide and unlocks every
  partition of every card, but recovering its value needs an early-boot capture
  of a real board; and
* a **per-volume master key** — the random XTS key of one specific partition of
  one specific image, recoverable only from a RAM dump of the board running that
  image.

Either unlocks a partition: an unlock keyfile goes through the LUKS keyslot to
*derive* the master key; a master key is used directly (the keyslot is skipped).

A :class:`Spike3KeySource` is built from a JSON keyfile the user owns::

    {
      "otp_keyfile": "<64 hex chars, or a path to a 32-byte file>",
      "master_keys": {
        "games":  "<64 hex>",        # by role, or
        "star_wars_2025_pro-0_84_0:games": "<64 hex>"   # by image:role
      }
    }

The pipeline finds this file from ``$PAD_SPIKE3_KEYFILE`` or a ``*.padkeys.json``
sidecar next to the card image.  Nothing here is ever committed.
"""

from __future__ import annotations

import json
import os


class Spike3KeyError(Exception):
    pass


def _as_32_bytes(value, what):
    """Accept 64 hex chars, or a path to a 32-byte binary file."""
    if value is None:
        return None
    if isinstance(value, (bytes, bytearray)):
        b = bytes(value)
    elif os.path.exists(value):
        with open(value, "rb") as f:
            b = f.read()
    else:
        s = value.strip().replace(" ", "")
        try:
            b = bytes.fromhex(s)
        except ValueError:
            raise Spike3KeyError("%s is neither 64 hex chars nor a file path: "
                                 "%r" % (what, value))
    if len(b) != 32:
        raise Spike3KeyError("%s must be 32 bytes, got %d" % (what, len(b)))
    return b


class Spike3KeySource:
    """Resolve a partition to its 32-byte master key.

    Parameters
    ----------
    otp_keyfile : 32 bytes | hex | path, optional
        The customer-OTP unlock keyfile (unlocks any partition via its keyslot).
    master_keys : dict, optional
        ``{role_or_"image:role": hex/bytes}`` per-volume master keys.
    image_id : str, optional
        The card's identity (``<title>-<version>``) used to match the more
        specific ``"image:role"`` master-key entries.
    """

    def __init__(self, otp_keyfile=None, master_keys=None, image_id=None):
        self._otp = _as_32_bytes(otp_keyfile, "otp_keyfile")
        self._mks = {}
        for k, v in (master_keys or {}).items():
            self._mks[k] = _as_32_bytes(v, "master_keys[%s]" % k)
        self._image_id = image_id

    # -- construction --------------------------------------------------------
    @classmethod
    def from_keyfile(cls, path, image_id=None):
        with open(path, "rb") as f:
            doc = json.loads(f.read().decode("utf-8"))
        base = os.path.dirname(os.path.abspath(path))

        def _resolve(v):
            # a bare filename in the keyfile is relative to the keyfile
            if isinstance(v, str) and not os.path.isabs(v) \
                    and os.path.exists(os.path.join(base, v)):
                return os.path.join(base, v)
            return v

        otp = _resolve(doc.get("otp_keyfile"))
        mks = {k: _resolve(v) for k, v in (doc.get("master_keys") or {}).items()}
        return cls(otp_keyfile=otp, master_keys=mks, image_id=image_id)

    @classmethod
    def discover(cls, image_path=None, image_id=None):
        """Find a key source from the environment or a sidecar, or return None.

        Looked for, in order: ``$PAD_SPIKE3_KEYFILE``; a ``<image>.padkeys.json``
        or ``padkeys.json`` next to *image_path*.  Returns None when nothing is
        found (the caller then reports the partition as locked)."""
        env = os.environ.get("PAD_SPIKE3_KEYFILE")
        if env and os.path.exists(env):
            return cls.from_keyfile(env, image_id=image_id)
        if image_path:
            d = os.path.dirname(os.path.abspath(image_path))
            for cand in (os.path.abspath(image_path) + ".padkeys.json",
                         os.path.join(d, "padkeys.json")):
                if os.path.exists(cand):
                    return cls.from_keyfile(cand, image_id=image_id)
        return None

    def has_any(self):
        return bool(self._otp or self._mks)

    # -- resolution ----------------------------------------------------------
    def master_key(self, header, role=None, part=None):
        """Return a 32-byte master key for the partition described by *header*.

        A per-volume master key (most specific first: ``image:role`` then
        ``role``) wins; otherwise the OTP keyfile is run through the keyslot to
        derive it.  The caller verifies the result against the LUKS digest."""
        otp_mod = _lo()
        # 1) direct master keys
        if role:
            for key in (("%s:%s" % (self._image_id, role)) if self._image_id
                        else None, role):
                if key and key in self._mks:
                    return self._mks[key]
        # 2) OTP unlock keyfile -> keyslot -> master key
        if self._otp is not None:
            return otp_mod.unlock_master_key(header, self._otp,
                                             area_bytes=header.raw)
        raise Spike3KeyError(
            "no Spike 3 key available for role %r. Point PAD at a keyfile via "
            "$PAD_SPIKE3_KEYFILE or a <image>.padkeys.json sidecar." % role)


def _lo():
    from . import spike3
    return spike3._luks_otp()
