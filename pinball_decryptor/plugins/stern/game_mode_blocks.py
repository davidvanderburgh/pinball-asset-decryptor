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
so a refused one could strand them. Ids from 32 up are left out (the runtime's masks are 32 bits).
"""

from dataclasses import dataclass

#: a start whose entry words load a literal cannot carry the runtime's veto (it moves the two words)
_LITERAL = (0x0F7F0000, 0x051F0000)


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
        return (not self.multiball and 0 <= self.id < 32 and self.start and self.words[0] is not None
                and not any((w & _LITERAL[0]) == _LITERAL[1] for w in self.words))


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
    return out


def _word(prog, va):
    try:
        return prog.word(va)
    except Exception:                                    # noqa: BLE001 - outside the program's loads
        return None


def port_lines(modes, defaults=(), header=None):
    """The port's block section (lines) for *modes*; *defaults* = the ids a mode blocks when it lists none
    (only modes checked on that title)."""
    out = ["# PAD-363: the game's own modes a mode of ours may keep from starting (game_mode_blocks.py, from the",
           "# game program: each mode's start = its vtable + 8 + 4 * the title's start slot). Never a multiball."]
    if header:
        out += ["# " + h for h in header]
    mask = 0
    for m in modes:
        if not m.blockable:
            continue
        out.append("site block_start_%-6d 0x%08x 0x%08x 0x%08x" % (m.id, m.start, m.words[0], m.words[1]))
        out.append("data block_obj_%-8d 0x%08x" % (m.id, m.obj))
        out.append("text block_name_%-7d %s" % (m.id, m.name))
        if m.id in defaults:
            mask |= 1 << m.id
    out.append("value block_default         0x%08x" % mask)
    return out
