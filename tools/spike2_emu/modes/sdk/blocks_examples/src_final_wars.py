"""FINAL WARS (PAD-658): the SDK's C example final_wars.c rebuilt in blocks - a three-phase wizard mode lit by playing
the pack's other modes.

Godzilla: Final Wars (2004): the Xiliens set every monster loose at once.

- QUALIFY: play KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE in one game (won or not), or WIN any two of them.
  The ledger is six SHARED variables (reset each game) the other modes set: "ghidorah played" / "oxygen played" /
  "maser played" when they start and "ghidorah won" / "oxygen won" / "maser won" when they are won (LEDGER below).
  Then FINAL WARS is lit at the Building (gold, pulsing) and stays lit.
- START: the lit Building. Never beside the game's own battle or multiball: it waits, still lit. Starting uses the
  qualification up (the ledger goes back to nothing).
- PHASE 1, INVASION (25 s): the Left ramp, the Right ramp and the Big loop blink orange: 3,000,000 each, then out.
- PHASE 2, MONSTER X (25 s): one target is lit purple and moves every 3 s among the three powerlines and the
  Godzilla target (in turn here: the C picks at random); hit it 3 times: 5M, 10M, 15M. It moves at once when hit.
- PHASE 3, KEIZER GHIDORAH (20 s): the Building: 30,000,000 + 1,000,000 a second left. GODZILLA WINS.
- ADD TIME: any Shield target adds 3 s, three times a phase (the shields pulse green while add-time is left).
- ENDS: the wizard shot (won), a phase's clock (THE XILIENS WIN), a drain, a tilt.
"""
from blk import (AND, BALLS, LIT, NOT, OR, SECS_LEFT, a_show, add, add_time, award, clip, clips, end, eq, every, ge,
                 hud, hud_counter, hud_line, hud_title, if_, light, light_mode, lt, mul, off, on_any_shot, on_drain,
                 on_end, on_shot, on_start, on_timer, score, set_, set_time, shake_game, shield, show, sound, sounds,
                 step, sub, change, game_show, timer_start, timer_stop, var, gt)

SLUG, NAME = "final_wars", "FINAL WARS"
GOLD, ORANGE, GREEN, PURPLE, WHITE = "#ffaa00", "#ff5000", "#00ff3c", "#aa00ff", "#ffffff"
FIRE, FW_GOLD, XILIEN = "#ff3c00", "#ffbe00", "#9600ff"
START_SHOT = "Building"
BX, BY = 123, 202                     # the BUILDING insert's place (the port's lamp line), the C's KIT_AT_BUILDING
CITIES = (("left done", "Left ramp", "LEFT RAMP"), ("right done", "Right ramp", "RIGHT RAMP"),
          ("loop done", "Big loop", "BIG LOOP"))
TARGETS = (("Powerline left", "POWERLINE L"), ("Powerline center", "POWERLINE C"),
           ("Powerline right", "POWERLINE R"), ("Godzilla target", "GODZILLA"))
SHIELDS = ("Shield target left", "Shield target center", "Shield target right")
#: the pack's ledger, one SHARED variable each (reset each game): KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE
#: (ghidorah_heads, oxygen_destroyer, maser_barrage) set "<x> played" to 1 as they start and "<x> won" when won
LEDGER_MODES = ("ghidorah", "oxygen", "maser")
PLAYED = [m + " played" for m in LEDGER_MODES]
WON = [m + " won" for m in LEDGER_MODES]
LEDGER = PLAYED + WON
TIMERS = ("lights", "saved", "hit", "move", "next")


def _sum(names):
    out = var(names[0])
    for n in names[1:]:
        out = add(out, var(n))
    return out


def counter(n, value, sub, label):
    """A HUD counter's value, sub and (PAD-658) its label from now on."""
    b = hud_counter(n, value, sub)
    b["label"] = label
    return b


QUALIFIED = OR(eq(_sum(PLAYED), 3), ge(_sum(WON), 2))

SHOWS = [
    a_show("Phase won",
           step("burst", 700, WHITE, FW_GOLD, "center", gi="flash"),
           step("fade", 400, FW_GOLD, "#000000", "center")),
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
            counter(2, var("cities left"), "TO SAVE", "CITIES"),
        ]),
        if_(eq("phase", 2), [
            *[off(s) for _v, s, _w in CITIES],
            *[if_(eq("monster x", i), [light(s, PURPLE, "blink", 150), hud_line("HIT MONSTER X AT " + w)], [off(s)])
              for i, (s, w) in enumerate(TARGETS, 1)],
            counter(2, var("hits"), "OF 3 HITS", "MONSTER X"),
        ]),
        if_(eq("phase", 3), [
            *[off(s) for s, _w in TARGETS],
            light(START_SHOT, GOLD, "hurry"), hud_line("WIZARD SHOT: THE BUILDING"),
            counter(2, add(30000000, mul(1000000, SECS_LEFT)), "BUILDING", "WIZARD"),
        ]),
        if_(lt("adds", 3), [light(s, GREEN, "pulse", 1200) for s in SHIELDS], [off(s) for s in SHIELDS]),
    ]


