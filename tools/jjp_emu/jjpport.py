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
  * defaults for a first mode (`defaults`), picked by name;
  * the coils a mode may pulse or hold (`coils`, PAD-1353), by the runtime's own
    name rules (COIL_NEVER / COIL_HOLDABLE, the twins of jjpmodes.c's lists), and
    whether the engine's ball saver and Coil API are there (`can_balls`, `can_coils`).

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
    ("balls", "_Z26mb_request_balls_into_playii", False),
    ("balls", "_Z22mb_add_balls_into_playii", False),
    ("balls", "_Z17mb_kill_ballsaverv", False),
    ("balls", "_Z23mb_ballsaver_is_runningv", False),
    ("balls", "_Z21mb_get_ballsaver_timev", False),
    ("coils", "_ZN4Coil10coil_pulseEj", False),
    ("coils", "_ZN4Coil9coil_dutyEjjh", False),
    ("coils", "_ZN4Coil8coil_offEv", False),
    ("coils", "_Z21coil_get_duty_patterni", False),
    ("coils", "coil_table", False),
]
#: PAD-1365: JJP's first engine generation (The Wizard of Oz 08.02) has no Mode class; the
#: runtime then runs a mode on a proc of its own (jjpmodes.c "the proc engine").  What that
#: needs, all plain engine functions; the runtime takes proc_create when proc_cret is missing.
PROC_SDK = [
    ("proc", "_Z11proc_createjPFvjE18proc_create_flag_t14proc_survive_t", True),
    ("proc", "_Z9proc_cretjPFvjE14proc_survive_t", False),
    ("proc", "_Z10proc_sleepj", True),
    ("proc", "_Z14proc_id_existsj", True),
    ("proc", "_Z22score_add_to_player_upyb", True),
    ("proc", "_Z15update_all_soonv", False),
]
#: the names every engine needs (the rest of SDK's required ones are the Mode class)
COMMON_REQUIRED = ("_Z14jjpe_state_getv", "_ZN11SoundEffect4playEv")
#: jjpmodes.c cb_proc_modes: a function of the proc's unsigned argument is one of the game's modes
#: (a proc running it = that mode running) when it is named for a mode, named like Mode's own
#: procs (<x>_run_proc, <x>_grace_proc ...), or is <x>_proc with an <x>_proc_kill_func of its own;
#: never one of these
PROC_MODE_NOT = ("amode", "attract", "kill", "jukebox", "timer", "test", "diag", "menu",
                 "leff", "_lef", "lamp", "tilt", "music", "match", "hook_", "multiled", "choreo")
PROC_MODE_ENDS = ("run_proc", "grace_proc", "proc_run", "proc_grace", "proc_grace_grace")


def _proc_fn_name(n):
    """jjpmodes.c demangle_proc_fn: `_Z<n>NAMEj` -> NAME, `_ZN<n>A<n>BEj` -> A::B, else None."""
    if not n.startswith("_Z") or not n.endswith("j"):
        return None
    p, nested, parts = n[2:], False, []
    if p.startswith("N"):
        nested, p = True, p[1:]
    while p[:1].isdigit() and p[0] != "0":
        m = re.match(r"(\d+)", p)
        k = int(m.group(1))
        if k > len(p) - m.end():
            return None
        parts.append(p[m.end():m.end() + k])
        p = p[m.end() + k:]
        if not nested:
            break
    if not parts or p != ("Ej" if nested else "j"):
        return None
    return "::".join(parts)


def proc_modes(e):
    """The game's mode functions the runtime watches on the proc engine (PAD-1365)."""
    out = []
    for n, (a, s) in e.syms.items():
        d = _proc_fn_name(n)
        if not d or not s:
            continue
        low = d.lower()
        if any(x in low for x in PROC_MODE_NOT):
            continue
        if ("mode" in low or low.endswith(PROC_MODE_ENDS)
                or (low.endswith("_proc") and "::" not in d and "_Z%d%s_kill_funcj" % (len(d) + 10, d) in e.syms)):
            out.append(d)
    return sorted(set(out))
