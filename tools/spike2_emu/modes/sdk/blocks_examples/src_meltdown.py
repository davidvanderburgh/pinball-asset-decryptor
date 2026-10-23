"""MELTDOWN (PAD-658): the SDK's C example meltdown.c rebuilt in blocks and taken deeper - a push-your-luck multiball
of our own in three stages, each meltdown survived taking it a stage further.

Burning Godzilla (Godzilla vs. Destoroyah, 1995): his heart is a nuclear reactor running away; Destoroyah comes for
him, Godzilla Junior comes to him, and at the end his meltdown brings Junior back.

After Lyman Sheats: a start that costs more each time (Metallica's Sparky), stages with their own shots, supers worth
your history (Batman '66), a meter you ride or cool (the C's core), and failing still pays (the core blowing pays a
quarter of what it held).

- LIGHT IT: captive ball hits (the Godzilla target, MAGNA GRAB): 15 the first time, 30 the second, 45 the third;
  then it pulses red and the next hit starts it (not beside the game's own battle or multiball: it waits, ready).
  The note (GODZILLA TARGET, 9 MORE FOR MELTDOWN) comes every hit the first time, then at every 5 left and the last 5.
- START: a 3-ball multiball with a 15 s ball save; the shields turn toward the player.
- THE CORE starts at 25% (30%, 35% the more he has melted) and rises 1% a second (2% from 70%); a jackpot heats it
  4% in stage 1, 6% in stage 2, 8% in stage 3 (the HEART 4% more). STABLE under 40% x1, HOT x2, CRITICAL (70%) x3,
  MELTDOWN IMMINENT (90%) x5. CADMIUM: from 40%, each Shield target cools it 12% (they light at 40% and count only
  while lit; the HOT and CRITICAL notes say so).
- STAGE 1, BURNING GODZILLA: the Left ramp, Right ramp, Building and Big loop: 2,000,000 x the heat; one of them is
  the HEART (double, chasing white): it moves every 10 s (a moving target stays 10 s at least) and when hit (in turn
  here). The line: RAMPS, BIG LOOP, BUILDING: 2X LEFT RAMP, moving with the heart.
- STAGE 2, DESTOROYAH: the red spiral ray: one ramp at a time, 2x the base x the heat; the other ramp is next. The
  line: JACKPOT: LEFT RAMP (then RIGHT RAMP).
- STAGE 3, JUNIOR: the Big loop and the Mecha lane (Mecha exit bottom), 3x the base x the heat. The line: JACKPOT:
  BIG LOOP OR MECHA LANE.
- MELTDOWN at 100%: the Building is the SUPER JACKPOT for 20 s (WINDOW_S: no shorter the more he has melted): the
  jackpots paid since the last super, times the stage and one more (x2, x3, x4); the core back to 25%, the base up
  500,000, and the next stage 4 s on (the super's note shows its 4 s first). In stage 3 it is the FINAL MELTDOWN
  (+25M) and Junior rises; stage 3 goes on. Missed, the core blows: a quarter of those jackpots paid, the core back
  to 50%, the base back to 2,000,000.
- ADD-A-BALL: after 4 jackpots the captive ball adds a ball, once (a note says it is lit).
- NOTES: every one 3 s at least (NOTE_S); a jackpot's names what is next (2X AT THE RIGHT RAMP, NOW THE LEFT RAMP).
- ENDS: one ball left after the ball save and 3 s more (for 2 s), the last drain, a tilt.
"""
from blk import (AND, BALLS, LIT, NOT, OR, a_show, add, award, beds, change, clip, clips, div, end, eq, every,
                 game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, light_mode, lt, mul,
                 multiball, music, off, off_insert, on_any_shot, on_end, on_shot, on_start, on_timer, score, set_, shake,
                 shake_game, shield, show, sound, sounds, step, sub, timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "meltdown", "MELTDOWN"
RED, ORANGE, EMBER, ICE, WHITE, GREEN = "#ff1400", "#ff5a00", "#460800", "#78d2ff", "#ffffff", "#00ff3c"
PURPLE, GOLD = "#c020ff", "#ffd200"
HEAT = ("#ffd200", "#ff6e00", "#ff1400", "#ffffff")              # STABLE, HOT, CRITICAL, IMMINENT
LEVELS = ("STABLE", "HOT", "CRITICAL", "IMMINENT")
MULT = (1, 2, 3, 5)
LIGHT_SHOT = "Godzilla target"                                    # the MAGNA-GRAB captive ball
JP = ("Left ramp", "Right ramp", "Building", "Big loop")
RAMPS = ("Left ramp", "Right ramp")
JUNIOR = ("Big loop", "Mecha exit bottom")
SHIELDS = ("Shield target left", "Shield target center", "Shield target right")
BX, BY = 123, 202                                                  # the BUILDING insert: the C's KIT_AT_BUILDING
SX, SY = 199, 346                                                  # SHIELD CENTER: the C's KIT_AT_SHIELDS
JX, JY = 282, 393                                                  # MECHA LANE: Junior's way in
TIMERS = ("core", "jackpot", "melt", "lights", "next")
STAGE_NAME = ("BURNING", "DESTOROYAH", "JUNIOR")
STAGE_TITLE = ("BURNING GODZILLA", "DESTOROYAH", "GODZILLA JUNIOR")
#: the HUD's line, by stage: what to shoot now by the playfield's names (stage 1 moves with the heart, 2 with the ray)
HEART_LINE = "RAMPS, BIG LOOP, BUILDING: 2X"                  # + the heart's shot: ... 2X LEFT RAMP
RAY_LINE = "JACKPOT:"                                           # + the ray's ramp: JACKPOT: LEFT RAMP
JUNIOR_LINE = "JACKPOT: " + " OR ".join(pack.SHOT_WORDS[s] for s in JUNIOR)
#: the start: 10 captive ball hits the first time, 20 the second, 30 the third
NEED = pack.need(15, "starts")                    # PAD-675: was 10
MOVE_S = 10                                                     # the heart stays this long at least before it moves

SHOWS = [
    a_show("Reactor",
           step("fade_in", 700, RED, "#000000", "xy", gi="dark", x=BX, y=BY),
           step("ripple", 1200, ORANGE, EMBER, "xy", rate=350, gi="dark", x=BX, y=BY),
           step("strobe", 400, WHITE, RED, "center", rate=55, gi="flash"),
           step("fire", 1100, GOLD, RED, "center", gi="dark")),
    a_show("Meltdown",
           step("strobe", 700, WHITE, RED, "center", rate=45, gi="flash"),
           step("implode", 900, WHITE, RED, "xy", gi="dark", x=BX, y=BY),
           step("fire", 1000, WHITE, RED, "center", gi="dark")),
    a_show("Super",
           step("burst", 700, WHITE, RED, "xy", gi="flash", x=BX, y=BY),
           step("spiral_out", 1100, RED, EMBER, "xy", gi="dark", x=BX, y=BY),
           step("bolts", 700, WHITE, ORANGE, "top", rate=100, gi="flash"),
           step("fade", 500, RED, "#000000", "center", blend=200)),
    a_show("Junior",
           step("burst", 800, WHITE, ICE, "xy", gi="flash", x=BX, y=BY),
           step("sparkle", 1000, ICE, "#001e50", "center"),
           step("rainbow", 1600, "#000000", "#000000", "xy", rate=60, x=JX, y=JY),
           step("fade", 600, ICE, "#000000", "center", blend=300)),
    a_show("Cadmium",
           step("sweep_rl", 500, ICE, "#00143c", "xy", x=SX, y=SY),
           step("fade", 300, ICE, "#000000", "center")),
    a_show("Destoroyah",
           step("sweep_down", 600, PURPLE, "#000000", "top", gi="dark"),
           step("bolts", 900, PURPLE, RED, "center", rate=120, gi="dark"),
           step("bounce", 900, RED, PURPLE, "center", rate=150, gi="dark"),
           step("fade", 400, PURPLE, "#000000", "center", blend=150)),
    a_show("Spiral ray",
           step("spin", 600, RED, "#000000", "top", rate=70, gi="dark"),
           step("sweep_lr", 400, WHITE, RED, "top", gi="dark")),
    a_show("Junior comes",
           step("spiral_in", 1000, ICE, "#000020", "xy", gi="dark", x=JX, y=JY),
           step("pulse", 900, ICE, "#001e50", "xy", rate=300, gi="dark", x=JX, y=JY),
           step("sweep_up", 600, GOLD, "#000000", "center", gi="dark"),
           step("fade", 400, ICE, "#000000", "center", blend=150)),
    a_show("Core blows",
           step("strobe", 300, WHITE, ORANGE, "center", rate=60, gi="flash"),
           step("burst", 800, ORANGE, RED, "center", gi="dark"),
           step("sparkle", 1000, ORANGE, EMBER, "center", gi="dark"),
           step("fade", 600, EMBER, "#000000", "center", blend=200)),
    a_show("Embers",
           step("solid", 500, EMBER, "#000000", "center", gi="dark"),
           step("fade", 1400, EMBER, "#000000", "center", blend=400)),
]


def lights():
    """The C's show_lamps, by stage: the jackpots in the heat's colour, the heart faster; the ray's ramp, Junior's
    shots; the shields ice blue from 40%; the captive ball green while the add-a-ball is lit; in MELTDOWN only the
    Building, white."""
    burn = []
    for lv in range(4):
        rest = 150 if lv == 3 else 500
        burn.append(if_(eq("level", lv), [light(s, HEAT[lv], "blink", rest) for s in JP]))
    heart = [if_(eq("heart", i), [light(s, WHITE, "chase", 90)]) for i, s in enumerate(JP, 1)]
    return [
        if_(eq("phase", 1), [
            if_(eq("stage", 1), burn + heart),
            if_(eq("stage", 2), [off("Building"), off("Big loop")] + [
                if_(eq("ray at", i), [light(s, RED, "chase", 80)], [off(s)]) for i, s in enumerate(RAMPS, 1)]),
            if_(eq("stage", 3), [off("Building"), *[off(s) for s in RAMPS]] + [light(s, ICE, "chase", 100)
                                                                              for s in JUNIOR]
                + [light_insert("MECHA LANE", ICE, "chase", 100)]),
            if_(ge("core", 40), [light(s, ICE, "pulse", 900) for s in SHIELDS], [off(s) for s in SHIELDS]),
            if_(AND(eq("add used", 0), ge("jackpots", 4)), [light(LIGHT_SHOT, GREEN, "blink", 300)],
                [off(LIGHT_SHOT)]),
            stage_lines(),
        ], [
            *[off(s) for s in ("Left ramp", "Right ramp", "Big loop", "Mecha exit bottom")],
            *[off(s) for s in SHIELDS], off(LIGHT_SHOT), off_insert("MECHA LANE"),
            light("Building", WHITE, "blink", 120),
        ]),
    ]


def stage_lines():
    """The HUD line for the stage it is in, naming its shots (one block: the three are an if-chain): stage 1's
    moves with the heart, stage 2's with the ray."""
    return if_(eq("stage", 1), pack.line_follows("heart", JP, verb=HEART_LINE), [
        if_(eq("stage", 2), pack.line_follows("ray at", RAMPS, verb=RAY_LINE), [hud_line(JUNIOR_LINE)])])


def core_sub():
    """The core moved: clamp it, MELTDOWN at 100%, else its level (a hotter one says so)."""
    return [
        if_(gt("core", 100), [set_("core", 100)]), if_(lt("core", 0), [set_("core", 0)]),
        if_(AND(eq("phase", 1), ge("core", 100)), [
            set_("phase", 2), set_("level", 3), set_("was level", 3), set_("mult", 5),
            timer_start("melt", pack.WINDOW_S * 1000),
            award("MELTDOWN!", sub="SHOOT THE BUILDING", seconds=3), show("Meltdown"), timer_start("next", 400),
            sound("meltdown"), clip("meltdown", "behind"), music("melt"),
            hud_title("MELTDOWN!"), hud_line("SHOOT THE BUILDING: SUPER JACKPOT"), hud_counter(1, 100, "MELTDOWN"),
            hud_counter(2, mul(var("paid"), add(var("stage"), 1)), "SUPER JACKPOT"),
        ], [
            set_("level", 0), if_(ge("core", 40), [set_("level", 1)]), if_(ge("core", 70), [set_("level", 2)]),
            if_(ge("core", 90), [set_("level", 3)]),
            *[if_(eq("level", lv), [set_("mult", MULT[lv]), hud_counter(1, var("core"), LEVELS[lv]),
                                    hud_counter(2, mul(mul(var("base"), MULT[lv]), var("stage")),
                                                "X%d HEAT" % MULT[lv])])
              for lv in range(4)],
            # a hotter level says what it pays and what the shields (lit from 40%) do
            if_(gt("level", "was level"), [
                if_(eq("level", 1), [award("HOT", sub="JACKPOTS X2 - SHIELDS COOL THE CORE", seconds=pack.NOTE_S),
                                     sound("heat"), shake(300, "soft")]),
                if_(eq("level", 2), [award("CRITICAL", sub="JACKPOTS X3 - SHIELDS COOL THE CORE", seconds=pack.NOTE_S),
                                     sound("critical"), clip("critical", "behind"), shake(500, "medium")]),
                if_(eq("level", 3), [award("MELTDOWN IMMINENT", sub="SHOOT THE SHIELDS TO COOL HIM",
                                           seconds=pack.NOTE_S), sound("heat"), shake(800, "medium")]),
            ]),
            set_("was level", var("level")),
        ]),
        timer_start("lights", 1),
    ]


def heart_moves():
    return [change("heart", 1), if_(gt("heart", 4), [set_("heart", 1)]), set_("heart secs", 0)]


def stage_bed():
    """The stage's own music: its own bed in stage 1, DESTOROYAH's, then JUNIOR's."""
    return if_(eq("stage", 1), [music("")], [if_(eq("stage", 2), [music("destoroyah")], [music("junior")])])


def stage_title():
    """The HUD title for the stage it is in."""
    return if_(eq("stage", 1), [hud_title(STAGE_TITLE[0])], [
        if_(eq("stage", 2), [hud_title(STAGE_TITLE[1])], [hud_title(STAGE_TITLE[2])])])


def back_to_burn(core):
    return [set_("phase", 1), set_("paid", 0), set_("core", core), set_("heart secs", 0), timer_stop("melt"),
            stage_title(), timer_start("core", 1)]


SCRIPTS = [
    # ---- light it: captive ball hits (15, then 30, then 45) ----------------------------------------------------------
    # the note names the shot: every hit the first time (10), then at every 5 left and the last 5 (20, 30)
    on_shot(LIGHT_SHOT, if_(eq("ready", 0), [                  # a multiball's hits too (PAD-690)
        change("hits", 1),
        if_(ge("hits", NEED), [
            set_("ready", 1), light_mode(LIGHT_SHOT, RED, "pulse"), sound("lit"),
            award("MELTDOWN IS READY", sub=pack.shoot(LIGHT_SHOT, verb="HIT THE"), seconds=pack.NOTE_S)], [
            if_(OR(eq("starts", 0), le(sub(NEED, var("hits")), 5),
                   eq(mul(div(sub(NEED, var("hits")), 5), 5), sub(NEED, var("hits")))), [
                award(pack.SHOT_WORDS[LIGHT_SHOT], value=sub(NEED, var("hits")), sub="MORE FOR MELTDOWN",
                      seconds=pack.NOTE_S)])])]), when="idle"),
    on_any_shot(if_(AND(eq("ready", 1), NOT(LIT)), [light_mode(LIGHT_SHOT, RED, "pulse")]), when="idle"),

    # ---- the multiball ---------------------------------------------------------------------------------------------------
    on_start(set_("ready", 0), set_("hits", 0), change("starts", 1), multiball(3, 15), shield("toward"),
             set_("stage", 1), set_("phase", 1), set_("level", 0), set_("was level", 0), set_("mult", 1),
             # each time he melts it starts hotter (the super's window stays WINDOW_S)
             set_("core", add(20, mul(5, var("starts")))), if_(gt("core", 40), [set_("core", 40)]),
             set_("base", 2000000), set_("heart", 1), set_("heart secs", 0), set_("jackpots", 0), set_("paid", 0),
             set_("meltdowns", 0), set_("add used", 0), set_("secs", 0), set_("one ball", 0), set_("ray at", 1),
             game_show("Strobe storm"), clip("intro", "full"), clip("loop", "loop"), show("Reactor"),
             shake_game("multiball_start"),
             hud_title("BURNING GODZILLA"), hud_counter(3, 0, "JACKPOTS", STAGE_NAME[0]),
             award("MELTDOWN MULTIBALL", sub="HIS HEART IS A NUCLEAR REACTOR", seconds=3),
             timer_start("core", 1)),
    on_timer("core", *core_sub()),
    on_timer("lights", *lights()),

    # ---- every second: the core rises, the heart moves, MELTDOWN counts down, one ball left ends it ---------------------
    every(1,
          change("secs", 1),
          if_(eq("phase", 1), [
              if_(ge("core", 70), [change("core", 2)], [change("core", 1)]),
              change("heart secs", 1), if_(AND(eq("stage", 1), ge("heart secs", MOVE_S)), heart_moves()),
              timer_start("core", 1)], [
              hud_line("SUPER JACKPOT AT THE BUILDING:", value=div(timer_left("melt"), 1000)),
              if_(le(timer_left("melt"), 5000), [light("Building", WHITE, "blink", 60)])]),
          if_(gt("secs", 18), [
              if_(lt(BALLS, 2), [change("one ball", 1), if_(ge("one ball", 2), [end()])], [set_("one ball", 0)])])),

    # ---- jackpots: which shot pays depends on the stage -----------------------------------------------------------------
    on_shot("Left ramp", if_(eq("phase", 1), [
        if_(eq("stage", 1), [set_("jp", 1), timer_start("jackpot", 1)]),
        if_(AND(eq("stage", 2), eq("ray at", 1)), [set_("jp", 1), timer_start("jackpot", 1)])])),
    on_shot("Right ramp", if_(eq("phase", 1), [
        if_(eq("stage", 1), [set_("jp", 2), timer_start("jackpot", 1)]),
        if_(AND(eq("stage", 2), eq("ray at", 2)), [set_("jp", 2), timer_start("jackpot", 1)])])),
    on_shot("Big loop", if_(AND(eq("phase", 1), OR(eq("stage", 1), eq("stage", 3))), [
        set_("jp", 4), timer_start("jackpot", 1)])),
    on_shot("Mecha exit bottom", if_(AND(eq("phase", 1), eq("stage", 3)), [set_("jp", 5), timer_start("jackpot", 1)])),
    on_shot("Building",
            if_(AND(eq("phase", 1), eq("stage", 1)), [set_("jp", 3), timer_start("jackpot", 1)]),
            if_(eq("phase", 2), [
                # MELTDOWN: the super jackpot, the jackpots paid since the last one x (the stage + 1); none paid: x25
                set_("got", mul(var("paid"), add(var("stage"), 1))), if_(eq("paid", 0), [set_("got", mul(var("base"), 25))]),
                if_(eq("stage", 3), [set_("got", add(var("got"), 25000000))]),
                score(var("got")), change("meltdowns", 1), change("base", 500000),
                shake(600, "hard"),
                if_(eq("stage", 3), [award("FINAL MELTDOWN", value=var("got"), sub="JUNIOR RISES", seconds=4),
                                     clip("won", "behind"), show("Junior"), sound("won"), music("junior")],
                    [award("SUPER JACKPOT", value=var("got"), sub="THE CORE BACK TO 25%", seconds=4),
                     clip("super", "behind"), show("Super"), sound("super"), timer_start("next", 4000)]),
                *back_to_burn(25)])),
    on_timer("jackpot",
             set_("got", mul(mul(var("base"), var("mult")), var("stage"))),
             if_(AND(eq("stage", 1), eq("jp", "heart")), [set_("got", mul(var("got"), 2))]),
             score(var("got")), change("paid", var("got")), change("jackpots", 1),
             hud_counter(3, var("jackpots"), "JACKPOTS"),
             sound("jackpot"), clip("jackpot", "behind"), change("core", add(2, mul(2, var("stage")))),
             # the heart moves (or the ray turns) first, so the note names where the next jackpot is
             if_(AND(eq("stage", 1), eq("jp", "heart")), [
                 change("core", 4), *heart_moves(), shake(300, "strong"),
                 *[if_(eq("heart", i), [award("HEART JACKPOT", value=var("got"), sub="2X NOW: " + pack.SHOT_WORDS[s],
                                              seconds=pack.NOTE_S)]) for i, s in enumerate(JP, 1)]], [
                 shake(250, "medium"),
                 if_(eq("stage", 2), [set_("ray at", sub(3, var("ray at"))), show("Spiral ray")]),
                 if_(eq("stage", 1), [
                     if_(eq("heart", i), [award("JACKPOT", value=var("got"), sub="2X AT THE " + pack.SHOT_WORDS[s],
                                                seconds=pack.NOTE_S)]) for i, s in enumerate(JP, 1)], [
                     if_(eq("stage", 2), [
                         if_(eq("ray at", i), [award("JACKPOT", value=var("got"), sub="NOW THE " + pack.SHOT_WORDS[s],
                                                     seconds=pack.NOTE_S)]) for i, s in enumerate(RAMPS, 1)],
                         [award("JACKPOT", value=var("got"), sub=" OR ".join(pack.SHOT_WORDS[s] for s in JUNIOR),
                                seconds=pack.NOTE_S)])])]),
             # the add-a-ball lights with the fourth: say where
             if_(AND(eq("jackpots", 4), eq("add used", 0)), [
                 award("ADD-A-BALL IS LIT", sub=pack.shoot(LIGHT_SHOT, verb="HIT THE"), seconds=pack.NOTE_S)]),
             timer_start("core", 1)),

    # ---- the next stage, 4 s after the super (its note has its 4 s; its own shake first) -----------------------------------
    # (and MELTDOWN's strong shake, 0.4 s after the jackpot that set it off and its own shake)
    on_timer("next", if_(eq("phase", 2), [shake(800, "strong")], [if_(lt("stage", 3), [
        change("stage", 1), shake_game("jackpot"), stage_bed(), stage_title(), timer_start("lights", 1),
        if_(eq("stage", 2), [award("DESTOROYAH", sub="THE LEFT RAMP, THEN THE RIGHT", seconds=pack.NOTE_S),
                             clip("destoroyah", "behind"), sound("jackpot"), show("Destoroyah"),
                             hud_counter(3, var("jackpots"), "JACKPOTS", STAGE_NAME[1])],
            [award("JUNIOR COMES", sub=pack.shoot(*JUNIOR), seconds=pack.NOTE_S), clip("junior", "behind"),
             sound("junior"), show("Junior comes"), hud_counter(3, var("jackpots"), "JACKPOTS", STAGE_NAME[2])])])])),

    # ---- cadmium at the shields ---------------------------------------------------------------------------------------------
    # (from 40%, while they are lit: a shield that is dark does nothing - lit = counts)
    *[on_shot(s, if_(AND(eq("phase", 1), ge("core", 40)), [
        change("core", -12), award("CADMIUM MISSILE", sub="THE CORE COOLS", seconds=pack.NOTE_S), show("Cadmium"),
        sound("cool"), clip("cool", "behind"), shake(250, "soft"), timer_start("core", 1)])) for s in SHIELDS],

    # ---- add-a-ball at the captive ball ----------------------------------------------------------------------------------
    on_shot(LIGHT_SHOT, if_(AND(eq("phase", 1), eq("add used", 0), ge("jackpots", 4)), [
        set_("add used", 1),
        if_(eq(BALLS, 1), [multiball(2, 10)], [if_(eq(BALLS, 2), [multiball(3, 10)], [
            if_(eq(BALLS, 3), [multiball(4, 10)], [if_(eq(BALLS, 4), [multiball(5, 10)])])])]),
        award("ADD-A-BALL", sub="ANOTHER BALL IN PLAY", seconds=pack.NOTE_S), sound("add"), shake_game("big_hit"),
        timer_start("lights", 1)])),

    # ---- MELTDOWN missed: the core blows, a quarter of what it held ---------------------------------------------------------
    on_timer("melt", if_(eq("phase", 2), [
        score(div(var("paid"), 4)),
        award("THE CORE BLOWS", value=div(var("paid"), 4), sub="A QUARTER BACK", seconds=3),
        sound("lost", fallback="time_up"), clip("blows", "behind"), show("Core blows"), shake(900, "hard"),
        stage_bed(), set_("base", 2000000), *back_to_burn(50)])),

    on_end(*[timer_stop(t) for t in TIMERS], set_("phase", 0), game_show("Ember fade"), show("Embers"),
           if_(gt("meltdowns", 0), [clip("won", "full")], [clip("lost", "full")]),
           # under MELTDOWN TOTAL: the meltdowns survived and the jackpots (a number can only come last)
           *[if_(eq("meltdowns", m), [hud_line("%d MELTDOWN%s SURVIVED  -  JACKPOTS" % (m, "" if m == 1 else "S"),
                                               value=var("jackpots"))]) for m in range(4)],
           if_(gt("meltdowns", 3), [hud_line("JACKPOTS", value=var("jackpots"))])),
]

PROGRAM = {
    "name": NAME, "seconds": 0, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 190,
    "vars": [{"name": n, "reset": "game"} for n in ("hits", "ready", "starts")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "phase", "core", "level", "was level", "mult", "base", "heart",
                                                "heart secs", "jp", "got", "jackpots", "paid", "meltdowns",
                                                "add used", "secs", "one ball", "ray at")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("%s %s" % (HEART_LINE, pack.SHOT_WORDS[JP[0]]),
               counters=[("CORE", "STABLE", None), ("JACKPOT", "X1 HEAT", None), (STAGE_NAME[0], "JACKPOTS", None)],
               timer=None,
               gauge={"label": "CORE", "kind": "segment", "count": 10, "color": ORANGE,
                      "value": div(add(var("core"), 9), 10)}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "jackpot", "cool", "critical", "meltdown", "won", "lost",
                   "destoroyah", "junior", "super", "blows"),
    "sounds": sounds({"lit": 4, "jackpot": 3, "cool": 4, "critical": 4, "meltdown": 4, "won": 4, "add": 3,
                      "heat": 4, "lost": 4, "super": 3, "junior": 4}),
    "music": "music.wav",
    "beds": beds("destoroyah", "junior", "melt"),
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 106, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "meltdown.c",
    # the Pro has two shields, left and right: the cadmium is those two
    "title_alt": {"godzilla_pro": {"shots": {"Shield target center": None}}},
    "about": ("The C example MELTDOWN rebuilt in blocks and taken deeper: captive ball hits (15, then 30, then 45) "
              "light a 3-ball multiball where the core heats by itself and with every jackpot (x1 to x5) and the "
              "shields cool it; three stages with their own jackpot shots and music (BURNING GODZILLA's four "
              "jackpot shots and the moving heart that pays double, DESTOROYAH's spiral ray at one ramp then the "
              "other, JUNIOR at the Big loop and the Mecha lane), the line naming the shots and moving with them; "
              "each meltdown's super at the Building worth the jackpots paid x2, x3, x4 and taking it a stage "
              "further."),
    "lost": [
        "No randomness in blocks: the HEART starts at the Left ramp and moves in turn (Left ramp, Right ramp, "
        "Building, Big loop) every 10 s and when hit, where the C picked another shot at random every 8 s "
        "(PAD-658: a moving target stays 10 s at least).",
        "The HUD's line names the shots (RAMPS, BIG LOOP, BUILDING: 2X LEFT RAMP, moving with the heart), where the "
        "C said SHOOT RED SHOTS  -  THE HEART PAYS DOUBLE, and from CRITICAL SHIELDS COOL THE CORE  -  OR RIDE THE "
        "HEAT (the HOT and CRITICAL notes say the shields cool it, where the C's said JACKPOTS ARE WORTH MORE); "
        "the heart chases white, where the C blinked it faster in the heat's colour. Every note stays 3 s at "
        "least (the C's level notes 1.8 s, cadmium 1.5 s, the add-a-ball 2 s), a jackpot's naming the next shot "
        "(2X AT THE RIGHT RAMP); the captive ball's note says GODZILLA TARGET, where the C's said CAPTIVE BALL.",
        "A shield cools the core only from 40%, while it is lit (what is lit counts, and only that), where the C's "
        "cooled it at any heat.",
        "The core is looked at once a second (an Every second script), so it rises a whole 1% or 2% each second "
        "and the MELTDOWN blink quickens on the second, where the C stepped them every tick.",
        "No timer badge: the MELTDOWN window is a timer the line counts (SUPER JACKPOT AT THE BUILDING: 17), where "
        "the C counted it on the MELTDOWN badge (a blocks badge counts only the mode's own clock, and this mode "
        "has none).",
        "The HUD shows the core as a number (25), not 25%; the third counter has no SUPER value under it; the "
        "CORE gauge is one colour (the C's ran yellow to white-hot); the lines lost their double spaces to fit "
        "the 40 letters a blocks HUD line holds.",
        "The ending's line under MELTDOWN TOTAL puts the jackpots last (1 MELTDOWN SURVIVED  -  JACKPOTS 6) where "
        "the C said 6 JACKPOTS  -  1 MELTDOWN SURVIVED, says JACKPOTS for one too, and past 3 meltdowns says only "
        "the jackpots.",
        "The ending stays up 3 s, the runtime's: the C kept it 10 s.",
        "The ready light is the runtime's lit mode (held ball after ball), where the C pulsed MAGNA GRAB only while "
        "nothing else owned the playfield.",
        "One ball left is checked once a second after 18 s (two looks in a row), the C's 2 s after the 15 s ball "
        "save and 3 s grace; and the C noted whether a second ball was ever served.",
        "On Godzilla Pro 1.16 the two shields (left, right) cool the core and stay where they are (the Pro's do "
        "not turn); the C on a Pro cooled with the same two.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(name, n, gap=200):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", gap]
    return out


_START = ["trigger", "meltdown.start", "secs", 1]
#: the heart in turn: each shot here is the heart (Left ramp first), 8% a time
_HEARTS = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Building", "ms", 300,
           "shot", "Big loop", "ms", 300]
#: nine hearts in a row (8% each, the core rising too) take the core from 25% to 100%: MELTDOWN
_TO_MELTDOWN = _HEARTS * 2 + ["shot", "Left ramp", "secs", 3]
#: stage 2: the lit ramp in turn (6% a jackpot) until MELTDOWN
_RAYS = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300] * 7 + ["secs", 3]
#: stage 3: Junior's two shots (8% a jackpot)
_JUNIOR = ["shot", "Big loop", "ms", 300, "shot", "Mecha exit bottom", "ms", 300] * 5 + ["secs", 3]
DESK = [
    ("fifteen hits light it and the next starts it", _shots(LIGHT_SHOT, 15, 300) + ["secs", 1, "lamps"] +
     ["shot", LIGHT_SHOT, "secs", 2],
     ["Hud_Award: GODZILLA TARGET", "Hud_AwardSub: 14  -  MORE FOR MELTDOWN", "Hud_AwardSub: 6  -  MORE FOR MELTDOWN",
      "Hud_Award: MELTDOWN IS READY", "Hud_AwardSub: HIT THE GODZILLA TARGET", "LAMP MAGNA GRAB ff1400 pulse",
      "[MELTDOWN] START (its lit shot)", "MULTIBALL 3 balls, save 15 s", "SHIELD toward",
      "Hud_Award: MELTDOWN MULTIBALL", "Hud_Line: RAMPS, BIG LOOP, BUILDING: 2X LEFT RAMP"]),
    # the second time (30): the note at 25, 20, 15, 10 and the last 5
    ("fifteen the first time, thirty the second", _shots(LIGHT_SHOT, 15, 300) + ["secs", 1, "shot", LIGHT_SHOT,
                                                                                 "secs", 2, "trigger",
                                                                                 "meltdown.stop", "secs", 5]
     + ["balls", 1, "secs", 1] + _shots(LIGHT_SHOT, 29, 300) + ["secs", 1, "lamps", "shot", LIGHT_SHOT, "secs", 1,
                                                                 "lamps"],
     ["[MELTDOWN] START (its lit shot)", "END (trigger file)", "Hud_AwardSub: 15  -  MORE FOR MELTDOWN",
      "Hud_AwardSub: 10  -  MORE FOR MELTDOWN", "Hud_AwardSub: 4  -  MORE FOR MELTDOWN",
      "Hud_AwardSub: 1  -  MORE FOR MELTDOWN", "Hud_Award: MELTDOWN IS READY"]),
    ("jackpots heat the core and cadmium cools it", _START + _HEARTS + ["shot", "Left ramp", "ms", 300] +
     ["secs", 1, "shot", "Shield target left", "secs", 1, "lamps"],
     ["SCORE +4000000", "Hud_Award: HEART JACKPOT", "Hud_AwardSub: 4,000,000  -  2X NOW: RIGHT RAMP",
      "Hud_Award: HOT", "Hud_AwardSub: JACKPOTS X2 - SHIELDS COOL THE CORE", "SCORE +8000000",
      "Hud_Line: RAMPS, BIG LOOP, BUILDING: 2X BIG LOOP", "Hud_Award: ADD-A-BALL IS LIT",
      "HELD SHIELD LEFT 78d2ff pulse 900", "HELD MAGNA GRAB 00ff3c blink 300", "Hud_Award: CADMIUM MISSILE"]),
    ("the heart moves after 10 s", _START + ["shot", "Right ramp", "secs", 11, "lamps"],
     ["Hud_Award: JACKPOT", "Hud_AwardSub: 2,000,000  -  2X AT THE LEFT RAMP",
      "Hud_Line: RAMPS, BIG LOOP, BUILDING: 2X RIGHT RAMP", "HELD RIGHT RAMP ffffff chase 90"]),
    ("three stages: destoroyah, junior, the final meltdown", _START + _TO_MELTDOWN + ["shot", "Building", "secs", 8, "lamps"] +
     _RAYS + ["shot", "Building", "secs", 8, "lamps"] + _JUNIOR + ["shot", "Building", "secs", 3,
                                                          "trigger", "meltdown.stop", "secs", 2],
     ["Hud_Award: MELTDOWN!", "LAMP BUILDING ffffff blink 120", "Hud_Award: SUPER JACKPOT",
      "Hud_Award: DESTOROYAH", "Hud_AwardSub: THE LEFT RAMP, THEN THE RIGHT", "HELD LEFT RAMP ff1400 chase 80",
      "Hud_Line: JACKPOT: LEFT RAMP", "Hud_Line: JACKPOT: RIGHT RAMP", "  -  NOW THE RIGHT RAMP", "  -  NOW THE LEFT RAMP",
      "WORDS PadMode_meltdown_Hud_C3_Label: DESTOROYAH",
      "Hud_Award: JUNIOR COMES", "Hud_AwardSub: SHOOT THE BIG LOOP OR MECHA LANE",
      "Hud_Line: JACKPOT: BIG LOOP OR MECHA LANE", "HELD MECHA LANE 78d2ff chase 100", "Hud_Award: FINAL MELTDOWN",
      "  -  JUNIOR RISES", "SHAKE 800 ms at 1", "Hud_Title: DESTOROYAH", "Hud_Title: GODZILLA JUNIOR",
      "END (trigger file)", "Hud_Line: 3 MELTDOWNS SURVIVED  -  JACKPOTS"]),
    ("meltdown missed the core blows", _START + _TO_MELTDOWN + ["secs", 15, "lamps", "secs", 7],
     ["Hud_Award: MELTDOWN!", "Hud_Line: SUPER JACKPOT AT THE BUILDING: 5",
      "LAMP BUILDING ffffff blink 60",
      "Hud_Award: THE CORE BLOWS", "own sound lost", "own clip blows", "WORDS PadMode_meltdown_Hud_C1_Value: 50"]),
    ("one ball left ends it", _START + ["secs", 5, "balls", 1, "secs", 18],
     ["END (a block)", "own clip lost", "Hud_Title: MELTDOWN TOTAL",
      "Hud_Line: 0 MELTDOWNS SURVIVED  -  JACKPOTS 0", "lamps held 0"]),
    ("the last drain", _START + ["shot", "Left ramp", "secs", 2, "balls", 1, "ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]

#: PAD-658: as a Pro gets it - two shields (left and right) cool the core; no shield turn
DESK_PRO = [
    ("the pro's two shields cool the core", _START + _HEARTS + ["secs", 1, "shot", "Shield target right", "secs", 1,
                                                                 "lamps"],
     ["Hud_Award: CADMIUM MISSILE", "HELD SHIELD RIGHT 78d2ff pulse 900", "MULTIBALL 3 balls, save 15 s"]),
    ("the pro lights it and reaches destoroyah", _shots(LIGHT_SHOT, 15, 300) + ["secs", 1, "shot", LIGHT_SHOT,
                                                                                 "secs", 2] + _TO_MELTDOWN +
     ["shot", "Building", "secs", 6],
     ["[MELTDOWN] START (its lit shot)", "Hud_Award: SUPER JACKPOT", "Hud_Award: DESTOROYAH",
      "Hud_Line: JACKPOT: LEFT RAMP"]),
]
