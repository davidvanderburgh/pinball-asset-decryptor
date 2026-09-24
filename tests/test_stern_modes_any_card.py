"""A card whose game build cannot run a mode: a Write leaves the modes out and writes the rest.

Desk tests (no card image, no emulator): the engine's build runs on the stand-in card of
tests/test_stern_audio_grow.py, the project names a card by its file name, and the
preview switch is stood in by ``mode_write.preview_on`` / ``engine._mode_family_on``.
"""

import json
import os

import pytest

from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import engine
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_tryit as MT
from pinball_decryptor.plugins.stern import mode_write as MW

#: a Spike 2 build no port exists for (none shipped, and the title cache is emptied below)
NO_PORT_CARD = "mando_le-1_40_0.Release.8G.sdcard.raw"


@pytest.fixture(autouse=True)
def _no_title_cache(monkeypatch, tmp_path):
    """Ports worked out on this machine live under PAD_TITLE_CACHE: never David's."""
    monkeypatch.setenv("PAD_TITLE_CACHE", str(tmp_path / "titles"))


def _name_card(project, image_name):
    os.makedirs(str(project), exist_ok=True)
    with open(os.path.join(str(project), ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": os.path.join(str(project), image_name),
                   "input_name": image_name}, f)


def _a_mode(project, name="KAIJU RUSH"):
    spec = dict(MP.example_specs())[name]
    MP.new_mode(str(project), name, spec)


# ---- the words -----------------------------------------------------------------------------
def test_every_latest_build_has_a_name():
    # one label per build: the version as a port spells it (major.minor, a patch level kept)
    assert MP.title_label("beatles", "1.29.0") == "The Beatles 1.29"
    assert MP.title_label("beatles", "1_29_0") == MP.title_label("beatles", "1.29")
    assert MP.title_label("godzilla_pro", "1.15.1") == "Godzilla Pro 1.15.1"
    assert MP.title_label("elvira3", "1.13") == "Elvira 1.13"
    assert MP.title_label("james_bond_60th_le", "1.11") == "James Bond 60th LE 1.11"
    assert MP.title_label("uncanny_xmen_le") == "Uncanny X-Men LE"
    assert MP.title_label("star_wars_elg") == "Star Wars ELG"
    assert MP.title_label("godzilla_le", "1.16") == "Godzilla Premium/LE 1.16"
    assert MP.title_label("turtles_pro", "1.59") == "TMNT Pro 1.59"
    # a directory the app has never seen is still written out, not title-cased blindly
    assert MP.title_label("house_of_the_dead_le") == "House of the Dead LE"


def test_no_port_words_say_what_is_missing():
    words = MP.no_port_words("The Beatles 1.29", ("shot_dispatch", "score_add", "scores"))
    assert words == ("Modes of your own can't be made for The Beatles 1.29 yet: the app could "
                     "not find where the game hands out its shots, how the game adds points "
                     "and the players' scores in its program.")
    assert "—" not in words
    # nothing tried yet (the contract's placeholder), or nothing said: the general help
    assert MP.no_port_words("X 1.0", ("no port for this build",)) == MP.NO_PORT_HELP % "X 1.0"
    assert MP.no_port_words("X 1.0") == MP.NO_PORT_HELP % "X 1.0"


# ---- no default game -------------------------------------------------------------------------
def test_nothing_falls_back_to_godzilla(tmp_path):
    bare = str(tmp_path / "bare")
    os.makedirs(bare)
    assert CM.profile_for(bare) is None
    assert MT.project_title(bare) is None
    assert MW.card_refusal(bare) == ""                  # no card: nothing to refuse for


def test_card_refusal_names_the_build(tmp_path):
    proj = tmp_path / "mando"
    _name_card(proj, NO_PORT_CARD)
    why = MW.card_refusal(str(proj))
    assert why == MP.no_port_words("The Mandalorian LE 1.40")
    gz = tmp_path / "gz"
    _name_card(gz, "godzilla_pro-1_15_0.raw")
    assert MW.card_refusal(str(gz)) == ""


def test_the_change_scan_promises_nothing_to_a_card_with_no_port(tmp_path):
    proj = tmp_path / "mando"
    _name_card(proj, NO_PORT_CARD)
    _a_mode(proj)
    lines = MW.pending_lines(str(proj))
    assert lines and all("not put on the card" in ln for ln in lines)
    assert not any("its own screen" in ln for ln in lines)


def test_a_code_mode_with_no_game_is_not_promised(tmp_path):
    proj = str(tmp_path / "bare")
    folder = MP.mode_folder(proj, "laser")
    os.makedirs(folder)
    with open(os.path.join(folder, "laser.c"), "w") as f:
        f.write('#define MODE_NAME          "LASER"\n')
    lines = MW.pending_lines(proj)
    assert lines and lines[0].startswith("LASER (code mode): not put on the card. ")
    assert CM.NO_TITLE in lines[0]


def test_a_port_worked_out_on_this_machine_is_the_cards_port_everywhere(tmp_path):
    """A port derived on this machine (in the title cache's ports folder) is the card's port
    for the tab's lookup, Write's refusal and a mode's title, in a later session too."""
    from pinball_decryptor.plugins.stern import port_derive
    from tests.test_webui_modes import BEATLES_CARD, BEATLES_PORT
    with open(os.path.join(port_derive.user_ports_dir(), "beatles-1.29.port"), "w",
              encoding="utf-8") as f:
        f.write(BEATLES_PORT)
    prof = MP.profile_for_card("beatles", "1.29.0")
    assert prof is not None and prof.key == "beatles_1_29"
    assert MP.profile("beatles_1_29").label == "The Beatles 1.29"
    proj = tmp_path / "beatles"
    _name_card(proj, BEATLES_CARD)
    assert MW.card_refusal(str(proj)) == ""
    MP.new_mode(str(proj), "HELP", MP.blank_spec(prof))
    found, _broken = MP.list_modes(str(proj))
    assert [s.title for _slug, s in MW.card_modes(str(proj), found)] == ["beatles_1_29"]


