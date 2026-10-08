"""Item 167: a multiball of the mode's own - the model, the generated mode file, the interpreter's
keys and the runtime's capability, at the desk. The emulator proof (a mode file's `multiball` line
serving balls) is recorded in ``mode_project.MULTIBALL_PROVEN``; until a build is there the tab
greys Multiball and ``validate`` refuses a multiball on it.
"""

import pathlib
import re
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"

#: Godzilla Pro 1.15 as a proven build would see it: the port names the call, and the tab offers it
CAN = replace(MP.GODZILLA_PRO_1_15, key="godzilla_pro_1_15_mbtest",
              cannot=tuple(c for c in MP.GODZILLA_PRO_1_15.cannot if c[0] != "multiball"))
CANNOT = replace(MP.GODZILLA_PRO_1_15, key="godzilla_pro_1_15_mbnot",
                 cannot=(("multiball", "Not on Godzilla Pro 1.15 yet (a test)."),))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    monkeypatch.setitem(MP.PROFILES, CAN.key, CAN)
    monkeypatch.setitem(MP.PROFILES, CANNOT.key, CANNOT)


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "mb").splitlines() if not line.startswith("#")]


def _key(lines, key):
    return [line.split(None, 1)[1] for line in lines if line.split(None, 1)[0] == key]


def test_the_part_and_its_needs_are_what_the_runtime_arms_with():
    assert "multiball" in MP.PARTS
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    arm = src[src.index("static void multiball_arm(void)"):]
    arm = arm[:arm.index("\n}\n")]
    names = set(re.findall(r'"([a-z_]+)"', arm.split("can |= PM_CAN_MULTIBALL")[0]))
    assert names == set(MP.MULTIBALL_NEEDS) == {"multiball_serve", "balls_in_play"}
    header = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    for call in ("pm_multiball_start", "pm_multiball_add", "pm_balls_in_play"):
        assert re.search(r"\bint %s\(" % call, header), call
    assert "PM_CAN_MULTIBALL" in header


def test_every_shipped_port_names_the_serve_call_and_the_count():
    for path in sorted((SDK / "ports").glob("*.port")):
        port = MP.read_port(str(path))
        missing = [n for n in MP.MULTIBALL_NEEDS if n not in port["site"]]
        assert not missing, "%s lacks %s" % (path.name, missing)
        # the site's words are the build's, never a person's: two non-zero instruction words
        addr, w0, w1 = port["site"]["multiball_serve"]
        assert addr and w0 and w1, path.name


def test_a_multiball_is_greyed_with_a_reason_until_its_build_is_proven():
    for key, p in MP.profiles(MP.PORTS_DIR).items():      # the shipped ports, not the fixture's two
        build = "%s-%s" % (p.game_dir, p.version)
        if build in MP.MULTIBALL_PROVEN:
            assert p.can("multiball"), key
        else:
            assert not p.can("multiball") and p.label in p.why_not("multiball"), key
            assert "not yet seen a mode of yours start one" in p.why_not("multiball"), key


def test_nothing_is_written_unless_the_mode_is_a_multiball_on_a_title_that_can():
    spec = MP.ModeSpec(title=CAN.key)
    plain = _lines(spec)
    assert not _key(plain, "multiball") and not _key(plain, "add_ball")
    spec = MP.ModeSpec(title=CAN.key, multiball=True, balls=4, ball_save=20)
    on = _lines(spec)
    assert _key(on, "multiball") == ["4 20"] and not _key(on, "add_ball")
    assert [line for line in on if not line.startswith("multiball")] == plain
    spec.add_ball_shot, spec.add_ball_max = "Maser target", 2
    assert _key(_lines(spec), "add_ball") == ["0x08000000 2"]
    # a title that cannot: validate refuses it, naming the Mode page's reason, and nothing builds
    spec.title = CANNOT.key
    assert MP.validate(spec) == MP.validate_multiball(spec, CANNOT) == [
        "A multiball of the mode's own is not on Godzilla Pro 1.15 yet (Mode says why)."]
    assert MP.multiball_lines(spec, CANNOT) == []
    with pytest.raises(MP.ModeProjectError):
        MP.runtime_cfg(spec, "mb")


