#!/usr/bin/env python3
"""patch_walking_dead.py - "The Walking Dead LE/Premium 4K (Stern 2014)"
(VPUniverse file 25269, Clapper and others), rewired from Stern's SAM ROM
(twd_160h) to the Spike 3 emulator running The Walking Dead Remastered LE
(walking_dead_remastered_le), the same playfield (PAD-1560).

    python patch_walking_dead.py "<The Walking Dead LE Premium (Stern 2014) ... .vpx>" <out dir>

Writes `<out dir>/<the map's output>` beside a copy of PADSPIKE2.vbs, which
the table loads from its own folder, and the patched script as `<output name
less .vpx>.script.vbs`. The table is re-signed (vpxfile.write_patched) so
Visual Pinball loads it. The day and night 1.1 builds and 1.0 share the
script this knows; anything else is refused, naming what it did not find.

WHAT CHANGES, all of it driven by walking_dead_remastered_le.vpxmap.json:

  script   controller.vbs + sam.VBS -> PADSPIKE2.vbs (PAD.Controller) with
           this title's cabinet switches; GameName walking_dead_remastered_le
           (the backglass keeps twd_160h); UseSolenoids 2 (fast flips on the
           controller's game-on solenoid), UseVPMModSol 0; the SAM fast-flip
           init goes; the flipper callbacks move to core.vbs's Consts; the
           tilt is the Remastered TILT PENDULUM. The SAM switch numbers stay:
           the controller reads them through the map's switch_rewrite.
  lamps    the table's own LampTimer still draws every insert from
           ChangedLamps: the controller reports each SAM lamp number as its
           Remastered LED's 0..255 (raw_lamp_rewrite). The flashers are LEDs
           on the Remastered game: their numbers (flash_subs) call the
           table's own SolModCallback subs from the LampTimer.
  crossbow the Remastered crossbow motor counts encoder edges: the table's
           crossbow sweep (Darryl_Timer) steps ENCODER 1 / 2 in quadrature.
           It starts at home (PadSync holds HOME / MARK to where it is) and
           the sweep carries on through the game's motor stop-restarts.
  trough   the Remastered game is a six-ball game and the table has four:
           TROUGH 5 and 6 are held, and the table's held switches re-sent
           every two seconds (PadSync), as Metallica's (PAD-811).
  objects  one Timer (PadTestTimer, cloned from LampTimer).

Everything else - art, physics, the physical trough, the toys - is the table's.
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import vpxfile  # noqa: E402
import vpxsounds  # noqa: E402
from patch_metallica_spike import retrofit_items  # noqa: E402

MAP = os.path.join(HERE, "walking_dead_remastered_le.vpxmap.json")
ROM = "twd_160h"


def cabinet_vars(m):
    """PADSPIKE2.vbs's cabinet switches (godzilla_le's by default), this title's."""
    c = m["cabinet"]
    sw = {int(k): int(v) for k, v in m["switch_rewrite"].items() if k != "_"}
    coins = [c["coin"], c["coin"] + 1, c["coin"] + 2]          # LEFT, CENTER, RIGHT COIN
    return ("swStartButton = %d : swTilt = %d : swSlamTilt = %d : swCoin1 = %d : swCoin2 = %d : "
            "swCoin3 = %d : swLaunch = %d : swLRFlip = %d : swLLFlip = %d : swULFlip = 0 : "
            "swURFlip = 0" % (c["start"], c["tilt"], c["slam"], coins[0], coins[1], coins[2],
                              c["launch"], c["right_flipper"], c["left_flipper"])), sw


