"""Which of the game's LIGHT SHOWS each of its modes starts, read off the game program (PAD-1475).

A Bond LE owner: "Since we can see the sound calls and videos it would be helpful to see the lightshows associated
with the game's own modes." A Spike 2 game numbers its light shows: its show starter (``show_start(n)``, the port's
``site show_start``; MODE_SDK.md "the game's light shows") looks the number up in a table of 12-byte rows
(``row = table + 12 * n``; the first word is the show's process body, most often through a one-instruction jump)
and starts that body as a process. James Bond LE 1.06: starter 0x311928, table 0x7c46b8, 538 numbers; its Aston
Martin Multiball asks for shows 382-391, its Dr. No Multiball 235-243.

So a mode's light shows are read the way its sounds are (:mod:`.clip_sounds`): every call of the starter, or of a
function that hands one of its own arguments on to it (:func:`.clip_sounds.sound_entries`, Bond's three wrappers at
0x13ab68/80/98), with a constant number, given the mode whose code it is in (:func:`.clip_sounds.mode_calls`,
:class:`.clip_modes._Owners` / :class:`.clip_files.FileOwners`). A show is named where the build's port names one
with the same body (PAD-411/418's names, made from what each show did in the emulator: "Wide slow fade"); the lit-
shot flash's body, which calls the port's call-kind show site (PAD-642), is "Lit shot flash". The rest go by the
game's number. Read-only; never raises on a program it can't read.
"""

import re
from dataclasses import dataclass, field

READ_REV = 1

#: the starter's first two words on every port that places it (58 of 69 ports: ``push {r4-sl, lr}; subs r8, r0, #0``)
STARTER_WORDS = (0xE92D47F0, 0xE2508000)
#: how far into the starter its count and table loads are read
STARTER_SCAN = 48
#: a table row's size
ROW = 12
_B_MASK, _B = 0xFF000000, 0xEA000000                        # b <target>, always


@dataclass
class ShowReading:
    """The light shows each mode's own code starts by a fixed number."""
    note: str = ""                  # why there is nothing, in words
    origin: str = ""                # "port" (the build's port placed the starter) or "located" (by its shape)
    starter: int = 0
    table: int = 0
    count: int = 0
    calls: int = 0
    #: mode class -> [[show number, first call VA, how many calls]] in the order its code first asks
    modes: dict = field(default_factory=dict)
    #: show number (str) -> its name, where the port names that show
    names: dict = field(default_factory=dict)
    #: show number (str) -> names a mode of the user's can pick for it on the Lights page ([] = none)
    pickable: dict = field(default_factory=dict)

    def to_json(self):
        return {"rev": READ_REV, "note": self.note, "origin": self.origin, "starter": self.starter,
                "table": self.table, "count": self.count, "calls": self.calls, "modes": self.modes,
                "names": self.names, "pickable": self.pickable}

    @classmethod
    def from_json(cls, d):
        d = d or {}
        return cls(d.get("note", ""), d.get("origin", ""), int(d.get("starter") or 0), int(d.get("table") or 0),
                   int(d.get("count") or 0), int(d.get("calls") or 0),
                   {k: [list(r) for r in v] for k, v in (d.get("modes") or {}).items()},
                   dict(d.get("names") or {}), {k: list(v) for k, v in (d.get("pickable") or {}).items()})


# ---- the port's lines ----------------------------------------------------------------------------
def port_lines(game, version):
    """The build's port as split lines, or [] (no port)."""
    if not game or not version:
        return []
    try:
        from . import mode_runtime as MR
        path = MR.port_file(game, version)
    except Exception:                                       # noqa: BLE001 - no port, nothing named
        path = None
    if not path:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return [ln.split("#", 1)[0].split() for ln in f]
    except OSError:
        return []


def _site(prog, p):
    """A ``site`` line's VA when its two words are this program's, else None."""
    try:
        va, w0, w1 = int(p[2], 0), int(p[3], 0), int(p[4], 0)
    except (ValueError, IndexError):
        return None
    try:
        return va if prog.in_text(va) and prog.word(va) == w0 and prog.word(va + 4) == w1 else None
    except Exception:                                       # noqa: BLE001
        return None


