"""SPACEGODZILLA (PAD-658): the C example spacegodzilla.c (PAD-379) rebuilt in blocks.

Godzilla vs. SpaceGodzilla (1994): SpaceGodzilla plants crystal towers across Fukuoka to draw power; Godzilla and
M.O.G.U.E.R.A. tear them down.

- LIGHT A LOCK at the powerlines: the first multiball, any powerline lights every lock left; the second, each hit
  lights one; from the third, two hits a lock. Nothing lights or locks in a multiball.
- LOCK at the Big loop: CRYSTAL 1, 2, 3 (the locks wait across balls). The third: SpaceGodzilla arrives 1.5 s later
  with CRYSTAL MULTIBALL, 3 balls and a 15 s ball save; while the game's own mode runs it waits, and the Big loop
  (blinking purple) starts it.
- THE TOWERS on the Left ramp, the Building and the Right ramp: each JACKPOT (from the base, +100,000 a jackpot)
  cracks one; a tower falls after 2 (3 from the second multiball). All down lights the SUPER JACKPOT at the Big loop
  for 20 s, worth every jackpot since the last; the first three supers add a ball; then the towers grow back one
  jackpot stronger (the window running out grows them back too).
- IN TURN: 1 CRYSTAL TOWERS (1,000,000), 2 M.O.G.U.E.R.A. (1,500,000; the shields turn toward the player and each
  shield target adds 250,000 to every jackpot), 3 SPACE BEAST (2,000,000; every 5th jackpot lights the super too).
- ENDS with one ball left after 20 s, a drain, a tilt, or one of the game's own modes beginning.
"""
from blk import (AND, BALLS, NOT, OR, RUNNING, a_show, add, award, change, clip, clips, div, end, eq, every,
                 game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_mode, lt, mul,
                 multiball, off, on_end, on_shot, on_start, on_timer, score, set_, show, shield, sound, sounds,
                 start, step, sub, timer_start, timer_stop, var)

SLUG, NAME = "spacegodzilla", "SPACEGODZILLA"
PURPLE, BLUE, DEEP, WHITE, CYAN = "#be28ff", "#285aff", "#1e003c", "#ffffff", "#00e6ff"
LOCK_SHOT = "Big loop"
TOWERS = (("Left ramp", "hp l", "LEFT RAMP"), ("Building", "hp b", "BUILDING"), ("Right ramp", "hp r", "RIGHT RAMP"))
SHIELDS = ("Shield target left", "Shield target center", "Shield target right")
POWERLINES = ("Powerline left", "Powerline center", "Powerline right")
KINDS = (("CRYSTAL TOWERS", 1000000), ("M.O.G.U.E.R.A.", 1500000), ("SPACE BEAST", 2000000))
TITLES = ("SPACEGODZILLA", "M.O.G.U.E.R.A.", "SPACE BEAST")
TIMERS = ("line", "arrive", "jp", "window", "grow", "lights")
HP = add(add(var("hp l"), var("hp b")), var("hp r"))

SHOWS = [
    a_show("Crystal",                                       # a crystal erupts
           step("implode", 600, PURPLE, DEEP, "top"),
           step("sparkle", 500, WHITE, PURPLE, "center"),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Tower falls",
           step("burst", 700, WHITE, PURPLE, "center", gi="flash"),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Super",
           step("implode", 700, WHITE, BLUE, "top", gi="flash"),
           step("rainbow", 1200, "#000000", "#000000", "center", rate=70),
           step("strobe", 400, WHITE, PURPLE, "center", rate=50, gi="flash")),
]


def lock_words(sub_words):
    return [if_(gt("lit", 1), [award("LOCKS ARE LIT", sub=sub_words, seconds=2)],
                [award("LOCK IS LIT", sub=sub_words, seconds=2)]), sound("lit")]


def line_now():
    """The instruction line while the super is not lit."""
    return [if_(eq("kind", 1), [hud_line("SHATTER TOWERS - SHIELDS RAISE JACKPOTS")],
                [hud_line("SHATTER THE CRYSTAL TOWERS")]), hud_counter(3, var("sum"), "THE SUM")]


def tower_lights():
    out = [if_(eq(hp, 0), [off(s)], [if_(eq(hp, 1), [light(s, PURPLE, "blink", 200)],
                                             [light(s, PURPLE, "blink", 500)])]) for s, hp, _w in TOWERS]
    return out + [if_(eq("super lit", 1), [light(LOCK_SHOT, WHITE, "blink", 120)], [off(LOCK_SHOT)])]


