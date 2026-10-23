"""blk.py - the blocks examples' Python (PAD-658): short words for writing a blocks.json program by hand.

Every function returns the plain dict the Modes tab's block editor reads and writes (pinball_decryptor/plugins/
stern/block_modes.py documents each), so a program written here is exactly one a person could have snapped
together on the page, and opens there to be changed. ``make_examples.py`` writes each example's JSON from it.
"""


# ---- values -------------------------------------------------------------------------------------------------
def num(v):
    return {"k": "num", "v": int(v)}


def _v(x):
    """A number, a variable's name, or a value already made."""
    if isinstance(x, dict):
        return x
    if isinstance(x, str):
        return var(x)
    return num(x)


def var(name):
    return {"k": "var", "name": name}


def hits(shot):
    return {"k": "hits", "shot": shot}


def timer_left(name):
    return {"k": "timer_left", "timer": name}


SECS_LEFT = {"k": "secs_left"}
TOTAL = {"k": "total"}
SCORED = {"k": "scored"}
BALLS = {"k": "balls"}


def _op(o, a, b):
    return {"k": "op", "op": o, "a": _v(a), "b": _v(b)}


def add(a, b):
    return _op("+", a, b)


def sub(a, b):
    return _op("-", a, b)


def mul(a, b):
    return _op("*", a, b)


def div(a, b):
    return _op("/", a, b)


# ---- conditions -----------------------------------------------------------------------------------------------
def _cmp(o, a, b):
    return {"k": "cmp", "op": o, "a": _v(a), "b": _v(b)}


def eq(a, b):
    return _cmp("=", a, b)


def ne(a, b):
    return _cmp("!=", a, b)


def ge(a, b):
    return _cmp(">=", a, b)


def gt(a, b):
    return _cmp(">", a, b)


def le(a, b):
    return _cmp("<=", a, b)


def lt(a, b):
    return _cmp("<", a, b)


def AND(a, b, *more):
    out = {"k": "and", "a": a, "b": b}
    for m in more:
        out = {"k": "and", "a": out, "b": m}
    return out


def OR(a, b, *more):
    out = {"k": "or", "a": a, "b": b}
    for m in more:
        out = {"k": "or", "a": out, "b": m}
    return out


def NOT(a):
    return {"k": "not", "a": a}


RUNNING = {"k": "running"}
STOCK = {"k": "stock"}
CAN_START = {"k": "can_start"}
LIT = {"k": "lit"}
SHIELDS_AWAY = {"k": "shields_away"}      # PAD-690


# ---- what sets a script off --------------------------------------------------------------------------------
def on_start(*do):
    return {"hat": {"kind": "mode_start"}, "do": list(do)}


def on_end(*do):
    return {"hat": {"kind": "mode_end"}, "do": list(do)}


def on_shot(shot, *do, when="running"):
    return {"hat": {"kind": "shot", "shot": shot, "when": when}, "do": list(do)}


def on_any_shot(*do, when="running"):
    return {"hat": {"kind": "any_shot", "when": when}, "do": list(do)}


def on_switch(*do, when="idle"):
    """PAD-675: every playfield switch's own hit (the game's 0x1 dispatch), as the C modes counted them."""
    return {"hat": {"kind": "switch", "when": when}, "do": list(do)}


def every(seconds, *do):
    return {"hat": {"kind": "every", "seconds": int(seconds)}, "do": list(do)}


def secs_left(seconds, *do):
    return {"hat": {"kind": "seconds_left", "seconds": int(seconds)}, "do": list(do)}


def on_drain(*do):
    return {"hat": {"kind": "ball_end"}, "do": list(do)}


def on_event(event, *do, when="any"):
    return {"hat": {"kind": "event", "event": event, "when": when}, "do": list(do)}


def on_timer(name, *do):
    return {"hat": {"kind": "timer_done", "timer": name}, "do": list(do)}


# ---- blocks ----------------------------------------------------------------------------------------------------
def start():
    return {"op": "start_mode"}


def end():
    return {"op": "end_mode"}


def score(points):
    return {"op": "score", "points": _v(points)}


def set_(name, value):
    return {"op": "set", "var": name, "value": _v(value)}


def change(name, by):
    return {"op": "change", "var": name, "by": _v(by)}


def if_(cond, then, else_=None):
    return {"op": "if", "cond": cond, "then": list(then), "else": list(else_) if else_ else None}


def callout(role):
    return {"op": "callout", "role": role}


def light(shot, color, pattern="blink", rate=None):
    b = {"op": "light_shot", "shot": shot, "color": color, "pattern": pattern}
    if rate is not None:
        b["rate"] = _v(rate)
    return b


def light_insert(insert, color, pattern="blink", rate=None):
    """One of the game's own lights by its name (an insert, a GI string or a flasher)."""
    b = {"op": "light_shot", "insert": insert, "color": color, "pattern": pattern}
    if rate is not None:
        b["rate"] = _v(rate)
    return b


def off(shot):
    """Hand a shot's lights back to the game ("*" = every light the mode holds)."""
    return {"op": "lights_off", "shot": shot}


