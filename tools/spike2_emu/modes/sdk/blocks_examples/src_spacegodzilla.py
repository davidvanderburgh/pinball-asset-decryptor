"""SPACEGODZILLA (PAD-658): the C example spacegodzilla.c (PAD-379) rebuilt in blocks, then (round 2) made a
three-stage multiball that goes deeper and deeper.

Godzilla vs. SpaceGodzilla (1994): SpaceGodzilla plants crystal towers across Fukuoka to draw power; Godzilla and
M.O.G.U.E.R.A. tear them down, break the crystals on his shoulders and cut his power at Fukuoka Tower.

- PLANT A CRYSTAL at the Right ramp: two ramps a crystal the first time, four the second, six the third (6, 12, 18
  ramps for the three); every ramp a note names it and says how many more (RIGHT RAMP, 1  -  MORE TO PLANT A
  CRYSTAL). A multiball's ramps count too (PAD-690). PAD-658: the Right ramp alone, so no two modes share a start (the powerlines
  are KING GHIDORAH's, the Big loop KUMONGA's).
- CRYSTAL 1, 2, 3 (they wait across balls; THE RIGHT RAMP PLANTS THE NEXT). The third: SpaceGodzilla arrives NOTE_S
  (3 s) later, once its note is read, with a 3-ball multiball and a 15 s ball save; while the game's own mode runs it
  waits, and the Right ramp (chasing purple) starts it.
- STAGE 1, CRYSTAL TOWERS: towers on the Left ramp, the Building and the Right ramp; each JACKPOT (1M, +100,000 a
  jackpot) cracks one, a tower falls after 2 (3 the second multiball, 4 the third). All down lights the SUPER JACKPOT
  at the Big loop for 20 s (pack.WINDOW_S): the stage's jackpots summed. Left alone the crystals regrow one stronger.
- EVERY STAGE (PAD-658 round 3): its standing targets chase in its colour and a fallen one goes dark; the line names
  the ones left (TOPPLE THE TOWERS: RAMPS AND BUILDING, then SHOOT THE LEFT OR RIGHT RAMP, then SHOOT THE RIGHT RAMP),
  then the super's shot (SUPER JACKPOT: THE BIG LOOP) chasing white; counter 1 counts the hits to go. The next stage
  lights the moment the super is collected; its title note waits NOTE_S so the super's note is read first.
- STAGE 2, M.O.G.U.E.R.A.: the shield platform turns toward the player; the three shield targets are SpaceGodzilla's
  shoulder crystals (1.5M a jackpot) and every hit is a SPIRAL GRENADE: +250,000 on every jackpot after it. All
  three broken light the SUPER JACKPOT at the Godzilla target: the stage's sum TWICE.
- STAGE 3, SPACE BEAST: his own music; the powerlines are his power (2M a jackpot), one hit more each to cut. All
  cut light FUKUOKA TOWER at the Building: the stage's sum THREE times plus every super before (Lyman's supers worth
  your history): SPACEGODZILLA FALLS.
- Each super adds a ball (up to 6, a 10 s ball save). Each multiball of the game starts 250,000 a jackpot higher.
- ENDS with one ball left after 20 s, a drain, a tilt, or one of the game's own modes beginning: the jackpots not
  yet summed in a super pay half again (CRYSTAL SHARDS).
"""
import itertools

