#!/usr/bin/env python3
"""patch_beatles.py - "The Beatles" (Original 2018) v007, rewired from Stern's
1980 Seawitch ROM (seawitfp) to the Spike 2 emulator running Stern's Beatles.

    python patch_beatles.py "<The Beatles_007.vpx>" <out dir>

Writes `<out dir>/The Beatles_007 (PAD).vpx` beside a copy of PADSPIKE2.vbs,
which the table loads from its own folder, and the patched script as
`The Beatles_007 (PAD).script.vbs`. The table is re-signed
(vpxfile.write_patched) so Visual Pinball loads it.

The body is Stern's Beatles (itself a Seawitch playfield: three drop banks,
four pop targets, two spinners, the record and the top magnet); the brain was
Seawitch's, with the tribute's own rules on top of it. WHAT CHANGES, all of it
driven by beatles.vpxmap.json:

  script   controller.vbs + stern.vbs -> PADSPIKE2.vbs (PAD.Controller), the
           cabinet switches set to beatles' ids (the upper flippers' buttons
           close with the lower ones, as on the machine);
           every switch edge -> its Spike 2 id + 1000; the tribute's own
           targets and triggers that sent nothing (the orbit targets, the
           mystery and super jackpot targets, the skill shot star, the
           shooter lane, the orbit optos) send theirs (`switch_subs`);
           the solenoid block -> the Spike 2 coils; the upper flippers on
           their own coils; the auto plunger fires the plunger;
           the trough -> a cvpmBallStack on TROUGH 1..6 + JAM with the four
           balls the game counts (PAD-933: six made it serve three);
           the top magnet follows MAGNET-TOP, a new record magnet
           MAGNET-RECORD (a pull, not a grab: PAD-950), the record turns
           on its motor's outputs and spins up while the magnet holds the
           ball, so it throws it (PAD-965);
           UpdateLamps is regenerated: every insert on its Stern LED, the
           flasher domes and spinner flashes on theirs;
           the tribute's own rules (modes, ball save, the lock and its balls,
           mystery, skill shots, the extra points it scored through the star
           rollover) are emptied (`quiet_subs`), and PinUP Player is off:
           the real game scores, and its LCD is the display.
  objects  the JACKPOT insert (cloned from l52), the record magnet's trigger
           (cloned from TurnTable) and PadTestTimer.

Everything else - art, physics, sounds kept for the playfield, animations -
is the author's.
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
import vpxshadow  # noqa: E402
import vpxsounds  # noqa: E402

MAP = os.path.join(HERE, "beatles.vpxmap.json")
LAMP_ARRAY = 3000          # lamp numbers run to 1000 + 9 * 100 + 63

SUB_RE = re.compile(r"^(?:public\s+|private\s+)?sub\s+([A-Za-z0-9_]+)\s*(\([^)]*\))?", re.I)
SW_RE = re.compile(r"(PulseSw\s*\(?\s*|Controller\.Switch\s*\(\s*)(\d+)(\s*\)?)", re.I)
DROP_RE = re.compile(r"^(\s*dt\w*\.InitDrop\s+Array\([^)]*\)\s*,\s*Array\()([^)]*)(\).*)$", re.I)
FLIP_RE = re.compile(r":\s*(LeftFlipper1|RightFlipper1)\.RotateTo(End|Start)", re.I)


def lamp_num(leds):
    node, idx = leds[0]
    return 1000 + node * 100 + idx


def entries(section):
    return {k: v for k, v in section.items() if not k.startswith("_")}


def gen_sol_callbacks(m):
    out = ["'---- PAD: Spike 2 coils, numbered as beatles.vpxmap.json `solenoids` says"]
    consts = {"SolRFlipper": "sLRFlipper", "SolLFlipper": "sLLFlipper",
              "SolULFlipper": "sULFlipper", "SolURFlipper": "sURFlipper"}
    for num, s in entries(m["solenoids"]).items():
        if s.get("callback"):
            out.append("SolCallback(%s) = \"%s\"          ' %s"
                       % (consts.get(s["callback"], num), s["callback"], s["name"]))
    return out


def sol_for_magnet(m, magnet):
    for num, s in entries(m["solenoids"]).items():
        if s.get("magnet") == magnet:
            return int(num)
    raise KeyError(magnet)


def gen_update_lamps(m):
    """NFadeL per insert; lights sharing a number are NFadeLm and come FIRST
    (NFadeL steps the fading state, NFadeLm only reads it). A lamp call gets
    (arg, 0|1) on each change of its LED."""
    by_num = {}
    for light, v in entries(m["lamps"]).items():
        by_num.setdefault(lamp_num(v["leds"]), []).append((light, v["name"]))
    for light, v in m["retrofit_lights"]["lights"].items():
        by_num.setdefault(lamp_num(v["leds"]), []).append((light, v["name"]))
    out = ["\t'---- PAD: every insert on its Spike 2 LED (1000 + node * 100 + index)"]
    for num, lights in by_num.items():
        for light, name in lights[1:]:
            out.append("\tNFadeLm %d, %s    ' %s" % (num, light, name))
        light, name = lights[0]
        out.append("\tNFadeL %d, %s    ' %s" % (num, light, name))
    out.append("\t'---- what the table shows with something other than a Light")
    for name, v in entries(m["lamp_calls"]).items():
        n = lamp_num(v["leds"])
        out += ["\tSelect Case FadingLevel(%d)    ' %s" % (n, v["name"]),
                "\t\tCase 4 : %s %s, 0 : FadingLevel(%d) = 0" % (v["call"], v["arg"], n),
                "\t\tCase 5 : %s %s, 1 : FadingLevel(%d) = 1" % (v["call"], v["arg"], n),
                "\tEnd Select"]
    return out


def cabinet_lines(m):
    c = m["cabinet"]
    return [
        "' ---- PAD: beatles' cabinet (switch_list.txt ids + 1000); PADSPIKE2.vbs",
        "' ---- carries godzilla_le's, so the ones that differ are set here",
        "swStartButton = %d : swTilt = %d : swSlamTilt = %d" % (c["start"], c["tilt"], c["slam"]),
        "swLaunch = 0   ' no Action button: the plunger is the player's",
        "swLLFlip = %d : swLRFlip = %d : swULFlip = %d : swURFlip = %d"
        % (c["left_flipper"], c["right_flipper"], c["up_left_flipper"], c["up_right_flipper"]),
        "swCoin1 = %d : swCoin2 = %d : swCoin3 = %d" % (c["coin1"], c["coin2"], c["coin3"]),
    ]


def switch_sub(name, args, v, body):
    """A switch object's sub as the map's `switch_subs` says: a pulse or a
    held switch, the original body after it when `keep`."""
    sid = 1000 + v.get("pulse", v.get("hold", 0))
    edge = ("vpmTimer.PulseSw %d" % sid) if "pulse" in v else ("Controller.Switch(%d) = 1" % sid)
    out = ["Sub %s%s" % (name, args or ""), "\t%s    ' %s" % (edge, v["name"])]
    if v.get("keep"):
        out += body
    out.append("End Sub")
    return out


def patch_script(src, m):
    """The table script, rewired. Returns (text, report lines)."""
    rep = []
    lines = src.replace("\r\n", "\n").split("\n")
    rewrite = {int(k): int(v) for k, v in entries(m["switch_rewrite"]).items()}
    by_obj = {k.lower(): int(v) for k, v in entries(m["switch_by_object"]).items()}
    subs_by = {k.lower(): (k, v) for k, v in entries(m["switch_subs"]).items()}
    quiet = {s.lower() for s in m["quiet_subs"]["subs"]}
    pup_class = vpxshadow.pup_stub(lines, rep)
    out = []
    cur = None          # the sub being walked: its lowered name
    mode = None         # None | "quiet" | "replace" | "lamps"
    held = []           # a replaced sub's original body (for `keep`)
    seen_subs = set()
    sol_done = False
    dropped = 0
    quieted = replaced = 0

    def rw(mm):
        nonlocal dropped
        n = int(mm.group(2))
        if n >= 1000:
            return mm.group(0)
        sid = by_obj.get(cur, rewrite.get(n, 0))
        if sid == 0:
            dropped += 1
        return "%s%d%s" % (mm.group(1), 1000 + sid if sid else 0, mm.group(3))

    for raw in lines:
        line = raw.rstrip("\r")
        s = line.strip()
        low = s.lower()
        msub = SUB_RE.match(s)
        one_line = bool(msub) and re.search(r":\s*end\s+sub\s*$", low) is not None
        is_end = low == "end sub" or low.startswith("end sub ") or low.startswith("end sub'")

        # ---- inside a sub being emptied or replaced: its End Sub closes it
        if mode in ("quiet", "replace", "lamps"):
            if is_end:
                if mode == "quiet":
                    out.append("End Sub")
                elif mode == "replace":
                    out.extend(held if subs_by[cur][1].get("keep") else [])
                    out.append("End Sub")
                else:
                    out.extend(gen_update_lamps(m))
                    out.append(line)
                mode, cur, held = None, None, []
            elif mode == "replace":
                held.append(line)
            continue

        if msub:
            cur = msub.group(1).lower()
            args = msub.group(2) or ""
            seen_subs.add(cur)
            if cur in quiet:
                quieted += 1
                out.append("Sub %s%s    ' PAD: the tribute's own rules; the game's now" % (msub.group(1), args))
                if one_line:
                    out.append("End Sub")
                    cur = None
                else:
                    mode = "quiet"
                continue
            if cur in subs_by:
                replaced += 1
                k, v = subs_by[cur]
                out.extend(switch_sub(msub.group(1), args, v, [])[:-1])
                if one_line:
                    out.append("End Sub")
                    cur = None
                else:
                    mode = "replace"
                continue
            if cur == "updatelamps":
                out.append(line)
                mode = "lamps"
                continue
        if is_end:
            cur = None

        # ---- the header: our system script, our title
        if low.startswith('executeglobal gettextfile("controller.vbs")'):
            out.append('ExecuteGlobal GetTextFile("PADSPIKE2.vbs")')
            continue
        if low.startswith("if err then msgbox \"you need the controller.vbs"):
            out.append('If Err Then MsgBox "You need PADSPIKE2.vbs beside this table (tools\\spike2_emu\\vpx)"')
            continue
        if low.startswith("const cgamename="):
            out.append('Const cGameName="%s",UseSolenoids=2,UseLamps=0,UseGI=0,'
                       'SSolenoidOn="SolOn",SSolenoidOff="SolOff",SCoin="coin"' % m["title"])
            rom = re.search(r'cgamename\s*=\s*"([^"]*)"', low)
            if rom:   # the backglass (B2S, DOF) knows the table by its ROM
                out.append('PadB2SName = "%s"' % rom.group(1))
            out.append("Dim mRecordMagnet, padMotor(1)")
            continue
        if low.startswith("loadvpm "):
            out.append('LoadVPM "01000000","PADSPIKE2.vbs",3.10')
            out.extend(cabinet_lines(m))
            continue
        if re.match(r"^sub\s+table1?_exit\b", low) and "controller.stop" in low:
            out.append(re.sub(r"(?i)\bController\.Stop\b", "Controller.Stop : PadStopB2S", line, count=1))
            continue

        # ---- solenoid callbacks: Seawitch's go, ours come (once)
        if re.match(r"^solcallback\s*\(", low):
            if not sol_done:
                sol_done = True
                out.extend(gen_sol_callbacks(m))
            continue

        # ---- the upper flippers flip on their own coils
        if cur in ("sollflipper", "solrflipper"):
            line = FLIP_RE.sub("", line)

        # ---- lamp arrays big enough for the Stern numbers
        if low.startswith("dim ") and "(200)" in low and ("lampstate" in low or "flash" in low):
            out.append(line.replace("(200)", "(%d)" % LAMP_ARRAY))
            continue
        if re.match(r"^for x = 0 to 200$", low):
            out.append(line.replace("200", str(LAMP_ARRAY)))
            continue

        # ---- the trough: the game's own ball count on the machine's switches
        if low.startswith("bstrough.initnotrough"):
            t = m["switch_holds"]["trough"]
            lead = line[:len(line) - len(line.lstrip())]
            out += [lead + "bsTrough.InitSw 0,%s" % ",".join("1%03d" % x for x in t),
                    lead + "bsTrough.InitKick ballrelease, 90, 4",
                    lead + "bsTrough.Balls = %d" % m["switch_holds"]["balls"],
                    lead + "superjlock.IsDropped = True   ' the tribute's lock post: no lock on the machine"]
            continue
        if low.startswith("vpmnudge.tiltswitch"):
            out.append(re.sub(r"=\s*\d+", "= %d" % m["cabinet"]["tilt"], line))
            continue

        # ---- PinUP Player off: the game's LCD is the display
        if re.match(r"^dim\s+haspup\s*:\s*haspup\s*=\s*true", low):
            out.append("Dim HasPup:HasPuP = False   ' PAD: the game's own LCD is the display")
            continue
        if low == "dim puplayer":
            out.append(line)
            out.append("Set PuPlayer = New PadNoPuP")
            continue

        # ---- the keys: Stern's upper flippers share the lower ones' buttons
        if re.match(r"^sub\s+table1_key(down|up)\b", low):
            out.append(line)
            on = "True" if "keydown" in low else "False"
            c = m["cabinet"]
            out.append("\tIf KeyCode = LeftFlipperKey Then Controller.Switch(%d) = %s : vpmFlips.FlipUL %s"
                       % (c["up_left_flipper"], on, on))
            out.append("\tIf KeyCode = RightFlipperKey Then Controller.Switch(%d) = %s : vpmFlips.FlipUR %s"
                       % (c["up_right_flipper"], on, on))
            continue

        # ---- switch numbers
        mo = DROP_RE.match(line)
        if mo:
            nums = []
            for n in mo.group(2).split(","):
                sid = rewrite.get(int(n), 0)
                nums.append(str(1000 + sid) if sid else "0")
            line = mo.group(1) + ", ".join(nums) + mo.group(3)
        else:
            line = SW_RE.sub(rw, line)
        out.append(line)

    # ---- held switches whose release the table never sent
    tail = ["", "", "'" + "=" * 70, "'==== PAD: the Spike 2 emulator drives this table (patch_beatles.py)",
            "'" + "=" * 70]
    for k, v in entries(m["switch_subs"]).items():
        if "hold" in v:
            un = re.sub(r"(?i)_hit$", "_UnHit", k)
            if un.lower() not in seen_subs:
                tail.append("Sub %s : Controller.Switch(%d) = 0 : End Sub" % (un, 1000 + v["hold"]))
    t = m["solenoids"]
    rec = t[str(sol_for_magnet(m, "mRecordMagnet"))]
    tail += [
        "",
        "Sub SolULFlipper(Enabled)",
        "\tIf Enabled Then",
        "\t\tLeftFlipper1.RotateToEnd",
        "\tElse",
        "\t\tLeftFlipper1.RotateToStart",
        "\tEnd If",
        "End Sub",
        "Sub SolURFlipper(Enabled)",
        "\tIf Enabled Then",
        "\t\tRightFlipper1.RotateToEnd",
        "\tElse",
        "\t\tRightFlipper1.RotateToStart",
        "\tEnd If",
        "End Sub",
        "",
        "Sub PadAutoPlunger(Enabled)   ' AUTO PLUNGER: the plunger fires itself",
        "\tIf Enabled Then",
        "\t\tPlunger.AutoPlunger = True : Plunger.Pullback : Plunger.Fire",
        "\t\tPlaySound SoundFX(\"plunger\",DOFContactors)",
        "\t\tPlunger.AutoPlunger = False",
        "\tEnd If",
        "End Sub",
        "",
        "' the magnets: the top one on MAGNET-TOP, the record's on MAGNET-RECORD;",
        "' the record's pulls without grabbing (the game only pulses it)",
        "MagnetW2.Solenoid = %d" % sol_for_magnet(m, "MagnetW2"),
        "Set mRecordMagnet = New cvpmMagnet",
        "With mRecordMagnet",
        "\t.InitMagnet PadRecordMagnet, %d" % rec["strength"],
        "\t.GrabCenter = %s" % ("True" if rec["grab"] else "False"),
        "\t.Solenoid = %d" % sol_for_magnet(m, "mRecordMagnet"),
        "\t.CreateEvents \"mRecordMagnet\"",
        "End With",
        "",
        "' the record turns on its motor's two outputs (MOTOR A0 / A1 DRIVER), and",
        "' gets to speed while the magnet still holds the ball (PAD-965)",
        "spinner.SpinUp = %d" % m["lamp_calls"]["RecordMotorA0"]["spin_up"],
        "Sub PadRecordMotor(n, v)",
        "\tpadMotor(n) = v",
        "\tspinner.SpinCW = (padMotor(1) = 0)",
        "\tspinner.MotorOn = ((padMotor(0) + padMotor(1)) = 1)",
        "End Sub",
        "",
        "' a flasher dome's LED: one flash of the dome as it lights",
        "Sub PadDome(n, v)",
        "\tIf v = 0 Then Exit Sub",
        "\tSelect Case n",
    ]
    for d in sorted({v["arg"] for v in entries(m["lamp_calls"]).values() if v["call"] == "PadDome"}):
        tail.append("\t\tCase %d : FlashLevel%d = 1 : Flasherflash%d_Timer" % (d, d, d))
    tail += [
        "\tEnd Select",
        "End Sub",
        "Sub PadShow(obj, v) : obj.Visible = (v = 1) : End Sub",
        "",
        "'---- PAD: scripted keys for a test run (vpxkeys.py): this timer reads",
        "'---- %TEMP%\\padvpx_keys.txt (one `down <code>` / `up <code>` per line,",
        "'---- DirectInput codes) and feeds the table's own key handlers.",
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
    ]
    tail += pup_class.split("\n") if isinstance(pup_class, str) else pup_class
    rep.append("switch edges dropped (no Stern switch): %d" % dropped)
    rep.append("the tribute's own subs emptied: %d; switch subs rewritten: %d" % (quieted, replaced))
    missing = [s for s in quiet | set(subs_by) if s not in seen_subs]
    if missing:
        rep.append("WARNING: the map names subs the script has none of: %s" % ", ".join(sorted(missing)))
    return "\n".join(out + tail) + "\n", rep


def retrofit_items(table, m):
    """New GameItem streams: the lights, the record magnet's trigger, the timer."""
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
    for name, v in entries(m["retrofit_triggers"]).items():
        kind, src = by_name[v["clone"]]
        assert kind == "Trigger", v["clone"]
        item = vpxfile.clone_item(src, name, *v["at"])
        if v.get("radius"):
            item = vpxfile.set_fields(item, {"RADI": struct.pack("<f", float(v["radius"]))})
        items.append(item)
    for name, v in entries(m["retrofit_timers"]).items():
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
    script, streams = vpxsounds.quiet(script, table.ole, rep)   # PAD-858
    items = retrofit_items(table, m)
    table.ole.close()
    out_name = m["output"]
    dst = os.path.join(outdir, out_name)
    mac = vpxfile.write_patched(src, dst, script=script, new_items=items, streams=streams)
    shutil.copyfile(os.path.join(HERE, "PADSPIKE2.vbs"), os.path.join(outdir, "PADSPIKE2.vbs"))
    open(os.path.join(outdir, out_name[:-4] + ".script.vbs"), "w", encoding="utf-8",
         newline="").write(script)
    ok = vpxfile.VpxTable(dst).verify()
    print("wrote %s\n  MAC %s  verify %s\n  +%d items" % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(items)))
    for r in rep:
        print("  " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