def patch_script(src, m):
    """The table script, rewired. Returns (text, report lines)."""
    rep = []
    cab_line, _ = cabinet_vars(m)
    out = []
    seen = set()
    cur_sub = None
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
            seen.add("system")
            continue
        if low.startswith('if err then msgbox "you need the controller.vbs'):
            out.append('If Err Then MsgBox "You need PADSPIKE2.vbs beside this table (tools\\spike2_emu\\vpx)"')
            continue
        if re.match(r'^const cgamename\s*=\s*"%s"' % ROM, low):
            out.append('Const cGameName = "%s"\t\' PAD: Spike 3 The Walking Dead Remastered (was %s)'
                       % (m["title"], ROM))
            out.append('PadB2SName = "%s"\t\' PAD: the backglass (B2S, DOF) knows the table by its ROM' % ROM)
            seen.add("gamename")
            continue
        if re.match(r"^const usesolenoids\s*=", low):
            out.append("Const UseSolenoids = 2\t' PAD: fast flips on the controller's game-on solenoid")
            seen.add("usesol")
            continue
        if re.match(r"^const usevpmmodsol\s*=", low):
            out.append("Const UseVPMModSol = 0\t' PAD: the controller reports solenoids 0/1; "
                       "the flashers come from LEDs (flash_subs)")
            seen.add("modsol")
            continue
        if low.startswith("loadvpm ") and "sam.vbs" in low:
            out.append("' PAD: this title's cabinet (PADSPIKE2.vbs defaults to godzilla_le's)")
            out.append(cab_line)
            out.append('LoadVPM "01000000", "PADSPIKE2.vbs", 3.10')
            seen.add("loadvpm")
            continue

        # ---- Table1_Init
        if cur_sub == "table1_init" and low == "initvpmfflipssam":
            out.append("\t' PAD: no SAM fast-flip class; core.vbs flips on GameOnSolenoid (UseSolenoids 2)")
            seen.add("fflips")
            continue
        if cur_sub == "table1_init" and low.startswith('if err then msgbox "you need the latest sam.vbs'):
            continue
        if cur_sub == "table1_init" and re.match(r"^vpmnudge\.tiltswitch\s*=", low):
            out.append("\tvpmNudge.TiltSwitch = swTilt\t' PAD: the Remastered TILT PENDULUM")
            out.append("\tPadSync\t' PAD: TROUGH 5 and 6 held from the start")
            seen.add("tilt")
            continue

        # ---- flipper callbacks on core.vbs's Consts
        mflip = re.match(r"^solcallback\((15|16)\)\s*=\s*(\"[^\"]*\")(.*)$", s, re.I)
        if mflip:
            const = "sLLFlipper" if mflip.group(1) == "15" else "sLRFlipper"
            out.append("SolCallback(%s) = %s%s\t' PAD: Remastered %s FLIPPER"
                       % (const, mflip.group(2), mflip.group(3),
                          "LEFT" if mflip.group(1) == "15" else "RIGHT"))
            seen.add("flip" + mflip.group(1))
            continue

        # ---- the LampTimer: the flashers' numbers call their subs
        if cur_sub == "lamptimer_timer" and re.match(
                r"^ii\s*=\s*chglamp\(cnt\s*,\s*0\)\s*:\s*pfinsertstate\(ii\)\s*=\s*chglamp\(cnt\s*,\s*1\)\s*/\s*255",
                low):
            out.append(line)
            out.append("\t\t\tIf PadFlash.Exists(CStr(ii)) Then PadFlashCall ii, PFInsertState(ii)"
                       "\t' PAD: a flasher (flash_subs)")
            seen.add("flash")
            continue

        # ---- the crossbow rests at home: the SAM ROM homed it at power-on, the
        #      Remastered game leaves it until a game starts (PAD-1560: it stood
        #      straight up between the flippers all through attract)
        if re.match(r"^dim cbdrop, cbrotz:\s*cbdrop = 0 : cbrotz = 55 \+ 125$", low):
            out.append("Dim CBDrop, CBrotZ: CBDrop = 0 : CBRotZ = 125\t' PAD: at home (was 55 + 125, "
                       "straight out, homed by the SAM ROM at power-on)")
            seen.add("cbhome")
            continue
        # ---- the Remastered game stops and restarts the motor mid-sweep: a
        #      real motor carries on, so only a crossbow at home starts out
        if cur_sub == "dazz_motor" and re.match(r"^cbdir = 1 : darryl\.enabled = 1$", low):
            out.append("\t\tIf CBRotZ <= 125.5 Then cbdir = 1\t' PAD: a restart carries on the sweep")
            out.append("\t\tDarryl.enabled = 1")
            seen.add("cbmotor")
            continue
        # ---- ... and the motor still on at home sweeps out again
        if cur_sub == "darryl_timer" and low == "me.enabled = 0":
            out.append("\t\t\tcbdir = 1\t' PAD: the motor is still on: it sweeps on (the table stopped it at home)")
            seen.add("cbsweep")
            continue

        # ---- the crossbow sweep steps the Remastered encoder
        if low.startswith("sub darryl_timer"):
            out.append(line)
            out.append("\tPadEncStep cbdir\t' PAD: the Remastered crossbow motor's encoder")
            seen.add("encoder")
            continue
        out.append(line)

    want = {"system", "gamename", "usesol", "modsol", "loadvpm", "fflips", "tilt", "flip15", "flip16",
            "flash", "encoder", "cbhome", "cbmotor", "cbsweep"}
    missing = want - seen
    if missing:
        raise SystemExit("the script is not the one this patcher knows: no %s" % ", ".join(sorted(missing)))
    text = "\n".join(out)
    text += "\n".join([""] + gen_pad_block(m, src) + [""])
    rep.append("SAM switch numbers kept: the controller reads them through switch_rewrite (%d)"
               % (len(m["switch_rewrite"]) - 1))
    rep.append("flashers through the LampTimer: %s"
               % ", ".join(v for k, v in sorted(m["flash_subs"].items()) if k != "_"))
    return text, rep


