"""ANGUIRUS (PAD-658): the SDK's C example anguirus_assist.c rebuilt in blocks and taken deeper: Godzilla's oldest
ally comes, charges his spikes, rolls, bites, and calls the allies in; or he goes home with the pot. PAD-675 (David:
"make sure that all modes are run in isolation"): he no longer joins the game's own battle - he is a mode of his own,
held off by the game's modes and holding them off, on a clock.

Destroy All Monsters (1968): at Mt. Fuji Anguirus charges King Ghidorah, clamps his jaws on a neck, and with Godzilla
and the others pins the three heads down; afterwards he is home on Monsterland. Godzilla: Final Wars (2004): he rolls
into battle as a ball of spikes. On the playfield he is the ANGUIRUS insert, among the allies the scoop summons.

After Lyman Sheats: a call that costs more each time (Metallica's Sparky), stages with their own shots, a grip that
slips when left alone (KING GHIDORAH's heads), a hurry-up finale, a pot you cash out or put at risk.

- THE CALL: Shield target hits while no mode runs call him: 8 the first time, 16 the second, 24 the third (a note
  on every hit says how many are left); the last one starts him. Held off (one of the game's modes or multiballs),
  the next shield hit once it is over starts him. 90 s on his clock.
- STAGE 1, SPIKES: each Shield target (left, center, right) charges one spike: 500,000, and 1M to the pot. A spike
  to charge blinks orange; a charged one goes dark (it no longer counts) and the SPIKES gauge fills.
- STAGE 2, ROLLING ATTACK: the Big loop chases cyan: 4,000,000 (and as much to the pot); each Big loop within 20 s
  of the last doubles it (8M, then 16M, the most). The window runs out: charge the spikes again. Three rolls.
- STAGE 3, THE BITE: one ramp chases amber: a bite, 2M and 8M, 12M, 16M to the pot; the other ramp is next. Left
  alone 20 s he is shaken off: one bite lost. Three bites.
- STAGE 4, ALLIES ATTACK: the Building, a hurry-up from 30M down 1M a second to 10M: the pot twice over and the
  hurry-up. He has won.
- CASH OUT: after any stage the right scoop chases white: the pot, and he goes home. His clock running out or a
  drain pays a quarter of the pot.

SAY THE SHOT (PAD-658 round 3, David: "the shots are not explicit enough and some of the information only flashes on
the screen very briefly"; "you can't really accomplish much in 10 seconds. 40 seconds is better"). His title and line take
the award line between his awards, so:
- his TITLE says the stage's count (CHARGE HIS SPIKES, 3 ROLLS TO GO, 2 BITES TO GO, ALLIES ATTACK) and his LINE the
  shot by the playfield's names (HIT THE CENTER AND RIGHT SHIELDS, SHOOT THE BIG LOOP, SHOOT THE RIGHT RAMP, SHOOT
  THE BUILDING: 24,000,000); the "say" timer writes both whenever something changes;
- a note's sub names what next (SPIKE CHARGED / HIT THE LEFT AND RIGHT SHIELDS; BITE / NOW THE RIGHT RAMP; BIG LOOP
  AGAIN TO DOUBLE), every note stays 3 s at least (pack.NOTE_S), a stage waits out the note before it, and the
  hurry-up's value is in his line, not a note every second;
- the roll's window and his grip are pack.WINDOW_S (were 6 and 12 s, 1 and 2 s shorter each time he joined); the
  Big loop blinks fast in the window's last 5 s;
- what is lit counts: a charged spike goes dark, the ramp he has let go of goes dark after the last bite, the scoop
  stops chasing once he has won.
"""
from blk import (AND, OR, BALLS, NOT, RUNNING, STOCK, a_show, add, award, change, clip, clips, div, end, eq, every,
                 ge, gt, hud, hud_line, hud_title, if_, le, light, light_insert, lt, mul, off, on_any_shot, on_end,
                 on_shot, on_start, on_timer, score, set_, shake, shake_game, show, sound, sounds, start, step, sub,
                 timer_left, timer_start, timer_stop, var, beds, music)
