#!/usr/bin/env python3
"""jjpport.py - what the JJP mode SDK has to work with in one title, read off its game binary.

PAD-1337.  The SDK runtime (jjpmodes.c) finds everything by exported name, so
whether a title can run custom modes is a question about its .dynsym, answered
here statically - no key, no running game:

  * every engine symbol the runtime needs, present or missing (`sdk`);
  * the Mode vtable slots, resolved the way the runtime does (by address,
    folded empty virtuals told apart by declaration order) - a title whose
    slots do not resolve cannot run modes;
  * the names a mode file can use: named shot switches (`switches`), lamps and
    lamp groups (`lamps`), sounds (`sounds`), the game's fonts (`fonts`), and
    its Mode classes (`mode_classes`);
  * defaults for a first mode (`defaults`), picked by name.

    jjpport.py GAME_ELF [--gamename NAME] [--out PORT.json] [--example DIR]

--example writes a starter mode folder (title.cfg + one .mode) from the
defaults.  The port JSON is what mkjjpmodes.py check --port checks names against.
"""
import argparse
import collections
import json
import os
import re
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jjpelf import GameElf  # noqa: E402

FORMAT = 1

#: (what it is for, mangled name, required)
SDK = [
    ("mode", "_ZN4ModeC1EPKciP11ModeManagerP4LampjjjP5AuditS7_", True),
    ("mode", "_ZTV4Mode", True),
    ("mode", "_ZN4Mode5startEv", True),
    ("mode", "_ZN4Mode3endEv", True),
    ("mode", "_ZN4Mode8set_timeEi", True),
    ("mode", "_ZN4Mode10is_runningEv", True),
    ("mode", "_ZN4Mode15is_timer_pausedEv", True),
    ("mode", "_ZN4Mode15score_and_totalEy", True),
    ("mode", "_ZN4Mode14hook_tick_workEi", True),
    ("mode", "_ZN4Mode25hook_do_mode_start_choreoEv", True),
    ("mode", "_ZN4Mode25hook_do_mode_total_choreoEv", False),
    ("game", "_Z14jjpe_state_getv", True),
    ("game", "_Z16proc_am_i_a_procv", False),
    ("game", "_Z26game_flow_get_ball_in_playv", False),
    ("yield", "_Z28mb_get_logical_balls_in_playv", False),
    ("yield", "_Z20mb_get_balls_in_playv", False),
    ("sound", "_ZN11SoundEffect4playEv", True),
    ("lamps", "_ZN10LampBufferC1EiPFvPS_EPKc9lb_flag_t", False),
    ("lamps", "_ZN4Lamp3setER10LampBufferhhhh", False),
    ("lamps", "_ZN4Lamp11transparentER10LampBuffer", False),
    ("lamps", "_ZN10LampBuffer10render_allEv", False),
    ("lamps", "_ZTV4Lamp", False),
    ("screen", "_ZN8JJPEFont4fontEv", False),
    ("screen", "_Z24font_plot_outline_shadowPK12ALLEGRO_FONT13ALLEGRO_COLORS2_iS2_iffiPKc", False),
]
#: runtime slot -> (mangled, nth among equal addresses, slot it must follow)
SLOTS = [
    ("start", "_ZN4Mode5startEv", 0, None), ("end", "_ZN4Mode3endEv", 0, None),
    ("set_time", "_ZN4Mode8set_timeEi", 0, None), ("is_running", "_ZN4Mode10is_runningEv", 0, None),
    ("timer_paused", "_ZN4Mode15is_timer_pausedEv", 0, None), ("score", "_ZN4Mode15score_and_totalEy", 0, None),
    ("tick", "_ZN4Mode14hook_tick_workEi", 0, None),
    ("start_choreo", "_ZN4Mode25hook_do_mode_start_choreoEv", 0, "tick"),
    ("total_choreo", "_ZN4Mode25hook_do_mode_total_choreoEv", 0, "start_choreo"),
]
_BARE_SWITCH = re.compile(r"^d?switch_\d+$")


