"""Give a Spike 2 Home Edition its coin door back (PAD-755).

A Pinside user asked for "adding coin door to the game [that] did not have it
but [it is] still on the node board and can be installed".  The Spike 2 builds
that ship without a coin door are the Home Editions (Jurassic Park The Pin
1.05, Star Wars Home 1.10).  Their game program still lists the door's
interlock switch (``Coin Door Power Interlock``, cabinet node 0 bit 23, beside
the four service buttons) and still carries the code that handles it, but
nothing connects the two, so a door wired to that input does nothing: on the
emulator a Pro shows ``48V DISABLED / CLOSE COIN DOOR`` the moment the door
opens, and the Home Edition carries on.

HOW A CABINET SWITCH REACHES ITS CODE.  Every switch device record carries a
link byte, ``0x80 | n``, naming record *n* of the dedicated-switch handler
table (32-byte records, the first one is number 1)::

    +0  handler (0 = none)   +4  argument     +8  name cell
    +12 mask                 +16 debounce ms  +20 key (dedicated no. << 16 | 5)
    +24 board << 24 | n << 16 | 0x4d          +28 board

The Service Select device links ``0x98`` -> record 24, ``SELECT``; on a Pro
the interlock links ``0x94`` -> record 20, ``COIN DOOR INTERLOCK`` (key 0x79),
whose handler reads the door and raises the 48V message.  A Home Edition keeps
record 20 as an empty ``DEDICATED SW. #20`` (no handler, its mask cut to
``0x04000000``, board 0) and the interlock's link byte at 0: both ends cut.
The handler itself is platform code and is still in the program: the routine
that, when the build says a door is fitted, forces the ``COIN DOOR INTERLOCK
SW PRESENT`` setting on and then reads the switch.

:func:`plan` finds all three generically (names, record shape and that
setting's id; no per-title addresses) and :func:`patched_bytes` restores the
Pro's link: the device's link byte, and record 20's handler, mask and board
(the mask and board copied from the build's own live SELECT record).  Nothing
moves and the file keeps its size.

It is a choice, never automatic: a machine with no door fitted has nothing on
that input, the game then reads the door as OPEN all the time and puts up the
48V message, exactly as a Pro with its interlock unplugged does.
"""
import struct

DEVICE_NAME = "Coin Door Power Interlock"
ADJUSTMENT = "AD_COIN_DOOR_INTERLOCK_SWITCH_PRESENT"
LINKED = 0x80
INTERLOCK_RECORD = 20          # the Pros' COIN DOOR INTERLOCK record
INTERLOCK_KEY = 0x00790005     # ...and its dedicated-switch key
SELECT_NAME = "Service Select"
SELECT_RECORD_NAME = "SELECT"
REC = 32

FITTED, MISSING = "fitted", "missing"


class _Elf:
    def __init__(self, data):
        self.b = bytes(data)
        b = self.b
        if b[:4] != b"\x7fELF":
            raise ValueError("not an ELF")
        phoff = struct.unpack_from("<I", b, 0x1C)[0]
        phent, phnum = struct.unpack_from("<HH", b, 0x2A)
        self.loads = []
        for i in range(phnum):
            typ, off, va, _pa, fsz = struct.unpack_from("<5I", b, phoff + i * phent)
            if typ == 1:
                self.loads.append((off, va, fsz))
        if not self.loads:
            raise ValueError("no LOAD segments")
        self.text = self.loads[0]

    def off(self, va):
        for o, v, f in self.loads:
            if v <= va < v + f:
                return o + va - v
        return None

    def va(self, off):
        for o, v, f in self.loads:
            if o <= off < o + f:
                return v + off - o
        return None

    def word(self, va):
        o = self.off(va)
        if o is None or o + 4 > len(self.b):
            return None
        return struct.unpack_from("<I", self.b, o)[0]

    def in_text(self, va):
        o, v, f = self.text
        return v <= va < v + f

    def cstr(self, va, cap=64):
        o = self.off(va) if va else None
        if o is None:
            return None
        e = self.b.find(b"\0", o, o + cap)
        if e <= o:
            return None
        s = self.b[o:e]
        return s.decode("latin1") if all(0x20 <= c < 0x7F for c in s) else None

    def word_refs(self, value, data_only=True):
        """VAs of aligned words equal to *value* (outside .text by default)."""
        p = struct.pack("<I", value)
        out, i = [], self.b.find(p)
        while i >= 0:
            if i % 4 == 0:
                v = self.va(i)
                if v is not None and not (data_only and self.in_text(v)):
                    out.append(v)
            i = self.b.find(p, i + 1)
        return out

    def cells(self, text):
        """Name cells (an array of per-language string pointers, English first)
        whose English string is exactly *text*.  The linker merges a string
        into the tail of a longer one ("SELECT" inside "... SELECT"), so every
        occurrence is a candidate start, not only those after a NUL."""
        needle = text.encode("latin1") + b"\0"
        out, i = [], self.b.find(needle)
        while i >= 0:
            sva = self.va(i)
            if sva is not None:
                out.extend(self.word_refs(sva))
            i = self.b.find(needle, i + 1)
        return out


def _devices(elf, name):
    """``[(link VA, link byte)]`` for the switch devices named *name*: the
    record holds the name cell, and the link byte is 8 bytes before it."""
    out = []
    for cell in elf.cells(name):
        for ref in elf.word_refs(cell):
            o = elf.off(ref - 8)
            if o is not None:
                out.append((ref - 8, elf.b[o]))
    return out


