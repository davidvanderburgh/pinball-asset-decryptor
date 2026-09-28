"""Spike 2 machine SETTINGS files: Stern's ``.SPB`` USB export and the card's NVM store.

PAD-233.  The same bytes live in two places:

  * ``<CODE>_<serial>_<date>_SET-<n>.SPB`` - what the operator menu's "Save
    Settings to USB" writes and "Load Settings from USB" reads back.  A 28-byte
    container around the body: ``b"SPBF"`` + u32 LE body length + SHA1(body).
  * ``/data/nv/<title>/NVM/<generation>`` on the card - the body alone (the
    machine's own three-deep ring, each file beside a ``.crc32`` sidecar holding
    the plain zlib CRC32 of the file).

THE BODY (verified on TMNT 1.58 / 1.59, Godzilla 1.15 and Batman 66 saves and on
the rig's own stores):

    +0x00  b"MAP0" + a two-letter map code ("Q5" TMNT, "T6" Godzilla)
    +0x08  u32 machine serial (0 in a store no machine has written)
    +0x0c  the build's version bytes (major, minor, ...)
    +0x3c  u16 number of audits, +0x3e u16 number of adjustments
    +208   the audits, 40 bytes each:
             SHA1(caption)[20] | u32 id | u32 value | u32 | u32 value | u32 check
             check = 0xFFFF - bytesum(the three value words)
    then   the adjustments (operator settings), 44 bytes each:
             SHA1(caption)[20] | default | min | max | adjustment id | VALUE | check
             check (low byte) = 0xFF - bytesum(VALUE), mod 256
    then   high scores and further state this module does not write.

Every record is keyed by the SHA1 of the operator menu's CAPTION, so a setting is
found by its name on any build that spells it the same way - which is what makes
carrying settings from one game code version to another possible (and what the
multi-boot builder's settings report, mkmulticard.settings_cost, counts).

The machine validates only each value's check and the container's SHA1 (a crafted
file with stale timestamps loaded on David's TMNT, 2026-07-22), so a write here is:
change the value, fix its check, re-sign.  A load restores audits and high scores
as well as settings, so write into a FRESH save of the machine you load it on.

This module is pure (bytes in / bytes out).  ``python -m
pinball_decryptor.plugins.stern.spb`` is its command line (show / set / carry).
"""
import argparse
import collections
import hashlib
import struct
import sys
import zlib

MAGIC = b"SPBF"
CONTAINER = 28
BODY_MAGIC = b"MAP0"
OFF_COUNTS = 0x3c
AUDITS_AT = 208
AUDIT_SIZE = 40
ADJ_SIZE = 44

Setting = collections.namedtuple(
    "Setting", "index offset key default min max id value check_ok")


def caption_key(caption):
    """The 20-byte key a caption's record is stored under: SHA1 of the caption, byte for
    byte (so a caption is never stripped or re-cased on the way in)."""
    if isinstance(caption, str):
        caption = caption.encode("latin-1")
    return hashlib.sha1(caption).digest()


def _bytesum(value):
    return sum(struct.pack("<I", value & 0xFFFFFFFF))


def adj_check(value):
    """The low byte of an adjustment's check word."""
    return (0xFF - _bytesum(value)) & 0xFF


def audit_check(*values):
    return (0xFFFF - sum(_bytesum(v) for v in values)) & 0xFFFFFFFF


def nvm_crc32(data):
    """What the card's ``<generation>.crc32`` sidecar holds for a store file: u32 LE."""
    return struct.pack("<I", zlib.crc32(bytes(data)) & 0xFFFFFFFF)


