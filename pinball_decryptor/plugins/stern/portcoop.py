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
    # the team's own high score boards go through the game's end-of-game high scores (PAD-640/663's lines); a build
    # with no challenge list (X-Men) has none of them in its port otherwise. The caller drops what the port has.
    from .portchallenge import scores_lines, screen_lines
    scores = scores_lines(e, 0)
    if scores:
        scores += screen_lines(e)
    return out + [line for line in scores if not line.startswith("#")], []
