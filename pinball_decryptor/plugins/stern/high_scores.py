"""Spike 2 factory default HIGH-SCORE BOARD decoder + patcher (game ELF).

The scores the machine seeds its high-score board with on a fresh flash /
factory reset are ordinary ``AD_*`` adjustments (see :mod:`.adjustments`), but
the INITIALS and player names that go with them are not in that table — they
live in their own array of records in the same ELF:

    +0x00  char*  initials      "SSR", "JDB", "J B"   (always 3 writable bytes)
    +0x04  char*  player name   "THE KING", "BORGIE", "PIZZA CAT"
    +0x08  void*  a handler pointer, IDENTICAL in every record
    +0x0c  0
    +0x10  char*  slot label    "GRAND CHAMPION", "HIGH SCORE #1",
                                "KASHMIR CHAMPION"

The slot label is the same caption the operator menu shows, and for most slots
it is the very string the matching adjustment descriptor points at — which is
what ties a record to the adjustment holding that slot's default SCORE.

CROSS-CHECKED against hardware: this table on the TMNT 1.59 Pro card reads
Grand Champion = ``JDB`` / ``BORGIE``, and the factory board read back out of
that machine's own NVRAM was ``JDB`` at 20,000,000 — which is exactly
``AD_GRAND_CHAMPION_SCORE``'s compiled default on the same card.

Patching is size-neutral: each string is overwritten inside its own existing
allocation (the pool is 4-byte aligned, so initials always have room for 3
characters and a name has whatever its padding allows), so the card's ``.sidx``
refresh applies unchanged — same contract as the adjustment defaults.  This
module is pure (bytes in / bytes out); the ext4 read/write lives in
:mod:`.explorer`.
"""
import collections
import struct

# Record layout, stable across every card examined (LZ 1.22 LE, TMNT 1.59 Pro).
OFF_INITIALS, OFF_NAME, OFF_HANDLER, OFF_LABEL = 0x00, 0x04, 0x08, 0x10

# A record's initials are 1-3 characters; anything longer is some other array.
MAX_INITIALS = 3
# Below this many records it isn't a high-score board, it's a coincidence.
MIN_RECORDS = 5


def _cstr(table, data, va, limit=64):
    """The NUL-terminated string at *va*, or None when it isn't one."""
    off = table._off(va)
    if off is None:
        return None
    end = data.find(b"\x00", off, off + limit)
    if end < 0:
        return None
    try:
        s = data[off:end].decode("latin1")
    except Exception:
        return None
    return s if s.isprintable() else None


def _writable_len(table, data, va, limit=64):
    """How many characters may be written at *va*.

    The strings sit in a packed, 4-byte-aligned pool, so a string can grow into
    its own NUL padding but no further — one byte is always reserved for the
    terminator.  Returns 0 when *va* isn't mapped.
    """
    off = table._off(va)
    if off is None:
        return 0
    end = data.find(b"\x00", off, off + limit)
    if end < 0:
        return 0
    pad = end
    while pad < off + limit and data[pad] == 0:
        pad += 1
    return max(0, pad - off - 1)


