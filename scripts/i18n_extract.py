"""Harvest the app's user-facing English strings for the translation
catalogs (PAD-458, docs/plans/app_languages.md).

    python scripts/i18n_extract.py                 # write i18n/strings.json
    python scripts/i18n_extract.py --missing es    # strings es.json lacks

The page translates what it SHOWS (static/js/core/i18n.js) by looking each
piece of text up in pinball_decryptor/webui/static/i18n/<lang>.json, so a
catalog key is the English exactly as the page draws it.  Text built from
parts becomes a TEMPLATE: ``{}`` stands for any run of text (a file name,
a count), so "Saved {} files" matches "Saved 12 files".

Sources: the page's own JavaScript (template text and string literals) and
the Python behind the tabs (webui/, app.py, core/), read with ``ast`` so
f-strings and %-formats turn into templates.  Docstrings, comparisons,
dictionary keys and logging calls are skipped; what is left is filtered to
things that read like words.  Anything the filter lets through that the
page never shows costs nothing but catalog space.
"""

import argparse
import ast
import itertools
import json
import os
import re
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(REPO, "pinball_decryptor")
WEBUI = os.path.join(PKG, "webui")
I18N = os.path.join(WEBUI, "static", "i18n")

#: Python sources whose strings reach the page
PY_ROOTS = [WEBUI, os.path.join(PKG, "app.py"), os.path.join(PKG, "core")]
JS_ROOT = os.path.join(WEBUI, "static", "js")
PLUGINS = os.path.join(PKG, "plugins")

#: calls whose string arguments never reach the page (or only the log,
#: which stays English so support reports read the same everywhere)
SKIP_CALLS = {
    "debug", "info", "warning", "exception", "critical", "getLogger",
    "compile", "match", "search", "sub", "fullmatch", "findall", "split",
    "join", "startswith", "endswith", "replace", "strip", "rstrip", "lstrip",
    "get", "pop", "setdefault", "getattr", "hasattr", "setattr", "open",
    "Popen", "run", "check_output", "call_wsl", "environ", "getenv",
    "isinstance", "encode", "decode", "struct", "pack", "unpack",
    "unpack_from", "pack_into", "calcsize", "fromhex", "strftime",
    "strptime", "exists", "isfile", "isdir", "makedirs", "listdir",
    "remove", "unlink", "rename", "rmtree", "copy", "copy2", "copyfile",
    "glob", "normpath", "abspath", "relpath", "dirname", "basename",
    "splitext", "expanduser", "expandvars", "log_cb", "_log", "log",
    "rpc", "service", "set_field", "emit", "event", "subscribe",
    "index", "find", "rfind", "count", "lower", "upper", "format_map",
    "register", "store_get", "add_argument", "write", "print",
    "mkdtemp", "NamedTemporaryFile", "TemporaryDirectory", "parse",
    "loads", "dumps", "load", "dump", "translate", "maketrans",
    "rjust", "ljust", "zfill", "center", "partition", "rpartition",
}

WORD = re.compile(r"[A-Za-z]{2,}")
#: a %-format: never "100% random" (no space flag, never right after a number)
PCT = re.compile(r"(?<!\d)%(?:\([a-z_]+\))?[-#0+]*\d*(?:\.\d+)?[sdifrxXgGeEc]")
FMT = re.compile(r"\{[^{}]*\}")


def as_template(s):
    """%-formats and str.format fields -> {}; numbers -> {} (the page's
    lookup does the same to what it shows)."""
    s = PCT.sub("\x00", s)
    s = FMT.sub("\x00", s)
    s = re.sub(r"\d+(?:[.,:]\d+)*", "\x00", s)
    return s.replace("\x00", "{}")