def _record(elf, va):
    o = elf.off(va)
    if o is None or o + REC > len(elf.b):
        return None
    return list(struct.unpack_from("<8I", elf.b, o))


def _is_record(w, n):
    return (w is not None and (w[5] & 0xFFFF) == 5 and (w[6] & 0xFFFF) == 0x4D
            and (w[6] >> 16) & 0xFF == n)


def _table_base(elf):
    """VA of handler record 1, found from the build's own Service Select: its
    link byte names its record, and that record must be the one named SELECT
    with the record shape above."""
    sel_cells = set(elf.cells(SELECT_RECORD_NAME))
    for link_va, link in _devices(elf, SELECT_NAME):
        if not link & LINKED:
            continue
        n = link & 0x7F
        for cell in sel_cells:
            for ref in elf.word_refs(cell):
                rva = ref - 8
                w = _record(elf, rva)
                if _is_record(w, n) and w[0] and elf.in_text(w[0]):
                    return rva - REC * (n - 1), w
    return None, None


def _handler(elf_bytes, table):
    """The interlock handler: the function that reads the coin-door setting,
    sets it to 1 when it isn't, and branches on a byte flag first (the Pros'
    record 20 handler; a twin reading a halfword flag is never called by any
    record).  Its entry is the ``movw``/``movt`` the compiler hoisted above the
    ``push``."""
    from . import stock_scan as S
    idx = table.by_name.get(ADJUSTMENT)
    if idx is None:
        return None
    prog = S.Program(elf_bytes)
    get_adj, _at = S.find_get_adjustment(prog)
    if get_adj is None:
        return None
    found = set()
    for site in prog.callers(get_adj):
        if prog.const_before(site, 0) != idx:
            continue
        start = prog.func_start(site)
        if start is None:
            continue
        # it sets the setting to 1 right after reading it
        sets = False
        for k in range(1, 8):
            nxt = site + 4 * k
            w = prog.word(nxt)
            if w is not None and (w & 0x0F000000) == 0x0B000000 \
                    and prog.const_before(nxt, 0) == idx \
                    and prog.const_before(nxt, 1) == 1:
                sets = True
                break
        if not sets:
            continue
        # the hoisted movw/movt of the flag's address, the ldrb that reads it
        mw, mt = prog.word(start - 8), prog.word(start - 4)
        if mw is None or mt is None:
            continue
        if (mw & 0x0FF00000) != 0x03000000 or (mt & 0x0FF00000) != 0x03400000:
            continue
        rd = (mw >> 12) & 0xF
        if (mt >> 12) & 0xF != rd:
            continue
        flag_byte = False
        for k in range(0, 6):
            w = prog.word(start + 4 * k)
            # ldrb rd, [rd]  (cond AL, P=1 U=1 B=1 W=0 L=1, imm 0)
            if w is not None and (w & 0x0FFF0FFF) == (0x05D00000 | rd << 16) \
                    and ((w >> 12) & 0xF) == rd:
                flag_byte = True
                break
        if flag_byte:
            found.add(start - 8)
    return found.pop() if len(found) == 1 else None


def plan(elf_bytes, table=None):
    """What this build's coin door is: ``{"state": "fitted"}`` for a build that
    handles its interlock (every Pro/Premium/LE), ``{"state": "missing", ...}``
    with everything :func:`patched_bytes` writes for one that can be given it,
    or None when the build can't be read with certainty (nothing is offered)."""
    try:
        elf = _Elf(elf_bytes)
    except (ValueError, struct.error):
        return None
    devs = _devices(elf, DEVICE_NAME)
    if len(devs) != 1:
        return None
    link_va, link = devs[0]
    base, sel = _table_base(elf)
    if base is None:
        return None
    rva = base + REC * (INTERLOCK_RECORD - 1)
    w = _record(elf, rva)
    if not _is_record(w, INTERLOCK_RECORD) or w[5] != INTERLOCK_KEY:
        return None
    if link == (LINKED | INTERLOCK_RECORD) and w[0] and elf.in_text(w[0]):
        return {"state": FITTED, "handler": w[0]}
    if link != 0 or w[0] != 0:
        return None                     # half-wired: not a shape we know
    if table is None:
        from .adjustments import AdjustmentTable
        table = AdjustmentTable(elf_bytes)
    fn = _handler(elf_bytes, table)
    if fn is None:
        return None
    board = sel[7]
    return {"state": MISSING, "link_va": link_va, "record_va": rva,
            "handler": fn, "mask": sel[3], "board": board,
            "flags": (board << 24) | (INTERLOCK_RECORD << 16) | 0x4D}


def patched_bytes(elf_bytes, p):
    """*elf_bytes* with the coin door's interlock linked to its handler, as on
    the Pros; *p* is a ``missing`` :func:`plan`.  Same size; re-read to check."""
    if not p or p.get("state") != MISSING:
        raise ValueError("this build has no coin door to fit")
    elf = _Elf(elf_bytes)
    out = bytearray(elf_bytes)
    out[elf.off(p["link_va"])] = LINKED | INTERLOCK_RECORD
    ro = elf.off(p["record_va"])
    struct.pack_into("<I", out, ro + 0, p["handler"])
    struct.pack_into("<I", out, ro + 12, p["mask"])
    struct.pack_into("<I", out, ro + 24, p["flags"])
    struct.pack_into("<I", out, ro + 28, p["board"])
    after = plan(bytes(out))
    if not after or after["state"] != FITTED or after["handler"] != p["handler"]:
        raise ValueError("the coin door patch did not read back")
    return bytes(out)
