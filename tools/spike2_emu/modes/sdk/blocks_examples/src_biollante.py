"""BIOLLANTE in blocks (PAD-658): the SDK's biollante.c rebuilt, then (round 2) taken deeper and deeper in four stages.

Godzilla vs. Biollante (1989): a rose spliced with Godzilla's cells. Her ROSE form spreads vines and acid sap at Lake
Ashi; Godzilla's ray sets her ablaze, her spores rise, and she comes back as the BEAST. After Lyman Sheats' switch
frenzies (The Walking Dead's Blood Bath: every switch scores into a jackpot the targets collect), his generous clocks
(a lit shot under 15 s puts it back to 15), his walkers that come back (TWD), stages with their own shots (EHoH's
House) and a pot to cash out or put at risk (Metallica's Crank It Up).

- LIGHT IT: 4 Left ramp shots in a game (a multiball's too, PAD-690) start it at once; 8 the second time, 12 the
  third (pack.need). PAD-658: the Left ramp alone, so no two modes share a start (the Right ramp lays ZILLA's eggs).
  Each ramp's note: RAMPS TO BIOLLANTE / 3 - SHOOT THE LEFT RAMP, 3 s.
- EVERY SHOT feeds the SAP: it scores the switch value (100,000, +25,000 a bank cut) and adds it to the SAP JACKPOT.
- EVERY STAGE'S CLOCK is pack.STAGE_S (40 s), the beast's too (round 3: it was 20 s; "deeper = more shots, not less
  time"). A new stage is named by the HUD's title (ROSE ABLAZE, REGROWTH, BIOLLANTE BEAST) and its line names the
  shots; the note the stage before ended on stays its 3 s and says what comes next.
- STAGE 1, THE ROSE: the three Shield targets and the three Powerline targets are two banks of vines (blinking green;
  a cut one goes dark). The line counts each bank: SHIELDS: 2 TO GO  POWERLINES: 3 TO GO. A whole bank cut COLLECTS
  the sap jackpot times the banks cut so far (x1, x2) into the POT (and scores it), and that bank stands again. Two
  banks: the rose is cut.
- STAGE 2, ROSE ABLAZE: Godzilla's ray moves across her petals (the Left ramp, the Big loop, the Right ramp in turn,
  chasing orange; the line: SHOOT THE BIG LOOP): the lit petal burns for 5M, 10M, 15M (+2.5M a petal each time she
  has come back) and the sap, into the pot; the Building's fire lights climb with each.
- STAGE 3, REGROWTH: all six vines stand again, chasing green (the line counts each bank, as in the rose): cut every
  one (2M, 3M ... 7M into the pot); left alone pack.WINDOW_S (20) s she grows one back (round 3: it was 6 s, 5 s,
  4 s the more she had been fought).
- STAGE 4, BEAST FORM: her own battle music: the Building (hurrying gold) is the FINAL BLOW, the pot twice over and
  20M (the line: FINAL BLOW: SHOOT THE BUILDING). Every light goes out at it, its note stays 3 s, then the end.
- CASH OUT at the right scoop after stages 1 to 3 (it chases white; the POT counter: AT RIGHT SCOOP): the pot, and
  she retreats. The clock (a vine cut puts it back to 15, a Pop bumper adds a second) or a drain pays a quarter of
  the pot.
- Godzilla Pro: the shield bank is the left shield, the Godzilla target and the right shield (title_alt); its line
  says so (title_alt's words: SHIELDS+GODZILLA: 2  POWERLINES: 3 TO GO).
"""
from blk import (AND, NOT, OR, RUNNING, SECS_LEFT, a_show, add, add_time, award, beds, callout, change, clip, clips, div, end, eq,
                 every, game_show, ge, gt, hud, hud_counter, hud_line, hud_title, if_, light, light_insert, lt, mul,
                 music, off, off_insert, on_any_shot, on_end, on_shot, on_start, on_timer, score, secs_left, set_,
                 set_time, shake, shake_game, shield, show, sound, sounds, start, step, sub, timer_start, timer_stop,
                 var)
import pack

SLUG, NAME = "biollante", "BIOLLANTE"
ROSE, VINE, DEEP, SPORE, GOLD, FIRE, WHITE = ("#ff1446", "#14c828", "#00280a", "#ffe678", "#ffaa00", "#ff5a00",
                                              "#ffffff")
START_RAMP = "Left ramp"
BANKS = ((("l1", "Shield target left"), ("l2", "Shield target center"), ("l3", "Shield target right")),
         (("p1", "Powerline left"), ("p2", "Powerline center"), ("p3", "Powerline right")))