def looks_like_words(s, shown=False):
    """*shown*: text the page draws as it is (a template's words, a label
    attribute), where a lone lowercase word ("vivid") is a word, not an id."""
    t = s.strip()
    if len(t) < 2 or not WORD.search(t):
        return False
    if t.startswith(("http://", "https://", "/static", "--", "#", ".", "=")):
        return False
    if re.fullmatch(r"[a-z0-9_.:\-/\\]+", t) and not (shown and re.fullmatch(r"[a-z]+", t)):
        return False                                    # ids, rpc names, paths
    if re.fullmatch(r"[A-Z0-9_]+", t) and len(t) > 3 and "_" in t:   # constants
        return False
    if re.search(r"[;{}]\s*$", t) and ":" in t:        # css
        return False
    if re.search(r"\\[nt]|\\x|\\u|\(\?|\[\^|\$\{", t):
        return False
    if re.fullmatch(r"[\w\-]+(\s+[\w\-]+)*", t) and t == t.lower() and " " in t \
            and re.search(r"\b(btn|row|grow|muted|dim|chip|sm|lg|mono|col|wrap|stack|ellip|hide|ghost|icon|acc|ok|err|warn|small|tip|sx|hd|bd|ft)\b", t):
        return False                                    # class lists
    if re.search(r"(^|\s)(def|return|import|lambda|function|const|let)\s", t):
        return False
    if t.count("/") >= 2 and " " not in t:
        return False
    if re.search(r'\w=\s*$|\w=\{|\w="|\bhtml\b|=>|\?\.|&&|\|\||^M\{\}|\bnull\}', t):
        return False                                    # htm attributes, code, svg paths
    if re.fullmatch(r"[A-Z][A-Z0-9_]*=.*", t):          # VAR=value
        return False
    return True


class _PyVisitor(ast.NodeVisitor):
    def __init__(self):
        self.out = []
        self._skip = set()

    def _mark(self, node):
        for n in ast.walk(node):
            self._skip.add(id(n))

    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            self._mark(node)                             # docstring / bare string
        self.generic_visit(node)

    def visit_Compare(self, node):
        self._mark(node)

    def visit_Subscript(self, node):
        self._mark(node.slice)
        self.generic_visit(node)

    def visit_Dict(self, node):
        for k in node.keys:
            if k is not None:
                self._mark(k)
        self.generic_visit(node)

    def visit_Call(self, node):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        if name in SKIP_CALLS:
            self._mark(node)
            return
        self.generic_visit(node)

    def visit_BinOp(self, node):
        # "Saved " + str(n) + " files": one sentence with a hole
        if isinstance(node.op, ast.Add) and id(node) not in self._skip:
            ops, stack = [], [node]
            while stack:
                n = stack.pop()
                if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Add):
                    stack += [n.right, n.left]
                else:
                    ops.append(n)
            def texts(o):           # a literal, either side of a "a" if c else "b", or a hole
                if isinstance(o, ast.Constant) and isinstance(o.value, str):
                    return [o.value]
                if (isinstance(o, ast.IfExp) and all(isinstance(x, ast.Constant) and isinstance(x.value, str)
                                                     for x in (o.body, o.orelse))):
                    return [o.body.value, o.orelse.value]
                return None
            alts = [texts(o) for o in ops]
            if any(alts) and not all(a is not None and len(a) == 1 for a in alts):
                for combo in itertools.islice(itertools.product(*[a or ["{}"] for a in alts]), 8):
                    self.out.append("".join(combo))
        self.generic_visit(node)

    def visit_JoinedStr(self, node):
        if id(node) in self._skip:
            return
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                parts.append("{}")
        self.out.append("".join(parts))
        self._mark(node)

    def visit_Constant(self, node):
        if id(node) in self._skip or not isinstance(node.value, str):
            return
        self.out.append(node.value)


def py_strings(path, plugin=False):
    try:
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
    except (SyntaxError, UnicodeDecodeError, OSError):
        return []
    v = _PluginVisitor() if plugin else _PyVisitor()
    v.visit(tree)
    return v.out