from blk import (AND, BALLS, NOT, OR, RUNNING, a_show, add, award, change, clip, clips, div, end, eq, every, beds,
                 game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_mode, lt, mul, music,
                 multiball, off, on_end, on_shot, on_start, on_timer, score, set_, shake, shake_game, show, shield,
                 sound, sounds, start, step, sub, timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "spacegodzilla", "SPACEGODZILLA"
PURPLE, BLUE, DEEP, WHITE, CYAN, PINK = "#be28ff", "#285aff", "#1e003c", "#ffffff", "#00e6ff", "#ff40c0"
LOCK_SHOT = "Right ramp"             # PAD-658: where the crystals are planted, and the full set starts
POWERLINES = ("Powerline left", "Powerline center", "Powerline right")
SHIELDS = ("Shield target left", "Shield target center", "Shield target right")
#: the three stages: (title, its three shots, the super's shot, the line, counter 1's label, a jackpot's words,
#: a target down, the super's words, the stage's colour, its first jackpot)
STAGES = {
    1: ("CRYSTAL TOWERS", ("Left ramp", "Building", "Right ramp"), "Big loop", "TOPPLE THE TOWERS: RAMPS AND BUILDING",
        "TOWERS",
        "CRYSTAL JACKPOT", "A TOWER FALLS", "SUPER JACKPOT: THE BIG LOOP", PURPLE, 1000000),
    2: ("M.O.G.U.E.R.A.", SHIELDS, "Godzilla target", "SPIRAL GRENADES: THE SHIELDS", "SHOULDERS",
        "SPIRAL GRENADE", "CRYSTAL SHATTERS", "SUPER JACKPOT: GODZILLA TARGET", CYAN, 1500000),
    3: ("SPACE BEAST", POWERLINES, "Building", "CUT HIS POWER: THE POWERLINES", "POWER",
        "POWER JACKPOT", "POWER CUT", "FUKUOKA TOWER: SHOOT THE BUILDING", BLUE, 2000000),
}
HPS = ("hp1", "hp2", "hp3")
TIMERS = ("ramp", "arrive", "jp", "window", "next", "lights", "super", "announce")
SUPER_MS = pack.WINDOW_S * 1000      # the super's window (20 s)
HP = add(add(var("hp1"), var("hp2")), var("hp3"))
NEED = pack.need(2, "plays")         # Right ramps a crystal: 2 the first time, 4 the second, 6 the third (PAD-675: was 1)
#: the port's lamp places: the Big loop (where he lands), the Building (Fukuoka Tower), the centre shield
BL, BLD, SHC = dict(x=195, y=251), dict(x=123, y=202), dict(x=199, y=346)

SHOWS = [
    a_show("Arrival",                                         # SpaceGodzilla descends in a pillar of light
           step("fade_in", 700, PURPLE, "#000000", "xy", gi="dark", **BL),
           step("bolts", 900, WHITE, BLUE, "xy", rate=120, gi="flash", **BL),
           step("implode", 700, WHITE, PURPLE, "xy", gi="dark", **BL),
           step("spiral_out", 1300, PURPLE, DEEP, "xy", gi="dark", **BL),
           step("fade", 500, PURPLE, "#000000", "center", blend=200)),
    a_show("Crystal",                                         # a crystal planted
           step("implode", 600, PURPLE, DEEP, "xy", **BL),
           step("sparkle", 500, WHITE, PURPLE, "center"),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Jackpot",
           step("ripple", 600, WHITE, PURPLE, "center", rate=250, gi="keep"),
           step("fade", 250, PURPLE, "#000000", "center")),
    a_show("Tower falls",
           step("burst", 700, WHITE, PINK, "center", gi="flash"),
           step("sweep_down", 500, PINK, DEEP, "top", gi="dark"),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Super lit",
           step("chase", 900, WHITE, PURPLE, "center", rate=90, gi="dark"),
           step("pulse", 700, WHITE, PURPLE, "center", rate=350, gi="keep")),
    a_show("Super",
           step("implode", 700, WHITE, BLUE, "top", gi="flash"),
           step("rainbow", 1200, "#000000", "#000000", "center", rate=70),
           step("strobe", 400, WHITE, PURPLE, "center", rate=50, gi="flash")),
    a_show("Moguera",                                         # M.O.G.U.E.R.A. separates and flies in
           step("sweep_lr", 450, CYAN, "#000000", "center", gi="dark"),
           step("sweep_rl", 450, WHITE, "#000000", "center", gi="dark"),
           step("spin", 1000, CYAN, DEEP, "xy", rate=90, gi="dark", **SHC),
           step("burst", 600, WHITE, CYAN, "xy", gi="flash", **SHC),
           step("fade", 400, CYAN, "#000000", "center")),
    a_show("Space beast",                                     # lightning between his shoulder crystals
           step("strobe", 400, WHITE, BLUE, "center", rate=55, gi="flash"),
           step("bolts", 1200, WHITE, BLUE, "xy", rate=100, gi="dark", **BLD),
           step("spiral_in", 1100, BLUE, DEEP, "xy", gi="dark", **BLD),
           step("fade", 500, BLUE, "#000000", "center", blend=200)),
    a_show("Regrow",
           step("sparkle", 900, PURPLE, DEEP, "center", gi="dark"),
           step("sweep_up", 600, PURPLE, DEEP, "flippers", gi="dark"),
           step("fade", 400, PURPLE, "#000000", "center")),
    a_show("Won",                                             # Godzilla's burning spiral ray: he explodes
           step("strobe", 600, WHITE, "#ff2000", "center", rate=45, gi="flash"),
           step("fire", 1500, "#ffc000", "#ff2000", "xy", gi="dark", **BLD),
           step("burst", 900, WHITE, PINK, "xy", gi="flash", **BLD),
           step("rainbow", 1800, "#000000", "#000000", "center", rate=50),
           step("fade", 700, PURPLE, "#000000", "center", blend=300)),
    a_show("Escapes",
           step("solid", 500, PURPLE, "#000000", "center", gi="dark"),
           step("spiral_in", 1200, PURPLE, "#000000", "xy", gi="dark", **BL),
           step("fade", 900, DEEP, "#000000", "center", blend=400)),
]


def ramp():
    """A Right ramp while it is not running (a multiball's too, PAD-690): one more toward the next crystal (pack.need)."""
    return [if_(AND(NOT(RUNNING), lt(var("crystals"), 3)), [
        change("ramp hits", 1),
        if_(ge("ramp hits", NEED), [set_("ramp hits", 0)] + plant(),
            [award("RIGHT RAMP", value=sub(NEED, var("ramp hits")), sub="MORE TO PLANT A CRYSTAL",
                   seconds=pack.NOTE_S), sound("lit")])])]


def plant():
    nxt = [award(w, sub="THE RIGHT RAMP PLANTS THE NEXT", seconds=pack.NOTE_S)
           for w in ("CRYSTAL 1 PLANTED", "CRYSTAL 2 PLANTED")]
    return [
        change("crystals", 1), sound("lock"), show("Crystal"),
        if_(ge("crystals", 3), [
            set_("ready", 1), light_mode(LOCK_SHOT, PURPLE, "chase"),
            award("CRYSTAL 3 PLANTED", sub="SPACEGODZILLA ARRIVES", seconds=pack.NOTE_S),
            timer_start("arrive", pack.NOTE_S * 1000)],                  # once its note is read
            [if_(eq("crystals", 1), [nxt[0]], [nxt[1]])])]


def either(shots):
    """The words for shooting any one of ``shots``: SHOOT THE LEFT OR CENTER SHIELD (a noun they share said once),
    else SHOOT THE LEFT RAMP OR BUILDING."""
    words = [pack.SHOT_WORDS[s].split() for s in shots]
    if len(words) > 1 and all(len(w) == 2 for w in words) and len({w[1] for w in words}) == 1:
        return "SHOOT THE %s %s" % (" OR ".join(w[0] for w in words), words[0][1])
    return pack.shoot(*shots)


def stage_lines(shots, line):
    """The line naming the stage's targets still standing (one block per set of them): all three the stage's own
    line, then the ones left by name."""
    out = []
    for up in itertools.product((1, 0), repeat=len(shots)):
        left = [s for s, u in zip(shots, up) if u]
        if left:
            out.append(if_(AND(*[gt(hp, 0) if u else eq(hp, 0) for hp, u in zip(HPS, up)]),
                           [hud_line(line if len(left) == len(shots) else either(left))]))
    return out


def lights():
    """The stage's three shots chasing in its colour (faster the nearer each is to breaking; dark once down), the
    super's shot chasing white while it is lit and blinking fast in its last 6 s; the line names what counts now."""
    out = []
    for k, (_t, shots, sup, line, _c, _j, _f, sup_line, color, _v) in STAGES.items():
        body = [if_(eq(hp, 0), [off(s)], [light(s, color, "chase", add(40, mul(60, var(hp))))])
                for s, hp in zip(shots, HPS)]
        body.append(if_(eq("super lit", 1), [
            if_(lt(timer_left("window"), 6000), [light(sup, WHITE, "blink", 70)],
                [light(sup, WHITE, "chase", 100)]), hud_line(sup_line)], [off(sup)] + stage_lines(shots, line)))
        out.append(if_(eq("stage", k), body))
    return out


def setup_stage():
    """A stage begins (the "next" timer, at once): its targets lit, its title, line and counters; the shields turn.
    Its note, clip and sound come NOTE_S later (announce)."""
    out = [change("stage", 1), set_("super lit", 0), set_("sum", 0), set_("standing", 3),
           *[set_(hp, add(var("strength"), div(var("stage"), 3))) for hp in HPS]]
    for k, (title, shots, sup, line, label, _j, _f, _s, _c, value) in STAGES.items():
        prev = STAGES.get(k - 1)
        body = [hud_title(title), set_("base", add(value, mul(250000, sub(var("plays"), 1)))),
                hud_counter(1, HP, "HITS TO GO", label),
                hud_counter(2, add(var("base"), mul(100000, var("jackpots"))), "STAGE %d OF 3" % k)]
        if prev:
            body += [off(s) for s in prev[1]] + [off(prev[2]), timer_start("announce", pack.NOTE_S * 1000)]
        if k == 2:
            body += [shield("toward")]
        out.append(if_(eq("stage", k), body))
    return out + [timer_start("lights", 1)]


def announce():
    """The stage's note (its title, its line's words: only while none of its jackpots is made yet, so a note the
    player's own shot just put up stays), clip, sound and show."""
    out = []
    for k, (title, _shots, _sup, line, *_r) in STAGES.items():
        if k == 1:
            continue
        body = [shake_game("jackpot"), if_(eq("sum", 0), [award(title, sub=line, seconds=pack.NOTE_S)])]
        if k == 2:
            body += [clip("moguera", "behind"), sound("moguera"), show("Moguera")]
        if k == 3:
            body += [clip("beast", "behind"), sound("beast"), show("Space beast"), music("beast")]
        out.append(if_(eq("stage", k), body))
    return out


def jackpot():
    """A target's jackpot (``hit`` = which of the stage's three)."""
    fell = [AND(eq("hit", i), eq(hp, 0)) for i, hp in enumerate(HPS, 1)]
    fell_any = OR(*fell)
    per_stage_fall = [if_(eq("stage", k), [award(st[6], value=var("got"), sub=st[0], seconds=pack.NOTE_S)])
                      for k, st in STAGES.items()]
    per_stage_jp = [if_(eq("stage", k), [award(st[5], value=var("got"), seconds=pack.NOTE_S), clip(c, "behind")])
                    for (k, st), c in zip(STAGES.items(), ("jackpot", "grenade", "shatter"))]
    return [
        set_("got", add(var("base"), mul(100000, var("jackpots")))),
        score(var("got")), change("sum", var("got")), change("jackpots", 1),
        if_(eq("stage", 2), [change("base", 250000)]),          # M.O.G.U.E.R.A.'s spiral grenade
        *[if_(eq("hit", i), [change(hp, -1)]) for i, hp in enumerate(HPS, 1)],
        if_(fell_any, [change("standing", -1), clip("tower", "behind"), sound("tower"), show("Tower falls"),
                       shake(450, "strong")] + per_stage_fall,
            per_stage_jp + [sound("jackpot"), show("Jackpot"), shake(250, "medium")]),
        if_(AND(eq("super lit", 0), eq("standing", 0)), [
            set_("super lit", 1), timer_start("window", SUPER_MS), show("Super lit"),
            *[if_(eq("stage", k), [award("SUPER JACKPOT IS LIT", value=mul(var("sum"), var("stage")),
                                         sub="%s IN %d S" % (pack.SHOT_WORDS[st[2]], pack.WINDOW_S),
                                         seconds=pack.NOTE_S)]) for k, st in STAGES.items()]]),
        timer_start("lights", 1)]


def super_jackpot():
    add_ball = [if_(eq(BALLS, n - 1), [multiball(n, 10)]) for n in (6, 5, 4, 3, 2)]   # highest first: one ball more
    return [
        set_("got", mul(var("sum"), var("stage"))),
        if_(eq("stage", 3), [change("got", var("history"))]),
        score(var("got")), change("history", var("got")), change("supers", 1), set_("super lit", 0),
        set_("sum", 0), timer_stop("window"),
        if_(eq("stage", 3), [
            set_("won", 1), clip("won", "full"), sound("won"), show("Won"), shake_game("multiball_start"), end()], [
            if_(eq("stage", 1), [award("SUPER JACKPOT", value=var("got"), sub="THE TOWERS' SUM", seconds=3)],
                [award("SUPER JACKPOT", value=var("got"), sub="THE SUM TWICE", seconds=3)]),
            clip("super", "full"), sound("super"), show("Super"), shake(600, "hard"),
            if_(lt(BALLS, 6), add_ball + [sound("add")]),
            timer_start("next", 1)])]                                  # the next stage lights at once


def target(stage, i):
    hp = HPS[i - 1]
    return if_(AND(eq("stage", stage), gt(hp, 0)), [set_("hit", i), timer_start("jp", 1)])


SCRIPTS = [
    # ---- light the locks, plant the crystals -------------------------------------------------------------------
    on_shot(LOCK_SHOT, if_(eq("ready", 1), [if_(lt(BALLS, 2), [start()])], [timer_start("ramp", 1)]), when="idle"),   # PAD-690
    on_timer("ramp", *ramp()),
    on_timer("arrive", start()),

    # ---- the multiball ----------------------------------------------------------------------------------------------
    on_start(set_("ready", 0), set_("crystals", 0), set_("ramp hits", 0), change("plays", 1),
             set_("stage", 0), set_("history", 0), set_("supers", 0), set_("jackpots", 0), set_("won", 0),
             set_("mb secs", 0), set_("strength", add(1, var("plays"))),
             multiball(3, 15),
             award(NAME, sub="CRYSTAL MULTIBALL", seconds=3),
             clip("intro", "full"), clip("loop", "loop"), sound("lock"), game_show("Strobe storm"), show("Arrival"),
             shake(1000, "strong"),
             timer_start("next", 1)),
    on_timer("next", *setup_stage()),
    on_timer("announce", *announce()),
    on_timer("lights", *lights()),
    *[on_shot(s, target(1, i)) for i, s in enumerate(STAGES[1][1], 1) if s != "Building"],
    on_shot("Building", target(1, 2), if_(AND(eq("stage", 3), eq("super lit", 1)), [timer_start("super", 1)])),
    *[on_shot(s, target(2, i)) for i, s in enumerate(SHIELDS, 1)],
    *[on_shot(s, target(3, i)) for i, s in enumerate(POWERLINES, 1)],
    on_timer("jp", *jackpot()),
    on_shot("Big loop", if_(AND(eq("stage", 1), eq("super lit", 1)), [timer_start("super", 1)])),
    on_shot("Godzilla target", if_(AND(eq("stage", 2), eq("super lit", 1)), [timer_start("super", 1)])),
    on_timer("super", *super_jackpot()),
    # the window ran out: the stage's crystals regrow, one stronger (the sum stays for the next super)
    on_timer("window", if_(eq("super lit", 1), [
        set_("super lit", 0), change("strength", 1), set_("standing", 3),
        *[set_(hp, var("strength")) for hp in HPS],
        award("CRYSTALS REGROW", sub="ONE HIT STRONGER", seconds=pack.NOTE_S), show("Regrow"), shake(600, "soft"),
        timer_start("lights", 1)])),
    # one ball left after the ball save and a few seconds more; the super's last seconds blink faster
    every(1, change("mb secs", 1), if_(AND(ge("mb secs", 20), lt(BALLS, 2)), [end()]),
          if_(eq("super lit", 1), [timer_start("lights", 1)])),
    on_end(*[timer_stop(t) for t in TIMERS],
           if_(eq("won", 1), [hud_title("SPACEGODZILLA FALLS"), hud_line("EVERY SUPER AGAIN")], [
               hud_title("SPACEGODZILLA ESCAPES"), hud_line("CRYSTAL SHARDS: HALF THE SUM"),
               score(div(var("sum"), 2)),
               clip("lost", "full"), sound("lost", fallback="time_up"), show("Escapes"), game_show("Blue fade"),
               shake_game("rumble")]),
           set_("stage", 0)),
]


PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 190,
    "vars": [{"name": n, "reset": "game"} for n in ("plays", "crystals", "ramp hits", "ready")] +
            [{"name": n, "reset": "mode"} for n in ("stage", "base", "strength", "hp1", "hp2", "hp3", "standing",
                                                     "jackpots", "sum", "history", "supers", "super lit", "mb secs",
                                                     "hit", "got", "won")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud(STAGES[1][3],
               counters=[("TOWERS", "HITS TO GO", HP),
                         ("JACKPOT", "STAGE 1 OF 3", add(var("base"), mul(100000, var("jackpots")))),
                         ("SUPER", "THE SUM", var("sum"))],
               gauge={"label": "CRYSTALS", "kind": "segment", "count": 12, "color": PURPLE, "value": HP}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "jackpot", "tower", "super", "won", "lost", "moguera", "grenade", "beast",
                   "shatter"),
    "sounds": sounds({"lit": 3, "lock": 3, "jackpot": 3, "tower": 4, "super": 4, "add": 3, "won": 4, "lost": 4,
                      "moguera": 4, "beast": 4, "shatter": 3}),
    "music": "music.wav",
    "beds": beds("beast"),
    "shows": SHOWS,
}

LOST = [
    "No points while the mode is not running: the C pays 250,000 a crystal times its number (250,000, 500,000, "
    "750,000) as it is planted; the blocks' Score only scores while the mode runs.",
    "The crystals are planted at the Right ramp, not locked at the Big loop after the powerlines light a lock (PAD-658: "
    "the powerlines are KING GHIDORAH's start, the Big loop KUMONGA's): no lock is lit, and only the full set (three "
    "crystals, waiting for the game's mode to end) chases purple at the Right ramp.",
    "No badge for the super's 20 s window: the badge counts the mode's own clock, and this multiball has none, so "
    "the window shows as the line (SUPER JACKPOT: THE BIG LOOP) and its shot chasing white, blinking fast in its "
    "last 6 s (looked at once a second).",
    "The super's added ball is asked as a multiball of one more ball than are in play (the blocks have no add-a-ball "
    "block), with its 10 s ball save.",
    "Another mode of ours running does not stop the Right ramp planting crystals (the blocks cannot tell one of our "
    "other modes runs; the C waits for it). A multiball still stops it.",
    "SpaceGodzilla arrives 3 s after the third crystal (PAD-658: its note is read first), where the C took 1.5 s.",
    "The ending's line says how it ended (EVERY SUPER AGAIN after the finale, CRYSTAL SHARDS: HALF THE SUM "
    "otherwise) where the C counted 7 JACKPOTS  -  1 SUPER.",
    "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
    "No light show of its own at the start and the end where the game has none (the C falls back on its own when the "
    "game's Strobe storm or Blue fade will not play): the blocks play the game's (and the mode's own shows beside).",
    "A tilt or the game moving on ends it as any blocks mode ends (the C also ends at once without its total).",
    "The C's three multiballs in turn (CRYSTAL TOWERS, M.O.G.U.E.R.A., SPACE BEAST, one per start) are now the three "
    "stages of every multiball, and the C's first-time rule (one powerline lit every lock) is now one hit a lock.",
]

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 108, "titles": ["godzilla_le", "godzilla_pro"],
    "based_on": "spacegodzilla.c",
    # PAD-658: a Pro's centre shield is the Maser target, and its lines say so
    "title_alt": {"godzilla_pro": {"shots": {"Shield target center": "Maser target"}, "words": {
        "SHOOT THE CENTER OR RIGHT SHIELD": "SHOOT THE MASER OR RIGHT SHIELD",
        "SHOOT THE CENTER SHIELD": "SHOOT THE MASER TARGET",
        "SHOOT THE LEFT OR CENTER SHIELD": "SHOOT THE LEFT SHIELD OR MASER",
        "SPIRAL GRENADES: THE SHIELDS": "SPIRAL GRENADES: SHIELDS AND MASER"}}},
    "about": ("The C example SPACEGODZILLA rebuilt in blocks and taken deeper (PAD-658): Right ramps plant the "
              "crystals (two a crystal the first time, four the second, six the third), and three crystals "
              "start a 3-ball multiball in three stages: CRYSTAL TOWERS (the ramps and the Building, a "
              "super at the Big loop), M.O.G.U.E.R.A. (the shoulder crystals at the shields, every hit a spiral "
              "grenade raising the jackpots, the super twice its sum at the Godzilla target) and SPACE BEAST (his "
              "own music, the powerlines cut, FUKUOKA TOWER at the Building: three times the sum and every super "
              "before). Each super adds a ball. On a Pro the Maser target is the centre shoulder crystal."),
    "lost": LOST,
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(*names, gap=300):
    out = []
    for n in names:
        out += ["shot", n, "ms", gap]
    return out


_START = ["trigger", "spacegodzilla.start", "secs", 2]
_STOP = ["secs", 2, "trigger", "spacegodzilla.stop", "secs", 4, "balls", 1, "secs", 1]
_STAGE1 = _shots("Left ramp", "Left ramp", "Building", "Building", "Right ramp", "Right ramp") + ["secs", 1]
_STAGE2 = _shots(*[s for s in SHIELDS for _i in (1, 2)]) + ["secs", 1]
_STAGE3 = _shots(*[s for s in POWERLINES for _i in (1, 2, 3)]) + ["secs", 1]
_RAMP = _shots("Right ramp", gap=600)
DESK = [
    ("two Right ramps a crystal the first time, four the second",
     _RAMP * 6 + ["secs", 7] + _STOP + _RAMP * 12 + ["secs", 7],
     ["Hud_Award: CRYSTAL 1 PLANTED", "Hud_AwardSub: THE RIGHT RAMP PLANTS THE NEXT", "Hud_Award: CRYSTAL 3 PLANTED",
      "[SPACEGODZILLA] START (a block)", "MULTIBALL 3 balls, save 15 s", "Hud_Title: CRYSTAL TOWERS",
      "Hud_Line: TOPPLE THE TOWERS: RAMPS AND BUILDING", "Hud_C1_Sub: HITS TO GO", "Hud_C1_Value: 6",
      "LAMP LEFT RAMP be28ff chase 160", "Hud_Award: RIGHT RAMP", "Hud_AwardSub: 1  -  MORE TO PLANT A CRYSTAL",
      "LAMP LEFT RAMP be28ff chase 220"]),        # the second multiball: towers one hit stronger
    ("towers fall, the super is their sum and adds a ball, M.O.G.U.E.R.A. comes",
     _START + _STAGE1 + _shots("Big loop") + ["secs", 5],
     ["SCORE +1000000", "SCORE +1500000", "Hud_Award: A TOWER FALLS", "Hud_C1_Value: 4",
      "Hud_Line: SHOOT THE BUILDING OR RIGHT RAMP", "Hud_Line: SHOOT THE RIGHT RAMP", "Hud_C1_Value: 1",
      "Hud_Award: SUPER JACKPOT IS LIT", "Hud_AwardSub: 7,500,000  -  BIG LOOP IN 20 S",
      "Hud_Line: SUPER JACKPOT: THE BIG LOOP", "SCORE +7500000", "Hud_Award: SUPER JACKPOT",
      "MULTIBALL 4 balls, save 10 s", "Hud_Title: M.O.G.U.E.R.A.", "SHIELD toward",
      "Hud_Line: SPIRAL GRENADES: THE SHIELDS", "Hud_Award: M.O.G.U.E.R.A.",
      "Hud_AwardSub: SPIRAL GRENADES: THE SHIELDS", "LAMP SHIELD CENTER 00e6ff chase"]),
    ("all three stages: FUKUOKA TOWER pays every super again",
     _START + _STAGE1 + _shots("Big loop") + ["secs", 2] + _STAGE2 + _shots("Godzilla target") + ["secs", 2] +
     _STAGE3 + _shots("Building") + ["secs", 6],
     ["Hud_Award: SPIRAL GRENADE", "Hud_Line: SHOOT THE CENTER OR RIGHT SHIELD", "Hud_Line: SHOOT THE RIGHT SHIELD",
      "Hud_Award: CRYSTAL SHATTERS", "Hud_Line: SUPER JACKPOT: GODZILLA TARGET", "Hud_Title: SPACE BEAST",
      "Hud_Line: CUT HIS POWER: THE POWERLINES", "Hud_Line: SHOOT THE CENTER OR RIGHT POWERLINE",
      "Hud_Line: SHOOT THE RIGHT POWERLINE", "Hud_Award: POWER CUT", "Hud_Line: FUKUOKA TOWER: SHOOT THE BUILDING",
      "SCORE +140400000", "END (a block)", "Hud_Title: SPACEGODZILLA FALLS", "lamps held 0"]),
    ("left alone the crystals regrow",
     _START + _STAGE1 + ["secs", 21],
     ["Hud_Award: SUPER JACKPOT IS LIT", "LAMP BIG LOOP ffffff blink 70", "Hud_Award: CRYSTALS REGROW",
      "Hud_Line: TOPPLE THE TOWERS: RAMPS AND BUILDING", "LAMP OFF BIG LOOP", "LAMP LEFT RAMP be28ff chase 220"]),
    ("one ball left ends it: half the sum",
     _START + _shots("Left ramp", "Left ramp") + ["secs", 1, "balls", 1, "secs", 22],
     ["SCORE +1100000", "END (a block)", "Hud_Title: SPACEGODZILLA ESCAPES", "Hud_Line: CRYSTAL SHARDS: HALF THE SUM",
      "SCORE +1050000", "lamps held 0"]),
    ("a drain ends it", _START + _shots("Left ramp") + ["secs", 1, "ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
    # PAD-690: a multiball's ramps plant too; PAD-675: the full set made just before the game's mode begins, and
    # SpaceGodzilla, arriving NOTE_S after the third crystal, waits for it
    ("a multiball's ramps plant, a full set waits for the game's mode",
     ["balls", 2, "secs", 1] + _RAMP * 2 + ["balls", 1, "secs", 1] + _RAMP * 4 +
     ["timed", 1, "secs", 5, "timed", 0, "secs", 1] + _RAMP + ["secs", 2],
     ["not started", "LAMP RIGHT RAMP be28ff chase", "[SPACEGODZILLA] START (its lit shot)",
      "MULTIBALL 3 balls, save 15 s"]),
]

#: PAD-658: as a Pro gets it - its shields are fixed (no platform to turn) and the Maser target is the centre
#: shoulder crystal
DESK_PRO = [
    ("M.O.G.U.E.R.A. on the fixed shields and the Maser",
     _START + _STAGE1 + _shots("Big loop") + ["secs", 2] +
     _shots("Shield target left", "Shield target left", "Maser target", "Maser target", "Shield target right",
            "Shield target right") + ["secs", 1] + _shots("Godzilla target") + ["secs", 2],
     ["Hud_Title: M.O.G.U.E.R.A.", "Hud_Award: SPIRAL GRENADE", "Hud_Award: CRYSTAL SHATTERS",
      "Hud_Title: SPACE BEAST"]),
]