VINES = [(v, s) for bank in BANKS for v, s in bank]
PETALS = ("Left ramp", "Big loop", "Right ramp")
FIRE_INSERTS = (("BUILDING FIRE LEFT 1", "BUILDING FIRE RIGHT 1"), ("BUILDING FIRE LEFT 2", "BUILDING FIRE RIGHT 2"),
                ("BUILDING FIRE LEFT 3", "BUILDING FIRE RIGHT 3"))
FINAL = "Building"
SWITCH_VALUE, SWITCH_STEP = 100000, 25000
RUN_SECONDS = pack.STAGE_S                      # every stage's clock, the beast's too
#: the port's lamp places on the playfield picture
BUILDING = dict(x=123, y=202)
SHIELDS = dict(x=199, y=346)
POWERLINES = dict(x=144, y=216)
TIMERS = ("ramp", "cut", "lamps", "burn", "grow", "next")
NEED = pack.need(6, "plays")                    # 6 Left ramps, then 12, then 18 (PAD-675: was 4)
SW = pack.SHOT_WORDS
#: a petal burns for 5M times the petals burnt (+2.5M a petal each time she has come back), and the sap
PETAL = add(5000000, mul(2500000, sub(var("plays"), 1)))
#: left alone pack.WINDOW_S seconds she grows a vine back (a window inside the stage: the brief's rule 5)
REGROW = pack.WINDOW_S * 1000
FINAL_BLOW = add(mul(var("pot"), 2), 20000000)


def note(text, value=None, sub="", seconds=pack.NOTE_S):
    """An award that stays pack.NOTE_S seconds at least (the brief's rule 3)."""
    return award(text, value=value, sub=sub, seconds=max(seconds, pack.NOTE_S))


SHOWS = [
    a_show("Rose blooms",                                                       # the start: she rises in the lake
           step("fade_in", 900, ROSE, "#000000", "center", gi="dark"),
           step("ripple", 1400, VINE, DEEP, "center", rate=450, gi="dark"),
           step("sparkle", 900, SPORE, ROSE, "top", gi="dark"),
           step("fade", 600, ROSE, "#000000", "center", blend=250)),
    a_show("Vine cut",                                                          # a small hit
           step("burst", 400, VINE, "#000000", "xy", gi="keep", **SHIELDS),
           step("fade", 250, VINE, "#000000", "center")),
    a_show("Collect",                                                           # the sap sprays
           step("sparkle", 700, SPORE, VINE, "center", gi="flash"),
           step("spiral_in", 700, SPORE, DEEP, "xy", gi="dark", **POWERLINES),
           step("fade", 300, VINE, "#000000", "center")),
    a_show("Ablaze",                                                            # Godzilla's ray sets her alight
           step("strobe", 400, WHITE, FIRE, "center", rate=55, gi="flash"),
           step("sweep_up", 700, FIRE, "#200000", "flippers", gi="dark"),
           step("fire", 1600, FIRE, ROSE, "top", gi="dark"),
           step("fade", 500, FIRE, "#000000", "center", blend=200)),
    a_show("Petal burns",
           step("burst", 500, WHITE, FIRE, "xy", gi="flash", **BUILDING),
           step("fire", 900, FIRE, "#300000", "xy", gi="dark", **BUILDING),
           step("fade", 300, FIRE, "#000000", "center")),
    a_show("Regrowth",                                                          # the vines lash out again
           step("spiral_out", 1100, VINE, DEEP, "center", gi="dark"),
           step("bounce", 900, VINE, "#000000", "center", rate=300, gi="dark"),
           step("fade", 400, VINE, "#000000", "center", blend=150)),
    a_show("Grows back",
           step("ripple", 700, VINE, "#000000", "xy", rate=250, gi="keep", **SHIELDS),
           step("fade", 300, VINE, "#000000", "center")),
    a_show("Stage up",
           step("sweep_lr", 400, ROSE, "#000000", "center", gi="dark"),
           step("sweep_rl", 400, VINE, "#000000", "center", gi="dark"),
           step("spin", 900, SPORE, ROSE, "center", rate=90, gi="dark"),
           step("fade", 400, ROSE, "#000000", "center", blend=150)),
    a_show("Beast",
           step("strobe", 500, ROSE, "#000000", "center", rate=60, gi="flash"),
           step("implode", 800, ROSE, DEEP, "xy", gi="dark", **BUILDING),               # the jaws close
           step("fire", 900, VINE, DEEP, "center")),
    a_show("Final blow",
           step("bolts", 900, GOLD, "#200800", "center", rate=120, gi="flash"),
           step("burst", 800, WHITE, GOLD, "xy", gi="dark", **BUILDING),
           step("rainbow", 1600, "#000000", "#000000", "center", rate=50),
           step("sparkle", 1500, SPORE, ROSE, "center", gi="dark"),
           step("fade", 700, SPORE, "#000000", "center", blend=300)),
    a_show("Spores",                                                            # the cash-out: she drifts away
           step("solid", 400, SPORE, "#000000", "flippers", gi="dark"),
           step("sweep_up", 1200, SPORE, "#000000", "flippers", gi="dark"),
           step("sparkle", 1400, SPORE, "#100800", "top", gi="dark"),
           step("fade", 900, SPORE, "#000000", "top", blend=400)),
    a_show("Withers",
           step("pulse", 900, ROSE, DEEP, "center", rate=450, gi="dark"),
           step("implode", 1100, DEEP, "#000000", "center", gi="dark"),
           step("fade", 700, ROSE, "#000000", "center", blend=300)),
]