#: a plugin call whose words only reach the log (which stays English)
_LOGLIKE = re.compile(r"log|emit|print|warn|debug|status|progress|_cb$|^cb$|^say$", re.I)
_CODEISH = re.compile(r"[;=#\\]|->|/\*|\*/|0x|\bx\{\}|\{\}x|\w_\w|\w\.\w+\(|\(\)|\[\{\}\]|&|\$"
                      r"|^[a-z_]+\s*\(|\b(?:fn|obj|ctor|vtable|imm|mask|int|char|void|const|"
                      r"struct|ptr|addr)\b")


class _PluginVisitor(_PyVisitor):
    def visit_Call(self, node):
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) else ""
        if name and _LOGLIKE.search(name):
            self._mark(node)
            return
        super().visit_Call(node)


def plugin_words(key):
    """A plugin string worth a catalog entry: words, not code or notes."""
    if _CODEISH.search(key) or key.isupper():
        return False
    if not re.search(r"[A-Za-z]{3,}", key.replace("{}", "")):
        return False
    return len(key.split()) >= 2 or bool(re.fullmatch(r"[A-Z][a-z]+", key))


def _js_unescape(s):
    return (s.replace('\\"', '"').replace("\\'", "'").replace("\\n", "\n")
            .replace("\\u00a0", " ").replace("\\`", "`").replace("\\\\", "\\"))


class _JsScan:
    """The page's JavaScript read just well enough: string literals, template
    literals (html`...` nested in each other's ${...} holes, as the tabs write
    them) with their holes, and the code around them with comments, strings
    and templates blanked out."""

    REGEX_BEFORE = set("(,=:[!&|?{};+-*%<>~^")

    def __init__(self, src):
        self.src, self.n = src, len(src)
        self.strings, self.templates, self.code = [], [], []
        self._code(0, top=True)
        self.code = "".join(self.code)

    def _string(self, i, q):
        j = i + 1
        while j < self.n and self.src[j] != q and self.src[j] != "\n":
            j += 2 if self.src[j] == "\\" else 1
        self.strings.append(_js_unescape(self.src[i + 1:j]))
        return j + 1

    def _regex(self, i):
        j, cls = i + 1, False
        while j < self.n and self.src[j] != "\n":
            c = self.src[j]
            if c == "\\":
                j += 2
                continue
            if c == "[":
                cls = True
            elif c == "]":
                cls = False
            elif c == "/" and not cls:
                return j + 1
            j += 1
        return j

    def _template(self, i):
        j, body = i + 1, []
        while j < self.n:
            c = self.src[j]
            if c == "\\":
                body.append(self.src[j:j + 2])
                j += 2
            elif c == "`":
                self.templates.append(_js_unescape("".join(body)))
                return j + 1
            elif self.src.startswith("${", j):
                body.append("\x00")
                j = self._code(j + 2, top=False)
            else:
                body.append(c)
                j += 1
        self.templates.append("".join(body))
        return j

    def _code(self, i, top):
        depth, prev = 0, ""
        src, out = self.src, self.code
        while i < self.n:
            c = src[i]
            if c in "\"'":
                j = self._string(i, c)
                if top:
                    out.append(src[i:j])
                i, prev = j, "x"
                continue
            if c == "`":
                i, prev = self._template(i), "x"
                if top:
                    out.append("``")
                continue
            if src.startswith("//", i):
                j = src.find("\n", i)
                i = self.n if j < 0 else j
                continue
            if src.startswith("/*", i):
                j = src.find("*/", i + 2)
                i = self.n if j < 0 else j + 2
                continue
            if c == "/" and (prev in self.REGEX_BEFORE or prev == ""):
                j = self._regex(i)
                if top:
                    out.append(src[i:j])
                i, prev = j, "x"
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                if not top and depth == 0:
                    return i + 1
                depth -= 1
            if top:
                out.append(c)
            if not c.isspace():
                prev = c if not (c.isalnum() or c in "_$)]") else "x"
            i += 1
        return i


