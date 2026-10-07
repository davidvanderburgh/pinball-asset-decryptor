"""PAD-228: the cabinet buttons in a mode - the Action button and the flipper buttons as shots from the
framework's switch drain, the Action button's light as an insert tied to its shot, and a multiball whose
balls come on a shot (`multiball_on`) instead of at the start. Desk parts; the emulator proof is
recorded in ``mode_project.SWITCH_EDGE_PROVEN``.
"""

import pathlib
import re
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
GODZILLA = ("godzilla_pro-1.15", "godzilla_pro-1.16", "godzilla_le-1.16")
BUTTONS = {34: "Action button", 60: "Left flipper button", 59: "Right flipper button"}

#: Godzilla Pro 1.15 as a proven multiball build would see it
CAN = replace(MP.GODZILLA_PRO_1_15, key="godzilla_pro_1_15_btntest",
              cannot=tuple(c for c in MP.GODZILLA_PRO_1_15.cannot if c[0] != "multiball"))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    monkeypatch.setitem(MP.PROFILES, CAN.key, CAN)


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "btn").splitlines() if not line.startswith("#")]


def _key(lines, key):
    return [line.split(None, 1)[1] for line in lines if line.split(None, 1)[0] == key]


# ---- the ports ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("name", GODZILLA)
def test_the_buttons_are_switch_shots_on_bits_no_shot_uses(name):
    port = MP.read_port(str(SDK / "ports" / (name + ".port")))
    assert {"switch_edge", "switch_drain"} <= set(port["site"])
    assert {"switch_records", "switch_count", "mode_mask"} <= set(port["data"])
    internal = {n.strip() for n in port["text"].get("internal_shots", "").split(",") if n.strip()}
    mapped = {sw: (mask, n) for sw, mask, n in port["switch"] if n not in internal}
    assert {sw: n for sw, (_m, n) in mapped.items()} == BUTTONS
    masks = [m for m, _n in mapped.values()]
    assert all(m and not m & (m - 1) for m in masks) and len(set(masks)) == 3
    shot_bits = 0
    for _n, m in port["shot"]:
        shot_bits |= m
    assert not shot_bits & sum(masks), "a button shares a bit with a shot the rules send"
    # the tab offers them, and says so until the build is proven
    p = MP.profile_from_port(str(SDK / "ports" / (name + ".port")))
    assert set(BUTTONS.values()) <= {n for n, _m in p.shots}
    assert set(p.switch_shots) == set(BUTTONS.values())
    assert not internal & {n for n, _m in p.shots}                      # PAD-416: the trough is code's, not the tab's
    assert bool(p.switch_shots_note) == (name not in MP.SWITCH_EDGE_PROVEN)


@pytest.mark.parametrize("name", GODZILLA)
def test_the_action_buttons_light_is_tied_to_its_shot(name):
    text = (SDK / "ports" / (name + ".port")).read_text(encoding="utf-8")
    lamp = re.search(r"^lamp\s+(\S+)\s+(\S+)\s+ACTION BUTTON\b", text, re.M)
    assert lamp, "no ACTION BUTTON lamp line"
    assert lamp.group(1) == "282,283,284"                  # LOCKDOWN BUTTON-R, -G, -B in the light table
    action = re.search(r"^switch 34\s+(\S+)", text, re.M).group(1)
    assert int(lamp.group(2), 16) == int(action, 16)


def test_the_hand_kept_profile_matches_its_port():
    p = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.15.port"))
    assert dict(MP.GODZILLA_PRO_1_15.shots) == dict(p.shots)
    assert MP.GODZILLA_PRO_1_15.switch_shots == p.switch_shots


# ---- a multiball on a shot ----------------------------------------------------------------------------
def test_the_multiball_waits_for_its_shot_only_when_one_is_picked():
    spec = MP.ModeSpec(title=CAN.key, multiball=True, balls=3, ball_save=10)
    assert not _key(_lines(spec), "multiball_on")
    spec.multiball_on_shot = "Action button"
    lines = _lines(spec)
    assert _key(lines, "multiball") == ["3 10"]
    assert _key(lines, "multiball_on") == ["0x1000000000000000"]
    # not a multiball: nothing, whatever the field says
    spec.multiball = False
    assert not _key(_lines(spec), "multiball_on")


@pytest.mark.parametrize("field, value, words", [
    ("multiball_on_shot", "Warp core", "no shot called 'Warp core' to start the multiball on"),
    ("seconds", 0, "needs Runs for"),
])
def test_validate_names_a_multiball_on_shot_problem(field, value, words):
    spec = MP.ModeSpec(title=CAN.key, multiball=True, multiball_on_shot="Action button")
    assert MP.validate(spec) == []
    setattr(spec, field, value)
    problems = MP.validate(spec)
    assert any(words in s for s in problems), problems
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(problems) == ["mode"] * len(problems)


def test_the_field_round_trips_and_retarget_drops_a_shot_the_title_lacks(tmp_path):
    spec = MP.ModeSpec(name="PRESS NOW", multiball=True, multiball_on_shot="Action button")
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=spec)
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert back.multiball_on_shot == "Action button"
    assert MP.ModeSpec.from_json({"format": 1, "name": "OLD", "seconds": 30}).multiball_on_shot == ""
    jaws = MP.profile_for_card("jaws_le", "1.02.0")
    out, dropped = MP.retarget(spec, jaws)
    assert out.multiball_on_shot == "" and "Action button" in dropped
    le = MP.profile_for_card("godzilla_le", "1.16.0")
    out, dropped = MP.retarget(spec, le)
    assert out.multiball_on_shot == "Action button" and "Action button" not in dropped


def test_the_interpreter_takes_multiball_on_and_lights_its_shot():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    body = src[src.index("static int multiball_line("):]
    body = body[:body.index("\n}\n")]
    assert set(re.findall(r'key_is\(line, "([a-z_]+)"\)', body)) == {"multiball", "add_ball", "multiball_on"}
    # the start does not serve the balls while it waits; the shot does, and stops the clock
    start = src[src.index("static void mode_start("):]
    start = start[:start.index("\n}\n")]
    assert "run.mball_wait = 1;" in start
    on = src[src.index("static void multiball_on_shot("):]
    on = on[:on.index("\n}\n")]
    assert "pm_multiball_start(cfg.mball_balls, cfg.mball_save_s)" in on and "run.no_clock = 1;" in on
    # "light the shots that score" lights the shot the multiball waits for
    assert "pm_lamp_shot(scoring_bits(M) | (cfg.mball_balls ? cfg.mball_on_bits : 0)" in src