def test_a_multiball_may_have_no_clock_and_a_plain_mode_may_not():
    spec = MP.ModeSpec(title=CAN.key, multiball=True, seconds=0)
    assert MP.validate(spec) == []
    assert "It has to run for at least a second." in MP.validate(MP.ModeSpec(title=CAN.key, seconds=0))
    # the generated file says so (the interpreter's `seconds 0` is no clock)
    assert "seconds        0" in "\n".join(_lines(spec))


@pytest.mark.parametrize("field, value, words", [
    ("balls", 1, "2 to 6 balls"),
    ("balls", 7, "2 to 6 balls"),
    ("balls", "three", "2 to 6 balls"),
    ("ball_save", -1, "0 to 60 seconds"),
    ("ball_save", 61, "0 to 60 seconds"),
    ("add_ball_shot", "Warp core", "no shot called 'Warp core' to add a ball"),
    ("add_ball_max", 0, "1 to 6 times"),
    ("add_ball_max", 9, "1 to 6 times"),
])
def test_validate_names_every_multiball_problem(field, value, words):
    spec = MP.ModeSpec(title=CAN.key, multiball=True, add_ball_shot="Maser target")
    setattr(spec, field, value)
    problems = MP.validate(spec)
    assert any(words in s for s in problems), problems
    # the tab files each under the Mode page
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(problems) == ["mode"] * len(problems)


def test_the_fields_round_trip_and_an_older_file_is_not_a_multiball(tmp_path):
    spec = MP.ModeSpec(name="TWIN TERROR", multiball=True, balls=2, ball_save=0,
                       add_ball_shot="Building", add_ball_max=3, seconds=0)
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=spec)
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    for f in ("multiball", "balls", "ball_save", "add_ball_shot", "add_ball_max", "seconds"):
        assert getattr(back, f) == getattr(spec, f), f
    old = MP.ModeSpec.from_json({"format": 1, "name": "OLD", "seconds": 30})
    assert old.multiball is False and old.balls == 3 and old.ball_save == 10
    assert old.add_ball_shot == "" and old.add_ball_max == 1


def test_retarget_drops_an_add_a_ball_shot_the_title_lacks():
    spec = MP.ModeSpec(multiball=True, add_ball_shot="Maser target", scoring_shots=["Left ramp"])
    jaws = MP.profile_for_card("jaws_le", "1.02.0")
    out, dropped = MP.retarget(spec, jaws)
    assert out.multiball is True and out.add_ball_shot == "" and "Maser target" in dropped
    # a title with the shot keeps it
    le = MP.profile_for_card("godzilla_le", "1.16.0")
    out, dropped = MP.retarget(spec, le)
    assert out.add_ball_shot == "Maser target" and "Maser target" not in dropped


def test_the_interpreter_takes_the_keys_and_the_doc_names_them():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "if (multiball_line(M, line)) return;" in src
    body = src[src.index("static int multiball_line("):]
    body = body[:body.index("\n}\n")]
    assert set(re.findall(r'key_is\(line, "([a-z_]+)"\)', body)) == {"multiball", "add_ball", "multiball_on"}  # PAD-228
    # a multiball with no clock is valid; a plain mode still needs its seconds (PAD-436 named the
    # rule runs(), which the game's own mini-wizard meets too)
    assert "return cfg.seconds || cfg.mball_balls || cfg.wizard[0];" in src
    assert "cfg.valid = runs(M) && cfg.trigger_count;" in src
    assert "cfg.valid = runs(M) && cfg.start_event >= 0;" in src
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("multiball", "add_ball", "pm_multiball_start", "pm_multiball_add", "pm_balls_in_play",
                 "balls", "ball_save", "add_ball_shot", "add_ball_max"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "## A multiball of your own" in sdk


def test_a_blank_mode_on_a_title_that_cannot_is_not_a_multiball():
    spec = MP.blank_spec(CANNOT)
    assert spec.multiball is False and MP.validate(spec) == []
    # and on one that can, it is not one either until the person ticks it (the same bytes as before)
    assert MP.blank_spec(CAN).multiball is False
