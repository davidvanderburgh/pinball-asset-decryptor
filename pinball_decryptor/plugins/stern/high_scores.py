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
    if s.isprintable():
        return s
    # Some captions are two display lines in one string ("JAWS MULTIBALL 1
    # \nCHAMPION", Jaws/Godzilla/King Kong) — a newline is the one control
    # character that doesn't disqualify.
    if "\n" in s and s.replace("\n", " ").isprintable():
        return s
    return None


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
        the caption text is kept as a fallback key.

        Older builds interpose the same language bundle the records use (see
        :meth:`_label_ptr`), so the caption is resolved through it and both
        maps are keyed by the resolved ENGLISH string — the same thing
        :meth:`_slot_label` hands back for a record."""
        from .adjustments import OFF_MENU_LABEL
        by_va, by_text = {}, {}
        t = self._t
        for i in range(t.count):
            off = t._off(t.table_va + i * t.elem)
            if off is None:
                continue
            va = struct.unpack_from("<I", self.data, off + OFF_MENU_LABEL)[0]
            va, cap = self._label_ptr(va)
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

    def _label_ptr(self, va):
        """``(string VA, text)`` for a label word, or ``(0, None)``.

        Newer builds point straight at the caption; older ones point at a
        NULL-terminated per-language bundle ``{char* EN, DE, FR, ES, IT, 0}``
        (Foo Fighters 1.03, Batman, Munsters, …), so when the word isn't a
        string itself, its first pointee is tried — the English caption.
        """
        t, data = self._t, self.data
        s = _cstr(t, data, va, 64)
        if s and len(s) >= 4:
            return va, s
        off = t._off(va)
        if off is not None and off + 4 <= len(data):
            first = struct.unpack_from("<I", data, off)[0]
            if first:
                s = _cstr(t, data, first, 64)
                if s and len(s) >= 4:
                    return first, s
        return 0, None

    def _slot_label(self, off, stride):
        """``(label VA, label text)`` for the record at *off*, or ``(0, None)``.

        The label normally sits at +0x10, but when that word doesn't resolve
        the other tail words are tried — record layouts drift a little
        between titles.
        """
        data = self.data
        if stride > OFF_LABEL:
            va, s = self._label_ptr(
                struct.unpack_from("<I", data, off + OFF_LABEL)[0])
            if s:
                return va, s
        for k in range(3, stride // 4):
            if k == OFF_LABEL // 4:
                continue
            va, s = self._label_ptr(
                struct.unpack_from("<I", data, off + k * 4)[0])
            if s:
                return va, s
        return 0, None

    def _locate(self):
        """Find the record array by SHAPE — no per-title magic values.

        Every record starts {char* 1-3 printable chars, char* short string,
        <handler>} and every record in the array shares that third word, so:
        collect candidates, group them by handler, and take the best
        constant-stride run.

        "Best" is NOT simply the longest run: a connector/pin wiring table
        ("CN7", pin "2", …) is shaped exactly like {initials, name, shared
        word} and on boards with more lamps than high-score slots (Venom: 87
        vs 47) it out-runs the real board; a topper LED map can even carry
        uppercase captions ("TOPPER 1-R", Bond: 314 of them).  What no
        impostor has is records whose captions normalise onto the score
        adjustments (GRAND CHAMPION -> AD_GRAND_CHAMPION_SCORE …), so runs
        are ranked by mapped-adjustment count first, readable-caption count
        second, and length only breaks the remaining ties — a title with no
        captions at all still resolves like before.
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

        by_va, by_text = self._label_owners()
        best = best_key = None
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
                if len(run) < MIN_RECORDS:
                    continue
                labels = mapped = 0
                claimed = set()
                for off in run:
                    va, s = self._slot_label(off, stride)
                    # ASCII-only for SCORING: a coil table's tail words can
                    # decode as printable-latin1 mush; real captions never do.
                    if s and s.isascii():
                        labels += 1
                    owner = self._owner_for(s, va, by_va, by_text)
                    if owner and owner not in claimed:
                        claimed.add(owner)
                        mapped += 1
                key = (mapped, labels, len(run))
                if best_key is None or key > best_key:
                    best_key, best = key, (stride, run)
        if best is None:
            raise ValueError("no default high-score table found")
        stride, run = best
        # One adjustment holds one score, so it can own at most one slot.  The
        # co-op / team boards repeat a caption at several menu indents and all
        # of them normalise onto the same adjustment; first (least-indented)
        # record wins, the rest are initials-and-name only.
        claimed = set()
        rows = []
        for i, off in enumerate(run):
            w = struct.unpack_from("<2I", data, off)
            label_va, label = self._slot_label(off, stride)
            rows.append({
                "index": i,
                "offset": off,
                # `label` is the RAW caption and the record's stable key —
                # co-op / team boards repeat the same wording at different
                # menu indents (" COOP HIGH SCORE #3 " vs "  COOP HIGH SCORE
                # #3  "), and that padding is what keeps them distinct.
                # `display` is the tidied version for the UI.
                "label": label or "High score %d" % (i + 1),
                "display": " ".join((label or "High score %d" % (i + 1))
                                    .split()),
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
