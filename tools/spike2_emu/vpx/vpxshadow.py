#!/usr/bin/env python3
"""vpxshadow.py - put the Spike 2 emulator behind a SCRIPTED tribute table.

    python vpxshadow.py <title>.shadow.json "<table.vpx>" <out dir>

A tribute has no ROM: its rules live in its own script, wound through every
hit sub, timer and light. Rewriting that is a table of its own, so this does
the smaller thing that makes the real game playable on it:

  * the whole original script stays - physics tweaks, flipper tricks, ball
    rolling, ramp sounds, GI, flasher shows, PuP calls - and its rules keep
    running as a SHADOW GAME that never gets a Start, so its lights and
    sounds stay lively while its ball logic never fires;
  * every switch object the map names gets a new event sub that hands the
    edge to PAD.Controller and then calls the original sub (renamed `_orig`)
    for its sound and animation;
  * the ball goes where the REAL game says: Drain feeds a cvpmBallStack on
    the machine's trough switches, each scoop/VUK is a saucer stack whose
    coil the game fires, the auto plunger fires on the game's coil, posts and
    drop-target resets follow their coils;
  * the original's own ball creation and auto-launch lines are commented out
    (`neuter`), so the shadow game cannot add balls;
  * DOF and the backglass stay on the B2S.Server the tribute's LoadEM made:
    Table1_Init keeps it as PadB2S before `Controller` becomes PAD.Controller,
    and every `Controller.B2S...` call (the script's own and controller.vbs's
    DOF sub) goes to it; the DOF calls of the table's own subs the bridge
    stands in for (a bumper's Hit, the sub that kicks a saucer, the trough
    or the plunger) are copied into the bridge's subs and coil callbacks,
    and the map's `b2s_name` renames cGameName, the name DOF looks for;
  * keys: Start, launch, coins and the flipper BUTTONS go to the machine, and
    Table1_KeyDown passes everything else on to the original handler;
  * the flippers are the MACHINE's coils: core.vbs's sLLFlipper/sLRFlipper
    callbacks go to the table's own SolLFlipper/SolRFlipper (their tricks and
    sounds stay), since a tribute flips from the key only while ITS game is
    in play, which it never is. The map's `flippers` can name other subs.

Lamps: the map's `lamps` put table lights on the machine's LEDs (an RGB
insert's three, `rgb`, also give the light the insert's colour);
`retrofit_lights` are new lights cloned where the machine has an insert the
table lacks, and `dark` lights, which the machine has no LED for, are held
off so the shadow game cannot leave them lit.

The map (<title>.shadow.json) says which object is which switch; see
rush_le.shadow.json for the fields. The patched table is re-signed and gets
a PinMAMETimer (core.vbs's) and a PadTestTimer (vpxkeys.py) cloned from an
existing timer.
"""
import json
import os
import re
import shutil
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vpxfile  # noqa: E402
import vpxsounds  # noqa: E402

SUB_RE = r"^(\s*)(Public\s+|Private\s+)?Sub\s+(%s)\s*(\([^)]*\))?(\s*'.*|\s*:.*)?$"

#: a switch's event -> the table sub(s) that carry it. "pass" (PAD-887) is a
#: spinner standing in for the machine's OPTO: a ball through it spins it a
#: dozen times, and the opto must see one pass, not twelve
EVENT_SUBS = {"hit": ("_Hit",), "hold": ("_Hit", "_UnHit"), "spin": ("_Spin",),
              "pass": ("_Spin",), "slingshot": ("_Slingshot",)}
PASS_MS = 600


def saucers(m):
    return {k: v for k, v in m.get("saucers", {}).items() if k != "_"}


def rename_sub(lines, name, rep):
    """Rename `Sub <name>` to `Sub <name>_orig`; True if it existed."""
    pat = re.compile(SUB_RE % re.escape(name), re.I)
    for i, line in enumerate(lines):
        m = pat.match(line.rstrip())  # Batman 66: a header can end in a space
        if m:
            lines[i] = line.replace(m.group(3), name + "_orig", 1)
            rep.append("renamed Sub %s -> %s_orig" % (name, name))
            return True
    return False


def _statements(line):
    """A line's `:`-joined statements, quotes respected; the first comment
    ends the split. Returns [(start, end)] spans."""
    spans, start, inq = [], 0, False
    for i, ch in enumerate(line):
        if ch == '"':
            inq = not inq
        elif not inq and ch == "'":
            break
        elif not inq and ch == ":" and not line[max(0, i - 1):i + 1].startswith("::"):
            spans.append((start, i))
            start = i + 1
    spans.append((start, len(line)))
    return spans


def quiet_sub(lines, name, rep):
    """Rename `Sub <name>` to `_orig` and return its argument list, so gen can
    stand an empty Sub of the same shape in its place; None if absent."""
    pat = re.compile(SUB_RE % re.escape(name), re.I)
    for i, line in enumerate(lines):
        m = pat.match(line.rstrip())  # Batman 66: a header can end in a space
        if m:
            lines[i] = line.replace(m.group(3), name + "_orig", 1)
            rep.append("quieted Sub %s (its lights are the machine's now)" % name)
            return m.group(4) or "()"
    rep.append("WARNING: quiet_subs names %s, which the script has no Sub for" % name)
    return None


def neuter(lines, patterns, rep):
    """Comment out every line that creates or launches a ball. A statement
    sharing its line with others (`Sub Drain_Hit : PlungerIM.AutoFire : End
    Sub`) cannot be commented without taking the rest, so it is guarded with
    `If False Then` instead."""
    n = 0
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("'"):
            continue
        for p in patterns:
            if p.lower() not in s.lower():
                continue
            spans = _statements(line)
            if len(spans) == 1:
                lines[i] = re.sub(r"^(\s*)", r"\1'PAD neutered: ", line, count=1)
            else:
                parts = []
                for a, b in spans:
                    seg = line[a:b]
                    if p.lower() in seg.lower() and not seg.strip().lower().startswith("if "):
                        lead = len(seg) - len(seg.lstrip())
                        seg = seg[:lead] + "If False Then " + seg[lead:]   # PAD neutered
                    parts.append(seg)
                lines[i] = ":".join(parts) + line[spans[-1][1]:]
            n += 1
            break
    rep.append("neutered %d line(s) that created or launched balls" % n)


B2S_RE = re.compile(r"\bController\.B2S", re.I)
CONTROLLER_VBS_RE = re.compile(r'ExecuteGlobal\s+(GetTextFile\s*\(\s*"controller\.vbs"\s*\))', re.I)


