"""Port lines for co-op play on a Spike 2 build, read from the game's own code (PAD-1017; MODE_SDK.md "Co-op play").

daveyvandy: "Add Spike 2 co-op to games without it. Should work like games that do have co-op (like TMNT). Should
have its own high score boards and share progress 2-4 players." Eight titles have co-op of their own (TMNT, Venom,
Mandalorian, D&D, Jaws, Jurassic Park, King Kong, Bond 60th); on TMNT (the symbol build in reference/) it is title
code: ccoop_play::hook_score_end copies the player up's score to the other players after every score, and some 70
places in the title's rules (cepisodes::CopyForCoop, ...) copy their own per-player state across. Nothing of that is
reusable on another title: every title keeps its progress in objects of its own, per player.

So co-op here is played the other way round: the game plays ONE player - its progress, its score, its lights and
flags are the team's, because there is only one of each - while the runtime takes the teammates in turn, each ball.
That needs two functions and three bytes of the framework's player code, the same shape on every Spike 2 build (53
of 53 shipped programs, Aerosmith .. Venom):

    the player change (the ball's end):           push {.., lr} ... bl <extra-ball test> ; subs rN, r0, #0 ;
                                                  bne ... ; movw/movt rG, <player> ; ... ldrb rX, [rG] ;
                                                  movw/movt rP, <players> ; ldrb rY, [rP] ... ldrb rZ, [rG, #1]
    add a player (Start in the first ball):       push {.., lr} ; mov r0, #<AD_MAX_PLAYERS_PER_GAME> ; bl <adj> ;
                                                  movw/movt rP, <players> ; ldrb ; ... ; strb(ne) rY, [rP]

The older builds (Aerosmith LE 1.15, Batman 1.13, Rush LE 1.18, ...) keep the count in a struct ([rP, #0x50]) and
put a `mov r0, #n` between the player change's test and its bne; the same lines come out of them.

(the framework's "can a player be added" test has the same opening but stores nothing - it is told apart by that).
The bytes: the player up (1-4) at <player>, the ball in play at <player> + 1, the count of players at <players>.

  site  coop_player_change  the player change (wrapped)
  site  coop_add_player     add a player (wrapped)
  data  coop_player         the player up's byte (the ball's is the next)
  data  coop_players        the count of players' byte
  site  coop_first_ball     (PAD-1046) the ball start's `bl <ball getter>` that tells a player's first ball (wrapped
                            where it is made: a later teammate's ball 1 is not a first ball, so the team's progress
                            holds)

  data  message_table         the game's message table (portchallenge.message_table), and
  value coop_ball_msg         its "BALL %d" line, which says whose turn it is in a co-op game
  site  audit_add             the game's audit add, whose audits a co-op game's awards count per teammate (PAD-1028)
  site  coop_panel_lit        the score panel's call of the player-up getter that lights the box up (PAD-1043),
  site  coop_panel_up[_n]     and its "player changed" checks' calls: answered with the teammate up

and, for the team's own high score boards, the end-of-game high scores' lines (portchallenge.scores_lines).

Read-only (bytes in, lines out).
"""
from .portchallenge import Elf, bl_target, extra_ball_lines, mov_r0

PUSH_LR_MASK, PUSH_LR = 0xFFFF4000, 0xE92D4000


def _movw_movt(w, k, stop):
    """{register: value} of the movw/movt pairs in words k..stop, and the words that complete each pair."""
    low, done = {}, []
    for j in range(k, min(stop, len(w))):
        x = w[j]
        r = (x >> 12) & 0xF
        if x & 0x0FF00000 == 0x03000000:
            low[r] = ((x >> 16) & 0xF) << 12 | (x & 0xFFF)
        elif x & 0x0FF00000 == 0x03400000 and r in low:
            done.append((j, r, low.pop(r) | (((x >> 16) & 0xF) << 12 | (x & 0xFFF)) << 16))
    return done


def _ldrb_imm(x):
    """(base, offset) of `ldrb rT, [rB, #imm]` (cond AL), or None."""
    if x & 0xFFF00000 != 0xE5D00000:
        return None
    return (x >> 16) & 0xF, x & 0xFFF


