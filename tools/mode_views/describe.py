"""PAD-611: a blocks program in plain words - what every view mockup writes on its cards.

One sentence per block, value, condition and hat, for every kind the blocks have (tests/test_pad611_mode_script.py
checks none falls through to the catch-all), so a view built on these never meets a block it cannot show.
"""
from pinball_decryptor.plugins.stern import block_modes as BM

COLOR_NAMES = {"#ffd000": "yellow", "#00a0ff": "blue", "#ff0000": "red", "#00c040": "green", "#ffffff": "white",
               "#ff7800": "orange", "#a040ff": "purple"}
PATTERN_WORDS = {"solid": "solid", "blink": "blinking", "pulse": "pulsing", "chase": "chasing",
                 "hurry": "blinking faster as time runs out", "off": "dark"}


def colour(c):
    return COLOR_NAMES.get(str(c or "").lower(), str(c or ""))


def points(v):
    if isinstance(v, dict) and v.get("k") == "num" and isinstance(v.get("v"), int):
        return "{:,}".format(v["v"])
    return val(v)


def val(e):
    """A value in words."""
    if not isinstance(e, dict):
        return "?" if e is None else str(e)
    k = e.get("k")
    if k == "num":
        v = e.get("v")
        return "{:,}".format(v) if isinstance(v, int) and abs(v) >= 10000 else str(v)
    if k == "var":
        return str(e.get("name") or "?")
    if k == "hits":
        return "hits of %s this ball" % (e.get("shot") or "?")
    if k == "scored":
        return "shots scored in the mode"
    if k == "total":
        return "points so far"
    if k == "secs_left":
        return "seconds left"
    if k == "balls":
        return "balls in play"
    if k == "player":
        return "the player up"
    if k == "timer_left":
        return "ms left on %s" % (e.get("timer") or "?")
    if k == "combo_chain":                                           # PAD-708
        return "combos in a row"
    if k == "combo_steps":
        return "shots made of the combo %s" % (e.get("combo") or "?")
    if k == "op":
        sym = {"*": "×", "/": "÷", "-": "−"}.get(e.get("op"), e.get("op"))
        return "%s %s %s" % (val(e.get("a")), sym, val(e.get("b")))
    return cond(e)


def cond(e):
    """A condition in words."""
    if not isinstance(e, dict):
        return "?"
    k = e.get("k")
    if k == "cmp":
        sym = {">=": "≥", "<=": "≤", "!=": "≠", "=": "="}.get(e.get("op"), e.get("op"))
        return "%s %s %s" % (val(e.get("a")), sym, val(e.get("b")))
    if k == "and":
        return "%s and %s" % (cond(e.get("a")), cond(e.get("b")))
    if k == "or":
        return "%s or %s" % (cond(e.get("a")), cond(e.get("b")))
    if k == "not":
        return "not (%s)" % cond(e.get("a"))
    if k == "running":
        return "the mode is running"
    if k == "stock":
        return "one of the game's own modes runs"
    if k == "can_start":
        return "the mode could start now"
    if k == "lit":
        return "the mode is lit"
    if k == "shields_away":
        return "the shield targets face away"
    return val(e)


def _ms(v):
    if isinstance(v, dict) and v.get("k") == "num" and isinstance(v.get("v"), int):
        ms = v["v"]
        return ("%g s" % (ms / 1000.0)) if ms >= 1000 else "%d ms" % ms
    return val(v) + " ms"


