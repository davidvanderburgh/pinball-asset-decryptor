#!/usr/bin/env python3
"""patch_metallica_spike.py - VPW's "Metallica Premium Monsters (Stern 2013)"
2.0.2, rewired from Stern's SAM ROM (mtl_180h) to the Spike 2 emulator running
Metallica Remastered (metallica_spike), the same playfield.

    python patch_metallica_spike.py "<Metallica Premium Monsters (Stern 2013) VPW 2.0.2.vpx>" <out dir>

Writes `<out dir>/<original name> (PAD).vpx` beside a copy of PADSPIKE2.vbs,
which the table loads from its own folder, and the patched script as
`<original name> (PAD).script.vbs`. The table is re-signed
(vpxfile.write_patched) so Visual Pinball loads it.

WHAT CHANGES, all of it driven by metallica_spike.vpxmap.json:

  script   controller.vbs + sam.VBS -> PADSPIKE2.vbs (PAD.Controller), with
           this title's flipper buttons; GameName metallica_spike;
           UseSolenoids 2 (fast flips on the controller's game-on solenoid),
           UseLamps 0, UseVPMModSol 0 (the controller reports 0/1);
           every literal switch number -> its Spike 2 id + 1000 (the target
           helpers' computed `Switchid mod 100` go through the map's
           switch_rewrite in the controller); the flipper callbacks move to
           core.vbs's flipper Consts; the SAM fast-flip init goes; the lamp
           block: every insert and RGB channel on its Spike 2 LED, the
           flashers (LEDs on Spike 2) calling the table's own SolModCallback
           subs, the white GI switched on; the lockbar key presses the
           Action button; PadTestTimer for scripted keys.
  objects  one Timer (PadTestTimer, cloned from UpdateTroughTimer).

Everything else - art, physics, the physical trough, the toys - is VPW's.
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

MAP = os.path.join(HERE, "metallica_spike.vpxmap.json")


def lamp_num(node, idx):
    return 1000 + node * 100 + idx


def patch_script(src, m):
    """The table script, rewired. Returns (text, report lines)."""
    rep = []
    rewrite = {int(k): int(v) for k, v in m["switch_rewrite"].items() if k != "_"}
    sw_re = re.compile(r"((?:Controller\.Switch|PulseSw)\s*\(?\s*)(\d+)\b", re.I)
    sol_flip = {"15": "sLLFlipper", "16": "sLRFlipper"}
    cab = m["cabinet"]
    out = []
    seen = set()
    rewritten = dropped = 0
    cur_sub = None

    def need(tag):
        seen.add(tag)

    for raw in src.split("\n"):
        line = raw.rstrip("\r")
        s = line.strip()
        low = s.lower()
        msub = re.match(r"^(?:public |private )?sub\s+([A-Za-z0-9_]+)", s, re.I)
        if msub:
            cur_sub = msub.group(1).lower()
        if low == "end sub":
            cur_sub = None

        # ---- the header: our system script, our title, our conventions
        if low.startswith('executeglobal gettextfile("controller.vbs")'):
            out.append('ExecuteGlobal GetTextFile("PADSPIKE2.vbs")')
            need("system")
            continue
        if low.startswith('if err then msgbox "can\'t open controller.vbs"'):
            out.append('If Err Then MsgBox "You need PADSPIKE2.vbs beside this table (tools\\spike2_emu\\vpx)"')
            continue
        if re.match(r'^const cgamename\s*=\s*"mtl_180h"', low):
            out.append('Const cGameName = "%s"\t\' PAD: Spike 2 Metallica Remastered (was mtl_180h)' % m["title"])
            need("gamename")
            continue
        if re.match(r"^const usesolenoids\s*=", low):
            out.append("Const UseSolenoids = 2\t' PAD: fast flips on the controller's game-on solenoid")
            need("usesol")
            continue
        if re.match(r"^const uselamps\s*=", low):
            out.append("Const UseLamps = 0\t' PAD: PadUpdateLamps (LampCallback) reads ChangedLamps itself")
            need("uselamps")
            continue
        if re.match(r"^const usevpmmodsol\s*=", low):
            out.append("Const UseVPMModSol = 0\t' PAD: the controller reports solenoids 0/1")
            need("modsol")
            continue
        if low.startswith("loadvpm "):
            out.append("' PAD: this title's cabinet (PADSPIKE2.vbs defaults to godzilla_le's)")
            out.append("swLRFlip = %d : swLLFlip = %d : swULFlip = 0 : swURFlip = 0"
                       % (cab["right_flipper"], cab["left_flipper"]))
            out.append('LoadVPM "01000000", "PADSPIKE2.vbs", 3.10')
            need("loadvpm")
            continue

        # ---- Table_Init
        if cur_sub == "table_init" and low == "initvpmfflipssam":
            out.append("\t' PAD: no SAM fast-flip class; core.vbs flips on GameOnSolenoid (UseSolenoids 2)")
            need("fflips")
            continue
        if cur_sub == "table_init" and low.startswith("vpmmaplights alllamps"):
            out.append(line)
            out.append("\tPadLampsInit")
            out.append("\tSet LampCallback = GetRef(\"PadUpdateLamps\")")
            for gi in m.get("gi_on", {}).get("lights", []):
                out.append("\t%s.State = 1\t' PAD: white GI on (no GI LED on Spike 2)" % gi)
            need("lamps")
            continue
        if cur_sub == "table_init" and re.match(r"^vpmnudge\.tiltswitch\s*=", low):
            out.append("\tvpmNudge.TiltSwitch = swTilt\t' PAD: Tilt Pendulum")
            need("tilt")
            continue

        # ---- keys: Start is PADSPIKE2.vbs's; the lockbar is the Action button
        if cur_sub in ("table_keydown", "table_keyup") and re.match(
                r"^if keycode = startgamekey then controller\.switch\(16\)", low):
            out.append("\t' PAD: Start is pressed by PADSPIKE2.vbs's vpmKeyDown/vpmKeyUp")
            need("start_" + cur_sub)
            continue
        if cur_sub in ("table_keydown", "table_keyup") and re.match(r"^if vpmkey(down|up)\(keycode\)", low):
            state = 1 if cur_sub == "table_keydown" else 0
            out.append("\tIf keycode = LockBarKey Then Controller.Switch(%d) = %d\t' PAD: Action button"
                       % (cab["launch"], state))
            out.append(line)
            need("lockbar_" + cur_sub)
            continue

        # ---- flipper callbacks on core.vbs's Consts
        mflip = re.match(r"^solcallback\((15|16)\)\s*=\s*(\"[^\"]*\")(.*)$", s, re.I)
        if mflip:
            out.append("SolCallback(%s) = %s%s\t' PAD: Spike 2 %s FLIPPER"
                       % (sol_flip[mflip.group(1)], mflip.group(2), mflip.group(3),
                          "LEFT" if mflip.group(1) == "15" else "RIGHT"))
            need("flip" + mflip.group(1))
            continue

        # ---- literal switch numbers
        def _rw(mm):
            nonlocal rewritten, dropped
            n = int(mm.group(2))
            if n >= 1000:
                return mm.group(0)
            sid = rewrite.get(n)
            if not sid:
                dropped += 1
                return mm.group(0)     # left on its SAM number: the controller drops it
            rewritten += 1
            return "%s%d" % (mm.group(1), 1000 + sid)
        line = sw_re.sub(_rw, line)
        out.append(line)

    want = {"system", "gamename", "usesol", "uselamps", "modsol", "loadvpm", "fflips", "lamps",
            "tilt", "start_table_keydown", "start_table_keyup", "lockbar_table_keydown",
            "lockbar_table_keyup", "flip15", "flip16"}
    missing = want - seen
    if missing:
        raise SystemExit("the script is not the one this patcher knows: no %s" % ", ".join(sorted(missing)))

    text = "\n".join(out)
    text += "\n".join([""] + gen_lamp_block(m) + gen_test_timer() + [""])
    rep.append("literal switch numbers rewritten: %d; left on SAM numbers (no Spike 2 switch): %d"
               % (rewritten, dropped))
    return text, rep


def gen_lamp_block(m):
    """Spike 2 lamp number -> the table's lights, and -> the flasher subs."""
    lights, subs = {}, {}
    for name, v in m["lamps"].items():
        if name == "_":
            continue
        num = lamp_num(*v["leds"][0])
        if v.get("sub"):
            subs.setdefault(num, []).append(v["sub"])
        else:
            lights.setdefault(num, []).append(name)
    out = ["", "",
           "'---- PAD: the machine's lamps (metallica_spike.vpxmap.json `lamps`): number",
           "'     1000 + node * 100 + LED index; core.vbs calls LampCallback every tick",
           "'     with UseLamps = 0, and this reads ChangedLamps itself. A flasher is an",
           "'     LED on Spike 2: its number calls the table's own SolModCallback sub.",
           "Dim PadLamps : Set PadLamps = CreateObject(\"Scripting.Dictionary\")",
           "Dim PadFlash : Set PadFlash = CreateObject(\"Scripting.Dictionary\")",
           "Dim PadLampState : Set PadLampState = CreateObject(\"Scripting.Dictionary\")",
           "Sub PadLampsInit"]
    for num in sorted(lights):
        out.append("\tPadLamps.Add \"%d\", Array(%s)" % (num, ", ".join(lights[num])))
    for num in sorted(subs):
        out.append("\tPadFlash.Add \"%d\", Array(%s)"
                   % (num, ", ".join("GetRef(\"%s\")" % s for s in subs[num])))
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
            "\t\tIf PadFlash.Exists(k) Then",
            "\t\t\tFor Each o In PadFlash(k) : o chg(ii, 1) : Next",
            "\t\tEnd If",
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
    return out


