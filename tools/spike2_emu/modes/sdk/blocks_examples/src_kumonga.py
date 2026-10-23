"""KUMONGA (PAD-658): the giant spider of Sollgel Island, deeper and deeper into her web, or cash out.

Son of Godzilla (1967): Kumonga wakes in the valley, webs Minilla and Godzilla in strands and stabs with her
stinger, until Godzilla and Minilla burn her together. On the playfield she clings above the scoop, on the shield
platform's rim, where the Shield ramp spinner turns.

After Lyman Sheats: a meter that costs more each time (Metallica's Sparky), stages with their own rules and shots,
regrowth that pushes back (KING GHIDORAH's heads, TWD's walkers), a hurry-up (EHoH's), a pot to cash out or risk
(Metallica's Crank It Up), and failing still pays a quarter of it.

- LOOP THE WEB: every Big loop counts; 3 light the Big loop (6 the second time, 9 the third), and the next Big loop
  wakes her (PAD-658: no other mode starts on the Big loop; the Shield ramp spinner is SUPER X2's / KIRYU's). Every
  loop a note: SHOOT THE BIG LOOP, n MORE TO WAKE KUMONGA.
- STAGE 1, THE WEB: the shields turn toward the player (Premium/LE); the two outer Shield targets, the centre
  Powerline and both ramps are webbed (purple).
  Each one torn pays 2M and 1M more for each torn before it, to the pot; Kumonga webs one again every pack.WINDOW_S
  (20 s, the same every time; PAD-658 round 3: it was 10 s, then 7 s, then 5 s the more she had been fought). Tear
  all five.
- STAGE 2, STRANDS: the shields turn away; every spinner spin cuts a strand (100K): 60 of them (20 more each time),
  5M to the pot each 10.
- STAGE 3, THE STING: a hurry-up at the Big loop from 20M, 250K a second down to 5M, into the pot.
- STAGE 4, FIRE: the Building (Godzilla's ray) then within pack.WINDOW_S (it was 8 s) the Right ramp (Minilla's): a
  BURN, 10M each to the pot; the third burns her: the pot twice over and 30M.
- CASH OUT at the right scoop after any stage; the clock or a drain pays a quarter of the pot.
- THE CLOCK (PAD-658 round 3): pack.STAGE_S and more: 50 s for THE WEB (five shots that grow back) and FIRE (six
  shots), 45 for STRANDS and THE STING; it was 45 s each.
- SAY THE SHOT (PAD-658 round 3, David: "the shots are not explicit enough"): the title names the stage (KUMONGA:
  THE WEB), the line the shots by the playfield's names: "ANY LIT SHOT: 4 TO GO" while 3 or more webs are left,
  then by name ("SHOOT BOTH RAMPS", "SHOOT THE LEFT SHIELD"); "SPIN ANY SPINNER TO CUT THE STRANDS"; "SHOOT THE BIG
  LOOP"; "SHOOT THE BUILDING, THEN THE RIGHT RAMP" / "NOW SHOOT THE RIGHT RAMP". Every note stays pack.NOTE_S and
  names the next shot where it is known; a web grown back says which. The spinners light their LEFT SPINNER and TOP
  SPINNER inserts by name (the spinner shots have none of their own; the Shield ramp spinner has no light at all).
"""
from itertools import combinations

import blk
from blk import (AND, BALLS, a_show, add, add_time, callout, change, clip, clips, div, end, eq, every, ge, gt,
                 hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, light_mode, lt, mul, off,
                 off_insert, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake, shake_game,
                 shield, show, sound, sounds, step, sub, timer_left, timer_start, timer_stop, var)
import pack

SLUG, NAME = "kumonga", "KUMONGA"
PURPLE, WHITE, AMBER, RED, BLUE = "#b040ff", "#ffffff", "#ffb000", "#ff2000", "#3080ff"
SPIN, START_SHOT = "Shield ramp spinner", "Big loop"
WEBS = (("web l", "Shield target left"), ("web c", "Powerline center"), ("web r", "Shield target right"),
        ("web lr", "Left ramp"), ("web rr", "Right ramp"))
