"""KING GHIDORAH (PAD-658): the C example ghidorah_heads.c rebuilt in blocks, then (round 2) three stages deep.

Ghidorah (1964). Each head is two shots with 3 health; only the LIT head takes damage, the lit head turns, and a
wounded head left alone grows back. Sever all three and Ghidorah takes to the air; ground him by his wings, then the
Maser gets one shot at the body. Round 2 (David: "multi-stage like what we did here"), after Lyman Sheats: a POT built
through the stages, cashed out at the right scoop once a stage is done, each start costing more and playing harder,
and failing still pays a quarter of the pot.

- START: powerline hits in one ball: each of the three twice the first time (6), four times the second (12), six times
  the third (9). Once a ball per player. No hit counts in a multiball (PAD-669). It waits out one of the game's
  battles or a multiball: the next powerline hit after it starts it. Every hit says how many are left (POWERLINE
  HITS, 2 TO SUMMON GHIDORAH); a powerline that has counted all it may says ANOTHER POWERLINE.
- STAGE 1, THE HEADS (the C's battle): LEFT = Left ramp (2) or Powerline left (1); MIDDLE = Building (2) or
  Powerline center (1); RIGHT = Right ramp (2) or Powerline right (1). The lit head: 1M a point of damage; another
  head: a glancing blow, 250K. The lit head turns every 14 s (12 s the second time, 10 s the third: a moving target
  stays 10 s at least); a wounded head that takes no damage for 28 s (24 s, 20 s: a window is WINDOW_S at least)
  grows 1 back, and again. SEVER: 5M x heads severed so far into the pot (7.5M the second time, 10M the third),
  +10 s on the clock, the lit head moves on at once. 50 s (STAGE_S + 10: nine points of damage).
- STAGE 2, THE WINGS: Ghidorah takes to the air. The Big loop and the Mecha lane are his wings: hit one, then the
  other (the same one twice does nothing): each wing hit puts 5M x (hits + 1) into the pot (the second-time value
  likewise). 4 wing hits ground him (5 the second time, 6 the third). 40 s (STAGE_S).
- STAGE 3, THE FINAL BLOW: the Maser target for 40 s (STAGE_S; its own music): the SUPER JACKPOT, 20M + 1M a second
  left, and the pot twice over. The clock running out: GHIDORAH ESCAPES.
- CASH OUT: once the heads are severed the right scoop chases white: it pays the pot and he flees. The clock or a
  drain pays a quarter of the pot.
- SAY THE SHOT (PAD-658 round 3): the line names the lit head's two shots (SHOOT THE LEFT RAMP OR LEFT POWERLINE)
  and moves with it; a hit on it says AGAIN: and its shots, a glancing blow NOW: and the lit head's; a wing hit says
  which shot is next (NOW THE MECHA LANE). Every note stays NOTE_S (3 s) at least; a stage's last note stays its
  NOTE_S before the next stage's announces it.
- INSERTS: stage 1 the lit head's two shots blink gold, slow at 3, faster at 2, fast at 1; every other head's are
  dark (only the lit head takes damage: the C pulsed a wounded one green); stage 2 the wing to hit chases gold (both
  at first; both dark once he is grounded); stage 3 MASER and MASER READY chase and flash white (faster in its last
  5 s).
"""
from blk import (AND, OR, SECS_LEFT, a_show, add, add_time, award, beds, callout, change, clip, clips, div, end, eq,
                 every, ge, gt, hud, hud_counter, hud_line, hud_title, if_, le, light, light_insert, lt, mul, music,
                 ne, off, off_insert, on_end, on_shot, on_start, on_timer, score, secs_left, set_, set_time, shake,
                 shake_game, show, sound, sounds, start, step, sub, timer_start, timer_stop, var)
import pack

SLUG, NAME = "ghidorah_heads", "KING GHIDORAH"
GOLD, GREEN, WHITE = "#ffaa00", "#00ff3c", "#ffffff"           # the kit's KIT_GOLD, KIT_GREEN, KIT_WHITE
GHID_GOLD, GHID_EMBER, BOLT = "#ffaf00", "#5a1e00", "#fff0a0"
#: each head: its name, its big shot (2 damage), its powerline (1), its health, its regrowth timer, its start count
HEADS = (("LEFT HEAD", "Left ramp", "Powerline left", "hp l", "regrow l", "pl left"),
         ("MIDDLE HEAD", "Building", "Powerline center", "hp m", "regrow m", "pl center"),
         ("RIGHT HEAD", "Right ramp", "Powerline right", "hp r", "regrow r", "pl right"))
