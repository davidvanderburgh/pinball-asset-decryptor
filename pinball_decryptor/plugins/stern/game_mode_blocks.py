"""The game's own modes a mode of ours may keep from starting (PAD-363), read from the game program.

A rule of the game's starts one of its modes by calling the mode's START: a virtual of the mode object at
the title's start slot (Godzilla 8, Deadpool 13; the vptr is the vtable + 8). The app's stock scanner
(:mod:`.stock_scan_cpp`) already finds the slot, every mode's id, class, readable name, static object and
vtable. From that, each mode gets one veto site in the title's port:

    site block_start_<id>   <the mode's start>  <its two entry words>
    data block_obj_<id>     <the mode's object>
    text block_name_<id>    <its name>

The runtime hooks each named start and refuses it, while a mode of ours that asked runs, for the objects
that mode listed (`pm_block_list`, a mode file's `block_modes`) or the port's checked defaults (`value
block_default`). A MULTIBALL is never written: balls sit in a lock or on a magnet while it starts (PAD-353),
so a refused one could strand them. Ids from 128 up are left out (the runtime's masks are 128 bits), and so is a
start whose first two words cannot be moved into the veto's trampoline (:func:`movable`).
"""

from dataclasses import dataclass

#: the game's mode ids the runtime can hold off (pad_mode_runtime.c BLOCK_IDS)
MAX_ID = 128


def movable(words):
    """The veto moves a start's first two words into its trampoline and runs them there: neither may read or
    write the pc (a branch, a literal load, an add from pc, a pop into pc), and the first may not end the
    function (the second would be the next function's)."""
    if len(words) != 2 or any(w is None for w in words):
        return False
    for i, w in enumerate(words):
        cond, cls = w >> 28, (w >> 25) & 7
        if cond == 0xF or cls == 5:                       # unconditional space; b / bl
            return False
        if w & 0x0FFFFFF0 == 0x012FFF10 or w & 0x0FFFFFF0 == 0x012FFF30:   # bx / blx register
            if i == 0 or w & 0x20:
                return False
            continue                                      # a bx lr as the second word: a two-word function
        if w & 0x0FFF0000 == 0x03200000:                  # nop and the other hints
            continue
        if cls in (0, 1, 2, 3):                           # data processing, load / store
            rn, rd = (w >> 16) & 0xF, (w >> 12) & 0xF
            if w & 0x0FB00000 == 0x03000000:              # movw / movt: bits 16-19 are the immediate's
                rn = 0
            if rn == 15 or rd == 15:
                return False
            if cls == 0 and (w & 0xF) == 15:
                return False
        if cls == 4 and ((w >> 16) & 0xF == 15 or (w & 0x00108000) == 0x00108000):   # ldm into pc / from pc
            return False
    return True


@dataclass
class GameMode:
    id: int
    cls: str
    name: str
    obj: int
    vtable: int
    start: int
    words: tuple
    multiball: bool

    @property
    def blockable(self):
        return not self.multiball and 0 <= self.id < MAX_ID and bool(self.start) and movable(self.words)


def read_modes(elf):
    """[:class:`GameMode`] of a C++ rule title's program (bytes), in id order. Raises
    :class:`.stock_scan.ScanError` when the program has no C++ mode manager."""
    from . import stock_scan as S
    from . import stock_scan_cpp as C
    prog = S.Program(elf)
    model = S.class_model(prog)
    if not C.family(model):
        raise S.ScanError("no C++ rule manager in this game program")
    reading = C.read(prog, model)
    slot = reading.engine.get("start_slot")
    if slot is None:
        raise S.ScanError("the scanner found no start slot in this game program")
    out = []
    for m in sorted(reading.modes, key=lambda m: m.id):
        start = _word(prog, m.vtable + 8 + 4 * int(slot)) if m.vtable else None
        words = (_word(prog, start), _word(prog, start + 4)) if start else (None, None)
        out.append(GameMode(m.id, m.cls, m.name, m.obj or 0, m.vtable or 0, start or 0, words,
                            bool(S.derives(model, m.cls, "cmode_mball"))))
    # a mode outside the game's own table gets the scanner's stand-in id (1000 up: Deadpool's Battle
    # Juggernaut, Jaws's Jaws and Encounter); in the port an id is only a label, so it takes the highest
    # one free, in the stand-ins' order (the same on every run of the same program)
    used = {m.id for m in out if 0 <= m.id < MAX_ID}
    free = [i for i in range(MAX_ID - 1, -1, -1) if i not in used]
    for m in sorted((m for m in out if m.id >= MAX_ID), key=lambda m: m.id):
        if free:
            m.id = free.pop(0)
    return sorted(out, key=lambda m: m.id)


def _word(prog, va):
    try:
        return prog.word(va)
    except Exception:                                    # noqa: BLE001 - outside the program's loads
        return None


def port_lines(modes, defaults=(), header=None):
    """The port's block section (lines) for *modes*; *defaults* = the ids a mode blocks when it lists none
    (only modes checked on that title), as `text block_default <ids>`."""
    out = ["# PAD-363: the game's own modes a mode of ours may keep from starting (game_mode_blocks.py, from the",
           "# game program: each mode's start = its vtable + 8 + 4 * the title's start slot). Never a multiball."]
    if header:
        out += ["# " + h for h in header]
    on = []
    for m in modes:
        if not m.blockable:
            continue
        out.append("site block_start_%-6d 0x%08x 0x%08x 0x%08x" % (m.id, m.start, m.words[0], m.words[1]))
        if m.obj:
            out.append("data block_obj_%-8d 0x%08x" % (m.id, m.obj))
        out.append("text block_name_%-7d %s" % (m.id, m.name))
        if m.id in defaults:
            on.append(m.id)
    if on:
        out.append("text block_default          %s" % " ".join(str(i) for i in on))
    return out