import pack

SLUG, NAME = "anguirus_assist", "ANGUIRUS"
AMBER, EMBER, ORANGE, CYAN, WHITE, RED, GOLD = "#ff6e00", "#501900", "#ff5000", "#00e6ff", "#ffffff", "#ff1400", "#ffb000"
ROLL_SHOT = "Big loop"
SPIKES = (("spike l", "Shield target left"), ("spike c", "Shield target center"), ("spike r", "Shield target right"))
SIDE = {"spike l": "LEFT", "spike c": "CENTER", "spike r": "RIGHT"}
RAMPS = ("Left ramp", "Right ramp")
ROLLS, BITES = 3, 3
AX, AY = 186, 439                     # the ANGUIRUS insert (the allies the scoop summons): his place on the playfield
SX, SY = 199, 346                     # the SHIELD CENTER insert's place: the C's KIT_AT_SHIELDS
BX, BY = 123, 202                     # the BUILDING
TIMERS = ("enter", "roll", "charged", "next", "grip", "bite", "say")
#: the call: 8 shield hits the first time, 16 the second, 24 the third
NEED = pack.need(8, "joins")          # PAD-675: was 3
#: a note's time on the glass: the next stage waits it out (a stage's last note is up a second longer, so his title and
#: line, which take the award line between notes, do not flash up between it and the next stage's note)
NOTE_MS = pack.NOTE_S * 1000
WINDOW_MS = pack.WINDOW_S * 1000      # the roll's window, his grip
HURRY_BLINK_MS = 5000                 # the Big loop blinks fast in the window's last 5 s
W = pack.SHOT_WORDS


def charged():
    return add(add(var("spike l"), var("spike c")), var("spike r"))


def shields(sides):
    """The words for the shields still to charge: HIT THE LEFT, CENTER AND RIGHT SHIELDS; HIT THE LEFT AND RIGHT
    SHIELDS; HIT THE CENTER SHIELD."""
    if len(sides) == 3:
        return "HIT THE %s, %s AND %s SHIELDS" % tuple(sides)
    if len(sides) == 2:
        return "HIT THE %s AND %s SHIELDS" % tuple(sides)
    return "HIT THE %s SHIELD" % sides[0]


ALL_SHIELDS = shields([SIDE[v] for v, _s in SPIKES])


def spike_words(note=False):
    """The line naming the spikes still to charge (one leaf per set of them), and with ``note`` a spike's note whose
    sub names them too."""
    def tree(i, left):
        if i == len(SPIKES):
            if not left:
                return []
            out = [hud_line(shields(left))]
            if note:
                out.append(award("SPIKE CHARGED", sub=shields(left), seconds=pack.NOTE_S))
            return out
        v = SPIKES[i][0]
        return [if_(eq(v, 0), tree(i + 1, left + [SIDE[v]]), tree(i + 1, left))]
    return tree(0, [])


def count_title(name, need, word):
    """The title says what is left of the stage: 3 ROLLS TO GO, 2 ROLLS TO GO, 1 ROLL TO GO."""
    return [if_(eq(name, n), [hud_title("%d %s%s TO GO" % (need - n, word, "S" if need - n > 1 else ""))])
            for n in range(need)]


