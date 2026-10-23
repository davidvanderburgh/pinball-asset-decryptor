"""KAMACURAS (PAD-658): waves of giant mantises swoop down the playfield; the closer the kill, the more it pays.

Son of Godzilla (1967) and Godzilla: Final Wars (2004). The rules are DESTOROYAH's (PAD-379, after Lyman Sheats'
Horde in The Walking Dead: walkers advance, a closer kill pays more, each wave needs one more kill, a cleared wave
pays its kills again, a boss at the end), re-themed for Kamacuras, whose art is under the right scoop's lights.

David, PAD-658: "modify the Kamacuras mode to require more to start it and make its shots more obvious."

- TO START IT (was: 30 Top spinner spins, 10 more each time, and it started at once): 50 spins of the Top spinner
  (100 the second time, 150 the third) light the RIGHT SCOOP, its own corner; the scoop starts it. Nothing counts in
  a multiball. A note every 10 spins says how many are left (SPIN THE TOP SPINNER / 40 - SPINS TO KAMACURAS).
- THE MANTISES are far more obvious: a mantis's shot CHASES fast in its ring's colour (far green, near yellow, close
  red, the closer the faster), the HUD names where they are, and each one swoops in with its own clip, screech and
  a ripple light show. Everything else on the playfield of ours stays dark; a killed mantis's shot goes off at once.
- THE SWARM: mantises land at the powerlines (FAR, x1), stay 10 s at each shot, advance to the ramps, the Big loop
  or the Building (NEAR, x2), then the Maser, the Godzilla target or the right shield (CLOSE, x4), then strike
  Godzilla. One at a time in wave 1, up to two at once from wave 2. A kill pays 1M (+250K a wave) times its
  closeness.
- WAVES: 3, 4, then 5 kills; a cleared wave pays its kills again. Three strikes on Godzilla and the swarm wins.
- No clock while the waves come (DESTOROYAH's has none either: three strikes end it); THE BIGGEST MANTIS: after
  wave 3, the Building for 40 s: three hits of 5M; the third is the SUPER JACKPOT, every kill of the mode again.

SAY THE SHOT (PAD-658 round 3, David: "the shots are not explicit enough and some of the information only flashes on
the screen very briefly"; "you can't really accomplish much in 10 seconds. 40 seconds is better"):
- the swarm: the TITLE names the first mantis's shot (SHOOT THE LEFT RAMP) and the LINE the second's (OR THE MASER
  TARGET); with one on the playfield the line says THE CLOSER IT IS, THE MORE IT PAYS; the counters say WAVE 2 OF
  3, KILLS 1 OF 4 and the strikes Godzilla can still take;
- each mantis stays 10 s at a shot, counted from when it got there (was: every mantis moved together every 7, 6,
  then 5 s, so one that had just landed could move on at once);
- the biggest mantis: SHOOT THE BUILDING 3 TIMES, SHOOT THE BUILDING AGAIN, SUPER JACKPOT: SHOOT THE BUILDING, HITS
  2 OF 3, announced once WAVE CLEARED has had its 3 s; its clock is pack.STAGE_S (was 25 s) and a hit keeps
  pack.CLOCK_FLOOR seconds on it;
- every note stays 3 s at least (pack.NOTE_S).

Mantis "a" is always the first on the playfield: when it goes and "b" is still there, "b" moves into "a", so the
title names the one nearest Godzilla (they advance at the same pace).
"""
from blk import (AND, OR, a_show, add, award, change, clip, clips, div, end, eq, every, ge, gt, timer_left,
                 hud, hud_counter, hud_line, hud_title, if_, light, light_insert, lt, mul, off, off_insert, on_end,
                 on_shot, on_start, on_timer, score, set_, shake, shake_game, shield, show, sound,
                 sounds, step, sub, timer_start, timer_stop, var)
import pack