def route_b2s(lines, rep):
    """A tribute's LoadEM (controller.vbs) puts B2S.Server in `Controller`,
    and DOF and the backglass go through it (`Controller.B2SSetData`). Once
    Table1_Init hands `Controller` to PAD.Controller those calls must still
    reach the B2S server: the table's own become `PadB2SCtl.B2S...`, and
    controller.vbs gets the same rewrite as it loads (PadB2SText), which
    covers its DOF sub. `\\b` keeps B2SController.B2S... (DOFALT) as it is."""
    n = loads = 0
    for i, line in enumerate(lines):
        line, k = B2S_RE.subn("PadB2SCtl.B2S", line)
        line, j = CONTROLLER_VBS_RE.subn(r"ExecuteGlobal PadB2SText(\1)", line)
        lines[i], n, loads = line, n + k, loads + j
    if n or loads:
        rep.append("B2S/DOF kept on the B2S server: %d call(s) in the script%s"
                   % (n, ", and controller.vbs's" if loads else ""))


GAMENAME_RE = re.compile(r'^(\s*(?:Const\s+)?cGameName\s*=\s*)"[^"]*"', re.I)


def rename_game(lines, name, rep):
    """The map's `b2s_name`: the name LoadEM hands B2S.Server, which is the
    name DOF looks the table up by in its config (Rush's tribute says
    "rushle", the DOF Config Tool knows it as "rush_le")."""
    for i, line in enumerate(lines):
        if GAMENAME_RE.match(line):
            lines[i] = GAMENAME_RE.sub(lambda mo: mo.group(1) + vb(name), line, count=1)
            rep.append("B2S/DOF game name is %s" % name)
            return


# ---- DOF: the table's own feedback calls, carried into the bridge's subs
#
# A shadow map's `orig_hits: false` keeps a tribute's hit subs out of the way,
# and its kickers, trough and plunger now fire on the machine's coils through
# cvpmBallStack: the `DOF 107, DOFPulse` in a bumper's Hit sub and the
# SoundFXDOF beside `Kicker1.Kick` never ran, so a cabinet's contactors stayed
# still. The unconditional ones are copied into the subs that stand in.

DOF_RE = re.compile(r"^(?:Call\s+)?DOF\s*\(?\s*([^,()]+?)\s*,\s*([^,()]+?)\s*\)?$", re.I)
FXDOF_RE = re.compile(r"\bSoundFXDOF\s*\(", re.I)


def _code(line):
    """A line without its comment."""
    inq = False
    for i, ch in enumerate(line):
        if ch == '"':
            inq = not inq
        elif ch == "'" and not inq:
            return line[:i]
    return line


def _args(text):
    """The comma-separated arguments up to the closing paren, nesting kept."""
    out, depth, inq, cur = [], 0, False, ""
    for ch in text:
        if ch == '"':
            inq = not inq
        elif not inq and ch == "(":
            depth += 1
        elif not inq and ch == ")":
            if depth == 0:
                break
            depth -= 1
        elif not inq and ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
            continue
        cur += ch
    out.append(cur.strip())
    return out


def _dof_in(stmt):
    """`PadDOF event, state, toy` for each DOF a statement fires."""
    found = []
    mo = DOF_RE.match(stmt)
    if mo:
        found.append("PadDOF %s, %s, Empty" % (mo.group(1), mo.group(2)))
    for mo in FXDOF_RE.finditer(stmt):
        a = _args(stmt[mo.end():])
        if len(a) == 4:
            found.append("PadDOF %s, %s, %s" % (a[1], a[2], a[3]))
    return found


def _walk(lines):
    """Every statement inside a Sub or Function, as (sub name lowered, block
    path, statement). The path names the If/Case/loop branch the statement
    runs in - () is the sub's own level; a single-line If's statements are
    conditional and get a path of their own."""
    head = re.compile(r"^(?:public\s+|private\s+)?(?:sub|function)\s+(\w+)", re.I)
    sub, path, ids = None, [], [0]

    def new():
        ids[0] += 1
        return ids[0]
    for line in lines:
        code = _code(line)
        cond = None             # a single-line If: the rest of the line is its
        for a, b in _statements(code):
            s = code[a:b].strip()
            low = s.lower()
            if not s:
                continue
            if cond:
                if not re.match(r"end\s+if\b", low):
                    yield sub, cond, s
                continue
            mo = head.match(s)
            if mo:
                sub, path = mo.group(1).lower(), []
                continue
            if sub is None:
                continue
            if re.match(r"end\s+(sub|function)\b", low):
                sub = None
                continue
            if low.startswith("if ") and re.search(r"\bthen$", low):
                path.append(new())
            elif low.startswith("if ") and re.search(r"\bthen\b", low):
                cond = tuple(path) + (new(),)
                yield sub, cond, re.split(r"(?i)\bthen\b", s, maxsplit=1)[1].strip()
            elif re.match(r"(elseif\b.*\bthen$|else$|case\b)", low) and path:
                path[-1] = new()
            elif re.match(r"(select\s+case|for\b|do\b|while\b)", low):
                path.append(new())
            elif re.match(r"(end\s+(if|select)|next|loop|wend)\b", low) and path:
                path.pop()
            else:
                yield sub, tuple(path), s


def _dedupe(calls):
    seen = []
    for c in calls:
        if c not in seen:
            seen.append(c)
    return seen


def dof_of_sub(stmts, name):
    """The DOF a sub always fires: its own level, no branch."""
    return _dedupe([c for sub, path, s in stmts if sub == name.lower() and not path
                    for c in _dof_in(s)])


def dof_at_fire(stmts, obj):
    """The DOF fired beside `<obj>.Kick` / `.AutoFire` / `.Fire`, in the same
    branch of the same sub (Rush: `kicker1.Kick 190, 15` then SoundFXDOF 113)."""
    fire = re.compile(r"\b%s\.(kick\w*|autofire|fire)\b" % re.escape(obj), re.I)
    where = {(sub, path) for sub, path, s in stmts if fire.search(s)}
    return _dedupe([c for sub, path, s in stmts if (sub, path) in where for c in _dof_in(s)])


def vb(s):
    return '"' + s.replace('"', '""') + '"'


def vb_value(v):
    """A JSON number or string as a VBScript literal."""
    return str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else vb(str(v))


def _argcount(rest):
    depth, inq, n, seen = 0, False, 0, False
    for ch in rest:
        if ch == '"':
            inq = not inq
        elif not inq:
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
            elif ch == "," and depth == 0:
                n += 1
            elif ch == "'":
                break
        if not ch.isspace():
            seen = True
    return (n + 1) if seen else 0


