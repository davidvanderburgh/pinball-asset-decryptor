#!/usr/bin/env python3
"""patch_godzilla.py - marty02's "Godzilla Limited Edition" v2.6, rewired from
Sega's 1998 ROM to the Spike 2 emulator.

    python patch_godzilla.py "<Godzilla limited edition.vpx>" <out dir>

Writes `<out dir>/Godzilla limited edition (PAD).vpx` beside a copy of
PADSPIKE2.vbs, which the table loads from its own folder. The table is
re-signed (vpxfile.write_patched) so Visual Pinball loads it.

WHAT CHANGES, all of it driven by godzilla_le.vpxmap.json:

  script   controller.vbs + SEGA.VBS -> PADSPIKE2.vbs (PAD.Controller);
           every switch number -> its Spike 2 id + 1000 (or dropped);
           solenoid callbacks -> the Spike 2 coils; the trough grows to the
           machine's six balls on TROUGH 1..6 + JAM; the right scoop becomes
           a saucer the RIGHT SCOOP coil empties; Godzilla's magnet follows
           the GODZILLA MAGNET coil, a new Mechagodzilla magnet the other;
           UpdateLamps is regenerated: every table insert on its Stern LED.
  objects  one Light per Stern insert the table had none for (cloned from
           L21, placed where the Stern drawing puts it) and one Trigger for
           the Mechagodzilla magnet (cloned from BottomMagnet).

Everything else - art, physics, ramps, the bridge, sounds - is marty02's.
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

MAP = os.path.join(HERE, "godzilla_le.vpxmap.json")
OUT_NAME = "Godzilla limited edition (PAD).vpx"

LAMP_ARRAY = 3000          # lamp numbers run to 1000 + 15 * 100 + 95


def lamp_num(leds):
    node, idx = leds[0]
    return 1000 + node * 100 + idx


def patch_script(src, m):
    """The table script, rewired. Returns (text, report lines)."""
    rep = []
    lines = src.split("\n")
    out = []
    rewrite = {int(k): int(v) for k, v in m["switch_rewrite"].items() if k != "_"}
    by_obj = {k: int(v) for k, v in m["switch_by_object"].items() if k != "_"}
    cur_sub = None
    sw_re = re.compile(r"(PulseSw\s*\(?\s*|Controller\.Switch\s*\(\s*)(\d+)(\s*\)?)", re.I)
    dropped = 0
    in_update_lamps = False
    in_sol_block = False

    for raw in lines:
        line = raw.rstrip("\r")
        s = line.strip()
        low = s.lower()
        is_end = (low == "end sub")

        # ---- subs being dropped or replaced whole (checked before the
        # sub-tracking below, so their End Sub goes with them)
        if cur_sub == "drop":
            if is_end:
                cur_sub = None
            continue
        if cur_sub == "K9_Hit_replaced":
            if is_end:
                out.append(line)
                cur_sub = None
            continue

        msub = re.match(r"^(?:public |private )?sub\s+([A-Za-z0-9_]+)", s, re.I)
        if msub:
            cur_sub = msub.group(1)
        if is_end:
            if in_update_lamps:
                out.extend(gen_update_lamps(m))
                in_update_lamps = False
            cur_sub = None

        # ---- the header: our system script, our title
        if low.startswith('executeglobal gettextfile("controller.vbs")'):
            out.append('ExecuteGlobal GetTextFile("PADSPIKE2.vbs")')
            continue
        if low.startswith("if err then msgbox \"you need the controller.vbs"):
            out.append('If Err Then MsgBox "You need PADSPIKE2.vbs beside this table (tools\\spike2_emu\\vpx)"')
            continue
        if low.startswith("const cgamename="):
            out.append('Const cGameName="godzilla_le",UseSolenoids=2,UseLamps=0,UseGI=0, SCoin="coin"')
            rom = re.search(r'cgamename\s*=\s*"([^"]*)"', low)
            if rom:   # the backglass (B2S, DOF) knows the table by its ROM
                out.append('PadB2SName = "%s"' % rom.group(1))
            out.append("Dim mMechaMagnet, bsScoop")
            continue
        if re.match(r"^sub\s+table1?_exit\b", low) and "controller.stop" in low:
            # the backglass PADSPIKE2.vbs started goes with the table (PAD-852)
            out.append(re.sub(r"(?i)\bController\.Stop\b", "Controller.Stop : PadStopB2S", line, count=1))
            continue
        if low.startswith("loadvpm "):
            out.append('LoadVPM "01000000","PADSPIKE2.vbs",3.10')
            continue

        # ---- solenoid callbacks: the Sega block goes, ours comes (once: the
        # original block has a blank line in it)
        if re.match(r"^solcallback\s*\(", low):
            if not in_sol_block:
                in_sol_block = True
                out.extend(gen_sol_callbacks(m))
            continue

        # ---- UpdateLamps is regenerated whole
        if re.match(r"^sub\s+updatelamps\b", low):
            out.append(line)
            in_update_lamps = True
            continue
        if in_update_lamps:
            continue
        if low.startswith("dim ") and "(200)" in low and ("lampstate" in low or "flash" in low):
            # LampState/FadingLevel AND the five Flash* arrays beside them:
            # InitLamps walks every one of them to the same bound
            out.append(line.replace("(200)", "(%d)" % LAMP_ARRAY))
            continue
        if re.match(r"^for x = 0 to 200$", low):
            out.append(line.replace("200", str(LAMP_ARRAY)))
            continue

        # ---- the trough: six balls on the machine's own switches
        if low.startswith("bstrough.initsw"):
            t = m["switch_holds"]["trough"]
            out.append("\t\tbsTrough.InitSw 0,%s" % ",".join("1%03d" % x for x in t))
            continue
        if low.startswith("bstrough.balls"):
            out.append("\t\tbsTrough.Balls = 6")
            continue
        if re.match(r"^kicker[123]\.(createball|kick)", low):
            continue                       # Sega's three captive balls

        # ---- magnets: Sega's four never energise, Godzilla's follows its coil
        if re.match(r"^m(top|middle|bottom|orbit)magnet\.solenoid\s*=", low):
            out.append(re.sub(r"=\s*\d+", "= 0", line))
            continue
        if low.startswith(".initmagnet magna2"):
            out.append(line)
            out.append("\t.Solenoid = %d   ' GODZILLA MAGNET, node 9 coil 6" % sol_for_magnet(m, "mMagnaSave2"))
            continue
        if cur_sub and cur_sub.lower() == "tr12_hit" and ("magnet" in low) and not low.startswith("playsound"):
            continue                       # the Sega game's own magnet timer
        if cur_sub and cur_sub.lower() == "magnettimer002_timer" and "magneton" in low:
            continue

        # ---- the right scoop: a saucer the RIGHT SCOOP coil empties
        if re.match(r"^sub\s+k9_hit", low):
            out.append("Sub K9_Hit")
            out.append("\tbsScoop.AddBall Me        ' RIGHT SCOOP switch held until the coil kicks")
            out.append("\tPlaySound \"combo\"")
            cur_sub = "K9_Hit_replaced"
            continue
        if re.match(r"^sub\s+timer0(09|10)_timer", low):
            cur_sub = "drop"
            continue

        # ---- flippers: the upper left one on its own coil
        if cur_sub and cur_sub.lower() == "sollflipper" and "leftflipperh" in low:
            continue
        if cur_sub and cur_sub.lower() == "solrelease" and "pulsesw" in low:
            continue                       # the trough switches say it

        # ---- switch numbers
        if cur_sub in by_obj:
            line2 = sw_re.sub(lambda mm: "%s%d%s" % (mm.group(1), 1000 + by_obj[cur_sub], mm.group(3)), line)
            if line2 != line:
                rep.append("%s: -> %d" % (cur_sub, 1000 + by_obj[cur_sub]))
            line = line2
        else:
            def _rw(mm):
                nonlocal dropped
                n = int(mm.group(2))
                if n >= 1000:
                    return mm.group(0)
                sid = rewrite.get(n, 0)
                if sid == 0:
                    dropped += 1
                    return "%s%d%s" % (mm.group(1), 0, mm.group(3))
                return "%s%d%s" % (mm.group(1), 1000 + sid, mm.group(3))
            line = sw_re.sub(_rw, line)

        out.append(line)

        # ---- extra edges, appended inside the sub they belong to
        if cur_sub and cur_sub.lower() == "k5_hit" and low.startswith("k6.kick"):
            out.append("\tvpmTimer.AddTimer 1200, \"vpmTimer.PulseSw 1075 '\"   ' BUILDING EXIT opto")
        if cur_sub and cur_sub.lower() == "tflash_hit" and low.startswith("flashforms f7"):
            out.append("\tvpmTimer.PulseSw 1074   ' BIG LOOP EXIT")
        if cur_sub and cur_sub.lower() == "k2_hit" and low.startswith("k3.kick"):
            out.append("\tvpmTimer.PulseSw 1081   ' R RAMP MADE OPTO")

        # ---- init additions
        if low.startswith("bstrough.initexitsnd"):
            out.append("")
            out.append("\tSet bsScoop = New cvpmBallStack")
            out.append("\t\tbsScoop.InitSaucer K9, 1053, 165, 7     ' RIGHT SCOOP switch; the coil kicks it out")
            out.append("\t\tbsScoop.InitExitSnd SoundFX(\"kicker\",DOFContactors), SoundFX(\"Solenoid\",DOFContactors)")
            out.append("")
            out.append("\tSet mMechaMagnet = New cvpmMagnet")
            out.append("\t\tmMechaMagnet.InitMagnet MechaMagnet, 60")
            out.append("\t\tmMechaMagnet.Solenoid = %d            ' MECHAGODZILLA MAGNET, node 9 coil 7"
                       % sol_for_magnet(m, "mMechaMagnet"))
            out.append("\t\tmMechaMagnet.GrabCenter = True")
            out.append("\t\tmMechaMagnet.CreateEvents \"mMechaMagnet\"")

    text = "\n".join(out)
    text += "\n".join([
        "", "",
        "'---- PAD: scripted keys for a test run. Visual Pinball polls its keyboard",
        "'---- itself, so a test cannot hand it a key from outside; this timer reads",
        "'---- %TEMP%\\padvpx_keys.txt (one `down <code>` / `up <code>` per line,",
        "'---- DirectInput codes: 2 = Start, 42 = left flipper, 54 = right, 28 = launch)",
        "'---- and feeds the table's own key handlers, then deletes the file.",
        "Sub PadTestTimer_Timer",
        "\tOn Error Resume Next",
        "\tDim fso, p, f, parts",
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
        "",
        "'---- PAD: edges the Sega script never sent ----",
        "Sub Gate4_Hit : vpmTimer.PulseSw 1051 : End Sub          ' MECHA EXIT BOTTOM",
        "Sub SolULFlipper(Enabled)",
        "\tIf Enabled Then",
        "\t\tPlaySound SoundFX(\"fx_Flipperup\",DOFContactors):LeftFlipperH.RotateToEnd",
        "\tElse",
        "\t\tPlaySound SoundFX(\"fx_Flipperdown\",DOFContactors):LeftFlipperH.RotateToStart",
        "\tEnd If",
        "End Sub",
        ""])
    rep.append("switch edges dropped (no Stern switch): %d" % dropped)
    return text, rep


def sol_for_magnet(m, magnet):
    for num, s in m["solenoids"].items():
        if num != "_" and s.get("magnet") == magnet:
            return int(num)
    raise KeyError(magnet)


def gen_sol_callbacks(m):
    out = ["'---- PAD: Spike 2 coils, numbered as godzilla_le.vpxmap.json `solenoids` says"]
    for num, s in m["solenoids"].items():
        if num == "_" or not s.get("callback"):
            continue
        name = s["callback"]
        if name in ("SolRFlipper", "SolLFlipper", "SolULFlipper"):
            const = {"SolRFlipper": "sLRFlipper", "SolLFlipper": "sLLFlipper",
                     "SolULFlipper": "sULFlipper"}[name]
            out.append("SolCallback(%s) = \"%s\"          ' %s" % (const, name, s["name"]))
        else:
            out.append("SolCallback(%s) = \"%s\"          ' %s" % (num, name, s["name"]))
    return out


def gen_update_lamps(m):
    out = [" '---- PAD: every insert on its Spike 2 LED (1000 + node * 100 + index)"]
    for light, v in m["lamps"].items():
        if light == "_":
            continue
        out.append(" NFadeL %d, %s    ' %s" % (lamp_num(v["leds"]), light, v["name"]))
    out.append(" '---- retrofit inserts the table had no light for")
    for light, v in m["retrofit_lights"]["lights"].items():
        out.append(" NFadeL %d, %s" % (lamp_num(v["leds"]), light))
    return out


def retrofit_items(table, m):
    """New GameItem streams: lights cloned from the map's `clone` light,
    the magnet trigger cloned from its `clone` trigger."""
    by_name = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        by_name[name] = (kind, data)
    items = []
    rl = m["retrofit_lights"]
    kind, src = by_name[rl["clone"]]
    assert kind == "Light", rl["clone"]
    for name, v in rl["lights"].items():
        items.append(vpxfile.clone_item(src, name, *v["at"]))
    for name, v in m["retrofit_triggers"].items():
        if name == "_":
            continue
        kind, src = by_name[v["clone"]]
        assert kind == "Trigger", v["clone"]
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
    dst = os.path.join(outdir, OUT_NAME)
    mac = vpxfile.write_patched(src, dst, script=script, new_items=items)
    shutil.copyfile(os.path.join(HERE, "PADSPIKE2.vbs"), os.path.join(outdir, "PADSPIKE2.vbs"))
    open(os.path.join(outdir, OUT_NAME[:-4] + ".script.vbs"), "w", encoding="utf-8",
         newline="").write(script)
    ok = vpxfile.VpxTable(dst).verify()
    print("wrote %s\n  MAC %s  verify %s\n  +%d items (%d lights, %d triggers)"
          % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(items),
             len(m["retrofit_lights"]["lights"]), len(m["retrofit_triggers"]) - 1))
    for r in rep:
        print("  " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
