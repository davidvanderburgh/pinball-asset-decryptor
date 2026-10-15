"""PAD-589: a mode moves Godzilla Premium/LE's building to one of the game's own floors - the mode file's line, the
app's part, the tab and the blocks, at the desk. The runtime's move, limits and put-back are PAD-393's
(tests/test_spike2_stepper.py). Emulator-proven on the stock Premium/LE 1.16 card (``mode_project.BUILDING_PROVEN``).

What is worth failing on:
  * ONLY THE PREMIUM/LE: a Pro has no building on a stepper, so its tab leaves the section out.
  * THE GAME IS NEVER FOUGHT: the building moves only while the game's modes cannot start and its own building
    locks (the port's `text building_rule`) see no shots - the app refuses a mode that asks otherwise.
  * ONCE AS IT STARTS, 1.5 s IN, OR ON ITS SHOT: the line's two forms, through pm_building and nothing else.
"""
import json
import os
import pathlib
import re
import subprocess
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"

LE = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
PRO = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
UNPROVEN = replace(LE, key="godzilla_le_1_16_buildingnot",
                   cannot=tuple(LE.cannot) + MP._building_cannot("godzilla_le-9.99", LE.label,
                                                                   MP.read_port(str(SDK / "ports" /
                                                                                    "godzilla_le-1.16.port"))))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (LE, PRO, UNPROVEN):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _key(spec, key):
    return [line.split(None, 1)[1] for line in MP.runtime_cfg(spec, "bl").splitlines()
            if line and not line.startswith("#") and line.split(None, 1)[0] == key]


def test_only_the_premium_le_can_and_the_rest_say_why():
    assert LE.can("building") and LE.building_rule == "Building Locks"
    assert not PRO.can("building") and "Godzilla Pro 1.16" in PRO.why_not("building")
    assert "building" in PRO.absent and "building" not in LE.absent
    assert not MP.GODZILLA_PRO_1_15.can("building")
    assert "has not yet seen a mode of yours move it in the emulator" in UNPROVEN.why_not("building")
    assert "Building Locks" in dict((n, i) for i, n in LE.game_rules)


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        if "%s-%s" % (p.game_dir, p.version) in MP.BUILDING_PROVEN:
            assert p.can("building"), key
        else:
            assert not p.can("building") and p.label in p.why_not("building"), key


def test_the_line_and_its_refusals():
    assert MP.ModeSpec().building_floor == 0 and not _key(_spec(LE), "building")
    assert _key(_spec(LE, building_floor=3), "building") == ["3"]
    shot = _spec(LE, building_floor=2, building_shot="Maser target")
    assert _key(shot, "building") == ["2 0x%08x" % LE.mask(["Maser target"])]
    assert MP.validate_building(shot, LE) == []
    stack = MP.validate_building(_spec(LE, building_floor=1, game_modes="stack"), LE)
    assert stack == ["The building moves only while the game's modes cannot start: otherwise the game's own "
                     "Building Locks may want it."]
    kept = MP.validate_building(_spec(LE, building_floor=1, keep_rules=["Building Locks"]), LE)
    assert kept == ["The building moves only while Building Locks does not keep counting."]
    assert MP.validate_building(_spec(LE, building_floor=1, keep_rules=["Bridge"]), LE) == []
    assert MP.validate_building(_spec(LE, building_floor=4), LE) == [
        "The building goes to floor 1, 2 or 3 (0 leaves it where it is)."]
    assert MP.validate_building(_spec(LE, building_floor=1, building_shot="Nope"), LE) == [
        "Godzilla Premium/LE 1.16 has no shot called 'Nope' to move the building on."]
    spec = _spec(PRO)
    spec.building_floor = 3
    assert MP.validate_building(spec, PRO) == ["Moving the building is not on Godzilla Pro 1.16 yet (Mode says why)."]
    assert MP.building_lines(spec, PRO) == []
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(stack) == problem_pages(kept) == ["mode"]


def test_a_new_mode_on_a_pro_has_it_off_and_the_fields_round_trip(tmp_path):
    assert MP.blank_spec(PRO).building_floor == 0
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="TOWER", building_floor=2, building_shot="Building"))
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert (back.building_floor, back.building_shot) == (2, "Building")
    assert {"building_floor", "building_shot"} <= set(MP.MODEL_FIELDS)


