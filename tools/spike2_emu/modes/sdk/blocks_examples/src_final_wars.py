"""FINAL WARS (PAD-658): the SDK's C example final_wars.c rebuilt in blocks, then (round 2) taken deeper - the
pack's wizard mode in four phases, a multiplier carried up by quick phases, and a multiball finale.

Godzilla: Final Wars (2004): the Xiliens set every monster loose at once; Monster X becomes Keizer Ghidorah, Ozaki's
Kaiser power reaches Godzilla, and he rises.

- QUALIFY (a ROUND): play KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE in one game (won or not), or WIN any two
  of them. The ledger is six SHARED variables (reset each game) the other modes set: "ghidorah played" / "oxygen
  played" / "maser played" when they start and "ghidorah won" / "oxygen won" / "maser won" when they are won
  (LEDGER below). A round counts on the next shot and clears the ledger. ONE round lights FINAL WARS the first time,
  TWO the second, THREE the third (pack.need); then it is lit at the Building (gold, pulsing) and stays lit.
- START: the lit Building. Never beside the game's own battle or multiball: it waits, still lit.
- Every value is worth the MULTIPLIER (1 to 4: a phase finished with 10 s or more on its clock carries +1 up) times
  the start (x2 the second time FINAL WARS runs, x3 the third). Every phase's clock is 3 s shorter each start.
- PHASE 1, INVASION (25 s): the Left ramp, the Right ramp and the Big loop blink orange: 3,000,000 each, then out.
- PHASE 2, MONSTER X (25 s): one target is lit purple and moves every 3 s (2.3, 1.6 s on later starts) among the
  three powerlines and the Godzilla target (in turn: the C picks at random); hit it 3 times: 5M, 10M, 15M.
- PHASE 3, KEIZER GHIDORAH (25 s): Godzilla's POWER (10) drains one every 2 s (1.6, 1.2 s); break the three
  gravity beams at the Maser target, the Godzilla target and the Pop bumper (6M each); the Mecha lane is Ozaki's
  KAISER POWER (+3). Power gone: THE XILIENS WIN.
- PHASE 4, GODZILLA RISES (20 s, a 2-ball multiball, its own music): the ramps and the Big loop are JACKPOTS (5M),
  the Building is the SUPER JACKPOT: 30,000,000 + 1,000,000 a second left + 5,000,000 a jackpot. GODZILLA WINS.
- ADD TIME: any Shield target adds 3 s, three times a phase (the shields pulse green while add-time is left).
- ENDS: the super jackpot (won), a phase's clock or the power gone (THE XILIENS WIN: 2,000,000 a phase reached), a
  drain, a tilt.
- Godzilla Pro 1.16: its two shields add the time (no centre shield), the rest is the same.
"""
from blk import (AND, LIT, NOT, OR, SECS_LEFT, a_show, add, add_time, award, beds, change, clip, clips,
                 end, eq, every, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert,
                 light_mode, lt, mul, multiball, music, off, off_insert, on_any_shot, on_drain, on_end, on_shot, on_start, on_timer, score, set_,
                 set_time, shake, shake_game, shield, show, sound, sounds, step, sub, timer_start, timer_stop, var)
import pack

SLUG, NAME = "final_wars", "FINAL WARS"
GOLD, ORANGE, GREEN, PURPLE, WHITE = "#ffaa00", "#ff5000", "#00ff3c", "#aa00ff", "#ffffff"
FIRE, FW_GOLD, XILIEN, KAISER, RED = "#ff3c00", "#ffbe00", "#9600ff", "#40a0ff", "#ff1010"
START_SHOT = "Building"
# the port's lamp places (the C's KIT_AT_BUILDING and the shots' own inserts)
BUILDING_XY, MECHA_XY, MASER_XY, GZ_XY, POP_XY = (123, 202), (282, 393), (51, 417), (89, 260), (251, 413)
CITIES = (("done 1", "Left ramp", "LEFT RAMP"), ("done 2", "Right ramp", "RIGHT RAMP"),
          ("done 3", "Big loop", "BIG LOOP"))
TARGETS = (("Powerline left", "POWERLINE L"), ("Powerline center", "POWERLINE C"),
           ("Powerline right", "POWERLINE R"), ("Godzilla target", "GODZILLA"))
