"""PAD-225: a ball save when a mode starts, with no multiball - the model, the generated mode file,
the interpreter's key and the runtime call, at the desk. The emulator proof (a mode file's
`ball_save` line: the drain inside it served back, the one after it ending the ball) is recorded in
``mode_project.BALL_SAVE_PROVEN``; until a build is there the tab greys Ball save and ``validate``
refuses one on it.
"""

import pathlib
import re
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"

#: Godzilla Pro 1.15 as a proven build would see it, and as one that cannot
CAN = replace(MP.GODZILLA_PRO_1_15, key="godzilla_pro_1_15_bstest",
              cannot=tuple(c for c in MP.GODZILLA_PRO_1_15.cannot if c[0] not in ("multiball", "ball_save")))
CANNOT = replace(MP.GODZILLA_PRO_1_15, key="godzilla_pro_1_15_bsnot",
                 cannot=(("ball_save", "Not on Godzilla Pro 1.15 yet (a test)."),))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    monkeypatch.setitem(MP.PROFILES, CAN.key, CAN)
    monkeypatch.setitem(MP.PROFILES, CANNOT.key, CANNOT)


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "bs").splitlines() if not line.startswith("#")]


def _key(lines, key):
    return [line.split(None, 1)[1] for line in lines if line.split(None, 1)[0] == key]


def test_a_mode_has_no_ball_save_until_one_is_set():
    spec = MP.ModeSpec(title=CAN.key)
    assert spec.start_ball_save == 0 and not _key(_lines(spec), "ball_save")
    assert MP.blank_spec(CAN).start_ball_save == 0
    old = MP.ModeSpec.from_json({"format": 1, "name": "OLD", "seconds": 30})
    assert old.start_ball_save == 0


def test_the_line_is_written_only_without_a_multiball_on_a_title_that_can():
    plain = _lines(MP.ModeSpec(title=CAN.key))
    spec = MP.ModeSpec(title=CAN.key, start_ball_save=15)
    on = _lines(spec)
    assert _key(on, "ball_save") == ["15"]
    assert [line for line in on if not line.startswith("ball_save")] == plain
    # a multiball keeps its own ball save: no second line
    spec.multiball = True
    lines = _lines(spec)
    assert not _key(lines, "ball_save") and _key(lines, "multiball") == ["3 10"]
    # a title that cannot: refused with the Mode page's reason, and nothing builds
    spec = MP.ModeSpec(title=CANNOT.key, start_ball_save=15)
    assert MP.validate(spec) == MP.validate_ball_save(spec, CANNOT) == [
        "A ball save of the mode's own is not on Godzilla Pro 1.15 yet (Mode says why)."]
    assert MP.ball_save_lines(spec, CANNOT) == []
    with pytest.raises(MP.ModeProjectError):
        MP.runtime_cfg(spec, "bs")
    # and a blank mode there starts without one
    assert MP.blank_spec(CANNOT).start_ball_save == 0


@pytest.mark.parametrize("value", [-1, 61, "ten"])
def test_validate_names_a_bad_ball_save(value):
    problems = MP.validate(MP.ModeSpec(title=CAN.key, start_ball_save=value))
    assert "The ball save when the mode starts is 1 to 60 seconds." in problems
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(problems) == ["mode"] * len(problems)


def test_the_field_round_trips(tmp_path):
    spec = MP.ModeSpec(name="SAVED", start_ball_save=20)
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=spec)
    assert MP.load(str(project / "modes" / slug / "mode.json")).start_ball_save == 20


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        build = "%s-%s" % (p.game_dir, p.version)
        if build in MP.BALL_SAVE_PROVEN:
            assert p.can("ball_save"), key
        else:
            assert not p.can("ball_save") and p.label in p.why_not("ball_save"), key
    # the same call: never proven without it - but for Munsters Pro 1.28 (PAD-420), whose serve worked (its ball save
    # is proven) while its multiball proof fails on the game's own end of it: two drains of four left 2 in play, then 0
    assert MP.BALL_SAVE_PROVEN - MP.MULTIBALL_PROVEN <= {"munsters_pro-1.28"}


def test_the_interpreter_takes_the_key_and_the_runtime_asks_for_no_more_balls():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert "if (ball_save_line(M, line)) return;" in src
    start = src[src.index("static void mode_start("):]
    start = start[:start.index("\n}\n")]
    # taken only without a multiball, and a refusal does not stop the mode
    assert "run.saving = !cfg.mball_balls && cfg.ball_save_s && pm_ball_save(cfg.ball_save_s);" in start
    header = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    assert re.search(r"\bint pm_ball_save\(unsigned seconds\);", header)
    rt = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = rt[rt.index("int pm_ball_save(unsigned seconds)"):]
    body = body[:body.index("\n}\n")]
    # the game's own one-ball saves: serve until the balls in play NOW are in play, with the save in ticks
    assert 'fn("multiball_serve"))' in body and "((unsigned)now, 0, seconds * 62u, arg3, 0, 0)" in body
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("ball_save", "pm_ball_save", "start_ball_save"):
        assert re.search(r"`%s(?:[ (][^`]*)?`" % re.escape(name), doc), name
    assert "## A ball save of your own" in (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