def _resuming(lines, i):
    """Whether line i already runs under the enclosing procedure's own `On
    Error Resume Next`: a wrapper then must not end it with `On Error Goto 0`
    (GOTG's and Aerosmith's PuPInit relied on theirs for the rest)."""
    for j in range(i - 1, -1, -1):
        s = lines[j].strip().lower()
        if re.match(r"(public\s+|private\s+)?(sub|function)\s", s):
            return False
        if s.startswith("on error resume next"):
            return True
        if s.startswith("on error goto 0"):
            return False
    return False


def _optional(lines, i, fallback, note):
    """Wrap line i's CreateObject so a failure runs `fallback` instead."""
    line = lines[i]
    ind = re.match(r"^\s*", line).group(0)
    out = [ind + "On Error Resume Next", line.rstrip("\r"),
           ind + "If Err Then Err.Clear : %s : End If   ' PAD: %s" % (fallback, note)]
    if not _resuming(lines, i):
        out.append(ind + "On Error Goto 0")
    lines[i] = "\n".join(out)


def pup_stub(lines, rep):
    """PinUP Player is a separate install most machines lack, and a tribute
    that calls it dies at CreateObject before anything else runs. Make the
    object optional: when CreateObject fails, PuPlayer becomes a class with
    every method the script calls, each taking the argument count the script
    uses, doing nothing. Returns the class text."""
    counts, spelling = {}, {}
    for line in lines:
        s = line.strip()
        if s.startswith("'"):
            continue
        # any case: Aerosmith's PuPInit calls `puplayer.getroot`
        for m in re.finditer(r"\bPuPlayer\.(\w+)\s*(.*)$", s, re.I):
            meth, rest = m.groups()
            if rest.startswith("("):
                inner = rest[1:rest.rfind(")")] if ")" in rest else rest[1:]
                n = _argcount(inner)
            elif rest.startswith("="):
                continue
            else:
                n = _argcount(rest)
            counts.setdefault(meth.lower(), {}).setdefault(n, 0)
            counts[meth.lower()][n] += 1
            spelling.setdefault(meth.lower(), meth)
    # EVERY creation: Iron Maiden makes it twice (lines 104 and 1738), and
    # the second, left bare, stopped the table at load
    made = 0
    for i, line in enumerate(lines):
        if line.lstrip().startswith("'"):
            continue
        if re.search(r'Set\s+PuPlayer\s*=\s*CreateObject\("PinUpPlayer\.PinDisplay"\)', line, re.I):
            _optional(lines, i, "Set PuPlayer = New PadNoPuP", "no PinUP Player here")
            made += 1
    if made:
        rep.append("PuP made optional at %d place(s) (PadNoPuP stands in, %d methods)"
                   % (made, len(counts)))
    out = ["", "'---- PAD: PinUP Player's shape, for a machine without it", "Class PadNoPuP"]
    for meth, cs in list(counts.items()):
        if meth in ("getroot",):
            # a property read (`Set r = PuPlayer.getroot`), not a Sub
            del counts[meth]
            out.append("\tPublic Function %s() : Set %s = Nothing : End Function"
                       % (spelling[meth], spelling[meth]))
    for meth, cs in sorted(counts.items()):
        n = max(cs, key=cs.get)
        if len(cs) > 1:
            rep.append("WARNING: PuPlayer.%s is called with %s arguments; the stub takes %d" % (meth, sorted(cs), n))
        args = ", ".join("a%d" % k for k in range(n))
        out.append("\tPublic Sub %s(%s) : End Sub" % (spelling[meth], args))
    out += ["End Class", ""]
    return "\n".join(out)


def flex_optional(lines, rep):
    """FlexDMD is a separate install too, and JP's Deadpool (DMD Type
    defaults to FlexDMD) dies at its CreateObject. When it fails, the table
    falls back to its desktop DMD: the object is Nothing and UseFlexDMD is
    False (ExecuteGlobal, so a table where it is a Const just keeps it). The
    machine's LCD is the real display either way."""
    for i, line in enumerate(lines):
        m = re.match(r'^(\s*)Set\s+(\w+)\s*=\s*CreateObject\("FlexDMD\.FlexDMD"\)', line, re.I)
        if m:
            var = m.group(2)
            _optional(lines, i, 'Set %s = Nothing : ExecuteGlobal "UseFlexDMD = False"' % var,
                      "no FlexDMD here")
            rep.append("FlexDMD made optional (%s falls back to the desktop DMD)" % var)


def lamp_number(node, index):
    return 1000 + node * 100 + index


def mapped_lights(m):
    """name -> lamp entry, the table's own lights and the retrofit ones."""
    out = {}
    for table in (m.get("lamps", {}), m.get("retrofit_lights", {}).get("lights", {})):
        out.update((k, v) for k, v in table.items() if k != "_" and isinstance(v, dict))
    return out


def lamp_groups(m):
    """lamp number -> [table lights]: the controller reports a mapped insert
    under the number of its FIRST LED (padcontroller.VpxMap), lit when any of
    the insert's LEDs is; several table lights may share one."""
    groups = {}
    for name, v in mapped_lights(m).items():
        node, idx = v["leds"][0]
        groups.setdefault(lamp_number(node, idx), []).append(name)
    return groups


def lamp_calls(m):
    """lamp number -> [lamp_calls entries]: inserts the table shows with a
    sub of its own (extra_vbs) rather than a Light, keyed like lamp_groups."""
    out = {}
    for name, v in m.get("lamp_calls", {}).items():
        if name == "_" or not isinstance(v, dict):
            continue
        node, idx = v["leds"][0]
        out.setdefault(lamp_number(node, idx), []).append(v)
    return out


LAMP_READ_RE = re.compile(r"\bController\.ChangedLamps\b", re.I)


def own_lamp_reads(lines, rep):
    """A tribute that once ran a ROM keeps a lamp loop of its own
    (Batman 66's and Aerosmith's LampTimer, `If B2SOn Then chglamp =
    Controller.ChangedLamps`). `Controller` is PAD.Controller now, and each
    such read takes the changes PadUpdateLamps waits for: the lights it
    missed stayed as they were. The table's reads come back Empty."""
    n = 0
    for i, line in enumerate(lines):
        code, sep, comment = _split_comment(line)
        code, k = LAMP_READ_RE.subn("Empty", code)
        if k:
            lines[i], n = code + sep + comment, n + k
    if n:
        rep.append("the table's own %d read(s) of Controller.ChangedLamps answer Empty "
                   "(the bridge reads it)" % n)


