"""PAD-710: the game's own mode framework, read from a C++ Spike 2 build's program - what a mode of the game's
writes as it starts and as it stops, so a mode of ours that takes one's place can count as it (MODE_SDK.md "A mode in
the place of one of the game's", tools/spike2_emu/modes/sdk/framework_lines.py is the command line).

Every C++ title builds its modes on Stern's mode class (`cmode`, a `crule` on the later titles). Its code differs from
one generation of the framework to the next - the offsets, the slots, whether the mode manager counts audits - but the
shape of its STOP is the same on every one read (Godzilla 1.16 v[11], Star Wars 1.31 v[12], Venom 1.07 v[50]):

    push  {.., lr}
    mov   r4, r0                     the mode
    mov   r5, r1                     the reason: non-zero = completed (won)
    bl    <player>                   the player up (the index the per-player fields are kept by)
    add   r0, r4, r0
    ldrb  r3, [r0, #<stopped>]       already stopped for this player: return
    cmp   r3, #0
    popne {.., pc}
    ...   strb <1>, [.., #<stopped>]  stopped
    ...   strb r5, [.., #<reason>]    (the generations that keep the reason: Godzilla's)
    ...   ldr r3, [vtable, #<end>]; blx r3      the mode's END
    ...   the outcome's bookkeeping (wins, the mode manager's COMPLETED audit, what the title's own stop adds)

and its START counts the start for the player (`ldr rX, [obj + 4 * player, #<starts>]; add rX, rX, #1; str`) and, on
the generations whose manager keeps per-mode audits (Godzilla's), tells the manager (`bl <started>` with r0 = the
manager, r1 = the mode's id: the STARTED audit). A game's rules read a mode's stopped byte and its reason (or its wins)
as "completed": that is what its wizards and unlocks are gated on.

The port lines (each build's own, never carried from a reference):

  site  mode_player          the player function the framework indexes its per-player fields by
  value mode_slot_stop       the STOP's virtual slot (called on the mode's object, so a title's own stop runs)
  value mode_stopped_at      the per-player stopped byte (obj + this + player)
  value mode_reason_at       the per-player reason byte (only where the stop keeps one)
  value mode_starts_at       the per-player start count (obj + this + 4 * player)
  value mode_wins_at         the per-player count of completions the STOP keeps (only where it keeps one)
  site  mode_started         the manager's "started" (STARTED audit), with
  data  mode_manager         ... the manager it is called on      (only where the START calls one)
  value mode_id_at           where a mode keeps its id (r1 of the call)

Read-only (bytes in, lines out). A plain-C title (no mode class) gets none.
"""
import collections
import re

from . import stock_scan as S

#: the slots a framework class has, at most, that are read
MAX_SLOTS = 140
#: how many instructions of a function are read for its shape
MAX_INS = 400

_H = r"0x[0-9a-f]+|\d+"


class Found(dict):
    """The finder's result: the port values by name, and ``notes`` saying what was not found."""

    def __init__(self):
        super().__init__()
        self.notes = []


def _ins(prog, start):
    """[(va, mnemonic, operands, word)] of the function at *start*: forward to a return or an unconditional branch
    with no forward branch target of its own past it (a target past it is followed: the code an early return
    jumps over), a tail call and a backward branch end a path. Capstone decodes each word."""
    cs = S._disassembler()
    out, pend, va = [], set(), start
    while len(out) < MAX_INS:
        w = prog.word(va)
        if w is None:
            break
        d = list(cs.disasm(w.to_bytes(4, "little"), va))
        m, o = (d[0].mnemonic, d[0].op_str) if d else ("?", "")
        out.append((va, m, o, w))
        t = S.branch_target(w, va) if (w & 0x0F000000) == 0x0A000000 else None
        if t is not None and va < t < va + 0x2000:
            pend.add(t)
        ends = (w >> 28) == 0xE and (
            (m == "bx" and o == "lr") or (m in ("pop", "ldm") and "pc" in o) or m == "b"
            or (m == "ldr" and o.startswith("pc,")) or (m == "bx" and re.match(r"r\d+$", o)))
        if ends:
            nxt = sorted(x for x in pend if x > va)
            if not nxt:
                break
            va = nxt[0]
            pend = set(nxt[1:])
            continue
        va += 4
        pend.discard(va)
    return out


def _num(s):
    return int(s, 0)


