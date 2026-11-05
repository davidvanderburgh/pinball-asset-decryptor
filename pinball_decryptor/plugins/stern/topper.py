"""Topper-gated features without the topper (PAD-1010).

Some Stern Spike 2 titles gate an extra software feature on the topper
accessory being fitted.  Venom's Ghost Rider host on the character-select
screen is the headline example (the ticket): buy the $1999 topper and an eighth
host appears; without it the game offers seven.  The game decides the topper is
present with a tiny predicate - ``device_usable(<topper device>)`` - and only
then offers the feature.

HOW THE GATE LOOKS.  Every title carries a ``device_usable(index)`` accessor of
one shape (Venom LE 0x444800)::

    subs r2, r0, #0            ; the device index
    beq  <absent>
    movw/movt r3, <count var>
    ldr  r3, [r3]
    cmp  r2, r3
    blo  <check>
    mov  r0, #0 ; bx lr        ; out of range -> absent
    b    <board status>        ; present iff that board answered on the bus

and, per topper-gated feature, a thin wrapper that asks it about the topper
(Venom's Ghost Rider check, 0x1acc44)::

    mov r0, #<topper index> ; mov r1, #0 ; b/bl device_usable

The topper device is the one whose device-table record names it ``...TOPPER...``
(Venom: device 9 -> node 12 "TOPPER").  The device table is found from the
``get_board`` tail the accessor itself reaches::

    movw/movt r3, <table ptr> ; ldr r3, [r3] ; add r0, r3, r0, lsl #4

each 16-byte record carrying its node at +0xe and a name cell at +8.

The predicate reaches the topper two ways, and they are patched differently:

* a thin standalone wrapper that TAIL-calls it (``...; b device_usable``, Venom's
  Ghost Rider check): rewritten to ``mov r0, #1 ; bx lr`` so it returns
  "present";
* an INLINE call (``...; bl device_usable ; cmp r0, #0 ; ...``, Jaws' challenge
  gate): only the ``bl`` becomes ``mov r0, #1``, so the code that follows reads
  the topper as present.  Writing ``bx lr`` here would return from the middle of
  the feature's own function, so the two forms are never patched alike.

THE PATCH.  :func:`patched_bytes` makes the feature's gate always see the topper,
so the extra character/mode is available on a cabinet that has none.  Only the
gameplay predicate changes: the node-board health layer still reads the real
bus, so a cabinet without the topper drives nothing and raises no node-board
error (the topper boards are optional, flags bit 2 - see PAD-498).  Size
neutral; every site is checked against its expected words.

The gate is found generically (no per-title addresses), but the box is OFFERED
only on the games below, each proven on the emulator that flipping this gate
frees the feature named.  The reason is that the same topper-present predicate
is used two ways across the library: on Venom it gates whether the Ghost Rider
host is offered (flipping it unlocks the host), but on Jaws the matching call
only gates the topper's own DISPLAY while the challenge itself is unlocked by
in-play progress - so flipping it there frees nothing and the box must not
pretend otherwise.  A title joins :data:`FEATURES` once it has been checked,
and never before.
"""
import struct

from .coin_door import _Elf

_MOV_R0_1 = 0xE3A00001          # mov r0, #1
_BX_LR = 0xE12FFF1E             # bx lr

#: ``game program directory -> what the topper adds that this unlock frees``.  Only games where the topper-present
#: gate IS the feature's gate (so flipping it to "present" makes the feature available without the topper), each
#: confirmed on the emulator.  Keyed by the game program's own directory name (``venom_le``...), which the caller
#: takes from its firmware path.  Games whose topper content is gated another way (Jaws / John Wick's challenges,
#: unlocked by in-play progress; the many light-only and motor toppers) are deliberately absent.
FEATURES = {
    "venom_le": "the Ghost Rider host on the character-select screen",
    "venom_pro": "the Ghost Rider host on the character-select screen",
}


def _imm16(x):
    return ((x >> 4) & 0xF000) | (x & 0xFFF)


def _words(elf):
    off, va, fsz = elf.text
    n = fsz // 4
    return va, struct.unpack_from("<%dI" % n, elf.b, off), n


def _bl_target(va, w):
    """The target of a ``b``/``bl`` (cond AL) at *va*, else None."""
    if (w & 0x0E000000) != 0x0A000000 or (w >> 28) != 0xE:
        return None
    off = w & 0xFFFFFF
    if off & 0x800000:
        off -= 1 << 24
    return va + 8 + off * 4


def _find_device_usable(w, base, n):
    """Every ``device_usable`` accessor address by its shape (see the module doc)."""
    out = []
    for i in range(n - 9):
        if (w[i] == 0xE2502000                                   # subs r2, r0, #0
                and (w[i + 1] & 0xFF000000) == 0x0A000000        # beq
                and (w[i + 2] & 0xFFF0F000) == 0xE3003000        # movw r3, count
                and (w[i + 3] & 0xFFF0F000) == 0xE3403000        # movt r3, count
                and w[i + 4] == 0xE5933000                       # ldr r3, [r3]
                and w[i + 5] == 0xE1520003                       # cmp r2, r3
                and (w[i + 6] & 0xFF000000) == 0x3A000000        # blo
                and w[i + 7] == 0xE3A00000                       # mov r0, #0
                and w[i + 8] == 0xE12FFF1E                       # bx lr
                and (w[i + 9] & 0xFF000000) == 0xEA000000):      # b <board status>
            out.append((base + 4 * i, _bl_target(base + 4 * i + 36, w[i + 9])))
    return out


def _at(w, base, n, va):
    i = (va - base) // 4
    return w[i] if 0 <= i < n else None