# ---- the starter, its table ----------------------------------------------------------------------
def _movwt(w):
    """``(reg, half, imm16)`` for a movw (half 0) / movt (half 1), else None."""
    if w >> 28 != 0xE:
        return None
    op = w & 0x0FF00000
    if op not in (0x03000000, 0x03400000):
        return None
    return (w >> 12) & 15, int(op == 0x03400000), ((w >> 4) & 0xF000) | (w & 0xFFF)


def starter_table(prog, va):
    """``(count, table VA)`` read off the starter at *va*, or ``(0, 0)``: the first constant it loads a word
    from is its count (``cmp r8, [count]``), the constant it adds ``n * 3 << 2`` to is its table."""
    regs, consts, order = {}, {}, []
    count = table = 0
    for i in range(STARTER_SCAN):
        try:
            w = prog.word(va + 4 * i)
        except Exception:                                   # noqa: BLE001
            break
        m = _movwt(w)
        if m:
            reg, half, imm = m
            if half == 0:
                regs[reg] = imm
            elif reg in regs:
                consts[reg] = regs.pop(reg) | (imm << 16)
                order.append(consts[reg])
            continue
        # ldr rd, [rn] (no offset): the count's word
        if (w & 0x0FF00FFF) == 0x05900000 and not count:
            rn = (w >> 16) & 15
            if rn in consts:
                try:
                    count = prog.word(consts[rn])
                except Exception:                           # noqa: BLE001
                    count = 0
        # add rd, rn, rm, lsl #2: the row's address
        if (w & 0x0FE00FF0) == 0x00800100 and not table:
            rn = (w >> 16) & 15
            if rn in consts:
                table = consts[rn]
    if not (0 < count < 0x4000) or not table:
        return 0, 0
    return count, table


def locate_starter(prog):
    """The starter's VA found by its first words and a table read off it (no port), or 0. Only when exactly one
    function fits."""
    found = []
    try:
        lo, hi = prog.tlo, prog.thi
    except Exception:                                       # noqa: BLE001
        return 0
    try:
        raw = prog.b
        off = prog.va2off(lo)
    except Exception:                                       # noqa: BLE001
        return 0
    head = STARTER_WORDS[0].to_bytes(4, "little") + STARTER_WORDS[1].to_bytes(4, "little")
    end = off + (hi - lo)
    i = raw.find(head, off, end)
    while i >= 0 and len(found) < 3:
        if (i - off) % 4 == 0:
            va = lo + (i - off)
            if starter_table(prog, va)[1]:
                found.append(va)
        i = raw.find(head, i + 4, end)
    return found[0] if len(found) == 1 else 0


def body_of(prog, table, n):
    """Show *n*'s process body: the row's first word, through the one-instruction jump most rows point at."""
    try:
        p = prog.word(table + ROW * n)
        if not p or not prog.in_text(p):
            return 0
        w = prog.word(p)
    except Exception:                                       # noqa: BLE001
        return 0
    if (w & _B_MASK) == _B:
        off = w & 0xFFFFFF
        if off & 0x800000:
            off -= 1 << 24
        return p + 8 + off * 4
    return p


# ---- the port's names ----------------------------------------------------------------------------
_COLOUR_TAIL = re.compile(r"\s+\S+$")


