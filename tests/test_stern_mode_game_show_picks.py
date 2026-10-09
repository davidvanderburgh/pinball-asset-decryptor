"""PAD-418: the Modes tab picks the game's own light shows (PAD-411's pm_game_show_named) for a mode's start and end,
from the form and from blocks.

What is worth failing on:
  * THE SHOWS ARE THE PORT'S: the profile lists the port's show lines by name, kind and length, as the runtime
    arms them; a title whose port names none cannot, and says why (the Pro, every other title).
  * A NAME IS CHECKED: a show the title does not have is refused, named, on the Lights page; going to the Pro
    leaves the shows out (kept for the way back), going to another game drops one it does not have.
  * THE MODE FILE PLAYS THEM: `show_start` as it starts, `show_end` as it ends - never as the ball drains (the
    game stops its own shows then).
  * THE BLOCK PLAYS ONE BY NAME through pm_game_show_named, refused where the game has none.
"""
import json
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
LE = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
PRO = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
OLD_PRO = MP.GODZILLA_PRO_1_15                  # a port that names none of the game's shows


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (LE, PRO):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _key(spec, key):
    return [line.split(None, 1)[1] for line in MP.runtime_cfg(spec, "ls").splitlines()
            if line and not line.startswith("#") and line.split(None, 1)[0] == key]


# ---- the profile -----------------------------------------------------------------------------
def test_the_profile_lists_the_ports_shows_in_order():
    text = (SDK / "ports" / "godzilla_le-1.16.port").read_text(encoding="utf-8")
    names = [re.search(r"^text show_name_%d\s+(.+?)\s*$" % n, text, re.M).group(1)
             for n in range(1, len(LE.game_shows) + 1)]
    assert [n for n, _k, _s in LE.game_shows] == names and len(names) == 10
    assert dict((n, (k, s)) for n, k, s in LE.game_shows)["Strobe burst"] == ("flashy", 6)
    assert dict((n, (k, s)) for n, k, s in LE.game_shows)["Blue fade"] == ("subdued", 6)
    assert {k for _n, k, _s in LE.game_shows} == set(MP.SHOW_KINDS)
    assert all(len(n) < MP.SHOW_NAME_MAX for n, _k, _s in LE.game_shows)
    assert LE.can("shows")


def test_titles_without_shows_cannot_and_say_why():
    assert not OLD_PRO.can("shows") and "Godzilla Pro 1.15" in OLD_PRO.why_not("shows") and OLD_PRO.game_shows == ()
    # PAD-420: the Pro 1.16 plays eight of the Premium/LE's shows by the same names, and four of its own
    assert PRO.can("shows") and len(PRO.game_shows) == 12
    assert {"Strobe burst", "Strobe storm", "Blue fade", "Cyan flick"} <= {n for n, _k, _s in PRO.game_shows}
    assert "Insert chase" not in {n for n, _k, _s in PRO.game_shows}     # its match crashed the game: left out
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        assert p.can("shows") == bool(p.game_shows), key
        if not p.game_shows:
            assert p.label in p.why_not("shows"), key


def test_the_runtime_needs_its_process_lines():
    port = MP.read_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    assert MP._game_shows(port)
    del port["value"]["show_proc"]
    assert MP._game_shows(port) == ()


# ---- the mode ----------------------------------------------------------------------------------
def test_the_lines_and_their_refusals():
    assert MP.ModeSpec().show_start == MP.ModeSpec().show_end == ""
    assert not _key(_spec(LE), "show_start") and not _key(_spec(LE), "show_end")
    spec = _spec(LE, show_start="Strobe burst", show_end="Blue fade")
    assert MP.validate(spec) == []
    assert _key(spec, "show_start") == ["Strobe burst"] and _key(spec, "show_end") == ["Blue fade"]
    bad = MP.validate_shows(_spec(LE, show_end="Nope"), LE)
    assert bad == ["Godzilla Premium/LE 1.16 has no light show called 'Nope' to play at the mode's end."]
    pro = MP.validate_shows(_spec(OLD_PRO, show_start="Strobe burst"), OLD_PRO)
    assert pro == ["A light show of the game's is not on Godzilla Pro 1.15 (Lights says why)."]
    assert MP.show_lines(_spec(OLD_PRO, show_start="Strobe burst"), OLD_PRO) == []
    assert MP.validate_shows(_spec(PRO, show_start="Strobe burst"), PRO) == []          # PAD-420
    from pinball_decryptor.webui.tabs.modes import problem_pages
    assert problem_pages(bad) == problem_pages(pro) == ["lights"]


