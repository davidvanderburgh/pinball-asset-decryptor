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

  site  mode_player          the player function the framework indexes its per-player fields by, or
  data  mode_player_at       ... the player-up byte itself, on the older builds that read it inline (PAD-714)
  value mode_slot_stop       the STOP's virtual slot (called on the mode's object, so a title's own stop runs)
  value mode_stopped_at      the per-player stopped byte (obj + this + player)
  value mode_reason_at       the per-player reason byte (only where the stop keeps one)
  value mode_starts_at       the per-player start count (obj + this + 4 * player)
  value mode_wins_at         the per-player count of completions the STOP keeps (only where it keeps one)
  value mode_slot_stopped_get  the mode's own "stopped?" virtual (mode, player), and
  value mode_slot_stopped_set  ... its own "mark stopped" (mode, value, player): where the STOP goes through them
                             (Jurassic Park; PAD-716)
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


#: PAD-714: what an instruction writes besides its first operand: a call the argument registers, a pop / ldm its list
_CALL_CLOBBERS = ("r0", "r1", "r2", "r3", "ip", "lr")
_COND = r"(?:eq|ne|cs|cc|hs|lo|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?"
_REG = r"r\d+|ip|lr|sb|sl|fp"


def _written(m, o):
    """The registers the instruction (*m*nemonic, *o*perands) writes, as far as the trackers here need: a call the
    argument registers, a pop / ldm its list, a store, compare or branch none, anything else its first operand."""
    if re.match(r"blx?%s$" % _COND, m):
        return set(_CALL_CLOBBERS)
    if m.startswith(("pop", "ldm")):
        if "pc" in o:      # a return: the code on is reached from a branch over it (popne: not taken), or not at all
            return set()
        return set(re.findall(_REG, o.split("{", 1)[-1]))
    if re.match(r"(?:str|stm|push|cmp|cmn|tst|teq|nop|bx?%s$)" % _COND, m):
        return set()
    first = o.split(",", 1)[0].strip()
    return {first} if re.match(r"(?:%s)$" % _REG, first) else set()


def _inline_track(ins):
    """PAD-714: the older builds read the player up INLINE where the later ones call a getter (Rush 1.18, Star Wars
    1.30, Venom 1.06, Godzilla 1.13...): ``movw rA, #lo; movt rA, #hi`` (the player-up byte), ``ldrb rX, [rA]``, often
    ``sub rX, rX, #1`` (a 0-based index), ``add rY, <mode>, rX`` (``, lsl #2`` for a per-player word). For each
    instruction, the state before it: ``(consts, idx, ptr, ptr4, objs, reasons)`` - the constants movw/movt built, the
    registers holding the player index (to the byte address and the amount taken off it), the mode + the index (the
    same, by byte and by word), and the registers holding the mode (r0 on entry) and the stop's reason (r1). Code
    after a return or a jump (:func:`_ins` goes on at the target of a branch over it) starts from the state at that
    branch."""
    state = ({}, {}, {}, {}, {"r0"}, {"r1"})
    at_branch = {}
    out = []
    ended = False
    for va, m, o, w in ins:
        if ended and va in at_branch:
            state = at_branch[va]
        state = tuple(dict(x) if isinstance(x, dict) else set(x) for x in state)
        out.append(tuple(dict(x) if isinstance(x, dict) else set(x) for x in state))
        consts, idx, ptr, ptr4, objs, reasons = state
        if (w & 0x0F000000) == 0x0A000000:               # a branch: what the code at its target starts from
            at_branch.setdefault(S.branch_target(w, va), out[-1])
        ended = (w >> 28) == 0xE and ((m == "bx") or (m in ("pop", "ldm") and "pc" in o) or m == "b"
                                      or (m == "ldr" and o.startswith("pc,")))
        new = {}
        mm = re.match(r"(r\d+), #(%s)$" % _H, o)
        if m == "movw" and mm:
            new["c"] = (mm.group(1), _num(mm.group(2)))
        elif m == "movt" and mm and mm.group(1) in consts:
            new["c"] = (mm.group(1), (consts[mm.group(1)] & 0xFFFF) | _num(mm.group(2)) << 16)
        ml = re.match(r"(r\d+), \[(r\d+)\]$", o)
        if m == "ldrb" and ml and ml.group(2) in consts:
            new["i"] = (ml.group(1), (consts[ml.group(2)], 0))
        ms = re.match(r"(r\d+), (r\d+), #1$", o)
        if m == "sub" and ms and ms.group(2) in idx:
            a, c = idx[ms.group(2)]
            new["i"] = (ms.group(1), (a, c + 1))
        mv = re.match(r"(r\d+), (r\d+)$", o)
        if m in ("mov", "uxtb", "sxth") and mv:
            if mv.group(2) in idx:
                new["i"] = (mv.group(1), idx[mv.group(2)])
            if m == "mov" and mv.group(2) in objs:
                new["o"] = mv.group(1)
            if m == "mov" and mv.group(2) in reasons:
                new["r"] = mv.group(1)
            if m == "mov" and mv.group(2) in ptr:
                new["p"] = (mv.group(1), ptr[mv.group(2)])
        ma = re.match(r"(%s), (r\d+), (r\d+)(, lsl #2)?$" % _REG, o)
        if m == "add" and ma:
            a, b, sh = ma.group(2), ma.group(3), ma.group(4)
            if b in objs and a in idx and not sh:
                a, b = b, a
            if a in objs and b in idx:
                new["p4" if sh else "p"] = (ma.group(1), idx[b])
        if m == "bl" and "r0" in idx:
            # Jurassic Park 1.15: the index goes through a check of the player number (`mov r0, rX; bl <check>`) and
            # comes back in r0
            new.setdefault("i", ("r0", idx["r0"]))
        for r in _written(m, o) - set(x[0] if isinstance(x, tuple) else x for x in new.values()):
            consts.pop(r, None), idx.pop(r, None), ptr.pop(r, None), ptr4.pop(r, None)
            objs.discard(r), reasons.discard(r)
        for k, v in new.items():
            reg = v[0] if isinstance(v, tuple) else v
            for d in (consts, idx, ptr, ptr4):
                d.pop(reg, None)
            if k != "o":
                objs.discard(reg)
            if k != "r":
                reasons.discard(reg)
            if k in ("c", "i", "p", "p4"):
                {"c": consts, "i": idx, "p": ptr, "p4": ptr4}[k][v[0]] = v[1]
            elif k == "o":
                objs.add(v)
            else:
                reasons.add(v)
    return out