def _split_comment(line):
    inq = False
    for i, ch in enumerate(line):
        if ch == '"':
            inq = not inq
        elif ch == "'" and not inq:
            return line[:i], "'", line[i + 1:]
    return line, "", ""


def _calls_orig(m, name):
    # with the machine's lamps on the table, a tribute's own hit subs (its
    # rules: lights, sounds, scores) stay out of the way; the real game's LCD
    # and sound say what a hit was worth
    return m.get("orig_hits", True) or name.lower() in {n.lower() for n in m.get("orig_keep", [])}


def gen(m, had, quiet=None, dof=None):
    """The bridge's own script, appended after the original. `dof`: handler
    (`sw001_Hit`, `sol:3`) -> the table's DOF calls it must fire itself."""
    cab = m["cabinet"]
    quiet = quiet or {}
    dof = dof or {}

    def fx(handler):
        return "".join(" : " + c for c in dof.get(handler, ()))
    lamps = lamp_groups(m) or lamp_calls(m)

    def calls_orig(name):
        return _calls_orig(m, name)
    out = ["", "", "'" + "=" * 70, "'==== PAD: the Spike 2 emulator drives this table (vpxshadow.py) ====",
           "'" + "=" * 70,
           "Dim bsTrough"]
    for k in saucers(m):
        out.append("Dim bs%s" % k)
    out += ["", "' the B2S.Server LoadEM made (DOF, the backglass): `Controller` is",
            "' PAD.Controller once Table1_Init has run, so B2S calls go here",
            "Dim PadB2S",
            "Function PadB2SCtl",
            "\tIf IsObject(PadB2S) Then Set PadB2SCtl = PadB2S Else Set PadB2SCtl = Controller",
            "End Function",
            "Function PadB2SText(t)   ' controller.vbs as it loads: its B2S calls to PadB2SCtl",
            "\tDim re : Set re = New RegExp",
            "\tre.Pattern = \"\\bController\\.B2S\" : re.IgnoreCase = True : re.Global = True",
            "\tPadB2SText = re.Replace(t, \"PadB2SCtl.B2S\")",
            "End Function"]
    if dof:
        out += ["Sub PadDOF(e, s, toy)   ' a DOF call of the table's, from a sub the bridge stands in for",
                "\tOn Error Resume Next   ' a table without controller.vbs has no DOF",
                "\tIf Not IsEmpty(toy) Then",
                "\t\tIf DOFeffects(toy) <> 1 And DOFeffects(toy) <> 2 Then Exit Sub   ' as SoundFXDOF",
                "\tEnd If",
                "\tDOF e, s",
                "End Sub"]
    # ---- Init
    out += ["", "Sub Table1_Init"]
    if had["Table1_Init"]:
        out.append("\tTable1_Init_orig            ' the table's own physics, sounds, attract")
    out += ["\tOn Error Resume Next",
            "\tIf IsObject(Controller) Then",
            "\t\tIf Not Controller Is Nothing Then Set PadB2S = Controller",
            "\tEnd If",
            "\tSet Controller = CreateObject(\"PAD.Controller\")",
            "\tIf Err Then MsgBox \"Can't load PAD.Controller: \" & Err.Description",
            "\tController.GameName = %s" % vb(m["title"]),
            "\tController.Run GetPlayerHWnd",
            "\tIf Err Then MsgBox \"Can't start the Spike 2 game: \" & Err.Description",
            "\tOn Error Goto 0",
            "\tPinMAMETimer.Interval = PinMAMEInterval",
            "\tPinMAMETimer.Enabled = True",
            "\tSet bsTrough = New cvpmBallStack",
            "\t\tbsTrough.InitSw 0,%s" % ",".join("1%03d" % s for s in m["trough"]["switches"]),
            "\t\tbsTrough.Balls = %d" % m["trough"].get("balls", 6),
            "\t\tbsTrough.InitKick %s, %d, %d" % (m["trough"]["release"], *m["trough"]["kick"])]
    for k, s in saucers(m).items():
        out.append("\tSet bs%s = New cvpmBallStack" % k)
        if s.get("stack"):
            # a lock lane (PAD-901): the kicker takes each ball in and the
            # stack rolls it down to the lowest free switch, `switch` first
            sw = ["1%03d" % n for n in [s["switch"]] + s["stack"]]
            out += ["\t\tbs%s.InitSw 0,%s" % (k, ",".join((sw + ["0"] * 7)[:7])),
                    "\t\tbs%s.InitKick %s, %d, %d" % (k, k, s["dir"], s["power"])]
        else:
            out.append("\t\tbs%s.InitSaucer %s, 1%03d, %d, %d" % (k, k, s["switch"], s["dir"], s["power"]))
        out.append("\t\tbs%s.KickZ = %s" % (k, s.get("kickz", 0)))
    if lamps:
        out.append("\t' the machine's lamps: the shadow game's light shows stop, ours start")
        for seq in m.get("_lightseqs", []):
            out.append("\t%s.StopPlay" % seq)
        out += ["\tPadLampsInit",
                "\tSet LampCallback = GetRef(\"PadUpdateLamps\")"]
    out += ["End Sub", "",
            "Sub Table1_Exit",
            "\tOn Error Resume Next",
            "\tController.Stop"]
    if had["Table1_Exit"]:
        out.append("\tTable1_Exit_orig")
    out += ["\tIf IsObject(PadB2S) Then PadB2S.Stop   ' its backglass closes with the table",
            "End Sub",
            "Sub Table1_Paused : Controller.Pause = 1 : End Sub",
            "Sub Table1_UnPaused : Controller.Pause = 0 : End Sub", ""]
    # ---- keys
    skip = list(m.get("keys_skip_orig", []))
    flips = flipper_subs(m, had)
    if flips:
        # the machine flips: its coils call the table's own flipper subs below,
        # so the shadow game's keyboard flippers must not (double flips, or none
        # at all - an EM-style tribute gates them on ITS game being in play)
        skip += [k for k in ("LeftFlipperKey", "RightFlipperKey") if k not in skip]
    keymap = [("StartGameKey", cab["start"]), ("LeftFlipperKey", cab["left_flipper"]),
              ("RightFlipperKey", cab["right_flipper"])]
    if cab.get("up_right_flipper"):
        # Stern's right button closes the upper flipper's switch too
        keymap.append(("RightFlipperKey", cab["up_right_flipper"]))
    if cab.get("up_left_flipper"):
        keymap.append(("LeftFlipperKey", cab["up_left_flipper"]))
    if cab.get("launch_key") and cab.get("launch"):
        keymap.append((cab["launch_key"], cab["launch"]))
    out += ["Sub Table1_KeyDown(ByVal KeyCode)"]
    for key, sw in keymap:
        out.append("\tIf KeyCode = %s Then Controller.Switch(%d) = True" % (key, sw))
    if cab.get("coin"):
        out.append("\tIf KeyCode = AddCreditKey Then vpmTimer.PulseSw %d" % cab["coin"])
    if skip:
        out.append("\tSelect Case KeyCode")
        out.append("\t\tCase %s" % ", ".join(skip))
        out.append("\t\t\t' the machine's keys: never the shadow game's")
        out.append("\t\tCase Else")
        if had["Table1_KeyDown"]:
            out.append("\t\t\tTable1_KeyDown_orig KeyCode")
        out.append("\tEnd Select")
    elif had["Table1_KeyDown"]:
        out.append("\tTable1_KeyDown_orig KeyCode")
    out += ["End Sub", "Sub Table1_KeyUp(ByVal KeyCode)"]
    for key, sw in keymap:
        out.append("\tIf KeyCode = %s Then Controller.Switch(%d) = False" % (key, sw))
    if skip:
        out.append("\tSelect Case KeyCode")
        out.append("\t\tCase %s" % ", ".join(skip))
        out.append("\t\tCase Else")
        if had["Table1_KeyUp"]:
            out.append("\t\t\tTable1_KeyUp_orig KeyCode")
        out.append("\tEnd Select")
    elif had["Table1_KeyUp"]:
        out.append("\tTable1_KeyUp_orig KeyCode")
    out += ["End Sub", ""]
    out, _ = with_service_keys(out)
    # ---- the trough and the plunger lane
    t = m["trough"]
    out += ["Sub %s_Hit" % t["drain"],
            "\tbsTrough.AddBall Me",
            "\tPlaySoundAt \"fx_drain\", %s" % t["drain"]]
    out += ["\t" + c for c in dof.get(t["drain"] + "_Hit", ())]
    out += ["End Sub"]
    p = m.get("plunger")
    if p:
        out += ["Sub %s_Hit : Controller.Switch(1%03d) = True" % (p["lane_trigger"], p["lane_switch"])
                + (" : %s_Hit_orig" % p["lane_trigger"] if had.get(p["lane_trigger"] + "_Hit") else "")
                + " : End Sub",
                "Sub %s_UnHit : Controller.Switch(1%03d) = False" % (p["lane_trigger"], p["lane_switch"])
                + (" : %s_UnHit_orig" % p["lane_trigger"] if had.get(p["lane_trigger"] + "_UnHit") else "")
                + " : End Sub",
                "Sub PadAutoPlunge(e) : If e Then %s.AutoFire : End If : End Sub" % p["autoplunge"]]
    # ---- switches
    out.append("")
    if any(s.get("event") == "pass" for k, s in m["switches"].items() if k != "_"):
        # every spin restarts the quiet time, so one pass is one pulse; the
        # dictionary is made on first use (a top-level Set may never run)
        out += ["Dim PadPassAt",
                "Sub PadPassSw(sw)",
                "\tIf IsEmpty(PadPassAt) Then Set PadPassAt = CreateObject(\"Scripting.Dictionary\")",
                "\tIf PadPassAt.Exists(sw) Then",
                "\t\tIf GameTime - PadPassAt(sw) < %d Then PadPassAt(sw) = GameTime : Exit Sub" % PASS_MS,
                "\tEnd If",
                "\tPadPassAt(sw) = GameTime",
                "\tvpmTimer.PulseSw sw",
                "End Sub"]
    for name, s in m["switches"].items():
        if name == "_":
            continue
        ev = s.get("event", "hit")
        sid = 1000 + s["id"]
        if ev == "hit":
            body = "vpmTimer.PulseSw %d" % sid
            if had.get(name + "_Hit") and calls_orig(name):
                body += " : %s_Hit_orig" % name
            else:
                body += fx(name + "_Hit")
            out.append("Sub %s_Hit : %s : End Sub" % (name, body))
        elif ev == "hold":
            b1 = "Controller.Switch(%d) = True" % sid
            b0 = "Controller.Switch(%d) = False" % sid
            if had.get(name + "_Hit") and calls_orig(name):
                b1 += " : %s_Hit_orig" % name
            else:
                b1 += fx(name + "_Hit")
            if had.get(name + "_UnHit") and calls_orig(name):
                b0 += " : %s_UnHit_orig" % name
            else:
                b0 += fx(name + "_UnHit")
            out.append("Sub %s_Hit : %s : End Sub" % (name, b1))
            out.append("Sub %s_UnHit : %s : End Sub" % (name, b0))
        elif ev in ("spin", "pass"):
            body = ("vpmTimer.PulseSw %d" if ev == "spin" else "PadPassSw %d") % sid
            if had.get(name + "_Spin") and calls_orig(name):
                body += " : %s_Spin_orig" % name
            else:
                body += fx(name + "_Spin")
            out.append("Sub %s_Spin : %s : End Sub" % (name, body))
        elif ev == "slingshot":
            body = "vpmTimer.PulseSw %d" % sid
            if had.get(name + "_Slingshot") and calls_orig(name):
                body += " : %s_Slingshot_orig" % name
            else:
                body += fx(name + "_Slingshot")
            out.append("Sub %s_Slingshot : %s : End Sub" % (name, body))
    # ---- lamps
    if lamps:
        out += ["", "'---- the machine's lamps: number 1000 + node * 100 + LED index, one",
                "'     table light (or several) per insert; core.vbs calls LampCallback",
                "'     every tick with UseLamps = 0, and this reads ChangedLamps itself",
                "'     The dictionaries are made in PadLampsInit, not by top-level",
                "'     code here: Iron Maiden's script stops running its top level",
                "'     before this tail, and a Set up here never happened",
                "Dim PadLamps, PadLampState, PadTick, PadDark, PadCalls",
                "Sub PadLampsInit",
                "\tSet PadLamps = CreateObject(\"Scripting.Dictionary\")",
                "\tSet PadLampState = CreateObject(\"Scripting.Dictionary\")",
                "\tPadTick = 0"]
        for num, names in sorted(lamp_groups(m).items()):
            out.append("\tPadLamps.Add \"%d\", Array(%s)" % (num, ", ".join(names)))
        # an insert the table shows some other way (a fader's bulb, a plastic's
        # image, a flasher): the map's sub of extra_vbs, called (arg, value)
        out.append("\tSet PadCalls = CreateObject(\"Scripting.Dictionary\")")
        for num, calls in sorted(lamp_calls(m).items()):
            out.append("\tPadCalls.Add \"%d\", Array(%s)" % (num, ", ".join(
                "Array(GetRef(%s), %s)" % (vb(c["call"]), vb_value(c.get("arg", 0))) for c in calls)))
        # lights the machine has no LED for: held off, or the shadow game's
        # last state (an attract light, a blink) would stay on them
        out += ["\tPadDark = Array(%s)" % ", ".join(m.get("dark", [])),
                "\tPadReassertLamps",
                "End Sub",
                "Sub PadUpdateLamps",
                "\tDim chg, ii, o, k, c, f",
                "\tchg = Controller.ChangedLamps",
                "\tIf IsEmpty(chg) Then Exit Sub",
                "\tFor ii = 0 To UBound(chg)",
                "\t\tk = CStr(chg(ii, 0))",
                "\t\tIf PadLamps.Exists(k) Then",
                "\t\t\tPadLampState(k) = chg(ii, 1)",
                "\t\t\tFor Each o In PadLamps(k) : PadLampSet o, chg(ii, 1) : Next",
                "\t\tEnd If",
                "\t\tIf PadCalls.Exists(k) Then",
                "\t\t\tFor Each c In PadCalls(k)",
                "\t\t\t\tSet f = c(0) : f c(1), chg(ii, 1)",
                "\t\t\tNext",
                "\t\tEnd If",
                "\tNext",
                "End Sub",
                "Sub PadLampSet(o, v)   ' 0 off, 1 on, more: a lit RGB insert's colour",
                "\tIf v > 1 Then",
                "\t\tIf o.ColorFull <> v Then o.ColorFull = v : o.Color = PadDim(v)",
                "\t\tIf o.State <> 1 Then o.State = 1",
                "\tElseIf o.State <> v Then",
                "\t\to.State = v",
                "\tEnd If",
                "End Sub",
                "Function PadDim(v)   ' the unlit tint, as the tributes' SetLightColor makes it",
                "\tPadDim = RGB((v And 255) \\ 14, ((v \\ 256) And 255) \\ 14, ((v \\ 65536) And 255) \\ 14)",
                "End Function",
                "Sub PadReassertLamps   ' the machine's last word on every mapped light, again",
                "\tDim k, o",
                "\tFor Each k In PadLampState.Keys",
                "\t\tIf PadLamps.Exists(k) Then",
                "\t\t\tFor Each o In PadLamps(k) : PadLampSet o, PadLampState(k) : Next",
                "\t\tEnd If",
                "\tNext",
                "\tFor Each o In PadDark",
                "\t\tIf o.State <> 0 Then o.State = 0",
                "\tNext",
                "End Sub",
                "Sub PadDumpLamps(path)   ' vpxkeys.py lamps <file>: every mapped light's state",
                "\tDim fso, f, k, o",
                "\tSet fso = CreateObject(\"Scripting.FileSystemObject\")",
                "\tSet f = fso.CreateTextFile(path & \".tmp\", True)",
                "\tFor Each k In PadLamps.Keys",
                "\t\tFor Each o In PadLamps(k) : f.WriteLine k & \" \" & o.Name & \" \" & o.State : Next",
                "\tNext",
                "\tf.Close",
                "\tIf fso.FileExists(path) Then fso.DeleteFile path",
                "\tfso.MoveFile path & \".tmp\", path",
                "End Sub"]
    for name, args in quiet.items():
        out.append("Sub %s%s : End Sub   ' PAD: quiet; the machine lights the table" % (name, args))
    # ---- saucers
    for k, s in saucers(m).items():
        if s.get("stack"):
            # a full lane: the ball has nowhere to stop and rolls back out
            out += ["Sub %s_Hit" % k,
                    "\tIf bs%s.Balls >= %d Then" % (k, 1 + len(s["stack"])),
                    "\t\tMe.Kick %d, %d" % (s["dir"], s["power"]),
                    "\t\tExit Sub",
                    "\tEnd If",
                    "\tbs%s.AddBall Me : PlaySoundAt \"fx_kicker_enter\", %s%s" % (k, k, fx(k + "_Hit"))]
            if s.get("held_ms"):          # the post is down: it rolls on through
                out.append("\tIf PadHeld%s And Not PadHeld%sRun Then PadHeld%s_Next" % (k, k, k))
            out.append("End Sub")
        else:
            out.append("Sub %s_Hit : bs%s.AddBall Me : PlaySoundAt \"fx_kicker_enter\", %s%s : End Sub"
                       % (k, k, k, fx(k + "_Hit")))
        if s.get("held_ms"):
            # a lock POST (PAD-901): the game holds it down for as long as it
            # wants balls out (Deadpool: 12 s at a multiball, every locked
            # ball rolling out under it), where a kicker coil is one pulse a
            # ball; a ball each held_ms while the post stays down
            out += ["Dim PadHeld%s, PadHeld%sRun" % (k, k),
                    "PadHeld%s = False : PadHeld%sRun = False" % (k, k),
                    "Sub PadHeld%s_Sol(e)" % k,
                    "\tPadHeld%s = CBool(e)" % k,
                    "\tIf PadHeld%s And Not PadHeld%sRun Then PadHeld%s_Next" % (k, k, k),
                    "End Sub",
                    "Sub PadHeld%s_Next" % k,
                    "\tPadHeld%sRun = False" % k,
                    "\tIf Not PadHeld%s Then Exit Sub" % k,
                    "\tIf bs%s.Balls = 0 Then Exit Sub" % k,
                    "\tbs%s.ExitSol_On" % k,
                    "\tPadHeld%sRun = True" % k,
                    "\tvpmTimer.AddTimer %d, \"PadHeld%s_Next '\"" % (s["held_ms"], k),
                    "End Sub"]
    # ---- solenoids
    out += ["", "'---- the machine's coils (godzilla-style numbering: the map's small numbers)"]
    held = {"bs%s.SolOut" % k: "PadHeld%s_Sol" % k for k, s in saucers(m).items() if s.get("held_ms")}
    for num, s in m["solenoids"].items():
        if num == "_" or not s.get("callback"):
            continue
        cb = held.get(s["callback"], s["callback"])
        calls = dof.get("sol:" + num)
        if calls:
            # the coil's own action, then the DOF the table fired beside it
            out += ["Sub PadSol%s(e)" % num, "\t%s e" % cb, "\tIf e Then"]
            out += ["\t\t" + c for c in calls]
            out += ["\tEnd If", "End Sub",
                    "SolCallback(%s) = %s          ' %s" % (num, vb("PadSol" + num), s["name"])]
        else:
            out.append("SolCallback(%s) = %s          ' %s" % (num, vb(cb), s["name"]))
    for const, sub in flips.items():
        out.append("SolCallback(%s) = %s          ' the machine's flipper coil" % (const, vb(sub)))
    # ---- test hook
    out += ["", "Sub PadTestTimer_Timer",
            "\tOn Error Resume Next"]
    if lamps:
        # a light show the shadow game still runs (a LightSeq, a GI timer, a
        # tilt) can overwrite the machine's states; every half second they
        # are put back, so the machine always wins within that
        out.append("\tPadTick = PadTick + 1 : If PadTick Mod 5 = 0 Then PadReassertLamps")
    if m.get("test_shoot"):
        out.append("\tPadTraceTick")
    out += ["\tDim fso, p, f, parts",
            "\tSet fso = CreateObject(\"Scripting.FileSystemObject\")",
            "\tp = fso.GetSpecialFolder(2) & \"\\padvpx_keys.txt\"",
            "\tIf Not fso.FileExists(p) Then Exit Sub",
            "\tSet f = fso.OpenTextFile(p, 1)",
            "\tDo While Not f.AtEndOfStream",
            "\t\tparts = Split(Trim(f.ReadLine), \" \")",
            "\t\tIf UBound(parts) = 1 Then",
            "\t\t\tIf parts(0) = \"down\" Then Table1_KeyDown CInt(parts(1))",
            "\t\t\tIf parts(0) = \"up\" Then Table1_KeyUp CInt(parts(1))",
            "\t\t\tIf parts(0) = \"lamps\" Then PadDumpLamps parts(1)",
            "\t\tEnd If"]
    if m.get("test_shoot"):
        # a generated table's test shooter (vpxgen.PadShoot): a ball at a spot
        out += ["\t\tIf UBound(parts) = 4 Then",
                "\t\t\tIf parts(0) = \"shoot\" Then",
                "\t\t\t\tPadShoot CInt(parts(1)), CInt(parts(2)), CInt(parts(3)), CInt(parts(4))",
                "\t\t\tEnd If",
                "\t\tEnd If"]
    out += ["\tLoop",
            "\tf.Close",
            "\tfso.DeleteFile p",
            "End Sub", ""]
    out += [m.get("extra_vbs", "")]
    return "\n".join(out) + "\n"


