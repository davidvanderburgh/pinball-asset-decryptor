"""KAMACURAS (PAD-658): waves of giant mantises swoop down the playfield; the closer the kill, the more it pays.

Son of Godzilla (1967) and Godzilla: Final Wars (2004). The rules are DESTOROYAH's (PAD-379, after Lyman Sheats'
Horde in The Walking Dead: walkers advance, a closer kill pays more, each wave needs one more kill, a cleared wave
pays its kills again, a boss at the end), re-themed for Kamacuras, whose art is under the right scoop's lights.

David, PAD-658: "modify the Kamacuras mode to require more to start it and make its shots more obvious."

- TO START IT (was: 30 Top spinner spins, 10 more each time, and it started at once): 50 spins of the Top spinner
  (20 more each time) light the RIGHT SCOOP, its own corner; the scoop starts it. Nothing counts in a multiball.
- THE MANTISES are far more obvious: a mantis's shot CHASES fast in its ring's colour (far green, near yellow, close
  red, the closer the faster), the flasher over it blinks, the HUD's line names where every mantis is
  ("MANTIS AT THE LEFT RAMP"), and each one swoops in with its own clip, screech and a ripple light show centred on
  its shot. Everything else on the playfield of ours stays dark.
- THE SWARM: mantises land at the powerlines (FAR, x1), advance every 7 s (6, 5 a wave) to the ramps, the Big loop
  or the Building (NEAR, x2), then the Maser, the Godzilla target or the right shield (CLOSE, x4), then strike
  Godzilla. Up to two at once. A kill pays 1M (+250K a wave) times its closeness.
- WAVES: 3, 4, then 5 kills; a cleared wave pays its kills again. Three strikes on Godzilla and the swarm wins.
- No clock while the waves come (DESTOROYAH's has none either: three strikes end it); THE BIGGEST MANTIS: after
  wave 3, the Building for 25 s: three hits of 5M; the third is the SUPER JACKPOT, every
  kill of the mode again.
"""
from blk import (AND, BALLS, OR, a_show, add, add_time, award, callout, change, clip, clips, div, end, eq, every, ge,
                 gt, timer_left,
                 hud, hud_counter, hud_line, hud_title, if_, light, light_insert, light_mode, lt, mul, off, off_insert, on_end,
                 on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game, shield, show, sound,
                 sounds, step, sub, timer_start, timer_stop, var)
import pack

SLUG, NAME = "kamacuras", "KAMACURAS"
GREEN, YELLOW, RED, WHITE, DARK = "#20ff40", "#d0ff00", "#ff1010", "#ffffff", "#002008"
SPIN, START_SHOT = "Top spinner", pack.CASH_SHOT
START_INSERTS = ",".join(pack.CASH_INSERTS)
NEED = add(50, mul(20, var("fought")))
#: the rings, far to close: (shot, the words that name it on the HUD, the flasher or insert beside it)
RINGS = (
    (("Powerline left", "THE LEFT POWERLINE"), ("Powerline center", "THE CENTER POWERLINE"),
     ("Powerline right", "THE RIGHT POWERLINE")),
    (("Left ramp", "THE LEFT RAMP"), ("Right ramp", "THE RIGHT RAMP"), ("Big loop", "THE BIG LOOP"),
     ("Building", "THE BUILDING")),
    (("Maser target", "THE MASER"), ("Godzilla target", "THE GODZILLA TARGET"),
     ("Shield target right", "THE RIGHT SHIELD")),
)
RING_COLOR = (GREEN, YELLOW, RED)
RING_PACE = (160, 110, 60)
RING_WORD = ("FAR", "NEAR", "CLOSE")
TIMERS = ("advance", "spawn", "lights", "kill", "wave", "boss", "strike", "boss clock")


def every_shot():
    return [(r, i, s, w) for r, ring in enumerate(RINGS, 1) for i, (s, w) in enumerate(ring, 1)]


def at(m, r, i):
    return AND(eq(m + " ring", r), eq(m + " at", i))


def kills_counter():
    """KILLS: this wave's kills, out of the kills it needs (3, 4, 5)."""
    return [if_(eq("wave", w), [hud_counter(2, var("kills"), "OF %d" % (w + 2))]) for w in (1, 2, 3)]