def powerline():
    """A powerline hit while it is not running and no multiball: a lock lit (one hit lights all at first)."""
    return [if_(AND(NOT(RUNNING), lt(BALLS, 2), lt(add(var("crystals"), var("lit")), 3)), [
        if_(eq("plays", 0), [set_("lit", sub(3, var("crystals")))] + lock_words("SHOOT THE BIG LOOP"), [
            change("line hits", 1),
            if_(OR(eq("plays", 1), ge("line hits", 2)), [set_("line hits", 0), change("lit", 1)]
                + lock_words("SHOOT THE BIG LOOP"),
                [award("CRYSTALS GROWING", sub="ONE MORE POWERLINE LIGHTS A LOCK", seconds=2)])])])]


def plant():
    nxt = [if_(gt("lit", 0), [award(w, sub="ANOTHER LOCK IS LIT", seconds=2)],
               [award(w, sub="POWERLINES LIGHT THE NEXT LOCK", seconds=2)]) for w in ("CRYSTAL 1 PLANTED",
                                                                                     "CRYSTAL 2 PLANTED")]
    return [
        change("lit", -1), change("crystals", 1), sound("lock"), show("Crystal"),
        if_(ge("crystals", 3), [
            set_("ready", 1), light_mode(LOCK_SHOT, PURPLE, "blink"),
            award("CRYSTAL 3 PLANTED", sub="SPACEGODZILLA ARRIVES", seconds=3),
            timer_start("arrive", 1500)],
            [if_(eq("crystals", 1), [nxt[0]], [nxt[1]])])]


def jackpot():
    """A tower's jackpot (``hit`` = which tower)."""
    fell = OR(*[AND(eq("hit", i), eq(hp, 0)) for i, (_s, hp, _w) in enumerate(TOWERS, 1)])
    return [
        set_("got", add(var("base"), mul(100000, var("jackpots")))),
        score(var("got")), change("sum", var("got")), change("jackpots", 1), change("since", 1),
        *[if_(eq("hit", i), [change(hp, -1)]) for i, (_s, hp, _w) in enumerate(TOWERS, 1)],
        if_(fell, [change("standing", -1), show("Tower falls"), clip("tower", "behind"), sound("tower")]
            + [if_(eq("hit", i), [award(w + " TOWER FALLS", value=var("got"), seconds=2)])
               for i, (_s, _hp, w) in enumerate(TOWERS, 1)],
            [award("JACKPOT", value=var("got"), seconds=2), clip("jackpot", "behind"), sound("jackpot")]),
        # every tower down (SPACE BEAST: every 5th jackpot too) lights the super for 20 s
        if_(AND(eq("super lit", 0), OR(eq("standing", 0),
                                       AND(eq("kind", 2), eq(sub(var("since"), mul(div(var("since"), 5), 5)), 0)))), [
            set_("super lit", 1), timer_start("window", 20000),
            award("SUPER JACKPOT IS LIT", sub="SHOOT THE BIG LOOP", seconds=3),
            hud_line("SUPER JACKPOT: SHOOT THE BIG LOOP"), hud_counter(3, var("sum"), "BIG LOOP")]),
        timer_start("lights", 1)]


def super_jackpot():
    add_ball = [if_(eq(BALLS, n - 1), [multiball(n, 10)]) for n in (2, 3, 4, 5, 6)]
    return [
        score(var("sum")), change("supers", 1), set_("super lit", 0), timer_stop("window"),
        award("SUPER JACKPOT", value=var("sum"), seconds=3), show("Super"), clip("super", "full"), sound("super"),
        # the first three supers add a ball (a multiball of one more than in play)
        if_(AND(le("supers", 3), lt(BALLS, 6)), add_ball + [change("added", 1), sound("add")]),
        set_("sum", 0), set_("since", 0),
        if_(eq("standing", 0), [timer_start("grow", 1)]),
        *line_now(), timer_start("lights", 1)]