#: The coin door's service buttons on Visual Pinball's 7 8 9 0 (DirectInput
#: 8-11, VPM's coin door keys), in the coin door's order: Back, Minus, Plus,
#: Select. A first boot opens Guided Setup, where a player sets Free Play,
#: and a table without these could never leave it (PAD-882). The switch is
#: the controller's SERVICE number (padcontroller.py), not a title's id.
SERVICE_KEYS = [(8, 9011, "7: Service Back"), (9, 9010, "8: Service Minus"),
                (10, 9009, "9: Service Plus"), (11, 9008, "0: Service Select")]


def with_service_keys(lines):
    """`lines` (a script's) with the service buttons in the bridge's
    Table1_KeyDown / Table1_KeyUp, and the table's own handler kept off those
    four keys. Used by the patch and, for a table patched before PAD-882, by
    service_keys_in_place: both give the same script. -> (lines, changed)."""
    if any("Controller.Switch(%d)" % SERVICE_KEYS[0][1] in ln for ln in lines):
        return lines, False
    out, sub, changed = [], None, False
    lo, hi = SERVICE_KEYS[0][0], SERVICE_KEYS[-1][0]
    for ln in lines:
        s, cr = ln.strip(), "\r" if ln.endswith("\r") else ""
        if s in ("Sub Table1_KeyDown(ByVal KeyCode)", "Sub Table1_KeyUp(ByVal KeyCode)"):
            sub = "True" if "KeyDown" in s else "False"
            out.append(ln)
            out += ["\tIf KeyCode = %d Then Controller.Switch(%d) = %s   ' %s%s"
                    % (k, sw, sub, what, cr) for k, sw, what in SERVICE_KEYS]
            changed = True
            continue
        if sub and s == "End Sub":
            sub = None
        elif sub and s in ("Table1_KeyDown_orig KeyCode", "Table1_KeyUp_orig KeyCode"):
            ln = "%sIf KeyCode < %d Or KeyCode > %d Then %s%s" % (
                ln[:len(ln) - len(ln.lstrip())], lo, hi, s, cr)
        out.append(ln)
    return out, changed


