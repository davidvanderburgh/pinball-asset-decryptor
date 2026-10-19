"""PAD-611: the mode every view mockup draws - a whole blocks mode on Godzilla Pro 1.15's shots.

RAMP FRENZY: three Left ramps start it; while it runs every shot scores more with a growing combo, the Right ramp is
a jackpot that adds time and opens a four-second window in which the Big loop is a super jackpot; ten seconds from
the end the callout plays and the ramp hurries; at the end a rainbow for three jackpots or more, else a fizzle.
It uses a hat of nearly every kind, variables, a timer, if / else, the HUD, light shows and lit shots: enough that
each view has to show the hard parts, not only the easy ones. ``block_modes.problems`` finds nothing wrong with it.
"""
from pinball_decryptor.plugins.stern import block_modes as BM

SHOTS = ("Left ramp", "Right ramp", "Building", "Godzilla target", "Maser target", "Powerline left",
         "Powerline center", "Powerline right", "Big loop", "Left spinner", "Top spinner", "Right spinner")


def num(v):
    return {"k": "num", "v": v}


def var(n):
    return {"k": "var", "name": n}


def program():
    return BM.normalize({
        "name": "RAMP FRENZY", "seconds": 30, "ends_on_drain": True, "wait_multiball": True, "priority": 180,
        "vars": [{"name": "combo", "reset": "mode"}, {"name": "jackpots", "reset": "mode"}],
        "timers": [{"name": "window"}],
        "hud": {"on": True, "line": "SHOOT THE RAMPS",
                "counters": [{"label": "COMBO", "sub": "", "value": var("combo")},
                             {"label": "JACKPOTS", "sub": "", "value": var("jackpots")}],
                "timer": {"on": True, "label": "FRENZY", "icon": "maser"}},
        "scripts": [
            {"hat": {"kind": "shot", "shot": "Left ramp", "when": "idle"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": {"k": "hits", "shot": "Left ramp"}, "b": num(3)},
                 "then": [{"op": "start_mode"}], "else": None}]},
            {"hat": {"kind": "mode_start"}, "do": [
                {"op": "set", "var": "combo", "value": num(1)},
                {"op": "light_shot", "shot": "Right ramp", "color": "#ffd000", "pattern": "blink", "rate": None},
                {"op": "show", "show": "burst"}]},
            {"hat": {"kind": "any_shot", "when": "running"}, "do": [
                {"op": "score", "points": {"k": "op", "op": "*", "a": num(500000), "b": var("combo")}},
                {"op": "change", "var": "combo", "by": num(1)}]},
            {"hat": {"kind": "shot", "shot": "Right ramp", "when": "running"}, "do": [
                {"op": "score", "points": num(5000000)},
                {"op": "add_time", "seconds": num(5)},
                {"op": "change", "var": "jackpots", "by": num(1)},
                {"op": "timer_start", "timer": "window", "ms": num(4000)},
                {"op": "light_shot", "shot": "Big loop", "color": "#00a0ff", "pattern": "chase", "rate": None},
                {"op": "hud_award", "text": "JACKPOT", "value": None, "sub": "", "seconds": 2}]},
            {"hat": {"kind": "shot", "shot": "Big loop", "when": "running"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">", "a": {"k": "timer_left", "timer": "window"}, "b": num(0)},
                 "then": [{"op": "score", "points": num(15000000)}, {"op": "show", "show": "lightning"},
                          {"op": "hud_award", "text": "SUPER JACKPOT", "value": None, "sub": "", "seconds": 3}],
                 "else": [{"op": "hud_text", "which": "line", "text": "RIGHT RAMP FIRST", "value": None}]}]},
            {"hat": {"kind": "timer_done", "timer": "window"}, "do": [
                {"op": "lights_off", "shot": "Big loop"}]},
            {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [
                {"op": "callout", "role": "ten_seconds"},
                {"op": "light_shot", "shot": "Right ramp", "color": "#ffd000", "pattern": "hurry", "rate": None}]},
            {"hat": {"kind": "mode_end"}, "do": [
                {"op": "if", "cond": {"k": "cmp", "op": ">=", "a": var("jackpots"), "b": num(3)},
                 "then": [{"op": "show", "show": "rainbow"}], "else": [{"op": "show", "show": "fizzle"}]},
                {"op": "lights_off", "shot": "*"}]},
            {"hat": {"kind": "ball_end"}, "do": [
                {"op": "log", "text": "drained in the frenzy"}]},
        ]})