def _stop_shape_inline(prog, ins, f):
    """PAD-714: :func:`stop_shape` for a STOP that reads the player up inline (:func:`_inline_track`): the same early
    return when the player's stopped byte is set, its store of 1 (or the reason) there and the mode's END. Offsets are
    given as the later builds' are, by the 1-based player (an index taken one off has its offsets one up)."""
    st = _inline_track(ins)
    for k in range(min(24, len(ins) - 3)):
        _va, m, o, _w = ins[k]
        ml = re.match(r"(r\d+), \[(r\d+), #(%s)\]$" % _H, o) if m == "ldrb" else None
        if not ml or ml.group(2) not in st[k][2]:
            continue
        if ins[k + 1][1] != "cmp" or ins[k + 1][2] != "%s, #0" % ml.group(1):
            continue
        if ins[k + 2][1] == "beq":
            if not any(m2 in ("pop", "bx", "ldm") and (m2 == "bx" or "pc" in o2) for _v, m2, o2, _w2 in ins[k + 3:k + 6]):
                continue
        elif ins[k + 2][1] not in ("popne", "bxne", "ldmne", "bne"):
            continue
        break
    else:
        return None
    byte, corr = st[k][2][ml.group(2)]
    stopped = _num(ml.group(3)) - corr
    ones = set()
    sets_stopped = end = False
    reason_at = None
    for i in range(k + 3, len(ins)):
        _va, m, o, _w = ins[i]
        _c, _i, ptr, _p4, objs, reasons = st[i]
        mm = re.match(r"(r\d+), #1$", o)
        if m == "mov" and mm:
            ones.add(mm.group(1))
        # (Godzilla 1.13 keeps the reason only when it is a first stop: `strbeq`)
        ms = re.match(r"(r\d+), \[(r\d+), #(%s)\]$" % _H, o) if re.match(r"strb%s$" % _COND, m) else None
        if ms and ms.group(2) in ptr and ptr[ms.group(2)][0] == byte:
            at = _num(ms.group(3)) - ptr[ms.group(2)][1]
            if at == stopped and ms.group(1) in ones | reasons:
                sets_stopped = True
            elif ms.group(1) in reasons and at != stopped and reason_at is None:
                reason_at = at
        if m in ("blx", "bx") and re.match(r"(?:r\d+|ip)$", o):
            back = ins[max(0, i - 6):i]
            if any(b[1] == "mov" and b[2] in ("r0, %s" % x for x in st[i - len(back) + j][4])
                   for j, b in enumerate(back)) and \
                    any(b[1] == "ldr" and re.match(r"%s, \[r\d+, #(%s)\]$" % (o, _H), b[2]) for b in back):
                end = True
    if not sets_stopped or not end:
        return None
    wins = inline_counts(ins, st, byte)
    # PAD-716 on an older build too: Jurassic Park LE 1.15's stop asks the same two virtuals (v[32], v[55]) around the
    # stopped byte as 1.16's
    obj = next((r for r in sorted(st[k][4]) if r != "r0"), "r0")
    get_slot, set_slot = stopped_virtuals(ins, obj, k, _num(ml.group(3)))
    return {"player_at": byte, "player": None, "stopped": stopped, "reason": reason_at, "fn": f,
            "wins": wins[0] if wins else None, "stopped_get": get_slot, "stopped_set": set_slot}


