"""JJP custom modes made of blocks (PAD-1384): the program the Blocks editor edits, and the C++
it makes.

On Stern a blocks mode is C the build compiles (plugins/stern/block_modes.py); on a Jersey Jack
game it is C++ against the JJP mode SDK's ``tools/jjp_emu/modes/sdk/jjp_mode.h``, which the
runtime (jjpmodes.so, inside the game) loads beside the mode file.  A blocks mode is three files
in the title's mode folder:

* ``<n>_<slug>.mode`` - its settings (name, start, scoring shots, seconds, sounds, lamps,
  screen): the same form every JJP mode has, with ``code = <slug>``;
* ``<slug>.blocks.json`` - the program below;
* ``<slug>.cpp`` - what the program makes, written again at every change (``to_cpp``); the app
  builds it to ``<slug>.so`` (mkjjpmodes.py code) before a check, a stick or an ISO.

The program (the Stern program's shape, with JJP's own hats and blocks)::

    {"format": 1,
     "vars": [{"name": "bonus", "reset": "mode" | "kept"}],
     "scripts": [{"hat": {"kind": ...}, "do": [statement, ...]}]}

hats: mode_start, mode_end, shot {shot: <switch>, when: running | idle}, any_shot (a scoring
shot the form scored), every {seconds}, seconds_left {seconds}.
statements: start_mode (from a "while it is not running" script), end_mode, add_time {seconds},
set_time {seconds, at_least}, multiball {balls, save}, ball_save {seconds}, score {points},
set {var, value}, change {var, by}, if {cond, then, else}, jjp_sound {sound}, jjp_lamp {lamp,
color, blink}, jjp_lamp_off {lamp}, jjp_title {text, value}, jjp_coil {coil, ms}, log {text}.
values: num {v}, var {name}, hits {shot} (a switch's hits this run), scored (the form's scoring
shots made), total, secs_left, op {op, a, b}.  conditions: cmp {op, a, b}, and, or, not, running.
"""
import json
import os
import re

FORMAT = 1
HATS = ("mode_start", "mode_end", "shot", "any_shot", "every", "seconds_left")
OPS = ("start_mode", "end_mode", "add_time", "set_time", "multiball", "ball_save", "score", "set",
       "change", "if", "jjp_sound", "jjp_lamp", "jjp_lamp_off", "jjp_title", "jjp_coil", "log")
VALUES = ("num", "var", "hits", "scored", "total", "secs_left", "op")
CONDS = ("cmp", "and", "or", "not", "running")
RESETS = ("mode", "kept")
ARITH = {"+": "+", "-": "-", "*": "*", "/": "/"}
CMPS = {"<": "<", "<=": "<=", "=": "==", "!=": "!=", ">=": ">=", ">": ">"}
SUFFIX = ".blocks.json"


# ============================================================================ the program
def normalize(program):
    """A program as the editor and to_cpp read it: every list there, unknown things dropped."""
    p = dict(program or {})
    out = {"format": FORMAT}
    vars_ = []
    seen = set()
    for v in p.get("vars") or []:
        name = str((v or {}).get("name") or "").strip()[:24]
        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())
        vars_.append({"name": name, "reset": v.get("reset") if v.get("reset") in RESETS else "mode"})
    out["vars"] = vars_
    out["scripts"] = [{"hat": dict((s or {}).get("hat") or {}), "do": list((s or {}).get("do") or [])}
                      for s in p.get("scripts") or [] if ((s or {}).get("hat") or {}).get("kind") in HATS]
    return out


def starter(defaults=None, name="New Mode"):
    """A first program for a new blocks mode: a bonus that grows with each scoring shot, its
    first lamp lit green while it runs, and a word in the log at 5 seconds left."""
    d = defaults or {}
    lamp = (d.get("lamps") or "").split()
    start = [{"op": "set", "var": "bonus", "value": {"k": "num", "v": 0}}]
    if lamp:
        start.append({"op": "jjp_lamp", "lamp": lamp[0], "color": "#00ff40", "blink": 0})
    return normalize({
        "vars": [{"name": "bonus", "reset": "mode"}],
        "scripts": [
            {"hat": {"kind": "mode_start"}, "do": start},
            {"hat": {"kind": "any_shot"}, "do": [
                {"op": "change", "var": "bonus", "by": {"k": "num", "v": 250000}},
                {"op": "score", "points": {"k": "var", "name": "bonus"}}]},
            {"hat": {"kind": "seconds_left", "seconds": 5}, "do": [
                {"op": "log", "text": "%s: 5 seconds left" % name}]},
        ]})


def load(path):
    with open(path, encoding="utf-8") as f:
        return normalize(json.load(f))


def save(path, program):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(normalize(program), f, indent=1)
        f.write("\n")
    os.replace(tmp, path)