SHOWS = [
    a_show("He enters",
           step("fade_in", 600, AMBER, "#000000", "xy", gi="dark", x=AX, y=AY),
           step("burst", 700, WHITE, AMBER, "xy", gi="flash", x=AX, y=AY),
           step("spin", 1400, AMBER, EMBER, "xy", rate=90, x=SX, y=SY),
           step("fade", 400, AMBER, "#000000", "center")),
    a_show("Spike",
           step("implode", 500, ORANGE, "#000000", "xy", gi="dark", x=SX, y=SY),
           step("pulse", 400, ORANGE, EMBER, "xy", rate=200, x=SX, y=SY)),
    a_show("Charged",
           step("strobe", 300, WHITE, ORANGE, "center", rate=55, gi="flash"),
           step("spiral_out", 1100, ORANGE, EMBER, "xy", gi="dark", x=SX, y=SY),
           step("sweep_up", 600, CYAN, "#000000", "center", gi="dark"),
           step("fade", 400, CYAN, "#000000", "center", blend=150)),
    a_show("Rolling attack",
           step("chase", 900, CYAN, "#000000", "center", rate=40),
           step("bounce", 700, WHITE, CYAN, "center", rate=120, gi="dark"),
           step("burst", 500, WHITE, CYAN, "top", gi="flash")),
    a_show("The bite",
           step("sweep_lr", 400, GOLD, "#000000", "top", gi="dark"),
           step("bolts", 600, WHITE, GOLD, "top", rate=110, gi="flash"),
           step("fade", 300, GOLD, "#000000", "center")),
    a_show("Shaken off",
           step("sweep_down", 600, EMBER, "#000000", "top", gi="dark"),
           step("fade", 400, EMBER, "#000000", "center")),
    a_show("Allies attack",
           step("strobe", 400, WHITE, RED, "center", rate=50, gi="flash"),
           step("ripple", 1200, RED, AMBER, "xy", rate=350, gi="dark", x=BX, y=BY),
           step("spiral_in", 900, AMBER, "#000000", "xy", gi="dark", x=BX, y=BY),
           step("fire", 900, GOLD, RED, "top", gi="dark")),
    a_show("Triumph",
           step("burst", 800, WHITE, AMBER, "xy", gi="flash", x=BX, y=BY),
           step("rainbow", 1800, "#000000", "#000000", "xy", rate=60, x=AX, y=AY),
           step("sparkle", 1200, GOLD, EMBER, "center"),
           step("fade", 600, AMBER, "#000000", "center", blend=300)),
    a_show("Going home",
           step("solid", 500, AMBER, "#000000", "xy", gi="dark", x=AX, y=AY),
           step("sweep_rl", 700, AMBER, "#000000", "center", gi="dark"),
           step("implode", 1100, AMBER, "#000000", "xy", gi="dark", x=AX, y=AY),
           step("fade", 800, AMBER, "#000000", "xy", gi="keep", blend=400, x=AX, y=AY)),
    a_show("Embers",
           step("sparkle", 900, AMBER, EMBER, "center", gi="dark"),
           step("fade", 800, EMBER, "#000000", "center")),
]


def shield_lights():
    """The spikes still to charge blink orange; a charged one is dark (it no longer counts: the gauge says it)."""
    return [if_(eq(v, 1), [off(s)], [light(s, ORANGE, "blink", 400)]) for v, s in SPIKES]


def pot_up(points):
    return [change("pot", points)]


def bite_lights():
    """The ramp to bite chases amber; the other one is the game's ("bite at" 0: neither, the bites are done)."""
    return [if_(eq("bite at", i), [light(s, GOLD, "chase", 90)], [off(s)]) for i, s in enumerate(RAMPS, 1)]


def roll_lit():
    """The spikes charged: the Big loop chases cyan for the window."""
    return [set_("rolling", 1), set_("roll value", 4000000), timer_start("roll", WINDOW_MS),
            light(ROLL_SHOT, CYAN, "chase", 90), clip("spike", "full"),
            award("ROLLING ATTACK LIT", sub=pack.shoot(ROLL_SHOT), seconds=pack.NOTE_S)]


def setup_stage():
    """What each stage lights and says as it begins (the "next" timer, once the stage before is done)."""
    return [
        if_(eq("stage", 2), [*roll_lit(), show("Charged")]),
        if_(eq("stage", 3), [
            set_("rolling", 0), timer_stop("roll"), off(ROLL_SHOT), set_("bite at", 1),
            *[set_(v, 1) for v, _s in SPIKES], *[off(s) for _v, s in SPIKES],
            timer_start("grip", WINDOW_MS), *bite_lights(), show("The bite"),
            award("THE BITE", sub=pack.shoot(RAMPS[0]), seconds=pack.NOTE_S)]),
        if_(eq("stage", 4), [
            timer_stop("grip"), *[off(s) for s in RAMPS], set_("hurry", 30000000),
            light("Building", RED, "chase", 70), clip("allies", "full"), sound("won"), music("allies"),
            show("Allies attack"),
            award("ALLIES ATTACK", value=var("hurry"), sub="SHOOT THE BUILDING", seconds=pack.NOTE_S)]),
    ]