#: stage 2: his wings, (the shot, its words, the insert beside it)
WINGS = (("Big loop", "THE BIG LOOP", ""), ("Mecha exit bottom", "THE MECHA LANE", "MECHA LANE"))
FINAL_SHOT, FINAL_INSERT = "Maser target", "MASER READY"
TIMERS = ("turn", "regrow l", "regrow m", "regrow r", "hit", "lights", "next")
NEED = pack.need(6, "starts")                      # powerline hits: 6, then 12, then 18 (PAD-675: was 3)
WINGS_NEED = add(3, var("starts"))                 # wing hits: 4, then 5, then 6
SUPER = add(20000000, mul(1000000, SECS_LEFT))
MOVE_S = 10                                        # the lit head stays this long at least before it turns
NOTE_MS = pack.NOTE_S * 1000                       # a stage's last note stays this long before the next one's


def head_shots(i):
    """Head ``i``'s two shots, as the line says them: LEFT RAMP OR LEFT POWERLINE."""
    return "%s OR %s" % (pack.SHOT_WORDS[HEADS[i][1]], pack.SHOT_WORDS[HEADS[i][2]])
BUILDING_XY, MASER_XY = (123, 202), (51, 417)      # the port's lamp places: BUILDING, MASER
LOOP_XY, LANE_XY = (195, 251), (282, 393)          # BIG LOOP, MECHA LANE

SHOWS = [
    # the C's own shows (its fallback where a card has no "Strobe burst" / "Colour fade"), now run for its moments
    a_show("Ghidorah start",
           step("bolts", 1500, GHID_GOLD, "#000000", "center", rate=190, gi="dark"),        # gravity beams strike
           step("strobe", 500, WHITE, GHID_GOLD, "center", rate=60, gi="flash"),
           step("burst", 800, GHID_GOLD, GHID_EMBER, "xy", gi="dark", x=BUILDING_XY[0], y=BUILDING_XY[1]),
           step("fade", 400, GHID_EMBER, "#000000", "center")),
    a_show("Ghidorah won",
           step("strobe", 400, WHITE, "#000000", "center", rate=50, gi="flash"),
           step("burst", 700, WHITE, GHID_GOLD, "xy", gi="dark", x=MASER_XY[0], y=MASER_XY[1]),   # the final blow
           step("rainbow", 1800, "#000000", "#000000", "center", rate=60),
           step("fade", 500, GHID_GOLD, "#000000", "center")),
    a_show("Ghidorah lost",
           step("sweep_up", 900, GHID_GOLD, GHID_EMBER, "center", gi="dark"),               # Ghidorah flies off
           step("sweep_up", 900, GHID_GOLD, "#000000", "center", gi="dark"),
           step("sparkle", 700, GHID_GOLD, "#000000", "center", gi="dark"),
           step("fade", 400, GHID_EMBER, "#000000", "center")),
    # round 2: one for every moment
    a_show("Sever",
           step("strobe", 250, WHITE, GHID_GOLD, "center", rate=45, gi="flash"),
           step("implode", 600, GHID_GOLD, GHID_EMBER, "xy", gi="dark", x=BUILDING_XY[0], y=BUILDING_XY[1]),
           step("burst", 500, WHITE, GHID_GOLD, "xy", gi="dark", x=BUILDING_XY[0], y=BUILDING_XY[1]),
           step("fade", 300, GHID_GOLD, "#000000", "center")),
    a_show("Regrow",
           step("fade_in", 500, GREEN, "#000000", "xy", gi="keep", x=BUILDING_XY[0], y=BUILDING_XY[1]),
           step("pulse", 700, GREEN, "#002008", "xy", rate=350, gi="keep", x=BUILDING_XY[0], y=BUILDING_XY[1]),
           step("fade", 300, GREEN, "#000000", "center")),
    a_show("Wings",
           step("sweep_lr", 400, GHID_GOLD, "#000000", "top", gi="dark"),
           step("sweep_rl", 400, GHID_GOLD, "#000000", "top", gi="dark"),
           step("bounce", 1400, BOLT, GHID_EMBER, "top", gi="dark"),
           step("spiral_out", 900, GHID_GOLD, GHID_EMBER, "top", gi="dark", blend=150),
           step("fade", 400, GHID_GOLD, "#000000", "center")),
    a_show("Wing hit",
           step("ripple", 600, BOLT, GHID_GOLD, "xy", rate=200, gi="flash", x=LOOP_XY[0], y=LOOP_XY[1]),
           step("sparkle", 500, GHID_GOLD, "#000000", "xy", gi="dark", x=LANE_XY[0], y=LANE_XY[1]),
           step("fade", 300, GHID_GOLD, "#000000", "center")),
    a_show("Final blow",
           step("sweep_down", 600, GHID_GOLD, GHID_EMBER, "center", gi="dark"),             # he crashes down
           step("fire", 900, GHID_GOLD, "#ff3000", "flippers", gi="dark"),
           step("spiral_in", 1200, WHITE, "#0050ff", "xy", gi="dark", x=MASER_XY[0], y=MASER_XY[1]),
           step("fade", 400, "#0050ff", "#000000", "center", blend=150)),
    a_show("Cash out",
           step("solid", 500, GHID_GOLD, "#000000", "right", gi="dark"),
           step("spin", 1400, GHID_GOLD, GHID_EMBER, "center", rate=120, gi="dark"),
           step("fade", 900, GHID_GOLD, "#000000", "center", blend=400)),
]