# ============================================================================ checks
def _walk(stmts, fn, path):
    for i, b in enumerate(stmts or []):
        if not isinstance(b, dict):
            continue
        fn(b, path + [i])
        if b.get("op") == "if":
            _walk(b.get("then"), fn, path + [i, "then"])
            _walk(b.get("else"), fn, path + [i, "else"])


def _values(x):
    """Every value and condition inside a statement, a value or a condition."""
    if isinstance(x, dict):
        if "k" in x:
            yield x
        for k, v in x.items():
            if k in ("then", "else"):
                continue
            yield from _values(v)
    elif isinstance(x, list):
        for v in x:
            yield from _values(v)


def problems(program, names=None):
    """What stops the program making C++ that does what it says (empty: none).  *names*: the
    title's {switches, lamps, sound, coil_pulse} lists, to check its picks against."""
    prog = normalize(program)
    names = names or {}
    out = []
    var_names = {v["name"] for v in prog["vars"]}
    known = {k: set(names.get(k) or ()) for k in ("switches", "lamps", "sound", "coil_pulse")}
    if not prog["scripts"]:
        out.append("No scripts yet: start with a When block.")

    def name_ok(kind, v, what):
        if not v:
            out.append("%s: no %s picked" % (what, kind_word(kind)))
        elif known.get(kind) and v not in known[kind]:
            out.append("%s: %s is not on this game" % (what, v))

    for si, s in enumerate(prog["scripts"]):
        h = s["hat"]
        where = "Script %d (%s)" % (si + 1, hat_words(h))
        if h["kind"] == "shot":
            name_ok("switches", h.get("shot"), where)
        if h["kind"] in ("every", "seconds_left") and not _pos_num(h.get("seconds")):
            out.append("%s: the seconds must be a number above 0" % where)
        idle = h["kind"] == "shot" and h.get("when") == "idle"

        def stmt(b, _path, where=where, idle=idle):
            op = b.get("op")
            if op not in OPS:
                out.append("%s: a block this game cannot run (%s)" % (where, op))
                return
            if op == "start_mode" and not idle:
                out.append("%s: Start the mode works only in a When a switch is hit while it is not running"
                           " script (it is already running here)" % where)
            if op in ("set", "change") and b.get("var") not in var_names:
                out.append("%s: %s names no variable of this mode" % (where, stmt_words(b)))
            if op == "jjp_sound":
                name_ok("sound", b.get("sound"), where)
            if op in ("jjp_lamp", "jjp_lamp_off"):
                name_ok("lamps", b.get("lamp"), where)
            if op == "jjp_coil":
                name_ok("coil_pulse", b.get("coil"), where)
            if op == "if" and not b.get("cond"):
                out.append("%s: an If with an empty condition" % where)
            slots = {"score": "points", "add_time": "seconds", "set_time": "seconds", "set": "value", "change": "by"}
            if op in slots and not isinstance(b.get(slots[op]), dict):
                out.append("%s: %s has an empty slot" % (where, stmt_words(b)))
            for v in _values({k: v for k, v in b.items() if k not in ("then", "else")}):
                if v.get("k") == "var" and v.get("name") not in var_names:
                    out.append("%s: a value names the variable %r, which this mode does not have" % (where, v.get("name")))
                if v.get("k") == "hits":
                    name_ok("switches", v.get("shot"), where)
                if v.get("k") in ("op", "cmp", "and", "or") and (not isinstance(v.get("a"), dict) or not isinstance(v.get("b"), dict)):
                    out.append("%s: a sum or a comparison has an empty slot" % where)
                if v.get("k") == "not" and not isinstance(v.get("a"), dict):
                    out.append("%s: a Not has an empty slot" % where)
        _walk(s["do"], stmt, [])
    seen, uniq = set(), []
    for p in out:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def kind_word(kind):
    return {"switches": "switch", "lamps": "lamp", "sound": "sound", "coil_pulse": "coil"}.get(kind, kind)


def _pos_num(v):
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def hat_words(h):
    k = h.get("kind")
    return {"mode_start": "when the mode starts", "mode_end": "when the mode ends",
            "shot": "when %s is hit%s" % (h.get("shot") or "a switch",
                                          " while it is not running" if h.get("when") == "idle" else ""),
            "any_shot": "when a scoring shot is made", "every": "every %s s" % h.get("seconds"),
            "seconds_left": "at %s s left" % h.get("seconds")}.get(k, k)


def stmt_words(b):
    return {"set": "Set a variable", "change": "Change a variable", "score": "Score", "add_time": "Add seconds",
            "set_time": "Set the clock"}.get(b.get("op"), b.get("op"))


# ============================================================================ C++
def _str(s):
    """A C string literal of *s* (printable ASCII only)."""
    s = "".join(c for c in str(s or "") if 32 <= ord(c) < 127)
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _ident(name, i):
    base = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()[:24] or "v"
    return "v%d_%s" % (i, base)


