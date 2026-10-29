"""Spare switch inputs and driver outputs for modes (PAD-826).

RobF on Pinside: "unmask unused switches and coils". A mode may read a node board input the game has no switch on
(as a shot of its own) and drive a driver output the game never fires (ONE bounded command at a time), for
hardware a mod adds. What is worth failing on:

  * THE LIMITS on a spare output, in their order (pad_mode_runtime.c spare_refusal, lifted verbatim): only the
    running mode, only in a game, powers 1..255, a pulse of 1..1000 ms, 5000 ms a command, 5 s on in any 10 s,
    50 commands in any 10 s.
  * WHAT IS SPARE is the game's own tables, read live: an output with a coil record of the game's is never driven
    (pm_spare_output walks the coil table), an input with a switch id in the switch service's map is never read;
    the switch struct's layout is checked against the game's entries first, over its 32 node blocks (the service's
    mutex follows at +0x1410 = 16 + 32 * 160 - walking 64 read the mutex and beyond, the first proof run's 824 of
    911 bad bits).
  * EVERY END turns a spare output OFF: the mode's end, the ball's, the game's or a tilt.
  * THE PORTS carry the lines spare_io.py finds in each build (the fire and OFF wrappers by their fixed words); when
    the build binaries are here (/var/tmp/pad826/elf, PAD_SPARE_ELF_DIR) every port's lines are the finder's.
  * BLOCKS: When a spare switch closes / Drive a spare output check and compile to pm_spare_shot / pm_spare_drive,
    and only on a build the emulator proved (SPARE_IO_PROVEN).

Emulator-proven separately (docs/plans/mode_spare_io.md; C:/tmp/PAD-826/spare_job.sh, spare_sweep_job.sh).
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"
HWSHIM = ROOT / "tools" / "spike2_emu" / "hwshim.c"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _lift(src, signature):
    """A function's text, verbatim from the runtime (brace-matched from its signature; a prototype is skipped)."""
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