def test_blocks_move_it_and_are_refused_where_the_game_would_want_it():
    prog = {"name": "TOWER", "seconds": 30, "vars": [], "scripts": [
        {"hat": {"kind": "mode_start"}, "do": [{"op": "start_mode"}, {"op": "building", "floor": "3"}]},
        {"hat": {"kind": "seconds_left", "seconds": 10}, "do": [{"op": "building", "floor": "0"}]}]}
    assert BM.problems(prog, building="Building Locks") == []
    assert BM.problems(dict(prog, game_modes="stack"), building="Building Locks") == [
        "The building moves only while the game's modes cannot start: otherwise the game's own Building Locks "
        "may want it."]
    assert BM.problems(dict(prog, keep_rules=["Building Locks"]), building="Building Locks") == [
        "The building moves only while Building Locks does not keep counting."]
    assert BM.problems(prog, building=False) == [
        "Script 1 moves the building, which a mode cannot do on this card's game.",
        "Script 2 moves the building, which a mode cannot do on this card's game."]
    bad = {**prog, "scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "building", "floor": "9"}]}]}
    assert "Script 1 moves the building: to floor 1, 2 or 3, or back where the game keeps it." in BM.problems(bad)
    c = BM.to_c(BM.normalize(prog), "tower")
    assert "building(3);" in c and "building(0);" in c and "pm_building(floor)" in c


def test_the_blocks_c_builds_with_build_mode_sh(tmp_path):
    import shutil
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    prog = {"name": "TOWER", "seconds": 30, "vars": [], "scripts": [
        {"hat": {"kind": "mode_start"}, "do": [{"op": "building", "floor": "2"}]}]}
    (tmp_path / "tower.c").write_text(BM.to_c(BM.normalize(prog), "tower"), encoding="utf-8")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(tmp_path / "tower.c"), str(SDK / "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_docs_name_the_key_and_the_fields():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("building", "building_floor", "building_shot", "pm_building"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    limits = (SDK / "MODE_LIMITS.md").read_text(encoding="utf-8")
    assert "| Move the building | Not yet |" not in limits
    assert "| Move the building |" in limits


# ---- mode_file.c's line, compiled for the host (the roster test's harness) --------------------
from tests.test_spike2_mode_roster import HARNESS, _cc, weak_stubs  # noqa: E402

BUILDING_STUB = r"""
int pm_building(int floor) { printf("BUILDING %d at %lu\n", floor, now_ms); return 1; }
"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    d = tmp_path_factory.mktemp("building")
    (d / "harness.c").write_text(HARNESS.replace("int main(int argc", BUILDING_STUB + "\nint main(int argc"))
    stubs, _names = weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


BASE = "name TOWER\ntrigger 0x00000100 1\nseconds 30\nshots 0x08000000\naward 1000000\n"


def test_as_it_starts_it_moves_once_after_the_ball_is_clear(harness, tmp_path):
    out = _run(harness, tmp_path, BASE + "building 3\n", "shot", "0x100", "tick", "60", "tick", "60",
               "shot", "0x08000000", "tick", "60")
    assert "unknown key" not in out
    assert '"TOWER": the building to floor 3 as it starts' in out
    moves = re.findall(r"BUILDING (\d) at (\d+)", out)
    assert [m for m, _t in moves] == ["3"]                        # once, not on the scoring shot
    assert "TOWER: the building to floor 3 as it starts - moving" in out
    assert out.index("TICKED 60") < out.index("BUILDING 3")      # not at the start: 1.5 s in (~88 ticks)


def test_on_its_shot_it_moves_on_every_hit_and_not_at_the_start(harness, tmp_path):
    out = _run(harness, tmp_path, BASE + "building 2 0x08000000\n", "shot", "0x100", "tick", "120",
               "shot", "0x08000000", "tick", "200", "shot", "0x08000000")
    assert '"TOWER": the building to floor 2 on its shot' in out
    assert [m for m, _t in re.findall(r"BUILDING (\d) at (\d+)", out)] == ["2", "2"]
    assert "TOWER: the building to floor 2 on its shot - moving" in out


def test_a_word_is_ignored_and_no_line_moves_nothing(harness, tmp_path):
    out = _run(harness, tmp_path, BASE + "building up\n", "shot", "0x100", "tick", "200")
    assert 'building takes a floor - "up" ignored' in out and "BUILDING" not in out
    out = _run(harness, tmp_path, BASE, "shot", "0x100", "tick", "200")
    assert "BUILDING" not in out and "building" not in out


# ---- the Modes tab -------------------------------------------------------------------------
def test_the_tab_offers_it_on_the_premium_le_and_leaves_it_out_on_a_pro(tmp_path):
    from tests.test_webui_modes import _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "le", "godzilla_le-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["form"]["building_floor"] == "(leave it where it is)" and not st["dis"]["building"]
            assert st["profile"]["building_rule"] == "Building Locks"
            assert st["profile"]["building_floors"][0] == "(leave it where it is)" and len(st["profile"]["building_floors"]) == 4
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:building_floor", MP.BUILDING_FLOORS[3])
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("building_floor") == 3)
            w.call("ui.set", "modes", "f:building_shot", "Maser target")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("building_shot") == "Maser target")
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:game_modes", "stack")
            assert _wait(w, lambda: "Building Locks may want it" in w.state("modes")["status"])
            assert w.state("modes")["fix_pages"] == ["mode"]
            w.call("modes.new_blocks_mode", "Tower")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["building_off"] == ""
        proj = _card_project(tmp_path / "pro", "godzilla_pro-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["dis"]["building"] and st["hide"].get("building") and "building" not in st["reasons"]
            w.call("modes.new_blocks_mode", "Tower")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["building_off"].startswith("Not on this game: The app has not found a building that moves on "
                                                 "Godzilla Pro")
            assert "building" in ch["absent"]
    finally:
        preview.enabled = old