class _Gen:
    def __init__(self, prog):
        self.prog = prog
        self.var = {v["name"]: _ident(v["name"], i) for i, v in enumerate(prog["vars"])}

    def val(self, v):
        if not isinstance(v, dict):
            return "0LL"
        k = v.get("k")
        if k == "num":
            try:
                n = float(str(v.get("v")).replace(",", ""))
            except ValueError:
                return "0LL"
            return "%dLL" % int(n) if n == int(n) else repr(n)
        if k == "var":
            return self.var.get(v.get("name"), "0LL")
        if k == "hits":
            return "(long long)jm_switch_hits(%s)" % _str(v.get("shot"))
        if k == "scored":
            return "(long long)jm_hits()"
        if k == "total":
            return "jm_total()"
        if k == "secs_left":
            return "(long long)jm_seconds_left()"
        if k == "op":
            a, b, op = self.val(v.get("a")), self.val(v.get("b")), ARITH.get(v.get("op"), "+")
            if op == "/":
                return "jb_div(%s, %s)" % (a, b)
            return "(%s %s %s)" % (a, op, b)
        return "0LL"

    def cond(self, c):
        if not isinstance(c, dict):
            return "false"
        k = c.get("k")
        if k == "cmp":
            return "(%s %s %s)" % (self.val(c.get("a")), CMPS.get(c.get("op"), ">="), self.val(c.get("b")))
        if k == "and":
            return "(%s && %s)" % (self.cond(c.get("a")), self.cond(c.get("b")))
        if k == "or":
            return "(%s || %s)" % (self.cond(c.get("a")), self.cond(c.get("b")))
        if k == "not":
            return "!%s" % self.cond(c.get("a"))
        if k == "running":
            return "(jm_running() != 0)"
        return "false"

    def stmts(self, lst, ind):
        out = []
        for b in lst or []:
            out.extend(self.stmt(b, ind))
        return out

    def stmt(self, b, ind):
        t = "    " * ind
        op = (b or {}).get("op")
        if op == "start_mode":
            return [t + "jm_start();"]
        if op == "end_mode":
            return [t + "jm_end();"]
        if op == "add_time":
            return [t + "jm_add_seconds((int)(%s));" % self.val(b.get("seconds"))]
        if op == "set_time":
            s = self.val(b.get("seconds"))
            if b.get("at_least"):
                return [t + "if (jm_seconds_left() < (int)(%s)) jm_set_seconds((int)(%s));" % (s, s)]
            return [t + "jm_set_seconds((int)(%s));" % s]
        if op == "multiball":
            return [t + "jm_multiball(%d, %d);" % (_int(b.get("balls"), 2), _int(b.get("save"), 10))]
        if op == "ball_save":
            return [t + "jm_ball_save(%d);" % _int(b.get("seconds"), 10)]
        if op == "score":
            return [t + "jm_score(%s);" % self.val(b.get("points"))]
        if op == "set" and b.get("var") in self.var:
            return [t + "%s = %s;" % (self.var[b["var"]], self.val(b.get("value")))]
        if op == "change" and b.get("var") in self.var:
            return [t + "%s += %s;" % (self.var[b["var"]], self.val(b.get("by")))]
        if op == "if":
            lines = [t + "if (%s) {" % self.cond(b.get("cond"))] + self.stmts(b.get("then"), ind + 1)
            if b.get("else") is not None:
                lines += [t + "} else {"] + self.stmts(b.get("else"), ind + 1)
            return lines + [t + "}"]
        if op == "jjp_sound":
            return [t + "jm_sound(%s);" % _str(b.get("sound"))]
        if op == "jjp_lamp":
            return [t + "jm_lamp(%s, 0x%06x, %d);" % (_str(b.get("lamp")), _rgb(b.get("color")), _int(b.get("blink"), 0))]
        if op == "jjp_lamp_off":
            return [t + "jm_lamp_off(%s);" % _str(b.get("lamp"))]
        if op == "jjp_title":
            if isinstance(b.get("value"), dict):
                return [t + "{ static char jb_t[64]; snprintf(jb_t, sizeof jb_t, \"%%s %%lld\", %s, (long long)(%s)); jm_title(jb_t); }"
                        % (_str(b.get("text")), self.val(b.get("value")))]
            return [t + "jm_title(%s);" % _str(b.get("text"))]
        if op == "jjp_coil":
            return [t + "jm_coil(%s, %d);" % (_str(b.get("coil")), _int(b.get("ms"), 0))]
        if op == "log":
            return [t + "jm_log(\"%%s\", %s);" % _str(b.get("text"))]
        return [t + "/* %s: not on this game */" % re.sub(r"[^a-z_]", "", str(op))]