def _host_run(tmp_path, code):
    cc = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
    if not cc:
        pytest.skip("no C compiler on this host")
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-o", str(tmp_path / "t"),
                        str(tmp_path / "t.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout


def test_the_limits_and_their_order(tmp_path):
    src = _src()
    defines = "\n".join(re.findall(r"^#define SPARE_\w+ .*$", src, re.M))
    out = _host_run(tmp_path, "#include <stdio.h>\n" + defines + "\n" + _lift(src, "static const char *spare_refusal(")
                    + r"""
static unsigned long at[SPARE_RING], ms[SPARE_RING];
static void t(const char *label, int run, int game, unsigned pp, unsigned pms, unsigned hp, unsigned hms, unsigned long now)
{
    const char *w = spare_refusal(run, game, pp, pms, hp, hms, at, ms, now);
    printf("%s|%s\n", label, w ? w : "-");
}
int main(void)
{
    unsigned i;
    t("ok", 1, 1, 255, 40, 0, 0, 100000);
    t("not_running", 0, 0, 0, 0, 0, 0, 100000);
    t("no_game", 1, 0, 0, 0, 0, 0, 100000);
    t("no_power", 1, 1, 0, 40, 0, 0, 100000);
    t("power_256", 1, 1, 256, 40, 0, 0, 100000);
    t("hold_256", 1, 1, 255, 40, 256, 10, 100000);
    t("pulse_0", 1, 1, 255, 0, 0, 0, 100000);
    t("pulse_1001", 1, 1, 255, 1001, 0, 0, 100000);
    t("pulse_1000", 1, 1, 255, 1000, 0, 0, 100000);
    t("cmd_5001", 1, 1, 255, 1000, 50, 4001, 100000);
    t("cmd_5000", 1, 1, 255, 1000, 50, 4000, 100000);
    t("hold_ms_no_power", 1, 1, 255, 1000, 0, 60000, 100000);
    at[0] = 95001; ms[0] = 3000; at[1] = 96000; ms[1] = 1500;
    t("budget_4500_plus_501", 1, 1, 255, 501, 0, 0, 100000);
    t("budget_4500_plus_500", 1, 1, 255, 500, 0, 0, 100000);
    t("budget_old_gone", 1, 1, 255, 1000, 100, 2000, 106000);
    for (i = 0; i < SPARE_RING; i++) { at[i] = 99000 + i; ms[i] = 1; }
    t("fifty", 1, 1, 255, 1, 0, 0, 100000);
    return 0;
}
""")
    rows = dict(l.split("|", 1) for l in out.strip().splitlines())
    assert rows["ok"] == "-"
    assert rows["not_running"].startswith("only the running mode")
    assert rows["no_game"].startswith("no game is being played")
    for k in ("no_power", "power_256", "hold_256"):
        assert rows[k].startswith("a power is out of"), k
    assert rows["pulse_0"].startswith("the pulse is out of") and rows["pulse_1001"].startswith("the pulse is out of")
    assert rows["pulse_1000"] == "-"
    assert rows["cmd_5001"].startswith("one command is longer than 5000 ms")
    assert rows["cmd_5000"] == "-"
    assert rows["hold_ms_no_power"] == "-"                       # a hold time with no hold power is no hold
    assert rows["budget_4500_plus_501"].startswith("it would be on more than 5 s")
    assert rows["budget_4500_plus_500"] == "-"
    assert rows["budget_old_gone"] == "-"                        # 10 s later the old commands no longer count
    assert rows["fifty"].startswith("50 commands")


def test_what_is_spare_is_the_games_own_tables():
    src = _src()
    out = _lift(src, "int pm_spare_output(")
    assert "COIL_REC_NODE" in out and "COIL_REC_COIL" in out and "output > 8" in out
    drive = _lift(src, "int pm_spare_drive(")
    assert drive.index("pm_spare_output(") < drive.index('fn("coil_frame")')     # checked before anything is sent
    level = _lift(src, "static int spare_level(")
    assert "+ 28u + 2u * bit" in level and "return -1" in level                  # a switch of the game's: never read
    check = _lift(src, "static unsigned spare_sw_struct(")
    assert "n < SW_NODES" in check and "bad" in check and "spare_sw_ok = -1" in check
    assert re.search(r"^#define SW_NODES 32u", src, re.M)
    assert "+ (unsigned)(n) * 160u" in src


def test_every_end_turns_a_spare_output_off():
    src = _src()
    assert 'spare_outs_off("the mode ended")' in _lift(src, "void pm_end(void)")
    assert 'spare_outs_off("the ball ended")' in src
    tick = _lift(src, "static void spare_tick(")
    assert "!pm_in_game()" in tick and "!running" in tick
    assert "spare_tick();" in _lift(src, "static void on_tick(unsigned *r)")
    assert 'fn("coil_off")' in _lift(src, "static void spare_out_off(")


def _port_lines(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) >= 3 and p[0] in ("site", "data") and p[1] in ("coil_frame", "coil_off", "sw_struct", "coil_table",
                                                                 "coil_count"):
            out[p[1]] = p[2:]
    return out


def test_the_ports_carry_the_wrappers_by_their_words():
    import importlib.util
    spec = importlib.util.spec_from_file_location("spare_io", SDK.parent / "spare_io.py")
    sio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sio)
    full = 0
    for path in sorted(PORTS.glob("*.port")):
        lines = _port_lines(path)
        assert "coil_frame" in lines, path.name                                  # every build has the wrapper
        assert [int(w, 0) for w in lines["coil_frame"][1:3]] == list(sio.FRAME[:2]), path.name
        if "sw_struct" in lines:
            full += 1
            assert [int(w, 0) for w in lines["coil_off"][1:3]] == list(sio.OFF[:2]), path.name
            assert "coil_table" in lines and "coil_count" in lines, path.name
    assert full == 59                                                            # the newer framework's builds