def port_names(prog, lines):
    """``({body VA: name}, {call-kind site VA: name})`` from the port's ``site show_<n>`` / ``text
    show_name_<n>`` lines whose words are this program's. A call-kind show (``value show_call_<n>``, PAD-642: the
    lit-shot flash, one per colour) names its site by the names' shared words ("Lit shot flash")."""
    names = {p[1][len("show_name_"):]: " ".join(p[2:]) for p in lines
             if len(p) > 2 and p[0] == "text" and p[1].startswith("show_name_")}
    calls = {p[1][len("show_call_"):] for p in lines if len(p) > 2 and p[0] == "value" and p[1].startswith("show_call_")}
    bodies, by_site = {}, {}
    for p in lines:
        if len(p) < 5 or p[0] != "site" or not p[1].startswith("show_") or not p[1][5:].isdigit():
            continue
        k = p[1][5:]
        name = names.get(k, "").strip()
        va = _site(prog, p)
        if not name or va is None:
            continue
        if k in calls:
            by_site.setdefault(va, []).append(name)
        else:
            bodies.setdefault(va, name)
    sites = {}
    for va, ns in by_site.items():
        words = ns[0].split()
        for other in ns[1:]:
            ow = other.split()
            n = 0
            while n < min(len(words), len(ow)) and words[n] == ow[n]:
                n += 1
            words = words[:n]
        sites[va] = " ".join(words) if words else _COLOUR_TAIL.sub("", ns[0])
    return bodies, {va: (sites[va], ns) for va, ns in by_site.items()}


def _calls_site(prog, body, site):
    """Whether the function at *body* calls *site* (a bl in its first instructions, up to its end)."""
    try:
        from .clip_sounds import _extent
        end = _extent(prog, body)[0]
    except Exception:                                       # noqa: BLE001
        end = body + 0x400
    va = body
    while va < end:
        try:
            w = prog.word(va)
        except Exception:                                   # noqa: BLE001
            return False
        if (w & 0xFF000000) == 0xEB000000:
            off = w & 0xFFFFFF
            if off & 0x800000:
                off -= 1 << 24
            if va + 8 + off * 4 == site:
                return True
        va += 4
    return False


# ---- the reading ---------------------------------------------------------------------------------
def analyse(elf=None, game="", version="", ctx=None):
    """:class:`ShowReading` of the game program *elf* (bytes; or *ctx*'s ``prog``, :func:`.clip_modes.analyse`'s,
    with its ``owners``). *game* and *version* find the build's port (its starter, its show names)."""
    from . import clip_sounds as CS
    from . import stock_scan as S
    out = ShowReading()
    ctx = ctx or {}
    prog = ctx.get("prog")
    if prog is None:
        try:
            prog = S.Program(bytes(elf))
        except (S.ScanError, TypeError) as e:
            out.note = "the game program could not be read (%s)" % e
            return out
    lines = port_lines(game, version)
    starter = 0
    for p in lines:
        if len(p) >= 5 and p[0] == "site" and p[1] == "show_start":
            starter = _site(prog, p) or 0
            break
    out.origin = "port" if starter else ""
    if not starter:
        starter = locate_starter(prog)
        out.origin = "located" if starter else ""
    if not starter:
        out.note = "the game's light show starter was not found in its program"
        return out
    count, table = starter_table(prog, starter)
    if not count:
        out.note = "the game's table of light shows was not found"
        return out
    out.starter, out.count, out.table = starter, count, table
    entries = CS.sound_entries(prog, {starter: "show_start"}, count, depth=CS.DEPTH_PORT,
                               trust=out.origin == "port")
    calls = [c for c in CS.sound_calls(prog, entries, count) if c.request > 0]   # 0 starts nothing
    out.calls = len(calls)
    owners = ctx.get("owners")
    if owners is not None:
        out.modes = CS.mode_calls(calls, owners)
    bodies, flash = port_names(prog, lines)
    shown = sorted({r[0] for rs in out.modes.values() for r in rs})
    for n in shown:
        body = body_of(prog, table, n)
        if body in bodies:
            out.names[str(n)] = bodies[body]
            out.pickable[str(n)] = [bodies[body]]
            continue
        for site, (name, picks) in flash.items():
            if body and _calls_site(prog, body, site):
                out.names[str(n)] = name
                out.pickable[str(n)] = list(picks)
                break
    if not out.modes:
        out.note = ("no mode's own code was told apart in the game program" if owners is None
                    else "no mode's code starts a light show by a fixed number")
    return out