def _int(v, dflt):
    try:
        return int(float(str(v).replace(",", "")))
    except (TypeError, ValueError):
        return dflt


def _rgb(c):
    m = re.match(r"^#?([0-9a-fA-F]{6})$", str(c or ""))
    return int(m.group(1), 16) if m else 0xffffff


def to_cpp(program, name="", code=""):
    """The C++ a program makes (jjp_mode.h): one function per moment, its scripts in order."""
    prog = normalize(program)
    g = _Gen(prog)
    by = {}
    for i, s in enumerate(prog["scripts"]):
        by.setdefault(s["hat"]["kind"], []).append((i, s))
    L = ["// %s - made of blocks in the app's Modes tab (PAD-1384)." % (name or code or "A mode"),
         "// The app writes this file again from %s%s at every change: change the blocks, not this." % (code or "its", SUFFIX),
         "// Its settings (start, scoring shots, seconds, sounds, lamps, screen) are its .mode file.",
         '#include "jjp_mode.h"', ""]
    for v in prog["vars"]:
        L.append("static long long %s;   // %s (%s)" % (g.var[v["name"]], v["name"].replace("*/", ""),
                                                        "each time it starts" if v["reset"] == "mode" else "kept"))
    timed = [(i, s) for i, s in by.get("every", [])]
    left = [(i, s) for i, s in by.get("seconds_left", [])]
    for i, _s in timed:
        L.append("static long jb_every_%d;" % i)
    for i, _s in left:
        L.append("static bool jb_left_%d;" % i)
    if any(v.get("k") == "op" and v.get("op") == "/" for s in prog["scripts"] for v in _values(s)):
        L += ["static long long jb_div(long long a, long long b) { return b ? a / b : 0; }"]
    L.append("")
    regs = []

    def fn(sig, body, reg):
        L.append(sig)
        L.append("{")
        L.extend(body)
        L.append("}")
        L.append("")
        regs.append(reg)

    start = ["    %s = 0;" % g.var[v["name"]] for v in prog["vars"] if v["reset"] == "mode"]
    start += ["    jb_every_%d = 0;" % i for i, _s in timed] + ["    jb_left_%d = false;" % i for i, _s in left]
    for i, s in by.get("mode_start", []):
        start += ["    // script %d" % (i + 1)] + g.stmts(s["do"], 1)
    if start:
        fn("static void start()", start, ".start = start")
    running = [(i, s) for i, s in by.get("shot", []) if s["hat"].get("when") != "idle"]
    if running:
        body = []
        for i, s in running:
            body += ["    if (jm_is(sw, %s)) {   // script %d" % (_str(s["hat"].get("shot")), i + 1)]
            body += g.stmts(s["do"], 2) + ["    }"]
        fn("static int shot(const char *sw)", body + ["    return JM_GO_ON;"], ".shot = shot")
    if by.get("any_shot"):
        body = ["    (void)sw;"]
        for i, s in by["any_shot"]:
            body += ["    // script %d" % (i + 1)] + g.stmts(s["do"], 1)
        fn("static void scored(const char *sw)", body, ".scored = scored")
    if timed or left:
        body = []
        for i, s in timed:
            ms = max(100, int(float(s["hat"].get("seconds") or 1) * 1000)) if _pos_num(s["hat"].get("seconds")) else 1000
            body += ["    if (jm_ms() - jb_every_%d >= %d) {   // script %d: every %s s" % (i, ms, i + 1, s["hat"].get("seconds")),
                     "        jb_every_%d += %d;" % (i, ms)] + g.stmts(s["do"], 2) + ["    }"]
        for i, s in left:
            secs = _int(s["hat"].get("seconds"), 5)
            body += ["    if (!jb_left_%d && jm_seconds_left() <= %d) {   // script %d" % (i, secs, i + 1),
                     "        jb_left_%d = true;" % i] + g.stmts(s["do"], 2) + ["    }"]
        fn("static void tick()", body, ".tick = tick")
    if by.get("mode_end"):
        body = ["    (void)why;"]
        for i, s in by["mode_end"]:
            body += ["    // script %d" % (i + 1)] + g.stmts(s["do"], 1)
        fn("static void end(const char *why)", body, ".end = end")
    idle = [(i, s) for i, s in by.get("shot", []) if s["hat"].get("when") == "idle"]
    if idle:
        body = []
        for i, s in idle:
            body += ["    if (jm_is(sw, %s)) {   // script %d" % (_str(s["hat"].get("shot")), i + 1)]
            body += g.stmts(s["do"], 2) + ["    }"]
        fn("static void idle(const char *sw)", body, ".idle = idle")
    L.append("JM_REGISTER({ .api = JM_API%s });" % "".join(", " + r for r in regs))
    return "\n".join(L) + "\n"