#: jjpmodes.c's COIL_NEVER and COIL_HOLDABLE (PAD-1353): a coil whose name has a NEVER
#: part is the game's own (ball handling, flippers, power, motors the game positions) and
#: no mode fires it, unless it has a COIL_ANYWAY part; one
#: with a HOLDABLE part is built to stay on and a mode may hold it, bounded.
COIL_NEVER = ("flipper", "trough", "autolaunch", "auto_launch", "autoplunge", "plunger", "sling", "jet", "bumper",
              "stepper", "relay", "power", "ticket", "null", "motor")
#: ...except these: the shaker motor is a motor a mode may run
COIL_ANYWAY = ("shaker",)
COIL_HOLDABLE = ("magnet", "divert", "post", "gate", "shaker", "flash", "lamp", "light", "led")


def coil_rules(name):
    """-> (pulse, hold) a mode may do on the coil called `name` (jjpmodes.c coil_index)."""
    pulse = not any(k in name for k in COIL_NEVER) or any(k in name for k in COIL_ANYWAY)
    return pulse, pulse and any(k in name for k in COIL_HOLDABLE)


def coils(e):
    """The named Coil globals (the size most coil_<n> have), each with what a mode may do."""
    sizes = collections.Counter(s for n, (a, s) in e.syms.items() if re.match(r"^coil_\d+$", n))
    if not sizes:
        return []
    size = sizes.most_common(1)[0][0]
    out = []
    for n in object_names(e, "coil_", re.compile(r"^coil_\d+$"), {size}):
        pulse, hold_ = coil_rules(n)
        out.append(collections.OrderedDict([("symbol", n), ("pulse", pulse), ("hold", hold_)]))
    return out
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
#: PAD-1354 start rules: the game's Hook<...>::list globals the runtime puts a node on
#: (start_on events, the per-ball / per-game resets, the score check and the moments a
#: raised start is done in), and what each is for
RULE_HOOKS = collections.OrderedDict([
    ("HookBallStart_", "start_on ball_start; start_once / start_count_reset per ball"),
    ("HookFirstBall_", "start_on first_ball"), ("HookLastBall_", "start_on last_ball"),
    ("HookValidPlayfield_", "start_on valid_playfield"), ("HookBallSave_", "start_on ball_saved"),
    ("HookExtraBallAwarded_", "start_on extra_ball"), ("HookMultiballEnd_", "start_on multiball_end"),
    ("HookGameStart_", "start counts, score marks and start_once reset per game"),
    ("HookScore_", "start_score checked as the game scores"),
    ("HookLampRender_", "tick: a raised start is done here"), ("HookUpdate_", "tick"),
    ("HookSwitchDispatchStart_", "tick"),
])
TICK_HOOKS = ("HookLampRender_", "HookUpdate_", "HookSwitchDispatchStart_")


def rule_hooks(e):
    """{hook: present} for RULE_HOOKS, found as jjpmodes.c hook_list finds them: a 16-byte
    _ZN4HookI<len><hook>...E4listE object."""
    out = collections.OrderedDict((h, False) for h in RULE_HOOKS)
    for n, (a, s) in e.syms.items():
        if not n.startswith("_ZN4HookI") or not n.endswith("4listE") or s != 16:
            continue
        m = re.match(r"_ZN4HookI(\d+)", n)
        if m:
            k = int(m.group(1))
            h = n[m.end():m.end() + k]
            if h in out:
                out[h] = True
    return out


def start_rules(e, hooks):
    score = "_Z22score_get_player_scorei" in e.syms and "_Z23game_flow_get_player_upv" in e.syms
    tick = any(hooks.get(h) for h in TICK_HOOKS)
    return collections.OrderedDict([
        ("can_start_on_rules", tick),
        ("start_on", [w for w, h in (("ball_start", "HookBallStart_"), ("first_ball", "HookFirstBall_"),
                                     ("last_ball", "HookLastBall_"), ("valid_playfield", "HookValidPlayfield_"),
                                     ("ball_saved", "HookBallSave_"), ("extra_ball", "HookExtraBallAwarded_"),
                                     ("multiball_end", "HookMultiballEnd_")) if tick and hooks.get(h)]),
        ("start_after", tick), ("start_combo", True), ("start_score", tick and score),
    ])


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