def _function_start(w, k, back=40):
    """The index of the push {.., lr} that opens the function word k is in (the nearest one before it), or None."""
    return next((j for j in range(k, max(k - back, -1), -1) if w[j] & PUSH_LR_MASK == PUSH_LR), None)


def player_change(e):
    """(function va, player byte va, players byte va) of the framework's player change, or None (not once)."""
    xb = extra_ball_lines(e)
    if not xb:
        return None
    test = int(xb[0].split()[2], 16)
    w, base = e.words, e.text_va
    found = set()
    for k in range(len(w) - 4):
        # PAD-1017: older builds (Aerosmith LE 1.15, Batman 1.13, ...) put a `mov r0, #n` between the test and the bne
        if bl_target(base + 4 * k, w[k]) != test or w[k + 1] & 0xFFFF0FFF != 0xE2500000                 or not any(w[j] >> 24 == 0x1A for j in (k + 2, k + 3)):
            continue
        pairs = _movw_movt(w, k + 3, k + 16)
        loads = []
        for j, r, val in pairs:
            ld = next((_ldrb_imm(w[q]) for q in range(j + 1, min(j + 6, len(w)))
                       if _ldrb_imm(w[q]) and _ldrb_imm(w[q])[0] == r), None)
            if ld:
                loads.append((r, val, ld[1]))
        if len(loads) < 2 or loads[0][2] != 0:
            continue
        (rg, g, _o), (_rp, p, po) = loads[0], loads[1]
        # the ball's byte, right after the player's, is read further on through the same register (or the
        # register the older builds load the player's address into again)
        if not any(_ldrb_imm(w[q]) and _ldrb_imm(w[q])[1] == 1 for q in range(k + 3, min(k + 48, len(w)))):
            continue
        start = _function_start(w, k)
        if start is not None:
            found.add((base + 4 * start, g, p + po))
    return found.pop() if len(found) == 1 else None


def add_player(e, players):
    """The va of the framework's add-a-player function (it stores the new count into `players`), or None."""
    from .adjustments import AdjustmentTable
    try:
        mp = AdjustmentTable(e.d).by_name.get("AD_MAX_PLAYERS_PER_GAME")
    except ValueError:
        return None
    if mp is None:
        return None
    w, base = e.words, e.text_va
    hits = []
    for k in range(1, len(w) - 4):
        if w[k - 1] & PUSH_LR_MASK != PUSH_LR or w[k] not in mov_r0(mp) or bl_target(base + 4 * k + 4, w[k + 1]) is None:
            continue
        pair = _movw_movt(w, k + 2, k + 4)
        if len(pair) != 1:
            continue
        j, rp, val = pair[0]
        # the count: [rP] on most builds, [rP, #off] where the older ones keep it in a struct (Aerosmith LE 1.15 +0x50)
        ld = next((_ldrb_imm(w[q]) for q in range(j + 1, min(j + 3, len(w)))
                   if _ldrb_imm(w[q]) and _ldrb_imm(w[q])[0] == rp), None)
        if not ld or val + ld[1] != players:
            continue
        # strb(ne) rT, [rP, #off]: the count goes up once the game's hooks let the player in (strbne on most builds, a
        # plain strb after the hook's test on the older ones)
        if any(w[q] & 0x0FFF0FFF == 0x05C00000 | rp << 16 | ld[1] and w[q] >> 28 in (0xE, 0x1)
               for q in range(k + 4, min(k + 32, len(w)))):
            hits.append(base + 4 * (k - 1))
    return hits[0] if len(hits) == 1 else None


def ball_getters(e, player):
    """The vas of the framework's "ball in play" getters: movw/movt rN, <player> ; ldrb r0, [rN, #1] ; bx lr."""
    w, base = e.words, e.text_va
    out = []
    for k in range(len(w) - 3):
        if w[k + 3] != 0xE12FFF1E or w[k + 2] & 0xFFF0FFFF != 0xE5D00001:
            continue
        pair = _movw_movt(w, k, k + 2)
        if len(pair) == 1 and pair[0][2] == player and (w[k + 2] >> 16) & 0xF == pair[0][1]:
            out.append(base + 4 * k)
    return out