def city(v, shot, words):
    return on_shot(shot, if_(AND(eq("phase", 1), eq(v, 0)), [
        set_(v, 1), score(3000000), award(words + " SAVED", sub="3,000,000", seconds=1),
        timer_start("saved", 1)]))


def target(i, shot):
    return on_shot(shot, if_(AND(eq("phase", 2), eq("monster x", i)), [timer_start("hit", 1)]))


def move_on():
    """MONSTER X moves to the next target (in turn: no random numbers in blocks)."""
    return [change("monster x", 1), if_(gt("monster x", 4), [set_("monster x", 1)])]


SCRIPTS = [
    # ---- lit by the pack's ledger -----------------------------------------------------------------------------
    on_any_shot(if_(AND(QUALIFIED, NOT(LIT)), [
        light_mode(START_SHOT, GOLD, "pulse"),
        award("FINAL WARS IS LIT", sub="SHOOT THE BUILDING", seconds=4)]), when="idle"),

    # ---- the start: the qualification used up -------------------------------------------------------------------
    on_start(*[set_(n, 0) for n in LEDGER],
             set_("phase", 1), set_("adds", 0), set_("won", 0), set_("drained", 0), set_("hits", 0),
             set_("monster x", 1), set_("cities left", 3), *[set_(v, 0) for v, _s, _w in CITIES],
             shield("toward"), game_show("Strobe storm"), shake_game("multiball_start"),
             clip("intro", "full"), clip("loop", "loop"),
             hud_title("GODZILLA: FINAL WARS"), hud_counter(1, 1, "INVASION"),
             award("PHASE 1: INVASION", sub="SAVE THE CITIES", seconds=3),
             timer_start("lights", 1)),
    on_timer("lights", *lights()),

    # ---- phase 1: invasion ------------------------------------------------------------------------------------------
    *[city(v, s, w) for v, s, w in CITIES],
    on_timer("saved", change("cities left", -1),
             if_(eq("cities left", 0), [timer_start("next", 1)], [timer_start("lights", 1)])),

    # ---- phase 2: Monster X -------------------------------------------------------------------------------------------
    *[target(i, s) for i, (s, _w) in enumerate(TARGETS, 1)],
    on_timer("hit", change("hits", 1), score(mul(5000000, var("hits"))),
             if_(ge("hits", 3), [timer_start("next", 1)], [
                 award("MONSTER X HIT", value=var("hits"), sub="5,000,000 X HITS", seconds=1),
                 *move_on(), timer_start("move", 3000), timer_start("lights", 1)])),
    on_timer("move", if_(eq("phase", 2), [*move_on(), timer_start("move", 3000), timer_start("lights", 1)])),

    # ---- phase 3: the wizard shot ---------------------------------------------------------------------------------
    on_shot(START_SHOT, if_(eq("phase", 3), [
        score(add(30000000, mul(1000000, SECS_LEFT))), set_("won", 1), sound("won"), end()])),
    every(1, if_(eq("phase", 3), [hud_counter(2, add(30000000, mul(1000000, SECS_LEFT)), "BUILDING")])),

    # ---- the next phase -----------------------------------------------------------------------------------------------
    on_timer("next", change("phase", 1), set_("adds", 0), show("Phase won"), clip("phase", "behind"),
             if_(eq("phase", 2), [
                 set_time(25), set_("hits", 0), timer_start("move", 3000), sound("phase1"), clip("loop2", "loop"),
                 hud_counter(1, 2, "MONSTER X"),
                 award("PHASE 2: MONSTER X", sub="HIT MONSTER X 3 TIMES", seconds=2)]),
             if_(eq("phase", 3), [
                 set_time(20), timer_stop("move"), sound("phase2"), clip("loop3", "loop"),
                 hud_counter(1, 3, "GHIDORAH"),
                 award("PHASE 3: GHIDORAH", sub="THE BUILDING IS THE WIZARD SHOT", seconds=2)]),
             timer_start("lights", 1)),

    # ---- add time at the shields ----------------------------------------------------------------------------------
    *[on_shot(s, if_(lt("adds", 3), [change("adds", 1), add_time(3), award("SHIELDS", sub="+3 SECONDS", seconds=1),
                                      timer_start("lights", 1)])) for s in SHIELDS],

    # ---- the end ---------------------------------------------------------------------------------------------------
    on_drain(set_("drained", 1)),
    on_end(*[timer_stop(t) for t in TIMERS], set_("phase", 0), game_show("Red and blue fade"),
           if_(eq("won", 1), [clip("won", "full"), shake_game("jackpot"), hud_title("GODZILLA WINS")], [
               clip("lost", "full"), hud_title("THE XILIENS WIN"), if_(eq("drained", 0), [sound("lost", fallback="time_up")])])),
]