def say():
    """His title (the stage's count) and line (the shot), in the award line between his awards."""
    return [
        if_(eq("stage", 1), [hud_title("CHARGE HIS SPIKES")]),
        if_(OR(eq("stage", 1), AND(eq("stage", 2), eq("rolling", 0))), spike_words()),
        if_(eq("stage", 2), [*count_title("rolls", ROLLS, "ROLL"),
                             if_(eq("rolling", 1), [hud_line(pack.shoot(ROLL_SHOT))])]),
        if_(eq("stage", 3), [*count_title("bites", BITES, "BITE"), *pack.line_follows("bite at", RAMPS)]),
        if_(eq("stage", 4), [hud_title("ALLIES ATTACK"), hud_line("SHOOT THE BUILDING:", value=var("hurry"))]),
    ]


SCRIPTS = [
    # ---- the call: shield hits while he is away; ready, he joins the game's own mode ---------------------------------
    *[on_shot(s, if_(AND(lt(BALLS, 2), eq("ready", 0)), [
        change("calls", 1),
        if_(ge("calls", NEED), [set_("ready", 1), start()], [
            award("SHIELD HITS", value=sub(NEED, var("calls")), sub="MORE TO CALL ANGUIRUS", seconds=pack.NOTE_S)])],
        [if_(eq("ready", 1), [start()])]),                 # held off: the next shield hit starts him
        when="idle") for _v, s in SPIKES],

    # ---- he joins ----------------------------------------------------------------------------------------------------------
    on_start(set_("ready", 0), set_("calls", 0), change("joins", 1),
             set_("stage", 1), set_("pot", 0), set_("rolling", 0), set_("rolls", 0), set_("entered", 0),
             set_("bites", 0), set_("won", 0), set_("cashed", 0),
             *[set_(v, 0) for v, _s in SPIKES],
             *shield_lights(), light_insert("ANGUIRUS", AMBER, "pulse", 700),
             timer_start("enter", 2000), timer_start("say", 1)),
    # his entrance, once the game's own start screen has had its moment
    on_timer("enter", if_(RUNNING, [
        set_("entered", 1), clip("intro", "full"), show("He enters"), shake(600, "strong"),
        award("ANGUIRUS JOINS", sub="SHIELDS CHARGE HIS SPIKES", seconds=pack.NOTE_S)])),
    on_timer("say", *say()),

    # ---- stage 1 (and the recharge in stage 2): the spikes ---------------------------------------------------------------
    *[on_shot(s, if_(AND(le("stage", 2), eq("rolling", 0), eq(v, 0)), [
        set_(v, 1), score(500000), *pot_up(1000000), sound("spike"), off(s), show("Spike"),
        shake(200, "soft"), timer_start("charged", 1)]))
      for v, s in SPIKES],
    on_timer("charged",
             if_(ge(charged(), 3), [
                 if_(eq("stage", 1), [award("SPIKES CHARGED", value=var("pot"), sub="THE POT", seconds=pack.NOTE_S + 1),
                                      timer_start("next", NOTE_MS)],
                     roll_lit())],                     # stage 2: charged again, he rolls again
                 [if_(eq("entered", 1), spike_words(note=True))]),
             timer_start("say", 1)),

    # ---- stage 2: roll ---------------------------------------------------------------------------------------------------
    on_shot(ROLL_SHOT, if_(AND(eq("stage", 2), eq("rolling", 1)), [
        score(var("roll value")), *pot_up(var("roll value")), change("rolls", 1), sound("roll"), clip("roll", "full"),
        show("Rolling attack"), shake(400, "hard"),
        if_(ge("rolls", ROLLS), [
            award("THREE ROLLS", value=var("pot"), sub="THE POT", seconds=pack.NOTE_S + 1), timer_stop("roll"),
            set_("rolling", 0), off(ROLL_SHOT), timer_start("next", NOTE_MS)], [
            award("ROLLING ATTACK", value=var("roll value"), sub="BIG LOOP AGAIN TO DOUBLE", seconds=pack.NOTE_S),
            set_("roll value", mul(var("roll value"), 2)),
            if_(gt("roll value", 16000000), [set_("roll value", 16000000)]),
            timer_start("roll", WINDOW_MS), light(ROLL_SHOT, CYAN, "chase", 90)]),
        timer_start("say", 1)])),
    on_timer("roll", if_(AND(eq("stage", 2), eq("rolling", 1)), [
        set_("rolling", 0), *[set_(v, 0) for v, _s in SPIKES], off(ROLL_SHOT), *shield_lights(),
        award("CHARGE THE SPIKES", sub=ALL_SHIELDS, seconds=pack.NOTE_S), timer_start("say", 1)])),

    # ---- stage 3: the bite --------------------------------------------------------------------------------------------------
    on_shot("Left ramp", if_(AND(eq("stage", 3), eq("bite at", 1)), [timer_start("bite", 1)])),
    on_shot("Right ramp", if_(AND(eq("stage", 3), eq("bite at", 2)), [timer_start("bite", 1)])),
    on_timer("bite",
             change("bites", 1), score(2000000), *pot_up(add(4000000, mul(4000000, var("bites")))),
             set_("bite at", sub(3, var("bite at"))), timer_start("grip", WINDOW_MS),
             clip("bite", "full"), sound("roll"), show("The bite"), shake(350, "strong"),
             if_(ge("bites", BITES), [
                 set_("bite at", 0), timer_stop("grip"),
                 award("THE NECK IS PINNED", value=var("pot"), sub="THE POT", seconds=pack.NOTE_S + 1),
                 timer_start("next", NOTE_MS)],
                 [if_(eq("bite at", i), [award("BITE", value=add(4000000, mul(4000000, var("bites"))),
                                               sub="NOW THE %s" % W[s], seconds=pack.NOTE_S)])
                  for i, s in enumerate(RAMPS, 1)]),
             *bite_lights(), timer_start("say", 1)),
    on_timer("grip", if_(eq("stage", 3), [
        if_(gt("bites", 0), [change("bites", -1)]), sound("spike"), show("Shaken off"), shake(300, "medium"),
        award("SHAKEN OFF", value=var("bites"), sub="BITES HELD", seconds=pack.NOTE_S),
        timer_start("grip", WINDOW_MS), timer_start("say", 1)])),

    # ---- stage 4: allies attack, a hurry-up at the Building ---------------------------------------------------------------
    on_shot("Building", if_(AND(eq("stage", 4), eq("won", 0)), [
        set_("won", 1), score(add(mul(var("pot"), 2), var("hurry"))), off("Building"), *pack.cash_out_off(),
        award("ANGUIRUS TRIUMPHS", value=add(mul(var("pot"), 2), var("hurry")), sub="THE POT TWICE", seconds=4),
        sound("won"), show("Triumph"), shake_game("multiball_start"), timer_start("next", 2500)])),

    # ---- a stage done: on to the next ------------------------------------------------------------------------------------------
    # (his awards stay up a moment before the end: while the battle runs the runtime's TOTAL is his only title)
    on_timer("next", if_(OR(eq("cashed", 1), eq("won", 1)), [end()], [
        change("stage", 1), shake_game("jackpot"), *pack.cash_out_lit(), *setup_stage(), timer_start("say", 1)])),
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
        set_("cashed", 1), score(var("pot")), *pack.cash_out_off(),
        award("ANGUIRUS GOES HOME", value=var("pot"), sub="CASHED OUT", seconds=4),
        clip("cashout", "full"), sound("cashout"), show("Going home"), shake(600, "medium"),
        timer_start("next", 1500)])),

    # ---- every second: the roll's chase quickens, the hurry-up falls; the game's mode over, he leaves with it ------------------
    every(1,
          if_(AND(eq("stage", 2), eq("rolling", 1)), [
              if_(le(timer_left("roll"), HURRY_BLINK_MS), [light(ROLL_SHOT, CYAN, "blink", 100)])]),
          if_(AND(eq("stage", 4), eq("won", 0)), [
              if_(gt("hurry", 10000000), [change("hurry", -1000000)]), timer_start("say", 1)])),

    # the ending: the runtime's TOTAL shows his points under the title that says how it ended
    on_end(*[timer_stop(t) for t in TIMERS], set_("rolling", 0), set_("stage", 0),
           if_(eq("won", 1), [hud_title("ANGUIRUS TRIUMPHS"), hud_line("THE POT TWICE AND THE HURRY-UP"),
                              clip("won", "full")]),
           if_(eq("cashed", 1), [hud_title("ANGUIRUS GOES HOME"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               score(div(var("pot"), 4)), hud_title("ANGUIRUS FALLS"), hud_line("A QUARTER OF THE POT"),
               clip("lost", "full"), show("Embers"), shake(800, "soft")])),
]

