"""BIOLLANTE in blocks (PAD-658): the SDK's biollante.c rebuilt, so David can open it in the block editor and change it.

Godzilla vs. Biollante (1989): a rose spliced with Godzilla's cells. Her ROSE form spreads vines and acid sap; cut her
down and she comes back as the BEAST. After Lyman Sheats' switch frenzies (The Walking Dead's Blood Bath: every switch
scores into a jackpot the targets collect) and his generous clocks (a lit shot under 15 s puts it back to 15).

- LIGHT IT: 6 ramp shots (either ramp) in a game start it at once; 8 the next time, then 10.
- THE SAP: a 40 s clock. Every shot scores the switch value (100,000, +25,000 a bank cut) and adds it to the SAP
  JACKPOT.
- THE VINES: the three Shield targets and the three Powerline targets are two banks of vines. A whole bank cut
  COLLECTS the sap jackpot times the banks cut so far (x1, x2, x3), empties it and grows the bank back. A vine cut puts
  a clock under 15 s back to 15; each Pop bumper hit gives a second back (up to 40).
- BEAST FORM: after three collects, 20 s: the Building is the FINAL BLOW, worth everything the collects paid.
- ENDS: the final blow (won); the clock (she withers); a drain; one of the game's own modes.
"""
from blk import (AND, div, NOT, OR, RUNNING, SECS_LEFT, a_show, add, award, change, clip, clips, end, eq, every,
                 game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, light, lt, mul, off, on_any_shot,
                 on_drain, on_end, on_shot, on_start, on_timer, score, set_, set_time, add_time, shield, show, sound,
                 sounds, start, step, sub, timer_start, timer_stop, var)

SLUG, NAME = "biollante", "BIOLLANTE"
ROSE, VINE, DEEP, SPORE, GOLD = "#ff1446", "#14c828", "#00280a", "#ffe678", "#ffaa00"
RAMPS = ("Left ramp", "Right ramp")
BANKS = ((("l1", "Shield target left"), ("l2", "Shield target center"), ("l3", "Shield target right")),
         (("p1", "Powerline left"), ("p2", "Powerline center"), ("p3", "Powerline right")))
FINAL = "Building"
RAMPS_FIRST, RAMPS_STEP = 6, 2
SWITCH_VALUE, SWITCH_STEP = 100000, 25000
RUN_SECONDS, BEAST_SECONDS, FLOOR = 40, 20, 15
BUILDING = dict(x=123, y=202)             # the BUILDING insert, the port's lamp place
TIMERS = ("ramp", "cut", "lamps")
#: the middle counter: the sap jackpot in the rose form (phase 1), the final blow's value in the beast's (phase 2)
C2 = add(mul(var("sap"), sub(2, var("phase"))), mul(var("collected"), sub(var("phase"), 1)))
NEED = add(RAMPS_FIRST, mul(RAMPS_STEP, var("plays")))

SHOWS = [
    a_show("Collect",                                                                    # the sap sprays
           step("sparkle", 700, SPORE, VINE, "center", gi="flash"),
           step("fade", 300, VINE, "#000000", "center")),
    a_show("Beast",
           step("strobe", 500, ROSE, "#000000", "center", rate=60, gi="flash"),
           step("implode", 800, ROSE, DEEP, "xy", gi="dark", **BUILDING),               # the jaws close
           step("fire", 900, VINE, DEEP, "center")),
]


def bank_sum(b):
    (v1, _s1), (v2, _s2), (v3, _s3) = BANKS[b]
    return add(add(var(v1), var(v2)), var(v3))


def lamps():
    """The vines still standing blink green; the beast: the Building gold, faster as her 20 s run down."""
    vines = [(v, s) for bank in BANKS for v, s in bank]
    secs = SECS_LEFT
    return [
        if_(eq("phase", 1), [if_(eq(v, 0), [light(s, VINE, "blink", 500)], [off(s)]) for v, s in vines],
            [off(s) for _v, s in vines]),
        if_(eq("phase", 2), [
            set_("rate", 100), if_(gt(secs, 3), [set_("rate", 200)]),
            if_(gt(mul(secs, 3), BEAST_SECONDS), [set_("rate", 400)]),
            if_(gt(mul(secs, 3), 2 * BEAST_SECONDS), [set_("rate", 700)]),
            light(FINAL, GOLD, "blink", var("rate"))], [off(FINAL)]),
    ]