BEAMS = (("done 1", "Maser target"), ("done 2", "Godzilla target"), ("done 3", "Pop bumper"))
KAISER_SHOT = "Mecha exit bottom"
SHIELDS = ("Shield target left", "Shield target center", "Shield target right")
#: the pack's ledger, one SHARED variable each (reset each game): KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE
#: (ghidorah_heads, oxygen_destroyer, maser_barrage) set "<x> played" to 1 as they start and "<x> won" when won
LEDGER_MODES = ("ghidorah", "oxygen", "maser")
PLAYED = [m + " played" for m in LEDGER_MODES]
WON = [m + " won" for m in LEDGER_MODES]
LEDGER = PLAYED + WON
TIMERS = ("lights", "saved", "hit", "move", "next", "drain")
MORE = sub(var("wars"), 1)                    # 0 the first time FINAL WARS runs, 1 the second ...
PHASE_SECS = sub(25, mul(3, MORE))
MOVE_MS = sub(3000, mul(700, MORE))
DRAIN_MS = sub(2000, mul(400, MORE))


def worth(points):
    """A value times the multiplier and the start."""
    return mul(mul(points, var("mult")), var("wars"))


SUPER = worth(add(add(30000000, mul(1000000, SECS_LEFT)), mul(5000000, var("hits"))))


def _sum(names):
    out = var(names[0])
    for n in names[1:]:
        out = add(out, var(n))
    return out


QUALIFIED = OR(eq(_sum(PLAYED), 3), ge(_sum(WON), 2))
ROUNDS = pack.need(1, "wars")                 # 1 round, then 2, then 3


def xy(fx, ms, a, b, p, rate=0, gi="keep", blend=0):
    return step(fx, ms, a, b, "xy", rate=rate, gi=gi, blend=blend, x=p[0], y=p[1])


SHOWS = [
    a_show("Invasion",
           step("strobe", 500, WHITE, FIRE, "center", rate=55, gi="flash"),
           step("fire", 1300, FIRE, FW_GOLD, "top", gi="dark"),
           step("sweep_down", 700, ORANGE, "#000000", "center", gi="dark"),
           xy("burst", 700, FW_GOLD, FIRE, BUILDING_XY, gi="dark"),
           step("fade", 500, FIRE, "#000000", "center", blend=200)),
    a_show("City saved",
           step("sweep_lr", 400, ORANGE, "#000000", "center", gi="keep"),
           step("fade", 300, ORANGE, "#000000", "center")),
    a_show("Monster X hit",
           step("bolts", 600, WHITE, XILIEN, "top", rate=120, gi="flash"),
           step("fade", 300, XILIEN, "#000000", "top")),
    a_show("Phase won",
           step("burst", 700, WHITE, FW_GOLD, "center", gi="flash"),
           step("rainbow", 900, "#000000", "#000000", "center", rate=60),
           step("fade", 400, FW_GOLD, "#000000", "center")),
    a_show("Keizer",
           step("solid", 500, "#201000", "#000000", "center", gi="dark"),
           step("bolts", 1200, FW_GOLD, "#301000", "top", rate=90, gi="dark"),
           step("sweep_down", 800, FW_GOLD, "#000000", "center", gi="dark"),
           step("fade", 400, FW_GOLD, "#000000", "center")),
    a_show("Beam broken",
           step("implode", 500, FW_GOLD, WHITE, "center", gi="flash"),
           step("burst", 500, WHITE, FW_GOLD, "center", gi="keep"),
           step("fade", 300, FW_GOLD, "#000000", "center")),
    a_show("Kaiser power",
           xy("spiral_out", 900, KAISER, "#000020", MECHA_XY, gi="dark"),
           xy("ripple", 700, WHITE, KAISER, MECHA_XY, rate=250, gi="keep"),
           step("fade", 300, KAISER, "#000000", "center")),
    a_show("Weakening",
           step("pulse", 1200, RED, "#000000", "center", rate=300, gi="dark"),
           step("fade", 400, RED, "#000000", "center")),
    a_show("Godzilla rises",
           step("fade_in", 600, KAISER, "#000000", "center", gi="dark"),
           step("spin", 1200, WHITE, KAISER, "center", rate=80, gi="dark"),
           step("strobe", 400, WHITE, KAISER, "center", rate=50, gi="flash"),
           step("spiral_out", 900, KAISER, "#000020", "center", gi="dark"),
           step("fade", 500, KAISER, "#000000", "center", blend=200)),
    a_show("Jackpot",
           step("bounce", 600, RED, "#200000", "top", rate=200, gi="keep"),
           step("burst", 400, WHITE, RED, "top", gi="flash"),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Super",
           step("strobe", 500, WHITE, KAISER, "center", rate=45, gi="flash"),
           xy("burst", 900, WHITE, FIRE, BUILDING_XY, gi="dark"),
           step("fire", 1200, FIRE, FW_GOLD, "center", gi="dark"),
           step("rainbow", 1800, "#000000", "#000000", "center", rate=50),
           step("fade", 700, FW_GOLD, "#000000", "center", blend=300)),
    a_show("Xiliens win",
           step("sparkle", 900, XILIEN, "#100020", "center", gi="dark"),
           step("sweep_up", 800, PURPLE, "#000000", "flippers", gi="dark"),
           step("fade", 800, XILIEN, "#000000", "center")),
]


