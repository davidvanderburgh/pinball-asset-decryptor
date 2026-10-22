"""Port lines for a Spike 2 build's named Player Challenge picks, read from the game's own code (PAD-615;
MODE_SDK.md "A mode in the game's Challenge list"; tools/spike2_emu/modes/sdk/challenge_lines.py is the command line).

Stern's framework has a Player Challenge game on every Spike 2 title: the player picks it as the game starts and it
is a one-ball game (the game ends at the first ball's end). Some builds name the challenges a player can pick, one
game flag each, set as the game starts from the pick: James Bond LE and Pro 1.06 (FG_CHAOS_AT_CRAB_KEY_CHALLENGE ...
FG_HER_MAJESTYS_SECRET_SERVICE_CHALLENGE) and Stranger Things 1.13 / LE 1.12 / LE 1.13 (FG_DEMOGORGON_CHALLENGE ...
FG_FINAL_SHOWDOWN_CHALLENGE). Every challenge's module there has one handler on the ball's start event, of the same
shape:

    push {r3, lr}
    bl   <challenge game?>        mov r0, #<FG_PLAYER_CHALLENGE_MODE_ACTIVE>; b <flag get>
    cmp r0, #0 ; bne +8 ; mov r0, #1 ; pop {r3, pc}
    mov r0, #<its flag> ; bl <flag get> ; cmp r0, #0 ; beq (the return above)
    ... bl <its start>  (Ahoy Mr. Bond with 1: as a challenge)
    mov r0, #1 ; pop {r3, pc}

Those handlers are the sites a mode of ours takes a challenge's place at (`site challenge_go_<n>`, refused with 1
when a mode holds it, so the game's own never starts). The lines, in flag order (the order of the game's menu):

  site  challenge_go_<n>    the handler
  value challenge_flag_<n>  its flag
  text  challenge_name_<n>  its name, from the flag's ("Chaos at Crab Key")
  value challenge_on_flag   FG_PLAYER_CHALLENGE_MODE_ACTIVE

Other titles' challenges are other things (Godzilla's King of the Monsters, Venom's Knull levels, Rush's 2112, a
timed whole game on Bond 60th): no FG_<name>_CHALLENGE flag with a handler of this shape, so no lines.
Read-only (bytes in, lines out).
"""
import re
import struct

PUSH_R3_LR = 0xE92D4008
#: the flag names that name ONE challenge (not FG_..._CHALLENGE_ACTIVE, _COMPLETED...)
CHALLENGE_FLAG = re.compile(r"^FG_([A-Z0-9_]+?)_CHALLENGE$")
#: words the names keep as written
SMALL = {"AT", "THE", "ON", "OF", "AND", "A", "IN", "TO"}
NAME_FIX = {"MR": "Mr.", "HER MAJESTYS": "Her Majesty's", "GOLDFINGERS": "Goldfinger's"}