def js_strings(path):
    with open(path, encoding="utf-8") as f:
        scan = _JsScan(f.read())
    out = list(scan.strings)
    for body in scan.templates:
        # html`...`: the text between tags (and between ${...} holes)
        for seg in re.split(r"<[^<>]*>", body):
            # the segment whole, holes and all ("“{}” is on too"): the page
            # joins text that sits side by side before it looks it up
            whole = re.sub(r"\s+", " ", seg).strip()
            if "\x00" in whole and whole.replace("\x00", "").strip():
                out.append(whole.replace("\x00", "{}"))
            for piece in seg.split("\x00"):
                piece = re.sub(r"\s+", " ", piece).strip()
                if piece:
                    out.append(SHOWN + piece)
        # attributes with literal text
        for a in re.finditer(r'\b(?:title|placeholder|label|aria-label|alt|left|right|hint|head|'
                             r'text|empty|note|sub|caption|unit|help|kicker|what)="([^"\x00]*)"', body):
            out.append(SHOWN + a.group(1))
    # "Nothing has been extracted into " + ps.name + " yet": one sentence
    for m in _JS_CHAIN.finditer(scan.code):
        ops = [o.strip() for o in _JS_PLUS.split(m.group(0))]
        # each operand's possible texts: a literal, either side of a
        # (cond ? "a" : "b"), or a hole
        alts = []
        for o in ops:
            t = re.fullmatch(_JS_TERN, o)
            if o[:1] in "\"'":
                alts.append([_js_unescape(o[1:-1])])
            elif t:
                alts.append([_js_unescape(t.group(1)[1:-1]), _js_unescape(t.group(2)[1:-1])])
            else:
                alts.append(None)
        if all(a is None for a in alts) or all(a is not None and len(a) == 1 for a in alts):
            continue
        for combo in itertools.islice(itertools.product(*[a or ["{}"] for a in alts]), 8):
            got = "".join(combo)
            if not re.search(r"[A-Za-z]\{\}[A-Za-z]", got):   # not a "Shift+Enter" inside a string
                out.append(got)
    return out


_JS_LIT = r'"(?:[^"\\\n]|\\.)*"|\'(?:[^\'\\\n]|\\.)*\''
_JS_EXPR = r"[A-Za-z_$][\w$]*(?:\([^()\"'\n]*\))?(?:\.[A-Za-z_$][\w$]*(?:\([^()\"'\n]*\))?|\[[^\[\]\"'\n]*\])*"
_JS_TERN = r"\(\s*[^()\"'\n?:]+\?\s*(%s)\s*:\s*(%s)\s*\)" % (_JS_LIT, _JS_LIT)
_JS_OPER = "(?:%s|%s|%s)" % (_JS_LIT, _JS_TERN, _JS_EXPR)
#: a + between operands (never one inside a string)
_JS_PLUS = re.compile(r"\s*\+\s*(?=(?:[^\"']|\"(?:[^\"\\]|\\.)*\"|'(?:[^'\\]|\\.)*')*$)")
_JS_CHAIN = re.compile(r"%s(?:\s*\+\s*%s)+" % (_JS_OPER, _JS_OPER))


#: the ? window's words: harvested as the window draws them, a whole block
#: at a time (help_harvest), not line by line
HELP_FILES = ("help_content.py",)


def help_harvest(seen):
    """Every block of the ? window's words, as tips_render looks them up."""
    sys.path.insert(0, REPO)
    from pinball_decryptor.webui import help_content as H
    from pinball_decryptor.webui import tips_render as R
    got = []

    def rec(text):
        got.append(text)
        return text
    keys = (set(H.HELP_CONTENT) | set(getattr(H, "_CONTENT_EXTRAS", {}))
            | set(getattr(H, "PREVIEW_HELP", {})))
    sections = list(H.GENERAL_CONTENT)
    for k in sorted(keys):
        got.append("Tips — " + k)
        got.append(k)
        try:
            sections += list(H.sections_for(k))
        except Exception:                               # noqa: BLE001
            pass
    for title, body in sections:
        got.append(title)
        R.render(body, tr=rec)
    for text in got:
        if looks_like_words(text):
            key = as_template(" ".join(text.split()))
            seen.setdefault(key, set()).add("pinball_decryptor/webui/help_content.py")