def stage_line(n, title):
    """A new stage: its title names it (the note the stage before ended on keeps the middle), counter 1 its number."""
    return [hud_title(title), hud_counter(1, n, "OF 4")]


def pot_up(points):
    return [change("pot", points), hud_counter(2, var("pot"), "AT RIGHT SCOOP")]


def bank_sum(b):
    (v1, _s1), (v2, _s2), (v3, _s3) = BANKS[b]
    return add(add(var(v1), var(v2)), var(v3))


def bank_words(shields, powerlines):
    """The line in the rose and the regrowth: how many of each vine bank still stand, by the playfield's names."""
    if shields and powerlines:
        return "SHIELDS: %d TO GO  POWERLINES: %d TO GO" % (shields, powerlines)
    if shields:
        return "HIT THE SHIELDS: %d TO GO" % shields
    if powerlines:
        return "HIT THE POWERLINES: %d TO GO" % powerlines
    return None


def pro_bank_words(shields, powerlines):
    """The same line on Godzilla Pro, where the shield bank is the two shields and the Godzilla target between them."""
    if shields and powerlines:
        return "SHIELDS+GODZILLA: %d  POWERLINES: %d TO GO" % (shields, powerlines)
    if shields:
        return "HIT SHIELDS+GODZILLA TARGET: %d TO GO" % shields
    return bank_words(shields, powerlines)


#: title_alt's words for the Pro: each bank line as the Pro's shots say it
PRO_WORDS = {bank_words(a, b): pro_bank_words(a, b) for a in range(4) for b in range(4)
             if bank_words(a, b) and bank_words(a, b) != pro_bank_words(a, b)}


def bank_line():
    """One line per (shields cut, powerlines cut)."""
    return [if_(eq(bank_sum(0), a), [if_(eq(bank_sum(1), b), [hud_line(bank_words(3 - a, 3 - b))])
                                      for b in range(4) if bank_words(3 - a, 3 - b)])
            for a in range(4)]


def lamps():
    """Every light, the line and the stage's counter, after anything changes: the vines standing (blinking green in
    the rose, chasing in the regrowth; a cut one dark at once), the lit petal chasing orange (the line follows it)."""
    vines = OR(eq("stage", 1), eq("stage", 3))
    return [
        *[if_(AND(vines, eq(v, 0)), [if_(eq("stage", 3), [light(s, VINE, "chase", 90)], [light(s, VINE, "blink", 500)])],
              [off(s)]) for v, s in VINES],
        *[if_(AND(eq("stage", 2), eq("burns", i)), [light(s, FIRE, "chase", 70)], [off(s)])
          for i, s in enumerate(PETALS)],
        if_(vines, bank_line()),
        if_(eq("stage", 2), pack.line_follows("burns", PETALS, first=0)),
        if_(eq("stage", 1), [if_(eq("collects", 0), [hud_counter(3, var("sap"), "X1 AT A BANK")],
                                 [hud_counter(3, var("sap"), "X2 AT A BANK")])]),
        if_(eq("stage", 3), [hud_counter(3, var("cut"), "OF 6")]),
    ]


def collect():
    """Stage 1: a whole bank cut ("bank" 1 the shields, 2 the powerlines): the sap jackpot times the banks cut."""
    return [
        change("collects", 1), set_("got", mul(var("sap"), var("collects"))), score(var("got")), *pot_up(var("got")),
        set_("sap", 0), change("cut", -3),
        set_("switch", add(SWITCH_VALUE, mul(SWITCH_STEP, var("collects")))),
        show("Collect"), sound("collect"), clip("collect", "behind"), shake(400, "medium"),
        if_(eq("bank", 1), [set_(v, 0) for v, _s in BANKS[0]], [set_(v, 0) for v, _s in BANKS[1]]),
        if_(ge("collects", 2), [note("THE ROSE IS CUT", value=var("got"), sub="NOW THE LEFT RAMP"),
                                timer_start("next", 700)],
            [note("SAP JACKPOT X1", value=var("got"), sub="INTO THE POT")]),
    ]