def by_lit(make):
    """``make(i)`` for the lit head: an if-chain over the three."""
    return [if_(eq("lit", 1), make(0), [if_(eq("lit", 2), make(1), make(2))])]


def pot_up(points):
    return [change("pot", points)]


def head_hit(i, damage):
    """A hit on head ``i`` worth ``damage``: the lit head is hurt (or severed), another one is a glancing blow (its
    note names the lit head's shots: the line under it is covered while it shows)."""
    name, _big, _small, hp, regrow, _pl = HEADS[i]
    j, k = [n for n in range(3) if n != i]
    return [if_(AND(eq("stage", 1), gt(hp, 0)), [
        if_(eq("lit", i + 1), [
            if_(le(hp, damage), [
                score(mul(1000000, var(hp))), set_(hp, 0), set_("cut", i + 1), timer_start("hit", 1)],
                [change(hp, -damage), score(1000000 * damage), pack.clock_floor(), *([shake(300, "soft")] if damage > 1 else []),
                 award("%s -%d" % (name, damage), sub="AGAIN: " + head_shots(i), seconds=pack.NOTE_S),
                 timer_start(regrow, var("regrow ms")), timer_start("lights", 1)]),
        ], [score(250000),
            if_(eq("lit", j + 1), [award("GLANCING BLOW", sub="NOW: " + head_shots(j), seconds=pack.NOTE_S)],
                [award("GLANCING BLOW", sub="NOW: " + head_shots(k), seconds=pack.NOTE_S)])]),
    ])]


def head_lights(i):
    """Head ``i``'s two shots and its counter, as the battle stands: only the lit head's are lit (only it takes
    damage)."""
    name, big, small, hp, _regrow, _pl = HEADS[i]
    return [if_(eq(hp, 0), [off(big), off(small), hud_counter(i + 1, 0, "SEVERED")], [
        if_(eq("lit", i + 1), [
            set_("pace", 180), if_(ge(hp, 2), [set_("pace", 400)]), if_(ge(hp, 3), [set_("pace", 700)]),
            light(big, GOLD, "blink", var("pace")), light(small, GOLD, "blink", var("pace")),
            hud_counter(i + 1, var(hp), ">> LIT <<"),
        ], [off(big), off(small), hud_counter(i + 1, var(hp), "HEALTH")]),
    ])]


def qualify(i):
    """A powerline while the battle is not on: each one counts up to once a start so far, plus one; every hit says
    how many are left, and one that has counted all it may says another powerline."""
    pl = HEADS[i][5]
    left = sub(NEED, var("pl hits"))
    # (counted out but held off by one of the game's battles: any powerline starts it once it may)
    return on_shot(HEADS[i][2], if_(eq("ran ball", 0), [
        if_(ge("pl hits", NEED), [start()], [if_(pack.ONE_BALL, [      # PAD-669: none counts in a multiball
            if_(lt(pl, mul(2, add(var("starts"), 1))), [            # each: twice a start so far, plus two
                change(pl, 1), change("pl hits", 1),
                if_(ge("pl hits", NEED), [start()], [
                    award("POWERLINE HITS", value=left, sub="TO SUMMON GHIDORAH", seconds=pack.NOTE_S)]),
            ], [award("ANOTHER POWERLINE", value=left, sub="TO SUMMON GHIDORAH", seconds=pack.NOTE_S)])])]),
    ]), when="idle")


def regrowth(i):
    name, _big, _small, hp, regrow, _pl = HEADS[i]
    return on_timer(regrow, if_(AND(eq("stage", 1), gt(hp, 0), lt(hp, 3)), [
        change(hp, 1), award(name, sub="GROWS BACK: FINISH IT", seconds=pack.NOTE_S),
        sound("regrow"), clip("regrow", "behind"), show("Regrow"), timer_start(regrow, var("regrow ms")),
        timer_start("lights", 1)]))


def wing(k):
    """Stage 2: a wing, when the other one was hit last (or none yet) and he is still up."""
    shot = WINGS[k][0]
    return on_shot(shot, if_(AND(eq("stage", 2), ne("wing last", k + 1), lt("wings", WINGS_NEED)), [
        set_("wing last", k + 1), timer_start("hit", 1)]))