def harvest():
    seen = {}
    help_harvest(seen)
    files = []
    for root in PY_ROOTS:
        if os.path.isfile(root):
            files.append(root)
            continue
        for dp, dn, fn in os.walk(root):
            dn[:] = [d for d in dn if d not in ("__pycache__", "vendor", "static")]
            files += [os.path.join(dp, f) for f in fn
                      if f.endswith(".py") and f not in HELP_FILES]
    for path in files:
        for s in py_strings(path):
            _add(seen, s, path)
    # the manufacturer plugins: their phases, notes, field labels and the
    # Modes tab's words, among a great deal of code and reverse-engineering
    # notes, so only what reads like a sentence or a label is kept
    for dp, dn, fn in os.walk(PLUGINS):
        dn[:] = [d for d in dn if d != "__pycache__"]
        for f in fn:
            if f.endswith(".py"):
                path = os.path.join(dp, f)
                for s in py_strings(path, plugin=True):
                    for line in str(s).split("\n"):
                        if plugin_words(as_template(" ".join(line.split()))):
                            _add(seen, line, path)
    for dp, dn, fn in os.walk(JS_ROOT):
        dn[:] = [d for d in dn if d != "vendor"]
        for f in fn:
            if f.endswith(".js"):
                for s in js_strings(os.path.join(dp, f)):
                    _add(seen, s, os.path.join(dp, f))
    return seen


#: marks a piece of text the page draws as it is (looks_like_words *shown*)
SHOWN = "\x01"


def _add(seen, s, path):
    s = str(s)
    shown = s.startswith(SHOWN)
    # the page translates line by line: a multi-line string is its lines
    for line in s.lstrip(SHOWN).split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if not looks_like_words(line, shown):
            continue
        key = as_template(line)
        if not WORD.search(key.replace("{}", "")):
            continue
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        seen.setdefault(key, set()).add(rel)


# ---------------------------------------------------------------- English
# The app is written in American English (PAD-458); English (UK) is the same
# strings spelled the British way, made by these tables, not by hand.  A word
# that is the same in both, or whose British form depends on its sense
# ("program", "license", "meter", "practice"), is left out: it stays as the
# app writes it.
US_TO_GB = {
    "color": "colour", "colors": "colours", "colored": "coloured", "coloring": "colouring",
    "colorful": "colourful", "colorless": "colourless", "discolored": "discoloured",
    "gray": "grey", "grays": "greys", "grayed": "greyed", "graying": "greying",
    "grayscale": "greyscale", "grayish": "greyish",
    "center": "centre", "centers": "centres", "centered": "centred", "centering": "centring",
    "behavior": "behaviour", "behaviors": "behaviours",
    "favor": "favour", "favors": "favours", "favorite": "favourite", "favorites": "favourites",
    "canceled": "cancelled", "canceling": "cancelling",
    "labeled": "labelled", "labeling": "labelling", "modeled": "modelled",
    "traveled": "travelled", "signaled": "signalled", "leveled": "levelled",
    "analyze": "analyse", "analyzed": "analysed", "analyzes": "analyses", "analyzing": "analysing",
    "catalog": "catalogue", "catalogs": "catalogues",
    "defense": "defence", "offense": "offence", "judgment": "judgement",
    "honor": "honour", "honors": "honours", "honored": "honoured",
}
#: -ize words: the British form ends -ise ("recognize" -> "recognise")
IZE_STEMS = ("recogniz organiz realiz normaliz summariz prioritiz customiz finaliz initializ "
             "optimiz synchroniz minimiz maximiz categoriz serializ randomiz standardiz visualiz "
             "apologiz authoriz emphasiz centraliz characteriz utiliz specializ capitaliz "
             "memoriz digitaliz localiz neutraliz stabiliz personaliz criticiz").split()