def gen_test_timer():
    return ["",
            "'---- PAD: scripted keys for a test run. Visual Pinball polls its keyboard",
            "'---- itself, so a test cannot hand it a key from outside; this timer reads",
            "'---- %TEMP%\\padvpx_keys.txt (one `down <code>` / `up <code>` per line,",
            "'---- DirectInput codes: 2 = Start, 42 = left flipper, 54 = right, 28 = plunger,",
            "'---- 56 = lockbar / Action; `lamps <file>` dumps the lights) and feeds the",
            "'---- table's own key handlers, then deletes the file.",
            "'---- It also re-sends the table's held switches every two seconds",
            "'---- (PadSync): a switch set before the controller attaches to the run",
            "'---- (Table_Init's trough, the raised drop targets, the grave marker",
            "'---- at its top) never reaches the game, and the rig's ball feeder",
            "'---- may have filled TROUGH 5 / 6, which this four-ball table never holds.",
            "Dim PadSyncTick : PadSyncTick = 0",
            "Sub PadSync",
            "\tDim i",
            "\tController.Switch(1070) = 0 : Controller.Switch(1071) = 0 : Controller.Switch(1076) = 0",
            "\tController.Switch(1075) = (sw21.BallCntOver > 0)",
            "\tController.Switch(1074) = (sw20.BallCntOver > 0)",
            "\tController.Switch(1073) = (sw19.BallCntOver > 0)",
            "\tController.Switch(1072) = (sw18.BallCntOver > 0)",
            "\tFor i = 0 To UBound(DTArray)",
            "\t\tController.Switch(DTArray(i).sw) = Not DTArray(i).isDropped   ' SAM polarity: raised = made",
            "\tNext",
            "\tController.Switch(1093) = (CrossPos >= CrossMax)",
            "\tController.Switch(1092) = (CrossPos <= CrossMin)",
            "End Sub",
            "Sub PadTestTimer_Timer",
            "\tOn Error Resume Next",
            "\tDim fso, p, f, parts",
            "\tPadSyncTick = PadSyncTick + 1",
            "\tIf PadSyncTick >= 20 Then",
            "\t\tPadSyncTick = 0",
            "\t\tPadSync",
            "\tEnd If",
            "\tSet fso = CreateObject(\"Scripting.FileSystemObject\")",
            "\tp = fso.GetSpecialFolder(2) & \"\\padvpx_keys.txt\"",
            "\tIf Not fso.FileExists(p) Then Exit Sub",
            "\tSet f = fso.OpenTextFile(p, 1)",
            "\tDo While Not f.AtEndOfStream",
            "\t\tparts = Split(Trim(f.ReadLine), \" \")",
            "\t\tIf UBound(parts) = 1 Then",
            "\t\t\tIf parts(0) = \"down\" Then Table_KeyDown CInt(parts(1))",
            "\t\t\tIf parts(0) = \"up\" Then Table_KeyUp CInt(parts(1))",
            "\t\t\tIf parts(0) = \"lamps\" Then PadDumpLamps parts(1)",
            "\t\tEnd If",
            "\tLoop",
            "\tf.Close",
            "\tfso.DeleteFile p",
            "End Sub"]