SPINNERS = ("Left spinner", "Top spinner", "Shield ramp spinner")
SPINNER_INSERTS = ("LEFT SPINNER", "TOP SPINNER")   # the spinner shots light no insert of their own
NEED = pack.need(6, "fought")   # 6 Big loops, then 12, then 18 (PAD-675: was 3)
TIMERS = ("tear", "regrow", "next", "burn", "fire", "say")
KX, KY = 251, 302              # her art on the playfield picture, above the scoop
#: each stage's clock and title; her regrowth and FIRE's window (PAD-658 round 3: a window inside a stage)
STAGE_SECS = {1: pack.STAGE_S + 10, 2: pack.STAGE_S + 5, 3: pack.STAGE_S + 5, 4: pack.STAGE_S + 10}
TITLES = {1: "KUMONGA: THE WEB", 2: "KUMONGA: STRANDS", 3: "KUMONGA: THE STING", 4: "KUMONGA: FIRE"}
REGROW_MS = pack.WINDOW_S * 1000
FIRE_MS = pack.WINDOW_S * 1000
POT_SUB = "POT: CASH AT RIGHT SCOOP"        # a stage done: on to the next, or cash out
FIRE_LINE = "SHOOT THE BUILDING, THEN THE RIGHT RAMP"


def award(text, value=None, sub="", seconds=pack.NOTE_S):
    """blk's award, on the glass NOTE_S at least (PAD-658 round 3: notes stay)."""
    return blk.award(text, value=value, sub=sub, seconds=max(seconds, pack.NOTE_S))


def _words(shot):
    return pack.SHOT_WORDS[shot]


def _say_set(shots):
    """The line naming one or two webs still to tear."""
    w = [_words(s) for s in shots]
    if len(w) == 1:
        return "SHOOT THE " + w[0]
    if set(shots) == {"Left ramp", "Right ramp"}:
        return "SHOOT BOTH RAMPS"
    t = "SHOOT THE %s AND %s" % tuple(w)
    return t if len(t) <= 40 else "SHOOT %s AND %s" % tuple(w)


def _now_set(shots):
    """A note's sub naming one or two webs still to tear."""
    w = [_words(s) for s in shots]
    if len(w) == 1:
        return "NOW THE " + w[0]
    t = "NOW %s AND %s" % tuple(w)
    return t if len(t) <= 36 else "NOW %s, %s" % tuple(w)


def stage_line(n, words=None):
    return [hud_title(TITLES[n])] + ([hud_line(words)] if words else []) + [hud_counter(1, n, "OF 4")]


def pot_up(points):
    return [change("pot", points), hud_counter(2, var("pot"), "CASH AT SCOOP")]


def webbed_left():
    return add(add(add(add(var("web l"), var("web c")), var("web r")), var("web lr")), var("web rr"))


LEFT = webbed_left()

SHOWS = [
    a_show("She wakes",
           step("sparkle", 900, PURPLE, "#100020", "xy", gi="dark", x=KX, y=KY),
           step("spiral_out", 1400, PURPLE, "#100020", "xy", gi="dark", x=KX, y=KY),
           step("strobe", 400, WHITE, PURPLE, "center", rate=55, gi="flash"),
           step("fade", 500, PURPLE, "#000000", "center", blend=200)),
    a_show("Web",
           step("spin", 700, WHITE, PURPLE, "xy", rate=70, gi="dark", x=KX, y=KY),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Tear",
           step("burst", 450, WHITE, PURPLE, "center", gi="flash"),
           step("fade", 250, PURPLE, "#000000", "center")),
    a_show("Strands",
           step("sweep_up", 500, WHITE, PURPLE, "center", gi="dark"),
           step("sweep_down", 500, WHITE, PURPLE, "center", gi="dark"),
           step("fade", 300, PURPLE, "#000000", "center")),
    a_show("Sting",
           step("bolts", 900, RED, "#200000", "xy", rate=110, gi="dark", x=KX, y=KY),
           step("implode", 600, RED, PURPLE, "xy", gi="dark", x=KX, y=KY),
           step("fade", 300, RED, "#000000", "center")),
    a_show("Burn",
           step("strobe", 300, WHITE, AMBER, "center", rate=50, gi="flash"),
           step("fire", 1100, "#ffc000", RED, "xy", gi="dark", x=KX, y=KY),
           step("fade", 400, RED, "#000000", "center", blend=150)),
    a_show("Stage up",
           step("strobe", 400, WHITE, PURPLE, "center", rate=55, gi="flash"),
           step("ripple", 1300, PURPLE, "#100020", "center", rate=450, gi="dark"),
           step("rainbow", 1100, "#000000", "#000000", "center", rate=60),
           step("fade", 500, PURPLE, "#000000", "center", blend=200)),
    a_show("She burns",
           step("strobe", 600, WHITE, RED, "center", rate=45, gi="flash"),
           step("fire", 1600, "#ffc000", RED, "xy", gi="dark", x=KX, y=KY),
           step("burst", 900, WHITE, AMBER, "xy", gi="flash", x=KX, y=KY),
           step("rainbow", 1800, "#000000", "#000000", "center", rate=50),
           step("fade", 700, AMBER, "#000000", "center", blend=300)),
    a_show("She leaves",
           step("implode", 1200, PURPLE, "#000000", "xy", gi="dark", x=KX, y=KY),
           step("fade", 900, PURPLE, "#000000", "center", blend=400)),
]