class SettingsFile(object):
    """One settings body, from an ``.SPB`` export or a raw NVM generation.  Raises
    :class:`ValueError` for anything that is neither."""

    def __init__(self, data):
        data = bytes(data)
        self.container = data[:4] == MAGIC
        if self.container:
            if len(data) < CONTAINER:
                raise ValueError("truncated .SPB container")
            n = struct.unpack_from("<I", data, 4)[0]
            if n != len(data) - CONTAINER:
                raise ValueError(".SPB says its body is %d bytes but %d follow"
                                 % (n, len(data) - CONTAINER))
            self.signature_ok = hashlib.sha1(data[CONTAINER:]).digest() == data[8:CONTAINER]
            body = data[CONTAINER:]
        else:
            self.signature_ok = None
            body = data
        if body[:4] != BODY_MAGIC or len(body) < AUDITS_AT:
            raise ValueError("not a Spike 2 settings file (no MAP0 body)")
        self.body = bytearray(body)
        self.n_audits, self.n_adjustments = struct.unpack_from("<HH", body, OFF_COUNTS)
        self.adj_at = AUDITS_AT + self.n_audits * AUDIT_SIZE
        if self.adj_at + self.n_adjustments * ADJ_SIZE > len(body):
            raise ValueError("the body is shorter than its %d audits and %d adjustments"
                             % (self.n_audits, self.n_adjustments))

    @classmethod
    def read(cls, path):
        with open(path, "rb") as f:
            return cls(f.read())

    # --- identity
    @property
    def map_code(self):
        return self.body[4:6].decode("latin-1")

    @property
    def serial(self):
        return struct.unpack_from("<I", self.body, 8)[0]

    @property
    def version(self):
        """'1.59' - major.minor from the version bytes."""
        return "%d.%02d" % (self.body[12], self.body[13])

    # --- records
    def settings(self):
        out = []
        for i in range(self.n_adjustments):
            o = self.adj_at + i * ADJ_SIZE
            d, mn, mx, aid, val, chk = struct.unpack_from("<6I", self.body, o + 20)
            out.append(Setting(i, o, bytes(self.body[o:o + 20]), d, mn, mx, aid, val,
                               (chk & 0xFF) == adj_check(val)))
        return out

    def audits(self):
        """[(key, value, check_ok)] - read only."""
        out = []
        for i in range(self.n_audits):
            o = AUDITS_AT + i * AUDIT_SIZE
            _id, v1, v2, v3, chk = struct.unpack_from("<5I", self.body, o + 20)
            ok = chk == audit_check(v1, v2, v3) or not (v1 or v2 or v3 or chk)
            out.append((bytes(self.body[o:o + 20]), v1, ok))
        return out

    def find(self, key):
        """The Setting stored under `key` (20 bytes, or a caption), or None."""
        if not isinstance(key, bytes) or len(key) != 20:
            key = caption_key(key)
        for s in self.settings():
            if s.key == key:
                return s
        return None

    def set(self, key, value):
        """Write one setting's value and its check -> the Setting as it was.  Refuses a key
        the file does not hold and a value outside the setting's own min..max."""
        s = self.find(key)
        if s is None:
            raise KeyError("this file holds no setting under that caption")
        value = int(value)
        if not s.min <= value <= s.max:
            raise ValueError("%d is outside this setting's range %d..%d" % (value, s.min, s.max))
        struct.pack_into("<I", self.body, s.offset + 36, value)
        # only the low byte is the check; the other three are kept as the machine wrote them
        chk = struct.unpack_from("<I", self.body, s.offset + 40)[0]
        struct.pack_into("<I", self.body, s.offset + 40, (chk & ~0xFF) | adj_check(value))
        return s

    def bad_checks(self):
        return [s for s in self.settings() if not s.check_ok]

    def to_bytes(self):
        """The file as written: re-signed when it is an .SPB, the bare body when it is a store
        (write ``nvm_crc32`` of it into the ``.crc32`` sidecar beside it)."""
        body = bytes(self.body)
        if not self.container:
            return body
        return MAGIC + struct.pack("<I", len(body)) + hashlib.sha1(body).digest() + body


def carry(src, dst, keys=None):
    """Copy settings from `src` into `dst` by caption key -> OrderedDict with lists
    'changed' [(key, old, new)], 'same' [key], 'out_of_range' [(key, value, min, max)] and
    'missing' [key]: settings `dst` has and `src` lacks (they keep dst's value).  `keys`
    limits it to those keys.  Nothing outside dst's own ranges is ever written."""
    theirs = {s.key: s for s in src.settings()}
    out = collections.OrderedDict((k, []) for k in ("changed", "same", "out_of_range", "missing"))
    want = None if keys is None else set(keys)
    for s in dst.settings():
        if want is not None and s.key not in want:
            continue
        t = theirs.get(s.key)
        if t is None:
            out["missing"].append(s.key)
        elif t.value == s.value:
            out["same"].append(s.key)
        elif not s.min <= t.value <= s.max:
            out["out_of_range"].append((s.key, t.value, s.min, s.max))
        else:
            dst.set(s.key, t.value)
            out["changed"].append((s.key, s.value, t.value))
    return out