_IZE_ENDS = ("e", "es", "ed", "ing", "ation", "ations", "er", "ers")
GB_TO_US = {gb: us for us, gb in US_TO_GB.items()}
_ENGLISH_WORD = re.compile(r"(?<![\w.$])(?<!--)[A-Za-z]+(?![\w])")


def _respell(word, table, stems, frm, to):
    low = word.lower()
    rep = table.get(low)
    if rep is None:
        for un in ("", "un"):
            for st in stems:
                if low.startswith(un + st) and low[len(un + st):] in _IZE_ENDS:
                    rep = un + st[:-1] + to + low[len(un + st):]
                    break
            if rep:
                break
    if rep is None:
        return None
    if word.isupper():
        return rep.upper()
    return rep[0].upper() + rep[1:] if word[0].isupper() else rep


def british(text):
    """*text* with its American spellings made British."""
    return _ENGLISH_WORD.sub(lambda m: _respell(m.group(0), US_TO_GB, IZE_STEMS, "z", "s")
                             or m.group(0), text)


def british_words(text):
    """The British spellings in *text* (the app writes American)."""
    gb_stems = [st[:-1] + "s" for st in IZE_STEMS]
    return [m.group(0) for m in _ENGLISH_WORD.finditer(text)
            if _respell(m.group(0), GB_TO_US, gb_stems, "s", "z")]


def write_british(seen):
    """en-gb.json: every harvested string that spells a word the American
    way, mapped to its British spelling."""
    cat = {}
    for key in seen:
        gb = british(key)
        if gb != key:
            cat[key] = gb
    path = os.path.join(I18N, "en-gb.json")
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(dict(sorted(cat.items())), f, ensure_ascii=False, indent=0)
        f.write("\n")
    print("en-gb: %d entries -> %s" % (len(cat), path))
    return 0


def merge(folder):
    """Add every ``<name>.<lang>.json`` in *folder* to that language's
    catalog (a key already there takes the new translation)."""
    import glob
    os.makedirs(I18N, exist_ok=True)
    for lang in ("es", "de", "fr"):
        path = os.path.join(I18N, lang + ".json")
        cat = {}
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                cat = json.load(f)
        n = len(cat)
        for part in sorted(glob.glob(os.path.join(folder, "*.%s.json" % lang))):
            with open(part, encoding="utf-8") as f:
                cat.update({k: v for k, v in json.load(f).items()
                            if isinstance(v, str) and v})
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(dict(sorted(cat.items())), f, ensure_ascii=False, indent=0)
            f.write("\n")
        print("%s: %d entries (%+d)" % (lang, len(cat), len(cat) - n))
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--missing", default="")
    ap.add_argument("--merge", default="",
                    help="a folder of <name>.<lang>.json translations to add "
                         "to the catalogs")
    ap.add_argument("--out", default=os.path.join(REPO, "i18n_strings.json"))
    ap.add_argument("--british", action="store_true",
                    help="write en-gb.json: every string with an American "
                         "spelling, spelled the British way")
    args = ap.parse_args()
    if args.merge:
        return merge(args.merge)
    seen = harvest()
    if args.british:
        return write_british(seen)
    if args.missing:
        with open(os.path.join(I18N, args.missing + ".json"), encoding="utf-8") as f:
            cat = json.load(f)
        miss = sorted(k for k in seen if k not in cat)
        for k in miss:
            print(k)
        print("%d of %d strings missing from %s" % (len(miss), len(seen), args.missing),
              file=sys.stderr)
        return 0
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump({k: sorted(v) for k, v in sorted(seen.items())}, f, indent=0,
                  ensure_ascii=False)
    print("%d strings -> %s" % (len(seen), args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