class HighScoreDefaults:
    """The factory high-score board compiled into a game ELF.

    Construct with the ELF bytes and the already-decoded
    :class:`~.adjustments.AdjustmentTable` (its segment mapping and menu-label
    strings are reused).  Raises :class:`ValueError` when the table can't be
    located, which is the caller's cue to offer scores-only editing.
    """

    def __init__(self, elf_bytes, table):
        self.data = bytes(elf_bytes)
        self._t = table
        self.offset, self.stride, self.rows = self._locate()

    # ---- discovery ---------------------------------------------------
    def _label_owners(self):
        """``({menu-label VA: AD_ name}, {caption text: AD_ name})``.

        Most slots share the very string their adjustment points at, so the VA
        match is exact; the Grand Champion doesn't (its record says "GRAND
        CHAMPION" where the adjustment caption is "GRAND CHAMPION SCORE"), so
        the caption text is kept as a fallback key."""
        from .adjustments import OFF_MENU_LABEL
        by_va, by_text = {}, {}
        t = self._t
        for i in range(t.count):
            off = t._off(t.table_va + i * t.elem)
            if off is None:
                continue
            va = struct.unpack_from("<I", self.data, off + OFF_MENU_LABEL)[0]
            cap = _cstr(t, self.data, va)
            if cap:
                by_va[va] = t.names[i]
                by_text.setdefault(self._norm_caption(cap), t.names[i])
        return by_va, by_text

    @staticmethod
    def _norm_caption(text):
        """A slot caption reduced to what identifies the SLOT.

        A record and the adjustment holding its score often hold two separate
        strings for the same thing, and they don't spell it the same way:

          record "GRAND CHAMPION"    adjustment "GRAND CHAMPION SCORE"
          record "KASHMIR CHAMPION"  adjustment "KASHMIR CHAMP SCORE"  (LZ)
          record " COOP HIGH SCORE #3 "  (menu-indent padding, TMNT)

        so drop the padding, drop a trailing " SCORE", and fold CHAMPION down
        to CHAMP.  The _AWARD / _AWARDS siblings keep their own word and so
        can never normalise onto a score.
        """
        t = " ".join((text or "").split()).upper()
        if t.endswith(" SCORE"):
            t = t[:-len(" SCORE")]
        if t.endswith(" CHAMPION"):
            t = t[:-len(" CHAMPION")] + " CHAMP"
        return t

    @classmethod
    def _owner_for(cls, label, va, by_va, by_text):
        """The adjustment holding this slot's default score, or None."""
        if va in by_va:
            return by_va[va]
        if not label:
            return None
        return by_text.get(cls._norm_caption(label))

    def _locate(self):
        """Find the record array by SHAPE — no per-title magic values.

        Every record starts {char* 1-3 printable chars, char* short string,
        <handler>} and every record in the array shares that third word, so:
        collect candidates, group them by handler, and keep the longest
        constant-stride run.
        """
        t, data = self._t, self.data
        cands = []
        for po, _pv, fsz in t._loads:
            base = (po + 3) & ~3
            n = (po + fsz - base) // 4
            if n <= 3:
                continue
            words = memoryview(data)[base:base + n * 4].cast("I")
            for j in range(n - 3):
                w0 = words[j]
                if not w0:
                    continue
                s0 = _cstr(t, data, w0, 8)
                if not s0 or not 1 <= len(s0) <= MAX_INITIALS:
                    continue
                s1 = _cstr(t, data, words[j + 1], 40)
                if not s1 or not 1 <= len(s1) <= 32:
                    continue
                handler = words[j + 2]
                if handler:
                    cands.append((base + 4 * j, handler))
        by_handler = collections.defaultdict(list)
        for off, handler in cands:
            by_handler[handler].append(off)

        best = None
        for offs in by_handler.values():
            offs.sort()
            for stride in range(16, 129, 4):
                run, cur = [], [offs[0]]
                for o in offs[1:]:
                    if o - cur[-1] == stride:
                        cur.append(o)
                    else:
                        if len(cur) > len(run):
                            run = cur
                        cur = [o]
                if len(cur) > len(run):
                    run = cur
                if len(run) >= MIN_RECORDS and (best is None
                                                or len(run) > len(best[1])):
                    best = (stride, run)
        if best is None:
            raise ValueError("no default high-score table found")
        stride, run = best
        by_va, by_text = self._label_owners()
        # One adjustment holds one score, so it can own at most one slot.  The
        # co-op / team boards repeat a caption at several menu indents and all
        # of them normalise onto the same adjustment; first (least-indented)
        # record wins, the rest are initials-and-name only.
        claimed = set()
        rows = []
        for i, off in enumerate(run):
            w = struct.unpack_from("<5I", data, off)
            label_va = w[OFF_LABEL // 4] if stride > OFF_LABEL else 0
            label = _cstr(t, data, label_va, 64)
            if not label or len(label) < 4:
                label_va, label = 0, None
                for k in range(3, stride // 4):
                    cand = struct.unpack_from("<I", data, off + k * 4)[0]
                    s = _cstr(t, data, cand, 64)
                    if s and len(s) >= 4:
                        label_va, label = cand, s
                        break
            rows.append({
                "index": i,
                "offset": off,
                # `label` is the RAW caption and the record's stable key —
                # co-op / team boards repeat the same wording at different
                # menu indents (" COOP HIGH SCORE #3 " vs "  COOP HIGH SCORE
                # #3  "), and that padding is what keeps them distinct.
                # `display` is the tidied version for the UI.
                "label": label or "High score %d" % (i + 1),
                "display": (label or "High score %d" % (i + 1)).strip(),
                "adjustment": None,     # filled in just below
                "initials": _cstr(t, data, w[0], 8) or "",
                "name": _cstr(t, data, w[1], 40) or "",
                "initials_max": _writable_len(t, data, w[0], 8),
                "name_max": _writable_len(t, data, w[1], 40),
            })
            owner = self._owner_for(label, label_va, by_va, by_text)
            if owner and owner not in claimed:
                claimed.add(owner)
                rows[-1]["adjustment"] = owner
        return run[0], stride, rows

    # ---- read --------------------------------------------------------
    def by_label(self):
        """``{slot label: row}`` — the label is the stable key across firmware
        versions (record ORDER and index both shift between releases)."""
        return {r["label"]: r for r in self.rows}

    # ---- patch -------------------------------------------------------
    def patched_bytes(self, overrides):
        """A copy of the ELF with ``{slot label: {initials, name}}`` written in.

        Each string is written inside its own allocation and NUL-padded to the
        original footprint, so the file size never changes.  Raises ValueError
        on an unknown label or a value too long for its slot.
        """
        buf = bytearray(self.data)
        rows = self.by_label()
        for label, vals in overrides.items():
            row = rows.get(label)
            if row is None:
                raise ValueError("unknown high-score slot %r" % label)
            w = struct.unpack_from("<2I", self.data, row["offset"])
            for key, va, cap in (("initials", w[0], row["initials_max"]),
                                 ("name", w[1], row["name_max"])):
                if key not in vals:
                    continue
                text = str(vals[key] or "")
                if len(text) > cap:
                    raise ValueError(
                        "%s for %r is %d characters; this slot has room for %d"
                        % (key, label, len(text), cap))
                off = self._t._off(va)
                if off is None:
                    raise ValueError("%r has no writable %s" % (label, key))
                # Overwrite the whole allocation so no tail of the old string
                # survives past the new terminator.
                buf[off:off + cap + 1] = (
                    text.encode("latin1") + b"\x00" * (cap + 1 - len(text)))
        return bytes(buf)