def web_lights():
    return [if_(eq(v, 1), [light(s, PURPLE, "chase", 110)], [off(s)]) for v, s in WEBS]


def web_line():
    """THE WEB's line: how many while 3 or more are webbed (every lit shot counts), then the one or two by name."""
    out = [if_(eq(LEFT, n), [hud_line("ANY LIT SHOT: %d TO GO" % n)]) for n in (3, 4, 5)]
    out.append(if_(eq(LEFT, 0), [hud_line("THE WEB IS TORN")]))
    for k in (1, 2):
        for combo in combinations(WEBS, k):
            out.append(if_(AND(eq(LEFT, k), *[eq(v, 1) for v, _s in combo]),
                           [hud_line(_say_set([s for _v, s in combo]))]))
    return out


def torn_note():
    """A web torn (not the last): how many are left, or the one or two still webbed by name."""
    named = []
    for k in (1, 2):
        for combo in combinations(WEBS, k):
            named.append(if_(AND(eq(LEFT, k), *[eq(v, 1) for v, _s in combo]),
                             [award("WEB TORN", sub=_now_set([s for _v, s in combo]))]))
    return [if_(ge(LEFT, 3), [award("WEB TORN", value=LEFT, sub="MORE TO TEAR")], named)]


def setup_stage():
    return [
        if_(eq("stage", 2), stage_line(2, "SPIN ANY SPINNER TO CUT THE STRANDS") + [
            shield("away"), timer_stop("regrow"), set_time(STAGE_SECS[2]),
            set_("strands", add(60, mul(20, sub(var("fought"), 1)))),
            hud_counter(3, var("strands"), "TO CUT", "STRANDS"),
        ] + [off(s) for _v, s in WEBS] + [light(s, WHITE, "blink", 200) for s in SPINNERS]
          + [light_insert(n, WHITE, "blink", 200) for n in SPINNER_INSERTS]),
        if_(eq("stage", 3), stage_line(3, "SHOOT THE BIG LOOP") + [
            set_("sting", 20000000), hud_counter(3, var("sting"), "INTO THE POT", "STING"), set_time(STAGE_SECS[3]),
        ] + [off(s) for s in SPINNERS] + [off_insert(n) for n in SPINNER_INSERTS]
          + [light(START_SHOT, RED, "hurry")]),
        if_(eq("stage", 4), stage_line(4, FIRE_LINE) + [
            off(START_SHOT), hud_counter(3, 0, "OF 3", "BURNS"), set_time(STAGE_SECS[4]),
            light("Building", AMBER, "blink", 200),
        ]),
    ]


def cut_strand():
    """A spin in STRANDS: one strand cut; a note every 10 (spins come fast: the line stays on the glass between)."""
    return [if_(eq("stage", 2), [
        change("strands", -1), score(100000), hud_counter(3, var("strands"), "TO CUT"), change("cut", 1),
        if_(ge("cut", 10), [set_("cut", 0), *pot_up(5000000), pack.clock_floor(), sound("tear"), show("Strands"),
                            award("STRANDS CUT", value=var("strands"), sub="MORE TO CUT")]),
        if_(le(var("strands"), 0), [award("CUT FREE", value=var("pot"), sub=POT_SUB), clip("strand", "behind"),
                                      timer_start("next", 700)])])]