def gen_pad_block(m, src):
    """The flashers' table, the crossbow encoder, PadSync, the test timer and
    the exit the table did not have."""
    holds = m["switch_holds"]
    enc = m["crossbow_encoder"]["switches"]
    out = ["", "",
           "'---- PAD: the flashers (walking_dead_remastered_le.vpxmap.json `flash_subs`):",
           "'     the controller reports each flasher LED as a lamp number of its own (its",
           "'     level 0..255), and the LampTimer above hands it to the table's own",
           "'     SolModCallback sub as 0..1.",
           "Dim PadFlash : Set PadFlash = CreateObject(\"Scripting.Dictionary\")"]
    for k, sub in sorted(m["flash_subs"].items()):
        if k != "_":
            out.append("PadFlash.Add \"%s\", GetRef(\"%s\")" % (k, sub))
    out += ["Sub PadFlashCall(n, lvl)",
            "\tDim f : Set f = PadFlash(CStr(n))",
            "\tf lvl",
            "End Sub",
            "",
            "'---- PAD: the Remastered crossbow motor counts encoder edges; the table's",
            "'     sweep steps ENCODER 1 / 2 in quadrature, one edge a tick (cbdir 1 out,",
            "'     2 back, 3 the pause at the end).",
            "Dim PadEncPh : PadEncPh = 0",
            "Sub PadEncStep(d)",
            "\tIf d = 1 Then",
            "\t\tPadEncPh = (PadEncPh + 1) Mod 4",
            "\tElseIf d = 2 Then",
            "\t\tPadEncPh = (PadEncPh + 3) Mod 4",
            "\tElse",
            "\t\tExit Sub",
            "\tEnd If",
            "\tController.Switch(%d) = (PadEncPh = 1 Or PadEncPh = 2)" % enc[0],
            "\tController.Switch(%d) = (PadEncPh >= 2)" % enc[1],
            "End Sub",
            "",
            "'---- PAD: TROUGH 5 and 6 are two balls the table does not have: the",
            "'     Remastered game is a six-ball game and the table's trough holds four, so",
            "'     the game counts the table's four plus two (Metallica's PAD-811). The",
            "'     table's trough and drop targets are re-sent every two seconds.",
            "Sub PadSync",
            "\tDim i"]
    for sid in holds["always"]:
        out.append("\tController.Switch(%d) = 1" % (1000 + sid))
    for n in (21, 20, 19, 18):
        out.append("\tController.Switch(%d) = (sw%d.BallCntOver > 0)" % (n, n))
    out.append("\tController.Switch(50) = (CBRotZ <= 127)\t' PAD: CROSSBOW HOME, from the start")
    out.append("\tController.Switch(51) = (CBRotZ >= 160)\t' PAD: CROSSBOW MARK")
    out += ["End Sub",
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
            "\t\t\tIf parts(0) = \"down\" Then Table1_KeyDown CInt(parts(1))",
            "\t\t\tIf parts(0) = \"up\" Then Table1_KeyUp CInt(parts(1))",
            "\t\tEnd If",
            "\tLoop",
            "\tf.Close",
            "\tfso.DeleteFile p",
            "End Sub",
            "Dim PadSyncTick : PadSyncTick = 0"]
    if not re.search(r"(?im)^\s*sub\s+table1_exit\b", src):
        out += ["", "Sub Table1_Exit\t' PAD: the run and the backglass go with the table",
                "\tController.Stop : PadStopB2S", "End Sub"]
    return out


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
    script, streams = vpxsounds.quiet(script, table.ole, rep)   # PAD-858
    items = retrofit_items(table, m)
    table.ole.close()
    out_name = m.get("output") or os.path.splitext(os.path.basename(src))[0] + " (PAD).vpx"
    dst = os.path.join(outdir, out_name)
    mac = vpxfile.write_patched(src, dst, script=script, new_items=items, streams=streams)
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