def mode_vtable(e):
    """{slot: byte offset from the vptr or None}, the runtime's resolve_vtable on the file."""
    a, sz = e.syms["_ZTV4Mode"]
    words = struct.unpack("<%dQ" % (sz // 8), e.read(a, sz - sz % 8))
    slots = list(words[2:])
    out = {}
    for name, mangled, nth, after in SLOTS:
        want = e.addr(mangled) if mangled in e.syms else None
        lo = out.get(after, -1) if after else -1
        hit = None
        if want is not None:
            k = nth
            for i, w in enumerate(slots):
                if w == want and i * 8 > (lo if lo is not None else -1):
                    if k == 0:
                        hit = i * 8
                        break
                    k -= 1
        out[name] = hit
    if out.get("total_choreo") is None and out.get("start_choreo") is not None:
        # GnR: the start and total choreo hooks are one folded body; the second
        # occurrence after tick_work is the total hook
        want = e.addr("_ZN4Mode25hook_do_mode_start_choreoEv")
        seen = 0
        for i, w in enumerate(slots):
            if w == want and i * 8 > out["tick"]:
                if seen == 1:
                    out["total_choreo"] = i * 8
                    break
                seen += 1
    return out


def _slot_of(e, vtname, fn):
    """Byte offset from the vptr of `fn` in vtable `vtname`, or None (jjpmodes.c byte_off_in)."""
    if vtname not in e.syms or fn not in e.syms:
        return None
    a, sz = e.syms[vtname]
    words = struct.unpack("<%dQ" % (sz // 8), e.read(a, sz - sz % 8))
    want = e.addr(fn)
    for i, w in enumerate(words[2:]):
        if w == want:
            return i * 8
    return None


def hold(e):
    """PAD-1348 game_modes = hold, on the file: the classes whose start/restart slots the
    runtime gates, found as jjpmodes.c finds them in the game - each vtable's typeinfo
    (word 1), walked up its base chain to Mode or MultiballRule.  A single-inheritance
    typeinfo holds its base at +16; a multiple-inheritance one a count at +20 and
    {base, offset} pairs from +24."""
    tis = {a: n for n, (a, s) in e.syms.items() if n.startswith("_ZTI")}

    def word(a):
        return struct.unpack("<Q", e.read(a, 8))[0]

    def bases(ti):
        b = word(ti + 16)
        if b in tis:
            return [b]
        n = struct.unpack("<I", e.read(ti + 20, 4))[0]
        if 1 <= n <= 16:
            return [p for p in (word(ti + 24 + 16 * i) for i in range(n)) if p in tis]
        return []

    def derives(ti, base, depth=0):
        if ti == base:
            return True
        return depth < 12 and any(derives(b, base, depth + 1) for b in bases(ti))

    ti_mode = e.addr("_ZTI4Mode") if "_ZTI4Mode" in e.syms else None
    ti_mb = e.addr("_ZTI13MultiballRule") if "_ZTI13MultiballRule" in e.syms else None
    modes, mbs = [], []
    for n, (a, s) in e.syms.items():
        if not n.startswith("_ZTV") or s < 32:
            continue
        ti = word(a + 8)
        if ti not in tis:
            continue
        if ti_mode and derives(ti, ti_mode):
            modes.append(n[4:])
        elif ti_mb and derives(ti, ti_mb):
            mbs.append(n[4:])
    slots = collections.OrderedDict([
        ("mode_start", _slot_of(e, "_ZTV4Mode", "_ZN4Mode5startEv")),
        ("mode_restart", _slot_of(e, "_ZTV4Mode", "_ZN4Mode7restartEv")),
        ("multiball_start", _slot_of(e, "_ZTV13MultiballRule", "_ZN13MultiballRule5startEv")),
        ("multiball_restart", _slot_of(e, "_ZTV13MultiballRule", "_ZN13MultiballRule7restartEv")),
    ])
    return collections.OrderedDict([
        ("can_hold", bool(ti_mode) and slots["mode_start"] is not None),
        ("slots", slots),
        ("mode_classes", len(modes)),
        ("multiball_classes", sorted(mbs)),
    ])


def object_names(e, prefix, exclude=None, sizes=None):
    out = []
    for n, (a, s) in e.syms.items():
        if n.startswith(prefix) and (exclude is None or not exclude.match(n)) and (sizes is None or s in sizes):
            out.append(n)
    return sorted(out)


#: words a switch name shares with half the playfield: worth less than a word naming the place
_KIND_WORDS = {"target", "targets", "ramp", "orbit", "loop", "scoop", "lane", "left", "right", "center",
               "upper", "lower", "top", "bottom"}
_NOISE_WORDS = {"made", "hit", "enter", "entry", "exit", "opto", "switch", "sw"}
#: the short forms switch names use for a lamp's long ones (Godfather switch_u_target_1 = lp_upper_target_1)
_SHORT_WORDS = {"u": "upper", "l": "left", "r": "right", "c": "center", "lo": "low", "hi": "high"}


def _lamp_for(stem, lamps):
    """The lamp nearest the start shot by name (PAD-1364): the one sharing the most of
    the switch's words, a word naming the place (`tv`, `jet`) counting double a kind word
    (`target`, `ramp`, `left`) and `made`/`hit` not at all.  A tie goes to an insert
    over GI, then to one with the switch's number, then to the shorter name.  '' when no lamp shares a word - better no
    lamp in a starter than one somewhere else on the playfield."""
    words = [_SHORT_WORDS.get(w, w) for w in stem.split("_") if w and w not in _NOISE_WORDS]
    digits = {w for w in words if w.isdigit()}
    words = [w for w in words if not w.isdigit()]
    best, best_key = "", None
    for l in lamps:
        parts = set(_SHORT_WORDS.get(w, w) for w in l[3:].split("_"))
        score = sum(1 if w in _KIND_WORDS else 2 for w in words if w in parts)
        if not any(w in parts for w in words if w not in _KIND_WORDS) and score < 2:
            continue
        key = (score, "gi" not in parts, bool(digits & parts), -len(l))
        if score and (best_key is None or key > best_key):
            best, best_key = l, key
    return best


def _first(names, patterns):
    for p in patterns:
        r = re.compile(p, re.I)
        hit = [n for n in names if r.search(n)]
        if hit:
            return sorted(hit, key=lambda n: (len(n), n))[0]
    return names[0] if names else ""


def port(elf_path, gamename=None):
    e = GameElf(elf_path)
    sdk = collections.OrderedDict()
    missing_required = []
    for what, name, required in SDK:
        ok = name in e.syms
        sdk.setdefault(what, collections.OrderedDict())[name] = ok
        if required and not ok:
            missing_required.append(name)
    vt = mode_vtable(e) if "_ZTV4Mode" in e.syms else {}
    bad_slots = [k for k, v in vt.items() if v is None and k != "total_choreo"]
    # a Switch is a 104-byte global on GnR; take the size most of the numbered ones have
    sw_sizes = collections.Counter(s for n, (a, s) in e.syms.items() if re.match(r"^switch_\d+$", n))
    sw_size = sw_sizes.most_common(1)[0][0] if sw_sizes else None
    switches = object_names(e, "switch_", _BARE_SWITCH, {sw_size} if sw_size else None)
    switches += object_names(e, "dswitch_", _BARE_SWITCH, {sw_size} if sw_size else None)
    lamp_size = e.syms.get("lp_dummy", (0, None))[1]
    lamps = [n for n in object_names(e, "lp_") if not re.search(r"(^lp_unused|_unused_?\d*$)", n)]
    groups = object_names(e, "ls_")
    sounds = object_names(e, "se_")
    fonts = object_names(e, "font_")
    is_running = e.addr("_ZN4Mode10is_runningEv") if "_ZN4Mode10is_runningEv" in e.syms else None
    classes = []
    if is_running:
        for n, (a, s) in e.syms.items():
            if n.startswith("_ZTV") and s >= 32:
                words = struct.unpack("<%dQ" % (min(s, 320) // 8), e.read(a, min(s, 320) - min(s, 320) % 8))
                if is_running in words[2:]:
                    classes.append(n[4:])
    shot_like = [s for s in switches if not s.startswith("dswitch_")]
    start = _first(shot_like, [r"target", r"ramp.*made", r"orbit", r"loop", r"scoop", r"lane"])
    stem = re.sub(r"^switch_", "", start)
    lamp = next((l for l in lamps if l == "lp_" + stem), "") or _lamp_for(stem, lamps)
    defaults = collections.OrderedDict([
        ("start", start),
        ("shots", " ".join([start] + [s for s in shot_like if s != start and re.search(r"ramp.*made|orbit.*hi", s)][:2])),
        ("lamps", lamp),
        ("font_title", _first(fonts, [r"_mode_name", r"bp_mode$", r"mode_title", r"_mode$", r"title"])),
        ("font_value", _first(fonts, [r"mode_value$", r"mode.*total", r"_total$", r"value", r"score"])),
        ("font_timer", _first(fonts, [r"mode_timer$", r"timer"])),
        ("sound_start", _first(sounds, [r"fanfare.*start", r"mode.*start", r"intro", r"fanfare"])),
        ("sound_shot", _first(sounds, [r"fanfare.*jackpot$", r"jackpot", r"award", r"hit"])),
        ("sound_end", _first(sounds, [r"cheer", r"applause", r"total", r"end"])),
    ])
    return collections.OrderedDict([
        ("format", FORMAT),
        ("elf", os.path.basename(elf_path)),
        ("game", gamename or ""),
        ("exported_symbols", len(e.syms)),
        ("can_run_modes", not missing_required and not bad_slots),
        ("missing_required", missing_required),
        ("mode_vtable", vt),
        ("hold", hold(e) if "_ZTV4Mode" in e.syms else {"can_hold": False}),
        ("sdk", sdk),
        ("switch_object_bytes", sw_size),
        ("lamp_object_bytes", lamp_size),
        ("defaults", defaults),
        ("mode_classes", sorted(classes)),
        ("switches", switches),
        ("lamps", lamps),
        ("lamp_groups", groups),
        ("fonts", fonts),
        ("sounds", sounds),
    ])


def write_example(p, folder, title_label):
    os.makedirs(folder, exist_ok=True)
    d = p["defaults"]
    with open(os.path.join(folder, "title.cfg"), "w", newline="\n") as f:
        f.write("# %s - title-wide defaults for every mode in this folder (jjpport.py)\n" % title_label)
        if p.get("game"):
            f.write("game = %s\n" % p["game"])
        for k in ("font_title", "font_value", "font_timer"):
            if d.get(k):
                f.write("%s = %s\n" % (k, d[k]))
    with open(os.path.join(folder, "1_example.mode"), "w", newline="\n") as f:
        f.write("# A first custom mode for %s.  Every key: tools/jjp_emu/MODES.md\n" % title_label)
        f.write("name = PAD Mode\ntitle = PAD MODE\n")
        f.write("start = %s\n" % d["start"])
        f.write("shots = %s\n" % d["shots"])
        f.write("points = 1000000\nseconds = 20\ncomplete = 5\ncomplete_points = 5000000\n")
        for k in ("sound_start", "sound_shot", "sound_end"):
            if d.get(k):
                f.write("%s = %s\n" % (k, d[k]))
        if d.get("lamps"):
            f.write("lamps = %s\nlamp_color = ff2000\nlamp_blink = 4\n" % d["lamps"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf")
    ap.add_argument("--gamename", help="the title's GAMENAME (setenv.sh)")
    ap.add_argument("--out")
    ap.add_argument("--example", help="write a starter mode folder here")
    ap.add_argument("--label", help="title label for the example's comments")
    a = ap.parse_args(argv)
    p = port(a.elf, a.gamename)
    if a.out:
        with open(a.out, "w", newline="\n") as f:
            json.dump(p, f, indent=1)
            f.write("\n")
    if a.example:
        write_example(p, a.example, a.label or a.gamename or p["elf"])
    print("%s: %s; %d exported, %d switches, %d lamps, %d sounds, %d fonts, %d Mode classes%s" % (
        p["elf"], "CAN run modes" if p["can_run_modes"] else "can NOT run modes", p["exported_symbols"],
        len(p["switches"]), len(p["lamps"]), len(p["sounds"]), len(p["fonts"]), len(p["mode_classes"]),
        ("; missing " + " ".join(p["missing_required"])) if p["missing_required"] else ""))
    print("  vtable %s" % " ".join("%s=%s" % (k, hex(v) if v is not None else "-") for k, v in p["mode_vtable"].items()))
    print("  defaults %s" % json.dumps(p["defaults"]))
    return 0 if p["can_run_modes"] else 1


if __name__ == "__main__":
    sys.exit(main())