def retrofit_items(table, m):
    by_name = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        by_name[name] = (kind, data)
    items = []
    for name, v in m.get("retrofit_timers", {}).items():
        if name == "_":
            continue
        if name in by_name:
            raise SystemExit("the table already has an object named %s" % name)
        kind, src = by_name[v["clone"]]
        assert kind == "Timer", v["clone"]
        item = vpxfile.clone_item(src, name, 0, 0)
        items.append(vpxfile.set_fields(item, {"TMON": struct.pack("<i", 1),
                                               "TMIN": struct.pack("<i", int(v["interval_ms"]))}))
    return items


def main(argv):
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, outdir = argv[1], argv[2]
    os.makedirs(outdir, exist_ok=True)
    m = json.load(open(MAP, encoding="utf-8"))
    table = vpxfile.VpxTable(src)
    if not table.verify():
        print("refusing: %s does not verify against its own MAC" % src)
        return 1
    script, rep = patch_script(table.script(), m)
    items = retrofit_items(table, m)
    table.ole.close()
    out_name = os.path.splitext(os.path.basename(src))[0] + " (PAD).vpx"
    dst = os.path.join(outdir, out_name)
    mac = vpxfile.write_patched(src, dst, script=script, new_items=items)
    shutil.copyfile(os.path.join(HERE, "PADSPIKE2.vbs"), os.path.join(outdir, "PADSPIKE2.vbs"))
    open(os.path.join(outdir, out_name[:-4] + ".script.vbs"), "w", encoding="utf-8",
         newline="").write(script)
    ok = vpxfile.VpxTable(dst).verify()
    print("wrote %s\n  MAC %s  verify %s\n  +%d items (timers)"
          % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(items)))
    for r in rep:
        print("  " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