def wing_lights():
    """The wing to hit chases gold (both before the first); the HUD's line names it."""
    out = []
    for k, (shot, words, ins) in enumerate(WINGS):
        lit = [light(shot, GHID_GOLD, "chase", 90)] + ([light_insert(ins, GHID_GOLD, "chase", 90)] if ins else [])
        dark = [off(shot)] + ([off_insert(ins)] if ins else [])
        out.append(if_(eq("wing last", k + 1), dark, lit))
    out.append(if_(eq("wing last", 1), [hud_line("THE WINGS: NOW THE MECHA LANE")],
                   [if_(eq("wing last", 2), [hud_line("THE WINGS: NOW THE BIG LOOP")],
                        [hud_line("THE WINGS: BIG LOOP OR MECHA LANE")])]))
    return out


SCRIPTS = [
    # ---- the start: powerline hits in one ball (6, then 12, then 18) ------------------------------------------------
    qualify(0), qualify(1), qualify(2),
    on_start(set_("ran ball", 1), change("starts", 1), set_("ghidorah played", 1),
             set_("pl left", 0), set_("pl center", 0), set_("pl right", 0), set_("pl hits", 0),
             set_("hp l", 3), set_("hp m", 3), set_("hp r", 3), set_("lit", 1), set_("severed", 0),
             set_("stage", 1), set_("pot", 0), set_("won", 0), set_("cashed", 0), set_("wings", 0),
             set_("wing last", 0),
             # harder each time: the lit head turns sooner (14, 12, then 10 s: MOVE_S at least), a wound grows back
             # sooner (28, 24, then 20 s: WINDOW_S at least); the stages pay more
             set_("turn ms", sub(MOVE_S * 1000 + 6000, mul(2000, var("starts")))),
             if_(lt("turn ms", MOVE_S * 1000), [set_("turn ms", MOVE_S * 1000)]),
             set_("regrow ms", sub(pack.WINDOW_S * 1000 + 12000, mul(4000, var("starts")))),
             if_(lt("regrow ms", pack.WINDOW_S * 1000), [set_("regrow ms", pack.WINDOW_S * 1000)]),
             set_("value", add(2500000, mul(2500000, var("starts")))),
             clip("intro", "full"), clip("loop", "loop"), sound("summon"), show("Ghidorah start"),
             shake(800, "strong"),
             *[hud_counter(i + 1, 3, "HEALTH", HEADS[i][0]) for i in range(3)],
             hud_line(pack.shoot(HEADS[0][1], HEADS[0][2])),
             award("GHIDORAH ATTACKS", sub="SEVER ALL THREE HEADS", seconds=3),
             timer_start("turn", var("turn ms")), timer_start("lights", 1)),

    # ---- stage 1: the heads ------------------------------------------------------------------------------------------
    *[on_shot(HEADS[i][1], *head_hit(i, 2)) for i in range(3)],
    *[on_shot(HEADS[i][2], *head_hit(i, 1)) for i in range(3)],
    *[regrowth(i) for i in range(3)],
    # the lit head moves on to the next living one (left, middle, right, round again)
    on_timer("turn", if_(eq("stage", 1), [
        if_(eq("lit", 1), [if_(gt("hp m", 0), [set_("lit", 2)], [if_(gt("hp r", 0), [set_("lit", 3)])])], [
            if_(eq("lit", 2), [if_(gt("hp r", 0), [set_("lit", 3)], [if_(gt("hp l", 0), [set_("lit", 1)])])],
                [if_(gt("hp l", 0), [set_("lit", 1)], [if_(gt("hp m", 0), [set_("lit", 2)])])])]),
        timer_start("lights", 1), timer_start("turn", var("turn ms"))])),
    on_timer("lights", if_(eq("stage", 1), [
        *by_lit(lambda i: [hud_line(pack.shoot(HEADS[i][1], HEADS[i][2]))]),
        *[b for i in range(3) for b in head_lights(i)]], [if_(eq("stage", 2), wing_lights())])),

    # ---- a head severed (stage 1), a wing hit (stage 2) ----------------------------------------------------------------
    on_timer("hit",
             if_(eq("stage", 1), [
                 change("severed", 1), *pot_up(mul(var("value"), var("severed"))), pack.clock_floor(),
                 sound("sever"), clip("sever", "behind"), show("Sever"), timer_start("lights", 1),
                 if_(ge("severed", 3), [
                     timer_stop("turn"), award("ALL HEADS SEVERED", value=var("pot"), sub="POT", seconds=pack.NOTE_S),
                     shake_game("big_hit"), timer_start("next", NOTE_MS),
                 ], [
                     add_time(10), shake(600, "hard"), timer_start("turn", 1),
                     *[if_(eq("cut", i + 1), [award(HEADS[i][0], value=mul(var("value"), var("severed")),
                                                    sub="SEVERED  +10 SECONDS", seconds=pack.NOTE_S)])
                       for i in range(3)],
                 ]),
             ], [
                 change("wings", 1), score(1000000), pack.clock_floor(), *pot_up(mul(var("value"), add(var("wings"), 1))),
                 hud_counter(1, sub(WINGS_NEED, var("wings")), "TO GO"), hud_counter(2, var("pot"), "CASH AT SCOOP"),
                 show("Wing hit"),
                 if_(ge("wings", WINGS_NEED), [
                     # grounded: both wings dark at once (they count no more), the note stays before stage 3's
                     *[b for shot, _w, ins in WINGS for b in [off(shot)] + ([off_insert(ins)] if ins else [])],
                     award("GHIDORAH FALLS", value=var("pot"), sub="POT", seconds=pack.NOTE_S), clip("fall", "behind"),
                     sound("fall"), shake_game("big_hit"), timer_start("next", NOTE_MS)],
                     [timer_start("lights", 1),
                      # the note names the other wing's shot: the line under it is covered while it shows
                      *[if_(eq("wing last", k + 1), [
                          award("WING HIT", value=mul(var("value"), add(var("wings"), 1)),
                                sub="NOW " + WINGS[1 - k][1], seconds=pack.NOTE_S)]) for k in range(2)],
                      clip("wing", "behind"), sound("wing"), shake(400, "medium")]),
             ])),

    # ---- stage 2: the wings ------------------------------------------------------------------------------------------
    wing(0), wing(1),

    # ---- a stage done: on to the next, or cash out ----------------------------------------------------------------------
    on_timer("next", if_(OR(eq("cashed", 1), eq("won", 1)), [end()], [
        # (the heads' turn and regrowth timers do nothing past stage 1, and stop themselves)
        change("stage", 1), shake_game("jackpot"), off("*"), *pack.cash_out_lit(),
        if_(eq("stage", 2), [
            set_time(pack.STAGE_S), set_("wing last", 0),
            hud_counter(1, WINGS_NEED, "TO GO", "WING HITS"), hud_counter(2, var("pot"), "CASH AT SCOOP", "POT"),
            hud_counter(3, 2, "OF 3", "STAGE"), timer_start("lights", 1),
            award("GHIDORAH FLIES", sub="%s AND %s, IN TURN" % (pack.SHOT_WORDS[WINGS[0][0]],
                                                               pack.SHOT_WORDS[WINGS[1][0]]), seconds=pack.NOTE_S),
            clip("wings", "behind"), sound("summon"), show("Wings")],
            [set_time(pack.STAGE_S),
             hud_line("FINAL BLOW: " + pack.shoot(FINAL_SHOT)),
             hud_counter(1, var("pot"), "TWICE OVER", "POT"), hud_counter(2, SUPER, "MASER TARGET", "SUPER JACKPOT"),
             hud_counter(3, 3, "OF 3", "STAGE"),
             award("THE FINAL BLOW", sub="SUPER JACKPOT: THE " + pack.SHOT_WORDS[FINAL_SHOT], seconds=pack.NOTE_S),
             light(FINAL_SHOT, WHITE, "chase", 120), light_insert(FINAL_INSERT, WHITE, "blink", 150),
             clip("final", "behind"), show("Final blow"), music("final")]),
    ])),

    # ---- stage 3: the final blow ----------------------------------------------------------------------------------------
    every(1, if_(eq("stage", 3), [hud_counter(2, SUPER, "MASER TARGET")])),
    secs_left(5, if_(eq("stage", 3), [light(FINAL_SHOT, WHITE, "blink", 80),
                                      light_insert(FINAL_INSERT, WHITE, "blink", 80)])),
    on_shot(FINAL_SHOT, if_(AND(eq("stage", 3), eq("won", 0), eq("cashed", 0)), [
        score(add(SUPER, mul(var("pot"), 2))), set_("won", 1), set_("ghidorah won", 1),
        award("GHIDORAH DEFEATED", value=add(SUPER, mul(var("pot"), 2)), sub="SUPER JACKPOT", seconds=4),
        clip("won", "full"), sound("won"), show("Ghidorah won"), shake_game("multiball_start"),
        timer_start("next", 3000)])),

    # ---- the cash-out ---------------------------------------------------------------------------------------------------
    on_shot(pack.CASH_SHOT, if_(AND(ge("stage", 2), eq("won", 0), eq("cashed", 0)), [
        set_("cashed", 1), score(var("pot")), award("CASHED OUT", value=var("pot"), sub="GHIDORAH FLEES", seconds=4),
        clip("cashout", "full"), sound("cashout"), show("Cash out"), shake(400, "medium"),
        timer_start("next", 1500)])),
    secs_left(10, callout("ten_seconds"), if_(ge("stage", 2), [light(pack.CASH_SHOT, pack.WHITE, "hurry")])),

    # ---- the end ---------------------------------------------------------------------------------------------------------
    on_end(*[timer_stop(t) for t in TIMERS], set_("stage", 0),
           off_insert(FINAL_INSERT),
           if_(AND(eq("won", 0), eq(SECS_LEFT, 0)), [sound("lost", fallback="time_up")]),
           if_(eq("won", 1), [hud_title("GHIDORAH DEFEATED"), hud_line("THE HEADS, THE WINGS, THE MASER")]),
           if_(eq("cashed", 1), [hud_title("GHIDORAH FLEES"), hud_line("THE POT IS CASHED OUT")]),
           if_(AND(eq("won", 0), eq("cashed", 0)), [
               hud_title("GHIDORAH ESCAPES"), hud_line("A QUARTER OF THE POT"), score(div(var("pot"), 4)),
               clip("lost", "full"), show("Ghidorah lost")])),
]

