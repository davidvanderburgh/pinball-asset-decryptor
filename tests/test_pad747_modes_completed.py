"""PAD-747: a mode that starts once the player has completed some of the game's own modes.

A tester (Uncanny X-Men): "is there a way to trigger my mode to happen based on X number of the stock modes being
completed? ... a mini-wizard mode after finishing 4 of the stock modes, then my bigger wizard mode after the final 4."

- The runtime keeps, per player and per game, which of the game's modes were completed, read the way the game records
  it: a C++ title's mode STOP entered with "completed" (PAD-710's framework lines), a plain-C title's COMPLETED audit or
  flag (PAD-710's books; mode_framework.done_lines adds the modes a build keeps books of but names no start of).
- Mode files `starts_on completed <N> [ids]`; the form's Starts on > the player completing N of the game's modes
  ticked; blocks' When the player has completed some of the game's modes.
- The desk runs (an ELF host C compiler; they skip elsewhere): mode_file.c and a blocks mode, the harness's `done <id>`
  standing in for the game completing a mode.
"""
import os
import re
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_framework as MF
from pinball_decryptor.plugins.stern import mode_project as MP

SDK = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu", "modes", "sdk")
PORTS = os.path.join(SDK, "ports")
XMEN = "uncanny_xmen_le_0_98"
MISSIONS = list(range(3, 11))          # X-Men 0.98's eight missions: A Fiery Assault .. Stopping a Juggernaut


def _src(name):
    with open(os.path.join(SDK, name), encoding="utf-8") as f:
        return f.read()


def _port(key):
    return MP.read_port(os.path.join(PORTS, key + ".port"))


def _wizard(count, ids=MISSIONS, title=XMEN):
    p = MP.profile(title)
    spec = MP.blank_spec(p, "MINI WIZARD")
    spec.starts_on, spec.done_count, spec.done_modes = "completed", count, list(ids)
    return p, spec


# ---- what the runtime can see, per build ---------------------------------------------------------------------------
def test_x_men_sees_its_missions_completed_through_their_audits():
    port = _port("uncanny_xmen_le-0.98")
    done = dict(MP._done_modes(port))
    assert [done[i] for i in MISSIONS] == ["A Fiery Assault", "Mayhem in Midtown", "Bitter Rivalry", "Genosha Under Siege",
                                           "Rescue the Innocent", "Sentinel Facility Raid", "Smuggled Cargo",
                                           "Stopping a Juggernaut"]
    assert 1 not in done and 2 not in done           # the hurry ups keep no COMPLETED audit


def test_cpp_titles_see_every_mode_object_where_the_framework_is_named():
    port = _port("godzilla_le-1.16")
    objs = {int(m) for m in re.findall(r"^data\s+block_obj_(\d+)", open(os.path.join(PORTS, "godzilla_le-1.16.port"),
                                                                     encoding="utf-8").read(), re.M)}
    assert {i for i, _n in MP._done_modes(port)} == objs


def test_plain_c_extra_modes_come_after_the_named_ones():
    port = _port("stranger_things_le-1.13")
    done = MP._done_modes(port)
    extra = [(i, n) for i, n in done if i >= MP.DONE_EXTRA]
    assert extra[:2] == [(128, "Wheres Barb"), (129, "Monster Hunting")]
    assert all(i < MP.DONE_EXTRA for i, _n in done[:len(done) - len(extra)])


def test_the_done_lines_titles():
    assert MF._done_title("WHERES_BARB") == "Wheres Barb"
    assert MF._done_title("ABOB") == "ABOB"
    assert MF._done_title("SHAME_MODE_EP_59_60") == "Shame Mode Ep 59 60"


def test_a_port_with_done_lines_gets_no_second_set():
    text = "text  done_name_0  Wheres Barb\nvalue done_audit_0 292\n"
    assert MF.done_lines(b"", text) == []


def test_every_proven_build_sees_something():
    for key in MP.DONE_PROVEN:
        path = os.path.join(PORTS, key + ".port")
        if os.path.isfile(path):
            assert MP._done_modes(MP.read_port(path)), key


# ---- the mode file ---------------------------------------------------------------------------------------------------
def test_the_form_writes_starts_on_completed_with_its_ids():
    p, spec = _wizard(4)
    if not p.can("done"):
        pytest.skip(p.why_not("done"))
    assert MP.validate(spec) == []
    cfg = MP.runtime_cfg(spec, "mini_wizard").splitlines()
    assert "starts_on      completed 4 3 4 5 6 7 8 9 10" in cfg
    assert not any(ln.startswith("trigger ") for ln in cfg)


def test_every_mode_ticked_writes_no_ids():
    p = MP.profile(XMEN)
    if not p.can("done"):
        pytest.skip(p.why_not("done"))
    _p, spec = _wizard(8, [i for i, _n in p.done_modes])
    assert "starts_on      completed 8" in MP.runtime_cfg(spec, "big_wizard").splitlines()


def test_the_checks():
    p, spec = _wizard(9)
    if not p.can("done"):
        pytest.skip(p.why_not("done"))
    assert "1 to 8 of the game's modes" in " ".join(MP.validate(spec))
    _p, spec = _wizard(1, [3, 99])
    assert "no mode the app sees completed numbered 99" in " ".join(MP.validate(spec))
    _p, spec = _wizard(1, ["A Fiery Assault"])
    assert "list of their numbers" in " ".join(MP.validate(spec))