def service_keys_in_place(path):
    """A table this patcher wrote before PAD-882 gets the service keys where
    it is, once (the tab's Play runs this, as it quiets old soundtracks).
    Returns the report lines, [] when there was nothing to do."""
    table = vpxfile.VpxTable(path)
    script = table.script()
    table.ole.close()
    if "(vpxshadow.py)" not in script:
        return []                           # not a scripted tribute this kit patched
    lines, changed = with_service_keys(script.split("\n"))
    if not changed:
        return []
    tmp = path + ".pad-keys.tmp"
    vpxfile.write_patched(path, tmp, script="\n".join(lines))
    check = vpxfile.VpxTable(tmp)
    ok = check.verify()
    check.ole.close()
    if not ok:
        os.remove(tmp)
        return ["WARNING: %s with the service keys does not verify; left as it was"
                % os.path.basename(path)]
    os.replace(tmp, path)
    return ["keys: the coin door's service buttons on 7 8 9 0 (Back, Minus, Plus, Select)"]


def flipper_subs(m, had):
    """core.vbs flipper constant -> the table's own flipper sub, for the
    machine's flipper coils to call. The map's `flippers` names them
    (`{"sLLFlipper": "SolLFlipper", ...}`); without it, a table's SolLFlipper /
    SolRFlipper / SolULFlipper / SolURFlipper are taken when it has them."""
    flips = dict(m.get("flippers", {}))
    flips.pop("_", None)
    if not flips:
        for const, sub in (("sLLFlipper", "SolLFlipper"), ("sLRFlipper", "SolRFlipper"),
                           ("sULFlipper", "SolULFlipper"), ("sURFlipper", "SolURFlipper")):
            if had.get(sub):
                flips[const] = sub
    return flips