def phase1_line():
    """SAVE and the cities still to save (the C writes the list; the blocks pick one of the seven lines)."""
    def leaf(l, r, b):
        names = [w for done, (_v, _s, w) in zip((l, r, b), CITIES) if not done]
        return [hud_line("SAVE  " + "  ".join(names))] if names else []

    def by(i, picked):
        if i == 3:
            return leaf(*picked)
        v = CITIES[i][0]
        return [if_(eq(v, 0), by(i + 1, picked + (0,)), by(i + 1, picked + (1,)))]
    return by(0, ())


def lights():
    """What every phase lights (the C's show_lamps / show), run by the "lights" timer after every change."""
    return [
        if_(eq("phase", 1), [
            *[if_(eq(v, 0), [light(s, ORANGE, "hurry")], [off(s)]) for v, s, _w in CITIES],
            *phase1_line(),
            hud_counter(2, var("left"), "TO SAVE", "CITIES"),
        ]),
        if_(eq("phase", 2), [
            *[off(s) for _v, s, _w in CITIES],
            *[if_(eq("monster x", i), [light(s, PURPLE, "blink", 150), hud_line("HIT MONSTER X AT " + w)], [off(s)])
              for i, (s, w) in enumerate(TARGETS, 1)],
            hud_counter(2, var("hits"), "OF 3 HITS", "MONSTER X"),
        ]),
        if_(eq("phase", 3), [
            *[off(s) for s, _w in TARGETS],
            *[if_(eq(v, 0), [light(s, FW_GOLD, "chase", 110)], [off(s)]) for v, s in BEAMS],
            light_insert("MECHA LANE", KAISER, "pulse", 900),
            hud_line("BREAK GHIDORAH'S BEAMS", value=var("left")),
            hud_counter(2, var("power"), "OF 10", "POWER"),
        ]),
        if_(eq("phase", 4), [
            *[off(s) for _v, s in BEAMS], off_insert("MECHA LANE"),
            *[light(s, RED, "chase", 80) for _v, s, _w in CITIES],
            light(START_SHOT, GOLD, "hurry"), hud_line("RAMPS AND LOOP, THEN THE BUILDING"),
            hud_counter(2, SUPER, "BUILDING", "SUPER"),
        ]),
        if_(lt("adds", 3), [light(s, GREEN, "pulse", 1200) for s in SHIELDS], [off(s) for s in SHIELDS]),
    ]


def city(v, shot, words):
    """A city saved in phase 1, a jackpot in phase 4."""
    return on_shot(shot,
                   if_(AND(eq("phase", 1), eq(v, 0)), [
                       set_(v, 1), score(worth(3000000)),
                       award(words + " SAVED", value=worth(3000000), sub="A CITY SAVED", seconds=1),
                       show("City saved"), shake(250, "soft"), timer_start("saved", 1)]),
                   if_(eq("phase", 4), [
                       change("hits", 1), score(worth(5000000)),
                       award("JACKPOT", value=worth(5000000), sub="NOW THE BUILDING", seconds=2),
                       clip("jackpot", "behind"), sound("jackpot"), show("Jackpot"), shake(400, "strong")]))