def first_ball(e, player):
    """PAD-1046: the va of the ball start's `bl <ball getter>` that tells a player's first ball, or None (not once).

    The framework's ball start (TMNT, the symbol build: FUN_001f4dec; Godzilla LE 1.16 0x2a76f0) opens
    proc_kill(0, 0x80) ; ball = <getter> ; ... first = ball == 1 && !<shoot again>, and on a first ball resets the
    player's lamps and flags and calls every rule's first-ball hook (Hook::call(0x37) on TMNT, 0x3e on Godzilla: the
    rules' per-player setup, a battle back to not started). The word after the call is plain (`mov rN, r0`), so the
    runtime can wrap the call where it is made (hook_call)."""
    getters = set(ball_getters(e, player))
    if not getters:
        return None
    w, base = e.words, e.text_va
    hits = []
    for k in range(3, len(w) - 1):
        if bl_target(base + 4 * k, w[k]) not in getters or w[k - 1] >> 24 != 0xEB:
            continue
        if not {0xE3A01080, 0xE3A00000} <= {w[k - 2], w[k - 3]}:          # mov r1, #0x80 ; mov r0, #0 (either order)
            continue
        regs = {0}
        for q in range(k + 1, min(k + 9, len(w))):                       # cmp r0 (or where it was moved), #1
            x = w[q]
            if x & 0xFFFF0FF0 == 0xE1A00000 and x & 0xF in regs:           # mov rD, rS
                regs.add((x >> 12) & 0xF)
            if x & 0xFFF0FFFF == 0xE3500001 and (x >> 16) & 0xF in regs:
                hits.append(base + 4 * k)
                break
    return hits[0] if len(hits) == 1 else None


def player_getter(e, player):
    """The va of the framework's player-up getter (`movw/movt rX, <player> ; ldrb r0, [rX] ; bx lr`), or None."""
    lo, hi = player & 0xFFFF, player >> 16
    w = e.words
    for k in range(len(w) - 3):
        x, y = w[k], w[k + 1]
        if x & 0xFFF00000 != 0xE3000000 or ((x >> 4) & 0xF000 | x & 0xFFF) != lo:
            continue
        r = (x >> 12) & 0xF
        if y & 0xFFF00000 != 0xE3400000 or (y >> 12) & 0xF != r or ((y >> 4) & 0xF000 | y & 0xFFF) != hi:
            continue
        if w[k + 2] == (0xE5D00000 | r << 16) and w[k + 3] == 0xE12FFF1E:
            return e.text_va + 4 * k
    return None


def _lit_test(w, j):
    """`rsb rX, .. ; clz rX, rX ; lsr rX, rX, #5` at word j: this box is the player up's"""
    x = w[j]
    if x & 0xFFE00000 != 0xE0600000:
        return False
    rd = (x >> 12) & 0xF
    clz = [q for q in range(j + 1, min(j + 3, len(w))) if w[q] == (0xE16F0F10 | rd << 12 | rd)]
    return bool(clz) and any(w[q] == (0xE1A002A0 | rd << 12 | rd) for q in range(clz[0] + 1, min(clz[0] + 3, len(w))))