SLUG, NAME = "kamacuras", "KAMACURAS"
GREEN, YELLOW, RED, WHITE, DARK = "#20ff40", "#d0ff00", "#ff1010", "#ffffff", "#002008"
SPIN, START_SHOT = "Top spinner", pack.CASH_SHOT
START_INSERTS = ",".join(pack.CASH_INSERTS)
NEED = pack.need(80, "fought")  # 80 spins, then 160, then 240 (PAD-675: was 50)
#: the rings, far to close: the shots a mantis lands on (the HUD says them in pack.SHOT_WORDS)
RINGS = (
    ("Powerline left", "Powerline center", "Powerline right"),
    ("Left ramp", "Right ramp", "Big loop", "Building"),
    ("Maser target", "Godzilla target", "Shield target right"),
)
RING_COLOR = (GREEN, YELLOW, RED)
RING_PACE = (160, 110, 60)
WAVES, BOSS_HITS = 3, 3
NOTE_MS = pack.NOTE_S * 1000                     # a note's time on the glass: the biggest mantis waits it out
#: PAD-658 round 3: a moving target stays 10 s at least before it moves on its own: a mantis's seconds at its shot
#: ("a stay", "b stay", counted every second) must pass MOVE_S, so it stays 10 to 11 s
MOVE_S = 10
STAGE_MS = pack.STAGE_S * 1000
FLOOR_MS = pack.CLOCK_FLOOR * 1000
CLOSER = "THE CLOSER IT IS, THE MORE IT PAYS"
W = pack.SHOT_WORDS
TIMERS = ("spawn", "lights", "kill", "wave", "boss", "strike", "boss clock", "next")


def every_shot():
    return [(r, i, s) for r, ring in enumerate(RINGS, 1) for i, s in enumerate(ring, 1)]


def at(m, r, i):
    return AND(eq(m + " ring", r), eq(m + " at", i))


def kills_counter():
    """KILLS: this wave's kills, out of the kills it needs (3, 4, 5)."""
    return [if_(eq("wave", w), [hud_counter(2, var("kills"), "OF %d" % (w + 2))]) for w in range(1, WAVES + 1)]


def promote():
    """Mantis "a" is the first on the playfield: when it is gone and "b" is not, "b" moves into "a"."""
    return if_(AND(eq("a ring", 0), gt("b ring", 0)), [
        set_("a ring", var("b ring")), set_("a at", var("b at")), set_("a stay", var("b stay")), set_("b ring", 0)])


def lights():
    """Every mantis shot chasing in its ring's colour, the rest handed back; the title names the first mantis's
    shot, the line the second's."""
    out = [promote()]
    for r, i, s in every_shot():
        out.append(if_(OR(at("a", r, i), at("b", r, i)),
                       [light(s, RING_COLOR[r - 1], "chase", RING_PACE[r - 1])], [off(s)]))
    first = [if_(at("a", r, i), [hud_title("SHOOT THE %s" % W[s])]) for r, i, s in every_shot()]
    second = [if_(at("b", r, i), [hud_line("OR THE %s" % W[s])]) for r, i, s in every_shot()]
    out.append(if_(gt("a ring", 0), [*first, if_(gt("b ring", 0), second, [hud_line(CLOSER)])], [
        if_(gt("wave", WAVES), [hud_title("THE SWARM IS BEATEN"), hud_line("THE BIGGEST MANTIS IS COMING")],
            [hud_title(NAME), hud_line("THE NEXT MANTIS IS COMING")])]))
    return out


def spawn(m):
    """A mantis lands at the next powerline in turn (no random numbers in blocks: left, center, right, ...)."""
    return [set_(m + " ring", 1), change("turn", 1), if_(gt("turn", 3), [set_("turn", 1)]), set_(m + " at", var("turn")),
            set_(m + " stay", 0), clip("swoop", "behind"), sound("swoop"), show("Swoop")]


def advance(m):
    """One step closer: far to near (the shot in the same place along), near to close, close strikes Godzilla."""
    return [if_(gt(m + " ring", 0), [
        change(m + " ring", 1),
        if_(eq(m + " ring", 2), [if_(eq(m + " at", 3), [set_(m + " at", 4)])]),       # the right powerline: the Building
        if_(eq(m + " ring", 3), [if_(gt(m + " at", 3), [set_(m + " at", 3)])]),
        if_(gt(m + " ring", 3), [set_(m + " ring", 0), timer_start("strike", 1)])])]


def step_on(m):
    """A mantis that has stood MOVE_S seconds at its shot moves on."""
    return if_(gt(m + " stay", MOVE_S), [*advance(m), set_(m + " stay", 0), timer_start("lights", 1)])


