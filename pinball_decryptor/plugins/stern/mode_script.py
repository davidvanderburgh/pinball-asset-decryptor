"""PAD-611: a blocks mode as a SCRIPT - text a person can type, that is the same program as the blocks.

The Modes tab's Script view (PAD-614; first drawn as one of PAD-611's alternatives,
docs/plans/pad611_mode_making_alternatives.md, "Script"): the blocks.json the Modes tab edits, written as lines of Python-shaped text and read back to exactly the same program.
Nothing is lost either way (tests/test_pad611_mode_script.py turns every block there is out and back), so a person
can move between the blocks and the script whenever they like - unlike "Edit as C", which is a one-way door.

    name = "RAMP FRENZY"
    seconds = 30
    vars = [{"name": "combo", "reset": "mode"}]

    with on.shot(shot="Left ramp", when="idle"):
        if hits(shot="Left ramp") >= 3:
            start_mode()

    with on.any_shot(when="running"):
        score(points=500000 * combo)
        change(var="combo", by=1)

The text is parsed with Python's own parser (``ast``), never run. A block, hat or value the plain form cannot carry
exactly (a key the page does not know, a value of an unusual kind) is written as ``block({...})`` /
``expr({...})`` / ``script({...})`` with its JSON in full, so the round trip is exact for any program.
"""
from __future__ import annotations

import ast
import json
import keyword
import re

from . import block_modes as BM

#: the fields of a block that hold a VALUE (a number the mode works out while it runs: block_modes._Gen.num); a plain
#: number written there is read back as {"k": "num", "v": n}
VALUE_FIELDS = {
    "score": {"points"}, "set": {"value"}, "change": {"by"}, "set_hits": {"value"}, "timer_start": {"ms"},
    "words": {"value"}, "light_shot": {"rate"}, "add_time": {"seconds"}, "set_time": {"seconds"},
    "hud_text": {"value"}, "hud_counter": {"value"}, "hud_gauge": {"value"}, "hud_award": {"value"},
    "hold": {"ms"}, "scoop_hold": {"ms"}, "shake": {"ms"},
}
NUM_KINDS = ("num", "var", "hits", "scored", "total", "secs_left", "balls", "player", "op", "timer_left")
BOOL_KINDS = ("cmp", "and", "or", "not", "running", "stock", "can_start", "lit", "shields_away")
#: value kinds written as a call of their own name, with their fields as keywords: hits(shot="Left ramp")
CALL_KINDS = {"hits", "scored", "total", "secs_left", "balls", "player", "timer_left", "running", "stock",
              "can_start", "lit", "shields_away"}
BINOPS = {"+": ast.Add, "-": ast.Sub, "*": ast.Mult, "/": ast.Div}
CMPOPS = {"<": ast.Lt, "<=": ast.LtE, "=": ast.Eq, "!=": ast.NotEq, ">=": ast.GtE, ">": ast.Gt}
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
#: the names a bare variable must not take: what the script itself calls
RESERVED = CALL_KINDS | {"num", "var", "raw", "expr", "block", "script", "on", "True", "False", "None"}
INDENT = "    "


class ScriptError(ValueError):
    """Text that is not a mode script; the message says where, ``line`` the line (0: not one line)."""

    def __init__(self, msg, line=0):
        super().__init__(msg)
        self.line = line


#: PAD-614: the plain form names only the blocks and hats there are (a misspelt one is an error on its line, not a
#: block the mode cannot run); any other is written and read as block({...}) / script({...}), kept exactly
OPS = frozenset(BM.STATEMENTS)
HAT_KINDS = frozenset(BM.HATS)


