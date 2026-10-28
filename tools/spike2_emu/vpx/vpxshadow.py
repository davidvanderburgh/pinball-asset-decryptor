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
  * keys: Start, launch, coins and the flipper BUTTONS go to the machine, and
    Table1_KeyDown passes everything else on to the original handler;
  * the flippers are the MACHINE's coils: core.vbs's sLLFlipper/sLRFlipper
    callbacks go to the table's own SolLFlipper/SolRFlipper (their tricks and
    sounds stay), since a tribute flips from the key only while ITS game is
    in play, which it never is. The map's `flippers` can name other subs.

Lamps are left to the shadow game until the title's LED identities are known
(these builds carry no lamp positions or names in their device table).

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

SUB_RE = r"^(\s*)(Public\s+|Private\s+)?Sub\s+(%s)\s*(\([^)]*\))?(\s*'.*|\s*:.*)?$"


def saucers(m):
    return {k: v for k, v in m.get("saucers", {}).items() if k != "_"}


def rename_sub(lines, name, rep):
    """Rename `Sub <name>` to `Sub <name>_orig`; True if it existed."""
    pat = re.compile(SUB_RE % re.escape(name), re.I)
    for i, line in enumerate(lines):
        m = pat.match(line.rstrip("\r"))
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
        m = pat.match(line.rstrip("\r"))
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


def vb(s):
    return '"' + s.replace('"', '""') + '"'


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
        for m in re.finditer(r"\bPuPlayer\.(\w+)\s*(.*)$", s):
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
    for i, line in enumerate(lines):
        if re.search(r'Set\s+PuPlayer\s*=\s*CreateObject\("PinUpPlayer\.PinDisplay"\)', line, re.I):
            ind = re.match(r"^\s*", line).group(0)
            lines[i] = "\n".join([
                ind + "On Error Resume Next",
                line.rstrip("\r"),
                ind + "If Err Then Err.Clear : Set PuPlayer = New PadNoPuP : End If   ' PAD: no PinUP Player here",
                ind + "On Error Goto 0"])
            rep.append("PuP made optional (PadNoPuP stands in, %d methods)" % len(counts))
            break
    out = ["", "'---- PAD: PinUP Player's shape, for a machine without it", "Class PadNoPuP"]
    for meth, cs in sorted(counts.items()):
        n = max(cs, key=cs.get)
        if len(cs) > 1:
            rep.append("WARNING: PuPlayer.%s is called with %s arguments; the stub takes %d" % (meth, sorted(cs), n))
        args = ", ".join("a%d" % k for k in range(n))
        out.append("\tPublic Sub %s(%s) : End Sub" % (spelling[meth], args))
    out += ["End Class", ""]
    return "\n".join(out)


def lamp_number(node, index):
    return 1000 + node * 100 + index


def lamp_groups(m):
    """lamp number -> [table lights]: the controller reports a mapped insert
    under the number of its FIRST LED (padcontroller.VpxMap), lit when any of
    the insert's LEDs is; several table lights may share one."""
    groups = {}
    for name, v in m.get("lamps", {}).items():
        if name == "_" or not isinstance(v, dict):
            continue
        node, idx = v["leds"][0]
        groups.setdefault(lamp_number(node, idx), []).append(name)
    return groups