def kill(m, r):
    return [set_(m + " ring", 0), change("kills", 1), change("all kills", 1),
            set_("kill value", mul(add(1000000, mul(250000, sub(var("wave"), 1))), {1: 1, 2: 2, 3: 4}[r])),
            timer_start("kill", 1)]


def floor_clock():
    """pack.clock_floor() for the biggest mantis's clock (a timer: the mode has no clock of its own)."""
    return if_(lt(timer_left("boss clock"), FLOOR_MS), [timer_start("boss clock", FLOOR_MS)])


def done_lights():
    """The biggest mantis beaten or gone: the Building no longer counts."""
    return [off("Building"), off_insert("BUILDING SPOT")]


def biggest():
    """The biggest mantis at the Building, once the third WAVE CLEARED has had its time."""
    return [set_("boss", 1), timer_start("boss clock", STAGE_MS), set_("boss hits", 0),
            hud_title("THE BIGGEST MANTIS"), hud_line("SHOOT THE BUILDING %d TIMES" % BOSS_HITS),
            hud_counter(2, 0, "OF %d" % BOSS_HITS, "HITS"), hud_counter(1, pack.STAGE_S, "TO HIT IT", "SECONDS"),
            award("THE BIGGEST MANTIS", sub="SHOOT THE BUILDING %d TIMES" % BOSS_HITS, seconds=pack.NOTE_S),
            light("Building", RED, "chase", 60), light_insert("BUILDING SPOT", RED, "blink", 120),
            clip("boss", "full"), sound("boss"), show("The biggest")]


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
                                 "KAMACURAS IS LIT", "SHOOT THE RIGHT SCOOP", "SPIN THE TOP SPINNER",
                                 "SPINS TO KAMACURAS", step=10), when="idle"),
    pack.relight("ready", START_SHOT, GREEN, START_INSERTS),

    on_start(*pack.begin(SLUG),
             set_("ready", 0), set_("spins", 0), set_("note at", 0), change("fought", 1),
             set_("wave", 1), set_("kills", 0), set_("all kills", 0), set_("strikes", 0), set_("boss", 0),
             set_("won", 0), set_("wave total", 0), set_("kill total", 0), set_("turn", 0),
             set_("a ring", 0), set_("b ring", 0),
             shield("toward"),
             clip("intro", "full"), clip("loop", "loop"), sound("wave"), show("They come"), shake(600, "strong"),
             hud_counter(1, 1, "OF 3"), hud_counter(2, 0, "OF 3"), hud_counter(3, 3, "STRIKES LEFT"),
             timer_start("spawn", 1500), timer_start("lights", 1)),

    # ---- the swarm --------------------------------------------------------------------------------------------------
    on_timer("spawn", if_(eq("boss", 0), [
        promote(),
        if_(eq("a ring", 0), [*spawn("a")], [if_(AND(eq("b ring", 0), ge("wave", 2)), [*spawn("b")])]),
        if_(AND(eq("b ring", 0), ge("wave", 2)), [timer_start("spawn", 1200)]),     # from wave 2: a second one
        timer_start("lights", 1)])),
    # each mantis moves on once it has stood its 10 s at its shot; the biggest mantis's seconds count down
    every(1, if_(eq("boss", 0), [change("a stay", 1), change("b stay", 1), step_on("a"), step_on("b")],
                 [if_(eq("won", 0), [hud_counter(1, div(add(timer_left("boss clock"), 999), 1000))])])),
    on_timer("lights", if_(eq("boss", 0), lights())),
    *[on_shot(s, if_(eq("boss", 0), [
        if_(at("a", r, i), kill("a", r), [if_(at("b", r, i), kill("b", r))])]))
      for r, i, s in every_shot() if s != "Building"],
    on_shot("Building",
            if_(eq("boss", 0), [if_(at("a", 2, 4), kill("a", 2), [if_(at("b", 2, 4), kill("b", 2))])]),
            if_(AND(eq("boss", 1), eq("won", 0)), [timer_start("boss", 1)])),
    on_timer("kill",
             score(var("kill value")), change("wave total", var("kill value")),
             change("kill total", var("kill value")), *kills_counter(),
             award("MANTIS DOWN", value=var("kill value"), seconds=pack.NOTE_S), clip("kill", "behind"),
             sound("kill"), show("Kill"), shake(250, "medium"), timer_start("lights", 1), timer_start("spawn", 1200),
             if_(ge("kills", add(2, var("wave"))), [timer_start("wave", 700)])),
    on_timer("strike",
             change("strikes", 1), hud_counter(3, sub(3, var("strikes")), "STRIKES LEFT"),
             clip("escape", "behind"), sound("escape"), show("Strike"), shake(400, "hard"),
             award("MANTIS STRIKE", value=sub(3, var("strikes")), sub="STRIKES LEFT", seconds=pack.NOTE_S),
             if_(ge("strikes", 3), [clip("lost", "full"), sound("lost"), show("Lost"), end()],
                 [timer_start("spawn", 1200)])),

    # ---- a wave cleared; after the third, the biggest mantis once the note has had its time -------------------------
    on_timer("wave", if_(gt("wave", WAVES), biggest(), [
        score(var("wave total")),
        award("WAVE CLEARED", value=var("wave total"), sub="ITS KILLS AGAIN", seconds=pack.NOTE_S),
        clip("wave", "behind"), sound("wave"), show("Wave cleared"), shake_game("jackpot"),
        set_("wave total", 0), set_("kills", 0), set_("a ring", 0), set_("b ring", 0), change("wave", 1),
        timer_start("lights", 1),
        if_(gt("wave", WAVES), [timer_stop("spawn"), timer_start("wave", NOTE_MS)],
            [hud_counter(1, var("wave"), "OF 3"), *kills_counter(), timer_start("spawn", 2500)])])),

    # ---- the biggest mantis -------------------------------------------------------------------------------------------
    on_timer("boss",
             change("boss hits", 1), score(5000000), floor_clock(), hud_counter(2, var("boss hits")),
             shake(450, "hard"), sound("kill"),
             if_(ge("boss hits", BOSS_HITS), [
                 set_("won", 1), score(var("kill total")), timer_stop("boss clock"), *done_lights(),
                 award("SWARM DEFEATED", value=var("kill total"), sub="SUPER JACKPOT", seconds=4),
                 clip("won", "full"), sound("won"), show("Won"), shake_game("multiball_start"),
                 timer_start("next", NOTE_MS)],
                 [if_(eq("boss hits", BOSS_HITS - 1), [hud_line("SUPER JACKPOT: SHOOT THE BUILDING")],
                      [hud_line("SHOOT THE BUILDING AGAIN")]),
                  award("THE BIG ONE REELS", value=sub(BOSS_HITS, var("boss hits")), sub="MORE AT THE BUILDING",
                        seconds=pack.NOTE_S),
                  clip("kill", "behind")])),

    # the clock out: "won" 2 (no more hits), the note its time, then the end
    on_timer("boss clock", if_(AND(eq("boss", 1), eq("won", 0)), [
        set_("won", 2), *done_lights(), award("THE BIG ONE ESCAPES", sub="THE SWARM WINS", seconds=pack.NOTE_S),
        clip("lost", "full"), sound("lost"), show("Lost"), set_("strikes", 3), timer_start("next", NOTE_MS)])),
    on_timer("next", end()),
    on_end(*pack.finish(), set_("boss", 0), set_("a ring", 0), set_("b ring", 0),
           if_(eq("won", 1), [hud_title("KAMACURAS DEFEATED"), hud_line("THE SWARM IS GONE")],
               [hud_title("THE MANTISES WIN"),
                if_(eq("won", 2), [hud_line("THE BIGGEST MANTIS GOT AWAY")], [hud_line("THE SWARM TOOK GODZILLA")])]),
           *[timer_stop(t) for t in TIMERS],
           if_(AND(eq("won", 0), lt("strikes", 3)), [clip("lost", "full"), sound("lost"), show("Lost")])),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("spins", "ready", "note at", "fought")] + [
        {"name": n, "reset": "mode"} for n in ("wave", "kills", "all kills", "strikes", "boss", "boss hits", "won",
                                                "wave total", "kill total", "kill value", "turn",
                                                "a ring", "a at", "a stay", "b ring", "b at", "b stay")],
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
    "about": ("Reworked (PAD-658): DESTOROYAH's waves as Kamacuras, now harder to start (80 Top spinner spins, then "
              "its own right scoop) and with its mantis shots far more obvious (chasing in the ring's colour, the "
              "HUD's title and line naming where they are, 10 s at each shot, a swoop clip and light show as each "
              "lands), then the biggest mantis at the Building for 40 s. Son of Godzilla (1967) and Godzilla: Final "
              "Wars (2004)."),
    "lost": [],
}