def _device_table(elf, w, base, n, board_check):
    """The device table's base address, reached from *board_check* (the accessor's tail): its first ``bl`` is
    ``get_board``, whose ``movw/movt r3, <tbl ptr> ; ldr r3, [r3] ; add r0, r3, r0, lsl #4`` names the pointer."""
    get_board = None
    for k in range(0, 12):
        x = _at(w, base, n, board_check + 4 * k)
        if x is None:
            break
        if (x & 0x0F000000) == 0x0B000000 and (x >> 28) == 0xE:
            get_board = _bl_target(board_check + 4 * k, x)
            break
    if get_board is None:
        return None
    for k in range(0, 24):
        a = get_board + 4 * k
        x0, x1, x2, x3 = (_at(w, base, n, a + 4 * j) for j in range(4))
        if (x0 is not None and (x0 & 0xFFF0F000) == 0xE3003000 and x1 is not None
                and (x1 & 0xFFF0F000) == 0xE3403000 and x2 == 0xE5933000 and x3 == 0xE0830200):
            ptr = _imm16(x0) | (_imm16(x1) << 16)
            o = elf.off(ptr)
            if o is None:
                return None
            tbl = struct.unpack_from("<I", elf.b, o)[0]
            return tbl if elf.off(tbl) is not None else None
    return None


def _device_name(elf, table, idx):
    """The English name of device *idx* (record +8 -> name cell -> first language string)."""
    rec = elf.off(table + 16 * idx)
    if rec is None:
        return None
    cell = struct.unpack_from("<I", elf.b, rec + 8)[0]
    o = elf.off(cell)
    if o is None:
        return None
    return elf.cstr(struct.unpack_from("<I", elf.b, o)[0])


#: Topper SUB-devices whose presence check drives hardware, not a feature: a cabinet without the topper must never
#: be told these are fitted (a motor would home against a switch that never comes; see King Kong's "Cannot detect
#: Topper Kong Mechanism").  The feature gate is always the MAIN topper board ("TOPPER", "Topper 1", "R2-D2 Topper").
_SUBDEVICE = ("MOTOR", "STEPPER", "MECH", "WHEEL", "OPTO", "LIGHT", " EYE", " GI")


def _is_main_topper(name):
    u = (name or "").upper()
    return "TOPPER" in u and not any(s in u for s in _SUBDEVICE)


def _gates(w, base, n, usables):
    """``[(va, idx, link)]`` for every ``mov r0, #idx ; mov r1, #k ; b/bl device_usable`` gate: *va* is the first
    word, *link* True for an inline ``bl`` call, False for a tail-call ``b`` wrapper."""
    tgts = {u for u, _b in usables}
    out = []
    for i in range(n - 2):
        if (w[i] & 0xFFFFF000) == 0xE3A00000 and ((w[i] >> 12) & 0xF) == 0 \
                and (w[i + 1] & 0xFFFFF000) == 0xE3A01000:
            x = w[i + 2]
            if (x & 0x0E000000) != 0x0A000000 or (x >> 28) != 0xE:
                continue
            if _bl_target(base + 4 * (i + 2), x) in tgts:
                out.append((base + 4 * i, w[i] & 0xFF, bool((x >> 24) & 1)))
    return out


def _find(elf_bytes):
    """``{"sites": [(va, old word, new word)], "devices": [names]}`` for a build whose game code asks whether the
    topper is present through the device_usable shape, else None.  Title-agnostic: finding the gate does not mean
    flipping it frees a feature - see :data:`FEATURES` and :func:`plan`."""
    try:
        elf = _Elf(elf_bytes)
    except (ValueError, struct.error):
        return None
    base, w, n = _words(elf)
    usables = _find_device_usable(w, base, n)
    if not usables:
        return None
    board_of = {u: b for u, b in usables}
    # the device table each accessor reaches (they share get_board; take the first that resolves)
    table = None
    for u, b in usables:
        if b is not None:
            table = _device_table(elf, w, base, n, b)
            if table:
                break
    if table is None:
        return None
    sites, devices = [], []
    for va, idx, link in _gates(w, base, n, usables):
        name = _device_name(elf, table, idx)
        if not _is_main_topper(name):
            continue
        if link:
            # inline `bl device_usable`: make the call itself yield "present", leaving the function's flow intact
            sites.append((va + 8, _at(w, base, n, va + 8), _MOV_R0_1))
        else:
            # tail-call wrapper `b device_usable`: it IS the predicate - return "present"
            sites.append((va, _at(w, base, n, va), _MOV_R0_1))
            sites.append((va + 4, _at(w, base, n, va + 4), _BX_LR))
        devices.append(name)
    if not sites:
        return None
    return {"sites": sites, "devices": devices}


def plan(elf_bytes, title=None):
    """The unlock for *title* (its game program directory name), or None.  Offered only on the games in
    :data:`FEATURES`, each confirmed that flipping the gate frees the named feature; the result carries that
    ``feature`` text for the box.  A game not in the table is offered nothing even when :func:`_find` locates a
    topper gate in it."""
    feature = FEATURES.get(title)
    if feature is None:
        return None
    p = _find(elf_bytes)
    if not p:
        return None
    p["feature"] = feature
    return p


def patched_bytes(elf_bytes, p=None):
    """*elf_bytes* with every topper-present predicate rewritten to report the topper present (see the module
    doc).  Same size; every site must hold its expected word."""
    p = p or _find(elf_bytes)
    if not p:
        raise ValueError("this build has no topper-gated feature this app can unlock")
    elf = _Elf(elf_bytes)
    out = bytearray(elf_bytes)
    for va, old, new in p["sites"]:
        o = elf.off(va)
        if o is None or struct.unpack_from("<I", out, o)[0] != old:
            raise ValueError("the topper patch site at 0x%x is not what was planned" % va)
        struct.pack_into("<I", out, o, new)
    return bytes(out)