def test_the_fields_round_trip_and_belong_to_the_model(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=_spec(LE, show_start="Insert chase", show_end="Ember fade"))
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert (back.show_start, back.show_end) == ("Insert chase", "Ember fade")
    assert "show_start" in MP.MODEL_FIELDS and "show_end" in MP.MODEL_FIELDS
    assert MP.blank_spec(PRO).show_start == "" and MP.blank_spec(OLD_PRO).show_start == ""


def test_the_pro_keeps_the_shows_it_shares_and_leaves_out_the_rest():
    # PAD-420: the Pro 1.16 has the Premium/LE's Strobe burst and Blue fade by the same names - kept
    spec = _spec(LE, show_start="Strobe burst", show_end="Blue fade")
    on_pro, _dropped = MP.retarget(spec, PRO)
    assert (on_pro.show_start, on_pro.show_end) == ("Strobe burst", "Blue fade") and MP.validate(on_pro) == []
    # its Insert chase is not on the Pro: left out there, and given back on the Premium/LE
    spec = _spec(LE, show_start="Insert chase", show_end="Blue fade")
    on_pro, _dropped = MP.retarget(spec, PRO)
    assert (on_pro.show_start, on_pro.show_end) == ("", "Blue fade") and MP.validate(on_pro) == []
    words = MP.port_words(spec, on_pro, PRO)
    assert "Godzilla Pro 1.16 does not have the light show Insert chase, so it is left out there" in words
    back, _dropped = MP.retarget(on_pro, LE)
    assert (back.show_start, back.show_end) == ("Insert chase", "Blue fade")
    # a port with none (the Pro 1.15) leaves both out
    on_old, _dropped = MP.retarget(_spec(LE, show_start="Strobe burst", show_end="Blue fade"), OLD_PRO)
    assert (on_old.show_start, on_old.show_end) == ("", "")


# ---- the mode file -----------------------------------------------------------------------------
def _harness(tmp_path_factory):
    from tests.test_spike2_mode_aside import BLOCK_STUBS, _build
    anchor = next(new for _old, new in BLOCK_STUBS if "pm_block_game_modes" in new)
    tail = anchor[anchor.index("int pm_block_game_modes"):]
    stubs = BLOCK_STUBS + [(tail, tail + "\nint pm_game_show_named(const char *name) "
                            "{ printf(\"GAMESHOW %s at %lu\\n\", name, now_ms); return 1; }")]
    return _build(tmp_path_factory, stubs, "gameshow")


@pytest.fixture(scope="module")
def harness_shows(tmp_path_factory):
    return _harness(tmp_path_factory)


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


RUSH = ("name RUSH\ntrigger 0x08000000 1\nseconds 2\nshots 0x00300000\naward 1000000\n"
        "show_start Strobe burst\nshow_end Blue fade\n")


def test_the_start_and_the_end_play_their_shows(harness_shows, tmp_path):
    out = _run(harness_shows, tmp_path, RUSH, "shot", "0x08000000", "tick", "200")
    assert 'the game\'s light show "Strobe burst" at its start, "Blue fade" at its end' in out
    shows = [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMESHOW ")]
    assert shows == ["GAMESHOW Strobe burst", "GAMESHOW Blue fade"], out
    assert "RUSH: the game's light show \"Strobe burst\" at its start - playing" in out
    assert out.index("GAMESHOW Strobe burst") < out.index("RUSH START") < out.index("GAMESHOW Blue fade") \
        < out.index("RUSH END (time ran out)")


def test_no_show_as_the_ball_drains_and_none_without_the_keys(harness_shows, tmp_path):
    out = _run(harness_shows, tmp_path, RUSH, "shot", "0x08000000", "tick", "30", "ball_end")
    assert "RUSH END (ball ended)" in out
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMESHOW ")] == ["GAMESHOW Strobe burst"]
    out = _run(harness_shows, tmp_path, RUSH.replace("show_start Strobe burst\nshow_end Blue fade\n", ""),
               "shot", "0x08000000", "tick", "200")
    assert "GAMESHOW" not in out and "light show" not in out


# ---- the blocks --------------------------------------------------------------------------------
PROG = {"name": "LIGHT SHOW", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "mode_start"}, "do": [{"op": "start_mode"}, {"op": "game_show", "name": "Strobe burst"}]},
    {"hat": {"kind": "mode_end"}, "do": [{"op": "game_show", "name": "Ember fade"}]}]}