PROGRAM = {
    "name": NAME, "seconds": pack.STAGE_S + 10, "ends_on_drain": True, "screen": False, "game_modes": "block",
    "wait_multiball": True, "priority": 180,
    "vars": [{"name": n, "reset": "ball"} for n in ("pl left", "pl center", "pl right", "pl hits", "ran ball")] +
            [{"name": "starts", "reset": "game"}] +
            [{"name": n, "reset": "game", "shared": True} for n in ("ghidorah played", "ghidorah won")] +
            [{"name": n, "reset": "mode"} for n in ("hp l", "hp m", "hp r", "lit", "severed", "won", "cut", "pace",
                                                    "stage", "pot", "cashed", "wings", "wing last", "turn ms",
                                                    "regrow ms", "value")],
    "timers": [{"name": n} for n in TIMERS],
    "hud": hud(pack.shoot(HEADS[0][1], HEADS[0][2]),
               counters=[("LEFT HEAD", "HEALTH", None), ("MIDDLE HEAD", "HEALTH", None),
                         ("RIGHT HEAD", "HEALTH", None)],
               timer=("GHIDORAH", "bolt"),
               gauge={"label": "STAGE", "kind": "diamond", "count": 3, "color": "#ffaa00", "value": var("stage")}),
    "bar": {"on": False}, "info": {"on": False},
    "clips": clips("intro", "loop", "sever", "regrow", "won", "lost", "wings", "wing", "fall", "final", "cashout"),
    "sounds": sounds({"sever": 3, "regrow": 3, "won": 4, "lost": 4, "summon": 4, "wing": 3, "fall": 4,
                      "cashout": 4}),
    "music": "music.wav",
    "beds": beds("final"),
    "shows": SHOWS,
    "scripts": None,
}