def setup_stage():
    """What each stage lights and says as it begins (run by the "next" timer once the stage before is done)."""
    return [
        if_(eq("stage", 2), stage_line(2, "ROSE ABLAZE") + [
            hud_counter(3, 0, "OF 3", "PETALS"), set_("burns", 0),
            clip("ablaze", "behind"), sound("ablaze"), show("Ablaze")]),
        if_(eq("stage", 3), stage_line(3, "REGROWTH") + [
            hud_counter(3, 0, "OF 6", "VINES"), set_("cut", 0), *[set_(v, 0) for v, _s in VINES],
            *[off_insert(n) for pair in FIRE_INSERTS for n in pair],
            timer_start("grow", REGROW), clip("grab", "behind"), sound("grab"), show("Regrowth")]),
        if_(eq("stage", 4), stage_line(4, "BIOLLANTE BEAST") + [
            timer_stop("grow"), *pack.cash_out_off(), music("beast"), hud_line("FINAL BLOW: SHOOT THE BUILDING"),
            hud_counter(2, FINAL_BLOW, "AT THE BUILDING", "FINAL BLOW"),
            hud_counter(3, var("switches"), "FED HER", "SWITCHES"),
            light(FINAL, GOLD, "hurry"), light_insert("BUILDING SPOT", GOLD, "blink", 120),
            show("Beast"), sound("beast"), clip("beast", "full")]),
    ]


def regrow():
    """She grows back the first vine cut (in the order shields left to right, then the powerlines)."""
    out = []
    for v, _s in reversed(VINES):
        out = [if_(eq(v, 1), [set_(v, 0)], out or None)]
    return out