def move_on():
    """MONSTER X moves to the next target (in turn: no random numbers in blocks)."""
    return [change("monster x", 1), if_(gt("monster x", 4), [set_("monster x", 1)])]


def beam(v, shot):
    """A gravity beam broken in phase 3 (the Godzilla target is also a Monster X place in phase 2)."""
    phase2 = []
    for i, (s, _w) in enumerate(TARGETS, 1):
        if s == shot:
            phase2 = [if_(AND(eq("phase", 2), eq("monster x", i)), [timer_start("hit", 1)])]
    return on_shot(shot, *phase2, if_(AND(eq("phase", 3), eq(v, 0)), [
        set_(v, 1), score(worth(6000000)),
        award("BEAM BROKEN", value=worth(6000000), sub="KEIZER GHIDORAH REELS", seconds=2),
        show("Beam broken"), shake(500, "strong"), timer_start("saved", 1)]))


def phase_award(words, normal, quick_words="QUICK! THE MULTIPLIER IS UP"):
    return if_(eq("quick", 1), [award(words, sub=quick_words, seconds=3)], [award(words, sub=normal, seconds=3)])


SCRIPTS = [
    # ---- lit by the pack's ledger: a round each time, 1 round then 2 then 3 ------------------------------------------
    on_any_shot(
        if_(QUALIFIED, [
            *[set_(n, 0) for n in LEDGER], change("rounds", 1),
            if_(ge("rounds", ROUNDS), [
                set_("ready", 1), light_mode(START_SHOT, GOLD, "pulse"),
                award("FINAL WARS IS LIT", sub="SHOOT THE BUILDING", seconds=4)],
                [award("FINAL WARS", value=sub(ROUNDS, var("rounds")), sub="MORE ROUNDS TO LIGHT IT", seconds=4)])]),
        if_(AND(eq("ready", 1), NOT(LIT)), [light_mode(START_SHOT, GOLD, "pulse")]),
        when="idle"),

    # ---- the start: the qualification used up -------------------------------------------------------------------
    on_start(*pack.begin(SLUG), *[set_(n, 0) for n in LEDGER], set_("ready", 0), set_("rounds", 0), change("wars", 1),
             set_("phase", 1), set_("adds", 0), set_("won", 0), set_("drained", 0), set_("hits", 0), set_("quick", 0),
             set_("monster x", 1), set_("left", 3), set_("mult", 1), set_("power", 10),
             *[set_(v, 0) for v, _s, _w in CITIES], set_time(PHASE_SECS),
             shield("toward"), show("Invasion"), shake_game("big_hit"),
             clip("intro", "full"), clip("loop", "loop"),
             hud_title("GODZILLA: FINAL WARS"), hud_counter(1, 1, "INVASION"),
             award("PHASE 1: INVASION", sub="SAVE THE CITIES", seconds=3),
             timer_start("lights", 1)),
    on_timer("lights", *lights()),

    # ---- phase 1: invasion (and phase 4's jackpots) -------------------------------------------------------------------
    *[city(v, s, w) for v, s, w in CITIES],
    on_timer("saved", change("left", -1),
             if_(le("left", 0), [timer_start("next", 700)], [timer_start("lights", 1)])),

    # ---- phase 2: Monster X -------------------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(eq("phase", 2), eq("monster x", i)), [timer_start("hit", 1)]))
      for i, (s, _w) in enumerate(TARGETS, 1) if s != "Godzilla target"],
    on_timer("hit", change("hits", 1), score(worth(mul(5000000, var("hits")))), show("Monster X hit"),
             shake(350, "medium"),
             if_(ge("hits", 3), [award("MONSTER X FALLS", value=worth(15000000), sub="NOW KEIZER GHIDORAH"),
                                 timer_stop("move"), timer_start("next", 700)], [
                 award("MONSTER X HIT", value=var("hits"), sub="OF 3", seconds=1),
                 *move_on(), timer_start("move", MOVE_MS), timer_start("lights", 1)])),
    on_timer("move", if_(eq("phase", 2), [*move_on(), timer_start("move", MOVE_MS), timer_start("lights", 1)])),

    # ---- phase 3: Keizer Ghidorah's beams, Ozaki's Kaiser power --------------------------------------------------------
    *[beam(v, s) for v, s in BEAMS],
    on_shot(KAISER_SHOT, if_(eq("phase", 3), [
        change("power", 3), if_(gt("power", 10), [set_("power", 10)]), score(worth(1000000)),
        award("KAISER POWER", value=var("power"), sub="GODZILLA'S POWER", seconds=2),
        clip("power", "behind"), show("Kaiser power"), shake(200, "soft"), timer_start("lights", 1)])),
    on_timer("drain", if_(eq("phase", 3), [
        change("power", -1), hud_counter(2, var("power"), "OF 10"),
        if_(le("power", 0), [end()], [
            if_(eq("power", 3), [sound("beam"), show("Weakening"),
                                 award("GODZILLA WEAKENS", sub="KAISER POWER AT THE MECHA LANE", seconds=2)]),
            timer_start("drain", DRAIN_MS)])])),

    # ---- phase 4: Godzilla rises, the super jackpot ----------------------------------------------------------------
    on_shot(START_SHOT, if_(AND(eq("phase", 4), eq("won", 0)), [
        set_("won", 1), score(SUPER), award("SUPER JACKPOT", value=SUPER, sub="GODZILLA WINS", seconds=4),
        clip("super", "behind"), sound("super"), show("Super"), shake(1000, "hard"), timer_start("next", 1500)])),
    every(1, if_(eq("phase", 4), [hud_counter(2, SUPER, "BUILDING")])),

    # ---- the next phase (a quick phase carries the multiplier up) ----------------------------------------------------
    on_timer("next", if_(eq("won", 1), [end()], [
        set_("quick", 0), if_(AND(ge(SECS_LEFT, 10), lt("mult", 4)), [change("mult", 1), set_("quick", 1)]),
        change("phase", 1), set_("adds", 0), set_time(PHASE_SECS), clip("phase", "behind"),
        if_(eq("phase", 2), [
            set_("hits", 0), timer_start("move", MOVE_MS), sound("phase1"), clip("loop2", "loop"), show("Phase won"),
            shake_game("jackpot"), hud_counter(1, 2, "MONSTER X"),
            phase_award("PHASE 2: MONSTER X", "HIT MONSTER X 3 TIMES")]),
        if_(eq("phase", 3), [
            set_("left", 3), *[set_(v, 0) for v, _s in BEAMS], set_("power", 10), timer_start("drain", DRAIN_MS),
            sound("phase2"), clip("keizer", "behind"), clip("loop3", "loop"), show("Keizer"), shake_game("jackpot"),
            hud_counter(1, 3, "GHIDORAH"), phase_award("KEIZER GHIDORAH", "PHASE 3: BREAK HIS GRAVITY BEAMS")]),
        if_(eq("phase", 4), [
            set_time(sub(20, mul(3, MORE))), timer_stop("drain"), set_("hits", 0), multiball(2, 10),
            music("rises"), clip("rises", "behind"), show("Godzilla rises"), shake(1000, "strong"),
            hud_counter(1, 4, "THE FINAL"), phase_award("GODZILLA RISES", "PHASE 4: JACKPOTS, THEN THE BUILDING")]),
        timer_start("lights", 1)])),

    # ---- add time at the shields ----------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(lt("adds", 3), lt("phase", 5)), [
        change("adds", 1), add_time(3), award("SHIELDS", sub="+3 SECONDS", seconds=1), timer_start("lights", 1)]))
      for s in SHIELDS],

    # ---- the end ---------------------------------------------------------------------------------------------------
    on_drain(set_("drained", 1)),
    on_end(*pack.finish(), *[timer_stop(t) for t in TIMERS],
           if_(eq("won", 1), [clip("won", "full"), hud_title("GODZILLA WINS"), hud_line("THE XILIENS ARE BEATEN")], [
               set_("pay", mul(2000000, var("phase"))), score(var("pay")),
               award("THE XILIENS WIN", value=var("pay"), sub="FOR THE FIGHT", seconds=3),
               clip("lost", "full"), show("Xiliens win"), shake_game("rumble"), hud_title("THE XILIENS WIN"),
               if_(eq("power", 0), [hud_line("KEIZER GHIDORAH DRAINED HIM")], [hud_line("2,000,000 A PHASE")]),
               if_(eq("drained", 0), [sound("lost", fallback="time_up")])]),
           set_("phase", 0)),
]