#: her regrowth: the first torn web (in WEBS' order) webbed again, and the note names it
def _regrow(i=0):
    v, s = WEBS[i]
    grow = [set_(v, 1), award("KUMONGA WEBS AGAIN", value=LEFT, sub="AT THE " + _words(s))]
    return [if_(eq(v, 0), grow, _regrow(i + 1) if i + 1 < len(WEBS) else None)]


SCRIPTS = [
    # ---- loop the web: lit at the Big loop ---------------------------------------------------------------------
    on_shot(START_SHOT, *pack.count_up("loops", 1, NEED, "ready", "note at", START_SHOT, PURPLE, "",
                                  "KUMONGA IS LIT", "SHOOT THE BIG LOOP", "SHOOT THE BIG LOOP", "MORE TO WAKE KUMONGA",
                                  step=1), when="idle"),
    pack.relight("ready", START_SHOT, PURPLE),

    # ---- she wakes -----------------------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("ready", 0), set_("loops", 0), set_("note at", 0), change("fought", 1),
             set_("stage", 1), set_("pot", 0), set_("torn", 0), set_("won", 0), set_("cashed", 0), set_("burns", 0),
             *[set_(v, 1) for v, _s in WEBS],
             timer_start("regrow", REGROW_MS),
             shield("toward"),
             clip("intro", "full"), clip("loop", "loop"), sound("chitter"), show("She wakes"), shake(600, "strong"),
             *stage_line(1),
             hud_counter(2, 0, "CASH AT SCOOP"), hud_counter(3, 5, "TO TEAR", "WEBS"),
             timer_start("say", 1)),
    # THE WEB's lights, count and line: after a start, a tear, a regrowth
    on_timer("say", if_(eq("stage", 1), [*web_lights(), hud_counter(3, LEFT, "TO TEAR"), *web_line()])),

    # ---- stage 1: tear the web -----------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(eq("stage", 1), eq(v, 1)), [set_(v, 0), off(s), timer_start("tear", 1)]))
      for v, s in WEBS if not s.endswith("ramp")],
    on_shot("Left ramp", if_(AND(eq("stage", 1), eq("web lr", 1)), [set_("web lr", 0), off("Left ramp"),
                                                                    timer_start("tear", 1)])),
    on_shot("Right ramp",
            if_(AND(eq("stage", 1), eq("web rr", 1)), [set_("web rr", 0), off("Right ramp"), timer_start("tear", 1)]),
            if_(AND(eq("stage", 4), gt(timer_left("fire"), 0)), [timer_start("burn", 1)])),
    on_timer("tear",
             change("torn", 1), score(500000), pack.clock_floor(),
             *pot_up(add(2000000, mul(1000000, sub(var("torn"), 1)))),
             clip("tear", "behind"), sound("tear"), show("Tear"), shake(250, "medium"), timer_start("say", 1),
             if_(eq(LEFT, 0), [award("THE WEB IS TORN", value=var("pot"), sub=POT_SUB), timer_start("next", 700)],
                 torn_note())),
    on_timer("regrow",
             if_(eq("stage", 1), [
                 if_(lt(LEFT, 5), [*_regrow(), timer_start("say", 1), clip("web", "behind"), sound("web"),
                                   show("Web")]),
                 timer_start("regrow", REGROW_MS)])),

    # ---- stage 2: cut the strands ----------------------------------------------------------------------------------
    *[on_shot(s, *cut_strand()) for s in SPINNERS],

    # ---- stage 3: the sting -----------------------------------------------------------------------------------------
    every(1, if_(AND(eq("stage", 3), gt("sting", 5000000)), [change("sting", -250000),
                                                              hud_counter(3, var("sting"), "INTO THE POT")])),
    on_shot(START_SHOT, if_(eq("stage", 3), [
        *pot_up(var("sting")), score(2000000), pack.clock_floor(), clip("sting", "behind"), sound("sting"),
        show("Sting"), shake(450, "hard"), award("THE STING", value=var("sting"), sub="INTO THE POT"),
        timer_start("next", 700)])),

    # ---- stage 4: fire ----------------------------------------------------------------------------------------------
    on_shot("Building", if_(eq("stage", 4), [
        timer_start("fire", FIRE_MS), score(1000000), pack.clock_floor(), sound("burn"),
        light("Right ramp", AMBER, "chase", 100), hud_line("NOW SHOOT THE RIGHT RAMP"),
        award("GODZILLA FIRES", sub="NOW MINILLA: THE RIGHT RAMP")])),
    on_timer("burn",
             timer_stop("fire"), off("Right ramp"), change("burns", 1), *pot_up(10000000), score(3000000),
             pack.clock_floor(), hud_line(FIRE_LINE),
             hud_counter(3, var("burns"), "OF 3"), clip("burn", "behind"), show("Burn"), shake(500, "hard"),
             if_(ge("burns", 3), [
                 set_("won", 1), score(add(mul(var("pot"), 2), 30000000)),
                 award("KUMONGA BURNS", value=add(mul(var("pot"), 2), 30000000), sub="SUPER JACKPOT", seconds=4),
                 clip("won", "full"), sound("won"), show("She burns"), shake_game("multiball_start"), end()],
                 [award("BURN", value=var("burns"), sub="OF 3: NOW THE BUILDING")])),
    # the window ran out: back to the Building
    on_timer("fire", off("Right ramp"), if_(eq("stage", 4), [hud_line(FIRE_LINE)])),

    # ---- a stage done: on to the next, or cash out -------------------------------------------------------------------
    on_timer("next", if_(eq("cashed", 1), [end()], [
        change("stage", 1), show("Stage up"), shake_game("jackpot"), *pack.cash_out_lit(), *setup_stage()])),
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
        set_("cashed", 1), score(var("pot")), award("CASHED OUT", value=var("pot"), sub="KUMONGA RETREATS", seconds=4),
        clip("cashout", "full"), sound("cashout"), show("She leaves"), timer_start("next", 1500)])),
    # the scoop hurries in the last 10 s once it cashes out (not in THE WEB: nothing to cash yet)
    secs_left(10, callout("ten_seconds"), if_(ge("stage", 2), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])),

    on_end(*pack.finish(), set_("stage", 0), *[timer_stop(t) for t in TIMERS],
           if_(eq("won", 1), [hud_title("KUMONGA BURNS"), hud_line("GODZILLA AND MINILLA WIN")]),
           if_(eq("cashed", 1), [hud_title("KUMONGA RETREATS"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [hud_title("CAUGHT IN THE WEB"), hud_line("A QUARTER OF THE POT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               score(div(var("pot"), 4)),
               award("CAUGHT IN THE WEB", value=div(var("pot"), 4), sub="A QUARTER OF THE POT", seconds=3),
               clip("lost", "full"), sound("lost"), show("She leaves")])),
]


PROGRAM = {
    "name": NAME, "seconds": STAGE_SECS[1], "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("loops", "ready", "note at", "fought")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "pot", "torn", "strands", "cut", "sting",
                                                "burns", "won", "cashed")] + [
        {"name": v, "reset": "mode"} for v, _s in WEBS],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("ANY LIT SHOT: 5 TO GO",
               counters=[("STAGE", "OF 4", None), ("POT", "CASH AT SCOOP", None), ("WEBS", "TO TEAR", None)],
               timer=("KUMONGA", "spider")),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "web", "tear", "strand", "sting", "burn", "won", "lost", "cashout"),
    "sounds": sounds({"chitter": 4, "web": 3, "tear": 3, "sting": 4, "burn": 3, "won": 4, "lost": 4, "cashout": 4}),
    "music": "music.wav",
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 2, "titles": ["godzilla_le", "godzilla_pro"],
    # a Pro's port calls the spinner on the shield ramp the Right spinner; its shields are fixed (no platform to turn)
    "title_shots": {"godzilla_pro": {"Shield ramp spinner": "Right spinner"}}, "based_on": "",
    "about": ("New (PAD-658). Loop the Big loop to wake her there (6 loops, 12, then 18); four stages, each one's shots "
              "named on the line (tear the web on the shield platform while she webs it again, cut the strands on "
              "every spinner, the sting hurry-up, burn her with Godzilla and Minilla); cash the pot out at the right "
              "scoop. Son of Godzilla (1967)."),
    "lost": [],
}