SCRIPTS = [
    # ---- light it: Left ramp shots (a note on every one: the count is small) --------------------------------------
    on_shot(START_RAMP, timer_start("ramp", 1), when="idle"),
    # (PAD-690: a multiball's ramps count too; one counted out but held off starts it on the next ramp)
    on_timer("ramp", if_(NOT(RUNNING), [
        if_(ge("ramps", NEED), [start()], [
            change("ramps", 1),
            if_(ge("ramps", NEED), [start()],
                [note("RAMPS TO BIOLLANTE", value=sub(NEED, var("ramps")), sub="SHOOT THE LEFT RAMP")])])])),

    # ---- the rose ---------------------------------------------------------------------------------------------------
    on_start(*pack.begin(SLUG),
             set_("ramps", 0), change("plays", 1),
             set_("stage", 1), set_("won", 0), set_("cashed", 0), set_("collects", 0), set_("sap", 0),
             set_("pot", 0), set_("cut", 0), set_("switches", 0), set_("burns", 0), set_("clip ok", 1),
             set_("switch", SWITCH_VALUE), *[set_(v, 0) for v, _s in VINES],
             shield("toward"), game_show("Playfield wave"), clip("intro", "full"), clip("loop", "loop"),
             show("Rose blooms"), shake(800, "strong"),
             note("BIOLLANTE", sub="EVERY SWITCH FEEDS HER SAP"),
             hud_counter(1, 1, "OF 4"), hud_counter(2, 0, "AT RIGHT SCOOP"),
             light("Pop bumper", ROSE, "pulse", 1200),
             timer_start("lamps", 1)),

    # ---- every switch feeds the sap ------------------------------------------------------------------------------
    on_any_shot(score(var("switch")), change("switches", 1),
                if_(lt("stage", 4), [change("sap", var("switch"))]), timer_start("lamps", 1)),
    on_shot("Pop bumper", if_(AND(lt(SECS_LEFT, RUN_SECONDS), eq("won", 0)), [add_time(1)])),

    # ---- the vines (stages 1 and 3) -------------------------------------------------------------------------------------
    *[on_shot(s, if_(AND(OR(eq("stage", 1), eq("stage", 3)), eq(v, 0)),
                     [set_(v, 1), set_("bank", b + 1), timer_start("cut", 1)]))
      for b, bank in enumerate(BANKS) for v, s in bank],
    on_timer("cut",
             change("cut", 1), pack.clock_floor(),
             if_(eq("stage", 1), [
                 if_(OR(AND(eq("bank", 1), eq(bank_sum(0), 3)), AND(eq("bank", 2), eq(bank_sum(1), 3))), collect(),
                     [sound("cut"), show("Vine cut"), shake(150, "soft"),
                      if_(eq("clip ok", 1), [clip("cut", "behind"), set_("clip ok", 0)])])],
                 [*pot_up(add(1000000, mul(1000000, var("cut")))), score(500000), timer_start("grow", REGROW),
                  sound("cut"), show("Vine cut"),
                  if_(ge("cut", 6), [timer_stop("grow"),
                                     note("THE VINES ARE DOWN", value=var("pot"), sub="NOW THE BUILDING"),
                                     clip("collect", "behind"), shake(400, "medium"), timer_start("next", 700)],
                      [note("VINE CUT", value=sub(6, var("cut")), sub="VINES TO GO"), shake(150, "soft"),
                       if_(eq("clip ok", 1), [clip("cut", "behind"), set_("clip ok", 0)])])]),
             timer_start("lamps", 1)),
    every(4, set_("clip ok", 1)),                       # a vine's clip every few seconds at most
    on_timer("grow", if_(AND(eq("stage", 3), gt("cut", 0)), [
        *regrow(), change("cut", -1), note("A VINE GROWS BACK", value=sub(6, var("cut")), sub="VINES TO GO"),
        sound("grab"), show("Grows back"), shake(300, "soft"), timer_start("lamps", 1)]),
        if_(eq("stage", 3), [timer_start("grow", REGROW)])),

    # ---- stage 2: rose ablaze (the lit petal moves on as one burns: the line with it) --------------------------------
    *[on_shot(s, if_(AND(eq("stage", 2), eq("burns", i)), [timer_start("burn", 1)])) for i, s in enumerate(PETALS)],
    on_timer("burn",
             change("burns", 1), set_("got", add(mul(PETAL, var("burns")), var("sap"))), *pot_up(var("got")),
             set_("sap", 0), score(1000000), pack.clock_floor(), hud_counter(3, var("burns"), "OF 3"),
             *[if_(ge("burns", i + 1), [light_insert(n, FIRE, "blink", 90) for n in pair])
               for i, pair in enumerate(FIRE_INSERTS)],
             clip("burn", "behind"), sound("ablaze"), show("Petal burns"), shake(500, "hard"),
             if_(ge("burns", 3), [note("THE ROSE IS ABLAZE", value=var("got"), sub="NOW ALL SIX VINES"),
                                  timer_start("next", 700)],
                 [*[if_(eq("burns", i), [note("A PETAL BURNS", value=var("got"), sub="NOW THE " + SW[s])])
                    for i, s in enumerate(PETALS) if i]]),
             timer_start("lamps", 1)),

    # ---- the beast: the final blow (every light out, its note up 3 s, then the end) -------------------------------------
    on_shot(FINAL, if_(AND(eq("stage", 4), eq("won", 0)), [
        set_("won", 1), score(FINAL_BLOW), off("*"),
        note("FINAL BLOW", value=FINAL_BLOW, sub="THE POT TWICE AND 20M", seconds=4),
        clip("won", "full"), sound("won"), show("Final blow"), shake_game("big_hit"),
        timer_start("next", pack.NOTE_S * 1000)])),
    on_timer("lamps", *lamps()),

    # ---- a stage done: on to the next, or cash out --------------------------------------------------------------
    on_timer("next",
             if_(OR(eq("cashed", 1), eq("won", 1)), [end()], [
                 change("stage", 1), set_time(RUN_SECONDS), show("Stage up"),
                 if_(lt("stage", 4), [shake_game("jackpot"), *pack.cash_out_lit()], [shake_game("rumble")]),
                 *setup_stage(), timer_start("lamps", 1)])),
    on_shot(pack.CASH_SHOT,
            if_(AND(ge("stage", 2), lt("stage", 4), eq("won", 0), eq("cashed", 0)), [
                set_("cashed", 1), score(var("pot")),
                note("CASHED OUT", value=var("pot"), sub="BIOLLANTE RETREATS", seconds=4),
                clip("cashout", "full"), sound("cashout"), show("Spores"), shake(600, "medium"),
                timer_start("next", 1500)])),
    secs_left(10, if_(AND(eq("won", 0), eq("cashed", 0)), [
        callout("ten_seconds"), if_(AND(ge("stage", 2), lt("stage", 4)), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])])),

    # ---- the end ------------------------------------------------------------------------------------------------------
    on_end(*pack.finish(), *[timer_stop(t) for t in TIMERS], set_("stage", 0),
           if_(eq("won", 1), [hud_title("BIOLLANTE IS FREE"), hud_line("THE SAP IS SPENT  -  SWITCHES",
                                                                        value=var("switches"))]),
           if_(eq("cashed", 1), [hud_title("BIOLLANTE RETREATS"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               hud_title("BIOLLANTE WITHERS"), hud_line("A QUARTER OF THE POT"),
               score(div(var("pot"), 4)),
               sound("lost", fallback="time_up"), clip("lost", "full"), show("Withers"), shake(500, "soft")]),
           game_show("Red and blue fade")),
]