def collect():
    """A whole bank cut ("bank" 1 the shields, 2 the powerlines): the sap jackpot times the banks cut so far."""
    return [
        change("collects", 1), set_("got", mul(var("sap"), var("collects"))), score(var("got")),
        change("collected", var("got")), set_("sap", 0), change("cut", -3),
        set_("switch", add(SWITCH_VALUE, mul(SWITCH_STEP, var("collects")))),
        *[if_(eq("collects", n), [award("SAP JACKPOT X%d" % n, value=var("got"), seconds=2)]) for n in (1, 2, 3)],
        if_(eq("collects", 1), [hud_counter(2, var("sap"), "X2 AT A BANK")]),
        if_(eq("collects", 2), [hud_counter(2, var("sap"), "X3 AT A BANK")]),
        show("Collect"), sound("collect"), clip("collect", "behind"),
        if_(eq("bank", 1), [set_(v, 0) for v, _s in BANKS[0]], [set_(v, 0) for v, _s in BANKS[1]]),
        if_(ge("collects", 3), [                                                         # the BEAST
            set_("phase", 2), set_time(BEAST_SECONDS), set_("cut", 6),
            hud_title("BIOLLANTE BEAST"), hud_line("FINAL BLOW: SHOOT THE BUILDING"),
            hud_counter(1, var("collects"), "THE BEAST"), hud_counter(2, var("collected"), "BUILDING", label="FINAL BLOW"),
            award("BEAST FORM!", sub="FINAL BLOW: SHOOT THE BUILDING", seconds=3),
            show("Beast"), sound("beast"), clip("beast", "full")]),
    ]


SCRIPTS = [
    # ---- light it: ramp shots -----------------------------------------------------------------------------------
    *[on_shot(r, timer_start("ramp", 1), when="idle") for r in RAMPS],
    on_timer("ramp", if_(NOT(RUNNING), [
        if_(lt("ramps", NEED), [change("ramps", 1)]),
        if_(ge("ramps", NEED), [start()],
            [award("RAMPS TO BIOLLANTE", value=sub(NEED, var("ramps")), sub="THE ROSE IS GROWING")])])),

    # ---- the rose ---------------------------------------------------------------------------------------------------
    on_start(set_("ramps", 0), change("plays", 1),
             set_("phase", 1), set_("won", 0), set_("drained", 0), set_("collects", 0), set_("sap", 0),
             set_("collected", 0), set_("cut", 0), set_("switches", 0), set_("clip ok", 1), set_("switch", SWITCH_VALUE),
             *[set_(v, 0) for bank in BANKS for v, _s in bank],
             shield("toward"), game_show("Playfield wave"), clip("intro", "full"), clip("loop", "loop"),
             award("BIOLLANTE", sub="EVERY SWITCH FEEDS HER SAP", seconds=3),
             timer_start("lamps", 1)),

    # ---- every switch feeds the sap ------------------------------------------------------------------------------
    on_any_shot(score(var("switch")), change("switches", 1), if_(eq("phase", 1), [change("sap", var("switch"))])),
    on_shot("Pop bumper", if_(OR(AND(eq("phase", 1), lt(SECS_LEFT, RUN_SECONDS)),
                                 AND(eq("phase", 2), lt(SECS_LEFT, BEAST_SECONDS))), [add_time(1)])),

    # ---- the vines ----------------------------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(eq("phase", 1), eq(v, 0)), [set_(v, 1), set_("bank", b + 1), timer_start("cut", 1)]))
      for b, bank in enumerate(BANKS) for v, s in bank],
    on_timer("cut",
             change("cut", 1), if_(lt(SECS_LEFT, FLOOR), [set_time(FLOOR)]),
             if_(OR(AND(eq("bank", 1), eq(bank_sum(0), 3)), AND(eq("bank", 2), eq(bank_sum(1), 3))), collect(),
                 [sound("cut"), if_(eq("clip ok", 1), [clip("cut", "behind"), set_("clip ok", 0)])]),
             timer_start("lamps", 1)),
    every(4, set_("clip ok", 1)),                       # a vine's clip every few seconds at most

    # ---- the beast: the final blow -------------------------------------------------------------------------------------
    on_shot(FINAL, if_(eq("phase", 2), [
        set_("won", 1), score(var("collected")), award("FINAL BLOW", value=var("collected"), seconds=3), end()])),
    on_timer("lamps", *lamps()),
    every(1, if_(eq("phase", 2), [timer_start("lamps", 1)])),       # the beast's blink hurries

    # ---- the end ------------------------------------------------------------------------------------------------------
    on_drain(set_("drained", 1)),
    on_end(*[timer_stop(t) for t in TIMERS], set_("phase", 0),
           if_(eq("drained", 0), [if_(eq("won", 1), [sound("won")], [sound("lost", fallback="time_up")])]),
           if_(eq("won", 1), [clip("won", "full"), hud_title("BIOLLANTE IS FREE")],
               [clip("lost", "full"), hud_title("BIOLLANTE WITHERS")]),
           # the banks cut and the switches under it (a number can only come last)
           *[if_(eq("collects", n), [hud_line("%d BANK%s CUT  -  SWITCHES" % (n, "" if n == 1 else "S"),
                                              value=var("switches"))]) for n in range(4)],
           game_show("Red and blue fade")),
]