def off_insert(insert):
    return {"op": "lights_off", "insert": insert}


def add_time(seconds):
    return {"op": "add_time", "seconds": _v(seconds)}


def set_time(seconds, at_least=False):
    """Set the clock; ``at_least``: Keep at least ``seconds`` on it (up to it when under, else left alone)."""
    b = {"op": "set_time", "seconds": _v(seconds)}
    if at_least:
        b["at_least"] = True
    return b


def multiball(balls, save=0):
    return {"op": "multiball", "balls": int(balls), "save": int(save)}


def log(text):
    return {"op": "log", "text": text}


def clip(name, where="full"):
    """One of the mode's own clips: "full" screen, "behind" the HUD once, or "loop" behind it while it runs."""
    return {"op": "clip", "clip": name, "where": where}


def sound(name, fallback=""):
    return {"op": "sound", "sound": name, "fallback": fallback}


def show(name):
    """One of the mode's own light shows, by name."""
    return {"op": "show", "show": "mine", "name": name}


def game_show(name):
    return {"op": "game_show", "name": name}


def timer_start(name, ms):
    return {"op": "timer_start", "timer": name, "ms": _v(ms)}


def timer_stop(name):
    return {"op": "timer_stop", "timer": name}


def hud_title(text, value=None):
    return {"op": "hud_text", "which": "title", "text": text, "value": _v(value) if value is not None else None}


def hud_line(text, value=None):
    return {"op": "hud_text", "which": "line", "text": text, "value": _v(value) if value is not None else None}


def hud_counter(n, value, sub=None, label=None):
    """Counter n (1-3) to a value; its line under it, and (PAD-658) its label, from now on when given."""
    b = {"op": "hud_counter", "counter": int(n), "value": _v(value), "sub": sub}
    if label is not None:
        b["label"] = label
    return b


def hud_gauge(value):
    return {"op": "hud_gauge", "value": _v(value)}


def award(text, value=None, sub="", seconds=2):
    return {"op": "hud_award", "text": text, "value": _v(value) if value is not None else None, "sub": sub,
            "seconds": int(seconds)}


def shake(ms, strength="hard"):
    return {"op": "shake", "ms": _v(ms), "strength": strength}


def shake_game(name):
    return {"op": "shake_game", "shake": name}


def scoop_hold(ms, which="next"):
    """Hold the next ball (or every ball) that settles in the scoop for ms while the mode runs."""
    return {"op": "scoop_hold", "ms": _v(ms), "which": which}


def shield(where):
    return {"op": "shield", "where": where}


def set_hits(shot, value):
    return {"op": "set_hits", "shot": shot, "value": _v(value)}


def light_mode(shot, color, pattern="blink", insert="", solid="", solid_color=None):
    b = {"op": "light_mode", "shot": shot, "color": color, "pattern": pattern, "insert": insert}
    if solid:
        b["solid"] = solid
        b["solid_color"] = solid_color or color
    return b


def unlight_mode(mode=""):
    return {"op": "unlight_mode", "mode": mode}


# ---- light shows -------------------------------------------------------------------------------------------------
def step(fx, ms, a, b="#000000", at="center", rate=0, gi="keep", blend=0, x=None, y=None):
    st = {"fx": fx, "ms": int(ms), "a": a, "b": b, "at": at, "rate": int(rate), "gi": gi}
    if blend:
        st["blend"] = int(blend)
    if at == "xy":
        st["x"], st["y"] = int(x), int(y)
    return st


def at_xy(x, y):
    """A step's place: a point of the playfield picture (an insert's own place, as the port's lamp lines say)."""
    return {"at": "xy", "x": x, "y": y}


def a_show(name, *steps, repeat=1):
    return {"name": name, "steps": list(steps), "repeat": int(repeat)}


# ---- media named by cue: <cue>.mp4 / <cue>.wav, as the example's recipe cuts them ---------------------------------
def clips(*cues):
    return [{"name": c, "file": c + ".mp4"} for c in cues]


def beds(*names):
    """PAD-658: further music beds by name -> the program's beds (music_<name>.wav, as the recipe cuts them)."""
    return [{"name": n, "file": "music_%s.wav" % n} for n in names]


def music(bed=""):
    """Switch the running music to bed ``bed`` ("" = its own music again)."""
    return {"op": "music", "bed": bed}


def sounds(priorities):
    """``{cue: priority}`` -> the program's sounds."""
    return [{"name": c, "file": c + ".wav", "priority": int(p)} for c, p in priorities.items()]


def hud(line, counters=(), timer=None, gauge=None):
    """The HUD: ``counters`` [(label, sub, value)], ``timer`` (label, icon), ``gauge`` dict."""
    out = {"on": True, "line": line,
           "counters": [{"label": l, "sub": s, "value": _v(v) if v is not None else None} for l, s, v in counters]}
    out["timer"] = {"on": bool(timer), "label": timer[0] if timer else "", "icon": timer[1] if timer else "xilien"}
    if gauge:
        g = dict(gauge)
        if g.get("value") is not None:
            g["value"] = _v(g["value"])
        out["gauge"] = dict(g, on=True)
    return out