PROGRAM = {
    "name": NAME, "seconds": RUN_SECONDS, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": pack.pack_vars() + [{"name": n, "reset": "game"} for n in ("ramps", "plays")] + [
        {"name": n, "reset": "mode"} for n in ("stage", "won", "cashed", "collects", "sap", "pot", "got", "switch",
                                                "switches", "cut", "bank", "burns", "clip ok")] + [
        {"name": v, "reset": "mode"} for v, _s in VINES],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud("SHIELDS: 3 TO GO  POWERLINES: 3 TO GO",
               counters=[("STAGE", "OF 4", None), ("POT", "AT RIGHT SCOOP", None), ("SAP", "X1 AT A BANK", None)],
               timer=("BIOLLANTE", "rose")),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "cut", "collect", "ablaze", "burn", "grab", "beast", "won", "lost", "cashout"),
    "sounds": sounds({"cut": 3, "collect": 3, "ablaze": 3, "grab": 4, "beast": 4, "won": 4, "lost": 4,
                      "cashout": 4}),
    "music": "music.wav",
    "beds": beds("beast"),
    "shows": SHOWS,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 109, "titles": ["godzilla_le", "godzilla_pro"], "based_on": "biollante.c",
    #: the Pro (two fixed shields, no platform, no Playfield wave): the shield bank's middle vine is the Godzilla
    #: target (the captive ball between them), the start's show the Pro's Wide yellow and white strobe
    "title_alt": {"godzilla_pro": {"shots": {"Shield target center": "Godzilla target"},
                                   "shows": {"Playfield wave": "Wide yellow and white strobe"},
                                   "words": PRO_WORDS}},
    "about": ("The C example BIOLLANTE rebuilt in blocks and taken deeper (PAD-658): six Left ramps start her (12 the "
              "second time, 18 the third) and every shot feeds the SAP JACKPOT. Four stages: THE ROSE (cut the "
              "Shield and Powerline vine banks to collect the sap x1, x2 into the pot), ROSE ABLAZE (burn the lit "
              "petal as Godzilla's ray moves across the ramps and the Big loop), REGROWTH (cut all six vines while "
              "she grows them back), then her BEAST form: the final blow at the Building, the pot twice over. 40 s "
              "a stage; the line names the shots (SHIELDS: 2 TO GO  POWERLINES: 3 TO GO, SHOOT THE BIG LOOP). Cash "
              "the pot out at the right scoop after any stage; the clock or a drain pays a quarter."),
    "lost": [
        "Every stage has 40 s, the beast's too (PAD-658's round 3: time to do it): round 2 gave the beast 20 s, and "
        "she grew a vine back after 6 s alone (5 s, 4 s the more she had been fought), now after 20 s.",
        "A new stage is named by the HUD's title (ROSE ABLAZE, REGROWTH, BIOLLANTE BEAST), not by a note over the "
        "one the stage before ended on (THE ROSE IS CUT, THE ROSE IS ABLAZE, THE VINES ARE DOWN): that note stays "
        "its 3 s and says what comes next; the beast's BEAST FORM! note is gone.",
        "On Godzilla Pro the line names the shield bank SHIELDS+GODZILLA (its two shields and the Godzilla target "
        "between them: title_alt's words).",
        "Only the port's named shots feed the sap: the C scored every playfield switch (its 0x1 switch dispatch), "
        "rollovers and other unnamed switches included.",
        "The counters show bare numbers: SAP 500,000 over X1 AT A BANK, where the C showed the bank count as 2/3 "
        "and the switch value as 125K.",
        "No VINES gauge: on the glass its pips sat over the game's own POWER widget at the right edge, so the vines "
        "are counted on the third counter in the regrowth (the C showed six pips shaded green to rose, BEAST in the "
        "beast form).",
        "The ramp count note reads RAMPS TO BIOLLANTE over 3  -  SHOOT THE LEFT RAMP (the number under the words) "
        "where the C said 5 RAMPS TO BIOLLANTE.",
        "The shield vines light at once: the C lit them only once the shield platform had turned to face the "
        "player.",
        "A vine's clip plays at most once in each 4 s window of the mode's own (a block's every 4 seconds): the C "
        "waited 4 s from the last one it played.",
        "No randomness in blocks: Godzilla's ray burns her petals in a fixed order (Left ramp, Big loop, Right "
        "ramp) and she grows back the first vine cut in a fixed order (the shields left to right, then the "
        "powerlines).",
        "The beast's Building blink quickens against its 40 s clock (slow, then fast in its last 13 s), where the "
        "C quickened it across the beast's own 20 s.",
        "The ending (BIOLLANTE IS FREE, BIOLLANTE RETREATS or BIOLLANTE WITHERS, its line and the total) stays up "
        "3 s, the runtime's: the C kept it 10 s; its SWITCHES are the named shots made (the C counted every "
        "switch).",
        "No debounce: the C counted the same target once in 250 ms (a bouncing standup pays once); the blocks "
        "count every report.",
        "A hit no longer answers by itself: the C flashed every scoring shot's inserts white and played the game's "
        "climbing orchestra hit (PAD-415).",
        "Its ending call plays after one of the game's own modes ends it too (the C kept quiet then, as it does "
        "for a drain or a tilt).",
        "On Godzilla Pro the shield bank is the left shield, the Godzilla target and the right shield (the Pro has "
        "two fixed shields), and the start plays the Pro's Wide yellow and white strobe: the C's bank there was the "
        "two shields alone.",
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
_PRO_SHIELDS = ["shot", "Shield target left", "ms", 300, "shot", "Godzilla target", "ms", 300,
                "shot", "Shield target right", "secs", 1]
_SHIELDS = ["shot", "Shield target left", "ms", 300, "shot", "Shield target center", "ms", 300,
            "shot", "Shield target right", "secs", 1]
_POWER = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300,
          "shot", "Powerline right", "secs", 1]