def test_a_card_that_carries_no_mode_keeps_the_update_in_place(tmp_path, monkeypatch):
    """The Write leaves a no-port card's modes out, so they do not force a whole build."""
    from pinball_decryptor import __version__
    monkeypatch.setattr(engine, "_mode_family_on", lambda: True)
    monkeypatch.setattr(MW, "enabled", lambda: True)
    monkeypatch.setattr(engine, "_stamp_matches", lambda s, p: True)
    orig, out = tmp_path / "o.raw", tmp_path / "b.raw"
    prev = {"version": engine.BUILD_MANIFEST_VERSION, "app": __version__, "complete": True,
            "stock": {"path": os.path.abspath(str(orig))}}
    proj = tmp_path / "mando"
    _name_card(proj, NO_PORT_CARD)
    _a_mode(proj)
    prev["assets"] = str(proj)
    assert engine.build_update_reason(prev, orig, out, str(proj)) is None
    gz = tmp_path / "gz"
    _name_card(gz, "godzilla_pro-1_15_0.raw")
    _a_mode(gz)
    prev["assets"] = str(gz)
    assert engine.build_update_reason(prev, orig, out, str(gz)) == \
        "a build that carries modes is built whole"


# ---- the engine's Write ----------------------------------------------------------------------
def _engine_run(monkeypatch, tmp_path, with_modes):
    from tests.test_stern_audio_grow import BLOCK, _capture, _edits, _grow_card, _params, _run
    monkeypatch.setenv("PAD_STERN_AUDIO_GROW", "1")
    tmp_path.mkdir(parents=True, exist_ok=True)
    params = _params(4)
    grown = [dict(p) for p in params]
    grown[0].update(body_off=0x40000, length=2 * 44100 + BLOCK, grown=True, shadows=4)
    _grow_card(monkeypatch, tmp_path, params, grown_rows=grown)
    assets, _wav = _edits(tmp_path, 2.0)
    _name_card(assets, NO_PORT_CARD)
    if with_modes:
        _a_mode(assets)
    msgs, log = _capture()
    writes, counts, plan, _m, _v = _run(monkeypatch, assets, params, 0x40000, log)
    engine._rmtree_grow_plan(plan)
    return writes, counts, msgs


def test_a_write_leaves_the_modes_out_and_writes_the_rest(monkeypatch, tmp_path):
    """Preview on, a project with a mode on a card whose build has no port: the Write says
    why the modes are left out and writes the project's other edits (it used to refuse the
    whole Write: "Nothing was written")."""
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    monkeypatch.setattr(engine, "_mode_family_on", lambda: True)
    monkeypatch.setattr(MW, "gate", lambda *a, **k: (True, ""))

    def never(*a, **k):
        raise AssertionError("the modes were built for a card with no port")
    monkeypatch.setattr(MW, "card_modes", never)
    writes, counts, msgs = _engine_run(monkeypatch, tmp_path, with_modes=True)
    assert writes is not None and counts[0] == 1          # the sound edit is written
    said = [m for _l, m in msgs if "left out of this build" in m]
    assert said and "The Mandalorian LE 1.40" in said[0]
    assert [lvl for lvl, m in msgs if m == said[0]] == ["warning"]


def test_with_the_switch_off_a_write_takes_mains_path(monkeypatch, tmp_path):
    """No preview code: the modes are not even read, and the Write is the one a project
    without them makes (same writes, same counts)."""
    monkeypatch.setattr(MW, "preview_on", lambda: False)
    monkeypatch.setattr(engine, "_mode_family_on", lambda: False)
    for name in ("card_refusal", "card_modes", "project_modes", "code_mode_list"):
        def boom(*a, _n=name, **k):
            raise AssertionError("%s was called with the switch off" % _n)
        monkeypatch.setattr(MW, name, boom)
    with_modes = _engine_run(monkeypatch, tmp_path / "a", with_modes=True)
    without = _engine_run(monkeypatch, tmp_path / "b", with_modes=False)
    assert with_modes[0] == without[0]
    assert with_modes[1] == without[1]
    words = " ".join(m for _l, m in with_modes[2]).lower()
    assert "mandalorian" not in words and "port" not in words.replace("report", "")


def test_a_write_asks_whether_a_port_that_never_ran_may_go_on_a_real_card(monkeypatch, tmp_path):
    """Review M6: the engine's Write asks card_refusal with real_card=True (a card or an image),
    so a port derived on this machine that no Try it has run leaves the modes out; Try it's set
    for the emulator (write_overrides, boot_screen=False) asks with real_card=False."""
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    monkeypatch.setattr(engine, "_mode_family_on", lambda: True)
    monkeypatch.setattr(MW, "gate", lambda *a, **k: (True, ""))
    asked = []

    def refusal(project, probe=True, real_card=False):
        asked.append(real_card)
        return MW.try_it_first_words("The Mandalorian LE 1.40")
    monkeypatch.setattr(MW, "card_refusal", refusal)
    writes, counts, msgs = _engine_run(monkeypatch, tmp_path, with_modes=True)
    assert asked and set(asked) == {True}
    assert writes is not None and counts[0] == 1          # the rest is written
    said = [m for _l, m in msgs if "left out of this build" in m]
    assert said and "Press Try it once first" in said[0]
    src = open(engine.__file__, encoding="utf-8").read()
    assert src.count("_MW.card_refusal(assets_dir, real_card=boot_screen)") == 2