def panel_sites(e, getter):
    """PAD-1043: the score panel's calls of the player-up getter, as (name, va): `coop_panel_lit` - the frame update's
    call, whose answer lights one of the boxes 1-4 (`box == up`, a Text colour for each); `coop_panel_up` - the panel's
    "player changed" check (the getter, then `ldrb rA, [obj, #count + 1] ; cmp rA, r0`, the count being the byte the
    frame update's loop reads), which turns the panel to the player up. Godzilla, Avengers, Jurassic Park The Pin and
    X-Men carry this panel; any other shape, or two of either: none."""
    w, base = e.words, e.text_va
    lit, checks = [], []
    for k in range(len(w) - 2):
        if bl_target(base + 4 * k, w[k]) != getter:
            continue
        ld = _ldrb_imm(w[k + 1])
        if ld and w[k + 2] == 0xE1500000 | ((w[k + 1] >> 12) & 0xF) << 16:   # cmp rA, r0
            checks.append((k, ld[1]))
        end = next((j for j in range(k + 1, min(k + 400, len(w) - 1)) if w[j] & PUSH_LR_MASK == PUSH_LR),
                   min(k + 400, len(w) - 1))                                         # this function's words only
        if not any(_lit_test(w, j) for j in range(k + 1, min(k + 40, end))):
            continue
        ahead = range(k + 1, end)
        if any(w[j] & 0xFFF0FFFF == 0xE3500005 for j in ahead) and any(
                w[j] & 0xFFF00FFF == 0xE5900040 and w[j + 1] & 0xFFFFFFF0 == 0xE12FFF30 for j in ahead):
            lit.append(k)
    if len(lit) != 1:
        return []
    k = lit[0]
    counts = {ld[1] for ld in (_ldrb_imm(w[j]) for j in range(k + 1, min(k + 60, len(w)))) if ld}
    # the panel's own code is near its frame update (X-Men's update has the check twice, once inlined)
    up = [q for q, off in checks if off - 1 in counts and abs(q - k) < 0x2000]
    return [("coop_panel_lit", base + 4 * k)] + [("coop_panel_up" + ("_%d" % (i + 1) if i else ""), base + 4 * q)
                                                 for i, q in enumerate(up[:4])]


def lines(elf):
    """(lines, notes): the co-op port lines of `elf` (the game program's bytes or its path), and what was not found."""
    e = Elf(elf)
    pc = player_change(e)
    if not pc:
        return [], ["no player change of the known shape"]
    fn, player, players = pc
    add = add_player(e, players)
    if add is None:
        return [], ["no add-a-player function of the known shape"]
    out = ["site  coop_player_change 0x%08x 0x%08x 0x%08x" % (fn, e.word(fn), e.word(fn + 4)),
           "site  coop_add_player    0x%08x 0x%08x 0x%08x" % (add, e.word(add), e.word(add + 4)),
           "data  coop_player        0x%08x" % player,
           "data  coop_players       0x%08x" % players]
    # PAD-1046: the ball start's read of the ball that tells a first ball (a later teammate's ball 1 is not one)
    first = first_ball(e, player)
    if first is not None:
        out.append("site  coop_first_ball    0x%08x 0x%08x 0x%08x" % (first, e.word(first), e.word(first + 4)))
    # the team's own high score boards go through the game's end-of-game high scores (PAD-640/663's lines); a build
    # with no challenge list (X-Men) has none of them in its port otherwise. The caller drops what the port has.
    from .portchallenge import message_table, message_text, scores_lines, screen_lines
    scores = scores_lines(e, 0)
    if scores:
        scores += screen_lines(e)
    # whose turn it is: the game's own "BALL %d" line reads "PLAYER 2  BALL %d" (the framework's line, the first)
    table, count = message_table(e)
    ball = next((i for i in range(count) if message_text(e, table, i) == "BALL %d"), None) if table else None
    if ball is not None:
        out += ["data  message_table          0x%08x" % table, "value coop_ball_msg          %d" % ball]
    # PAD-1028: the awards counted from the game's audits (AUD_TOTAL_BALLS_SAVED, ...) - its audit add, hooked
    from .mode_framework import audit_add
    add_at = audit_add(e)
    if add_at:
        out.append("site  audit_add              0x%08x 0x%08x 0x%08x" % (add_at, e.word(add_at), e.word(add_at + 4)))
    # PAD-1043: the score panel's own calls of the player-up getter, answered with the teammate up
    getter = player_getter(e, player)
    for name, at in panel_sites(e, getter) if getter else []:
        out.append("site  %-22s 0x%08x 0x%08x 0x%08x" % (name, at, e.word(at), e.word(at + 4)))
    return out + [line for line in scores if not line.startswith("#")], []
