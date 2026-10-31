#!/usr/bin/env python3
"""patch_turtles_le.py - Bigus / Cheese3075's "Teenage Mutant Ninja Turtles
(Stern-Data East mash-up)" v2.86d, rewired from Data East's 1991 tmnt_104 ROM
to the Spike 2 emulator running turtles_le (or turtles_pro: --map).

    python patch_turtles_le.py "<Teenage Mutant Ninja Turtles (Stern-Data East mash-up) v2.86d.vpx>" <out dir> [--map <x.vpxmap.json>]

turtles_pro.vpxmap.json is this map renumbered by name for the Pro card, the
one the table plays today: the LE card starts no game in the emulator
(PAD-811, rigbatch startcheck), so the Pro map is the preferred one and
writes "(PAD).vpx"; the LE map writes "... LE (PAD).vpx".

Writes `<out dir>/<original name> (PAD).vpx` beside a copy of PADSPIKE2.vbs,
which the table loads from its own folder, and the patched script as
`<original name> (PAD).script.vbs`. The table is re-signed
(vpxfile.write_patched) so Visual Pinball loads it.

The body is Stern's TMNT LE (the Party Wagon van with its lock, one right
spinner); the brain was Data East's. WHAT CHANGES, all of it driven by
turtles_le.vpxmap.json:

  script   controller.vbs + DE.VBS -> PADSPIKE2.vbs (PAD.Controller), the
           cabinet switches set to turtles_le's ids;
           every switch edge -> its Spike 2 id + 1000, by the object whose
           event sub sends it (Data East shared numbers between objects);
           the solenoid block -> the Spike 2 coils;
           the table's own kicker trough (three balls, outhole + ball
           release coils) -> a cvpmBallStack on TROUGH 1..6 + JAM with the
           machine's six balls, emptied by the TROUGH coil;
           the van kicker -> a two-ball stack on LOWER LOCK 1/2, emptied by
           the LOWER LOCK coil; KRANG shakes Krang;
           UpdateLamps' inserts -> their Stern LEDs (1000 + node * 100 +
           index), the flasher domes LampFlasher drives -> the Stern flash
           LEDs; GI follows the GI LEDs, the pizza turntable the SPIN DISC
           outputs; the lamp arrays grow to 3000;
           slingshots, the left ramp entry, the van entry and the right
           ramp exit send the edges the Data East script never did;
           Plunger key and Lockbar key hold the Action button (launch);
           the shooter lane's upper switch (UPPER SHOOTER LANE on the Pro,
           SKILL SHOT on the LE) on a trigger of its own: the game keeps the
           turtle select open until the launched ball crosses it (PAD-897).
  objects  START EPISODE's insert (cloned from l58a), PadUpperShooter (cloned
           from sw14) and PadTestTimer.

Everything else - art, physics, ramps, sounds, animations - is the authors'.
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

MAP = os.path.join(HERE, "turtles_le.vpxmap.json")
LAMP_ARRAY = 3000          # lamp numbers run to 1000 + 15 * 100 + 95


def lamp_num(leds):
    node, idx = leds[0]
    return 1000 + node * 100 + idx


def sw_holds(m, key):
    return [1000 + x for x in m["switch_holds"][key]]


def object_of(sub):
    """The table object a VPX event sub belongs to: `sw20a_unHit` -> sw20a."""
    return sub.rsplit("_", 1)[0] if "_" in sub else sub


def cabinet_lines(m):
    c = m["cabinet"]
    return [
        "' ---- PAD: turtles_le's cabinet (switch_list.txt ids + 1000); PADSPIKE2.vbs",
        "' ---- carries godzilla_le's, so the ones that differ are set here",
        "swStartButton = %d : swTilt = %d : swSlamTilt = %d" % (c["start"], c["tilt"], c["slam"]),
        "swLaunch = %d" % c["launch"],
        "swLLFlip = %d : swLRFlip = %d : swULFlip = %d"
        % (c["left_flipper"], c["right_flipper"], c["up_left_flipper"]),
        "swCoin1 = 1039 : swCoin2 = 1040 : swCoin3 = 1041",
        # the service buttons: PADSPIKE2.vbs's own (the controller finds each
        # in the title's switch table, PAD-882)
    ]


def gen_sol_callbacks(m):
    out = ["'---- PAD: Spike 2 coils, numbered as turtles_le.vpxmap.json `solenoids` says"]
    for num, s in m["solenoids"].items():
        if num == "_" or not s.get("callback"):
            continue
        name = s["callback"]
        const = {"SolRFlipper": "sLRFlipper", "SolLFlipper": "sLLFlipper"}.get(name, num)
        out.append("SolCallback(%s) = \"%s\"          ' %s" % (const, name, s["name"]))
    return out


def gen_lamp_lines(m):
    """NFadeL per insert; a light sharing its number with an earlier one is
    NFadeLm and comes FIRST (NFadeL steps the fading state, NFadeLm only reads it)."""
    by_num = {}
    for light, v in m["lamps"].items():
        if light == "_":
            continue
        by_num.setdefault(lamp_num(v["leds"]), []).append((light, v["name"]))
    for light, v in m["retrofit_lights"]["lights"].items():
        by_num.setdefault(lamp_num(v["leds"]), []).append((light, "retrofit"))
    out = ["\t'---- PAD: every insert on its Spike 2 LED (1000 + node * 100 + index)"]
    for num, lights in by_num.items():
        for light, name in lights[1:]:
            out.append("\tNFadeLm %d, %s    ' %s" % (num, light, name))
        light, name = lights[0]
        out.append("\tNFadeL %d, %s    ' %s" % (num, light, name))
    out.append("\tPadGiTick")
    out.append("\tPadDiscTick")
    return out


def trigger_subs(m):
    """A retrofit trigger with a `switch` holds that switch while a ball sits
    on it, as a rollover on the machine does."""
    out = []
    for name, v in m.get("retrofit_triggers", {}).items():
        if name.startswith("_") or not v.get("switch"):
            continue
        sid = 1000 + v["switch"]
        out += [
            "' %s: %s" % (name, v.get("why", "")),
            "Sub %s_Hit : Controller.Switch(%d) = 1 : End Sub" % (name, sid),
            "Sub %s_unHit : Controller.Switch(%d) = 0 : End Sub" % (name, sid),
            "",
        ]
    return out


def pad_subs(m):
    gi = " Or ".join("LampState(%d)" % lamp_num([l]) for l in m["gi_leds"]["leds"])
    cw = lamp_num([m["disc_leds"]["cw"]])
    ccw = lamp_num([m["disc_leds"]["ccw"]])
    van = sw_holds(m, "van")
    return [
        "",
        "'---- PAD: what the Spike 2 machine drives that Data East's ROM did not ----",
        "' GI: the machine's GI LEDs; SolGi(True) puts the table's GI OUT",
        "Sub PadGiTick",
        "\tDim lit",
        "\tlit = 0",
        "\tIf %s Then" % gi,
        "\t\tlit = 1",
        "\tEnd If",
        "\tIf lit <> padGiState Then",
        "\t\tpadGiState = lit",
        "\t\tSolGi (lit = 0)",
        "\tEnd If",
        "End Sub",
        "",
        "' the pizza disc: SPIN DISC CW (%d) / CCW (%d) are the motor's outputs" % (cw, ccw),
        "Sub PadDiscTick",
        "\tDim lit",
        "\tlit = 0",
        "\tIf LampState(%d) Or LampState(%d) Then" % (cw, ccw),
        "\t\tlit = 1",
        "\tEnd If",
        "\tIf lit <> padDiscOn Then",
        "\t\tpadDiscOn = lit",
        "\t\tttPizza.SpinCW = (LampState(%d) = 0)" % ccw,
        "\t\tSolPizzaSpin (lit = 1)",
        "\tEnd If",
        "End Sub",
        "",
        "' LOWER LOCK: the van gives back one ball (LOWER LOCK 1/2 = %d/%d)" % tuple(van),
        "Sub PadVanOut(Enabled)",
        "\tIf Enabled Then",
        "\t\tIf bsVan.Balls > 0 Then",
        "\t\t\tpizzavanshake",
        "\t\t\tpizzavan.blenddisablelighting = 0.1",
        "\t\tEnd If",
        "\t\tbsVan.ExitSol_On",
        "\tEnd If",
        "End Sub",
        "",
        "' KRANG: the coil that shakes Krang on the machine shakes the table's",
        "Sub PadKrang(Enabled)",
        "\tIf Enabled Then",
        "\t\tPikachuShake",
        "\tEnd If",
        "End Sub",
        "",
    ] + trigger_subs(m) + [
        "' at most as many shadows / rolling sounds as the table made objects for",
        "Function PadMin(a, b)",
        "\tIf a < b Then",
        "\t\tPadMin = a",
        "\tElse",
        "\t\tPadMin = b",
        "\tEnd If",
        "End Function",
        "",
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
        "\t\t\tIf parts(0) = \"down\" Then table1_KeyDown CInt(parts(1))",
        "\t\t\tIf parts(0) = \"up\" Then table1_KeyUp CInt(parts(1))",
        "\t\tEnd If",
        "\tLoop",
        "\tf.Close",
        "\tfso.DeleteFile p",
        "End Sub",
        "",
    ]


def patch_script(src, m):
    """The table script, rewired. Returns (text, report lines)."""
    rep = []
    out = []
    rewrite = {int(k): int(v) for k, v in m["switch_rewrite"].items() if not k.startswith("_")}
    by_obj = {k.lower(): int(v) for k, v in m["switch_by_object"].items() if not k.startswith("_")}
    extra = {k.lower(): int(v) for k, v in m["switch_extra"].items() if not k.startswith("_")}
    flash = {int(k): int(v) for k, v in m["lamp_flasher_numbers"].items() if not k.startswith("_")}
    trough = sw_holds(m, "trough")
    van = sw_holds(m, "van")
    sw_re = re.compile(r"(PulseSw\s*\(?\s*|Controller\.Switch\s*\(\s*)(\d+)(\s*\)?)", re.I)
    cur_sub = None
    dropped = 0
    edges = 0
    in_update_lamps = False
    in_sol_block = False
    done = set()

    def once(key):
        if key in done:
            return False
        done.add(key)
        return True

    lines = src.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r")
        i += 1
        s = line.strip()
        low = s.lower()

        # ---- subs replaced whole: skip to their End Sub
        if cur_sub == "__drop__":
            if low == "end sub":
                cur_sub = None
            continue

        msub = re.match(r"^(?:public |private )?sub\s+([A-Za-z0-9_]+)", s, re.I)
        one_liner = bool(msub) and low.endswith("end sub")
        if msub:
            cur_sub = msub.group(1)
        sub_low = (cur_sub or "").lower()

        # ---- the header: our system script, our title
        if low.startswith('executeglobal gettextfile("controller.vbs")'):
            out.append('ExecuteGlobal GetTextFile("PADSPIKE2.vbs")')
            continue
        if low.startswith("if err then msgbox \"you need the controller.vbs"):
            out.append('If Err Then MsgBox "You need PADSPIKE2.vbs beside this table (tools\\spike2_emu\\vpx)"')
            continue
        if low == "on error goto 0" and once("cabinet"):
            out.append(line)
            out.extend(cabinet_lines(m))
            continue
        if re.match(r"^const usegi\s*=", low):
            out.append("Const UseGI \t\t\t= False   ' PAD: GI follows the GI LEDs (PadGiTick)")
            continue
        if low.startswith("usevpmdmd") and "true" in low:
            out.append("UseVPMDMD = False   ' PAD: the game's LCD is the rig's window, not a VPM DMD")
            continue
        if low.startswith("const cgamename"):
            out.append('Const cGameName = "%s"' % m["title"])
            rom = re.search(r'cgamename\s*=\s*"([^"]*)"', low)
            if rom:   # the backglass (B2S, DOF) knows the table by its ROM
                out.append('PadB2SName = "%s"' % rom.group(1))
            out.append("Dim bsTrough, bsVan, padGiState, padDiscOn")
            out.append("padGiState = -1 : padDiscOn = 0")
            continue
        if low.startswith("loadvpm "):
            out.append('LoadVPM "01000000","PADSPIKE2.vbs",3.10')
            continue
        if low.startswith("vpmnudge.tiltswitch"):
            out.append("\tvpmNudge.TiltSwitch\t\t= %d   ' TILT PENDULUM" % m["cabinet"]["tilt"])
            continue

        # ---- solenoid callbacks: Data East's go (both blocks), ours come once
        if re.match(r"^solcallback\s*\(", low):
            if not in_sol_block:
                in_sol_block = True
                out.extend(gen_sol_callbacks(m))
            continue

        # ---- lamps: bigger arrays, a bounded ChangedLamps, regenerated inserts
        if low.startswith("dim ") and "(340)" in low:
            out.append(line.replace("(340)", "(%d)" % LAMP_ARRAY))
            continue
        if low.startswith("lampstate(chglamp(ii, 0) )"):
            ind = line[:len(line) - len(line.lstrip())]
            out.append(ind + "If chgLamp(ii, 0) <= %d Then" % LAMP_ARRAY)
            out.append(ind + "\t" + s)
            continue
        if low.startswith("fadinglevel(chglamp(ii, 0) )"):
            ind = line[:len(line) - len(line.lstrip())]
            out.append(ind + "\t" + s)
            out.append(ind + "End If")
            continue
        if re.match(r"^sub\s+updatelamps\b", low):
            out.append(line)
            in_update_lamps = True
            out.extend(gen_lamp_lines(m))
            continue
        if in_update_lamps:
            if low == "end sub":
                in_update_lamps = False
                cur_sub = None
                out.append(line)
                continue
            if re.match(r"^nfadelm?\s", low):
                continue                     # Data East's numbering: regenerated above
            out.append(line)                 # Flashc on the backbox lamps, LampFlasher()
            continue
        if sub_low == "lampflasher":
            line = re.sub(r"LampState\s*\(\s*(\d+)\s*\)",
                          lambda mm: "LampState(%d)" % flash[int(mm.group(1))], line)
            out.append(line)
            if low == "end sub":
                cur_sub = None
            continue

        # ---- balls: the machine's six in a stack; the table's own trough goes
        if re.match(r"^sub\s+creatballs\b", low):
            out.append("Sub CreatBalls()")
            out.append("\t' PAD: the machine's six balls live in bsTrough (table1_Init)")
            out.append("End Sub")
            cur_sub = "__drop__"
            continue
        if re.match(r"^sub\s+drain_hit\b", low):
            out.append("Sub Drain_Hit()")
            out.append("\tPlaySound \"drain\"")
            out.append("\tbsTrough.AddBall Me        ' TROUGH 1..6 held while the balls sit there")
            out.append("End Sub")
            cur_sub = "__drop__"
            continue
        if low == "creatballs" and sub_low == "table1_init":
            out.append(line)
            out += [
                "",
                "\t' PAD: the machine's trough: six balls on TROUGH 1..6 (+ JAM), out on the TROUGH coil",
                "\tSet bsTrough = New cvpmBallStack",
                "\tbsTrough.InitSw 0, %s" % ", ".join(str(x) for x in trough),
                "\tbsTrough.InitKick BallRelease, 70, 5",
                "\tbsTrough.InitExitSnd SoundFX(\"BallRelease\",DOFContactors), SoundFX(\"Solenoid\",DOFContactors)",
                "\tbsTrough.Balls = 6",
                "",
                "\t' PAD: the van: LOWER LOCK 1/2 held while it holds balls, out on the LOWER LOCK coil",
                "\tSet bsVan = New cvpmBallStack",
                "\tbsVan.InitSw 0, %d, %d, 0, 0, 0, 0, 0" % tuple(van),
                "\tbsVan.InitKick sw41, 190, 7",
                "\tbsVan.InitExitSnd SoundFX(\"solenoid\",DOFContactors), \"\"",
            ]
            continue
        if sub_low == "sw41_hit" and re.match(r"^controller\.switch\s*\(\s*41\s*\)", low):
            out.append("\tbsVan.AddBall Me        ' LOWER LOCK 1/2: the van holds it until the coil")
            edges += 1
            continue

        # ---- the keys: the Action button (launch) on the plunger and lockbar keys,
        # the upper flipper's own button on the left key (the machine's button closes both)
        if re.match(r"^sub\s+table1_keydown\b", low):
            out.append(line)
            out += [
                "\tIf keycode = PlungerKey Or keycode = LockBarKey Then",
                "\t\tController.Switch(swLaunch) = 1",
                "\tEnd If",
                "\tIf keycode = LeftFlipperKey Then",
                "\t\tController.Switch(swULFlip) = 1",
                "\tEnd If",
            ]
            continue
        if re.match(r"^sub\s+table1_keyup\b", low):
            out.append(line)
            out += [
                "\tIf keycode = PlungerKey Or keycode = LockBarKey Then",
                "\t\tController.Switch(swLaunch) = 0",
                "\tEnd If",
                "\tIf keycode = LeftFlipperKey Then",
                "\t\tController.Switch(swULFlip) = 0",
                "\tEnd If",
            ]
            continue

        # ---- the ball shadows and rolling sounds stop at tnob
        if sub_low == "ballshadowupdate_timer" and low == "for b = 0 to ubound(bot)":
            out.append(line.replace("UBound(BOT)", "PadMin(UBound(BOT), tnob - 1)"))
            continue
        if sub_low == "rollingtimer_timer" and low == "for b = 0 to ubound(bot)":
            out.append(line.replace("UBound(BOT)", "PadMin(UBound(BOT), tnob)"))
            continue

        # ---- switch numbers: by the object whose sub sends them, else the rewrite
        obj = object_of(sub_low)
        if obj in by_obj:
            sid = by_obj[obj]

            def _obj(mm):
                nonlocal dropped
                if int(mm.group(2)) >= 1000:
                    return mm.group(0)
                if sid == 0:
                    dropped += 1
                return "%s%d%s" % (mm.group(1), (1000 + sid) if sid else 0, mm.group(3))
            line2 = sw_re.sub(_obj, line)
            if line2 != line:
                rep.append("%s: -> %s" % (cur_sub, (1000 + sid) if sid else "dropped"))
            line = line2
        else:
            def _rw(mm):
                nonlocal dropped
                n = int(mm.group(2))
                if n >= 1000 or n == 0:
                    return mm.group(0)
                sid = rewrite.get(n, 0)
                if sid == 0:
                    dropped += 1
                    return "%s%d%s" % (mm.group(1), 0, mm.group(3))
                return "%s%d%s" % (mm.group(1), 1000 + sid, mm.group(3))
            line2 = sw_re.sub(_rw, line)
            if line2 != line:
                rep.append("%s (by number): %s" % (cur_sub, line2.strip()[:70]))
            line = line2

        # ---- edges the Data East script never sent
        if sub_low in extra:
            sid = 1000 + extra[sub_low]
            if one_liner and sub_low == "sw40a_hit":
                # Sub sw40a_Hit:...:End Sub -> the same, plus RAMP RIGHT EXIT after it
                body = line.rstrip()
                assert body.lower().endswith(":end sub"), body
                line = body[:-len(":End Sub")] + (":vpmTimer.AddTimer 400, \"vpmTimer.PulseSw %d '\":End Sub" % sid)
                out.append(line + "   ' PAD: RIGHT RAMP ENTER held, RAMP RIGHT EXIT 400 ms on")
                edges += 1
                cur_sub = None
                continue
            assert not one_liner, cur_sub
            out.append(line)
            if msub:
                out.append("\tvpmTimer.PulseSw %d   ' PAD: %s" % (sid, {
                    1071: "LEFT SLINGSHOT", 1070: "RIGHT SLINGSHOT",
                    1088: "LEFT RAMP ENTER OPTO", 1084: "VAN ENTER OPTO"}.get(sid, "")))
                edges += 1
            if low == "end sub":
                cur_sub = None
            continue

        out.append(line)
        if one_liner or low == "end sub":
            cur_sub = None

    text = "\n".join(out)
    text += "\n".join(pad_subs(m))
    rep.append("switch edges dropped (no Stern switch): %d; edges added: %d" % (dropped, edges))
    return text, rep


def retrofit_items(table, m):
    """New GameItem streams: lights cloned from the map's `clone` light, the
    test timer cloned from its `clone` timer."""
    by_name = {}
    for data in table.items:
        kind, name, pos = table.item_info(data)
        by_name[name.lower()] = (kind, data)
    items = []
    rl = m["retrofit_lights"]
    kind, src = by_name[rl["clone"].lower()]
    assert kind == "Light", rl["clone"]
    for name, v in rl["lights"].items():
        items.append(vpxfile.clone_item(src, name, *v["at"]))
    for name, v in m.get("retrofit_triggers", {}).items():
        if name.startswith("_"):
            continue
        kind, src = by_name[v["clone"].lower()]
        assert kind == "Trigger", v["clone"]
        items.append(vpxfile.clone_item(src, name, *v["at"]))
    for name, v in m.get("retrofit_timers", {}).items():
        if name.startswith("_"):
            continue
        kind, src = by_name[v["clone"].lower()]
        assert kind == "Timer", v["clone"]
        item = vpxfile.clone_item(src, name, 0, 0)
        items.append(vpxfile.set_fields(item, {"TMON": struct.pack("<i", 1),
                                               "TMIN": struct.pack("<i", int(v["interval_ms"]))}))
    return items


def main(argv):
    mpath = MAP
    if "--map" in argv:
        i = argv.index("--map")
        mpath = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 3:
        print(__doc__)
        return 2
    src, outdir = argv[1], argv[2]
    os.makedirs(outdir, exist_ok=True)
    m = json.load(open(mpath, encoding="utf-8"))
    table = vpxfile.VpxTable(src)
    if not table.verify():
        print("refusing: %s does not verify against its own MAC" % src)
        return 1
    script = table.script()
    if not all(d in script or d in os.path.basename(src) for d in m["detect"]):
        print("refusing: %s is not the table %s is for (detect %s)"
              % (src, os.path.basename(mpath), m["detect"]))
        return 1
    script, rep = patch_script(script, m)
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
    print("wrote %s\n  MAC %s  verify %s\n  +%d items (%d lights, %d timers)"
          % (dst, mac.hex(), "OK" if ok else "MISMATCH", len(items),
             len(m["retrofit_lights"]["lights"]),
             len([k for k in m.get("retrofit_timers", {}) if not k.startswith("_")])))
    for r in rep:
        print("  " + r)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
