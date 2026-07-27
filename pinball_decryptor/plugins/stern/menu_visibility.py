"""Which Spike 2 adjustments the machine's operator menu can actually show.

peanuts asked why settings that read fine in the firmware never appear in the
game menu on a real machine (Mandalorian's ``ALLOW TOPPER CHEATS`` and
``THIS IS THE WAY DEBUG``).  The RE answer, written up in
``plans/spike2_hidden_adjustments_re.md``, is that **nothing marks the
adjustment**: a hidden entry and a visible one are byte-for-byte alike in every
descriptor field (same type, same flags, same label struct).  Visibility is
decided by the MENU.

One firmware routine draws one PAGE of adjustments.  Its loop reaches the
descriptor through a small bounds-checked accessor::

    r0 = section pointer     # [+0]=table  [+4]=count  [+8]=elem
    r1 = id                  # list[i], or first+i when the list arg is NULL
    bl  accessor             # rec = table + elem*id

and its callers describe a page as either a NUL-terminated ``u16`` id list in
``.rodata`` or, when that argument is NULL, the inclusive id range ``r1..r2``.
Every title examined has exactly two adjustment pages — "Standard Adjustments"
(an explicit list of ~100 ids) and "Feature Adjustments" (one contiguous
range).  An adjustment in neither page cannot be reached from the menu.

This module finds those pages generically (no per-title addresses): locate the
section pointer, find the accessor by how often it is called right after the
section pointer is materialised, take the functions that call it as the
adjustment walkers, then recover each caller's arguments by a small backward
constant propagation.

**Refusing to guess** matters more than coverage here: a wrong "Debug" badge on
a real operator setting is worse than no badge.  James Bond 60th (of 14 titles
tested) exposes only its Standard page to this analysis, so :func:`statuses`
requires at least one list page AND at least one range page and returns ``None``
otherwise.
"""
import struct

# Unreachable adjustments come in two very different flavours and must not be
# conflated.  These families are genuine operator settings that simply live on
# another service screen — Guided Setup, the audio page, the volume screen, the
# redemption and tournament menus — rather than in Adjustments.  The names are
# system-side and identical across every title, so recognising them by name is
# safe in a way that guessing at game-specific names would not be.
_SERVICE_PREFIXES = (
    "AD_SOUND_", "AD_SOFTWARE_UPDATE_", "AD_TOURNAMENT_", "AD_REDEMPTION_",
    "AD_TICKET_",
)
_SERVICE_NAMES = frozenset((
    "AD_MUSIC_VOLUME", "AD_SPEAKER_BALANCE", "AD_BACKBOX_SPEAKER_TYPE",
    "AD_CABINET_SPEAKER_TYPE", "AD_COIN_DOOR", "AD_COIN_ACCEPTOR",
    "AD_COIN_DOOR_INTERLOCK_SWITCH_PRESENT", "AD_BILL_VALIDATOR",
    "AD_FAST_SETUP", "AD_HOW_TO_CONNECT_MESSAGE", "AD_KNOCKER_STYLE",
    "AD_COIL_PULSE_POWER", "AD_FLASH_LAMP_POWER", "AD_GAME_ID",
    "AD_LOCATION_ID", "AD_CUSTOM_MESSAGE",
))

VISIBLE, SERVICE, DEBUG = "", "service", "debug"

# ARM encodings the argument recovery understands.
_MOVW = 0x03000000
_MOVT = 0x03400000
_MOV_IMM = 0x03A00000
_LDR_PC = 0x059F0000
_MOV_REG = 0x01A00000
_BL = 0x0B000000
_PUSH_LR = 0xE92D4000
_STR_LR = 0xE52DE004
_BX_LR = 0x012FFF1E

_MAX_LIST = 600            # a page id list longer than this is not a page
_MIN_LIST = 5              # ...and a shorter one is some other small array
_MIN_RANGE = 4


def _kind(name):
    if name in _SERVICE_NAMES or name.startswith(_SERVICE_PREFIXES):
        return SERVICE
    return DEBUG