SCRIPTS = [
    # ---- light the locks, plant the crystals -------------------------------------------------------------------
    *[on_shot(s, timer_start("line", 1), when="idle") for s in POWERLINES],
    on_timer("line", *powerline()),
    on_shot(LOCK_SHOT, if_(lt(BALLS, 2), [if_(eq("ready", 1), [start()], [if_(gt("lit", 0), plant())])]),
            when="idle"),
    on_timer("arrive", start()),

    # ---- the multiball -----------------------------------------------------------------------------------------
    on_start(set_("ready", 0), set_("crystals", 0), set_("lit", 0), set_("line hits", 0),
             set_("kind", var("plays")), if_(gt("kind", 2), [set_("kind", 2)]), change("plays", 1),
             *[if_(eq("kind", k), [set_("base", base), hud_title(TITLES[k]), award(name, sub="MULTIBALL", seconds=3)])
               for k, (name, base) in enumerate(KINDS)],
             set_("strength", 2), if_(gt("kind", 0), [set_("strength", 3)]),
             *[set_(hp, var("strength")) for _s, hp, _w in TOWERS], set_("standing", 3),
             multiball(3, 15),
             clip("intro", "full"), clip("loop", "loop"), game_show("Strobe storm"),
             if_(eq("kind", 1), [shield("toward")] + [light(s, CYAN, "pulse", 900) for s in SHIELDS]),
             *line_now(), timer_start("lights", 1)),
    on_timer("lights", *tower_lights()),
    *[on_shot(s, if_(gt(hp, 0), [set_("hit", i), timer_start("jp", 1)])) for i, (s, hp, _w) in enumerate(TOWERS, 1)],
    on_timer("jp", *jackpot()),
    on_shot(LOCK_SHOT, if_(eq("super lit", 1), super_jackpot())),
    on_timer("window", if_(eq("super lit", 1), [
        set_("super lit", 0), award("THE CRYSTALS GROW BACK", seconds=2),
        if_(eq("standing", 0), [timer_start("grow", 1)]), *line_now(), timer_start("lights", 1)])),
    on_timer("grow", change("strength", 1), *[set_(hp, var("strength")) for _s, hp, _w in TOWERS],
             set_("standing", 3), timer_start("lights", 1)),
    # M.O.G.U.E.R.A.'s spiral grenades: every shield target, +250,000 on every jackpot
    *[on_shot(s, if_(eq("kind", 1), [change("base", 250000),
                                     award("SPIRAL GRENADE", sub="+250,000 ON EVERY JACKPOT", seconds=1),
                                     sound("add")])) for s in SHIELDS],
    # one ball left after the ball save and a few seconds more
    every(1, change("mb secs", 1), if_(AND(ge("mb secs", 20), lt(BALLS, 2)), [end()])),
    on_end(*[timer_stop(t) for t in ("jp", "window", "grow", "lights")], game_show("Blue fade"),
           if_(gt("supers", 0), [clip("won", "full"), sound("won"), hud_title("SPACEGODZILLA FALLS")],
               [clip("lost", "full"), sound("lost", fallback="time_up"), hud_title("SPACEGODZILLA ESCAPES")]),
           # its jackpots and supers under the title (a number can only come last)
           *[if_(eq("supers", n), [hud_line("%d SUPER%s  -  JACKPOTS" % (n, "" if n == 1 else "S"),
                                            value=var("jackpots"))]) for n in range(4)],
           if_(gt("supers", 3), [hud_line("JACKPOTS", value=var("jackpots"))])),
]


PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 190,
    "vars": [{"name": n, "reset": "game"} for n in ("plays", "crystals", "lit", "line hits", "ready")] +
            [{"name": n, "reset": "mode"} for n in ("kind", "base", "strength", "hp l", "hp b", "hp r", "standing",
                                                     "jackpots", "since", "sum", "supers", "super lit", "added",
                                                     "mb secs", "hit", "got")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SHATTER THE CRYSTAL TOWERS",
               counters=[("TOWERS", "STANDING", var("standing")),
                         ("JACKPOT", " ", add(var("base"), mul(100000, var("jackpots")))),
                         ("SUPER", "THE SUM", var("sum"))],
               gauge={"label": "CRYSTALS", "kind": "segment", "count": 9, "color": PURPLE, "value": HP}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "jackpot", "tower", "super", "won", "lost"),
    "sounds": sounds({"lit": 3, "lock": 3, "jackpot": 3, "tower": 4, "super": 4, "add": 3, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

LOST = [
    "No points while the mode is not running: the C pays 250,000 a crystal times its number (250,000, 500,000, "
    "750,000) as it is planted; the blocks' Score only scores while the mode runs.",
    "A lit lock does not blink the Big loop purple: the blocks light inserts only while the mode runs, and a mode lit "
    "at a shot starts on it, so only the full set (three crystals, waiting for the game's mode to end) blinks there; "
    "the notes say LOCK IS LIT and SHOOT THE BIG LOOP.",
    "No badge for the super's 20 s window: the badge counts the mode's own clock, and this multiball has none, so "
    "the window shows as the line SUPER JACKPOT: SHOOT THE BIG LOOP and the Big loop blinking white fast (the C "
    "blinks it faster as the window runs out).",
    "The super's added ball is asked as a multiball of one more ball than are in play (the blocks have no add-a-ball "
    "block), with its 10 s ball save.",
    "Another mode of ours running does not stop the powerlines lighting locks or the Big loop planting crystals (the "
    "blocks cannot tell one of our other modes runs; the C waits for it). A multiball still stops them.",
    "The ending's line puts the jackpots last (1 SUPER  -  JACKPOTS 7) where the C said 7 JACKPOTS  -  1 SUPER, "
    "says JACKPOTS for one too, and past 3 supers says only the jackpots.",
    "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
    "No light show of its own at the start and the end where the game has none (the C falls back on its own when the "
    "game's Strobe storm or Blue fade will not play): the blocks play the game's.",
    "A tilt or the game moving on ends it as any blocks mode ends (the C also ends at once without its total).",
]

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 108, "titles": ["godzilla_le"], "based_on": "spacegodzilla.c",
    "about": ("The C example SPACEGODZILLA rebuilt in blocks: the powerlines light the locks, harder each time; "
              "three crystals planted at the Big loop start a 3-ball multiball whose towers fall to jackpots for a "
              "super worth their sum; the three multiballs in turn are CRYSTAL TOWERS, M.O.G.U.E.R.A. and SPACE "
              "BEAST."),
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


_START = ["trigger", "spacegodzilla.start", "secs", 1]
_STOP = ["secs", 2, "trigger", "spacegodzilla.stop", "secs", 4, "balls", 1, "secs", 1]
#: KING GHIDORAH (in the same pack) also counts the powerlines and its notes would cover these: run it once so it
#: is done for the ball
_QUIET = ["trigger", "ghidorah_heads.start", "secs", 1, "trigger", "ghidorah_heads.stop", "secs", 5]
_TOWERS_DOWN = _shots("Left ramp", "Left ramp", "Building", "Building", "Right ramp", "Right ramp")
DESK = [
    ("the first set of locks starts it",
     _QUIET + _shots("Powerline left", gap=600) + _shots("Big loop", gap=600) * 3 + ["secs", 3],
     ["Hud_Award: LOCKS ARE LIT", "Hud_Award: CRYSTAL 1 PLANTED", "Hud_AwardSub: ANOTHER LOCK IS LIT",
      "Hud_Award: CRYSTAL 3 PLANTED", "[SPACEGODZILLA] START (a block)", "MULTIBALL 3 balls, save 15 s",
      "Hud_Award: CRYSTAL TOWERS", "Hud_Title: SPACEGODZILLA", "LAMP LEFT RAMP be28ff blink 500"]),
    ("towers fall, the super is the sum and adds a ball",
     _START + _TOWERS_DOWN + ["secs", 1] + _shots("Big loop") + ["secs", 2] + _shots("Left ramp") +
     ["secs", 1, "balls", 1, "secs", 25],
     ["SCORE +1000000", "SCORE +1500000", "Hud_Award: LEFT RAMP TOWER FALLS 1,100,000",
      "Hud_Award: SUPER JACKPOT IS LIT", "Hud_Line: SUPER JACKPOT: SHOOT THE BIG LOOP", "SCORE +7500000",
      "Hud_Award: SUPER JACKPOT 7,500,000", "MULTIBALL 4 balls, save 10 s", "Hud_Award: JACKPOT 1,600,000",
      "END (a block)", "Hud_Title: SPACEGODZILLA FALLS", "Hud_Line: 1 SUPER  -  JACKPOTS", "lamps held 0"]),
    ("the second is M.O.G.U.E.R.A.",
     _QUIET + _START + _STOP + _shots("Powerline center", "Big loop", gap=600) + _START +
     _shots("Shield target left", "Left ramp") + ["secs", 1, "ball_end", "secs", 8],
     ["Hud_Award: CRYSTAL 1 PLANTED", "Hud_AwardSub: POWERLINES LIGHT THE NEXT LOCK", "Hud_Title: M.O.G.U.E.R.A.",
      "SHIELD toward", "LAMP SHIELD", "Hud_Award: SPIRAL GRENADE", "SCORE +1750000", "END (ball ended)",
      "lamps held 0"]),
    ("the third is SPACE BEAST",
     _QUIET + _START + _STOP + _START + _STOP + _shots("Powerline right", gap=600) + _START +
     _shots("Left ramp", "Building", "Right ramp", "Left ramp", "Building") + ["secs", 21],
     ["Hud_Award: CRYSTALS GROWING", "Hud_Title: SPACE BEAST", "SCORE +2400000", "Hud_Award: SUPER JACKPOT IS LIT",
      "Hud_Award: THE CRYSTALS GROW BACK"]),
    ("nothing locks in a multiball, a full set waits for the game's mode",
     ["balls", 2, "secs", 1] + _shots("Powerline left", "Big loop") + ["balls", 1, "secs", 1] +
     _shots("Powerline left", gap=600) + _shots("Big loop", gap=600) * 2 + ["timed", 1, "secs", 1] +
     _shots("Big loop") + ["secs", 3, "timed", 0, "secs", 1] + _shots("Big loop") + ["secs", 2],
     ["not started", "LAMP BIG LOOP be28ff blink", "[SPACEGODZILLA] START (its lit shot)",
      "MULTIBALL 3 balls, save 15 s"]),
]