def lights():
    """Every mantis shot chasing in its ring's colour, the rest handed back; the HUD's line says where they are."""
    out = []
    for r, i, s, _w in every_shot():
        out.append(if_(OR(at("a", r, i), at("b", r, i)),
                       [light(s, RING_COLOR[r - 1], "chase", RING_PACE[r - 1])], [off(s)]))
    words = []
    for r, i, _s, w in every_shot():
        words.append(if_(at("a", r, i), [hud_line("MANTIS AT %s" % w)]))
    out.append(if_(gt("a ring", 0), words, [hud_line("THE NEXT MANTIS IS COMING")]))
    return out


def spawn(m):
    """A mantis lands at the next powerline in turn (no random numbers in blocks: left, center, right, ...)."""
    return [set_(m + " ring", 1), change("turn", 1), if_(gt("turn", 3), [set_("turn", 1)]), set_(m + " at", var("turn")),
            clip("swoop", "behind"), sound("swoop"), show("Swoop")]


def advance(m):
    """One step closer: far to near (the shot in the same place along), near to close, close strikes Godzilla."""
    return [if_(gt(m + " ring", 0), [
        change(m + " ring", 1),
        if_(eq(m + " ring", 2), [if_(eq(m + " at", 3), [set_(m + " at", 4)])]),       # the right powerline: the Building
        if_(eq(m + " ring", 3), [if_(gt(m + " at", 3), [set_(m + " at", 3)])]),
        if_(gt(m + " ring", 3), [set_(m + " ring", 0), timer_start("strike", 1)])])]


def kill(m, r):
    return [set_(m + " ring", 0), change("kills", 1), change("all kills", 1),
            set_("kill value", mul(add(1000000, mul(250000, sub(var("wave"), 1))), {1: 1, 2: 2, 3: 4}[r])),
            timer_start("kill", 1)]