PROGRAM = {
    "name": NAME, "seconds": 25, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 190,
    "vars": [{"name": n, "reset": "game", "shared": True} for n in LEDGER] + [
        {"name": n, "reset": "game"} for n in ("wars", "rounds", "ready")] + [
        {"name": n, "reset": "mode"} for n in ("phase", "left", "done 1", "done 2", "done 3", "monster x", "hits",
                                                "adds", "won", "drained", "mult", "power", "quick", "pay")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SAVE THE CITIES",
               counters=[("PHASE", "INVASION", var("phase")), ("TARGETS", "OF 3", None),
                         ("ADD TIME", "SHIELDS +3 SEC", sub(3, var("adds")))],
               timer=("FINAL WARS", "xilien"),
               gauge={"label": "MULTIPLIER", "kind": "diamond", "count": 4, "color": "#ff3c00",
                      "value": var("mult")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "loop2", "loop3", "phase", "won", "lost", "keizer", "power", "rises", "jackpot",
                   "super"),
    "sounds": sounds({"phase1": 4, "phase2": 4, "won": 4, "lost": 4, "beam": 3, "jackpot": 3, "super": 3}),
    "music": "music.wav",
    "beds": beds("rises"),
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 104, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "final_wars.c",
    # Godzilla Pro 1.16: two fixed shields (no centre one, no platform to turn): its left and right add the time
    "title_alt": {"godzilla_pro": {"shots": {"Shield target center": None}}},
    "about": ("The C example FINAL WARS rebuilt in blocks and taken deeper (PAD-658): a round of KING GHIDORAH, "
              "OXYGEN DESTROYER and MASER BARRAGE played (or two of them won) lights it at the Building the first "
              "time, two rounds the second, three the third. Four timed phases: save the cities, hit the moving "
              "Monster X, break Keizer Ghidorah's three beams before Godzilla's power drains (the Mecha lane "
              "recharges it), and GODZILLA RISES, a 2-ball multiball with jackpots and the Building super jackpot. "
              "A quick phase carries the multiplier up (to x4); shields add time."),
    "lost": [
        "No randomness in blocks: Monster X moves to the next target in turn (Powerline left, center, right, the "
        "Godzilla target, round again) every 3 s and when hit, where the C picked another target at random.",
        "The ledger is six shared variables (ghidorah / oxygen / maser played and won) the blocks KING GHIDORAH, "
        "OXYGEN DESTROYER and MASER BARRAGE set; the C modes' own ledger (kit_ledger) is a different store, so the "
        "C versions of those modes do not light this blocks version, nor the other way round.",
        "A round counts on the next shot after it is played (blocks only look while a shot is made), where the C "
        "looked twice a second; and the FINAL WARS IS LIT note shows then, not 7 s after the other mode's total.",
        "The lit Building pulses as any lit mode does (the runtime's light), where the C pulsed it only while none "
        "of our modes ran and not between balls.",
        "The ending title (GODZILLA WINS or THE XILIENS WIN) and its total stay up 3 s, the runtime's: the C kept "
        "them 10 s, with FINAL WARS TOTAL under the total.",
        "It plays its own light shows at every moment, where the C played the game's Strobe storm and Red and blue "
        "fade (its own shows only on a game without them).",
        "Godzilla Pro 1.16 has two shields (no centre one, no platform to turn): its left and right add the time, "
        "where the C simply had one shield fewer there.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


_START = ["trigger", "final_wars.start", "secs", 1]
_P1 = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Big loop", "secs", 2]
_P2 = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300, "shot", "Powerline right",
       "secs", 2]
_P3 = ["shot", "Maser target", "ms", 300, "shot", "Godzilla target", "ms", 300, "shot", "Pop bumper", "secs", 3]
DESK = [
    ("won phase by phase", _START + _P1 + _P2 + _P3 + ["shot", "Left ramp", "ms", 500, "shot", "Building", "secs", 6],
     ["Hud_Award: PHASE 2: MONSTER X", "Hud_AwardSub: QUICK! THE MULTIPLIER IS UP", "Hud_Award: MONSTER X FALLS",
      "Hud_Award: KEIZER GHIDORAH", "Hud_Award: BEAM BROKEN", "Hud_Award: GODZILLA RISES", "MULTIBALL 2",
      "Hud_Award: JACKPOT", "Hud_Award: SUPER JACKPOT", "Hud_C2_Label: SUPER", "own clip super", "SHIELD toward",
      "Hud_Title: GODZILLA WINS", "lamps held 0"]),
    ("monster x moves", _START + _P1 + ["secs", 3.5, "lamps"],
     ["LAMP POWERLINE LEFT aa00ff blink 150", "LAMP POWERLINE CENTER aa00ff blink 150",
      "Hud_Line: HIT MONSTER X AT POWERLINE C", "Hud_C2_Label: CITIES", "Hud_C2_Label: MONSTER X"]),
    ("keizer drains godzilla's power", _START + _P1 + _P2 + ["secs", 23],
     ["Hud_Line: BREAK GHIDORAH'S BEAMS 3", "Hud_C2_Label: POWER", "Hud_Award: GODZILLA WEAKENS",
      "END (a block)", "Hud_Title: THE XILIENS WIN", "Hud_Line: KEIZER GHIDORAH DRAINED HIM", "SCORE +6000000",
      "lamps held 0"]),
    ("kaiser power at the mecha lane", _START + _P1 + _P2 + ["secs", 6, "shot", "Mecha exit bottom", "secs", 4],
     ["Hud_Award: KAISER POWER", "Hud_C2_Value: 10", "own clip power", "LAMP MECHA LANE 40a0ff pulse 900"]),
    ("shields add time then the clock", _START + ["shot", "Shield target left", "ms", 300] * 4 + ["secs", 40],
     ["Hud_Award: SHIELDS", "WORDS PadMode_final_wars_Hud_C3_Value: 0", "END (time ran out)", "own sound lost",
      "own clip lost", "Hud_Title: THE XILIENS WIN", "SCORE +2000000", "lamps held 0"]),
    ("a drain", _START + ["shot", "Left ramp", "secs", 2, "ball_end", "secs", 4],
     ["END (ball ended)", "own clip lost", "lamps held 0"]),
]


def _played(slug):
    return ["trigger", slug + ".start", "secs", 1, "trigger", slug + ".stop", "secs", 2]


_ROUND = _played("ghidorah_heads") + _played("oxygen_destroyer") + _played("maser_barrage") + ["secs", 3, "shot",
                                                                                               "Left ramp", "secs", 5]
#: the lighting rule needs the three ledger modes beside it in the desk harness: played when they are built in
#: (make_examples.py --desk with no slugs, or with these four named)
_named = [a for a in __import__("sys").argv[1:] if not a.startswith("-")]
if not _named or {"ghidorah_heads", "oxygen_destroyer", "maser_barrage"} <= set(_named):
    DESK.append(("one round lights it, two the second time",
                 _ROUND + ["shot", "Building", "secs", 2, "trigger", "final_wars.stop", "secs", 5] + _ROUND +
                 ["shot", "Building", "secs", 2] + _ROUND + ["shot", "Building", "secs", 2],
                 ["Hud_Award: FINAL WARS IS LIT", "[FINAL WARS] START (its lit shot)", "END (trigger file)",
                  "Hud_AwardSub: 1  -  MORE ROUNDS TO LIGHT IT"]))
#: the same mode as a Godzilla Pro 1.16 gets it: two shields add the time
DESK_PRO = [
    ("the Pro's two shields add time", _START + ["shot", "Shield target left", "ms", 300,
                                                 "shot", "Shield target right", "ms", 300] * 2 + ["secs", 5],
     ["Hud_Award: SHIELDS", "WORDS PadMode_final_wars_Hud_C3_Value: 0", "LAMP LEFT RAMP ff5000 blink 700"]),
    ("won phase by phase on the Pro", _START + _P1 + _P2 + _P3 + ["shot", "Left ramp", "ms", 500,
                                                                  "shot", "Building", "secs", 6],
     ["Hud_Award: BEAM BROKEN", "MULTIBALL 2", "Hud_Award: SUPER JACKPOT", "Hud_Title: GODZILLA WINS",
      "lamps held 0"]),
]