def stop_shape(prog, f):
    """The framework STOP's facts for the function at *f*, or None when it is not of that shape."""
    ins = _ins(prog, f)
    if len(ins) < 12:
        return None
    obj = reason = None
    for _va, m, o, _w in ins[:12]:
        mm = re.match(r"(r\d+), (r\d+)$", o)
        if m == "mov" and mm and mm.group(2) == "r0" and obj is None:
            obj = mm.group(1)
        elif m == "mov" and mm and mm.group(2) == "r1" and reason is None:
            reason = mm.group(1)
    if obj is None or reason is None:
        return None
    # `bl <player>; add rA, <obj>, r0; ldrb rX, [rA, #<stopped>]; cmp rX, #0; <return when set>` early on (Jurassic Park
    # asks two of the mode's virtuals first)
    for k in range(min(24, len(ins) - 5)):
        if ins[k][1] != "bl" or not ins[k][2].startswith("#"):
            continue
        m1 = re.match(r"(r\d+), %s, r0$" % obj, ins[k + 1][2]) if ins[k + 1][1] == "add" else None
        m2 = re.match(r"(r\d+), \[(r\d+), #(%s)\]$" % _H, ins[k + 2][2]) if ins[k + 2][1] == "ldrb" else None
        if not m1 or not m2 or m2.group(2) != m1.group(1):
            continue
        if ins[k + 3][1] != "cmp" or ins[k + 3][2] != "%s, #0" % m2.group(1):
            continue
        if ins[k + 4][1] == "beq":
            # Jaws / King Kong: `beq <on>` with the return right after it (stopped already: return)
            if not any(m in ("pop", "bx", "ldm") and (m == "bx" or "pc" in o) for _va, m, o, _w in ins[k + 5:k + 8]):
                continue
        elif ins[k + 4][1] not in ("popne", "bxne", "ldmne", "bne"):
            continue
        break
    else:
        return None
    player = _num(ins[k][2].lstrip("#"))
    if not is_player_getter(prog, player):
        # Jurassic Park: the index goes through a check of the player number (`sub r3, r0, #1; cmp r3, #3`); the
        # player is the getter called before it
        getters = [_num(o[1:]) for _va, m, o, _w in ins[:k] if m == "bl" and o.startswith("#")
                   and is_player_getter(prog, _num(o[1:]))]
        if not getters:
            return None
        player = getters[-1]
    stopped = _num(m2.group(3))
    ones = set()
    sets_stopped = end = False
    reason_at = None
    for i, (_va, m, o, _w) in enumerate(ins[k + 5:], k + 5):
        mm = re.match(r"(r\d+), #1$", o)
        if m == "mov" and mm:
            ones.add(mm.group(1))
        ms = re.match(r"(r\d+), \[r\d+, #(%s)\]$" % _H, o) if m == "strb" else None
        if ms and ms.group(1) in ones | {reason} and _num(ms.group(2)) == stopped:
            sets_stopped = True                          # (Rush keeps the reason itself in the stopped byte)
        if ms and ms.group(1) == reason and _num(ms.group(2)) != stopped and reason_at is None:
            reason_at = _num(ms.group(2))
        if m in ("blx", "bx") and re.match(r"r\d+$", o) and i >= 1:
            # the mode's END: a virtual of the mode called with r0 = the mode
            back = ins[max(0, i - 6):i]
            if any(b[1] == "mov" and b[2] == "r0, %s" % obj for b in back) and \
                    any(b[1] == "ldr" and re.match(r"%s, \[r\d+, #(%s)\]$" % (o, _H), b[2]) for b in back):
                end = True
    if not sets_stopped or not end:
        return None
    wins = player_counts(ins)               # Star Wars, Venom...: a completed stop counts the player's wins
    return {"player": player, "stopped": stopped, "reason": reason_at, "fn": f, "wins": wins[0] if wins else None}


def is_player_getter(prog, f):
    """`movw rX, #lo; movt rX, #hi; ldrb r0, [rX]; bx lr`: the framework's player-up byte (1-4)."""
    w = [prog.word(f + 4 * i) for i in range(4)]
    if None in w:
        return False
    rx = (w[0] >> 12) & 0xF
    return ((w[0] & 0x0FF00000) == 0x03000000 and (w[1] & 0x0FF00000) == 0x03400000 and (w[1] >> 12) & 0xF == rx
            and (w[2] & 0x0FFFF000) == (0x05D00000 | rx << 16) and w[3] == 0xE12FFF1E)