PROGRAM = {
    "name": NAME, "seconds": 90, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "game"} for n in ("ready", "calls", "joins")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "pot", "rolling", "roll value", "rolls", "entered", "bites",
                                                "bite at", "hurry", "won", "cashed")] + [
        {"name": v, "reset": "mode"} for v, _s in SPIKES],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud(" ", counters=[], timer=("ANGUIRUS", "radiation"),
               gauge={"label": "SPIKES", "kind": "spike", "count": 3, "color": "#ff7800", "value": charged()}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "spike", "roll", "won", "lost", "bite", "allies", "cashout"),
    "sounds": sounds({"spike": 3, "roll": 3, "won": 4, "cashout": 4}),
    "music": "music.wav",
    "beds": beds("allies"),
    "shows": SHOWS,
}


def _pro_words():
    """The words that name the center shield, as a Pro (whose Maser target is the third spike) should letter them
    (BM.adapt rewords whole strings with title_alt's "words")."""
    out = {}

    def pro(sides):
        shields_left = [s for s in sides if s != "CENTER"]
        if "CENTER" not in sides:
            return shields(sides)
        if not shields_left:
            return "HIT THE MASER TARGET"
        if len(shields_left) == 2:
            return "HIT THE SHIELDS AND THE MASER TARGET"
        return ("HIT THE %s SHIELD AND MASER TARGET" % shields_left[0] if shields_left[0] == "LEFT"
                else "HIT THE MASER TARGET AND %s SHIELD" % shields_left[0])
    sides = [SIDE[v] for v, _s in SPIKES]
    for n in range(1, len(sides) + 1):
        for i in range(len(sides)):
            pick = sides[i:i + n]
            if len(pick) == n and "CENTER" in pick:
                out[shields(pick)] = pro(pick)
    out["SHIELD HITS"] = "SHIELD OR MASER HITS"
    out["SHIELDS CHARGE HIS SPIKES"] = "SHIELDS AND MASER CHARGE HIS SPIKES"
    return out


EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 105, "titles": ["godzilla_le", "godzilla_pro"],
    "based_on": "anguirus_assist.c",
    # the Pro has two shields (left, right): its Maser target is the third spike, so the call and the charge play the
    # same (three different targets to charge, all on the way up the left and right)
    "title_alt": {"godzilla_pro": {"shots": {"Shield target center": "Maser target"}, "words": _pro_words()}},
    "about": ("The C example ANGUIRUS rebuilt in blocks and taken deeper: shield hits call him (8, then 16, then 24), a "
              "mode of his own for 90 s; four stages (charge the spikes at the shields, three rolling attacks "
              "at the Big loop, 20 s apart at most, three bites at the chasing ramp, the allies' hurry-up at the "
              "Building), his title saying what is left and his line the shot; cash the pot out at the right scoop "
              "after any stage. Destroy All Monsters (1968) and Final Wars (2004)."),
    "lost": [
        "PAD-675: he is a mode of his own, held off by the game's modes and holding them off, 90 s on his clock; the "
        "C joined the game's kaiju battles and left with them (half the pot).",
        "The SPIKES gauge keeps its label: the C relabelled it ROLLING! while he rolls; from THE BITE on it stays "
        "full. A charged spike's shield goes dark (it no longer counts; the gauge shows the charge), where the C "
        "lit it solid.",
        "The roll's window is 20 s, the same each time he joins (PAD-658: a window inside a stage is 20 s at "
        "least), where the C's was 6 s.",
        "The Big loop's chase turns to a fast blink in the window's last 5 s (looked at once a second), where the C "
        "stepped its blink every tick.",
        "On Godzilla Pro 1.16 the Maser target stands in for the center shield (a third spike to charge): the C "
        "charged with two spikes on the Pro's two shields; its lines name the Maser target there (title_alt words).",
        "The C's total gave way at once when another of our modes asked to start; the blocks' runtime TOTAL runs "
        "its 3 s.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


_SH = ["shot", "Shield target left", "ms", 400]
#: PAD-675: eight shield hits call him, and the eighth starts him; his entrance 2 s on
_CALL3 = _SH * 8 + ["secs", 3]
_JOIN = []
#: the three spikes, then the 3 s SPIKES CHARGED holds the glass before the rolling attack is lit
_CHARGE = ["shot", "Shield target left", "ms", 400, "shot", "Shield target center", "ms", 400,
           "shot", "Shield target right", "secs", 4]
_ROLLS = ["shot", "Big loop", "secs", 2] * 3 + ["secs", 2]
_BITES = ["shot", "Left ramp", "secs", 1, "shot", "Right ramp", "secs", 1, "shot", "Left ramp", "secs", 2]
DESK = [
    ("eight shield hits call him, sixteen the second time",
     _CALL3 + ["ball_end", "secs", 8] + _SH * 15 + ["secs", 1] + _SH + ["secs", 3],
     ["Hud_Line: 1  -  MORE TO CALL ANGUIRUS", "[ANGUIRUS] START", "END (ball ended)",
      "Hud_Line: 15  -  MORE TO CALL ANGUIRUS", "Hud_Line: 1  -  MORE TO CALL ANGUIRUS"]),
    ("the spikes: his title, his line and the shields", _CALL3 + _JOIN + ["lamps", "shot", "Shield target left", "secs", 4],
     ["Hud_Award: ANGUIRUS JOINS", "Hud_Title: CHARGE HIS SPIKES",
      "Hud_Line: HIT THE LEFT, CENTER AND RIGHT SHIELDS", "HELD SHIELD LEFT ff5000 blink 400",
      "LAMP OFF SHIELD LEFT", "Hud_Award: SPIKE CHARGED", "Hud_AwardSub: HIT THE CENTER AND RIGHT SHIELDS"]),
    ("all four stages and the allies win", _CALL3 + _JOIN + _CHARGE + ["lamps", "secs", 3] + _ROLLS +
     ["secs", 3] + _BITES + ["secs", 7, "shot", "Building", "secs", 6],
     ["Hud_Award: ANGUIRUS JOINS", "Hud_Award: SPIKES CHARGED",
      "Hud_Award: ROLLING ATTACK LIT", "Hud_AwardSub: SHOOT THE BIG LOOP", "Hud_Title: 3 ROLLS TO GO",
      "SCORE +4000000", "Hud_AwardSub: 4,000,000  -  BIG LOOP AGAIN TO DOUBLE", "SCORE +8000000", "SCORE +16000000",
      "Hud_Award: THE BITE", "Hud_AwardSub: SHOOT THE LEFT RAMP", "LAMP LEFT RAMP ffb000 chase 90",
      "Hud_Title: 3 BITES TO GO",
      "Hud_AwardSub: 8,000,000  -  NOW THE RIGHT RAMP", "Hud_Award: THE NECK IS PINNED",
      "Hud_Award: ALLIES ATTACK", "Hud_AwardSub: 30,000,000  -  SHOOT THE BUILDING",
      "Hud_Line: SHOOT THE BUILDING: 27,000,000", "Hud_Award: ANGUIRUS TRIUMPHS", "SCORE +158000000",
      "own clip won", "END (a block)", "lamps held 0"]),
    ("the roll runs out, then cash out", _CALL3 + _JOIN + _CHARGE + ["secs", 16, "lamps", "secs", 6, "lamps",
                                                                     "shot", "Right scoop", "secs", 4],
     ["LAMP BIG LOOP 00e6ff blink 100", "Hud_Award: CHARGE THE SPIKES",
      "Hud_AwardSub: HIT THE LEFT, CENTER AND RIGHT SHIELDS", "LAMP OFF BIG LOOP",
      "LAMP SELECT CITY ffffff chase", "Hud_Award: ANGUIRUS GOES HOME", "SCORE +3000000", "own clip cashout",
      "END (a block)", "lamps held 0"]),
    ("shaken off in the bite", _CALL3 + _JOIN + _CHARGE + _ROLLS + ["shot", "Left ramp", "secs", 25],
     ["Hud_Award: BITE", "Hud_Title: 2 BITES TO GO", "Hud_Line: SHOOT THE RIGHT RAMP", "Hud_Award: SHAKEN OFF",
      "Hud_AwardSub: 0  -  BITES HELD", "Hud_Title: 3 BITES TO GO"]),
    ("his clock runs out: a quarter of the pot", _CALL3 + _CHARGE + ["secs", 90],
     ["END (time ran out)", "Hud_Title: ANGUIRUS FALLS", "SCORE +750000", "lamps held 0"]),
    # PAD-680: the seventh hit, in the battle, still counts; its note waits for the middle and shows as the battle
    # ends; the eighth, after it, calls him
    ("a battle holds his start off: he counts through it",
     _SH * 6 + ["battle", 1, "secs", 1] + _SH + ["secs", 1, "battle", 0, "secs", 1] + _SH + ["secs", 3],
     ["its note waits for the game's mode to give the middle back", "its note shows - the game's mode gave the middle back",
      "Hud_Line: 1  -  MORE TO CALL ANGUIRUS", "[ANGUIRUS] START"]),
    ("a drain", _CALL3 + _JOIN + ["shot", "Shield target left", "secs", 1, "ball_end", "secs", 7,
                                             "shot", "Slingshot", "secs", 1],
     ["END (ball ended)", "own clip lost", "SCORE +250000", "lamps held 0"]),
]

#: PAD-658: as a Pro gets it - two shields and the Maser target are the three spikes
_PRO_CHARGE = ["shot", "Shield target left", "ms", 400, "shot", "Maser target", "ms", 400,
               "shot", "Shield target right", "secs", 4]
DESK_PRO = [
    ("the pro's maser is the third spike", _CALL3 + _JOIN + _PRO_CHARGE + ["lamps"] + _ROLLS,
     ["[ANGUIRUS] START", "Hud_Award: SPIKES CHARGED", "Hud_Award: ROLLING ATTACK LIT", "SCORE +16000000",
      "Hud_Award: THE BITE"]),
    ("the pro's lines name its maser", _CALL3 + _JOIN + ["shot", "Shield target left", "secs", 4],
     ["Hud_Line: HIT THE SHIELDS AND THE MASER TARGET", "Hud_AwardSub: HIT THE MASER TARGET AND RIGHT SHIELD"]),
    ("the pro calls him with the maser too", ["shot", "Maser target", "ms", 400] * 8 + ["secs", 1],
     ["[ANGUIRUS] START"]),
]