PROGRAM = {
    "name": NAME, "seconds": 25, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 190,
    "vars": [{"name": n, "reset": "game", "shared": True} for n in LEDGER] + [
        {"name": n, "reset": "mode"} for n in ("phase", "cities left", "left done", "right done", "loop done",
                                                "monster x", "hits", "adds", "won", "drained")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SAVE THE CITIES",
               counters=[("PHASE", "INVASION", var("phase")), ("TARGETS", "OF 3", None),
                         ("ADD TIME", "SHIELDS +3 SEC", sub(3, var("adds")))],
               timer=("FINAL WARS", "xilien"),
               gauge={"label": "PHASES", "kind": "diamond", "count": 3, "color": "#ff3c00",
                      "value": sub(var("phase"), 1)}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "loop2", "loop3", "phase", "won", "lost"),
    "sounds": sounds({"phase1": 4, "phase2": 4, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 104, "titles": ["godzilla_le"], "based_on": "final_wars.c",
    "about": ("The C example FINAL WARS rebuilt in blocks: lit by playing KING GHIDORAH, OXYGEN DESTROYER and "
              "MASER BARRAGE (or winning two), started at the Building; three timed phases (save the cities, "
              "hit the moving Monster X, the Building wizard shot), shields add time."),
    "lost": [
        "No randomness in blocks: Monster X moves to the next target in turn (Powerline left, center, right, the "
        "Godzilla target, round again) every 3 s and when hit, where the C picked another target at random.",
        "The ledger is six shared variables (ghidorah / oxygen / maser played and won) the blocks KING GHIDORAH, "
        "OXYGEN DESTROYER and MASER BARRAGE set; the C modes' own ledger (kit_ledger) is a different store, so the "
        "C versions of those modes do not light this blocks version, nor the other way round.",
        "It lights on the next shot after it qualifies (blocks only look while a shot is made), where the C looked "
        "twice a second; and the FINAL WARS IS LIT note shows then, not 7 s after the other mode's total.",
        "The lit Building pulses as any lit mode does (the runtime's light), where the C pulsed it only while none "
        "of our modes ran and not between balls.",
        "The ending title (GODZILLA WINS or THE XILIENS WIN) and its total stay up 3 s, the runtime's: the C kept "
        "them 10 s.",
        "The ending has no FINAL WARS TOTAL under the total: the C put those words there.",
        "The game's own light shows (Strobe storm, Red and blue fade) always play at the start and the end; the C "
        "played its own start/won/lost shows on a game without them (Godzilla LE has both, so the C never did there).",
        "The jackpot shake starts as the mode ends rather than being run out past the end (pm_shake_outlast).",
        "Godzilla LE only: the program names the center shield target (Godzilla Pro has two shields), where the C "
        "simply had one shield fewer there.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


_START = ["trigger", "final_wars.start", "secs", 1]
_P1 = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Big loop", "secs", 1]
_P2 = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300, "shot", "Powerline right",
       "secs", 1]
DESK = [
    ("won phase by phase", _START + _P1 + _P2 + ["secs", 2, "shot", "Building", "secs", 6],
     ["Hud_Award: PHASE 2: MONSTER X", "Hud_Award: PHASE 3: GHIDORAH", "SCORE +3000000", "SCORE +5000000",
      "SCORE +10000000", "SCORE +15000000", "SCORE +47000000", "Hud_C2_Label: WIZARD", "own sound won", "own clip won", "SHIELD toward",
      "Hud_Title: GODZILLA WINS", "lamps held 0"]),
    ("monster x moves", _START + _P1 + ["secs", 3.5, "lamps"],
     ["LAMP POWERLINE LEFT aa00ff blink 150", "LAMP POWERLINE CENTER aa00ff blink 150",
      "Hud_Line: HIT MONSTER X AT POWERLINE C", "Hud_C2_Label: CITIES", "Hud_C2_Label: MONSTER X"]),
    ("shields add time then the clock", _START + ["shot", "Shield target left", "ms", 300] * 4 + ["secs", 40],
     ["Hud_Award: SHIELDS", "WORDS PadMode_final_wars_Hud_C3_Value: 0", "END (time ran out)", "own sound lost",
      "own clip lost", "Hud_Title: THE XILIENS WIN", "lamps held 0"]),
    ("a drain", _START + ["shot", "Left ramp", "secs", 2, "ball_end", "secs", 4],
     ["END (ball ended)", "own clip lost", "lamps held 0"]),
]
