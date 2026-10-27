"""PAD-589: a mode the player starts by picking one of Godzilla's battles on its selection screen - the Modes tab's
"Starts on: the player picking <battle>", written as item 146's ``roster_slot`` line in the trigger's place. The
mode file's claim, pick and give-back are item 146's (tests/test_spike2_mode_roster.py); this is the app's part.
Emulator-proven on Pro 1.15, Premium/LE 1.16 and Pro 1.16 (``mode_project.ROSTER_PROVEN``).

What is worth failing on:
  * ONLY THE PICK STARTS IT: no `trigger` line, `roster_slot <n>` in its place, the slot by its name on the tab.
  * GODZILLA ONLY, AND ONLY WHERE PROVEN: another game has no battle selection, so the tab shows no such start.
"""
import json
import pathlib
import re
from dataclasses import replace

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
GODZILLA = ("Ebirah", "Titanosaurus", "Gigan", "Megalon", "King Ghidorah", "Megalon & Gigan", "King Ghidorah & Gigan")

LE = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
PRO = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
BEATLES = MP.profile_from_port(str(SDK / "ports" / "beatles-1.29.port"))
UNPROVEN = replace(LE, key="godzilla_le_1_16_rosternot", roster=(),
                   cannot=tuple(LE.cannot) + MP._roster_cannot("godzilla_le-9.99", LE.label,
                                                               MP.read_port(str(SDK / "ports" / "godzilla_le-1.16.port"))))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (LE, PRO, BEATLES, UNPROVEN):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "bt").splitlines() if line and not line.startswith("#")]


def test_the_godzilla_builds_can_and_name_their_seven_battles():
    for p in (LE, PRO, MP.GODZILLA_PRO_1_15):
        assert p.can("roster") and p.roster == GODZILLA, p.label
    assert not BEATLES.can("roster") and BEATLES.roster == ()
    assert BEATLES.why_not("roster") == "The Beatles 1.29 has no battle selection a mode of yours can take a place on."
    assert "has not yet seen a mode of yours start from it in the emulator" in UNPROVEN.why_not("roster")


def test_every_shipped_build_gets_a_verdict_with_the_game_named():
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        if "%s-%s" % (p.game_dir, p.version) in MP.ROSTER_PROVEN:
            assert p.can("roster") and p.roster, key
        else:
            assert not p.can("roster") and p.label in p.why_not("roster"), key


def test_the_pick_replaces_the_trigger_line():
    lines = _lines(_spec(PRO, starts_on="battle", roster_slot=2))
    assert "roster_slot    2" in lines and not [line for line in lines if line.startswith("trigger")]
    assert lines.index("roster_slot    2") == 1                    # where the trigger was, after the name
    shot = _lines(_spec(PRO))
    assert [line for line in shot if line.startswith("trigger")] and not [l for l in shot if l.startswith("roster")]
    # a slot left over from a battle start does nothing once it starts on its shot again
    assert not [l for l in _lines(_spec(PRO, roster_slot=2)) if l.startswith("roster")]


def test_its_refusals():
    assert MP.validate(_spec(PRO, starts_on="battle", roster_slot=2)) == []
    assert MP.validate(_spec(PRO, starts_on="battle")) == ["Pick the battle on the selection screen that starts "
                                                           "the mode."]
    assert MP.validate(_spec(PRO, starts_on="battle", roster_slot=7)) == ["Pick the battle on the selection screen "
                                                                          "that starts the mode."]
    assert MP.validate(_spec(BEATLES, starts_on="battle", roster_slot=0)) == [
        "Starting on a battle picked on the selection screen is not on The Beatles 1.29 yet (Mode says why)."]
    assert MP.validate(_spec(PRO, starts_on="nope")) == [
        "A mode starts on a shot, on shots made in order, on one of the game's events, on a battle picked on the "
        "game's selection screen, as a challenge picked in the game's Challenge mode, in the place of one of the "
        "game's own modes, or once some of the game's modes are completed."]                 # PAD-747


def test_it_round_trips_and_a_game_without_a_roster_starts_on_its_shot(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=MP.ModeSpec(name="MOTHRA", starts_on="battle", roster_slot=0))
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert (back.starts_on, back.roster_slot) == ("battle", 0) and MP.starts_on_battle(back)
    spec = _spec(BEATLES, starts_on="battle", roster_slot=0)
    MP._switch_off_what_it_cannot(spec, BEATLES)
    assert (spec.starts_on, spec.roster_slot) == ("shot", -1)


def test_the_docs_say_it_is_in_the_tab():
    limits = (SDK / "MODE_LIMITS.md").read_text(encoding="utf-8")
    assert "Not in the Modes tab yet" not in limits and "the battle slot in the tab" not in limits
    assert "*the player picking* Ebirah" in limits
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    assert re.search(r"\| `roster_slot` \| -1 \|", doc)


# ---- the Modes tab -------------------------------------------------------------------------
def test_the_tab_offers_the_battles_on_godzilla_and_nothing_elsewhere(tmp_path):
    from tests.test_webui_modes import BEATLES_CARD, _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "pro", "godzilla_pro-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["profile"]["roster"] == list(GODZILLA) and st["profile"]["roster_found"]
            assert not st["dis"]["roster"] and st["form"]["starts_kind"] == "shot"
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:roster_slot", "Gigan")
            w.call("ui.set", "modes", "f:starts_kind", "battle")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("starts_on") == "battle")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("roster_slot") == 2)
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:starts_kind", "shot")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("roster_slot") == -1)
        proj = _card_project(tmp_path / "beatles", BEATLES_CARD)
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["profile"]["roster"] == [] and not st["profile"]["roster_found"] and st["dis"]["roster"]
    finally:
        preview.enabled = old
