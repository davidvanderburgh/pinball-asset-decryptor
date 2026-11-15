"""Headless tests for the JJP mode SDK (PAD-1337): the mode-file checker and the
rungame.sh hook in mkjjpmodes.py, the runtime's keys staying in step with the
checker's, and jjpport.py's Mode vtable resolution (folded virtuals)."""
import importlib.util
import os
import re
import struct
import sys

import pytest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(HERE, "tools", "jjp_emu")


def _load(name):
    path = os.path.join(RIG, name + ".py")
    if not os.path.exists(path):
        pytest.skip(f"tools/jjp_emu/{name}.py not present")
    sys.path.insert(0, RIG)
    try:
        spec = importlib.util.spec_from_file_location(name + "_undertest", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.path.remove(RIG)
    return mod


RUNGAME = """#!/bin/dash
export JJPEDIR='/jjpe/gen1'
. $JJPEDIR/setenv.sh
chmod +x $JJPEDIR/scripts/runonce.sh
$JJPEDIR/scripts/runonce.sh

while true
do
  $GAMEDIR/game
done
"""

PORT = {"title": "Guns N' Roses", "switches": ["switch_target_jam", "switch_orbit_left_hi"],
        "lamps": ["lp_target_jam"], "sounds": ["se_cheer"], "fonts": ["font_slash_solo_mode_timer"],
        "game_modes": []}


def _folder(tmp_path, files):
    for name, text in files.items():
        (tmp_path / name).write_text(text)
    return str(tmp_path)


def test_hook_goes_after_runonce_once_and_strips_clean():
    mm = _load("mkjjpmodes")
    hooked = mm.hook_rungame_modes(RUNGAME)
    lines = hooked.split("\n")
    at = lines.index("$JJPEDIR/scripts/runonce.sh")
    assert lines[at + 3] == "[ -r $JJPEDIR/scripts/padmodes.sh ] && . $JJPEDIR/scripts/padmodes.sh"
    assert mm.hook_rungame_modes(hooked) == hooked            # idempotent
    assert mm.strip_modes_hook(hooked) == RUNGAME


def test_hook_sits_beside_a_multiboot_hook():
    mm = _load("mkjjpmodes")
    multi = RUNGAME.replace("$JJPEDIR/scripts/runonce.sh\n",
                            "$JJPEDIR/scripts/runonce.sh\n\n# PAD multi-boot: a boot menu\n"
                            "[ -x $JJPEDIR/scripts/padselect.sh ] && $JJPEDIR/scripts/padselect.sh\n")
    hooked = mm.hook_rungame_modes(multi)
    assert "padselect.sh ] && $JJPEDIR/scripts/padselect.sh" in hooked
    assert mm.has_modes_hook(hooked) and mm.strip_modes_hook(hooked) == multi


def test_hook_refuses_a_rungame_it_does_not_know():
    mm = _load("mkjjpmodes")
    with pytest.raises(mm.Refused):
        mm.hook_rungame_modes(RUNGAME.replace("$JJPEDIR/scripts/runonce.sh\n", ""))


def test_padmodes_sh_honours_the_off_switch_and_appends_to_ld_preload():
    mm = _load("mkjjpmodes")
    assert "[ ! -e /jjpe/perm/padmodes.off ]" in mm.PADMODES_SH
    assert 'LD_PRELOAD="${LD_PRELOAD:+$LD_PRELOAD }$JJPEDIR/padmodes/jjpmodes.so"' in mm.PADMODES_SH
    assert "JJP_MODS_DIR=$JJPEDIR/padmodes/modes" in mm.PADMODES_SH


def test_check_passes_a_good_folder_and_names_every_problem(tmp_path):
    mm = _load("mkjjpmodes")
    good = _folder(tmp_path, {
        "title.cfg": "game = GunsNRoses\nfont_timer = font_slash_solo_mode_timer\n",
        "1_jam.mode": "name = Jam\nstart = switch_target_jam\npoints = 1,000,000  # a shot\n"
                      "lamps = lp_target_jam\nlamp_color = ff2000\ngame_modes = end\nsound_shot = se_cheer\n",
    })
    modes, problems = mm.check_modes(good, PORT)
    assert problems == [] and modes[0]["name"] == "Jam" and modes[0]["points"] == "1,000,000"
    (tmp_path / "2_bad.mode").write_text("start = switch_typo\nseconds = soon\nlamp_color = red\n"
                                         "game_modes = maybe\ningame_state = 5\nwobble = 1\n")
    _, problems = mm.check_modes(good, PORT)
    text = "\n".join(problems)
    assert "2_bad.mode:1: start not in Guns N' Roses: switch_typo" in text
    assert "seconds must be a whole number" in text
    assert "lamp_color must be rrggbb hex" in text
    assert "game_modes must be one of pause, end, ignore" in text
    assert "ingame_state belongs in title.cfg" in text
    assert "unknown key wobble" in text


def test_check_wants_a_start_switch(tmp_path):
    mm = _load("mkjjpmodes")
    _, problems = mm.check_modes(_folder(tmp_path, {"a.mode": "name = A\n"}))
    assert problems == ["a.mode: no start = <switch> (the mode would never start)"]


def test_every_key_the_runtime_reads_is_a_key_the_checker_knows():
    mm = _load("mkjjpmodes")
    src = open(os.path.join(RIG, "jjpmodes.c"), encoding="utf-8").read()
    body = src[src.index("static void apply_kv("):src.index("static int load_file(")]
    runtime = set(re.findall(r'!strcmp\(k, "([a-z_]+)"\)', body))
    assert runtime == set(mm.KEYS) | set(mm.TITLE_KEYS)


class _StubElf:
    """Enough of jjpelf.GameElf for mode_vtable: a _ZTV4Mode laid out like GnR's, where
    is_timer_paused shares its body with another class's hook and the start and total
    choreo hooks are one body."""

    def __init__(self):
        self.syms, words = {}, [0, 0x1111]
        fns = {"_ZN4Mode5startEv": 0x10, "_ZN4Mode3endEv": 0x20, "_ZN4Mode8set_timeEi": 0x28,
               "_ZN4Mode10is_runningEv": 0x48, "_ZN4Mode15score_and_totalEy": 0x88,
               "_ZN4Mode14hook_tick_workEi": 0xa8}
        empty, false_ = 0x9000, 0x9100
        slots = [0x5000 + i for i in range(24)]
        for name, off in fns.items():
            slots[off // 8] = 0x6000 + off
            self.syms[name] = (0x6000 + off, 8)
        slots[0x38 // 8] = false_
        slots[0xb0 // 8] = slots[0xb8 // 8] = empty
        self.syms["_ZN4Mode15is_timer_pausedEv"] = (false_, 8)
        self.syms["_ZN4Mode25hook_do_mode_start_choreoEv"] = (empty, 8)
        self.syms["_ZN4Mode25hook_do_mode_total_choreoEv"] = (empty, 8)
        words += slots
        self.blob = struct.pack("<%dQ" % len(words), *words)
        self.syms["_ZTV4Mode"] = (0x100000, len(self.blob))

    def addr(self, n):
        return self.syms[n][0]

    def read(self, a, n):
        return self.blob[a - 0x100000:a - 0x100000 + n]


def test_vtable_resolution_tells_folded_virtuals_apart():
    jp = _load("jjpport")
    vt = jp.mode_vtable(_StubElf())
    assert vt == {"start": 0x10, "end": 0x20, "set_time": 0x28, "is_running": 0x48, "timer_paused": 0x38,
                  "score": 0x88, "tick": 0xa8, "start_choreo": 0xb0, "total_choreo": 0xb8}