def inline_counts(ins, st=None, byte=None):
    """PAD-714: :func:`player_counts` for code that reads the player up inline: the per-player words it adds one to
    (``ldr rX, [rB, #off]``, ``add rY, rX, #1`` (or a register holding 1) a few instructions on, ``str rY, [rB,
    #off]`` a few more on, rB = the mode + 4 * the index all along), as offsets by the 1-based player. *byte*: only an
    index read from that player-up byte."""
    st = st or _inline_track(ins)
    ones = {mm.group(1) for _va, m, o, _w in ins for mm in [re.match(r"(r\d+), #1$", o)] if m == "mov" and mm}
    out = []
    for i in range(len(ins) - 2):
        _va, m, o, _w = ins[i]
        ml = re.match(r"(r\d+), \[(r\d+), #(%s)\]$" % _H, o) if m == "ldr" else None
        if not ml or ml.group(2) not in st[i][3]:
            continue
        a, c = st[i][3][ml.group(2)]
        if byte is not None and a != byte:
            continue
        for j in range(i + 1, min(i + 5, len(ins) - 1)):
            ma = re.match(r"(r\d+), %s, (#1|r\d+)$" % ml.group(1), ins[j][2]) if ins[j][1] == "add" else None
            if ma and (ma.group(2) == "#1" or ma.group(2) in ones):
                break
            if ml.group(1) in _written(ins[j][1], ins[j][2]):
                ma = None
                break
        else:
            ma = None
        if not ma:
            continue
        for k in range(j + 1, min(j + 4, len(ins))):
            if ins[k][1] == "str" and ins[k][2] == "%s, [%s, #%s]" % (ma.group(1), ml.group(2), ml.group(3))                     and ml.group(2) in st[k][3] and st[k][3][ml.group(2)] == (a, c):
                out.append(_num(ml.group(3)) - 4 * c)
                break
    return out


def stop_shape(prog, f):
    """The framework STOP's facts for the function at *f*, or None when it is not of that shape. PAD-714: a slot that
    is only a jump to the STOP (Godzilla 1.13) is followed, and a STOP that reads the player up inline (the older
    builds) is read by :func:`_stop_shape_inline` (``player_at``: the player-up byte, ``player`` None)."""
    w = prog.word(f)
    if w is not None and (w & 0xFF000000) == 0xEA000000:
        f = S.branch_target(w, f)
    ins = _ins(prog, f)
    if len(ins) < 12:
        return None
    return _stop_shape_call(prog, ins, f) or _stop_shape_inline(prog, ins, f)


def _stop_shape_call(prog, ins, f):
    """:func:`stop_shape` for a STOP that calls the framework's player getter (every newest build)."""
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
    get_slot, set_slot = stopped_virtuals(ins, obj, k, stopped)
    return {"player": player, "stopped": stopped, "reason": reason_at, "fn": f, "wins": wins[0] if wins else None,
            "stopped_get": get_slot, "stopped_set": set_slot}