def derived_classes(e):
    """(Mode classes, MultiballRule classes) as mangled names ("13CandyLaneMode"), found as
    jjpmodes.c finds them in the game - each vtable's typeinfo (word 1), walked up its base
    chain.  A single-inheritance typeinfo holds its base at +16; a multiple-inheritance one
    a count at +20 and {base, offset} pairs from +24."""
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
    return modes, mbs


def hold(e):
    """PAD-1348 game_modes = hold, on the file: the classes whose start/restart slots the
    runtime gates (derived_classes)."""
    modes, mbs = derived_classes(e)
    slots = collections.OrderedDict([
        ("mode_start", _slot_of(e, "_ZTV4Mode", "_ZN4Mode5startEv")),
        ("mode_restart", _slot_of(e, "_ZTV4Mode", "_ZN4Mode7restartEv")),
        ("multiball_start", _slot_of(e, "_ZTV13MultiballRule", "_ZN13MultiballRule5startEv")),
        ("multiball_restart", _slot_of(e, "_ZTV13MultiballRule", "_ZN13MultiballRule7restartEv")),
    ])
    return collections.OrderedDict([
        ("can_hold", "_ZTI4Mode" in e.syms and slots["mode_start"] is not None),
        ("slots", slots),
        ("mode_classes", len(modes)),
        ("multiball_classes", sorted(mbs)),
    ])


#: what a mode's own sounds, music, picture and video use (PAD-1352): the game's
#: SoundEffect (a copy of one of its own plays our sample), its music list, and
#: the Allegro / FFmpeg libraries the game links (found at run time by name)
MEDIA_SYMBOLS = [
    ("sounds", "_ZN11SoundEffect23create_sample_instancesEPKc"),
    ("sounds", "_ZN11SoundEffect7do_playEb"),
    ("sounds", "_ZN11SoundEffect9is_loadedEv"),
    ("sounds", "_ZN11SoundEffect10is_playingEv"),
    ("sounds", "_ZN11SoundEffect17play_audio_streamEv"),
    ("music", "_ZN6UpdateI14UpdateBGMusic_PPFvvEE4listE"),
    ("music", "_Z12update_musicv"),
    ("music", "_Z13music_requestPFvvE"),
]
MEDIA_LIBS = [
    ("sounds", "liballegro_audio.so"), ("sounds", "liballegro_acodec.so"),
    ("picture", "liballegro_image.so"),
    ("video", "libavformat.so"), ("video", "libavcodec.so"), ("video", "libavutil.so"),
]
_NEEDED = re.compile(rb"lib[a-z_]+\.so\.[0-9.]+")


def media(e):
    """Can this title play a mode's own sounds, music, picture and video?  Statically: the
    engine pieces by name, the game's SoundEffect object size (a copy of one is ours), the
    libraries it links.  The runtime reads the SoundEffect fields off the decrypted code."""
    needed = sorted(set(m.decode() for m in _NEEDED.findall(e.data[:8 << 20])))
    have = collections.OrderedDict()
    for what, name in MEDIA_SYMBOLS:
        have.setdefault(what, collections.OrderedDict())[name] = name in e.syms
    for what, lib in MEDIA_LIBS:
        have.setdefault(what, collections.OrderedDict())[lib] = any(n.startswith(lib) for n in needed)
    sizes = collections.Counter(s for n, (a, s) in e.syms.items() if n.startswith("se_") and s >= 0x100)
    ok = {what: all(v.values()) for what, v in have.items()}
    ok["sounds"] = ok.get("sounds", False) and bool(sizes)
    return collections.OrderedDict([
        ("can_play_own_media", all(ok.values())),
        ("ok", ok),
        ("pieces", have),
        ("sound_object_bytes", sizes.most_common(1)[0][0] if sizes else None),
        ("libraries", [n for n in needed if re.match(r"lib(av|allegro)", n)]),
    ])