PROGRAM = {
    "name": NAME, "seconds": RUN_SECONDS, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("ramps", "plays")] + [
        {"name": n, "reset": "mode"} for n in ("phase", "won", "drained", "collects", "sap", "collected", "got",
                                                "switch", "switches", "cut", "bank", "rate", "clip ok")] + [
        {"name": v, "reset": "mode"} for bank in BANKS for v, _s in bank],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SWITCHES FEED THE SAP - CUT A VINE BANK",
               counters=[("BANKS CUT", "VINE BANKS", var("collects")), ("SAP JACKPOT", "X1 AT A BANK", C2),
                         ("PER SWITCH", "THOUSAND SAP", div(var("switch"), 1000))],
               timer=("BIOLLANTE", "rose"),
               gauge={"label": "VINES", "kind": "segment", "count": 6, "color": VINE, "value": var("cut")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "cut", "collect", "beast", "won", "lost"),
    "sounds": sounds({"cut": 3, "collect": 3, "beast": 4, "won": 4, "lost": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 109, "titles": ["godzilla_le"], "based_on": "biollante.c",
    "about": ("The C example BIOLLANTE rebuilt in blocks: six ramps start her, every shot feeds the SAP JACKPOT, "
              "each vine bank cut (the Shield targets, the Powerlines) collects it x1, x2, x3, then her BEAST form "
              "gives 20 s to land the final blow at the Building."),
    "lost": [
        "Only the port's named shots feed the sap: the C scored every playfield switch (its 0x1 switch dispatch), "
        "rollovers and other unnamed switches included.",
        "The counters show bare numbers: BANKS CUT 2 where the C showed 2/3, and PER SWITCH 125 over THOUSAND "
        "SAP where it showed 125K over SAP (an edge counter holds about four characters).",
        "The gauge stays one vine green labelled VINES: the C shaded its six pips from green to rose and relabelled "
        "it BEAST in the beast form.",
        "The ramp count note reads RAMPS TO BIOLLANTE 5 (the number after the words) where the C said 5 RAMPS TO "
        "BIOLLANTE.",
        "The shield vines light at once: the C lit them only once the shield platform had turned to face the "
        "player.",
        "A vine's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C "
        "waited 4 s from the last one it played.",
        "The ending's line puts the switches last (2 BANKS CUT  -  SWITCHES 14) where the C said 14 SWITCHES  -  "
        "2 BANKS CUT, and its SWITCHES are the named shots made (the C counted every switch).",
        "The ending (BIOLLANTE IS FREE or BIOLLANTE WITHERS, its line and the total) stays up 3 s, the runtime's: "
        "the C kept it 10 s.",
        "No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks "
        "count every report.",
        "A hit no longer answers by itself: the C flashed every scoring shot's inserts white and played the game's "
        "climbing orchestra hit (PAD-415).",
        "Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does "
        "for a drain or a tilt).",
        "Its own start, win and end light shows are gone: the C used them only on a game without the game's "
        "Playfield wave and Red and blue fade, which Godzilla Premium/LE has.",
        "For Godzilla Premium/LE only: the C also ran on Godzilla Pro, where its shield bank is two targets.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


def _shots(name, n, gap=300):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", gap]
    return out


_START = ["trigger", "biollante.start", "secs", 1]
_SHIELDS = ["shot", "Shield target left", "ms", 300, "shot", "Shield target center", "ms", 300,
            "shot", "Shield target right", "secs", 1]
_POWER = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300,
          "shot", "Powerline right", "secs", 1]
#: two slingshots and the shield vines (5 x 100K: x1 500K), a slingshot and the powerlines (4 x 125K: x2 1M), the
#: shields again (3 x 150K: x3 1.35M) - the beast
_BANKS = _shots("Slingshot", 2) + _SHIELDS + _shots("Slingshot", 1) + _POWER + _SHIELDS
DESK = [
    ("six ramps then eight", _shots("Left ramp", 6) + ["secs", 1, "trigger", "biollante.stop", "secs", 4] +
     _shots("Right ramp", 7) + ["secs", 2] + _shots("Right ramp", 1) + ["secs", 2],
     ["Hud_Award: RAMPS TO BIOLLANTE 5", "[BIOLLANTE] START (a block)", "Hud_Award: RAMPS TO BIOLLANTE 7",
      "Hud_Award: RAMPS TO BIOLLANTE 1", "SHIELD toward"]),
    ("three banks, the beast and the final blow", _START + _BANKS + ["secs", 3, "shot", "Building", "secs", 6],
     ["SCORE +500000", "Hud_Award: SAP JACKPOT X2 1,000,000", "SCORE +1350000", "Hud_Title: BIOLLANTE BEAST", "Hud_C2_Label: FINAL BLOW",
      "Hud_Award: BEAST FORM!", "LAMP BUILDING ffaa00 blink 700", "SCORE +2850000", "END (a block)",
      "Hud_Title: BIOLLANTE IS FREE", "Hud_Line: 3 BANKS CUT  -  SWITCHES 13", "lamps held 0"]),
    ("the beast's clock runs out", _START + _BANKS + ["secs", 22],
     ["Hud_Line: FINAL BLOW: SHOOT THE BUILDING", "LAMP BUILDING ffaa00 blink 100", "END (time ran out)",
      "lamps held 0"]),
    ("she withers on the clock", _START + ["shot", "Shield target left", "secs", 45],
     ["SCORE +100000", "Hud_C2_Value: 100,000", "Hud_C3_Value: 100", "END (time ran out)",
      "Hud_Title: BIOLLANTE WITHERS", "Hud_Line: 0 BANKS CUT  -  SWITCHES 1", "lamps held 0"]),
    ("a vine puts a short clock back to fifteen", _START + ["secs", 30, "shot", "Shield target left", "secs", 12],
     ["SCORE +100000", "END lamps held 5"]),           # still running at 43 s: the clock went back to 15
    ("the pop bumper gives seconds back", _START + ["secs", 30] + _shots("Pop bumper", 5, 100) + ["secs", 12],
     ["SCORE +100000", "END lamps held 6"]),           # 10 s left + 5 pops: still running at 43.5 s
    ("a drain ends it", _START + _shots("Slingshot", 3) + ["ball_end", "secs", 8],
     ["END (ball ended)", "lamps held 0"]),
]