EXAMPLE = {
    "name": NAME, "slug": SLUG, "order": 101, "titles": ["godzilla_le", "godzilla_pro"],
    "based_on": "ghidorah_heads.c",
    "about": ("The C example KING GHIDORAH rebuilt in blocks, three stages deep. Powerline hits in one ball start it "
              "(each powerline twice, four times the second time, six times the third). THE HEADS is the C's battle: "
              "only the lit head (two shots each, lit gold and named on the line) takes damage, it turns, a wounded "
              "head grows back, each sever pays into the pot; THE WINGS: hit the Big loop and the Mecha lane in "
              "turn to ground him; THE FINAL BLOW: the Maser's super jackpot and the pot twice over. Cash the pot "
              "at the right scoop once the heads are off; failing pays a quarter."),
    "lost": [
        "The heads' shots have no 250 ms debounce: a ball rattling on a target is several hits (the C counted one "
        "hit a quarter second per shot).",
        "A start from the tab's Start mode now counts as the ball's and the game's start too (the C counted only "
        "the three powerlines).",
        "When a run will not count (it already ran this ball) the powerlines say nothing; the C logged why once. "
        "The C ran at most twice a game; the blocks any number of times, each start costing more.",
        "The HUD shows a severed head's health as 0, where the C showed X; in the final blow the counters are the "
        "POT, the SUPER JACKPOT and the STAGE, where the C hid all but the super jackpot; and the gauge counts the "
        "stages, where the C's counted the severed heads.",
        "Awards say their numbers under the words: LEFT HEAD over 5,000,000  -  SEVERED  +10 SECONDS, where the C "
        "said LEFT HEAD SEVERED over 5,000,000   +10 SECONDS; a head growing back says LEFT HEAD over GROWS BACK, "
        "where the C said LEFT HEAD REGROWS. A hit on the lit head says AGAIN: and its two shots under LEFT HEAD "
        "-2, where the C said the points; a glancing blow names the lit head's two shots (NOW: BUILDING OR CENTER "
        "POWERLINE), where the C named the head. Every note stays 3 s at least, where the C showed a hit's 1.3 s, "
        "a glancing blow's 1.2 s and a head growing back 1.8 s.",
        "The HUD's line names the lit head's two shots (SHOOT THE LEFT RAMP OR LEFT POWERLINE), where the C said "
        "SHOOT THE LEFT HEAD.",
        "The lit head turns every 14 s (12 s the second time, 10 s the third) and a wound grows back after 28 s "
        "(24 s, 20 s), where the C turned it every 8 s and grew a wound back after 10 s (PAD-658: a moving target "
        "stays 10 s at least, a window 20 s). A wounded head that is not lit stays dark, where the C pulsed it "
        "green: only the lit head takes damage, so only its shots are lit.",
        "The ending title (GHIDORAH DEFEATED, GHIDORAH FLEES or GHIDORAH ESCAPES) and its total stay up 3 s, the "
        "runtime's: the C kept them 10 s, with KING GHIDORAH TOTAL under the total.",
        "The lit head moves on its own timer, and moves a tick after a sever (the C moved it in the same tick); "
        "its inserts change a tick after a hit too.",
        "The countdown's 5, 4, 3, 2, 1 callouts are gone (the blocks say only ten seconds and time up).",
        "Godzilla Premium/LE and Pro 1.16 only (a Pro 1.15 has no switch shots): the C also ran on a Pro 1.15. It "
        "played the game's Strobe burst at the start and Colour fade at the end, with its own shows where the game "
        "had none; the blocks run its own shows (Ghidorah start, Ghidorah won, Ghidorah lost and six more) on "
        "every title instead.",
        "The blocks pack keeps its own FINAL WARS ledger in shared variables ('ghidorah played', 'ghidorah won'), "
        "which the blocks FINAL WARS reads: the C FINAL WARS does not read them, and the blocks FINAL WARS does not "
        "read the C's ledger.",
    ],
}