class MenuVisibility(object):
    """Operator-menu pages of an :class:`~.adjustments.AdjustmentTable`."""

    def __init__(self, table):
        self.t = table
        self.data = table.data
        self.text = table._loads[0]          # (file_off, vaddr, filesz)
        self._consts = None                  # {address: [(off, rd), ...]}
        self._bls = None                     # {target va: [file offs]}

    # ---- one pass over .text -------------------------------------------
    def _scan(self):
        """Materialised ``movw``/``movt`` addresses and every ``bl`` target.

        Both are needed for the whole hunt, and the text segment is up to
        ~190 MB on the biggest titles, so they are collected in a single pass
        over a cast memoryview rather than a ``struct.unpack_from`` per word.
        """
        if self._consts is not None:
            return
        po, _pv, fsz = self.text
        base = (po + 3) & ~3
        n = (po + fsz - base) // 4
        words = memoryview(self.data)[base:base + n * 4].cast("I")
        consts, bls, last = {}, {}, {}
        for j in range(n):
            w = words[j]
            op = w & 0x0FF00000
            if op == _MOVW:
                last[(w >> 12) & 0xF] = (j, ((w >> 16) & 0xF) << 12 | (w & 0xFFF))
            elif op == _MOVT:
                rd = (w >> 12) & 0xF
                prev = last.get(rd)
                if prev is not None and j - prev[0] <= 16:
                    hi = ((w >> 16) & 0xF) << 12 | (w & 0xFFF)
                    consts.setdefault((hi << 16) | prev[1], []).append(
                        (base + 4 * j, rd))
            elif (w & 0x0F000000) == _BL:
                imm = w & 0xFFFFFF
                if imm & 0x800000:
                    imm -= 0x1000000
                off = base + 4 * j
                bls.setdefault(self.t._va(off) + 8 + imm * 4, []).append(off)
        self._consts, self._bls = consts, bls

    # ---- small helpers --------------------------------------------------
    def _bl_target(self, off):
        w = struct.unpack_from("<I", self.data, off)[0]
        if (w & 0x0F000000) != _BL:
            return None
        imm = w & 0xFFFFFF
        if imm & 0x800000:
            imm -= 0x1000000
        return self.t._va(off) + 8 + imm * 4

    def _func_start(self, off, limit=4000):
        """Walk back to the enclosing prologue."""
        for k in range(limit):
            w = struct.unpack_from("<I", self.data, off - 4 * k)[0]
            if (w & 0xFFFF4000) == _PUSH_LR and (w & 0x0FFF0000) == 0x092D0000:
                return self.t._va(off - 4 * k)
            if w == _STR_LR:
                return self.t._va(off - 4 * k)
        return None

    def _trivial_getter(self, va):
        """``movw r0 / movt r0 / bx lr`` -> the constant it returns, else None.

        The Standard page's id list reaches its call site through exactly such
        a getter on several titles, so the argument recovery has to see through
        one level of call.
        """
        if va is None:
            return None
        off = self.t._off(va)
        if off is None or off + 12 > len(self.data):
            return None
        w0, w1, w2 = struct.unpack_from("<3I", self.data, off)
        if (w0 & 0x0FF0F000) != _MOVW or (w1 & 0x0FF0F000) != _MOVT:
            return None
        if (w2 & 0x0FFFFFFF) != _BX_LR:
            return None
        lo = ((w0 >> 16) & 0xF) << 12 | (w0 & 0xFFF)
        hi = ((w1 >> 16) & 0xF) << 12 | (w1 & 0xFFF)
        return (hi << 16) | lo

    def _args(self, call_off, back=40):
        """``{reg: value}`` for r0..r3 at a call site, best effort.

        Only the forms the compiler actually uses to set up a page call are
        modelled; anything else drops the register so an unknown value can
        never be mistaken for a real argument.
        """
        r = {}
        for k in range(back, 0, -1):
            off = call_off - 4 * k
            if off < 0:
                continue
            w = struct.unpack_from("<I", self.data, off)[0]
            if w >> 28 != 0xE:                     # conditional -> ignore
                continue
            op = w & 0x0FF00000
            rd = (w >> 12) & 0xF
            if op == _MOVW:
                r[rd] = ((w >> 16) & 0xF) << 12 | (w & 0xFFF)
            elif op == _MOVT:
                imm = ((w >> 16) & 0xF) << 12 | (w & 0xFFF)
                r[rd] = (r.get(rd, 0) & 0xFFFF) | (imm << 16)
            elif op == _MOV_IMM:
                imm, rot = w & 0xFF, ((w >> 8) & 0xF) * 2
                r[rd] = (((imm >> rot) | (imm << (32 - rot))) & 0xFFFFFFFF
                         if rot else imm)
            elif (w & 0x0FFF0000) == _LDR_PC:
                lit = self.t._off(self.t._va(off) + 8 + (w & 0xFFF))
                if lit is None:
                    r.pop(rd, None)
                else:
                    r[rd] = struct.unpack_from("<I", self.data, lit)[0]
            elif (w & 0x0FEF0FF0) == _MOV_REG:
                rm = w & 0xF
                if rm in r:
                    r[rd] = r[rm]
                else:
                    r.pop(rd, None)
            elif (w & 0x0F000000) == _BL:
                got = self._trivial_getter(self._bl_target(off))
                if got is None:
                    r.pop(0, None)
                else:
                    r[0] = got
                for scratch in (1, 2, 3, 12):
                    r.pop(scratch, None)
            elif (w & 0x0C000000) == 0x00000000:
                # Some other data-processing form.  TST/TEQ/CMP/CMN write no
                # register; everything else makes rd unknown.  (Getting this
                # wrong the other way matters: the stores that spill the stack
                # arguments of a page call sit between the ``mov``s and the
                # ``bl``, and treating their source register as a destination
                # threw away the r0 = 0 that marks a range page.)
                if (w >> 21) & 0xF not in (0x8, 0x9, 0xA, 0xB):
                    r.pop(rd, None)
            elif (w & 0x0C100000) == 0x04100000:        # ldr/ldrb rd, [...]
                r.pop(rd, None)
            elif (w & 0x0E100000) == 0x08100000:        # ldm {...}
                for reg in (0, 1, 2, 3):
                    if w >> reg & 1:
                        r.pop(reg, None)
        return r

    def _id_list(self, va):
        """A NUL-terminated ``u16`` list of valid adjustment ids, or None."""
        off = self.t._off(va)
        if off is None:
            return None
        ids = []
        while len(ids) < _MAX_LIST:
            if off + 2 > len(self.data):
                return None
            v = struct.unpack_from("<H", self.data, off)[0]
            if v == 0:
                break
            if not 0 < v < self.t.count:
                return None
            ids.append(v)
            off += 2
        return ids or None

    # ---- the hunt -------------------------------------------------------
    def pages(self):
        """``[(kind, [ids])]`` for every adjustment page the menu can draw."""
        rec = getattr(self.t, "record_va", None)
        if rec is None:
            return []
        self._scan()
        sites = [o for o, rd in self._consts.get(rec + 4, []) if rd == 0]
        if not sites:
            return []
        # The accessor is whatever those sites call immediately afterwards.
        calls = {}
        for off in sites:
            for k in (1, 2, 3):
                tgt = self._bl_target(off + 4 * k)
                if tgt is not None:
                    calls[tgt] = calls.get(tgt, 0) + 1
                    break
        if not calls:
            return []
        accessor = max(calls, key=calls.get)
        walkers = set()
        for off in sites:
            for k in (1, 2, 3):
                if self._bl_target(off + 4 * k) == accessor:
                    start = self._func_start(off)
                    if start is not None:
                        walkers.add(start)
                    break
        out = []
        for fn in walkers:
            for call in self._bls.get(fn, ()):
                a = self._args(call)
                r0, r1, r2 = a.get(0), a.get(1), a.get(2)
                if r0:
                    ids = self._id_list(r0)
                    if ids and len(ids) >= _MIN_LIST:
                        out.append(("list", ids))
                elif r0 == 0 and r1 is not None and r2 is not None \
                        and 0 < r1 <= r2 < self.t.count \
                        and r2 - r1 >= _MIN_RANGE:
                    out.append(("range", list(range(r1, r2 + 1))))
        return out

    def visible(self):
        """The set of menu-reachable ids, or ``None`` if it can't be trusted.

        Both page shapes must be present.  A title that yields only one of them
        (James Bond 60th) has not been fully read, and its complement would
        wrongly condemn most of the game's own settings.
        """
        pages = self.pages()
        kinds = {k for k, _ids in pages}
        if not {"list", "range"} <= kinds:
            return None
        ids = set()
        for _kind, page in pages:
            ids |= set(page)
        return ids


def statuses(table):
    """``{id: VISIBLE | SERVICE | DEBUG}``, or ``None`` if unreadable.

    ``SERVICE`` is an adjustment the operator can still change, just from
    another service-menu screen; ``DEBUG`` is one no menu reaches at all.
    """
    try:
        vis = MenuVisibility(table).visible()
    except Exception:
        return None
    if vis is None:
        return None
    out = {}
    for i in range(table.count):
        name = table.names[i] or ""
        out[i] = VISIBLE if i in vis else _kind(name)
    return out