#: two slingshots and the shield vines (5 x 100K: x1 500K), the powerlines (3 x 125K: x2 750K): the rose is cut
_STAGE1 = _shots("Slingshot", 2) + _SHIELDS + _POWER + ["secs", 1]
_STAGE2 = ["shot", "Left ramp", "ms", 500, "shot", "Big loop", "ms", 500, "shot", "Right ramp", "secs", 2]
_STAGE3 = _SHIELDS + _POWER + ["secs", 2]
DESK = [
    # PAD-690: a multiball's Left ramps count (David: "allow incrementing towards our custom modes during
    # multi-balls"): five in one, back to one ball, the sixth starts it
    ("a multiball's ramps count", ["balls", 2] + _shots("Left ramp", 5) + ["balls", 1, "secs", 1] + _shots("Left ramp", 1) + ["secs", 2],
     ["Hud_AwardSub: 1  -  SHOOT THE LEFT RAMP", "[BIOLLANTE] START (a block)"]),
    ("six Left ramps the first time, twelve the second",
     _shots("Left ramp", 6) + ["secs", 1, "trigger", "biollante.stop", "secs", 4] +
     _shots("Left ramp", 11) + ["secs", 2] + _shots("Left ramp", 1) + ["secs", 2],
     ["Hud_Award: RAMPS TO BIOLLANTE", "Hud_AwardSub: 5  -  SHOOT THE LEFT RAMP", "[BIOLLANTE] START (a block)",
      "Hud_AwardSub: 11  -  SHOOT THE LEFT RAMP", "Hud_AwardSub: 1  -  SHOOT THE LEFT RAMP", "SHIELD toward"]),
    ("stage one then cash out", _START + _STAGE1 + ["shot", "Right scoop", "secs", 5],
     ["Hud_Line: SHIELDS: 3 TO GO  POWERLINES: 3 TO GO", "Hud_Line: SHIELDS: 2 TO GO  POWERLINES: 3 TO GO",
      "Hud_Line: SHIELDS: 1 TO GO  POWERLINES: 3 TO GO", "Hud_Award: SAP JACKPOT X1",
      "Hud_AwardSub: 500,000  -  INTO THE POT", "Hud_Line: SHIELDS: 3 TO GO  POWERLINES: 1 TO GO",
      "Hud_Award: THE ROSE IS CUT", "Hud_AwardSub: 750,000  -  NOW THE LEFT RAMP", "Hud_Title: ROSE ABLAZE",
      "Hud_Line: SHOOT THE LEFT RAMP", "Hud_C2_Sub: AT RIGHT SCOOP", "Hud_Award: CASHED OUT",
      "SCORE +1250000", "Hud_Title: BIOLLANTE RETREATS", "lamps held 0"]),
    ("all four stages and the final blow", _START + _STAGE1 + _STAGE2 + _STAGE3 + ["secs", 2, "shot", "Building", "secs", 6],
     ["Hud_AwardSub: 5,150,000  -  NOW THE BIG LOOP", "Hud_Line: SHOOT THE BIG LOOP",
      "Hud_AwardSub: 10,150,000  -  NOW THE RIGHT RAMP", "Hud_Line: SHOOT THE RIGHT RAMP",
      "Hud_Award: THE ROSE IS ABLAZE", "Hud_Title: REGROWTH", "Hud_Line: SHIELDS: 3 TO GO  POWERLINES: 3 TO GO",
      "Hud_Line: HIT THE POWERLINES: 3 TO GO", "Hud_Line: HIT THE POWERLINES: 1 TO GO",
      "LAMP POWERLINE LEFT 14c828 chase 90", "Hud_Award: VINE CUT", "Hud_Award: THE VINES ARE DOWN",
      "Hud_Title: BIOLLANTE BEAST", "Hud_Line: FINAL BLOW: SHOOT THE BUILDING", "Hud_C2_Label: FINAL BLOW",
      "LAMP BUILDING ffaa00 blink", "Hud_Award: FINAL BLOW", "Hud_AwardSub: 137,400,000  -  THE POT TWICE AND 20M",
      "SHAKE the game's big_hit", "SHAKE the game's rumble", "END (a block)", "Hud_Title: BIOLLANTE IS FREE",
      "lamps held 0"]),
    ("a vine grows back in the regrowth", _START + _STAGE1 + _STAGE2 + ["shot", "Shield target left", "secs", 21],
     ["Hud_Line: SHIELDS: 2 TO GO  POWERLINES: 3 TO GO", "Hud_Award: A VINE GROWS BACK",
      "Hud_AwardSub: 6  -  VINES TO GO"]),
    ("the beast's clock runs out", _START + _STAGE1 + _STAGE2 + _STAGE3 + ["secs", 42],
     ["Hud_Line: FINAL BLOW: SHOOT THE BUILDING", "END (time ran out)", "Hud_Title: BIOLLANTE WITHERS",
      "SCORE +14675000", "lamps held 0"]),
    ("she withers on the clock", _START + ["shot", "Shield target left", "secs", 45],
     ["SCORE +100000", "Hud_C3_Value: 100,000", "END (time ran out)", "Hud_Title: BIOLLANTE WITHERS",
      "lamps held 0"]),
    ("a vine puts a short clock back to fifteen", _START + ["secs", 30, "shot", "Shield target left", "secs", 12],
     ["SCORE +100000", "END lamps held 6, display priority 180"]),           # still running at 43 s: the clock went back to 15
    ("the pop bumper gives seconds back", _START + ["secs", 30] + _shots("Pop bumper", 5, 100) + ["secs", 12],
     ["SCORE +100000", "END lamps held 7, display priority 180"]),           # 10 s left + 5 pops: still running at 43.5 s
    ("a drain ends it", _START + _STAGE1 + ["ball_end", "secs", 8],
     ["END (ball ended)", "SCORE +312500", "BALL END HOLD", "lamps held 0"]),
]
#: the same mode as a Pro gets it (title_alt): the Godzilla target is the shield bank's middle vine
DESK_PRO = [
    ("six Left ramps and the Pro's shield bank, then cash out",
     _shots("Left ramp", 6) + ["secs", 1] + _shots("Slingshot", 2) + _PRO_SHIELDS + _POWER +
     ["secs", 1, "shot", "Right scoop", "secs", 5],
     ["[BIOLLANTE] START (a block)", "Hud_Line: SHIELDS+GODZILLA: 1  POWERLINES: 3 TO GO", "Hud_Award: SAP JACKPOT X1",
      "Hud_AwardSub: 500,000  -  INTO THE POT", "Hud_Award: THE ROSE IS CUT", "Hud_Title: BIOLLANTE RETREATS",
      "SCORE +1250000", "lamps held 0"]),
    ("the Pro's regrowth and the final blow", _START + _shots("Slingshot", 2) + _PRO_SHIELDS + _POWER + ["secs", 1] +
     _STAGE2 + _PRO_SHIELDS + _POWER + ["secs", 4, "shot", "Building", "secs", 6],
     ["Hud_Award: THE VINES ARE DOWN", "Hud_Title: BIOLLANTE BEAST", "Hud_Award: FINAL BLOW",
      "Hud_Title: BIOLLANTE IS FREE", "lamps held 0"]),
]