def build():
    p = dict(PROGRAM)
    p["scripts"] = SCRIPTS
    return dict(EXAMPLE, program=p)


_PL = ["shot", "Powerline left", "ms", 300, "shot", "Powerline center", "ms", 300, "shot", "Powerline right"]
#: each powerline twice (PAD-675: a powerline counts up to twice a start so far, plus two)
POWER6 = _PL + ["ms", 300] + _PL + ["secs", 1]
_START = ["trigger", "ghidorah_heads.start", "secs", 1]
_SEVER_ALL = ["shot", "Left ramp", "ms", 300, "shot", "Right ramp", "ms", 300, "shot", "Powerline left", "secs", 1,
              "shot", "Building", "ms", 300, "shot", "Powerline center", "secs", 1,
              "shot", "Right ramp", "ms", 300, "shot", "Powerline right", "secs", 2]
_WINGS = ["shot", "Big loop", "ms", 600, "shot", "Mecha exit bottom", "ms", 600] * 2 + ["secs", 1]
#: the desk scenarios (make_examples.py --desk): what, the harness's commands, lines its output must hold
DESK = [
    # PAD-669: a multiball's powerline hits count for nothing: back to one ball, 1 more says 5 to go, no start
    ("no hit counts in a multiball", ["balls", 2] + POWER6 + ["balls", 1, "secs", 1] + ["shot", "Powerline left"] + ["secs", 2],
     ["Hud_AwardSub: 5  -  TO SUMMON GHIDORAH", "![KING GHIDORAH] START (a block)"]),
    # the Left powerline a third time does not count: ANOTHER POWERLINE
    ("the powerlines start it", ["shot", "Powerline left", "secs", 1, "shot", "Powerline left", "secs", 1] + POWER6 +
     ["secs", 5],
     ["Hud_Award: POWERLINE HITS", "Hud_AwardSub: 5  -  TO SUMMON GHIDORAH", "Hud_Award: ANOTHER POWERLINE",
      "Hud_AwardSub: 1  -  TO SUMMON GHIDORAH",
      "[KING GHIDORAH] START (a block)", "Hud_Award: GHIDORAH ATTACKS", "Hud_Line: SHOOT THE LEFT RAMP OR LEFT POWERLINE",
      "Hud_C1_Sub: >> LIT <<", "LAMP LEFT RAMP ffaa00 blink 700", "LAMP POWERLINE LEFT ffaa00 blink 700"]),
    # the next ball: each powerline twice does not start it again this game, four times does
    ("six hits the first time, twelve the second", POWER6 + ["trigger", "ghidorah_heads.stop", "secs", 4, "ball_end",
                                                             "secs", 2] + POWER6 + POWER6 + ["secs", 2],
     ["[KING GHIDORAH] START (a block)", "END (trigger file)", "Hud_AwardSub: 3  -  TO SUMMON GHIDORAH",
      "Hud_AwardSub: 1  -  TO SUMMON GHIDORAH"]),
    ("the heads, then cash out", POWER6 + _SEVER_ALL + ["secs", 7, "shot", "Right scoop", "secs", 5],
     ["SCORE +2000000", "SCORE +250000", "Hud_Award: LEFT HEAD -2", "Hud_AwardSub: AGAIN: LEFT RAMP OR LEFT POWERLINE",
      "Hud_Award: GLANCING BLOW", "Hud_AwardSub: NOW: LEFT RAMP OR LEFT POWERLINE",
      "Hud_Award: LEFT HEAD", "Hud_AwardSub: 5,000,000  -  SEVERED  +10 SECONDS",
      "Hud_Line: SHOOT THE BUILDING OR CENTER POWERLINE",
      "Hud_Award: ALL HEADS SEVERED", "Hud_AwardSub: 30,000,000  -  POT", "Hud_Award: GHIDORAH FLIES",
      "Hud_AwardSub: BIG LOOP AND MECHA LANE, IN TURN",
      "Hud_C1_Label: WING HITS", "LAMP BIG LOOP ffaf00 chase 90", "LAMP SELECT CITY ffffff chase",
      "Hud_Award: CASHED OUT", "Hud_Title: GHIDORAH FLEES", "END (a block)", "lamps held 0"]),
    ("all three stages", POWER6 + _SEVER_ALL + ["secs", 3] + _WINGS + ["secs", 3, "shot", "Maser target", "secs", 6],
     ["Hud_Award: WING HIT", "Hud_AwardSub: 10,000,000  -  NOW THE MECHA LANE",
      "Hud_AwardSub: 15,000,000  -  NOW THE BIG LOOP", "Hud_Line: THE WINGS: NOW THE MECHA LANE",
      "Hud_Award: GHIDORAH FALLS",
      "Hud_Award: THE FINAL BLOW", "Hud_AwardSub: SUPER JACKPOT: THE MASER TARGET",
      "Hud_Line: FINAL BLOW: SHOOT THE MASER TARGET", "Hud_C2_Label: SUPER JACKPOT", "Hud_Timer_Num: 40",
      "LAMP MASER READY ffffff blink", "Hud_Award: GHIDORAH DEFEATED", "Hud_Title: GHIDORAH DEFEATED",
      "END (a block)", "lamps held 0"]),
    ("a head regrows, turns, and Ghidorah escapes", _START + ["shot", "Left ramp", "secs", 12, "secs", 60],
     ["Hud_Award: LEFT HEAD -2", "Hud_Line: SHOOT THE BUILDING OR CENTER POWERLINE", "LAMP OFF LEFT RAMP",
      "Hud_AwardSub: GROWS BACK: FINISH IT", "CALLOUT 1295", "END (time ran out): 1 scores, total 2000000",
      "Hud_Title: GHIDORAH ESCAPES", "lamps held 0"]),
    ("the final blow missed pays a quarter", _START + _SEVER_ALL + ["secs", 3] + _WINGS + ["secs", 45],
     ["Hud_Award: GHIDORAH FALLS", "END (time ran out)", "Hud_Title: GHIDORAH ESCAPES",
      "Hud_Line: A QUARTER OF THE POT", "lamps held 0"]),
    ("a drain ends it", _START + ["shot", "Building", "secs", 1, "ball_end", "secs", 8],
     ["SCORE +250000", "Hud_Award: GLANCING BLOW", "Hud_AwardSub: NOW: LEFT RAMP OR LEFT POWERLINE",
      "END (ball ended)", "lamps held 0"]),
]

#: the Pro (Godzilla Pro 1.16) has every shot and insert it names (MASER READY too): the same rules, played there
DESK_PRO = [
    ("the powerlines start it", POWER6 + ["secs", 5],
     ["[KING GHIDORAH] START (a block)", "LAMP LEFT RAMP ffaa00 blink 700"]),
    ("all three stages", POWER6 + _SEVER_ALL + ["secs", 3] + _WINGS + ["secs", 3, "shot", "Maser target", "secs", 6],
     ["Hud_Award: GHIDORAH FALLS", "LAMP MASER READY ffffff blink", "Hud_Title: GHIDORAH DEFEATED", "lamps held 0"]),
]