class Elf:
    def __init__(self, data):
        self.d = data if isinstance(data, (bytes, bytearray)) else open(data, "rb").read()
        d = self.d
        phoff, = struct.unpack_from("<I", d, 0x1c)
        phentsize, phnum = struct.unpack_from("<HH", d, 0x2a)
        self.segs = []
        for i in range(phnum):
            t, off, va, _pa, fsz, _msz, fl, _al = struct.unpack_from("<8I", d, phoff + i * phentsize)
            if t == 1:
                self.segs.append((off, va, fsz, fl))
        o, v, n = next((o, v, n) for o, v, n, f in self.segs if f & 1)
        self.text_va = v
        self.words = struct.unpack_from("<%dI" % (n // 4), d, o)

    def off(self, va):
        for o, v, n, _f in self.segs:
            if v <= va < v + n:
                return o + va - v
        return None

    def va(self, off):
        for o, v, n, _f in self.segs:
            if o <= off < o + n:
                return v + off - o
        return None

    def word(self, va):
        return struct.unpack_from("<I", self.d, self.off(va))[0]

    def cstr(self, va):
        o = self.off(va) if va else None
        if o is None:
            return None
        e = self.d.find(b"\0", o, o + 200)
        s = self.d[o:e] if e >= 0 else b""
        return s.decode() if s and all(32 <= c < 127 for c in s) else None


def flag_names(e):
    """The game's flag names, by id (the FG_ table: FG_INVALID at 0), or []."""
    m = re.search(rb"(?<=\0)FG_INVALID\0", e.d)
    if not m:
        return []
    want = struct.pack("<I", e.va(m.start()))
    i = 0
    while True:
        i = e.d.find(want, i)
        if i < 0:
            return []
        if i % 4 == 0:
            names, at = [], e.va(i)
            while True:
                s = e.cstr(e.word(at + 4 * len(names))) if e.off(at + 4 * len(names)) is not None else None
                if not s or not s.startswith("FG_"):
                    break
                names.append(s)
            if len(names) > 8:
                return names
        i += 1


def mov_r0(imm):
    """The words `mov r0, #imm` assembles to (the plain form for 0-255, else movw)."""
    out = {0xE3A00000 | imm} if imm < 256 else set()
    if imm < 0x10000:
        out.add(0xE3000000 | (imm >> 12) << 16 | imm & 0xFFF)
    return out


def bl_target(va, w):
    if w & 0xFF000000 != 0xEB000000:
        return None
    return (va + 8 + (((w & 0xFFFFFF) << 8 & 0xFFFFFFFF) - ((w & 0x800000) << 9) >> 6)) & 0xFFFFFFFF


def pretty(stem):
    words = stem.replace("_", " ")
    for k, v in NAME_FIX.items():
        words = re.sub(r"\b%s\b" % k, v.upper(), words)
    out = []
    for i, w in enumerate(words.split()):
        fixed = next((v for v in NAME_FIX.values() if v.upper() == w), None)
        out.append(fixed or (w.lower() if i and w in SMALL else w.capitalize()))
    return " ".join(out)


def find(elf):
    """(lines, notes): the port lines of `elf` (the game program's bytes or its path), and what was not found.

    PAD-619: two routes to a build's challenges. The named challenges' own ball-start handlers (Bond, Stranger
    Things: the shape above) when every named challenge has one; otherwise the start menu's (:func:`menu_generic`):
    each of its kinds that makes a challenge game with a flag of its own is a challenge, taken by its flag alone
    (`value challenge_flag_<n>`, no site: the runtime clears the flag as the ball starts). A build whose menu has
    no such kind (only the plain challenge game) still gets the menu lines: challenges of the modes' own."""
    e = Elf(elf)
    names = flag_names(e)
    if not names:
        return [], ["no FG_ flag name table"]
    try:
        on_flag = names.index("FG_PLAYER_CHALLENGE_MODE_ACTIVE")
    except ValueError:
        return [], ["no FG_PLAYER_CHALLENGE_MODE_ACTIVE flag"]
    lines, notes = _handler_route(e, names, on_flag)
    menu = menu_lines(e) if lines else []                       # Bond's own menu code (PAD-615 round 2)
    # PAD-630's end of the ball when the mode that took the pick ends - PAD-619: on every build that has it, not only
    # the handler builds: a plain challenge game (Avengers, The Beatles, Led Zeppelin, Godzilla) re-serves every
    # drain until its challenge ends the ball, so a mode's challenge game never ended without it
    end_ball = end_ball_lines(e)
    generic = None if menu else menu_generic(e, names, on_flag)
    if not lines and generic and generic["named"]:
        lines = ["value challenge_on_flag   %d" % on_flag]
        for n, (kind, flag) in enumerate(generic["named"]):
            stem = re.sub(r"^FG_|_ACTIVE$", "", names[flag])
            lines += ["# %s: menu kind %d sets flags %d and %d" % (pretty(_short(stem)), kind, on_flag, flag),
                      "value challenge_flag_%d  %d" % (n, flag),
                      "text  challenge_name_%d  %s" % (n, pretty(_short(stem)))]
    elif not lines and generic:
        lines = ["value challenge_on_flag   %d" % on_flag]
    if not lines and not generic:
        lines = table_lines(e, names, on_flag)                  # PAD-619: Godzilla's game-mode table
    if not lines and not generic:
        lines = gpm_lines(e, names, on_flag)                    # PAD-619: the GamePlayModes index (Jaws, ...)
    if not lines and not generic:
        lines = adapter_lines(e, names, on_flag)                # PAD-619: the adapter's static tables (Venom)
    if not lines and not generic and not menu:
        wide = menu_wide(e, names, on_flag)                   # PAD-619: TMNT's wide-entry start menu
        if wide:
            lines, menu = ["value challenge_on_flag   %d" % on_flag], wide
    if not lines and not generic and not menu:
        live = menu_live(e, names, on_flag)                   # PAD-619: Foo Fighters' live-applied menu
        if live:
            lines, menu = ["value challenge_on_flag   %d" % on_flag], live
    if not lines:
        return [], notes or ["no challenge list and no start menu of the known shape"]
    if generic:
        menu = generic["lines"]
    # PAD-640: a mode's challenge game keeps its own high score - on the handler builds (Bond, Stranger Things), where
    # the pick's flag stays set and the game files the game under that challenge's champion; PAD-663: on every other
    # build too, in HIGHEST SCORES' place, with the game's own records shut for that game
    named = sum(1 for l in lines if l.startswith("site  challenge_go_"))
    scores = scores_lines(e, named)
    if scores:
        scores += screen_lines(e)
    # PAD-643: a mode's challenge ball launched for the player, and the game's own ball-start work that skips a
    # challenge game run in a mode's
    return (flag_lines(e) + lines + balls_lines(e) + extra_ball_lines(e) + menu + end_ball + scores
            + launch_lines(e, names) + plain_lines(e, names, on_flag)), []


def balls_lines(e):
    """PAD-619: `site challenge_balls` - the framework's balls-per-game getter, one shape on every Spike 2 build:
        push {r4, r5, lr} ; mov r5, r0 ; sub sp, sp, #12 ; mov r0, #<AD_BALLS_PER_GAME> ; bl <adjustment> ;
        mov r4, r0 ; mov r0, r5 ; bl <...> ; cmp r0, #0 ...        (the setting, unless the game's mode says otherwise)
    The runtime has it say 1 while a mode's challenge game runs. Empty when it is not there, or not once."""
    from .adjustments import AdjustmentTable
    try:
        bpg = AdjustmentTable(e.d).by_name.get("AD_BALLS_PER_GAME")
    except ValueError:
        return []
    if bpg is None:
        return []
    w, base = e.words, e.text_va
    hits = [k for k in range(len(w) - 9) if w[k] == 0xE92D4030 and w[k + 1] == 0xE1A05000 and w[k + 2] == 0xE24DD00C
            and w[k + 3] in mov_r0(bpg) and bl_target(base + 4 * k + 16, w[k + 4]) is not None
            and w[k + 5] == 0xE1A04000 and w[k + 6] == 0xE1A00005
            and bl_target(base + 4 * k + 28, w[k + 7]) is not None and w[k + 8] == 0xE3500000]
    if len(hits) != 1:
        return []
    k = hits[0]
    out = ["site  challenge_balls     0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1])]
    # PAD-619: the older builds' per-player sum of the setting and the next (push ; mov r4, r0 ; mov r1, r4 ; mov r0,
    # #<bpg> ; bl ; mov r1, r4 ; mov r5, r0 ; mov r0, #<bpg + 1> ; bl ; add r0, r0, r5), what they end a game by
    two = [j for j in range(len(w) - 9) if (w[j] & 0xFFFF0000) == 0xE92D0000 and w[j + 1] == 0xE1A04000
           and w[j + 2] == 0xE1A01004 and w[j + 3] in mov_r0(bpg) and w[j + 5] == 0xE1A01004 and w[j + 6] == 0xE1A05000
           and w[j + 7] in mov_r0(bpg + 1) and w[j + 9] == 0xE0800005]
    if len(two) == 1:
        j = two[0]
        out.append("site  challenge_balls_2   0x%08x 0x%08x 0x%08x" % (base + 4 * j, w[j], w[j + 1]))
    return out


def extra_ball_lines(e):
    """PAD-619: `site challenge_extra_ball` - the framework's take-an-extra-ball test, one shape on every Spike 2 build:
        movw rX, <count> ; movt rX, <count> ; ldrb rY, [rX] ; adds r0, rY, #0 ; movne r0, #1 ; cmp r0, #0 ;
        subne rY, rY, #1 ; strbne rY, [rX] ; bx lr
    The ball's end asks it before the balls-per-game getter: an extra ball earned in a mode's challenge game (Star Wars
    ELG 1.10) was played as a second ball. The runtime has it say 0 then. Empty when it is not there, or not once."""
    w, base = e.words, e.text_va
    hits = []
    for k in range(len(w) - 9):
        a, b, c = w[k], w[k + 1], w[k + 2]
        rx = (a >> 12) & 0xF
        if (a & 0xFFF00000) != 0xE3000000 or (b & 0xFFF00000) != 0xE3400000 or (b >> 12) & 0xF != rx \
                or (c & 0xFFFF0FFF) != (0xE5D00000 | rx << 16):
            continue
        ry = (c >> 12) & 0xF
        if w[k + 3:k + 9] == (0xE2900000 | ry << 16, 0x13A00001, 0xE3500000, 0x12400001 | ry << 16 | ry << 12,
                              0x15C00000 | rx << 16 | ry << 12, 0xE12FFF1E):
            hits.append(k)
    if len(hits) != 1:
        return []
    k = hits[0]
    return ["site  challenge_extra_ball 0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1])]


def _short(stem):
    """A menu challenge's name from its flag's stem: CYGNUS_CHALLENGE_BOOK_1 -> CYGNUS_BOOK_1, RETRO_CHALLENGE ->
    RETRO, 2112_CHALLENGE -> 2112."""
    return re.sub(r"_+", "_", re.sub(r"(^|_)CHALLENGE(_|$)", "_", stem)).strip("_") or stem


def flag_lines(e):
    """PAD-619: the game's flag bitmap - `data game_flags` (the holder: the bitmap pointer at + game_flags_at) and
    `data game_flag_count` (its size in bits) - read off the flag functions' one shape on every Spike 2 build:
        cmp r0,#0 ; beq ; movw/movt r3,<count> ; ldr r3,[r3] ; cmp r0,r3 ; bhs ; movw r2,<holder> ; and r3,r0,#7 ;
        movt r2,<holder> ; mov ip,#1 ; ldr r1,[r2,#4] ; ldrb r2,[r1,r0,asr #3] ; bic|orr r3,r2,ip,lsl r3 ...
    Empty when it is not there, or not one holder."""
    fl = flag_functions(e)
    if not fl or fl["holder"] is None:
        return []
    return ["data  game_flags          0x%08x" % fl["holder"],
            "value game_flags_at       4",
            "data  game_flag_count     0x%08x" % fl["count"]]


def flag_functions(e):
    """{set, clear, holder, count} of the game's flag functions (see :func:`flag_lines`), or None."""
    w, base = e.words, e.text_va
    found, holders = {}, set()
    for k in range(12, len(w) - 3):
        if w[k] != 0xE5921004 or w[k + 1] != 0xE7D121C0:
            continue
        regs = {}
        for j in range(k - 12, k):
            x = w[j]
            if x & 0x0FF00000 == 0x03000000:
                regs[(x >> 12) & 0xF] = ((x >> 16) & 0xF) << 12 | (x & 0xFFF)
            elif x & 0x0FF00000 == 0x03400000 and ((x >> 12) & 0xF) in regs:
                r = (x >> 12) & 0xF
                regs[r] = regs[r] | (((x >> 16) & 0xF) << 12 | (x & 0xFFF)) << 16
                regs[("v", r)] = regs[r]
        start = next((j for j in range(k - 1, k - 14, -1) if w[j] == 0xE3500000), None)
        if start is None or ("v", 2) not in regs or ("v", 3) not in regs:
            continue
        kind = {0xE1C2331C: "clear", 0xE182331C: "set"}.get(w[k + 2])
        if kind:
            found[kind] = base + 4 * start
            holders.add((regs[("v", 2)], regs[("v", 3)]))
    if set(found) != {"set", "clear"} or len(holders) != 1:
        return None
    (holder, count), = holders
    return dict(found, holder=holder, count=count)


def _handler_route(e, names, on_flag):
    """PAD-615's route: each named challenge's own ball-start handler. (lines, notes); lines empty unless every named
    challenge has exactly one."""
    picks = [(i, CHALLENGE_FLAG.match(n).group(1)) for i, n in enumerate(names) if CHALLENGE_FLAG.match(n)]
    if not picks:
        return [], ["the build names no challenge (no FG_<name>_CHALLENGE flag)"]
    w, base = e.words, e.text_va
    # the "a challenge game?" predicates: mov r0, #on_flag ; b <flag get>
    on = mov_r0(on_flag)
    preds = {base + 4 * k for k in range(len(w) - 1) if w[k] in on and w[k + 1] & 0xFF000000 == 0xEA000000}
    found = {}
    n = len(w)
    for k in range(n - 1):
        if w[k] != PUSH_R3_LR or bl_target(base + 4 * k + 4, w[k + 1]) not in preds:
            continue
        for j in range(k + 2, min(k + 10, n - 1)):
            hit = next((f for f, _s in picks if w[j] in mov_r0(f)), None)
            if hit is None or bl_target(base + 4 * j + 4, w[j + 1]) is None:
                continue
            start = next((bl_target(base + 4 * q, w[q]) for q in range(j + 2, min(j + 10, n))
                          if bl_target(base + 4 * q, w[q]) is not None), None)
            found.setdefault(hit, []).append((base + 4 * k, start))
            break
    lines, notes = ["value challenge_on_flag   %d" % on_flag], []
    for n, (f, stem) in enumerate(picks):
        at = found.get(f, [])
        if len(at) != 1:
            notes.append("%s (flag %d): %d handlers of the shape" % (names[f], f, len(at)))
            continue
        va, start = at[0]
        lines += ["# %s: its handler starts 0x%x" % (pretty(stem), start or 0),
                  "site  challenge_go_%d    0x%08x 0x%08x 0x%08x" % (n, va, e.word(va), e.word(va + 4)),
                  "value challenge_flag_%d  %d" % (n, f),
                  "text  challenge_name_%d  %s" % (n, pretty(stem))]
    if notes:
        return [], notes
    return lines, notes


#: PAD-630: the framework's "end this ball now" - what the game's own challenge endings call in a challenge game
#: (Bond LE: Ahoy Mr. Bond's ending 0x1cda4 -> 0x3f79bc(1, 1)), so the ball drains dead and GAME OVER follows. It
#: opens on the game's status halfword: movw r2 / movt r2 (its address), a push, ldrh r3, [r2], orr r3, r3, #0x200,
#: orr r3, r3, #2, strh r3, [r2] (Bond LE/Pro, Stranger Things 1.13 and LE 1.13 take two words, LE 1.12 one).
END_BALL_WORDS = (0xE1D230B0, 0xE3833C02, 0xE3833002, 0xE1C230B0)


def end_ball_lines(e):
    """The `site challenge_end_ball` line (empty when the build has no one function of that shape)."""
    w, base = e.words, e.text_va
    at = []
    for k in range(len(w) - 12):
        if (w[k] & 0xFFF0F000) != 0xE3002000 or (w[k + 1] & 0xFFF0F000) != 0xE3402000:
            continue
        body, q = w[k + 2:k + 12], 0
        for x in body:
            if q < len(END_BALL_WORDS) and x == END_BALL_WORDS[q]:
                q += 1
        if q == len(END_BALL_WORDS) and any(x & 0xFFFFF000 == 0xE92D4000 for x in body[:4]):
            at.append(k)
    if len(at) > 1:
        # PAD-619: more than one of that opening (Rush 1.19, Iron Maiden 1.18, TMNT, Venom, Mando, Foo Fighters): the
        # end of the ball takes its argument in r4 (mov r4, r0) and turns the flippers off (mov r1, #0x1000 ; mov r0,
        # #0 ; bl), as Bond's and Rush 1.18's do
        at = [k for k in at if 0xE1A04000 in w[k + 2:k + 8]
              and any(w[j] == 0xE3A01A01 and w[j + 1] == 0xE3A00000 for j in range(k, min(k + 40, len(w) - 1)))]
    if len(at) != 1:
        return []
    k = at[0]
    return ["# the game's own challenges end the ball when they are over: so does a mode that took the pick",
            "site  challenge_end_ball  0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1])]


def launch_lines(e, names):
    """PAD-643: `site ball_launch` - the framework's launch-button handler, one shape on every Spike 2 build:
        push {r4, lr} ; movw/movt r4, <auto plunger device> ; sub sp, sp, #8 ; ldrh r0, [r4, #<id>] ; ...
        mov r0, #<FG_MBDEV_AUTO_PLUNGER_PLAYER_CONTROL> ; bl <flag get> ; ...
        mov r0, #<FG_MBDEV_AUTO_PLUNGER_BALL_IN_DEVICE> ; bl <flag get> ; ... mov r2, #8 ; bl <fire>
    (fires the auto plunger when a ball waits in it, else does nothing), with those two flags: the runtime calls it
    for the player as a mode's challenge ball starts. Empty when it is not there, or not once."""
    try:
        wait, ball = names.index("FG_MBDEV_AUTO_PLUNGER_PLAYER_CONTROL"), names.index("FG_MBDEV_AUTO_PLUNGER_BALL_IN_DEVICE")
    except ValueError:
        return []
    w, base = e.words, e.text_va
    hits = []
    for k in range(len(w) - 40):
        if w[k] != 0xE92D4010 or (w[k + 4] & 0xFFFFF0F0) != 0xE1D400B0:
            continue
        win = w[k + 1:k + 40]
        for j, x in enumerate(win):              # up to the next function's push
            if (x & 0xFFFF0000) == 0xE92D0000:
                win = win[:j]
                break
        at_wait = [j for j, x in enumerate(win) if x in mov_r0(wait)]
        at_ball = [j for j, x in enumerate(win) if x in mov_r0(ball)]
        at_fire = [j for j, x in enumerate(win) if x == 0xE3A02008]
        if at_wait and at_ball and at_fire and at_wait[0] < at_ball[0] < at_fire[0]:
            hits.append(k)
    if len(hits) != 1:
        return []
    k = hits[0]
    return ["# a mode's challenge ball launched for the player: the launch button's handler, while these flags say a "
            "ball waits in the auto plunger",
            "site  ball_launch         0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1]),
            "value ball_launch_flag       %d" % ball,
            "value ball_launch_wait_flag  %d" % wait]


def plain_lines(e, names, on_flag):
    """PAD-643: `site challenge_plain_<k>` - the game's ball-start handlers that set its skill shot up only OUTSIDE a
    challenge game (James Bond LE / Pro 1.06, bus 34: the super skill shot whose process opens the top control gate
    to the loop while the left flipper button is held at the launch):
        push {.., lr} ; ... (10 words at most) bl <challenge game?> ; cmp r0, #0 ; bne <out> ; ...
        mov r0, #<a FG_..SKILL_SHOT.. flag> ; bl <flag set|clear>        (within 40 words)
    where <challenge game?> is `mov r0, #<FG_PLAYER_CHALLENGE_MODE_ACTIVE> ; b <flag get>`. In a mode's challenge
    game the runtime runs each with the challenge flag cleared for the call. No other build's skill shot asks the
    challenge flag this way (PAD-643 sweep of 69 builds). At most 4."""
    fl = flag_functions(e)
    skill = {i for i, n in enumerate(names) if "SKILL_SHOT" in n}
    if not fl or not skill:
        return []
    w, base = e.words, e.text_va
    asks = {base + 4 * k for k in range(len(w) - 1)
            if w[k] in mov_r0(on_flag) and (w[k + 1] & 0xFF000000) == 0xEA000000}
    sets = {fl["set"], fl["clear"]}
    out = []
    for k in range(len(w) - 3):
        if bl_target(base + 4 * k, w[k]) not in asks or w[k + 1] != 0xE3500000 or (w[k + 2] & 0xFF000000) != 0x1A000000:
            continue
        s = next((j for j in range(k - 1, max(k - 11, -1), -1) if (w[j] & 0xFFFF4000) == 0xE92D4000), None)
        if s is None or any((w[j] & 0xFFFF0000) == 0xE92D0000 for j in range(s + 1, k)):
            continue
        if not any(w[j] in mov_r0(f) and bl_target(base + 4 * j + 4, w[j + 1]) in sets
                   for j in range(k, min(k + 40, len(w) - 1)) for f in skill):
            continue
        if len(out) < 4:
            out.append("site  challenge_plain_%d   0x%08x 0x%08x 0x%08x" % (len(out), base + 4 * s, w[s], w[s + 1]))
    if not out:
        return []
    return ["# the game's skill shot set up at the ball's start only outside a challenge game: in a mode's one too"] + out


def rot_imm(w):
    rot, imm = (w >> 8) & 0xF, w & 0xFF
    return ((imm >> (2 * rot)) | (imm << (32 - 2 * rot))) & 0xFFFFFFFF if rot else imm


#: PAD-615 round 2: the game's own start menu (CHOOSE YOUR MODE OF PLAY, both flipper buttons held in attract), Bond
#: LE/Pro 1.06. One function builds the menu's list on its stack - 12-byte entries {kind, caption message id, name}
#: from sp+<list_at>, their count at sp+<count_at> - and, as the player selects, jumps on the entry's kind (3..7: the
#: five challenges). Its two hook points, each two plain words the runtime moves:
#:   after the list is built:  sub r0, r0, #1 ; cmp r0, #5 ; movwls r3, ... ; movhi r4, #0   (the Default Game Mode read)
#:   at the pick:              ldr r3, [r3, #-n] ; sub r3, r3, #1 ; cmp r3, #7 ; ldrls pc, [pc, r3, lsl #2]
MENU_AT = (0xE2400001, 0xE3500005)
PICK_AT = (0xE2433001, 0xE3530007, 0x979FF103)


def menu_lines(e):
    """The start menu's port lines (empty when the build has no such menu code): its two sites, where the list and
    its count are on the menu function's stack, how many entries fit before the next local, the first challenge's
    kind and the caption message the game gives a challenge entry."""
    w, base = e.words, e.text_va
    n = len(w)
    menu = [k for k in range(n - 4) if (w[k], w[k + 1]) == MENU_AT and (w[k + 2] & 0xFFF0F000) == 0x93003000
            and w[k + 3] == 0x83A04000]
    pick = [k for k in range(1, n - 3) if tuple(w[k:k + 3]) == PICK_AT and (w[k - 1] & 0xFFFFF000) == 0xE5133000]
    caption = [k for k in range(n - 2) if w[k] == 0xE3A0C003 and (w[k + 1] & 0xFFF0F000) == 0xE3002000
               and (w[k + 2] & 0xFFF0F000) == 0xE3000000]
    if len(menu) != 1 or len(pick) != 1 or len(caption) != 1:
        return []
    m, k = menu[0], pick[0]
    back = w[k - 1] & 0xFFF                                   # ldr r3, [r3, #-back]: the entry's kind
    top = next((rot_imm(w[q] & 0xFFF) for q in range(k - 2, k - 8, -1) if (w[q] & 0xFFFFF000) == 0xE28D2000), None)
    count = next((w[q] & 0xFFF for q in range(m + 4, m + 24) if (w[q] & 0xFFFFF000) == 0xE59D1000), None)
    after = [rot_imm(w[q] & 0xFFF) for q in range(k - 24, k) if (w[q] & 0xFFFFF000) == 0xE28D0000]
    if top is None or count is None:
        return []
    list_at = top - back
    ends = [a for a in after if a > list_at]
    if not ends:
        return []
    cap = (min(ends) - list_at) // 12
    cw = w[caption[0] + 1]
    menu_va, pick_va = base + 4 * m, base + 4 * k
    return ["# the start menu (CHOOSE YOUR MODE OF PLAY): our names on the challenges modes take, and challenges of "
            "their own",
            "site  challenge_menu      0x%08x 0x%08x 0x%08x" % (menu_va, w[m], w[m + 1]),
            "site  challenge_menu_pick 0x%08x 0x%08x 0x%08x" % (pick_va, w[k], w[k + 1]),
            "value challenge_menu_list_at   %d" % list_at,
            "value challenge_menu_count_at  %d" % count,
            "value challenge_menu_cap       %d" % cap,
            "value challenge_menu_kind      3",
            "value challenge_menu_caption   %d" % ((cw >> 4 & 0xF000) | (cw & 0xFFF))]


#: PAD-619: the start menu on the other builds of Bond's generation (Aerosmith, Avengers, Batman 66, The Beatles, Deadpool,
#: Elvira, Guardians, Iron Maiden, JP The Pin, Led Zeppelin, The Munsters, Rush, Star Wars ELG, Stranger Things, Sword
#: of Rage, their versions): the same function shape as Bond's - the list on the stack (12- or 16-byte entries {u32
#: kind, u16 caption message, char *name, ...}), a loop that reads the buttons every frame and, whenever the
#: selection is shown, jumps on its kind to set the game's mode flags:
#:   every frame:     mov rX, r0 ; tst rX, #0x80                  (the buttons just read; 0x80 = Start)
#:   the kind jump:   ldr r3, [r3, #-back] ; sub r3, r3, #1 ; cmp r3, #N ; ldrls pc, [pc, r3, lsl #2]
PICK_LDR = 0xE5103000          # ldr r3, [r3, #-imm]  (mask 0xFFF0F000)


def _pick_sites(e):
    w = e.words
    return [k for k in range(len(w) - 4) if (w[k] & 0xFFF0F000) == PICK_LDR and w[k + 1] == 0xE2433001
            and (w[k + 2] & 0xFFFFFF00) == 0xE3530000 and w[k + 3] == 0x979FF103]


def _chain_sites(e):
    """PAD-619: the compare-chain pick (Star Wars' generation): ldr r3, [r3, #-back] after `add r3, sp, #T ; add
    r3, r3, rC` (rC = cursor << 4), then cmp r3, #n ; beq - word indexes of the ldr."""
    w = e.words
    return [k for k in range(3, len(w) - 2) if (w[k] & 0xFFF0F000) == PICK_LDR and (w[k + 1] & 0xFFFFFF00) == 0xE3530000
            and (w[k + 2] & 0xFF000000) == 0x0A000000 and (w[k - 3] & 0xFFFFF000) == 0xE28D3000
            and (w[k - 2] & 0xFFFFFFF0) == 0xE0833000 and (w[k - 1] & 0x0E000010) == 0
            and (w[k - 1] & 0xF000F) != 0xF000F]


def _case_flags(e, va, r0, fl, limit=40):
    """The flags one case of a kind jump sets (calls of the set function), following its branches until another
    call (the shared tail's first) or a return. r0: what the code before the jump left in r0."""
    w, base, out, seen = e.words, e.text_va, [], set()
    for _ in range(limit):
        k = (va - base) // 4
        if va in seen or not 0 <= k < len(w):
            break
        seen.add(va)
        x = w[k]
        if x & 0x0FFF0000 == 0x03A00000 and x >> 28 == 0xE and (x >> 12) & 0xF == 0:
            r0 = rot_imm(x & 0xFFF)
        elif x & 0x0FF00000 == 0x03000000 and x >> 28 == 0xE and (x >> 12) & 0xF == 0:
            r0 = ((x >> 16) & 0xF) << 12 | (x & 0xFFF)
        t = bl_target(va, x)
        if t is not None:
            if t == fl["set"]:
                out.append(r0)
            elif t != fl["clear"]:
                break
            r0 = None
        elif x & 0x0F000000 == 0x0A000000 and x >> 28 == 0xE:
            off = x & 0xFFFFFF
            va = va + 8 + 4 * (off - (1 << 24) if off & 0x800000 else off)
            continue
        elif (x & 0xFFFF0000) == 0xE8BD0000 or x == 0xE12FFF1E:
            break
        va += 4
    return out


def message_table(e):
    """(va, count) of the game's message table: one pointer per message id to a record of five language strings,
    found from the record of "CHOOSE YOUR MODE OF PLAY"; (None, 0) when not there."""
    d, z = e.d, bytes(1)

    def ok(off):
        r = struct.unpack_from("<I", d, off)[0]
        ro = e.off(r)
        if ro is None:
            return False
        p = struct.unpack_from("<I", d, ro)[0]
        po = e.off(p)
        if po is None:
            return False
        end = d.find(z, po, po + 400)
        return end >= 0 and all(32 <= c < 256 or c in (9, 10) for c in d[po:end])

    i = d.find(z + b"CHOOSE YOUR MODE OF PLAY" + z)
    if i < 0:
        return None, 0
    pk = struct.pack("<I", e.va(i + 1))
    best = (None, 0)
    rec = d.find(pk)
    while rec >= 0:
        if rec % 4 == 0:
            pk2 = struct.pack("<I", e.va(rec))
            a = d.find(pk2)
            while a >= 0:
                if a % 4 == 0:
                    b = a
                    while ok(b - 4):
                        b -= 4
                    n = 0
                    while ok(b + 4 * n):
                        n += 1
                    if n > best[1]:
                        best = (e.va(b), n)
                a = d.find(pk2, a + 1)
        rec = d.find(pk, rec + 1)
    return best


def message_text(e, table, i):
    return e.cstr(e.word(e.word(table + 4 * i))) or ""


def challenge_caption(e):
    """The message id the start menu shows over a challenge (CHALLENGE; The Beatles: CHALLENGE MODE): the first after
    CHOOSE YOUR MODE OF PLAY's."""
    table, n = message_table(e)
    if not table:
        return None
    head = next((i for i in range(n) if message_text(e, table, i) == "CHOOSE YOUR MODE OF PLAY"), None)
    if head is None:
        return None
    return next((i for i in range(head, min(n, head + 40)) if message_text(e, table, i) in ("CHALLENGE", "CHALLENGE MODE")),
                None)


def menu_generic(e, names, on_flag):
    """PAD-619: the start menu of a build of Bond's generation (see PICK_LDR). None when it is not there, else
    {lines, named: [(kind, flag)], plain: kind or None}: the port lines, the kinds that make a challenge game with a
    flag of their own (in kind order: challenge 0, 1, ..) and the kind of the plain one-ball challenge game."""
    w, base = e.words, e.text_va
    picks = _pick_sites(e)
    fl = flag_functions(e)
    chain = False
    if not picks:
        picks, chain = _chain_sites(e), True                    # PAD-619: Star Wars' compare chain
    if len(picks) != 1 or not fl:
        return None
    k = picks[0]
    back = w[k] & 0xFFF
    pre = w[k - 8:k]
    tops = [rot_imm(x & 0xFFF) for x in pre if (x & 0xFFFF0000) == 0xE28D0000]
    if not tops:
        return None
    top = tops[-1]
    list_at = top - back
    entry = 16 if any((x & 0xFFFF0FF0) == 0xE1A00200 for x in pre) else 12        # mov rd, rm, lsl #4
    frames = [j for j in range(max(0, k - 1500), k) if (w[j] & 0xFFFF0FFF) == 0xE1A00000
              and (w[j + 1] & 0xFFF0FFFF) == 0xE3100080 and ((w[j] >> 12) & 0xF) == ((w[j + 1] >> 16) & 0xF)]
    if not frames:
        return None
    fr = frames[-1]
    # the count: the cursor's wrap past the last entry - ldr r3, [sp, #count] ; ... sub r3, r3, #1 ; cmp r3, <cursor>
    count_at = next((w[j] & 0xFFF for j in range(fr, min(len(w) - 4, fr + 600)) if (w[j] & 0xFFFFF000) == 0xE59D3000
                     and 0xE2433001 in w[j + 1:j + 4] and any((x & 0xFFFFFFF0) == 0xE1530000 for x in w[j + 2:j + 5])),
                    None)
    start = next((j for j in range(fr, max(0, fr - 3000), -1) if (w[j] & 0xFFFF4000) == 0xE92D4000), None)
    count_reg = None
    if count_at is None:
        # PAD-619, Elvira 1.13: the count kept in a callee-saved register the whole loop - the cursor's wrap reads
        # `sub r3, rN, #1 ; cmp r3, <cursor>`; the runtime then hooks the frame with every register saved
        count_reg = next(((w[j] >> 16) & 0xF for j in range(fr, min(len(w) - 2, fr + 200))
                          if (w[j] & 0xFFF0FFFF) == 0xE2403001 and 4 <= (w[j] >> 16) & 0xF <= 11
                          and any((x & 0xFFFFFFF0) == 0xE1530000 for x in w[j + 1:j + 3])), None)
    if (count_at is None and count_reg is None) or start is None:
        return None
    # the room: up to the first local object above the list the function hands a call (add r0, sp, #x ; bl)
    above = [rot_imm(w[j] & 0xFFF) for j in range(start, k + 1500) if (w[j] & 0xFFFFF000) == 0xE28D0000
             and bl_target(base + 4 * j + 4, w[j + 1]) is not None]
    above = [a for a in above if list_at < a and a != top]
    if not above:
        return None
    cap = (min(above) - list_at) // entry
    # what each kind sets: r0 as the code before the jump left it
    r0 = None
    for j in range(k - 6, k):
        x = w[j]
        if x & 0x0FFF0000 == 0x03A00000 and x >> 28 == 0xE and (x >> 12) & 0xF == 0:
            r0 = rot_imm(x & 0xFFF)
    caption = challenge_caption(e)
    if chain:
        # no kind of this menu makes a challenge game (Star Wars LE/Pro 1.30/1.31: Standard, Tournament, Competition,
        # DJ Mixer); ours become Standard's (0) at the pick, the runtime hands the ball to the mode. The hook sits a
        # word early (`mov r7, r0 ; ldr r3, [r3, #-back]`: the cmp/beq after it cannot move) and reads the entry
        # through r3.
        if caption is None:
            return None
        lines = ["# the start menu (CHOOSE YOUR MODE OF PLAY): challenges of the modes' own - no kind of the game's "
                 "makes a challenge game, so ours play as Standard (kind 0) and the runtime hands the ball to the mode",
                 "site  challenge_menu      0x%08x 0x%08x 0x%08x" % (base + 4 * fr, w[fr], w[fr + 1]),
                 "site  challenge_menu_pick 0x%08x 0x%08x 0x%08x" % (base + 4 * (k - 1), w[k - 1], w[k]),
                 "value challenge_menu_pick_back %d" % back,
                 "value challenge_menu_list_at   %d" % list_at,
                 "value challenge_menu_count_at  %d" % count_at,
                 "value challenge_menu_cap       %d" % cap,
                 "value challenge_menu_entry     %d" % entry,
                 "value challenge_menu_kind      0",
                 "value challenge_menu_slot      -1",
                 "value challenge_menu_sets_on   1",
                 "value challenge_menu_caption   %d" % caption]
        return {"lines": lines, "named": [], "plain": None}
    n = (w[k + 2] & 0xFF) + 1
    named, plain = [], None
    for i in range(n):
        flags = _case_flags(e, e.word(base + 4 * (k + 5) + 4 * i), r0, fl)
        if on_flag not in flags:
            continue
        own = [f for f in flags if f != on_flag and not names[f].startswith("FG_PLAYER_")]
        if not own and len(flags) == 1 and plain is None:
            plain = i + 1
        elif len(own) == 1 and len(flags) == 2:
            named.append((i + 1, own[0]))
    if caption is None or (plain is None and not named):
        return None
    kind = plain if plain is not None else named[0][0]
    lines = ["# the start menu (CHOOSE YOUR MODE OF PLAY): our names on the challenges modes take, and challenges of "
             "their own - %s" % ("the plain challenge game (kind %d)" % plain if plain is not None
                                 else "challenge 0's kind (%d), its own start stopped" % kind),
             "site  challenge_menu      0x%08x 0x%08x 0x%08x" % (base + 4 * fr, w[fr], w[fr + 1]),
             "site  challenge_menu_pick 0x%08x 0x%08x 0x%08x" % (base + 4 * k + 4, w[k + 1], w[k + 2]),
             "value challenge_menu_list_at   %d" % list_at,
             ("value challenge_menu_count_at  %d" % count_at if count_at is not None
              else "value challenge_menu_count_reg %d   # the count in r%d (Elvira)" % (count_reg, count_reg)),
             "value challenge_menu_cap       %d" % cap,
             "value challenge_menu_entry     %d" % entry,
             "value challenge_menu_kind      %d" % kind,
             "value challenge_menu_slot      %d" % (-1 if plain is not None else 0),
             "value challenge_menu_caption   %d" % caption]
    return {"lines": lines, "named": named, "plain": plain}


#: PAD-619: Godzilla's game-mode table (Godzilla Pro 1.15 / 1.16, LE 1.16): 32-byte entries {u32 kind, u16 flag, u16
#: flag2, u16 caption message, u16 name message, ...}, filled by one constructor, read by accessors of one shape:
#:   cmp r1, #<last> ; movwls r3, <table> ; movtls r3, <table> ; addls r3, r3, r1, lsl #5 ; ldrhls r0, [r3, #4]
#: An entry whose flag is the challenge game's and whose flag2 is set is a challenge, picked by flag2 (KOTM 40, Time
#: Attack 41): taken by its flag alone as the ball starts, like Rush's.
def table_lines(e, names, on_flag):
    """The port lines of a game-mode table's challenges (see above), or []."""
    w, base = e.words, e.text_va
    tables = set()
    for k in range(len(w) - 4):
        x = w[k]
        if x & 0xFFFFFF00 == 0xE3510000 and w[k + 1] & 0xFFF0F000 == 0x93003000 and w[k + 2] & 0xFFF0F000 == 0x93403000 \
                and w[k + 3] == 0x90833281 and w[k + 4] == 0x91D300B4:
            lo = ((w[k + 1] >> 16) & 0xF) << 12 | (w[k + 1] & 0xFFF)
            hi = ((w[k + 2] >> 16) & 0xF) << 12 | (w[k + 2] & 0xFFF)
            tables.add(((hi << 16) | lo, (x & 0xFF) + 1))
    if len(tables) != 1:
        return []
    (tbl, n), = tables
    entries = _table_entries(e, tbl, n)
    if not entries:
        return []
    table, count = message_table(e)
    lines, slot = [], 0
    for i, (flag, flag2, name) in enumerate(entries):
        if flag != on_flag or not flag2 or flag2 >= len(names) or names[flag2].startswith("FG_PLAYER_") and \
                not names[flag2].endswith("_CHALLENGE") and not names[flag2].endswith("_CHALLENGE_MODE"):
            continue
        words = message_text(e, table, name) if table and name < count else ""
        stem = re.sub(r"[^A-Z0-9]+", "_", words.upper()).strip("_") or re.sub(r"^FG_(PLAYER_)?", "", names[flag2])
        lines += ["# entry %d of the game-mode table at 0x%08x: flags %d and %d" % (i, tbl, flag, flag2),
                  "value challenge_flag_%d  %d" % (slot, flag2),
                  "text  challenge_name_%d  %s" % (slot, pretty(_short(stem))),
                  "value challenge_name_msg_%d  %d" % (slot, name)]     # where the start menu shows its name
        slot += 1
    return (["value challenge_on_flag   %d" % on_flag] + lines) if slot else []


def _table_entries(e, tbl, n):
    """[(flag, flag2, name message)] of the table's n entries, read off its constructor's stores: the function that
    stores to tbl + 32 * i + 4 / 6 / 10 from immediates (mov/movw), the table in a register by movw/movt or a literal."""
    w, base = e.words, e.text_va
    for k in range(len(w) - 1):
        x = w[k]
        # the constructor names the table: movw/movt rX, tbl (or ldr rX, =tbl) followed by strh's through rX
        reg = None
        if x & 0x0FF00000 == 0x03000000 and (((x >> 16) & 0xF) << 12 | (x & 0xFFF)) == tbl & 0xFFFF:
            for j in range(k + 1, min(k + 6, len(w))):
                y = w[j]
                if y & 0x0FF00000 == 0x03400000 and (y >> 12) & 0xF == (x >> 12) & 0xF \
                        and (((y >> 16) & 0xF) << 12 | (y & 0xFFF)) == tbl >> 16:
                    reg = (x >> 12) & 0xF
                    break
        elif x & 0xFFFF0000 == 0xE59F0000:
            lit = base + 4 * k + 8 + (x & 0xFFF)
            if e.off(lit) is not None and e.word(lit) == tbl:
                reg = (x >> 12) & 0xF
        if reg is None:
            continue
        regs, mem = {}, {}
        for j in range(k, min(k + 600, len(w))):
            y = w[j]
            if y >> 28 != 0xE:
                continue
            rd = (y >> 12) & 0xF
            if y & 0x0FFF0000 == 0x03A00000:
                regs[rd] = rot_imm(y & 0xFFF)
            elif y & 0x0FF00000 == 0x03000000:
                regs[rd] = ((y >> 16) & 0xF) << 12 | (y & 0xFFF)
            elif y & 0x0FFF0000 == 0x03E00000:
                regs[rd] = ~rot_imm(y & 0xFFF) & 0xFFFFFFFF
            elif y & 0x0FF000F0 == 0x01C000B0 and (y >> 16) & 0xF == reg:     # strh rd, [reg, #imm]
                off = ((y >> 4) & 0xF0) | (y & 0xF)
                if rd in regs:
                    mem[off] = regs[rd] & 0xFFFF
            elif (y & 0xFFFF0000) == 0xE8BD0000 or y == 0xE12FFF1E:
                break
        entries = [(mem.get(32 * i + 4), mem.get(32 * i + 6, 0), mem.get(32 * i + 10, 0)) for i in range(n)]
        if sum(1 for f, _f2, _m in entries if f) >= 3:
            return [(f or 0, f2, m) for f, f2, m in entries]
    return []


#: PAD-619: the GamePlayModes builds whose challenges set FG_PLAYER_CHALLENGE_MODE_ACTIVE alone (Jaws, John Wick,
#: Metallica, King Kong, X-Men, Jurassic Park LE/Pro): the framework's singleton GamePlayModes (typeinfo
#: `13GamePlayModes`) holds the current game-play mode's index at +8 (Jaws Pro 1.02: 0x855368, read by 0x5e9f0). The
#: game's table of them (GamePlayModeAdapter's) is 28-byte entries {u32 index, u16 flag, u16 msg x3, u32 kind, u8 x2,
#: std::string name at +20}, read by accessors of one shape:
#:   cmp r1, #<last> ; rsbls r1, r1, r1, lsl #3 ; movwls r3, <tbl> ; movtls r3, <tbl> ; addls r1, r3, r1, lsl #2
#: and filled by one constructor (read here by a small emulation of its stores). An entry whose flag is the challenge
#: game's is a challenge, picked by its index; Standard's (the first sys_standard with no flag) is what a mode's
#: challenge game plays instead.
GPM_ENTRY = 28


def _imm16(x):
    return ((x >> 16) & 0xF) << 12 | (x & 0xFFF)


def _lit(e, va, x):
    """The word an `ldr rX, [pc, #+/-imm]` at va loads, or None (not one, or off the image)."""
    if x & 0xFF7F0000 != 0xE51F0000:
        return None
    lit = va + 8 + ((x & 0xFFF) if x & 0x00800000 else -(x & 0xFFF))
    return e.word(lit) if e.off(lit) is not None else None


def _refs(d, v):
    p, out = struct.pack("<I", v), []
    i = d.find(p)
    while i >= 0:
        if i % 4 == 0:
            out.append(i)
        i = d.find(p, i + 1)
    return out


def _gpm_singleton(e):
    """The GamePlayModes singleton's address, or None: its vtable (by the typeinfo name), the constructor that stores
    that vptr, and the one movw/movt r0 + bl that constructor."""
    d = e.d
    i = d.find(b"\x0013GamePlayModes\x00")
    if i < 0:
        return None
    name = e.va(i + 1)
    vptrs = set()
    for ti_off in _refs(d, name):
        ti = e.va(ti_off) - 4
        for vt_off in _refs(d, ti):
            vptrs.add(e.va(vt_off) + 4)
    w, base = e.words, e.text_va
    ctors, lo = set(), {}
    for k, x in enumerate(w):
        hit = False
        if x & 0x0FF00000 == 0x03000000:
            lo[(x >> 12) & 0xF] = (k, _imm16(x))
        elif x & 0x0FF00000 == 0x03400000 and (x >> 12) & 0xF in lo and k - lo[(x >> 12) & 0xF][0] < 8:
            hit = (_imm16(x) << 16 | lo[(x >> 12) & 0xF][1]) in vptrs
        elif x & 0xFF7F0000 == 0xE51F0000:
            hit = _lit(e, base + 4 * k, x) in vptrs
        if hit:
            ctors.add(base + 4 * k)                          # the load may be its first instruction (Godzilla)
            for j in range(k, max(k - 12, 0), -1):           # the function starts after the one before returns
                if w[j - 1] == 0xE12FFF1E or w[j - 1] & 0xFFFF8000 == 0xE8BD8000:
                    ctors.add(base + 4 * j)
                    break
    singles = set()
    for k in range(2, len(w)):
        if w[k] & 0x0F000000 == 0x0B000000 and bl_target(base + 4 * k, w[k]) in ctors:
            a, b = w[k - 2], w[k - 1]
            if a & 0xFFF0F000 == 0xE3000000 and b & 0xFFF0F000 == 0xE3400000 and (a >> 12) & 0xF == 0 \
                    and (b >> 12) & 0xF == 0:
                singles.add(_imm16(b) << 16 | _imm16(a))
    return singles.pop() if len(singles) == 1 else None


def _gpm_table(e):
    """(table va, entries) of the GamePlayModeAdapter's table, by its accessors' one shape; (None, 0)."""
    w, found = e.words, set()
    for k in range(len(w) - 4):
        if w[k] & 0xFFFFFF00 == 0xE3510000 and w[k + 1] == 0x90611181 and w[k + 2] & 0xFFF0F000 == 0x93003000 \
                and w[k + 3] & 0xFFF0F000 == 0x93403000 and w[k + 4] == 0x90831101:
            found.add((_imm16(w[k + 3]) << 16 | _imm16(w[k + 2]), (w[k] & 0xFF) + 1))
    return found.pop() if len(found) == 1 else (None, 0)


def _gpm_entries(e, tbl, n):
    """{i: {"index", "flag", "msgs", "name"}} of the table, read off the constructor that loads tbl into a register:
    its stores (str/strh/strb, immediate, register and post-indexed offsets) emulated from immediates, and its string
    assignments (bl with r0 = an entry's name field, r1 = a C string)."""
    w, base = e.words, e.text_va
    for k in range(len(w) - 1):
        x = w[k]
        if x & 0xFF7F0000 == 0xE51F0000:                     # ldr rX, =tbl
            if _lit(e, base + 4 * k, x) != tbl:
                continue
        elif not (x & 0xFFF00000 == 0xE3000000 and _imm16(x) == tbl & 0xFFFF and any(
                z & 0xFFF00000 == 0xE3400000 and (z >> 12) & 0xF == (x >> 12) & 0xF and _imm16(z) == tbl >> 16
                for z in w[k + 1:k + 4])):
            continue
        regs, mem, names = {}, {}, {}
        for j in range(k, min(k + 1200, len(w))):
            z = w[j]
            if z >> 28 != 0xE:
                continue
            r_d, r_n = (z >> 12) & 0xF, (z >> 16) & 0xF
            if z & 0x0FFF0000 == 0x03A00000:
                regs[r_d] = rot_imm(z & 0xFFF)
            elif z & 0x0FFF0000 == 0x03E00000:
                regs[r_d] = ~rot_imm(z & 0xFFF) & 0xFFFFFFFF
            elif z & 0x0FF00000 == 0x03000000:
                regs[r_d] = _imm16(z)
            elif z & 0x0FF00000 == 0x03400000:
                regs[r_d] = (regs[r_d] & 0xFFFF) | _imm16(z) << 16 if regs.get(r_d) is not None else None
            elif z & 0x0FE00000 == 0x02800000:                                                 # add rd, rn, #imm
                regs[r_d] = (regs[r_n] + rot_imm(z & 0xFFF)) & 0xFFFFFFFF if regs.get(r_n) is not None else None
            elif z & 0x0FE00000 == 0x02400000:                                                 # sub rd, rn, #imm
                regs[r_d] = (regs[r_n] - rot_imm(z & 0xFFF)) & 0xFFFFFFFF if regs.get(r_n) is not None else None
            elif z & 0x0FFF0FF0 == 0x01A00000:                                                 # mov rd, rm
                regs[r_d] = regs.get(z & 0xF)
            elif z & 0xFF7F0000 == 0xE51F0000:
                regs[r_d] = _lit(e, base + 4 * j, z)
            elif z & 0x0F000000 == 0x0B000000:                                                 # bl
                a0, a1 = regs.get(0), regs.get(1)
                if a0 is not None and a1 is not None and tbl <= a0 < tbl + GPM_ENTRY * n:
                    c = e.cstr(a1)
                    if c:
                        names[(a0 - tbl) // GPM_ENTRY] = c
                for r in (0, 1, 2, 3, 12, 14):
                    regs.pop(r, None)
            elif (z & 0xFFFF0000) == 0xE8BD0000 or z == 0xE12FFF1E:
                break
            else:
                addr, size = None, None
                if z & 0x0E100000 == 0x04000000 and z & 0x01000000 and regs.get(r_n) is not None:   # str/strb imm
                    off = z & 0xFFF
                    addr = regs[r_n] + (off if z & 0x00800000 else -off)
                    size = 1 if z & 0x00400000 else 4
                elif z & 0x0E1000F0 == 0x000000B0 and regs.get(r_n) is not None:                  # strh
                    off = ((z >> 4) & 0xF0) | (z & 0xF) if z & 0x00400000 else regs.get(z & 0xF)
                    if off is not None:
                        size = 2
                        if z & 0x01000000:
                            addr = regs[r_n] + (off if z & 0x00800000 else -off)
                        else:                                                   # post-indexed: rn, then rn += off
                            addr = regs[r_n]
                            regs[r_n] = regs[r_n] + (off if z & 0x00800000 else -off)
                if addr is not None:
                    v = regs.get(r_d)
                    if v is not None:
                        mem[addr] = v & ((1 << 8 * size) - 1)
                    else:
                        mem.pop(addr, None)
        if sum(1 for v in names.values() if v) < 3:
            continue
        out = {}
        for i in range(n):
            a = tbl + GPM_ENTRY * i
            out[i] = {"index": mem.get(a), "flag": mem.get(a + 4),
                      "msgs": tuple(mem.get(a + o) for o in (6, 8, 10)), "name": names.get(i, "")}
        return out
    return {}


def gpm_lines(e, names, on_flag, debug=False):
    """The port lines of a GamePlayModes build's challenges (see above), or []."""
    single = _gpm_singleton(e)
    tbl, n = _gpm_table(e)
    if not single or not tbl:
        return ["no singleton (%s) or table (%s)" % (single, tbl)] if debug else []
    entries = _gpm_entries(e, tbl, n)
    table, count = message_table(e)

    def text(m):
        return message_text(e, table, m) if table and m is not None and m < count else ""
    if debug:
        out = ["singleton 0x%x table 0x%x n %d" % (single, tbl, n)]
        for i, v in sorted(entries.items()):
            out.append("%2d idx %s flag %s %s msgs %s" % (i, v["index"], v["flag"], v["name"],
                                                          [(m, text(m)) for m in v["msgs"]]))
        return out
    plain = next((i for i, v in sorted(entries.items()) if v["name"] == "sys_standard" and not v["flag"]), None)
    if plain is None:
        return []
    lines, slot = [], 0
    for i, v in sorted(entries.items()):
        if v["flag"] != on_flag or v["index"] != i or v["name"].endswith("_test"):     # Jaws: a video-mode test
            continue
        msg = v["msgs"][0]
        stem = re.sub(r"[^A-Z0-9]+", "_", text(msg).upper()).strip("_") \
            or re.sub(r"^[a-z]+_(cm_)?", "", v["name"]).upper()
        lines += ["# entry %d of the game-play-mode table at 0x%08x (%s): flag %d alone - picked by its index"
                  % (i, tbl, v["name"], on_flag),
                  "value challenge_mode_%d  %d" % (slot, i),
                  "text  challenge_name_%d  %s" % (slot, pretty(_short(stem)))]
        if msg:
            lines.append("value challenge_name_msg_%d  %d" % (slot, msg))
        slot += 1
    if not slot:
        return []
    return ["value challenge_on_flag   %d" % on_flag,
            "data  game_play_modes     0x%08x   # the GamePlayModes singleton: the current game-play mode at +8" % single,
            "value game_play_mode_at   8",
            "value challenge_mode_plain  %d   # Standard: what a mode's challenge game plays" % plain] + lines


#: PAD-619: Venom's GamePlayModeAdapter keeps no table of objects: the current game-play mode is a plain global (the
#: adapter's second method: movw/movt r3, <cur>; ldr r0, [r3, #<at>]; bx lr), and each mode's flag and name message
#: are u16 arrays in the game's read-only data, read by the adapter's methods:
#:   flag: sub r1, r1, #1 ; cmp r1, #<last> ; lslls r1, r1, #1 ; movwls/movtls r3, <arr> ; ldrhls r0, [r3, r1]
#:   name: sub r2, r2, #1 ; cmp r2, #<last> ; push ; movwls/movtls r3, <arr> ; addls r3, r3, r2, lsl #1 ; ...
#:         ldrhls r0, [r3, #<off>]
#: (modes from 1; 0 is Standard, what the adapter's reset stores). Venom Pro/LE 1.07: Challenge Mode Low / Medium /
#: High (Defeat Knull) are modes 11-13, flag 18 alone.
def _adapter_vtable(e):
    d = e.d
    i = d.find(b"\x0019GamePlayModeAdapter\x00")
    if i < 0:
        return None
    name = e.va(i + 1)
    vts = [e.va(o) + 4 for ti in (e.va(o) - 4 for o in _refs(d, name)) for o in _refs(d, ti)]
    return vts[0] if len(vts) == 1 else None


def adapter_lines(e, names, on_flag):
    """The port lines of a static-table GamePlayModeAdapter's challenges (see above), or []."""
    vt = _adapter_vtable(e)
    if not vt:
        return []
    fns = []
    for j in range(16):
        f = e.word(vt + 4 * j)
        if not f or e.off(f) is None:
            break
        fns.append(f)
    if len(fns) < 9:
        return []

    def words(va, n):
        return [e.word(va + 4 * k) for k in range(n)]
    a, b, c, r = words(fns[1], 4)
    if not (a & 0xFFF0F000 == 0xE3003000 and b & 0xFFF0F000 == 0xE3403000 and c & 0xFFFFF000 == 0xE5930000
            and r == 0xE12FFF1E):
        return []
    cur, at = _imm16(b) << 16 | _imm16(a), c & 0xFFF
    flags = msgs = None
    for f in fns:
        w = words(f, 12)
        if w[0] == 0xE2411001 and w[1] & 0xFFFFFF00 == 0xE3510000 and w[2] == 0x91A01081 \
                and w[3] & 0xFFF0F000 == 0x93003000 and w[4] & 0xFFF0F000 == 0x93403000 and w[5] == 0x919300B1:
            flags = (_imm16(w[4]) << 16 | _imm16(w[3]), (w[1] & 0xFF) + 1)
        if w[0] == 0xE2422001 and w[1] & 0xFFFFFF00 == 0xE3520000 and msgs is None:
            arr = None
            for k in range(2, 10):
                if w[k] & 0xFFF0F000 == 0x93003000 and w[k + 1] & 0xFFF0F000 == 0x93403000:
                    arr = _imm16(w[k + 1]) << 16 | _imm16(w[k])
                if arr and w[k] & 0xFFF000F0 == 0x91D000B0:                    # ldrhls r0, [r3, #off]
                    msgs = arr + (((w[k] >> 4) & 0xF0) | (w[k] & 0xF))
                    break
    if not flags:
        return []
    arr, n = flags
    table, count = message_table(e)
    lines, slot = [], 0
    for i in range(1, n + 1):
        flag = struct.unpack_from("<H", e.d, e.off(arr + 2 * (i - 1)))[0]
        if flag != on_flag:
            continue
        msg = struct.unpack_from("<H", e.d, e.off(msgs + 2 * (i - 1)))[0] if msgs else 0
        words_ = message_text(e, table, msg) if table and msg and msg < count else ""
        stem = re.sub(r"[^A-Z0-9]+", "_", words_.upper()).strip("_") or "CHALLENGE_%d" % i
        lines += ["# game-play mode %d (the adapter's flag table at 0x%08x): flag %d alone - picked by its index"
                  % (i, arr, on_flag),
                  "value challenge_mode_%d  %d" % (slot, i),
                  "text  challenge_name_%d  %s" % (slot, pretty(stem))]
        if msg:
            lines.append("value challenge_name_msg_%d  %d" % (slot, msg))
        slot += 1
    if not slot:
        return []
    return ["value challenge_on_flag   %d" % on_flag,
            "data  game_play_modes     0x%08x   # the adapter's current game-play mode" % cur,
            "value game_play_mode_at   %d" % at,
            "value challenge_mode_plain  0   # Standard (what the adapter's reset stores)"] + lines


#: PAD-619: TMNT's start menu (TMNT LE/Pro 1.58/1.59): Bond's shape with its fields moved - 24-byte entries
#: {+0 u8, +4 kind, +8 / +0xa caption message, +0xc char *name, +0x14 u32 ...}, the kind jump a few words after the kind
#: load (`ldr r3, [r3, #-back] ; cmp r0, r2 ; bhi ; sub r3, r3, #1 ; cmp r3, #N ; ldrls pc, [pc, r3, lsl #2]`), the count
#: wrapped through another register (`ldr r3, [sp, #count] ; ... sub r6, r3, #1 ; cmp r6, <cursor>`). Its plain
#: challenge kind is FINAL BATTLE CHALLENGE's (11: flag 18 alone).
def menu_wide(e, names, on_flag):
    """The port lines of a wide-entry start menu (see above), or None."""
    w, base = e.words, e.text_va
    fl = flag_functions(e)
    if not fl:
        return None
    sites = []
    for k in range(8, len(w) - 8):
        if (w[k] & 0xFFF0F000) != PICK_LDR:
            continue
        for j in range(k + 2, k + 6):
            if w[j] == 0xE2433001 and (w[j + 1] & 0xFFFFFF00) == 0xE3530000 and w[j + 2] == 0x979FF103:
                sites.append((k, j))
                break
    if len(sites) != 1:
        return None
    k, j = sites[0]
    back = w[k] & 0xFFF
    if (w[k - 1] & 0x0F0F0000) == 0x050F0000 or (w[k - 1] & 0x0F000000) in (0x0A000000, 0x0B000000)             or (w[k - 1] >> 16) & 0xF == 15:
        return None                                                 # a pc-relative word cannot move
    pre = w[k - 6:k]
    tops = [rot_imm(x & 0xFFF) for x in pre if (x & 0xFFFF0000) == 0xE28D0000]
    wide = any((x & 0x0FF00FF0) == 0x00800180 and x >> 28 == 0xE for x in pre)   # (cursor * 3) lsl #3: 24 bytes
    if not tops or not wide:
        return None
    es, kind_addr = 24, tops[-1] - back
    frames = [i for i in range(max(0, k - 6000), k) if (w[i] & 0xFFFF0FFF) == 0xE1A00000
              and (w[i + 1] & 0xFFF0FFFF) == 0xE3100080 and ((w[i] >> 12) & 0xF) == ((w[i + 1] >> 16) & 0xF)]
    if not frames:
        return None
    fr = frames[-1]
    start = next((i for i in range(fr, max(0, fr - 6000), -1) if (w[i] & 0xFFFF4000) == 0xE92D4000), None)
    if start is None:
        return None
    # the entry's start: the builder's own base (add rX, sp, #B) just below the kind - the kind is B's +kat
    bases = [rot_imm(w[i] & 0xFFF) for i in range(start, fr) if (w[i] & 0xFFFF0000) == 0xE28D0000]
    bases = [b_ for b_ in bases if kind_addr - es < b_ < kind_addr]
    if not bases:
        return None
    list_at = max(bases)
    kat = kind_addr - list_at
    count_at = next((w[i] & 0xFFF for i in range(fr, min(len(w) - 4, fr + 600)) if (w[i] & 0xFFFFF000) == 0xE59D3000
                     and any((x & 0xFFFF0FFF) == 0xE2430001 for x in w[i + 1:i + 4])
                     and any((x & 0xFFF0FFF0) == 0xE1500000 for x in w[i + 2:i + 5])), None)
    if count_at is None:
        return None
    above = [rot_imm(w[i] & 0xFFF) for i in range(start, k + 1500) if (w[i] & 0xFFFFF000) == 0xE28D0000
             and bl_target(base + 4 * i + 4, w[i + 1]) is not None]
    # the room: up to the first local above the list handed to a call, else the base the function indexes the list
    # down from (TMNT: sp+0x430, 14 entries of 24)
    above = [a for a in above if list_at + es <= a and a != tops[-1]] + [tops[-1]]
    cap = (min(above) - list_at) // es
    n = (w[j + 1] & 0xFF) + 1
    plain = None
    for i in range(n):
        flags = _case_flags(e, e.word(base + 4 * (j + 4) + 4 * i), None, fl)
        if on_flag in flags and len(flags) == 1 and plain is None:
            plain = i + 1
    caption = challenge_caption(e)
    if plain is None or caption is None:
        return None
    # PAD-619: ours play as STANDARD, not as the plain challenge's kind: TMNT's challenges are locked until a player has
    # unlocked them ("PLAY AS ALL FOUR TURTLES TO UNLOCK"), and Start on a locked kind clears the challenge flags and
    # plays Standard - the game's own pick did too, on the rig. The ball's start hands the game to the mode instead.
    return ["# the start menu (CHOOSE YOUR MODE OF PLAY), TMNT's wide entries: challenges of the modes' own - played as "
            "Standard (0), the plain challenge game (kind %d) being locked until a player unlocks it" % plain,
            "site  challenge_menu      0x%08x 0x%08x 0x%08x" % (base + 4 * fr, w[fr], w[fr + 1]),
            # hooked a word before the kind's load, where r3 still points into the entry: the Start that follows
            # re-reads the kind from the entry itself, so ours is made the plain kind there (as on Star Wars)
            "site  challenge_menu_pick 0x%08x 0x%08x 0x%08x" % (base + 4 * (k - 1), w[k - 1], w[k]),
            "value challenge_menu_pick_back %d" % back,
            "value challenge_menu_list_at   %d" % list_at,
            "value challenge_menu_count_at  %d" % count_at,
            "value challenge_menu_cap       %d" % cap,
            "value challenge_menu_entry     %d" % es,
            "value challenge_menu_kind_at   %d" % kat,
            "value challenge_menu_caption_at %d" % (kat + 4),
            "value challenge_menu_caption2_at %d" % (kat + 6),
            "value challenge_menu_name_at   %d" % (kat + 8),
            "value challenge_menu_kind      0",
            "value challenge_menu_slot      -1",
            "value challenge_menu_sets_on   1",
            "value challenge_menu_caption   %d" % caption]


#: PAD-619: Foo Fighters LE/Pro 1.04's start menu applies the hovered entry live, every frame, from the frame's own load
#: of its kind: `add r3, sp, #T ; ... ; add r3, r3, <cursor>, lsl #4 ; ldr r3, [r3, #-back] ; cmp r3, #0 ; bne` (0 =
#: Standard; any other kind sets the game's mode there), and Start only leaves the menu. No kind of it makes a challenge
#: game, so ours play as Standard: the pick is hooked on that load (r3 points into the entry) and ours becomes kind 0.
def menu_live(e, names, on_flag):
    """The port lines of a live-applied start menu (see above), or None."""
    w, base = e.words, e.text_va
    frames = [i for i in range(len(w) - 2) if (w[i] & 0xFFFF0FFF) == 0xE1A00000 and (w[i + 1] & 0xFFF0FFFF) == 0xE3100080
              and ((w[i] >> 12) & 0xF) == ((w[i + 1] >> 16) & 0xF)]
    # ... or the buttons through the stack (Mando: str r0, [sp, #x] ; ldr r3, [sp, #x] ; tst r3, #0x80)
    frames += [i for i in range(len(w) - 3) if (w[i] & 0xFFFFF000) == 0xE58D0000
               and w[i + 1] == (0xE59D3000 | (w[i] & 0xFFF)) and w[i + 2] == 0xE3130080]
    # ... or kept in a register tested later, the cursor in a register too (Mando LE 1.44: mov r8, r0 ; ... ;
    # ldrb sb, [r3, #-0xc8] ; cmp sb, #0 ; bne - and `tst r8, #0x80` at the loop's foot)
    frames += [i for i in range(len(w) - 8) if (w[i] & 0xFFFF0FFF) == 0xE1A00000 and ((w[i] >> 12) & 0xF) > 3
               and any((x & 0xFFF00000) == 0xE5500000 and (x >> 16) & 0xF == 3 for x in w[i + 1:i + 4])
               and (0xE3100080 | ((w[i] >> 12) & 0xF) << 16) in w[i + 2:i + 1500]]
    hits = []
    for fr in sorted(set(frames)):
        for k in range(fr + 1, fr + 14):
            rd = (w[k] >> 12) & 0xF
            if ((w[k] & 0xFFF0F000) == PICK_LDR or (w[k] & 0xFFF00000) == 0xE5500000) and (w[k] >> 16) & 0xF == 3 \
                    and w[k + 1] == 0xE3500000 | rd << 16 and (w[k + 2] & 0xFF000000) == 0x1A000000:
                five = lambda xs: any(                                         # cursor * 5: r + r lsl 2, or
                    (x & 0x0FF00FF0) == 0x00800100 and (x >> 16) & 0xF == x & 0xF for x in xs) or any(
                    (a & 0xFFFF0FF0) == 0xE1A00100 and (b & 0xFFF00000) == 0xE0800000          # lsl rA, rB, #2 ;
                    and (b >> 16) & 0xF == (a >> 12) & 0xF and b & 0xF == a & 0xF and not b & 0xFF0  # add rD, rA, rB
                    for j, a in enumerate(xs) for b in xs[j + 1:])
                if (w[k - 1] & 0xFFFFFFF0) == 0xE0833200:                       # add r3, r3, rC, lsl #4: 16 bytes
                    es = 16
                elif (w[k - 1] & 0xFFF0FFFF) == 0xE0803103 and five(w[k - 6:k - 1]):   # add r3, rB, r3, lsl #2
                    es = 20                                                    # r3 = cursor * 5: 20 bytes (Mando)
                else:
                    continue
                tops = [rot_imm(x & 0xFFF) for x in w[k - 5:k - 1] if (x & 0xFFFF0000) == 0xE28D0000]
                if tops:
                    hits.append((fr, k, tops[-1] - (w[k] & 0xFFF), w[k] & 0xFFF, tops[-1], es))
                break
    if len(hits) != 1:
        return None
    fr, k, list_at, back, top, es = hits[0]
    # the count, as the right button wraps (ldr r3, [sp, #x] ; sub r3, r3, #1 ; cmp r3, rC): after the frame, or - where the
    # buttons are read at the loop's foot (Mando LE 1.44) - before it
    count_at = next((w[i] & 0xFFF for i in list(range(fr, min(len(w) - 4, fr + 600))) + list(range(fr - 1, max(0, fr - 600), -1))
                     if (w[i] & 0xFFFFF000) == 0xE59D3000
                     and 0xE2433001 in w[i + 1:i + 4] and any((x & 0xFFFFFFF0) == 0xE1530000 for x in w[i + 2:i + 5])),
                    None)
    start = next((i for i in range(fr, max(0, fr - 6000), -1) if (w[i] & 0xFFFF4000) == 0xE92D4000), None)
    caption = challenge_caption(e)
    if count_at is None or start is None or caption is None:
        return None
    above = [rot_imm(w[i] & 0xFFF) for i in range(start, k + 1500) if (w[i] & 0xFFFFF000) == 0xE28D0000
             and bl_target(base + 4 * i + 4, w[i + 1]) is not None]
    above = [a for a in above if list_at + es <= a and a != top] + [top]
    cap = (min(above) - list_at) // es
    if cap < 2:
        return None
    return ["# the start menu (CHOOSE YOUR MODE OF PLAY), applied live as an entry is shown: challenges of the modes' own "
            "- no kind of the game's makes a challenge game, so ours play as Standard (0) and the runtime hands the ball "
            "to the mode",
            "site  challenge_menu      0x%08x 0x%08x 0x%08x" % (base + 4 * fr, w[fr], w[fr + 1]),
            "site  challenge_menu_pick 0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1]),
            "value challenge_menu_pick_back %d" % back,
            "value challenge_menu_list_at   %d" % list_at,
            "value challenge_menu_count_at  %d" % count_at,
            "value challenge_menu_cap       %d" % cap,
            "value challenge_menu_entry     %d" % es,
            "value challenge_menu_kind      0",
            "value challenge_menu_slot      -1",
            "value challenge_menu_sets_on   1",
            "value challenge_menu_caption   %d" % caption]


#: PAD-640: the game's champions (one framework on every Spike 2 build, PAD-663): categories 1.. of 36 bytes each in
#: one table, {per-player bytes, score getter, reset, compare, qualify, fn, char **titles, u16 *entries, flags},
#: their count in a word. The category lookup checks the id against that count, then indexes the table:
#:   cmp r0,#0 ; push {r3,lr} ; beq ; movw/movt r3 <count> ; ldr r3,[r3] ; cmp r0,r3 ; bcs ;
#:   add r0,r0,r0,lsl #3 ; movw/movt r3 <table> ; add r0,r3,r0,lsl #2 ; ldr r3,[r0,#28]
#: The entry lookup, (category, n) -> the n-th score entry:
#:   mov r3,r0 ; movw r0 <map> ; push {r4,lr} ; movt r0 ; mov r4,r1 ; mov r1,r3 ; bl ; .. ; ldr r0,[r0,#28]
#: and the end-of-game high scores, the one function that loads the table with movwhi/movthi.
def scores_lines(e, n_challenges):
    """The `site challenge_scores` / `challenge_score_entry` / `challenge_scores_gate` lines, `value
    challenge_scores_cat` (HIGHEST SCORES: every challenge game's) and, where the build has one "... CHALLENGE
    CHAMPION" category per challenge (Bond, Stranger Things), `value challenge_scores_cat_<n>`. Empty when the build
    has not exactly one of each function, or neither the per-challenge categories nor the gate."""
    w, base = e.words, e.text_va
    n = len(w)
    cats = [k for k in range(n - 13) if w[k] == 0xE3500000 and w[k + 1] == 0xE92D4008
            and (w[k + 3] & 0xFFF0F000) == 0xE3003000 and (w[k + 4] & 0xFFF0F000) == 0xE3403000
            and w[k + 5] == 0xE5933000 and w[k + 6] == 0xE1500003 and w[k + 8] == 0xE0800180
            and (w[k + 9] & 0xFFF0F000) == 0xE3003000 and (w[k + 10] & 0xFFF0F000) == 0xE3403000
            and w[k + 11] == 0xE0830100 and w[k + 12] == 0xE590301C]
    ents = [k for k in range(n - 10) if w[k] == 0xE1A03000 and (w[k + 1] & 0xFFF0F000) == 0xE3000000
            and w[k + 2] == 0xE92D4010 and (w[k + 3] & 0xFFF0F000) == 0xE3400000 and w[k + 4] == 0xE1A04001
            and w[k + 5] == 0xE1A01003 and w[k + 6] >> 24 == 0xEB and w[k + 9] == 0xE590001C]
    if len(cats) != 1 or len(ents) != 1:
        return []
    k = cats[0]
    count_at = _imm16(w[k + 3]) | _imm16(w[k + 4]) << 16
    table = _imm16(w[k + 9]) | _imm16(w[k + 10]) << 16
    if e.off(count_at) is None or e.off(table) is None:
        return []
    count = e.word(count_at)
    ends = [q for q in range(n - 1) if (w[q] & 0xFFF0F000) == 0x83003000 and _imm16(w[q]) == table & 0xFFFF
            and (w[q + 1] & 0xFFF0F000) == 0x83403000 and _imm16(w[q + 1]) == table >> 16]
    if len(ends) != 1 or not 2 <= count < 64:
        return []
    top = next((s for s in range(ends[0], max(ends[0] - 64, 0), -1) if (w[s] & 0xFFFF4000) == 0xE92D4000), None)
    if top is None:
        return []
    titles = {}
    for c in range(1, count):
        at = table + 36 * c
        tl = e.word(at + 24) if e.off(at + 24) is not None else 0
        titles[c] = e.cstr(e.word(tl)) if tl and e.off(tl) is not None else None
    picked = [(c, t) for c, t in sorted(titles.items()) if t and t.endswith("CHALLENGE CHAMPION")]
    per = n_challenges > 0 and len(picked) == n_challenges
    gate = gate_lines(e, top)
    if not per and not gate:
        return []
    out = ["# PAD-640: the game's end-of-game high scores (a mode's challenge game keeps the mode's own)",
           "site  challenge_scores       0x%08x 0x%08x 0x%08x" % (base + 4 * top, w[top], w[top + 1]),
           "site  challenge_score_entry  0x%08x 0x%08x 0x%08x" % (base + 4 * ents[0], w[ents[0]], w[ents[0] + 1])]
    out += gate
    if gate:
        out += ["# PAD-663: the category table (36 bytes each; +28 the entry list a category's insert shifts) and its "
                "count",
                "data  challenge_scores_table 0x%08x" % table,
                "data  challenge_scores_count 0x%08x" % count_at]
    if gate and titles.get(1):
        out += ["# PAD-663: %s, whose first entry a mode's challenge game goes in as the mode's own record" % titles[1],
                "value challenge_scores_cat   1"]
    out += record_lines(e, table)
    if per:
        out.append("# PAD-640: each challenge's champion category")
        for slot, (c, title) in enumerate(picked):
            out += ["# %s" % title.replace("/'", "'"), "value challenge_scores_cat_%d  %d" % (slot, c)]
        return out + page_lines(e, base + 4 * ents[0], picked[-1][0])
    pages = pages_lines(e, base + 4 * ents[0])
    # PAD-663: no page function, but a page process per category (Aerosmith, Guardians: Bond's shape): PAD-660's
    # route on the last category with one
    for c in sorted(titles, reverse=True):
        if pages or c < 2:
            break
        pages = page_lines(e, base + 4 * ents[0], c)
    return out + (pages or list_page_lines(e, base + 4 * ents[0]))      # PAD-663: else HIGHEST SCORES' list page


#: PAD-663: the one-screen cabinets' 800x480 panel (tools/spike2_emu/display2.py REPORTED_PANELS: reported from real
#: machines, in no game program) - a mode's champion page title past ~20 characters runs off its edges (Star Wars
#: Home Edition, Jurassic Park The Pin), so it drops " CHAMPION" there. The program names its own title.
SMALL_SCREEN_TITLES = ("james_bond_60th_le", "star_wars_elg", "jurassic_park_the_pin")
SMALL_SCREEN_TITLE_MAX = 18


def screen_lines(e):
    """`value challenge_page_title_max` on a build of an 800x480 one-screen cabinet (empty on every other)."""
    if not any(b"\0" + t.encode() + b"\0" in e.d for t in SMALL_SCREEN_TITLES):
        return []
    return ["# PAD-663: an 800x480 one-screen cabinet: a mode's champion title past this many characters is its name alone",
            "value challenge_page_title_max %d" % SMALL_SCREEN_TITLE_MAX]


#: PAD-663: a champion record's layout, as HIGHEST SCORES' compare (category 1's +0x10) reads it:
#:   ldr r4, [r1] ; mov r1, #<check at> ; .. ; ldrh r5, [r4, #<check at>] ; bl <byte sum> ; .. ; blx r3 (the score)
#:   ; ldrd r2, r3, [r4, #<score at>] (u64) or ldr r3, [r4, #<score at>] (u32)
#: Most builds: u64 score at +72, check at +88 (the runtime's default). The Beatles 1.29 and Star Wars ELG 1.10: u32
#: at +80, check at +84 - a record of the default layout fails their check and the game resets the category.
RECORD_DEFAULT = (88, 72, 8)


def record_lines(e, table):
    """`value challenge_record_check_at` / `_score_at` / `_score_size` when the build's records are not laid out as
    the runtime's default (empty when they are, or the compare is not of the known shape)."""
    if e.off(table + 36 + 16) is None:
        return []
    fn = e.word(table + 36 + 16)
    if e.off(fn) is None or fn % 4 or not e.text_va <= fn < e.text_va + 4 * len(e.words):
        return []
    w = e.words[(fn - e.text_va) // 4:(fn - e.text_va) // 4 + 24]
    movs = {x & 0xFF for x in w[:8] if (x & 0xFFFFFF00) == 0xE3A01000}
    checks = [(x >> 4 & 0xF0) | (x & 0xF) for x in w[:8] if (x & 0xFFF000F0) == 0xE1D000B0]
    if len(checks) != 1 or checks[0] not in movs or 0xE12FFF33 not in w:
        return []
    after = w[w.index(0xE12FFF33) + 1:]
    score = next(((((x >> 4 & 0xF0) | (x & 0xF)), 8) if (x & 0xFFF000F0) == 0xE1C000D0 else (x & 0xFFF, 4)
                  for x in after[:3] if (x & 0xFFF000F0) == 0xE1C000D0 or (x & 0xFFF00000) == 0xE5900000), None)
    if score is None or (checks[0], score[0], score[1]) == RECORD_DEFAULT:
        return []
    return ["# PAD-663: the champion records' layout (the score's place and size, the check's place)",
            "value challenge_record_check_at   %d" % checks[0],
            "value challenge_record_score_at   %d" % score[0],
            "value challenge_record_score_size %d" % score[1]]


#: PAD-663: the end-of-game function asks the bus before it files a player under a category's entry, one shape on
#: every build: {u8 player, u16 category, int entry} stored at sp + X (strb / strh / str), then
#:   mov r0, #<id> ; add r1, sp, #X ; .. ; bl <dispatch> ; cmp r0, #0
#: - the only one of its bus calls whose answer it tests.
def gate_lines(e, top):
    """`site challenge_scores_gate` (the bl) and `value challenge_scores_gate_id` / `_cat_at` / `_entry_at`, for the
    end-of-game function at word `top` (empty unless exactly one call of that shape)."""
    w, base = e.words, e.text_va
    hits = []
    for q in range(top + 8, min(len(w) - 1, top + 1600)):
        if w[q] >> 24 != 0xEB or w[q + 1] != 0xE3500000:
            continue
        j = q - 1                                                   # its arguments: after the call before it
        while j > q - 7 and w[j] >> 24 != 0xEB:
            j -= 1
        before = w[j + 1:q]
        r0 = [x & 0xFF for x in before if (x & 0xFFFFFF00) == 0xE3A00000]
        r1 = [rot_imm(x & 0xFFF) for x in before if (x & 0xFFFFF000) == 0xE28D1000]
        if len(r0) != 1 or len(r1) != 1:
            continue
        x = r1[0]
        prior = w[max(top, q - 60):q]
        if _sp_store(prior, 0xE5C00000, x) and _sp_strh(prior, x + 2) and _sp_store(prior, 0xE5800000, x + 4):
            hits.append((q, r0[0]))
    if len(hits) != 1:
        return []
    q, ident = hits[0]
    return ["# PAD-663: its question to the bus before it files a player under a category's entry ({player, category "
            "+2, entry +4}): in a mode's challenge game only the mode's record says yes",
            "site  challenge_scores_gate  0x%08x 0x%08x 0x%08x" % (base + 4 * q, w[q], w[q + 1]),
            "value challenge_scores_gate_id       %d" % ident,
            "value challenge_scores_gate_cat_at   2",
            "value challenge_scores_gate_entry_at 4"]


def _sp_store(words, op, at):
    """1 when one of `words` is `op` (strb / str, immediate offset) of a register to [sp, #at]."""
    return any((y & 0xFFFF0FFF) == (op | 0xD0000 | at) for y in words)


def _sp_strh(words, at):
    """1 when one of `words` is `strh rX, [sp, #at]`."""
    return any((y & 0xFFFF0FFF) == (0xE1CD00B0 | (at >> 4) << 8 | (at & 0xF)) for y in words)


#: PAD-663: most builds show every champion through ONE page function (not Bond's page process per category), called by
#: the attract mode once per category: it looks the category's entry up with the category from a register, keeps the
#: entry (`subs/mov rE, r0` before any other call) and reads its titles list (`ldr rX, [rE, #0x18]`). It may open
#: with `movw/movt ip` before its push (Avengers LE 1.10). A build may have more than one of that shape (Deadpool,
#: Batman 66, Jaws, The Beatles): all are named (four at most), and the runtime follows the one the attract mode calls.
def pages_lines(e, entry_va):
    """`site challenge_pages_<k>` for the build's champion page functions (empty when it has none of that shape)."""
    found = _page_fns(e, entry_va, False)
    row = _row_page(e, entry_va)
    if row is not None and row not in found:
        found = (found + [row])[-4:] if len(found) >= 4 else found + [row]
    if not found:
        return []
    w, base = e.words, e.text_va
    out = ["# PAD-663: the champion page function(s) (each called per category; the attract mode's is the one it calls): "
           "a mode's challenge champion is shown on it after the lowest category the attract mode shows"]
    for i, k in enumerate(found):
        out.append("site  challenge_pages_%d     0x%08x 0x%08x 0x%08x" % (i, base + 4 * k, w[k], w[k + 1]))
    return out


#: PAD-663: a build with no page function of that shape (Teenage Mutant Ninja Turtles: a bespoke page per category,
#: its title in the scene) still lists HIGHEST SCORES on one page: `mov r0, #1 ; mov r1, rN ; bl <entry lookup>` in
#: a loop over its rows, each row's title through the entry (+0x18, or its callback +0x10). Repeated with the category's
#: list cut to its first entry, pointed at the mode's record, that page lists the mode's champion alone.
def list_page_lines(e, entry_va):
    """`site challenge_list_page` (the lowest such function; empty when none)."""
    found = _page_fns(e, entry_va, True)
    if not found:
        return []
    w, base = e.words, e.text_va
    k = found[0]
    return ["# PAD-663: HIGHEST SCORES' list page: a mode's challenge champion is listed alone on it after the game's",
            "site  challenge_list_page   0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1])]


#: PAD-663: Jurassic Park The Pin shows HIGHEST SCORES one row per page, each its own small function: `mov r0, #1 ;
#: mov r1, #<row> ; bl <entry lookup> ; mov rE, r0 ; .. ; mov r1, rE ; bl <page body>`, the body reading the entry's
#: titles (+0x18). The GRAND CHAMPION's (row 0) is named with the page functions (pages_lines): its category's first
#: entry is the one a mode's record stands in.
def _row_page(e, entry_va):
    """The word index of HIGHEST SCORES' row-0 page of that shape (None when none, or not one)."""
    w, base = e.words, e.text_va
    n = len(w)
    found = []
    for q in range(8, n - 30):
        if w[q] >> 24 != 0xEB or bl_target(base + 4 * q, w[q]) != entry_va:
            continue
        if not (0xE3A00001 in w[q - 3:q] and 0xE3A01000 in w[q - 3:q]):            # mov r0, #1 ; mov r1, #0
            continue
        keep = next(((x >> 12) & 0xF for x in w[q + 1:q + 5] if (x & 0xFFFF0FFF) == 0xE1A00000), None)
        if keep is None or keep in (0, 1, 13, 15):
            continue
        body = None
        for j in range(q + 1, q + 30):
            if w[j] >> 24 == 0xEB and (0xE1A01000 | keep) in w[j - 4:j]:
                body = bl_target(base + 4 * j, w[j])
                break
        if body is None or e.off(body) is None:
            continue
        bw = [e.word(body + 4 * i) for i in range(400)]
        held = [(x >> 12) & 0xF for x in bw[:8] if (x & 0xFFFF0FFF) == 0xE1A00001]   # mov rY, r1
        if not held or not any((x & 0xFFFF0FFF) == (0xE5900018 | held[0] << 16) for x in bw):
            continue
        top = next((t for t in range(q, max(q - 60, 0), -1) if (w[t] & 0xFFFF4000) == 0xE92D4000), None)
        top = None if top is None else _prologue_start(w, top)
        if top is not None and _openable(w[top], w[top + 1]) and top not in found:
            found.append(top)
    return found[0] if len(found) == 1 else None


def _page_fns(e, entry_va, listed):
    """Word indexes of the functions of the champion page shape (listed: HIGHEST SCORES' list page instead)."""
    w, base = e.words, e.text_va
    n = len(w)
    found = []
    for q in range(8, n - 8):
        if w[q] >> 24 != 0xEB or bl_target(base + 4 * q, w[q]) != entry_va:
            continue
        imm = [x & 0xFF for x in w[q - 4:q] if (x & 0xFFFFFF00) == 0xE3A00000]
        r1reg = any((x & 0xFFFFFFF0) == 0xE1A01000 and x & 0xF not in (13, 15) for x in w[q - 4:q])
        if listed and not (imm == [1] and r1reg):                     # mov r0, #1 ; mov r1, <row>
            continue
        if not listed and any((x & 0xFFFFFF00) == 0xE3A00000 for x in w[q - 6:q]):   # a page of its own category
            continue
        keep, handed = None, None
        for j, x in enumerate(w[q + 1:q + 7]):
            if x >> 24 in (0xEB, 0xFA, 0xFB) or (x & 0x0FFFFFF0) == 0x012FFF30:
                if x >> 24 == 0xEB and keep == 1:                       # mov r1, r0 ; .. ; bl <its formatter>
                    handed = bl_target(base + 4 * (q + 1 + j), x)
                break
            if (x & 0xFFFF0FFF) in (0xE2500000, 0xE1A00000) and (x >> 12) & 0xF not in (0, 13, 15):
                keep = (x >> 12) & 0xF
                if keep != 1:
                    break
        if keep is None:
            continue
        after = w[q + 2:min(n, q + 400)]
        titles = keep != 1 and any((x & 0xFFFF0FFF) == (0xE5900018 | keep << 16) for x in after)
        # ... or its title through the entry's own callback (+0x10: Foo Fighters, John Wick): ldr rX, [rE, #0x10] ;
        # .. ; blx rX - or the entry handed to a formatter that calls it (The Beatles: mov r1, r0 ; bl <f>, f opening
        # `.. ; ldr ip, [r1, #0x10] ; .. ; bx ip`)
        told = any((x & 0xFFFF0FFF) == (0xE5900010 | keep << 16)
                   and any(y == 0xE12FFF30 | (x >> 12) & 0xF for y in after[j + 1:j + 6]) for j, x in enumerate(after[:40]))
        if handed is not None and e.off(handed) is not None:
            f = [e.word(handed + 4 * i) for i in range(10)]
            told = told or any((x & 0xFFFF0FFF) == 0xE5910010 and (0xE12FFF10 | (x >> 12) & 0xF) in f[i + 1:i + 4]
                               for i, x in enumerate(f))
        if not titles and not told:
            continue
        top = next((t for t in range(q, max(q - 4000, 0), -1) if (w[t] & 0xFFFF4000) == 0xE92D4000), None)
        if top is None:
            continue
        top = _prologue_start(w, top)
        if top not in found:
            found.append(top)
    return [k for k in sorted(found) if _openable(w[k], w[k + 1])][:4]


def _prologue_start(w, push):
    """The word index a function starts at, given its push: back over the movw / movt before the push (Avengers:
    `movw ip ; movt ip ; push`), and the load of that address (Sword of Rage: `movw ip ; movt ip ; ldr ip, [ip] ;
    push` - wrapped at the push, the page ran with ip unset and the game crashed in attract)."""
    k = push
    x = w[k - 1] if k > 0 else 0
    if (x & 0xFFF00000) == 0xE5900000 and (x >> 16) & 0xF == (x >> 12) & 0xF:   # ldr rX, [rX, #imm]
        k -= 1
    top = k
    while top > 0 and push - top < 8 and (w[top - 1] & 0xFFF00000) in (0xE3000000, 0xE3400000):
        top -= 1
    return top if top < k else push


def _openable(w0, w1):
    """1 when hook_wrap_at takes a function opening with these two words: hook_wrap's push and a word not reading pc,
    or movw / movt / push only (pad_mode_runtime.c hook_wrap_at's checks)."""
    plain = lambda x: (x & 0xFFF00000) in (0xE3000000, 0xE3400000) or (x & 0xFFFF0000) == 0xE92D0000
    return _wrappable(w0, w1) or (plain(w0) and plain(w1) and not (w0 | w1) & 0xE92D8000 == 0xE92D8000)


def _wrappable(w0, w1):
    """1 when hook_wrap takes a function opening with these two words: `push {.., lr}` and neither reads or writes
    pc (pad_mode_runtime.c hook_wrap's checks)."""
    if (w0 & 0xFFFF4000) != 0xE92D4000:
        return False
    for x in (w0, w1):
        if (x & 0x0C000000) == 0x04000000 and (x >> 16) & 0xF == 15:
            return False
        if (x & 0x0C000000) == 0 and ((x >> 16) & 0xF == 15 or (not x & 0x02000000 and x & 0xF == 15)):
            return False
        if (x >> 12) & 0xF == 15:
            return False
    return True


#: PAD-660: the attract mode's champion pages. One page function per category, each the proc the attract mode's
#: page list starts (Bond LE 0x7a6864: {shown?, page} pairs), each reading its champion once, before its first frame:
#:   push {r4-fp,lr} ; mov r0,#<cat> ; vpush {d8} ; mov r1,#0 ; sub sp ; bl <the record, or 0> ; .. ;
#:   mov r1,#0 ; mov r0,#<cat> ; bl <the entry lookup> ; ..
#: then sets its lines: the title (`mov r0,#<message>; bl <message text>`, two or three times), CHAMPION, the record's
#: initials and the entry's score, and only then draws frames: a loop that yields with
#:   movw r3 <proc list> ; movt r3 ; add r1,r3,#12 ; ..
#: until its time is up (Bond: a timer; Stranger Things: 187 frames).
def page_lines(e, entry_va, cat):
    """The `site challenge_page` / `challenge_page_text` / `challenge_page_yield` and `value challenge_page_cat` /
    `challenge_page_title` lines for category `cat`'s page (empty when the build has not exactly one such page, or the
    page's title, yield or opening words are not of the known shapes)."""
    w, base = e.words, e.text_va
    n = len(w)
    pages = []
    for k in range(n - 14):
        if (w[k] & 0xFFFF4000) != 0xE92D4000:
            continue
        win = w[k:k + 14]
        if sum(1 for x in win if x == 0xE3A00000 | cat) == 2 and \
                any(bl_target(base + 4 * (k + i), x) == entry_va for i, x in enumerate(win)):
            pages.append(k)
    if len(pages) != 1 or not _wrappable(w[pages[0]], w[pages[0] + 1]):
        return []
    k = pages[0]
    end = next((q for q in range(k + 2, min(n, k + 4000)) if (w[q] & 0xFFFF8000) == 0xE8BD8000), None)
    if end is None:
        return []
    titles = {}
    for q in range(k + 1, end):
        t = bl_target(base + 4 * q, w[q])
        r0 = w[q - 1]
        imm = rot_imm(r0) if (r0 & 0xFFFFF000) == 0xE3A00000 else _imm16(r0) if (r0 & 0xFFF0F000) == 0xE3000000 \
            else None
        if t is not None and imm is not None and imm > 0xFF:
            titles[(t, imm)] = titles.get((t, imm), 0) + 1
    best = sorted(titles.items(), key=lambda kv: -kv[1])
    if not best or best[0][1] < 2 or (len(best) > 1 and best[1][1] == best[0][1]):
        return []
    (text, title), _count = best[0]
    if e.off(text) is None or not _wrappable(e.word(text), e.word(text + 4)):
        return []
    yld = None
    for q in range(end - 1, max(k, end - 16), -1):
        t = bl_target(base + 4 * q, w[q])
        if t is None or e.off(t) is None:
            continue
        y = [e.word(t + 4 * i) for i in range(3)]
        if (y[0] & 0xFFF0F000) == 0xE3003000 and (y[1] & 0xFFF0F000) == 0xE3403000 and y[2] == 0xE283100C:
            yld = t
            break
    if yld is None:
        return []
    return ["# PAD-660: the attract mode's last challenge champion page; a mode's challenge champion is shown after it, "
            "in the same page",
            "site  challenge_page        0x%08x 0x%08x 0x%08x" % (base + 4 * k, w[k], w[k + 1]),
            "site  challenge_page_text   0x%08x 0x%08x 0x%08x" % (text, e.word(text), e.word(text + 4)),
            "site  challenge_page_yield  0x%08x 0x%08x 0x%08x" % (yld, e.word(yld), e.word(yld + 4)),
            "value challenge_page_cat    %d" % cat,
            "value challenge_page_title  %d" % title]


def missing_from(lines, port_text):
    have = {tuple(l.split()[:2]): l for l in port_text.splitlines() if l.strip() and not l.startswith("#")}
    out = []
    for l in lines:
        if l.startswith("#"):
            continue
        key = tuple(l.split()[:2])
        if key not in have:
            out.append(l)
        elif have[key].split() != l.split():
            out.append("# DIFFERS in the port: " + l)
    return out