def test_every_port_is_what_the_finder_reads(request):
    elfdir = pathlib.Path(os.environ.get("PAD_SPARE_ELF_DIR") or "/var/tmp/pad826/elf")
    if not elfdir.is_dir():
        pytest.skip("the builds' game binaries are not here (spare_io.py's census reads them)")
    import importlib.util
    spec = importlib.util.spec_from_file_location("spare_io", SDK.parent / "spare_io.py")
    sio = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(sio)
    for path in sorted(PORTS.glob("*.port")):
        elf = elfdir / (path.stem + ".elf")
        if not elf.exists():
            continue
        lines, _notes = sio.lines_for(str(elf), None)
        have = _port_lines(path)
        for line in lines:
            p = line.split()
            assert have.get(p[1]) == p[2:], (path.name, line)


def test_the_emulator_sets_a_spare_input():
    src = HWSHIM.read_text(encoding="utf-8")
    assert '"/dump/spare_in"' in src
    body = _lift(src, "static int sw_scan_bytes(")
    assert "sw_spare_in(nid, out)" in body


GAME = {"in", "out"}


def _program():
    prog = BM.normalize(BM.starter("SPARE BLOCKS", ["Left ramp", "Right ramp"]))
    prog["scripts"].append({"hat": {"kind": "spare_switch", "node": 9, "input": 24, "closed": "low", "when": "any"},
                            "do": [{"op": "start_mode"},
                                   {"op": "spare_drive", "node": 9, "output": 4, "power": 255, "ms": 40,
                                    "hold_power": 128, "hold_ms": 500}]})
    return prog


def test_blocks_check_the_spare_blocks():
    prog = _program()
    assert BM.problems(prog, shots=["Left ramp", "Right ramp"], spare=sorted(GAME)) == []
    off = BM.problems(prog, shots=["Left ramp", "Right ramp"], spare=[])
    assert any("spare switch, which a mode cannot read" in p for p in off)
    assert any("spare output, which a mode cannot do" in p for p in off)
    for field, value, words in (("ms", 1001, "its pulse is 1 to 1000 ms"), ("power", 0, "its power is 1 to 255"),
                                ("output", 9, "output (0 to 8)"), ("hold_ms", 4961, "more than 5000 ms in all")):
        bad = _program()
        bad["scripts"][-1]["do"][1][field] = value
        assert any(words in p for p in BM.problems(bad, shots=["Left ramp", "Right ramp"], spare=sorted(GAME))), field
    bad = _program()
    bad["scripts"][-1]["hat"]["input"] = 64
    assert any("input (0 to 63)" in p for p in BM.problems(bad, shots=["Left ramp", "Right ramp"], spare=sorted(GAME)))


def test_blocks_compile_to_the_sdk_calls():
    c = BM.to_c(_program(), "spare_blocks")
    assert "static const unsigned char SPARE_IN[1][3] = { { 9, 24, 0 } };" in c
    assert "pm_spare_shot(SPARE_IN[k][0], SPARE_IN[k][1], name, SPARE_IN[k][2])" in c
    assert "if (spare_mask[0] && (shot & spare_mask[0])) {" in c
    assert "if (run.on) pm_spare_drive(9u, 4u, 255u, 40u, 128u, 500u);" in c
    on_shot = c[c.index("static void on_shot("):]
    assert on_shot.index("spare_mask[0]") < on_shot.index("if (!(shot & named)) return;")   # not a named shot
    assert "spare_ask();" in c[c.index("static void on_tick("):]


def test_only_a_proven_build_offers_them():
    profiles = MP.profiles()
    assert profiles["godzilla_pro_1_16"].spare == ("in", "out")
    for p in profiles.values():
        key = "%s-%s" % (p.key.rsplit("_", 2)[0], ".".join(p.key.rsplit("_", 2)[1:]))
        if key not in MP.SPARE_IO_PROVEN:
            assert p.spare == (), p.key
    assert BM.card_checks(profiles["godzilla_pro_1_16"])["spare"] == ["in", "out"]