def _demangled_class(mangled):
    m = re.match(r"^(\d+)(.*)$", mangled)
    return m.group(2)[:int(m.group(1))] if m else mangled


def _fn_at(e, vtname, off):
    """The exported function a vtable slot holds (byte offset from the vptr), or None."""
    if off is None or vtname not in e.syms:
        return None
    a, sz = e.syms[vtname]
    if 16 + off + 8 > sz:
        return None
    w = struct.unpack("<Q", e.read(a + 16 + off, 8))[0]
    return e.by_addr.get(w)


#: the shot id a made shot carries, and how the runtime sets it for shots_add (jjpmodes.c stock_install)
SHOT_GET = "_Z21shot_get_proc_shot_idv"
SHOT_SET = ("_Z21shot_set_proc_shot_id9shot_id_t", "_Z21shot_set_proc_shot_id10_shot_id_e")


def stock(e, live=None):
    """PAD-1351 .stock files, on the file: for each of the title's Mode classes, which of the
    game's own virtuals a .stock key works through - timer (its run_proc slot, then its
    set_time), points (its score_and_total slot), shots (its own shot_dispatch, which asks
    is_running through the vtable).  `live` (modes/ports/<title>.live.json, jjpstock.py live)
    adds what only a running game shows: each mode global's class and the shot table."""
    if "_ZTV4Mode" not in e.syms:
        return collections.OrderedDict([("can_change", False)])
    modes, _mbs = derived_classes(e)
    slot = {k: _slot_of(e, "_ZTV4Mode", fn) for k, fn in (
        ("run_proc", "_ZN4Mode8run_procEj"), ("set_time", "_ZN4Mode8set_timeEi"),
        ("score", "_ZN4Mode15score_and_totalEy"), ("is_running", "_ZN4Mode10is_runningEv"),
        ("is_running_or_grace", "_ZN4Mode19is_running_or_graceEv"),
        ("is_running_or_grace_grace", "_ZN4Mode25is_running_or_grace_graceEv"))}
    classes = collections.OrderedDict()
    for mangled in sorted(modes, key=_demangled_class):
        c = _demangled_class(mangled)
        vt = "_ZTV" + mangled
        own_sd = "_ZN%s13shot_dispatchEv" % mangled
        set_time = _fn_at(e, vt, slot["set_time"])
        score = _fn_at(e, vt, slot["score"])
        classes[c] = collections.OrderedDict([
            ("timer", "own set_time" if set_time and set_time != "_ZN4Mode8set_timeEi" else "Mode::set_time"),
            ("points", "own score_and_total" if score and score != "_ZN4Mode15score_and_totalEy" else "Mode::score_and_total"),
            ("shots", own_sd in e.syms),
        ])
    shot_set = next((n for n in SHOT_SET if n in e.syms), None)
    shot_made = sorted(n for n in e.syms if re.match(r"^_Z\d+shot_made_\w+v$", n))
    out = collections.OrderedDict([
        ("can_change", all(v is not None for v in slot.values()) and SHOT_GET in e.syms),
        ("slots", slot),
        ("shot_id", collections.OrderedDict([
            ("read", SHOT_GET in e.syms),
            ("set_by", "shot_set_proc_shot_id" if shot_set else "the proc argument (read off shot_get_proc_shot_id)"),
        ])),
        ("shot_handlers", len(shot_made)),
        ("classes", classes),
    ])
    live = live or {}
    if live.get("objects"):
        out["objects"] = collections.OrderedDict(sorted(
            (o, c) for o, c in live["objects"].items() if c in classes))
    if live.get("shots"):
        out["shots"] = live["shots"]
    out["live"] = live.get("source", "") if live else ""
    return out


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