#: op -> words (b -> str); every op in block_modes.STATEMENTS but "if" (a branch, not a sentence)
SAY = {
    "start_mode": lambda b: "Start the mode",
    "end_mode": lambda b: "End the mode",
    "light_mode": lambda b: "Light the mode at %s (%s, %s)" % (b.get("shot") or b.get("insert") or "?",
                                                               colour(b.get("color")), PATTERN_WORDS.get(b.get("pattern"), "")),
    "unlight_mode": lambda b: "Put out the light of %s" % (b.get("mode") or "this mode"),
    "add_time": lambda b: "Add %s s to the clock" % val(b.get("seconds")),
    "set_time": lambda b: ("Keep at least %s s on the clock" if b.get("at_least") else "Set the clock to %s s")
    % val(b.get("seconds")),
    "multiball": lambda b: "%s-ball multiball, ball save %s s" % (b.get("balls"), b.get("save", 0)),
    "ball_save": lambda b: "Ball save %s s" % b.get("seconds"),
    "game_wizard": lambda b: "%s the game's %s" % ("Start" if b.get("how") == "start" else "Light", b.get("name") or "mini-wizard"),
    "hold": lambda b: "Hold the %s for %s" % (b.get("what") or "magnet", _ms(b.get("ms"))),
    "scoop_hold": lambda b: "Hold %s in the scoop for %s" % (BM.SCOOP_WHICH.get(b.get("which"), "the ball"), _ms(b.get("ms"))),
    "let_go": lambda b: "Let go of %s" % ("everything" if b.get("what") == "*" else b.get("what")),
    "shield": lambda b: "Turn the shield %s" % BM.SHIELD_WHERE.get(b.get("where"), "?"),
    "building": lambda b: "Move the building to %s" % BM.BUILDING_FLOOR.get(str(b.get("floor")), "?"),
    "shake": lambda b: "Shake the cabinet %s for %s" % (b.get("strength") or "", _ms(b.get("ms"))),
    "shake_game": lambda b: "The game's %s shake" % (b.get("shake") or "?"),
    "score": lambda b: "Score %s" % points(b.get("points")),
    "set": lambda b: "Set %s to %s" % (b.get("var"), val(b.get("value"))),
    "change": lambda b: "Add %s to %s" % (val(b.get("by")), b.get("var")),
    "set_hits": lambda b: "Set the hits of %s to %s" % (b.get("shot"), val(b.get("value"))),
    "timer_start": lambda b: "Start the %s timer: %s" % (b.get("timer"), _ms(b.get("ms"))),
    "timer_stop": lambda b: "Stop the %s timer" % b.get("timer"),
    "callout": lambda b: "Callout: “%s”" % BM.CALLOUT_ROLES.get(b.get("role"), "sound %s" % b.get("id")),
    "words": lambda b: "Show “%s”" % (b.get("text") or ""),
    "light_shot": lambda b: "Light %s %s %s" % (b.get("shot") or b.get("insert"), colour(b.get("color")),
                                                  PATTERN_WORDS.get(b.get("pattern"), "")),
    "lights_off": lambda b: "Hand back %s" % ("every light" if b.get("shot") == "*" else "the %s lights" % (b.get("shot") or b.get("insert"))),
    "show": lambda b: "Light show: %s" % (("the mode's %s" % (b.get("name") or "?")) if b.get("show") == "mine"
                                          else BM.SHOWS.get(b.get("show"), ("its own steps",))[0]),
    "game_show": lambda b: "The game's show %s" % (b.get("name") or "?"),
    "log": lambda b: "Log “%s”" % (b.get("text") or ""),
    "clip": lambda b: "Play clip %s (%s)" % (b.get("clip"), BM.CLIP_WHERE.get(b.get("where"), "")),
    "sound": lambda b: "Play sound %s" % b.get("sound"),
    "music": lambda b: "Play the music %s" % (b.get("bed") or "(its own)"),   # PAD-658
    "hud_text": lambda b: "HUD %s: “%s”" % ("title" if b.get("which") == "title" else "line", b.get("text") or ""),
    "hud_counter": lambda b: "HUD counter %s = %s" % (b.get("counter"), val(b.get("value"))),
    "hud_gauge": lambda b: "HUD gauge = %s" % val(b.get("value")),
    "hud_progress": lambda b: "Progress panel shows %s" % val(b.get("value")),
    "hud_award": lambda b: "Award on the HUD: “%s”" % (b.get("text") or ""),
}
#: the block's family, as the page colours it (modes_blocks.js STMT_CLASS)
FAMILY = {"start_mode": "mode", "light_mode": "mode", "unlight_mode": "mode", "set_hits": "var", "end_mode": "mode",
          "add_time": "mode", "set_time": "mode", "multiball": "mode", "ball_save": "mode", "game_wizard": "mode", "score": "score",
          "set": "var", "change": "var", "if": "flow", "callout": "show", "words": "show", "light_shot": "show",
          "lights_off": "show", "show": "show", "game_show": "show", "log": "show", "clip": "own", "sound": "own", "music": "own",
          "timer_start": "timer", "timer_stop": "timer", "hud_text": "hud", "hud_counter": "hud", "hud_gauge": "hud", "hud_progress": "hud",
          "hud_award": "hud", "hold": "mech", "scoop_hold": "mech", "let_go": "mech", "shield": "mech",
          "building": "mech", "shake": "mech", "shake_game": "mech"}
FAMILY_COLOUR = {"hat": "#c28a12", "mode": "#8b5bd6", "score": "#2f9a5b", "var": "#c8553a", "timer": "#b0457e",
                 "flow": "#d77a21", "show": "#3a78c9", "hud": "#a8457a", "own": "#b8458f", "mech": "#5d6b7e"}


def say(b):
    if not isinstance(b, dict):
        return "?"
    f = SAY.get(b.get("op"))
    return f(b) if f else "(%s)" % b.get("op")


def hat(h):
    """A hat in words."""
    k = h.get("kind")
    when = {"idle": " (not running)", "running": " (running)"}.get(h.get("when"), "")
    if k == "mode_start":
        return "When the mode starts"
    if k == "mode_end":
        return "When the mode ends"
    if k == "shot":
        return "When %s is made%s" % (h.get("shot") or "?", when)
    if k == "any_shot":
        return "When any shot is made%s" % when
    if k == "switch":
        return "When any playfield switch is hit%s" % when
    if k == "every":
        return "Every %s s while it runs" % h.get("seconds")
    if k == "seconds_left":
        return "When %s s are left" % h.get("seconds")
    if k == "ball_end":
        return "When the ball drains"
    if k == "drain":
        return "When a ball goes into the trough%s" % when
    if k == "event":
        return "When the game: %s%s" % (h.get("event") or "?", when)
    if k == "timer_done":
        return "When %s runs out" % (h.get("timer") or "a timer")
    if k == "challenge":
        return "When the player picks the challenge %s" % (h.get("challenge") or "?")
    if k == "combo":                                                 # PAD-708
        steps = [" or ".join(x) if isinstance(x, list) else {"lit": "a lit shot", "*": "any shot"}.get(x, x or "?")
                 for x in h.get("shots") or []]
        return "When %s within %s s%s" % (", then ".join(steps) or "?", h.get("seconds"), when)
    if k == "battle":                                                       # PAD-706
        return "When the player picks the battle %s" % BM.battle_name(h)
    return "(%s)" % k


def lines(stack, depth=0):
    """The blocks of a stack as (depth, family, words), an If as its condition and its branches."""
    out = []
    for b in stack or []:
        if isinstance(b, dict) and b.get("op") == "if":
            out.append((depth, "flow", "If %s" % cond(b.get("cond"))))
            out += lines(b.get("then"), depth + 1)
            if b.get("else") is not None:
                out.append((depth, "flow", "Otherwise"))
                out += lines(b.get("else"), depth + 1)
        else:
            out.append((depth, FAMILY.get(b.get("op"), "show") if isinstance(b, dict) else "show", say(b)))
    return out