def player_counts(ins):
    """The offsets of the per-player words the function *ins* adds one to: `ldr rX, [rB, #off]; add rX, rX, #1 (or a
    register holding 1); str rX, [rB, #off]` with rB = the mode + 4 * the player index - `sxth rP, r0` (the player
    getter's byte) and `add rB, <mode>, rP, lsl #2` just before. A `sub r0, r0, #1; uxtb` index is another, 0-based,
    count and is left out."""
    obj = next((mm.group(1) for _va, m, o, _w in ins[:10]
                for mm in [re.match(r"(r\d+), r0$", o)] if m == "mov" and mm), None)
    ones = {mm.group(1) for _va, m, o, _w in ins for mm in [re.match(r"(r\d+), #1$", o)] if m == "mov" and mm}
    out = []
    for i in range(len(ins) - 2):
        _va, m, o, _w = ins[i]
        ml = re.match(r"(r\d+), \[(r\d+), #(%s)\]$" % _H, o) if m == "ldr" else None
        if not (obj and ml and ins[i + 1][1] == "add" and ins[i + 2][1] == "str" and ins[i + 2][2] == o):
            continue
        ma = re.match(r"%s, %s, (#1|r\d+)$" % (ml.group(1), ml.group(1)), ins[i + 1][2])
        if not ma or (ma.group(1) != "#1" and ma.group(1) not in ones):
            continue
        back = ins[max(0, i - 4):i]
        sx = [mm.group(1) for _va, m2, o2, _w2 in back for mm in [re.match(r"(r\d+), r0$", o2)] if m2 == "sxth" and mm]
        if any(b[1] == "add" and b[2] == "%s, %s, %s, lsl #2" % (ml.group(2), obj, r) for b in back for r in sx):
            out.append(_num(ml.group(3)))
    return out


def start_facts(prog, f, player):
    """The START's per-player start count offset and the manager call (fn, manager) in the function at *f*."""
    ins = _ins(prog, f)
    starts = player_counts(ins)
    calls = []
    for i in range(len(ins) - 2):
        _va, m, o, _w = ins[i]
        if m == "bl" and o.startswith("#"):
            back = ins[max(0, i - 8):i]
            lo = hi = None
            idr = False
            for b in reversed(back):
                mw = re.match(r"r0, #(%s)$" % _H, b[2])
                if b[1] == "movw" and mw and lo is None:
                    lo = _num(mw.group(1))
                elif b[1] == "movt" and mw and hi is None:
                    hi = _num(mw.group(1))
                if b[1] in ("ldr", "ldreq") and re.match(r"r1, \[r\d+, #4\]$", b[2]):
                    idr = True
            if lo is not None and hi is not None and idr and _num(o[1:]) != player:
                calls.append((_num(o[1:]), hi << 16 | lo))
    return starts, calls


def _is_log(prog, f):
    """A trace print: varargs (`push {r0, r1, r2, r3}` first), or a jump to one (a PLT stub)."""
    w = prog.word(f)
    return w is None or w == 0xE92D000F or (w & 0xFFFFF000) == 0xE28FC000


def _mode_classes(prog, model):
    return [c for c in model if model[c].get("vtable") and (c == "cmode" or "cmode" in S.chain_of(model, c))]


def find(elf, start_slot=None):
    """:class:`Found` for a build's program (bytes). *start_slot*: the title's START slot (the stock scanner's, the
    port's `stock_slot_start`); read by the scanner when None."""
    out = Found()
    prog = elf if isinstance(elf, S.Program) else S.Program(elf)
    model = S.class_model(prog)
    classes = _mode_classes(prog, model)
    if not classes:
        out.notes.append("no mode class in this game program (a plain-C title)")
        return out
    # the STOP: the slot most mode classes hold a function of the stop's shape at
    votes, shapes = collections.Counter(), {}
    for c in classes:
        vt = model[c]["vtable"]
        n = int(model[c].get("nvirt") or MAX_SLOTS)
        for k in range(min(n, MAX_SLOTS)):
            f = prog.word(vt + 8 + 4 * k)
            if not f or f < 0x8000:
                continue
            if f not in shapes:
                shapes[f] = stop_shape(prog, f)
            if shapes[f]:
                votes[(k, shapes[f]["stopped"], shapes[f]["player"])] += 1
    if not votes:
        out.notes.append("no function of the framework STOP's shape in the mode classes")
        return out
    (slot, stopped, player), n = votes.most_common(1)[0]
    base = collections.Counter()
    for c in classes:
        f = prog.word(model[c]["vtable"] + 8 + 4 * slot)
        if f and shapes.get(f) and shapes[f]["stopped"] == stopped:
            base[f] += 1
    stop = shapes[base.most_common(1)[0][0]]
    out.update(mode_player=player, mode_slot_stop=slot, mode_stopped_at=stopped)
    if stop["reason"] is not None:
        out["mode_reason_at"] = stop["reason"]
    if stop.get("wins") is not None:
        out["mode_wins_at"] = stop["wins"]
    out.notes.append("stop: v[%d] in %d of %d mode classes (base 0x%x)" % (slot, n, len(classes), stop["fn"]))
    # the START: the title's start slot's functions and what they call; the port's slot first (a derived port's may be
    # its reference's), then the stock scanner's
    starts = calls = None
    tried = []
    for k, slot_k in enumerate((start_slot, None)):
        if slot_k is None and k:
            try:
                from . import stock_scan_cpp as C
                slot_k = C.read(prog, model).engine.get("start_slot")
            except Exception:                            # noqa: BLE001
                slot_k = None
        if slot_k is None or slot_k in tried:
            continue
        tried.append(slot_k)
        starts, calls = _start_scan(prog, model, classes, int(slot_k), player)
        if starts:
            break
    if starts is None:
        out.notes.append("no START slot: no start count")
        return out
    if starts:
        out["mode_starts_at"] = starts.most_common(1)[0][0]
    else:
        out.notes.append("no per-player start count in the START (v[%s])" % ", v[".join(str(x) for x in tried))
    if calls:
        (fn, mgr), _n = calls.most_common(1)[0]
        out.update(mode_started=fn, mode_manager=mgr, mode_id_at=4)
    else:
        out.notes.append("the START tells no mode manager (no STARTED audit on this generation)")
    return out