def has_sub(lines, name):
    pat = re.compile(r"^\s*(?:Public\s+|Private\s+)?(?:Sub|Function)\s+%s\b" % re.escape(name), re.I)
    return any(pat.match(ln) for ln in lines)


def dof_calls(lines, m):
    """Handler -> the table's DOF calls the bridge's own sub must make: what
    each stood-in event sub fires at its own level (gen uses it only where
    the original is not called), and per coil what the table fires beside
    kicking the trough's release, a saucer or the auto plunger. Read from the
    script as written, before any sub is renamed or line neutered."""
    stmts = list(_walk(lines))
    dof = {}
    for name, s in m["switches"].items():
        if name != "_":
            for ev in EVENT_SUBS[s.get("event", "hit")]:
                dof[name + ev] = dof_of_sub(stmts, name + ev)
    for name in [m["trough"]["drain"]] + list(saucers(m)):
        dof[name + "_Hit"] = dof_of_sub(stmts, name + "_Hit")
    fires = {"bsTrough.SolOut": m["trough"]["release"]}
    fires.update({"bs%s.SolOut" % k: k for k in saucers(m)})
    if m.get("plunger"):
        fires["PadAutoPlunge"] = m["plunger"]["autoplunge"]
    for num, s in m["solenoids"].items():
        obj = fires.get(s.get("callback")) if num != "_" else None
        if obj:
            dof["sol:" + num] = dof_at_fire(stmts, obj)
    return {k: v for k, v in dof.items() if v}