def _shots(name, n, gap=200):
    out = []
    for _i in range(n):
        out += ["shot", name, "ms", gap]
    return out


_START = ["trigger", "kumonga.start", "secs", 1]
_STAGE1 = ["shot", "Shield target left", "ms", 300, "shot", "Powerline center", "ms", 300,
           "shot", "Shield target right", "ms", 300, "shot", "Left ramp", "ms", 300, "shot", "Right ramp", "secs", 1]
_STAGE2 = _shots("Top spinner", 60, 60) + ["secs", 1]
_STAGE3 = ["secs", 4, "shot", "Big loop", "secs", 1]
_STAGE4 = ["shot", "Building", "ms", 500, "shot", "Right ramp", "ms", 500] * 3 + ["secs", 6]
DESK = [
    ("six loops light it, the next one wakes her",
     ["shot", "Big loop", "secs", 1] * 6 + ["shot", "Big loop", "secs", 2],
     ["Hud_Award: SHOOT THE BIG LOOP", "Hud_AwardSub: 5  -  MORE TO WAKE KUMONGA", "Hud_AwardSub: 1  -  MORE TO WAKE KUMONGA",
      "Hud_Award: KUMONGA IS LIT", "[KUMONGA] START (its lit shot)", "SHIELD toward",
      "Hud_Title: KUMONGA: THE WEB", "Hud_Line: ANY LIT SHOT: 5 TO GO"]),
    # her regrowth is a window (20 s): the torn Left ramp webbed again
    ("the web grows back", _START + ["shot", "Left ramp", "secs", pack.WINDOW_S + 3],
     ["Hud_Award: WEB TORN", "Hud_AwardSub: 4  -  MORE TO TEAR", "Hud_Line: ANY LIT SHOT: 4 TO GO",
      "Hud_Award: KUMONGA WEBS AGAIN", "Hud_AwardSub: 5  -  AT THE LEFT RAMP", "LAMP LEFT RAMP b040ff chase",
      "Hud_Line: ANY LIT SHOT: 5 TO GO"]),
    ("all four stages", _START + _STAGE1 + _STAGE2 + _STAGE3 + _STAGE4,
     ["Hud_Line: SHOOT BOTH RAMPS", "Hud_AwardSub: NOW LEFT RAMP AND RIGHT RAMP", "Hud_Line: SHOOT THE RIGHT RAMP",
      "Hud_AwardSub: NOW THE RIGHT RAMP", "Hud_Award: THE WEB IS TORN", "Hud_Title: KUMONGA: STRANDS",
      "Hud_Line: SPIN ANY SPINNER TO CUT THE STRANDS", "Hud_AwardSub: 50  -  MORE TO CUT", "Hud_Award: CUT FREE",
      "Hud_Title: KUMONGA: THE STING", "Hud_Line: SHOOT THE BIG LOOP", "Hud_Award: THE STING", "SHIELD away",
      "Hud_Title: KUMONGA: FIRE", "Hud_Line: SHOOT THE BUILDING, THEN THE RIGHT RAMP",
      "Hud_Line: NOW SHOOT THE RIGHT RAMP", "Hud_AwardSub: 1  -  OF 3: NOW THE BUILDING",
      "Hud_Title: KUMONGA BURNS", "END (a block)", "lamps held 0"]),
    ("cash out after the web", _START + _STAGE1 + ["shot", "Right scoop", "secs", 5],
     ["Hud_Title: KUMONGA RETREATS", "SCORE +20000000", "END (a block)", "lamps held 0"]),
    # the spinners' inserts: the spinner shots light none of their own
    ("the spinners light their inserts", _START + _STAGE1 + ["secs", 5],
     ["LAMP LEFT SPINNER ffffff blink 200", "LAMP TOP SPINNER ffffff blink 200"]),
]


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


#: PAD-658: as a Pro gets it - the spinner on the shield ramp is the Pro's Right spinner, and its shields are fixed
DESK_PRO = [
    ("six loops light it on the Pro", ["shot", "Big loop", "secs", 1] * 6 + ["shot", "Big loop", "secs", 2],
     ["Hud_Award: KUMONGA IS LIT", "[KUMONGA] START (its lit shot)"]),
    ("the web on the fixed shields", _START + _STAGE1 + ["shot", "Right scoop", "secs", 5],
     ["Hud_Title: KUMONGA RETREATS", "SCORE +20000000"]),
]