def port(elf_path, gamename=None, live=None):
    e = GameElf(elf_path)
    sdk = collections.OrderedDict()
    missing_mode = []
    for what, name, required in SDK + PROC_SDK:
        ok = name in e.syms
        sdk.setdefault(what, collections.OrderedDict())[name] = ok
        if required and not ok and (what, name, required) in SDK:
            missing_mode.append(name)
    vt = mode_vtable(e) if "_ZTV4Mode" in e.syms else {}
    hooks = rule_hooks(e)
    bad_slots = [k for k, v in vt.items() if v is None and k != "total_choreo"]
    # which engine runs a mode: the Mode class when it is there and its slots resolve (as
    # jjpmodes.c pick_engine), else a proc of the runtime's own (PAD-1365)
    missing_proc = [n for w, n, r in PROC_SDK if r and n not in e.syms] + [n for n in COMMON_REQUIRED if n not in e.syms]
    if not missing_mode and not bad_slots:
        engine, missing_required = "mode", []
    elif not missing_proc:
        engine, missing_required = "proc", []
    else:
        engine, missing_required = "", missing_mode
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
    pulse_ok = [c["symbol"] for c in coils(e) if c["pulse"]]
    defaults["multiball_start"] = defaults["shots"].split()[1] if len(defaults["shots"].split()) > 1 else start
    defaults["coil_shot"] = _first(pulse_ok, [r"knocker", r"kick", r"vuk", r"eject"]) if pulse_ok else ""
    return collections.OrderedDict([
        ("format", FORMAT),
        ("elf", os.path.basename(elf_path)),
        ("game", gamename or ""),
        ("exported_symbols", len(e.syms)),
        ("can_run_modes", bool(engine)),
        ("engine", engine),
        ("missing_required", missing_required),
        ("mode_vtable", vt),
        ("hold", hold(e) if engine == "mode" else {"can_hold": False}),
        ("proc_modes", proc_modes(e) if engine == "proc" else []),
        ("media", media(e)),
        ("can_balls", all(sdk.get("balls", {}).values()) and bool(sdk.get("balls"))),
        ("can_coils", all(sdk.get("coils", {}).values()) and bool(sdk.get("coils"))),
        ("hooks", hooks),
        ("start_rules", start_rules(e, hooks)),
        ("stock", stock(e, live)),
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
        ("coils", coils(e)),
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
    write_multiball_example(p, folder, title_label)


def write_multiball_example(p, folder, title_label):
    """A second starter (PAD-1353): the mode's own multiball, with a coil pulse per shot."""
    d = p["defaults"]
    if not (p.get("can_balls") and d.get("multiball_start")):
        return
    with open(os.path.join(folder, "2_multiball.mode"), "w", newline="\n") as f:
        f.write("# A multiball of the mode's own for %s: 3 balls, 10 s ball save, one ball left\n"
                "# ends it (seconds = 0: no clock).  Every key: tools/jjp_emu/MODES.md\n" % title_label)
        f.write("name = PAD Multiball\ntitle = PAD MULTIBALL\n")
        f.write("start = %s\nshots = %s\n" % (d["multiball_start"], d["shots"]))
        f.write("points = 2000000\nseconds = 0\nmultiball = 3 10\nadd_ball = %s 1\n" % d["start"])
        if d.get("coil_shot"):
            f.write("coil_shot = %s\n" % d["coil_shot"])
        if d.get("sound_shot"):
            f.write("sound_shot = %s\n" % d["sound_shot"])


def write_stock_example(p, folder, title_label):
    """A starter .stock file: one of the title's own mode classes with shots of its own
    (a mode global's name needs a live game, jjpstock.py; a class name works without)."""
    cl = (p.get("stock") or {}).get("classes") or {}
    pick = sorted((c for c, v in cl.items() if v["shots"]),
                  key=lambda c: (not c.endswith("Mode"), v_own(cl[c]), c))
    if not pick:
        return None
    c = pick[0]
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, "%s.stock" % c)
    with open(path, "w", newline="\n") as f:
        f.write("# %s: the game's own %s, changed.  Every key: tools/jjp_emu/MODES.md\n" % (title_label, c))
        f.write("# Its timer: %s; its points: %s; shots of its own: yes.\n" % (cl[c]["timer"], cl[c]["points"]))
        f.write("mode = %s\npoints_x = 2\n" % c)
        f.write("# seconds = 45\n# shots_off = <shot>\n# shots_add = <switch>:<shot>\n")
        f.write("# Shot names are logged on the machine (jjpmodes.log, \"shots:\").\n")
    return path


def v_own(v):
    """Sort key: classes whose points are their own first (0)."""
    return 0 if v["points"] != "Mode::score_and_total" else 1


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("elf")
    ap.add_argument("--gamename", help="the title's GAMENAME (setenv.sh)")
    ap.add_argument("--out")
    ap.add_argument("--example", help="write a starter mode folder here")
    ap.add_argument("--label", help="title label for the example's comments")
    ap.add_argument("--multiball-example", help="write only the multiball starter (2_multiball.mode) here")
    ap.add_argument("--stock-example", help="write a starter .stock folder here")
    ap.add_argument("--live", help="a running game's mode globals and shot table (jjpstock.py live) to fold in")
    a = ap.parse_args(argv)
    live = json.load(open(a.live)) if a.live else None
    p = port(a.elf, a.gamename, live)
    if a.out:
        with open(a.out, "w", newline="\n") as f:
            json.dump(p, f, indent=1)
            f.write("\n")
    if a.example:
        write_example(p, a.example, a.label or a.gamename or p["elf"])
    if a.multiball_example:
        write_multiball_example(p, a.multiball_example, a.label or a.gamename or p["elf"])
    if a.stock_example:
        print("  starter .stock: %s" % write_stock_example(p, a.stock_example, a.label or a.gamename or p["elf"]))
    print("%s: %s; %d exported, %d switches, %d lamps, %d sounds, %d fonts, %d Mode classes%s" % (
        p["elf"], ("CAN run modes (%s engine)" % p["engine"]) if p["can_run_modes"] else "can NOT run modes", p["exported_symbols"],
        len(p["switches"]), len(p["lamps"]), len(p["sounds"]), len(p["fonts"]), len(p["mode_classes"]),
        ("; missing " + " ".join(p["missing_required"])) if p["missing_required"] else ""))
    print("  own media: %s" % ("yes" if p["media"]["can_play_own_media"] else
                               "no (%s)" % " ".join(k for k, v in p["media"]["ok"].items() if not v)))
    print("  vtable %s" % " ".join("%s=%s" % (k, hex(v) if v is not None else "-") for k, v in p["mode_vtable"].items()))
    if p["engine"] == "proc":
        print("  proc engine: %d game mode function(s) watched: %s" % (len(p["proc_modes"]), " ".join(p["proc_modes"])))
    print("  defaults %s" % json.dumps(p["defaults"]))
    cs = p["coils"]
    print("  balls %s, coils %s: %d named, %d a mode may pulse, %d it may hold" % (
        "yes" if p["can_balls"] else "no", "yes" if p["can_coils"] else "no", len(cs),
        sum(c["pulse"] for c in cs), sum(c["hold"] for c in cs)))
    sr = p["start_rules"]
    print("  start rules: %s; start_on %s%s" % ("yes" if sr["can_start_on_rules"] else "switches and combos only",
                                             " ".join(sr["start_on"]) or "-", "; start_score" if sr["start_score"] else ""))
    st = p["stock"]
    if st.get("classes"):
        cl = st["classes"]
        print("  stock modes: %d classes, %d with their own shots, %d their own timer, %d their own points%s" % (
            len(cl), sum(1 for v in cl.values() if v["shots"]), sum(1 for v in cl.values() if v["timer"] != "Mode::set_time"),
            sum(1 for v in cl.values() if v["points"] != "Mode::score_and_total"),
            "; %d shots named (live)" % len(st["shots"]) if st.get("shots") else ""))
    return 0 if p["can_run_modes"] else 1


if __name__ == "__main__":
    sys.exit(main())