def patch(script, m):
    rep = []
    lines = script.split("\n")
    dof = dof_calls(lines, m)
    for name in m["switches"]:
        if name != "_" and _calls_orig(m, name):   # its own sub runs and fires them
            for k in [k for k in dof if k.rsplit("_", 1)[0] == name]:
                del dof[k]
    if dof:
        rep.append("DOF carried into the bridge: %s" % ", ".join(
            "%s (%s)" % (k, ", ".join(c.split()[1].rstrip(",") for c in v)) for k, v in dof.items()))
    if m.get("b2s_name"):
        rename_game(lines, m["b2s_name"], rep)
    had = {}
    for name in ("Table1_Init", "Table1_KeyDown", "Table1_KeyUp", "Table1_Exit",
                 "Table1_Paused", "Table1_UnPaused", m["trough"]["drain"] + "_Hit"):
        had[name] = rename_sub(lines, name, rep)
    p = m.get("plunger")
    if p:
        for ev in ("_Hit", "_UnHit"):
            had[p["lane_trigger"] + ev] = rename_sub(lines, p["lane_trigger"] + ev, rep)
    for name, s in m["switches"].items():
        if name == "_":
            continue
        for ev in EVENT_SUBS[s.get("event", "hit")]:
            had[name + ev] = rename_sub(lines, name + ev, rep)
    for k in saucers(m):
        rename_sub(lines, k + "_Hit", rep)
    for sub in ("SolLFlipper", "SolRFlipper", "SolULFlipper", "SolURFlipper"):
        had[sub] = has_sub(lines, sub)
    quiet = {}
    for name in m.get("quiet_subs", []):
        args = quiet_sub(lines, name, rep)
        if args is not None:
            quiet[name] = args
    neuter(lines, m.get("neuter", []), rep)
    route_b2s(lines, rep)
    own_lamp_reads(lines, rep)
    stub = pup_stub(lines, rep) if m.get("pup_stub") else ""
    flex_optional(lines, rep)
    # what core.vbs's PinMAMETimer expects a VPM table to declare, at the TOP:
    # Iron Maiden loads core.vbs and controller.vbs itself near its start,
    # and they died on "Variable is undefined: 'UseSolenoids'" with this line
    # at the end of the script, not yet run
    # after Option Explicit wherever it is (Aerosmith's is on line 133, under
    # a long comment header): before it, VBScript refuses the whole script
    at = next((i + 1 for i, ln in enumerate(lines)
               if ln.strip().lower().startswith("option explicit")), 0)
    lines.insert(at, "Const UseSolenoids = 1, UseLamps = 0, UseGI = 0, UsePdbLeds = 0"
                     "   ' PAD: for core.vbs (vpxshadow.py)")
    text = "\n".join(lines) + gen(m, had, quiet, dof) + stub
    return text, rep


def retrofit_items(table, m):
    by_name = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        by_name[name] = (kind, data)
    items = []
    rl = m.get("retrofit_lights", {})
    for name, v in rl.get("lights", {}).items():
        if name == "_":
            continue
        kind, src = by_name[v.get("clone", rl.get("clone"))]
        assert kind == "Light", v.get("clone", rl.get("clone"))
        items.append(vpxfile.clone_item(src, name, *v["at"]))
    for name, v in m.get("retrofit_timers", {}).items():
        if name == "_":
            continue
        kind, src = by_name[v["clone"]]
        assert kind == "Timer", v["clone"]
        item = vpxfile.clone_item(src, name, 0, 0)
        items.append(vpxfile.set_fields(item, {"TMON": struct.pack("<i", 1),
                                               "TMIN": struct.pack("<i", int(v["interval_ms"]))}))
    return items


def main(argv):
    if len(argv) != 4:
        print(__doc__)
        return 2
    mpath, src, outdir = argv[1:]
    m = json.load(open(mpath, encoding="utf-8"))
    os.makedirs(outdir, exist_ok=True)
    table = vpxfile.VpxTable(src)
    if not table.verify():
        print("refusing: %s does not verify against its own MAC" % src)
        return 1
    info = [table.item_info(d) for d in table.items]
    names = {n.lower() for _, n, _ in info}
    for name in list(m["switches"]) + list(saucers(m)) + list(m.get("lamps", {})) + m.get("dark", []):
        if name != "_" and name.lower() not in names:
            print("WARNING: the table has no object named %s" % name)
    m["_lightseqs"] = sorted(n for k, n, _ in info if k == "LightSeq")
    script, rep = patch(table.script(), m)
    script, streams = vpxsounds.quiet(script, table.ole, rep)   # PAD-858
    items = retrofit_items(table, m)
    table.ole.close()
    dst = os.path.join(outdir, m["output"])
    mac = vpxfile.write_patched(src, dst, script=script, new_items=items, streams=streams)
    open(os.path.join(outdir, m["output"][:-4] + ".script.vbs"), "w", encoding="utf-8",
         newline="").write(script)
    ok = vpxfile.VpxTable(dst).verify()
    print("wrote %s\n  MAC %s  verify %s  +%d items" % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(items)))
    for r in rep:
        print("  " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
