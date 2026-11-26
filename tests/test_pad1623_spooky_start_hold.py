"""PAD-1623: a Spooky mode as a challenge of its own on the game's START BUTTON HOLD setting.

Halloween and Ultraman have no mode-select menu: holding Start in attract (free play) plays a
one-ball game of the wizard their START BUTTON HOLD setting names.  ``start_hold = yes`` makes a
mode one more choice of that setting; holding Start with it chosen plays one ball of just that
mode (proven on the Spooky rig for both titles, tools/spooky_emu/modes/unity/glue_pc.cs).
"""
import os

import pytest

from pinball_decryptor.plugins.spooky import custom_modes as CM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UNITY = os.path.join(ROOT, "tools", "spooky_emu", "modes", "unity")
HOLD_TITLES = ("ultraman-1.18", "halloween_78-1.18.1")
NO_HOLD_TITLES = ("texas_chainsaw-1.00", "scooby_doo-2025.12.01.09", "evil_dead-2026.07.15")

CHALLENGE = ("name = Ultra Challenge\ntitle = ULTRA CHALLENGE\nstart_hold = yes\n"
             "shots = slingl slingr\npoints = 100000\nseconds = 0\n")


def _check(tmp_path, label, body):
    d = tmp_path / "modes"
    d.mkdir()
    (d / "1_challenge.mode").write_text(body)
    return CM.mk().check_modes(str(d), CM.load_port(label))


@pytest.mark.parametrize("label", HOLD_TITLES)
def test_a_start_hold_mode_needs_no_other_start_rule(tmp_path, label):
    _modes, problems = _check(tmp_path, label, CHALLENGE)
    assert problems == []


@pytest.mark.parametrize("label", NO_HOLD_TITLES)
def test_start_hold_is_refused_where_the_game_has_no_start_hold_game(tmp_path, label):
    _modes, problems = _check(tmp_path, label, CHALLENGE)
    assert any("start_hold is not on" in p for p in problems), problems


@pytest.mark.parametrize("label", NO_HOLD_TITLES)
def test_start_hold_no_is_fine_everywhere(tmp_path, label):
    body = "name = Plain\nstart_hold = no\nstart_score = 1000000\n"
    _modes, problems = _check(tmp_path, label, body)
    assert not any("start_hold" in p for p in problems), problems


def test_the_form_offers_it_only_where_it_runs():
    def keys(label):
        return {k for _g, ks in CM.form_groups(CM.load_port(label)) for k in ks}
    for label in HOLD_TITLES:
        assert "start_hold" in keys(label)
    for label in NO_HOLD_TITLES:
        assert "start_hold" not in keys(label)
    assert CM.LABELS["start_hold"] == "A challenge of its own (hold Start)"
    assert CM.DEFAULTS["start_hold"] == "no"


def test_the_runtime_and_its_prebuilt_builds_carry_it():
    core = open(os.path.join(UNITY, "PadModes.cs"), encoding="utf-8").read()
    glue = open(os.path.join(UNITY, "glue_pc.cs"), encoding="utf-8").read()
    assert 'm.Get("start_hold", "no")' in core
    assert "only it plays" in core
    # the stock wizard out, the one-ball wizard kind of game, the choice kept over a settings reload
    for s in ("GameModes.TheNightUltraBrothers", "theNightUltraBros", "ReferenceEquals(s, holdOf)",
              "pad_start_hold_choice.txt", "public bool evt_ball_started(string msg)"):
        assert s in glue, s
    # .NET keeps string literals UTF-16 in the assembly: the shipped builds are this source's
    needle = "pad_start_hold_choice.txt".encode("utf-16-le")
    for t in ("ultraman", "halloween_78"):
        with open(os.path.join(UNITY, "prebuilt", t, "PadModes.dll"), "rb") as f:
            assert needle in f.read(), t
    with open(os.path.join(UNITY, "prebuilt", "texas_chainsaw", "PadModes.dll"), "rb") as f:
        assert needle not in f.read()       # built -d:TCM: no start-hold game there


def test_help_names_it():
    from pinball_decryptor.webui import help_content as H
    text = "".join("".join(b for b in body if isinstance(b, str)) for _t, body in H.SPOOKY_MODES_HELP
                   if isinstance(body, list))
    assert "A challenge of its own (hold Start)" in text and "START BUTTON HOLD" in text