def test_the_block_plays_one_by_name_and_is_refused_where_there_is_none():
    names = [n for n, _k, _s in LE.game_shows]
    assert BM.problems(PROG, game_shows=names) == [] and BM.problems(PROG) == []
    assert BM.problems(PROG, game_shows=[]) == [
        "Script 1 plays a light show of the game's, which a mode cannot do on this card's game.",
        "Script 2 plays a light show of the game's, which a mode cannot do on this card's game."]
    bad = {**PROG, "scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "game_show", "name": "Nope"},
                                                                       {"op": "game_show", "name": ""}]}]}
    assert BM.problems(bad, game_shows=names) == [
        "Script 1 plays the game's light show Nope, which this card's game does not have.",
        "Script 1 plays the game's light show with none chosen."]
    assert not any("light show" in n for n in BM.notes(PROG))
    drain = {**PROG, "scripts": PROG["scripts"] + [{"hat": {"kind": "ball_end"},
                                                    "do": [{"op": "game_show", "name": "Blue fade"}]}]}
    assert any("only while the mode runs or as it ends" in n for n in BM.notes(drain))
    c = BM.to_c(BM.normalize(PROG), "light_show")
    assert 'game_show("Strobe burst");' in c and 'game_show("Ember fade");' in c
    assert "pm_game_show_named(name)" in c
    assert "pm_game_show_named" not in BM.to_c(BM.normalize({**PROG, "scripts": []}), "x")


def test_the_blocks_c_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    (tmp_path / "ls.c").write_text(BM.to_c(BM.normalize(PROG), "light_show"), encoding="utf-8")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(tmp_path / "ls.c"), str(SDK / "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_docs_name_the_keys_and_the_fields():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    for name in ("show_start", "show_end"):
        assert re.search(r"\| `%s` \| `<name>`" % name, doc), name
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "**From the Modes tab (PAD-418).**" in sdk


# ---- the Modes tab -------------------------------------------------------------------------------
def test_the_tab_offers_them_where_the_port_names_them_and_greys_them_where_none(tmp_path):
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
            assert st["form"]["show_start"] == st["form"]["show_end"] == "(none)"
            assert not st["dis"]["shows"] and "shows" not in st["reasons"]
            shows = st["profile"]["game_shows"]
            assert shows[0] == {"name": "Strobe burst", "kind": "flashy", "secs": 6} and len(shows) == 10
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:show_start", "Insert chase")
            w.call("ui.set", "modes", "f:show_end", "Colour fade")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("show_end") == "Colour fade")
            assert json.loads(path.read_text("utf-8"))["show_start"] == "Insert chase"
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:show_end", "(none)")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("show_end") == "")
            w.call("modes.new_blocks_mode", "Shows")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["game_shows_off"] == "" and len(ch["game_shows"]) == 10
        # PAD-420: the Pro 1.16 plays eight of the Premium/LE's shows by the same names, and four of its own
        proj = _card_project(tmp_path / "pro", "godzilla_pro-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert not st["dis"]["shows"] and "shows" not in st["reasons"]
            names = [s["name"] for s in st["profile"]["game_shows"]]
            assert len(names) == 12 and {"Strobe burst", "Strobe storm", "Blue fade", "Cyan flick"} <= set(names)
        # a port that names none (the Pro's older 1.15) greys them and says why
        proj = _card_project(tmp_path / "old", "godzilla_pro-1_15_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["dis"]["shows"] and "Godzilla Pro 1.15" in st["reasons"]["shows"]
            assert st["profile"]["game_shows"] == []
            w.call("modes.new_blocks_mode", "Shows")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["game_shows_off"].startswith("Not on this game: The app has not found Godzilla Pro 1.15's own")
    finally:
        preview.enabled = old