def _spins(n):
    out = []
    for _i in range(n):
        out += ["shot", SPIN, "ms", 60]
    return out


_START = ["trigger", "kamacuras.start", "secs", 2]
_SWEEP = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300, "shot", "Powerline right",
          "ms", 300]
_WAVES = _START + _SWEEP * 40 + ["secs", 4]
DESK = [
    # PAD-675: on a full card the 50th spin starts DESTOROYAH (the same spinner; that spin may not count here) and
    # nothing counts while he runs: stop him, then 32 more (80 and one to spare)
    ("eighty spins then the scoop", _spins(50) + ["secs", 2, "trigger", "destoroyah.stop", "secs", 4] +
     ["shot", "Right scoop", "secs", 1] + _spins(32) + ["shot", "Right scoop", "secs", 3],
     ["Hud_Award: SPIN THE TOP SPINNER", "Hud_AwardSub: 79  -  SPINS TO KAMACURAS", "Hud_AwardSub: 29  -  SPINS TO KAMACURAS",
      "Hud_Award: KAMACURAS IS LIT", "[KAMACURAS] START (its lit shot)", "LAMP SELECT CITY 20ff40 chase"]),
    ("a mantis is obvious, a near kill pays 2x", _START + ["secs", 12, "shot", "Left ramp", "secs", 1],
     ["Hud_Title: SHOOT THE LEFT POWERLINE", "Hud_Line: THE CLOSER IT IS, THE MORE IT PAYS",
      "LAMP POWERLINE LEFT 20ff40 chase 160", "Hud_Title: SHOOT THE LEFT RAMP", "LAMP LEFT RAMP d0ff00 chase 110",
      "SCORE +2000000", "Hud_Title: KAMACURAS", "Hud_Line: THE NEXT MANTIS IS COMING"]),
    ("a close kill pays 4x", _START + ["secs", 22, "shot", "Maser target", "secs", 1],
     ["Hud_Title: SHOOT THE MASER TARGET", "LAMP MASER ff1010 chase 60", "SCORE +4000000"]),
    ("two mantises from wave two: the title and the line", _START + _SWEEP * 5 + ["secs", 6],
     ["Hud_Award: WAVE CLEARED", "Hud_C1_Value: 2", "Hud_C2_Sub: OF 4", "Hud_Title: SHOOT THE LEFT POWERLINE",
      "Hud_Line: OR THE CENTER POWERLINE"]),
    ("three waves and the biggest mantis", _WAVES +
     ["shot", "Building", "ms", 500, "shot", "Building", "ms", 500, "shot", "Building", "secs", 6],
     ["Hud_Award: WAVE CLEARED", "Hud_Title: THE SWARM IS BEATEN", "Hud_Line: THE BIGGEST MANTIS IS COMING",
      "Hud_Title: THE BIGGEST MANTIS", "Hud_Line: SHOOT THE BUILDING 3 TIMES", "Hud_C1_Label: SECONDS",
      "Hud_C2_Label: HITS", "LAMP BUILDING ff1010 chase 60", "Hud_Line: SHOOT THE BUILDING AGAIN",
      "Hud_Line: SUPER JACKPOT: SHOOT THE BUILDING", "Hud_Award: SWARM DEFEATED", "Hud_Title: KAMACURAS DEFEATED",
      "END (a block)", "lamps held 0"]),
    ("the biggest mantis escapes", _WAVES + ["secs", 42],
     ["Hud_Title: THE BIGGEST MANTIS", "Hud_Award: THE BIG ONE ESCAPES", "LAMP OFF BUILDING KAMACURAS",
      "Hud_Title: THE MANTISES WIN", "Hud_Line: THE BIGGEST MANTIS GOT AWAY", "END (a block)", "lamps held 0"]),
    ("three strikes and the swarm wins", _START + ["secs", 110],
     ["Hud_Award: MANTIS STRIKE", "Hud_AwardSub: 2  -  STRIKES LEFT", "Hud_Title: THE MANTISES WIN", "END (a block)",
      "lamps held 0"]),
]


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)