SHOWS = [
    a_show("They come",
           step("sparkle", 1000, GREEN, DARK, "top", gi="dark"),
           step("sweep_down", 800, GREEN, DARK, "top", gi="dark"),
           step("strobe", 400, WHITE, GREEN, "center", rate=55, gi="flash"),
           step("fade", 400, GREEN, "#000000", "center", blend=200)),
    a_show("Swoop",
           step("ripple", 900, GREEN, DARK, "top", rate=300, gi="keep"),
           step("fade", 300, GREEN, "#000000", "center")),
    a_show("Kill",
           step("burst", 500, WHITE, GREEN, "center", gi="flash"),
           step("fade", 300, GREEN, "#000000", "center")),
    a_show("Strike",
           step("strobe", 500, RED, "#000000", "center", rate=60, gi="flash"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Wave cleared",
           step("implode", 800, YELLOW, DARK, "center", gi="flash"),
           step("rainbow", 900, "#000000", "#000000", "center", rate=60),
           step("fade", 400, GREEN, "#000000", "center")),
    a_show("The biggest",
           step("bolts", 900, GREEN, DARK, "center", rate=130, gi="dark"),
           step("burst", 800, WHITE, GREEN, "xy", gi="dark", x=123, y=202),
           step("spin", 900, GREEN, DARK, "xy", rate=90, gi="keep", x=123, y=202)),
    a_show("Won",
           step("burst", 800, WHITE, YELLOW, "xy", gi="flash", x=123, y=202),
           step("fire", 1200, YELLOW, GREEN, "center", gi="keep"),
           step("rainbow", 1500, "#000000", "#000000", "center", rate=50),
           step("fade", 700, GREEN, "#000000", "center", blend=300)),
    a_show("Lost",
           step("sparkle", 900, RED, DARK, "center", gi="dark"),
           step("fade", 900, DARK, "#000000", "center")),
]

SCRIPTS = [
    # ---- to start it: the spins, then its scoop ------------------------------------------------------------------
    on_shot(SPIN, *pack.count_up("spins", 1, NEED, "ready", "note at", START_SHOT, GREEN, START_INSERTS,
                                 "KAMACURAS IS LIT", "SHOOT THE RIGHT SCOOP", "THE MANTISES",
                                 "SPINS TO LIGHT IT", step=10), when="idle"),
    pack.relight("ready", START_SHOT, GREEN, START_INSERTS),

    on_start(*pack.begin(SLUG),
             set_("ready", 0), set_("spins", 0), set_("note at", 0), change("fought", 1),
             set_("wave", 1), set_("kills", 0), set_("all kills", 0), set_("strikes", 0), set_("boss", 0),
             set_("won", 0), set_("wave total", 0), set_("kill total", 0), set_("turn", 0),
             set_("a ring", 0), set_("b ring", 0), set_("adv ms", 7000),
             shield("toward"),
             clip("intro", "full"), clip("loop", "loop"), sound("wave"), show("They come"), shake(600, "strong"),
             hud_counter(1, 1, "OF 3"), hud_counter(2, 0, "OF 3"), hud_counter(3, 3, "STRIKES LEFT"),
             timer_start("spawn", 1500), timer_start("advance", 8500)),

    # ---- the swarm --------------------------------------------------------------------------------------------------
    on_timer("spawn", if_(eq("boss", 0), [
        if_(eq("a ring", 0), [*spawn("a")], [if_(AND(eq("b ring", 0), ge("wave", 2)), [*spawn("b")])]),
        timer_start("lights", 1)])),
    on_timer("advance", if_(eq("boss", 0), [
        *advance("a"), *advance("b"), timer_start("lights", 1),
        if_(OR(eq("a ring", 0), AND(eq("b ring", 0), ge("wave", 2))), [timer_start("spawn", 1200)]),
        timer_start("advance", var("adv ms"))])),
    on_timer("lights", if_(eq("boss", 0), lights())),
    *[on_shot(s, if_(eq("boss", 0), [
        if_(at("a", r, i), kill("a", r), [if_(at("b", r, i), kill("b", r))])]))
      for r, i, s, _w in every_shot() if s != "Building"],
    on_shot("Building",
            if_(eq("boss", 0), [if_(at("a", 2, 4), kill("a", 2), [if_(at("b", 2, 4), kill("b", 2))])]),
            if_(eq("boss", 1), [timer_start("boss", 1)])),
    on_timer("kill",
             score(var("kill value")), change("wave total", var("kill value")),
             change("kill total", var("kill value")), *kills_counter(),
             award("MANTIS DOWN", value=var("kill value")), clip("kill", "behind"), sound("kill"), show("Kill"),
             shake(250, "medium"), timer_start("lights", 1), timer_start("spawn", 1200),
             if_(ge("kills", add(2, var("wave"))), [timer_start("wave", 700)])),
    on_timer("strike",
             change("strikes", 1), hud_counter(3, sub(3, var("strikes")), "STRIKES LEFT"),
             clip("escape", "behind"), sound("escape"), show("Strike"), shake(400, "hard"),
             award("MANTIS STRIKE", value=sub(3, var("strikes")), sub="STRIKES LEFT"),
             if_(ge("strikes", 3), [clip("lost", "full"), sound("lost"), show("Lost"), end()],
                 [timer_start("spawn", 1200)])),

    # ---- a wave cleared --------------------------------------------------------------------------------------------
    on_timer("wave",
             score(var("wave total")), award("WAVE CLEARED", value=var("wave total"), sub="ITS KILLS AGAIN", seconds=3),
             clip("wave", "behind"), sound("wave"), show("Wave cleared"), shake_game("jackpot"),
             set_("wave total", 0), set_("kills", 0), set_("a ring", 0), set_("b ring", 0), change("wave", 1),
             change("adv ms", -1000), hud_counter(1, var("wave"), "OF 3"), *kills_counter(), timer_start("lights", 1),
             if_(gt("wave", 3), [
                 set_("boss", 1), timer_stop("advance"), timer_stop("spawn"), timer_start("boss clock", 25000),
                 set_("boss hits", 0),
                 hud_line("THE BIGGEST MANTIS: SHOOT THE BUILDING"), hud_counter(2, 0, "OF 3", "HITS"),
                 hud_counter(1, 25, "TO HIT IT", "SECONDS"),
                 light("Building", RED, "chase", 60), light_insert("BUILDING SPOT", RED, "blink", 120),
                 clip("boss", "full"), sound("boss"), show("The biggest")],
                 [timer_start("spawn", 2500)])),

    # ---- the biggest mantis -------------------------------------------------------------------------------------------
    on_timer("boss",
             change("boss hits", 1), score(5000000), hud_counter(2, var("boss hits"), "OF 3"),
             shake(450, "hard"), sound("kill"),
             if_(ge("boss hits", 3), [
                 set_("won", 1), score(var("kill total")),
                 award("SWARM DEFEATED", value=var("kill total"), sub="SUPER JACKPOT", seconds=4),
                 clip("won", "full"), sound("won"), show("Won"), shake_game("multiball_start"), end()],
                 [award("THE BIG ONE REELS", value=var("boss hits"), sub="OF 3"), clip("kill", "behind")])),

    every(1, if_(eq("boss", 1), [hud_counter(1, div(add(timer_left("boss clock"), 999), 1000), "TO HIT IT")])),
    on_timer("boss clock", if_(AND(eq("boss", 1), eq("won", 0)), [
        award("THE BIG ONE ESCAPES", sub="THE SWARM WINS"), clip("lost", "full"), sound("lost"), show("Lost"),
        set_("strikes", 3), end()])),
    on_end(*pack.finish(), set_("boss", 0), set_("a ring", 0), set_("b ring", 0),
           if_(eq("won", 1), [hud_title("KAMACURAS DEFEATED"), hud_line("THE SWARM IS GONE")],
               [hud_title("THE MANTISES WIN"), hud_line("THE SWARM TOOK GODZILLA")]),
           *[timer_stop(t) for t in TIMERS],
           if_(AND(eq("won", 0), lt("strikes", 3)), [clip("lost", "full"), sound("lost"), show("Lost")])),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("spins", "ready", "note at", "fought")] + [
        {"name": n, "reset": "mode"} for n in ("wave", "kills", "all kills", "strikes", "boss", "boss hits", "won",
                                                "wave total", "kill total", "kill value", "turn", "adv ms",
                                                "a ring", "a at", "b ring", "b at")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("THE NEXT MANTIS IS COMING",
               counters=[("WAVE", "OF 3", None), ("KILLS", "OF WAVE", None), ("GODZILLA", "STRIKES LEFT", None)],
               timer=None),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "kill", "escape", "wave", "boss", "won", "lost", "swoop", "lit"),
    "sounds": sounds({"kill": 3, "escape": 3, "wave": 4, "boss": 4, "won": 4, "lost": 4, "swoop": 3}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 4, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "destoroyah.c",
    "about": ("Reworked (PAD-658): DESTOROYAH's waves as Kamacuras, now harder to start (50 Top spinner spins, then "
              "its own right scoop) and with its mantis shots far more obvious (chasing in the ring's colour, the "
              "HUD naming each one, a swoop clip and light show as each lands). Son of Godzilla (1967) and "
              "Godzilla: Final Wars (2004)."),
    "lost": [],
}


def _spins(n):
    out = []
    for _i in range(n):
        out += ["shot", SPIN, "ms", 60]
    return out


_START = ["trigger", "kamacuras.start", "secs", 2]
DESK = [
    ("fifty spins then the scoop", _spins(30) + ["shot", "Right scoop", "secs", 1] + _spins(20) +
     ["shot", "Right scoop", "secs", 3],
     ["Hud_Award: KAMACURAS IS LIT", "[KAMACURAS] START (its lit shot)", "LAMP SELECT CITY 20ff40 chase"]),
    ("a mantis is obvious, a near kill pays 2x", _START + ["secs", 9, "shot", "Left ramp", "secs", 1],
     ["Hud_Line: MANTIS AT THE LEFT POWERLINE", "LAMP POWERLINE LEFT 20ff40 chase 160",
      "Hud_Line: MANTIS AT THE LEFT RAMP", "LAMP LEFT RAMP d0ff00 chase 110", "SCORE +2000000"]),
    ("a close kill pays 4x", _START + ["secs", 16, "shot", "Maser target", "secs", 1],
     ["Hud_Line: MANTIS AT THE MASER", "LAMP MASER ff1010 chase 60", "SCORE +4000000"]),
    ("three waves and the biggest mantis", _START + ["shot", "Powerline left", "ms", 300, "shot", "Powerline center",
                                                     "ms", 300, "shot", "Powerline right", "ms", 300] * 30 +
     ["secs", 2, "shot", "Building", "ms", 500, "shot", "Building", "ms", 500, "shot", "Building", "secs", 6],
     ["Hud_Title: KAMACURAS DEFEATED", "Hud_Award: WAVE CLEARED", "Hud_Line: THE BIGGEST MANTIS: SHOOT THE BUILDING", "LAMP BUILDING ff1010 chase 60",
      "END (a block)", "lamps held 0"]),
    ("three strikes and the swarm wins", _START + ["secs", 80],
     ["Hud_Title: THE MANTISES WIN", "Hud_Award: MANTIS STRIKE", "END (a block)", "lamps held 0"]),
]


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)