def elf_captions(elf):
    """{key: (AD name, caption, where)} for a game ELF - `where` as
    :func:`.menu_visibility.statuses` says it ('' menu, 'service', 'debug', None unknown).
    Empty when the ELF's adjustment table cannot be located."""
    from . import adjustments, menu_visibility
    try:
        table = adjustments.AdjustmentTable(elf)
    except ValueError:
        return {}
    mode = adjustments._caption_mode(table)
    where = menu_visibility.statuses(table) or {}
    out = collections.OrderedDict()
    for i in range(1, table.count):
        name = table.names[i]
        if not name or not name.startswith("AD_"):
            continue
        direct, indirect = adjustments._caption_at(table, i)
        cap = indirect if mode == "indirect" else direct
        if adjustments._is_caption(cap):
            out[caption_key(cap)] = (name, cap, where.get(i))
    return out


# ---------------------------------------------------------------------------- command line
def _label(key, names):
    hit = names.get(key)
    return " ".join(hit[1].split()) if hit else "(unnamed %s)" % key.hex()[:12]


def _load_names(path):
    if not path:
        return {}
    with open(path, "rb") as f:
        return elf_captions(f.read())


def _write(sf, path):
    with open(path, "wb") as f:
        f.write(sf.to_bytes())
    if not sf.container:
        with open(path + ".crc32", "wb") as f:
            f.write(nvm_crc32(sf.to_bytes()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="spb", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("show", help="list every setting in a .SPB or NVM file")
    p.add_argument("file")
    p.add_argument("--elf", help="the game program, to name each setting by its caption")
    p = sub.add_parser("set", help="change one setting by its caption")
    p.add_argument("file")
    p.add_argument("caption")
    p.add_argument("value", type=int)
    p.add_argument("--out", required=True)
    p = sub.add_parser("carry", help="copy settings from one file into another by caption")
    p.add_argument("src")
    p.add_argument("dst")
    p.add_argument("--out", required=True)
    p.add_argument("--elf", help="the DESTINATION's game program, to name what moved")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "show":
            sf, names = SettingsFile.read(a.file), _load_names(a.elf)
            print("%s map %s serial %d version %s: %d settings, %d audits%s"
                  % ("SPB" if sf.container else "NVM", sf.map_code, sf.serial, sf.version,
                     sf.n_adjustments, sf.n_audits,
                     "" if sf.signature_ok in (None, True) else " - SIGNATURE DOES NOT MATCH"))
            for s in sf.settings():
                print("%4d  %-44s %12d  (default %d, %d..%d)%s"
                      % (s.id, _label(s.key, names)[:44], s.value, s.default, s.min, s.max,
                         "" if s.check_ok else "  BAD CHECK"))
        elif a.cmd == "set":
            sf = SettingsFile.read(a.file)
            old = sf.set(a.caption, a.value)
            _write(sf, a.out)
            print("%s: %d -> %d; wrote %s" % (a.caption, old.value, a.value, a.out))
        else:
            src, dst, names = SettingsFile.read(a.src), SettingsFile.read(a.dst), _load_names(a.elf)
            rep = carry(src, dst)
            _write(dst, a.out)
            for key, old, new in rep["changed"]:
                print("changed  %-44s %d -> %d" % (_label(key, names)[:44], old, new))
            for key, v, mn, mx in rep["out_of_range"]:
                print("KEPT     %-44s %d is outside %d..%d here" % (_label(key, names)[:44], v, mn, mx))
            print("%d changed, %d already the same, %d out of range, %d the source does not have; "
                  "wrote %s" % (len(rep["changed"]), len(rep["same"]), len(rep["out_of_range"]),
                                len(rep["missing"]), a.out))
    except (OSError, ValueError, KeyError) as e:
        print("spb: %s" % (e.args[0] if e.args else e), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