# ---- writing ----------------------------------------------------------------------------------------------------
def lit(v):
    """``v`` (JSON data) as a Python literal with double quotes: what ``ast.literal_eval`` reads back."""
    if v is None:
        return "None"
    if v is True:
        return "True"
    if v is False:
        return "False"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(lit(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{" + ", ".join("%s: %s" % (json.dumps(str(k), ensure_ascii=False), lit(x)) for k, x in v.items()) + "}"
    raise ScriptError("cannot write %r" % (v,))


def _is_expr(v):
    return isinstance(v, dict) and v.get("k") in NUM_KINDS + BOOL_KINDS


def _kw_ok(name):
    return isinstance(name, str) and bool(_IDENT.match(name)) and not keyword.iskeyword(name)


def expr(e, value_ctx=True):
    """A value or condition as text. ``value_ctx``: a bare number here reads back as a num value."""
    if e is None:
        return "None"
    if not _is_expr(e):
        return "raw(%s)" % lit(e) if value_ctx else lit(e)
    k, keys = e["k"], set(e)
    if k == "num" and keys == {"k", "v"} and isinstance(e["v"], (int, float)) and not isinstance(e["v"], bool):
        s = repr(e["v"])
        return s if value_ctx and e["v"] >= 0 else "num(%s)" % s
    if k == "var" and keys == {"k", "name"} and isinstance(e["name"], str):
        n = e["name"]
        return n if _kw_ok(n) and n not in RESERVED else "var(%s)" % lit(n)
    if k == "op" and keys == {"k", "op", "a", "b"} and e["op"] in BINOPS:
        return "(%s %s %s)" % (expr(e["a"]), e["op"], expr(e["b"]))
    if k == "cmp" and keys == {"k", "op", "a", "b"} and e["op"] in CMPOPS:
        return "(%s %s %s)" % (expr(e["a"]), "==" if e["op"] == "=" else e["op"], expr(e["b"]))
    if k in ("and", "or") and keys == {"k", "a", "b"}:
        return "(%s %s %s)" % (expr(e["a"]), k, expr(e["b"]))
    if k == "not" and keys == {"k", "a"}:
        return "(not %s)" % expr(e["a"])
    if k in CALL_KINDS and all(_kw_ok(x) for x in keys - {"k"}) and not any(_is_expr(e[x]) for x in keys - {"k"}):
        return "%s(%s)" % (k, ", ".join("%s=%s" % (x, lit(e[x])) for x in e if x != "k"))
    return "expr(%s)" % lit(e)


def _top(s):
    """A condition at the head of an if: its outer brackets off, when they are the outer pair."""
    if s.startswith("(") and s.endswith(")"):
        try:
            if ast.dump(ast.parse(s[1:-1], mode="eval")) == ast.dump(ast.parse(s, mode="eval")):
                return s[1:-1]
        except SyntaxError:
            pass
    return s


def statement(b, depth):
    pad = INDENT * depth
    if not isinstance(b, dict) or not isinstance(b.get("op"), str) or not (_kw_ok(b["op"]) or b["op"] == "if"):
        return [pad + "block(%s)" % lit(b)]
    op = b["op"]
    if op not in OPS:
        return [pad + "block(%s)" % lit(b)]
    if op == "if" and set(b) <= {"op", "cond", "then", "else"} and "cond" in b and "then" in b \
            and isinstance(b["then"], list) and (b.get("else") is None or isinstance(b["else"], list)) \
            and (b["cond"] is None or _is_expr(b["cond"])):
        out = [pad + "if %s:" % _top(expr(b["cond"]))]
        out += body(b["then"], depth + 1)
        if "else" not in b:
            return [pad + "block(%s)" % lit(b)]          # an If saved with no else key at all: kept exactly
        if b["else"] is not None:
            out.append(pad + "else:")
            out += body(b["else"], depth + 1)
        return out
    fields = [x for x in b if x != "op"]
    if op == "if" or not all(_kw_ok(x) for x in fields):
        return [pad + "block(%s)" % lit(b)]
    vals = VALUE_FIELDS.get(op, set())
    args = []
    for x in fields:
        v = b[x]
        if x in vals:
            args.append("%s=%s" % (x, _top(expr(v))))
        elif _is_expr(v):
            args.append("%s=%s" % (x, expr(v, value_ctx=False)))
        else:
            args.append("%s=%s" % (x, lit(v)))
    return [pad + "%s(%s)" % (op, ", ".join(args))]


def body(stack, depth):
    lines = []
    for b in stack:
        lines += statement(b, depth)
    return lines or [INDENT * depth + "pass"]


def lit_pretty(v, depth=0):
    """As :func:`lit`, a long dict or list over several lines."""
    flat = lit(v)
    if len(flat) <= 100 or not isinstance(v, (dict, list)) or not v:
        return flat
    pad, inner = INDENT * depth, INDENT * (depth + 1)
    if isinstance(v, list):
        return "[\n" + "".join(inner + lit_pretty(x, depth + 1) + ",\n" for x in v) + pad + "]"
    return "{\n" + "".join(inner + "%s: %s,\n" % (json.dumps(str(k), ensure_ascii=False), lit_pretty(x, depth + 1))
                           for k, x in v.items()) + pad + "}"


def to_script(program, defaults=None):
    """The program (a blocks.json dict) as script text. ``defaults``: settings left out where the program's equal
    them (block_modes.normalize({}) - reading back through normalize puts them back)."""
    out = []
    for key, v in program.items():
        if key == "scripts" or (defaults is not None and key in defaults and defaults[key] == v):
            continue
        if isinstance(v, dict) and defaults is not None and isinstance(defaults.get(key), dict):
            v = {k: x for k, x in v.items() if defaults[key].get(k) != x or k == "on"}
        out.append("%s = %s" % (key, lit_pretty(v)) if _kw_ok(key) else "settings(%s)" % lit({key: v}))
    for s in program.get("scripts") or []:
        out.append("")
        hat, do = (s.get("hat"), s.get("do")) if isinstance(s, dict) else (None, None)
        if not (isinstance(s, dict) and set(s) == {"hat", "do"} and isinstance(hat, dict) and isinstance(do, list)
                and hat.get("kind") in HAT_KINDS and all(_kw_ok(x) for x in hat if x != "kind")
                and not any(_is_expr(hat[x]) for x in hat if x != "kind")):
            out.append("script(%s)" % lit(s))
            continue
        out.append("with on.%s(%s):" % (hat["kind"], ", ".join("%s=%s" % (x, lit(hat[x])) for x in hat if x != "kind")))
        out += body(do, 1)
    return "\n".join(out) + "\n"


# ---- reading ----------------------------------------------------------------------------------------------------
def _err(node, what):
    line = getattr(node, "lineno", 0)
    raise ScriptError("line %d: %s" % (line, what), line)


def _literal(node):
    try:
        return ast.literal_eval(node)
    except ValueError:
        _err(node, "a plain value (text, a number, a list) was expected")


def _number(node):
    v = node.value if isinstance(node, ast.Constant) else None
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def read_expr(node, value_ctx=True):
    if isinstance(node, ast.Constant) and node.value is None:
        return None
    if _number(node):
        return {"k": "num", "v": node.value} if value_ctx else node.value
    if not value_ctx and isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return {"k": "var", "name": node.id}
    if isinstance(node, ast.BinOp):
        for sym, cls in BINOPS.items():
            if isinstance(node.op, cls):
                return {"k": "op", "op": sym, "a": read_expr(node.left), "b": read_expr(node.right)}
    if isinstance(node, ast.Compare) and len(node.ops) == 1:
        for sym, cls in CMPOPS.items():
            if isinstance(node.ops[0], cls):
                return {"k": "cmp", "op": sym, "a": read_expr(node.left), "b": read_expr(node.comparators[0])}
    if isinstance(node, ast.BoolOp) and len(node.values) == 2:
        return {"k": "and" if isinstance(node.op, ast.And) else "or",
                "a": read_expr(node.values[0]), "b": read_expr(node.values[1])}
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return {"k": "not", "a": read_expr(node.operand)}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        f = node.func.id
        if f in ("num", "var", "raw", "expr") and len(node.args) == 1 and not node.keywords:
            v = _literal(node.args[0])
            return {"num": lambda: {"k": "num", "v": v}, "var": lambda: {"k": "var", "name": v},
                    "raw": lambda: v, "expr": lambda: v}[f]()
        if f in CALL_KINDS and not node.args:
            out = {"k": f}
            for kw in node.keywords:
                out[kw.arg] = _literal(kw.value)
            return out
    if not value_ctx:
        return _literal(node)
    _err(node, "not a value the blocks have")


def read_stack(stmts):
    out = []
    for st in stmts:
        if isinstance(st, ast.Pass):
            continue
        if isinstance(st, ast.If):
            b = {"op": "if", "cond": read_expr(st.test), "then": read_stack(st.body),
                 "else": read_stack(st.orelse) if st.orelse else None}
            out.append(b)
            continue
        if not (isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Name)):
            _err(st, "a block (a call such as score(points=1000)) or an if was expected")
        call, op = st.value, st.value.func.id
        if op == "block":
            if len(call.args) != 1 or call.keywords:
                _err(st, "block() takes one {...}")
            out.append(_literal(call.args[0]))
            continue
        if op not in OPS:
            _err(st, "there is no block called %s()" % op)
        if call.args:
            _err(st, "%s() takes its settings by name (field=value)" % op)
        b = {"op": op}
        vals = VALUE_FIELDS.get(op, set())
        for kw in call.keywords:
            if kw.arg is None:
                _err(st, "%s() takes its settings by name (field=value)" % op)
            b[kw.arg] = read_expr(kw.value, value_ctx=kw.arg in vals)
        out.append(b)
    return out


def from_script(text):
    """The program the script text is (a blocks.json dict). Raises :class:`ScriptError`."""
    try:
        tree = ast.parse(text)
    except SyntaxError as e:
        raise ScriptError("line %s: %s" % (e.lineno, e.msg), e.lineno or 0) from None
    program, scripts = {}, []
    for st in tree.body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            program[st.targets[0].id] = _literal(st.value)
        elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and isinstance(st.value.func, ast.Name) \
                and st.value.func.id in ("settings", "script") and len(st.value.args) == 1:
            v = _literal(st.value.args[0])
            if st.value.func.id == "settings":
                program.update(v)
            else:
                scripts.append(v)
        elif isinstance(st, ast.With) and len(st.items) == 1:
            call = st.items[0].context_expr
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
                    and isinstance(call.func.value, ast.Name) and call.func.value.id == "on" and not call.args):
                _err(st, "a script starts with: with on.<what sets it off>(...):")
            if call.func.attr not in HAT_KINDS:
                _err(st, "nothing called on.%s sets a script off (%s)" % (call.func.attr, ", ".join(sorted(HAT_KINDS))))
            hat = {"kind": call.func.attr}
            for kw in call.keywords:
                if kw.arg is None:
                    _err(st, "on.%s() takes its settings by name (field=value)" % call.func.attr)
                hat[kw.arg] = _literal(kw.value)
            scripts.append({"hat": hat, "do": read_stack(st.body)})
        else:
            _err(st, "a setting (name = value) or a script (with on....:) was expected")
    program["scripts"] = scripts
    return program