def gen(m, had, quiet=None):
    """The bridge's own script, appended after the original."""
    cab = m["cabinet"]
    quiet = quiet or {}
    lamps = lamp_groups(m)
    orig_keep = {n.lower() for n in m.get("orig_keep", [])}

    def calls_orig(name):
        # with the machine's lamps on the table, a tribute's own hit subs
        # (its rules: lights, sounds, scores) stay out of the way; the real
        # game's LCD and sound say what a hit was worth
        return m.get("orig_hits", True) or name.lower() in orig_keep
    out = ["", "", "'" + "=" * 70, "'==== PAD: the Spike 2 emulator drives this table (vpxshadow.py) ====",
           "'" + "=" * 70,
           "' what core.vbs's PinMAMETimer expects a VPM table to declare",
           "Const UseSolenoids = 1, UseLamps = 0, UseGI = 0, UsePdbLeds = 0",
           "Dim bsTrough"]
    for k in saucers(m):
        out.append("Dim bs%s" % k)
    # ---- Init
    out += ["", "Sub Table1_Init"]
    if had["Table1_Init"]:
        out.append("\tTable1_Init_orig            ' the table's own physics, sounds, attract")
    out += ["\tOn Error Resume Next",
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
        out += ["\tSet bs%s = New cvpmBallStack" % k,
                "\t\tbs%s.InitSaucer %s, 1%03d, %d, %d" % (k, k, s["switch"], s["dir"], s["power"]),
                "\t\tbs%s.KickZ = %s" % (k, s.get("kickz", 0))]
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
    out += ["End Sub",
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
    # ---- the trough and the plunger lane
    t = m["trough"]
    out += ["Sub %s_Hit" % t["drain"],
            "\tbsTrough.AddBall Me",
            "\tPlaySoundAt \"fx_drain\", %s" % t["drain"],
            "End Sub"]
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
    for name, s in m["switches"].items():
        if name == "_":
            continue
        ev = s.get("event", "hit")
        sid = 1000 + s["id"]
        if ev == "hit":
            body = "vpmTimer.PulseSw %d" % sid
            if had.get(name + "_Hit") and calls_orig(name):
                body += " : %s_Hit_orig" % name
            out.append("Sub %s_Hit : %s : End Sub" % (name, body))
        elif ev == "hold":
            b1 = "Controller.Switch(%d) = True" % sid
            b0 = "Controller.Switch(%d) = False" % sid
            if had.get(name + "_Hit") and calls_orig(name):
                b1 += " : %s_Hit_orig" % name
            if had.get(name + "_UnHit") and calls_orig(name):
                b0 += " : %s_UnHit_orig" % name
            out.append("Sub %s_Hit : %s : End Sub" % (name, b1))
            out.append("Sub %s_UnHit : %s : End Sub" % (name, b0))
        elif ev == "spin":
            body = "vpmTimer.PulseSw %d" % sid
            if had.get(name + "_Spin") and calls_orig(name):
                body += " : %s_Spin_orig" % name
            out.append("Sub %s_Spin : %s : End Sub" % (name, body))
        elif ev == "slingshot":
            body = "vpmTimer.PulseSw %d" % sid
            if had.get(name + "_Slingshot") and calls_orig(name):
                body += " : %s_Slingshot_orig" % name
            out.append("Sub %s_Slingshot : %s : End Sub" % (name, body))
    # ---- lamps
    if lamps:
        out += ["", "'---- the machine's lamps: number 1000 + node * 100 + LED index, one",
                "'     table light (or several) per insert; core.vbs calls LampCallback",
                "'     every tick with UseLamps = 0, and this reads ChangedLamps itself",
                "Dim PadLamps : Set PadLamps = CreateObject(\"Scripting.Dictionary\")",
                "Dim PadLampState : Set PadLampState = CreateObject(\"Scripting.Dictionary\")",
                "Dim PadTick : PadTick = 0",
                "Sub PadLampsInit"]
        for num in sorted(lamps):
            out.append("\tPadLamps.Add \"%d\", Array(%s)" % (num, ", ".join(lamps[num])))
        out += ["End Sub",
                "Sub PadUpdateLamps",
                "\tDim chg, ii, o, k",
                "\tchg = Controller.ChangedLamps",
                "\tIf IsEmpty(chg) Then Exit Sub",
                "\tFor ii = 0 To UBound(chg)",
                "\t\tk = CStr(chg(ii, 0))",
                "\t\tIf PadLamps.Exists(k) Then",
                "\t\t\tPadLampState(k) = chg(ii, 1)",
                "\t\t\tFor Each o In PadLamps(k) : o.State = chg(ii, 1) : Next",
                "\t\tEnd If",
                "\tNext",
                "End Sub",
                "Sub PadReassertLamps   ' the machine's last word on every mapped light, again",
                "\tDim k, o",
                "\tFor Each k In PadLampState.Keys",
                "\t\tFor Each o In PadLamps(k)",
                "\t\t\tIf o.State <> PadLampState(k) Then o.State = PadLampState(k)",
                "\t\tNext",
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
    for k in saucers(m):
        out.append("Sub %s_Hit : bs%s.AddBall Me : PlaySoundAt \"fx_kicker_enter\", %s : End Sub" % (k, k, k))
    # ---- solenoids
    out += ["", "'---- the machine's coils (godzilla-style numbering: the map's small numbers)"]
    for num, s in m["solenoids"].items():
        if num == "_" or not s.get("callback"):
            continue
        out.append("SolCallback(%s) = %s          ' %s" % (num, vb(s["callback"]), s["name"]))
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


def patch(script, m):
    rep = []
    lines = script.split("\n")
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
        evs = {"hit": ("_Hit",), "hold": ("_Hit", "_UnHit"), "spin": ("_Spin",),
               "slingshot": ("_Slingshot",)}[s.get("event", "hit")]
        for ev in evs:
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
    stub = pup_stub(lines, rep) if m.get("pup_stub") else ""
    text = "\n".join(lines) + gen(m, had, quiet) + stub
    return text, rep


def retrofit_items(table, m):
    by_name = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        by_name[name] = (kind, data)
    items = []
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
    for name in list(m["switches"]) + list(saucers(m)) + list(m.get("lamps", {})):
        if name != "_" and name.lower() not in names:
            print("WARNING: the table has no object named %s" % name)
    m["_lightseqs"] = sorted(n for k, n, _ in info if k == "LightSeq")
    script, rep = patch(table.script(), m)
    items = retrofit_items(table, m)
    table.ole.close()
    dst = os.path.join(outdir, m["output"])
    mac = vpxfile.write_patched(src, dst, script=script, new_items=items)
    open(os.path.join(outdir, m["output"][:-4] + ".script.vbs"), "w", encoding="utf-8",
         newline="").write(script)
    ok = vpxfile.VpxTable(dst).verify()
    print("wrote %s\n  MAC %s  verify %s  +%d items" % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(items)))
    for r in rep:
        print("  " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