def _start_scan(prog, model, classes, slot, player):
    """(start counts, manager calls) - Counters - of the functions at START slot *slot* of the mode classes and the
    functions they call (a derived START calls its base)."""
    starts, calls = collections.Counter(), collections.Counter()
    seen = set()
    for c in classes:
        f = prog.word(model[c]["vtable"] + 8 + 4 * slot)
        todo = [f] if f else []
        for depth in range(2):
            nxt = []
            for g in todo:
                if g in seen or g < 0x8000:
                    continue
                seen.add(g)
                s, cl = start_facts(prog, g, player)
                starts.update(s)
                calls.update(x for x in cl if not _is_log(prog, x[0]))
                if depth == 0:
                    nxt += [_num(o[1:]) for _va, m, o, _w in _ins(prog, g) if m == "bl" and o.startswith("#")]
            todo = nxt
    return starts, calls


def port_lines(found, prog=None):
    """The port's framework section for :func:`find`'s result (lines); [] when no STOP was found. *prog* gives the
    sites' first two words (the runtime checks them)."""
    if "mode_slot_stop" not in found:
        return []

    def words(va):
        if prog is None:
            return ""
        a, b = prog.word(va), prog.word(va + 4)
        return " 0x%08x 0x%08x" % (a or 0, b or 0)

    out = ["# PAD-710: the game's own mode framework (mode_framework.py, from this build's program): what one of its",
           "# modes writes as it starts and stops, so a mode of ours in one's place counts as it"]
    out.append("site  mode_player            0x%08x%s" % (found["mode_player"], words(found["mode_player"])))
    out.append("value mode_slot_stop         %d" % found["mode_slot_stop"])
    out.append("value mode_stopped_at        0x%x" % found["mode_stopped_at"])
    if "mode_reason_at" in found:
        out.append("value mode_reason_at         0x%x" % found["mode_reason_at"])
    if "mode_starts_at" in found:
        out.append("value mode_starts_at         0x%x" % found["mode_starts_at"])
    if "mode_wins_at" in found:
        out.append("value mode_wins_at           0x%x" % found["mode_wins_at"])
    if "mode_started" in found:
        out.append("site  mode_started           0x%08x%s" % (found["mode_started"], words(found["mode_started"])))
        out.append("data  mode_manager           0x%08x" % found["mode_manager"])
        out.append("value mode_id_at             %d" % found["mode_id_at"])
    return out


def missing_from(lines, port_text):
    """The *lines* whose name the port does not have yet (as portchallenge.missing_from)."""
    have = set()
    for raw in port_text.splitlines():
        p = raw.split("#", 1)[0].split()
        if len(p) >= 2:
            have.add((p[0], p[1]))
    out = []
    for line in lines:
        p = line.split("#", 1)[0].split()
        if len(p) < 2 or (p[0], p[1]) not in have:
            out.append(line)
    return out if any(not x.startswith("#") for x in out) else []


def lines_for(elf, port_text):
    """The framework lines *port_text* lacks, read from the build's own program (bytes); [] when it has them, or
    the build has none (a plain-C title), or the program cannot be read. Never raises: a card build or a derive
    goes on without them (a mode in a game mode's place then counts only as ours)."""
    if re.search(r"^value\s+mode_slot_stop\s", port_text or "", re.M):
        return []
    try:
        prog = S.Program(elf)
        m = re.search(r"^value\s+stock_slot_start\s+(\d+)", port_text or "", re.M)
        found = find(prog, int(m.group(1)) if m else None)
        return missing_from(port_lines(found, prog), port_text or "")
    except Exception:                                    # noqa: BLE001 - an odd build: without them
        return []