def stopped_virtuals(ins, obj, k, stopped):
    """PAD-716: (getter slot, setter slot) of the stopped byte where the STOP reaches it through two of the mode's own
    virtuals, else (None, None). Jurassic Park's stop reads it through v[32] (mode, player) and writes it through v[55]
    (mode, value, player), each called only where a class overrides it (`ldr rA, [<vtable>, #off]; ...; cmp rA, <the
    base's own>; bne <call it>`; the base's own is the plain byte), and JP Pro's chase, Ctrl Room and T-Rex classes do:
    they keep their stopped byte elsewhere (Trex Chase +0x137, Virus Attack +0x11f). The getter is the last such load
    before the stopped byte is read (*k*: the `bl` of its read), the setter the last one before it is written."""
    vt = {"r0", obj}
    regs = set()
    guarded = []
    for i, (_va, m, o, _w) in enumerate(ins):
        mv = re.match(r"(r\d+|ip), \[(r\d+)\]$", o) if m == "ldr" else None
        if mv and mv.group(2) in vt:
            regs.add(mv.group(1))
            continue
        ml = re.match(r"(r\d+|ip), \[(r\d+|ip), #(%s)\]$" % _H, o) if m == "ldr" else None
        if ml and ml.group(2) in regs and _num(ml.group(3)) % 4 == 0:
            if any(c[1] == "cmp" and c[2].startswith(ml.group(1) + ", ") for c in ins[i + 1:i + 6]):
                guarded.append((i, _num(ml.group(3)) // 4))
        ms = re.match(r"r\d+, \[r\d+, #(%s)\]$" % _H, o) if m == "strb" else None
        if ms and i > k and _num(ms.group(1)) == stopped:
            before = [s for j, s in guarded if j < k]
            after = [s for j, s in guarded if k < j < i]
            return (before[-1], after[-1]) if before and after else (None, None)
    return None, None


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


def start_facts(prog, f, player, player_at=None):
    """The START's per-player start count offset and the manager call (fn, manager) in the function at *f*.
    *player_at*: the player-up byte, on a build that reads it inline (PAD-714)."""
    ins = _ins(prog, f)
    starts = player_counts(ins) + (inline_counts(ins, byte=player_at) if player_at else [])
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
                votes[(k, shapes[f]["stopped"], shapes[f]["player"], shapes[f].get("player_at"))] += 1
    if not votes:
        out.notes.append("no function of the framework STOP's shape in the mode classes")
        return out
    (slot, stopped, player, player_at), n = votes.most_common(1)[0]
    base = collections.Counter()
    for c in classes:
        f = prog.word(model[c]["vtable"] + 8 + 4 * slot)
        if f and shapes.get(f) and shapes[f]["stopped"] == stopped:
            base[f] += 1
    stop = shapes[base.most_common(1)[0][0]]
    if player is not None:
        out["mode_player"] = player
    else:
        out["mode_player_at"] = player_at            # PAD-714: no getter on this build: the player-up byte itself
    out.update(mode_slot_stop=slot, mode_stopped_at=stopped)
    if stop["reason"] is not None:
        out["mode_reason_at"] = stop["reason"]
    if stop.get("wins") is not None:
        out["mode_wins_at"] = stop["wins"]
    if stop.get("stopped_get") is not None:             # PAD-716: Jurassic Park's own-stopped virtuals
        out.update(mode_slot_stopped_get=stop["stopped_get"], mode_slot_stopped_set=stop["stopped_set"])
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
        starts, calls = _start_scan(prog, model, classes, int(slot_k), player, player_at)
        if player_at is not None:
            # PAD-714: an older build's mode STARTs count their own per-player words beside the framework's; the base
            # class's START (cmode's, crule's) counts only the framework's
            for root in ("cmode", "crule"):
                g = prog.word(model[root]["vtable"] + 8 + 4 * int(slot_k)) if model.get(root, {}).get("vtable") else 0
                own = inline_counts(_ins(prog, g), byte=player_at) if g and g >= 0x8000 else []
                if own:
                    starts = collections.Counter({own[0]: 1})
                    break
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


def _start_scan(prog, model, classes, slot, player, player_at=None):
    """(start counts, manager calls) - Counters - of the functions at START slot *slot* of the mode classes and the
    functions they call (a derived START calls its base)."""
    starts, calls = collections.Counter(), collections.Counter()
    seen = {}
    for c in classes:
        f = prog.word(model[c]["vtable"] + 8 + 4 * slot)
        todo = [f] if f else []
        for depth in range(2):
            nxt = []
            for g in todo:
                if g in seen and player_at is not None and g >= 0x8000:
                    # PAD-714: on an older build each mode's START counts words of its own beside the framework's: a
                    # count in a START more of the classes reach is the framework's
                    starts.update(seen[g])
                if g in seen or g < 0x8000:
                    continue
                s, cl = start_facts(prog, g, player, player_at)
                seen[g] = s
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
    if "mode_player" in found:
        out.append("site  mode_player            0x%08x%s" % (found["mode_player"], words(found["mode_player"])))
    else:                                            # PAD-714: an older build reads the player up inline
        out.append("data  mode_player_at         0x%08x" % found["mode_player_at"])
    out.append("value mode_slot_stop         %d" % found["mode_slot_stop"])
    out.append("value mode_stopped_at        0x%x" % found["mode_stopped_at"])
    if "mode_reason_at" in found:
        out.append("value mode_reason_at         0x%x" % found["mode_reason_at"])
    if "mode_starts_at" in found:
        out.append("value mode_starts_at         0x%x" % found["mode_starts_at"])
    if "mode_wins_at" in found:
        out.append("value mode_wins_at           0x%x" % found["mode_wins_at"])
    if "mode_slot_stopped_get" in found:
        out.append("value mode_slot_stopped_get  %d" % found["mode_slot_stopped_get"])
        out.append("value mode_slot_stopped_set  %d" % found["mode_slot_stopped_set"])
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
    """The framework lines *port_text* lacks, read from the build's own program (bytes) - a port with PAD-710's section
    but not PAD-716's own-stopped virtuals is read again for those; [] when it has them, or
    the build has none (a plain-C title), or the program cannot be read. Never raises: a card build or a derive
    goes on without them (a mode in a game mode's place then counts only as ours)."""
    had = re.search(r"^value\s+mode_slot_stop\s", port_text or "", re.M)
    if had and re.search(r"^value\s+mode_slot_stopped_get\s", port_text or "", re.M):
        return []
    try:
        prog = S.Program(elf)
        m = re.search(r"^value\s+stock_slot_start\s+(\d+)", port_text or "", re.M)
        found = find(prog, int(m.group(1)) if m else None)
        lines = missing_from(port_lines(found, prog), port_text or "")
        # PAD-716: a port with PAD-710's section gets only what it lacks (Jurassic Park's own-stopped virtuals)
        return [x for x in lines if not x.startswith("#")] if had else lines
    except Exception:                                    # noqa: BLE001 - an odd build: without them
        return []


# ---- the plain-C titles ------------------------------------------------------------------------------------------
# A title with no mode class keeps its books in the framework's audits and game flags, named after the mode: James Bond
# LE 1.06's Ahoy Mr Bond Wizard Mode starts by setting FG_AHOY_MR_BOND_WIZARD_MODE_ACTIVE (and _PLAYED) and counts
# AUD_AHOY_MR_BOND_WIZARD_MODE_STARTED; its completion is FG_..._COMPLETED. Both name tables are in the program (FG_INVALID
# at id 0: a flag's index is its id; an audit's id is its descriptor's, stock_scan_c.audit_ids - PAD-714), and every
# build counts an audit through the same framework function:
#
#     push {r4, r5, r6, r7, r8, r9, lr} ; subs r5, r0, #0 ; sub sp, sp, #0x14 ; ...   (id in r0, the amount in r1)
#
# So a game mode's stem comes from the ACTIVE / PLAYED flag its START sets (else from the port's name for it), and its
# books from the names: STARTED (or STARTS, START) and COMPLETED (or COMPLETIONS) audits, PLAYED and COMPLETED flags,
# trying the spellings the games use (a MODE_ prefix or _MODE suffix, HURRYUP for "Hurry-Up"). PAD-715: where neither
# names any books, the flags its callers set: a site that is not the mode's start but a check before it (James Bond's
# Bird One Multiball is the lock-open check, PAD-578) is called by the start itself - the lock handler, which sets
# FG_ROCKET_MULTIBALL_ACTIVE: the game's own name for that multiball. Jurassic Park counts AUD_RESTORE_POWER_START.
AUDIT_ADD_HEAD = (0xE92D43F0, 0xE2505000, 0xE24DD014)


def names_table(e, first, prefix):
    """The program's ``prefix`` names by id (the pointer table whose first entry names ``first``), or []."""
    import struct
    m = re.search(re.escape(b"\0" + first.encode() + b"\0"), e.d)
    if not m:
        return []
    want = struct.pack("<I", e.va(m.start() + 1))
    i = 0
    while True:
        i = e.d.find(want, i)
        if i < 0:
            return []
        if i % 4 == 0 and e.va(i) is not None:
            names, at = [], e.va(i)
            while e.off(at + 4 * len(names)) is not None:
                s = e.cstr(e.word(at + 4 * len(names)))
                if not s or not s.startswith(prefix):
                    break
                names.append(s)
            if len(names) > 8:
                return names
        i += 1


def audit_add(e):
    """The framework's audit add (id in r0, amount in r1), or None: the head above, and within its first words the audit
    table into r4 (`movw r4` / `movt r4`) and the record index `lsl r8, r5, #4` (16-byte records). Another function
    opens with the same three words on every build (it takes stack arguments: Star Wars ELG has only that one)."""
    w = e.words
    for k in range(len(w) - 16):
        if tuple(w[k:k + 3]) != AUDIT_ADD_HEAD:
            continue
        win = w[k:k + 16]
        if 0xE1A08205 in win and any(x & 0xFFF0F000 == 0xE3004000 for x in win) \
                and any(x & 0xFFF0F000 == 0xE3404000 for x in win):
            return e.text_va + 4 * k
    return None


def _stems(name):
    up = name.upper().replace("'", "")
    base = re.sub(r"[^A-Z0-9]+", "_", up).strip("_")
    bare = re.sub(r"[^A-Z0-9]+", "_", re.sub(r"\(.*?\)", "", up)).strip("_")          # "Houses (whichever ...)"
    # Batman 66: "Egghead (episodes 47-48)" is AUD_EGGHEAD_MODE_EP_47_48_STARTS
    ep = re.sub(r"_EPISODES?_", "_MODE_EP_", base)
    out = []
    for s in (base, bare, ep, base.replace("HURRY_UP", "HURRYUP"), bare[:-1] if bare.endswith("S") else bare):
        out += [s, "MODE_" + s, s + "_MODE"]
    return list(dict.fromkeys(x for x in out if x))


def _start_flags(prog, f, flag_set, depth=1, seen=None):
    """The flag ids `mov r0, #id; bl <flag set>` sets in the function at *f* and the ones it calls."""
    seen = seen if seen is not None else set()
    if f in seen or not f:
        return []
    seen.add(f)
    ins = _ins(prog, f)
    out = []
    for i, (_va, m, o, _w) in enumerate(ins):
        if m not in ("bl", "b") or not o.startswith("#"):
            continue
        t = _num(o[1:])
        if t == flag_set:
            for _v, m2, o2, _w2 in reversed(ins[max(0, i - 5):i]):
                mm = re.match(r"r0, #(%s)$" % _H, o2)
                if m2 in ("mov", "movw") and mm:
                    out.append(_num(mm.group(1)))
                    break
                if o2.startswith("r0,"):
                    break
        elif depth > 0 and m == "bl":
            out += _start_flags(prog, t, flag_set, depth - 1, seen)
    return out


def plain_books(elf, port_text):
    """PAD-710: ``({id: {"started": audit, "completed": audit, "played": flag, "completed_flag": flag}}, audit add)``
    (each where the program names it) for the game modes of a plain-C port (`site block_start_<id>`, `text
    block_name_<id>`); ({}, None) on a C++ port or a program without the tables."""
    from . import portchallenge as PC
    if re.search(r"^data\s+block_obj_\d+", port_text or "", re.M):
        return {}, None
    e = PC.Elf(elf)
    add = audit_add(e)
    fg = names_table(e, "FG_INVALID", "FG_")
    if not fg:
        return {}, None
    from . import stock_scan_c as SC
    prog = S.Program(elf)
    # PAD-714: an audit's id is its descriptor's (what the game's own code passes the audit add), not its name's place:
    # X-Men 0.98 counts AUD_FASTBALL_SPECIAL_STARTS as 165, its name 209th. No audit add: its flags alone (Star Wars ELG)
    aid = {n: i for i, n in SC.audit_ids(prog)[1].items()} if add else {}
    fid = {n: i for i, n in enumerate(fg)}
    flags = PC.flag_functions(e)
    out = {}

    def flag_stems(f, depth=1):                      # the ACTIVE / PLAYED flags *f* (or what it calls) sets
        stems = []
        for fl in _start_flags(prog, f, flags["set"], depth) if flags else ():
            if fl < len(fg) and re.search(r"_(ACTIVE|PLAYED|RUNNING)$", fg[fl]):
                stems.append(re.sub(r"^FG_|_(ACTIVE|PLAYED|RUNNING)$", "", fg[fl]))
        return stems

    def books_of(stems):
        for st in dict.fromkeys(stems):
            books = {}
            for key, names, table in (("started", ("AUD_%s_STARTED", "AUD_%s_STARTS", "AUD_%s_START"), aid),
                                      ("completed", ("AUD_%s_COMPLETED", "AUD_%s_COMPLETIONS",
                                                     "AUD_%s_STAGE_X_COMPLETIONS"), aid),
                                      ("played", ("FG_%s_PLAYED",), fid),
                                      ("completed_flag", ("FG_%s_COMPLETED",), fid)):
                hit = next((table[n % st] for n in names if n % st in table), None)
                if hit:
                    books[key] = hit
            if books:
                return st, books
        return None, None

    for m in re.finditer(r"^site\s+block_start_(\d+)\s+0x([0-9a-f]+)", port_text, re.M):
        i, f = int(m.group(1)), int(m.group(2), 16)
        nm = re.search(r"^text\s+block_name_%d\s+(.+)$" % i, port_text, re.M)
        own = flag_stems(f)
        st, books = books_of(own + (_stems(nm.group(1).strip()) if nm else []))
        if st in own:                                # its START sets the mode's flags: the start itself
            out[i] = books
            continue
        # PAD-715: a check before the start (James Bond's lock multiballs: the lock-open check, which the lamps ask
        # too, and the lock handler at each lock) - the start is the one function that sets the mode's flags, there or
        # in what a caller calls (Bird One: the lock handler calls it at the last lock): a mode in its place takes that
        starts = {}
        for c in prog.callers(f):
            fs = prog.func_start(c)
            for t in [fs] + [_num(o[1:]) for _v, m, o, _w in _ins(prog, fs) if m == "bl" and o.startswith("#")]:
                for s in flag_stems(t, 0):
                    starts.setdefault(s, set()).add(t)
        if not books and len(starts) == 1:           # no books by its name: the one stem its callers set
            st, books = books_of(list(starts))
        if books and len(starts.get(st, ())) == 1:
            books["start"] = next(iter(starts[st]))
        if books:
            out[i] = books
    return out, add


def plain_lines(books, add, prog=None):
    """The port lines for :func:`plain_books`' result; [] when it found none."""
    if not books:
        return []
    out = ["# PAD-710: the game's own books of its modes (mode_framework.py, from this build's audit and flag names): a",
           "# mode of ours in one's place counts its STARTED audit and PLAYED flag, and when completed its COMPLETED ones"]
    if add:
        words = " 0x%08x 0x%08x" % (prog.word(add) or 0, prog.word(add + 4) or 0) if prog is not None else ""
        out.append("site  audit_add              0x%08x%s" % (add, words))
    for i in sorted(books):
        for key, line in (("started", "place_audit_started"), ("completed", "place_audit_completed"),
                          ("played", "place_flag_played"), ("completed_flag", "place_flag_completed")):
            if key in books[i]:
                out.append("value %-28s %d" % ("%s_%d" % (line, i), books[i][key]))
        if "start" in books[i]:                      # PAD-715: its site is a check; the place is this start's
            f = books[i]["start"]
            words = " 0x%08x 0x%08x" % (prog.word(f) or 0, prog.word(f + 4) or 0) if prog is not None else ""
            out.append("site  %-28s 0x%08x%s" % ("place_start_%d" % i, f, words))
    return out


def plain_lines_for(elf, port_text):
    """The plain-C books lines *port_text* lacks (as :func:`lines_for`), one by one - PAD-715: a port with some modes'
    books gets the others' (a derived port with the base's audit add site); never raises. PAD-747: and the game's other
    modes it keeps books of (:func:`done_lines`)."""
    try:
        books, add = plain_books(elf, port_text)
        out = missing_from(plain_lines(books, add, S.Program(elf)), port_text or "")
    except Exception:                                    # noqa: BLE001
        books, add, out = {}, None, []
    try:
        return out + done_lines(elf, (port_text or "") + "\n" + "\n".join(out))
    except Exception:                                    # noqa: BLE001
        return out


# ---- PAD-747: the game's other modes a plain-C build keeps books of -------------------------------------------------
#: how many such modes a port names at most (the runtime's ids DONE_EXTRA.. DONE_IDS - 1)
DONE_EXTRA_MAX = 128


def _done_title(stem):
    """``WHERES_BARB`` -> ``Wheres Barb``; a short single word (Elvira's movie initials, ``ABOB``) kept as it is."""
    words = stem.split("_")
    if len(words) == 1 and len(stem) <= 5:
        return stem
    return " ".join(w if w.isdigit() else w.capitalize() for w in words)


def done_books(elf, port_text):
    """PAD-747: ``[(name, "audit" | "flag", id), ...]``: a plain-C build's modes the game counts COMPLETED but the port
    names no start of (no `text block_name_<i>` books for them) - every stem with an ``AUD_<stem>_STARTED`` (or
    _STARTS / _START) and an ``AUD_<stem>_COMPLETED`` (or _COMPLETIONS) audit, counted through the framework's audit
    add; with no such audit, a ``FG_<stem>_COMPLETED`` flag where the port names the flag bitmap. In audit / flag id
    order. [] on a C++ port, or a program without the tables."""
    from . import portchallenge as PC
    from . import stock_scan_c as SC
    text = port_text or ""
    if re.search(r"^data\s+block_obj_\d+", text, re.M):
        return []
    e = PC.Elf(elf)
    add = audit_add(e)
    prog = S.Program(elf)
    names = SC.audit_ids(prog)[1] if add else {}
    aid = {n: i for i, n in names.items()}
    fg = names_table(e, "FG_INVALID", "FG_") or []
    have_a = {int(v) for v in re.findall(r"^value\s+place_audit_completed_\d+\s+(\d+)", text, re.M)}
    have_f = {int(v) for v in re.findall(r"^value\s+place_flag_completed_\d+\s+(\d+)", text, re.M)}
    out, stems = [], set()
    for n in sorted(aid, key=lambda n: aid[n]):
        m = re.match(r"AUD_(.+)_(COMPLETED|COMPLETIONS)$", n)
        if not m or m.group(1) in stems:
            continue
        st = m.group(1)
        if not any("AUD_%s_%s" % (st, w) in aid for w in ("STARTED", "STARTS", "START")):
            continue
        stems.add(st)
        if aid[n] not in have_a:
            out.append((_done_title(st), "audit", aid[n]))
    if re.search(r"^data\s+game_flags\s", text, re.M):
        for i, n in enumerate(fg):
            m = re.match(r"FG_(.+)_COMPLETED$", n)
            if m and m.group(1) not in stems and i not in have_f and not any(
                    "AUD_%s_%s" % (m.group(1), w) in aid for w in ("COMPLETED", "COMPLETIONS")):   # its audit counts it
                stems.add(m.group(1))
                out.append((_done_title(m.group(1)), "flag", i))
    return out[:DONE_EXTRA_MAX]


def done_lines(elf, port_text):
    """PAD-747: the port lines for :func:`done_books` - `text done_name_<n>` with `value done_audit_<n>` or `value
    done_flag_<n>`, numbered from 0 - or [] when there are none or the port names some already (numbered as one set)."""
    if re.search(r"^text\s+done_name_\d+", port_text or "", re.M):
        return []
    books = done_books(elf, port_text)
    if not books:
        return []
    out = ["# PAD-747: the game's other modes it keeps books of (mode_framework.done_lines): a mode of ours may start once",
           "# some of them are completed - each one's COMPLETED audit (through audit_add) or COMPLETED flag"]
    if any(k == "audit" for _n, k, _i in books) and not re.search(r"^site\s+audit_add\s", port_text or "", re.M):
        from . import portchallenge as PC
        add, prog = audit_add(PC.Elf(elf)), S.Program(elf)
        out.append("site  audit_add              0x%08x 0x%08x 0x%08x" % (add, prog.word(add) or 0, prog.word(add + 4) or 0))
    for n, (name, kind, i) in enumerate(books):
        out.append("text  %-28s %s" % ("done_name_%d" % n, name))
        out.append("value %-28s %d" % ("done_%s_%d" % (kind, n), i))
    return out


# ---- a plain-C build's own modes, from the same title's port ----------------------------------------------------
# PAD-714: on a plain-C title the game modes' starts (`site block_start_<i>`, PAD-363) come from the start finder
# (sdk/cstarts, with each title's hand-checked knowledge), run over the programs on hand when a port ships. An older
# build derived on a card has none: no game mode to keep off, none to take the place of. The same title's port names
# its modes; each one's start on THIS build is the one function that counts that mode's STARTED audit (the finder's
# audit witness), as the reference's does - the same audit, by name, so a build that renumbered its audits still gets
# its own - and whose first two words the veto can move.
def _audit_counters(prog, add):
    """{audit id: [function entry]} over every caller of the audit add, with the tracker's constants (a movw made far
    ahead of the call counts)."""
    out = collections.defaultdict(list)
    for f in sorted({prog.func_start(c) for c in prog.callers(add)}):
        for c in S.track(prog, f).calls:
            v = c["args"].get("r0") if c["target"] == add else None
            if isinstance(v, S.Val) and f not in out[v.v]:
                out[v.v].append(f)
    return out


def plain_starts(elf, ref_text):
    """{i: (start, name)} for the reference port's game modes (`site block_start_<i>`, `text block_name_<i>`, a
    plain-C port: no `data block_obj_`) on the build *elf*: each where exactly one function counts the mode's STARTED
    audit (by the reference start's own audit: its name names, at the function whose first two words are the reference start's) and its entry is movable; a mode
    the witness cannot place is left out. {} on a C++ reference or a build without the tables."""
    from . import game_mode_blocks as B
    from . import portchallenge as PC
    if not ref_text or re.search(r"^data\s+block_obj_\d+", ref_text, re.M):
        return {}
    from . import stock_scan_c as SC
    prog = S.Program(elf)
    _names, ids, _rec = SC.audit_ids(prog)               # the id the code passes, not the name's place (PAD-634)
    add = audit_add(PC.Elf(elf)) or SC.find_audit_add(prog, ids)
    if not ids or not add:
        return {}
    aid = {n: i for i, n in ids.items()}
    counters = _audit_counters(prog, add)
    out = {}
    for m in re.finditer(r"^site\s+block_start_(\d+)\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)", ref_text, re.M):
        i, words = int(m.group(1)), (int(m.group(2), 16), int(m.group(3), 16))
        nm = re.search(r"^text\s+block_name_%d\s+(.+)$" % i, ref_text, re.M)
        if not nm:
            continue
        name = nm.group(1).strip()
        shape, fs = _shape(*words), []
        for st in _stems(name):
            ids = [aid[n % st] for n in ("AUD_%s_STARTED", "AUD_%s_STARTS", "AUD_%s_START") if n % st in aid]
            heads = [f for a in ids for f in counters.get(a, ())]
            ins = {e for f in heads for e in _entries(prog, f)}
            same = sorted(e for e in ins if (prog.word(e), prog.word(e + 4)) == words)
            fs = same if len(same) == 1 else sorted(e for e in ins if _shape(prog.word(e), prog.word(e + 4)) == shape)
            if fs:
                break
        fs = sorted(set(fs))
        if len(fs) == 1 and B.movable((prog.word(fs[0]), prog.word(fs[0] + 4)))                 and fs[0] not in [v[0] for v in out.values()]:
            out[i] = (fs[0], name)
    return out


def _shape(*words):
    """Two instruction words with what another build of the title changes left out - a push's register list (Batman
    66 1.13 saves r4-r11 where 1.14 saves r4-r10), a `movw` / `movt` / `mov #`'s immediate (an audit id or a flag
    renumbered): the same function's head on every build."""
    out = []
    for w in words:
        if w is not None and w & 0xFFFF4000 == 0xE92D4000:
            w = 0xE92D4000                               # push {..., lr}
        elif w is not None and w & 0x0FF00000 in (0x03000000, 0x03400000):
            w &= 0xFFF0F000                              # movw / movt rd, #imm16
        elif w is not None and w & 0x0FEF0000 == 0x03A00000:
            w &= 0xFFFFF000                              # mov rd, #imm
        out.append(w)
    return tuple(out)


def _entries(prog, f):
    """*f* (a push) and the words before it that flow into it (a movw the compiler put ahead of the push: the
    function's true entry is up to six words earlier, PAD-363's cstart_lib.entry)."""
    out = [f]
    for k in range(1, 7):
        e = f - 4 * k
        w = prog.word(e)
        if w is None:
            break
        d = S.decode(w, e)
        if S.ends_flow(d) or d[0] in ("poppc", "bxlr") or prog.literal_loads(e):
            break
        out.append(e)
    return out


def plain_start_lines(elf, ref_text):
    """The `site block_start_<i>` / `text block_name_<i>` lines of :func:`plain_starts` (the reference's ids and names,
    this build's starts and words); [] when it found none. Never raises."""
    try:
        found = plain_starts(elf, ref_text)
        if not found:
            return []
        prog = S.Program(elf)
        out = ["# PAD-714: the game's own modes, the same title's port's, each found on this build by the function that "
               "counts", "# its STARTED audit (mode_framework.plain_starts)"]
        for i in sorted(found):
            f, name = found[i]
            out += ["site block_start_%-5d 0x%08x 0x%08x 0x%08x" % (i, f, prog.word(f) or 0, prog.word(f + 4) or 0),
                    "text block_name_%-6d %s" % (i, name)]
        return out
    except Exception:                                    # noqa: BLE001
        return []


# ---- the challenges ----------------------------------------------------------------------------------------------
# A Player Challenge (PAD-615/619) that is one of the game's own modes - James Bond's Ahoy Mr. Bond (its mini-wizard,
# started as a challenge), Godzilla's King of the Monsters, Metallica's songs - counts as that mode when a mode of ours
# takes the challenge's place, as a mode in that mode's place does. Which mode a challenge is: its name and the
# mode's, the challenge's words leading the mode's ("Ahoy Mr. Bond" / "Ahoy Mr Bond Wizard Mode").
def _words(name):
    s = re.sub(r"\b4th\b", "fourth", (name or "").lower())
    return re.findall(r"[a-z0-9]+", s)


def challenge_places(port_text):
    """``{challenge n: game mode id}`` for the port's challenges (`text challenge_name_<n>`) that are one of its game
    modes (`text block_name_<id>`, a start the port names): the one mode whose name begins with the challenge's words
    (exactly one; none when two would)."""
    text = port_text or ""
    modes = {int(m.group(1)): _words(m.group(2)) for m in re.finditer(r"^text\s+block_name_(\d+)\s+(.+)$", text, re.M)
             if re.search(r"^site\s+block_start_%s\s" % m.group(1), text, re.M)}
    out = {}
    for m in re.finditer(r"^text\s+challenge_name_(\d+)\s+(.+)$", text, re.M):
        cw = _words(m.group(2))
        hits = [i for i, mw in modes.items() if cw and mw[:len(cw)] == cw]
        if len(hits) == 1:
            out[int(m.group(1))] = hits[0]
    return out


def challenge_place_lines(port_text):
    """The `value challenge_place_<n> <id>` lines the port lacks (as :func:`missing_from`)."""
    places = challenge_places(port_text)
    if not places:
        return []
    lines = ["# PAD-710: the challenges that are one of the game's own modes: a mode taking the challenge counts as it"]
    lines += ["value challenge_place_%-8d %d" % (n, i) for n, i in sorted(places.items())]
    return missing_from(lines, port_text)