def test_a_title_that_cannot_starts_on_its_shot():
    _p, spec = _wizard(4)
    p = MP.profile("james_bond_60th_le_1_11")
    assert not p.can("done")
    out, _dropped = MP.retarget(spec, p)
    assert not MP.starts_on_done(out) or "not on" in " ".join(MP.validate(out))


def test_le_and_pro_map_the_modes_by_name():
    p, spec = _wizard(2, [3, 4])
    pro = MP.profile("uncanny_xmen_pro_0_98")
    if not (p.can("done") and pro.can("done")):
        pytest.skip("not proven yet")
    out, _dropped = MP.retarget(spec, pro)
    names = dict(pro.done_modes)
    assert [names[i] for i in out.done_modes] == ["A Fiery Assault", "Mayhem in Midtown"]


def test_mode_file_c_reads_the_line_and_waits_for_nothing_in_its_way():
    mf = _src("mode_file.c")
    for want in ('key_is(how, "completed")', "cfg.start_on_done = 1;", "pm_game_modes_done(cfg.done_ids, cfg.done_n)",
                 "M->done_pend[p] = 1;", "done_in_way(M)", "done_tick();",
                 "slots[k].done_pend[p] = 0, slots[k].done_last[p] = 0;"):
        assert want in mf, want


def test_the_runtime_counts_completions_the_way_the_game_records_them():
    rt = _src("pad_mode_runtime.c")
    for want in ("hook(f, on_done_stop)", "hook(fn(\"audit_add\"), on_done_audit)", "if (place_stopped(obj, p)) return;",
                 "done_arm();", "done_tick();", "can |= PM_CAN_GAME_DONE;", "done_name_%u", "done_audit"):
        assert want in rt, want
    h = _src("pad_mode.h")
    assert "#define PM_CAN_GAME_DONE    0x20000000u" in h
    caps = [int(v, 16) for v in re.findall(r"#define PM_CAN_\w+\s+(0x[0-9a-fA-F]+)u", h)]
    assert len(caps) == len(set(caps))


# ---- blocks ----------------------------------------------------------------------------------------------------------
DONE = [[i, "Mission %d" % i] for i in MISSIONS]


def wizard(count=4, ids=MISSIONS):
    return {"name": "MINI WIZARD", "seconds": 20, "game_modes": "stack",
            "scripts": [{"hat": {"kind": "completed", "count": count, "modes": list(ids)}, "do": [{"op": "start_mode"}]}]}


def test_the_completed_hat_builds_and_says_what_is_wrong():
    assert BM.problems(BM.normalize(wizard()), done=DONE) == []
    assert "none of the game's modes ticked" in " ".join(BM.problems(BM.normalize(wizard(ids=[])), done=DONE))
    assert "1 to 8" in " ".join(BM.problems(BM.normalize(wizard(count=9)), done=DONE))
    assert "does not say it completed" in " ".join(BM.problems(BM.normalize(wizard(ids=[3, 50])), done=DONE))
    assert "cannot tell" in " ".join(BM.problems(BM.normalize(wizard()), done=[]))
    c = BM.to_c(BM.normalize(wizard()), "mini_wizard")
    assert "static const unsigned char DONE_IDS_0[8] = { 3, 4, 5, 6, 7, 8, 9, 10 };" in c
    assert "pm_game_modes_done(DONE_IDS[k], DONE_N[k])" in c


def _cc():
    from tests import test_spike2_mode_roster as R      # its rules (ELF only), and the one place a test run re-points
    return R._cc()


def play(tmp_path, program, *args, slug="mini_wizard"):
    cc = _cc()
    src = tmp_path / (slug + ".c")
    src.write_text(BM.to_c(BM.normalize(program), slug), encoding="utf-8")
    exe = tmp_path / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wextra", "-Wno-unused-parameter", "-I", SDK,
                        "-I", os.path.join(SDK, "examples"), "-o", str(exe),
                        os.path.join(SDK, "examples", "desk_harness.c"), str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "warning" not in r.stderr.lower(), r.stderr
    r = subprocess.run([str(exe), "new_game"] + [str(a) for a in args], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_a_blocks_mode_starts_at_the_fourth_completion(tmp_path):
    out = play(tmp_path, wizard(), "done", 3, "done", 4, "done", 3, "done", 5, "secs", 1, "done", 6, "secs", 1)
    assert "3 of the game's modes completed, 4 wanted" in out
    assert out.count("START") == 1
    assert out.index("done 6") < out.index("START")


def test_a_count_met_waits_for_the_game_mode_in_the_way(tmp_path):
    p = wizard(count=1)
    p["game_modes"] = "give_way"
    out = play(tmp_path, p, "timed", 1, "done", 3, "secs", 2, "timed", 0, "secs", 1)
    assert out.count("START") == 1
    assert out.index("timed 0") < out.index("START")


def test_another_player_and_a_new_game_count_their_own(tmp_path):
    out = play(tmp_path, wizard(count=2), "done", 3, "player", 2, "done", 4, "secs", 1, "new_game", "done", 5, "secs", 1)
    assert "START" not in out


def test_mode_ids_beyond_the_named_ones_are_counted(tmp_path):
    out = play(tmp_path, wizard(count=1, ids=[50]), "done", 50, "secs", 1)
    assert "START" in out
