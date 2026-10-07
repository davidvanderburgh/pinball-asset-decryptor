"""PAD-436: a mode can be the GAME's own mini-wizard (James Bond LE 1.06's four): when it starts - on a film done, a
shot, shots in order - the player is handed the game's mode (pad_mode_runtime.c pm_game_wizard), lit for its start
shot or started at once, and nothing of the mode's own runs.

What is worth failing on:
  * THE WIZARDS ARE THE PORT'S: the profile lists the port's wizard lines by name and film, as the runtime arms them;
    a title whose port names none cannot, and says why.
  * A HAND-OVER WRITES ONLY WHAT IT USES: its name, what starts it, how often, and `game_wizard light|start <name>` -
    no clock, shots, screen, lights or sounds - and is valid with no clock (mode_file.c's runs()).
  * THE MODE FILE HANDS IT OVER INSTEAD OF RUNNING: pm_game_wizard_named is called with the name and how, no START of
    a mode of ours, no screen; how often it can start still holds.
  * A NAME IS CHECKED, and goes with the model like the light shows.
  * THE BLOCK hands one over by name, refused where the game has none.
  * THE RUNTIME keeps a refused start lit: a mode of ours that holds the game's modes off vetoes Ahoy Mr. Bond's
    start, and the game's start would otherwise unlight it and mark it played.
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
BOND_PORT = SDK / "ports" / "james_bond_le-1.06.port"
BOND = MP.profile_from_port(str(BOND_PORT))
GZ = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
NAMES = ["Chaos at Crab Key", "Ahoy Mr. Bond", "Goldfinger's Jackpot", "Duel on the Disco Volante"]


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (BOND, GZ):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _lines(spec):
    return [line for line in MP.runtime_cfg(spec, "w").splitlines() if line and not line.startswith("#")]


# ---- the profile -----------------------------------------------------------------------------
def test_the_profile_lists_the_ports_wizards_with_their_films():
    assert [n for n, _f in BOND.game_wizards] == NAMES
    assert dict(BOND.game_wizards)["Ahoy Mr. Bond"] == "From Russia With Love"      # its insert is ROSA KLEBB
    assert dict(BOND.game_wizards)["Duel on the Disco Volante"] == "Thunderball"     # its insert is LARGO
    assert BOND.wizard_shot == "Right ramp"
    assert all(len(n) < MP.WIZARD_NAME_MAX for n in NAMES)
    assert "james_bond_le-1.06" in MP.WIZARDS_PROVEN and BOND.can("wizard")


def test_titles_without_wizards_cannot_and_say_why():
    assert not GZ.can("wizard") and GZ.game_wizards == () and "Godzilla Premium/LE 1.16" in GZ.why_not("wizard")
    for key, p in MP.profiles(MP.PORTS_DIR).items():
        assert p.can("wizard") == bool(p.game_wizards), key
        if not p.game_wizards:
            assert p.label in p.why_not("wizard"), key


def test_the_runtime_needs_its_lines():
    port = MP.read_port(str(BOND_PORT))
    assert MP._game_wizards(port)
    for kind, name in (("site", "wizard_start"), ("data", "wizard_state"), ("data", "wizard_table"),
                       ("data", "lamps_dirty")):
        cut = MP.read_port(str(BOND_PORT))
        del cut[kind][name]
        assert MP._game_wizards(cut) == (), name


def test_the_port_lines_match_the_game_program_when_it_is_here():
    """The start's words, and the table the runtime checks at its arm (index, bit, a start in the code)."""
    elf = next((p for p in (os.environ.get("PAD_BOND_LE_106_ELF", ""), r"C:\tmp\PAD-420\elf\james_bond_le-1.06.elf",
                            "/mnt/c/tmp/PAD-420/elf/james_bond_le-1.06.elf") if p and os.path.isfile(p)), None)
    if not elf:
        pytest.skip("James Bond LE 1.06's game program is not here")
    import struct
    b = open(elf, "rb").read()
    text = BOND_PORT.read_text(encoding="utf-8")

    def word(addr):                         # the program's first PT_LOAD is at 0x8000, file offset 0
        return struct.unpack_from("<I", b, addr - 0x8000)[0]
    m = re.search(r"^site\s+wizard_start\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)", text, re.M)
    addr, w0, w1 = (int(x, 16) for x in m.groups())
    assert (word(addr), word(addr + 4)) == (w0, w1)
    table = int(re.search(r"^data\s+wizard_table\s+(0x[0-9a-f]+)", text, re.M).group(1), 16)
    starts = []
    for n in range(4):
        e = [word(table + 0x20 * n + 4 * k) for k in range(4)]
        assert e[0] == n and e[1] == 1 << n
        starts.append(e[3])
    assert starts == [0x92bd8, 0x20530, 0xbd4dc, 0x7e0b0]
    assert "site block_start_6      0x00020530" in text            # Ahoy's start: a mode of ours may veto it


# ---- the mode ----------------------------------------------------------------------------------
def test_a_hand_over_writes_only_what_it_uses():
    spec = _spec(BOND, name="FRWL WIZARD", starts_on="event film_frwl", starts="once_per_game",
                 game_wizard="Ahoy Mr. Bond", wizard_how="start", screen=True, lights=True)
    assert MP.validate(spec) == []
    assert _lines(spec) == ["name           FRWL WIZARD", "starts_on      event film_frwl",
                            "starts         once_per_game", "game_wizard    start Ahoy Mr. Bond"]
    shot = _spec(BOND, name="GF", game_wizard="Goldfinger's Jackpot")
    lines = _lines(shot)
    assert lines[1].startswith("trigger ") and lines[-1] == "game_wizard    light Goldfinger's Jackpot"
    assert not any(line.split()[0] in ("seconds", "shots", "award", "screen_scene", "light_all", "callout_end",
                                       "game_modes", "ends_on") for line in lines)


def test_a_hand_over_needs_none_of_a_modes_own_parts():
    spec = _spec(BOND, game_wizard="Chaos at Crab Key", seconds=0, scoring_shots=[], award=0)
    assert MP.validate(spec) == []
    spec.game_wizard = ""
    assert "It has to run for at least a second." in MP.validate(spec)


def test_a_mode_of_its_own_writes_no_wizard_line():
    assert MP.ModeSpec().game_wizard == "" and MP.ModeSpec().wizard_how == "light"
    assert not any(line.startswith("game_wizard") for line in _lines(_spec(BOND)))


def test_the_refusals_name_the_mode_page():
    from pinball_decryptor.webui.tabs.modes import problem_pages
    bad = MP.validate(_spec(BOND, game_wizard="Nope"))
    assert bad == ["James Bond 007 LE 1.06 has no mini-wizard called 'Nope'."]
    how = MP.validate(_spec(BOND, game_wizard="Ahoy Mr. Bond", wizard_how="later"))
    assert how == ["The game's mini-wizard is lit for its start shot, or started at once."]
    gz = MP.validate_wizard(_spec(GZ, game_wizard="Ahoy Mr. Bond"), GZ)
    assert gz == ["A mini-wizard of the game's is not on Godzilla Premium/LE 1.16 (Mode says why)."]
    assert problem_pages(bad) == problem_pages(how) == problem_pages(gz) == ["mode"]
    assert MP.blank_spec(GZ).game_wizard == ""


def test_the_fields_round_trip_and_belong_to_the_model(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=_spec(BOND, game_wizard="Duel on the Disco Volante", wizard_how="start"))
    back = MP.load(str(project / "modes" / slug / "mode.json"))
    assert (back.game_wizard, back.wizard_how) == ("Duel on the Disco Volante", "start")
    assert "game_wizard" in MP.MODEL_FIELDS


def test_a_hand_over_takes_no_screen_clip_or_sound_on_the_card():
    """Its own parts are kept in the mode (for the way back to a mode of its own) but nothing is built for them;
    its mode file still goes on the card in its slot."""
    import inspect
    from pinball_decryptor.plugins.stern import mode_assets as MA
    from pinball_decryptor.plugins.stern import mode_sounds as MS
    spec = _spec(BOND, game_wizard="Ahoy Mr. Bond", sound_start="s.wav", music="m.wav")
    assert MS.wants(spec) == ()
    spec.game_wizard = ""
    assert MS.wants(spec) == ("sound_start", "music")
    src = inspect.getsource(MA.build)
    assert "own = [(slug, spec) for slug, spec in found if not spec.game_wizard]" in src
    assert "for slug, spec in own if spec.screen" in src and "for slug, spec in own if spec.clip" in src
    assert "for slot, (slug, spec) in enumerate(found):" in src


def test_another_game_drops_the_wizard_and_says_so():
    spec = _spec(BOND, game_wizard="Ahoy Mr. Bond")
    on_gz, _dropped = MP.retarget(spec, GZ)
    assert on_gz.game_wizard == ""


# ---- the mode file -----------------------------------------------------------------------------
def _harness(tmp_path_factory):
    from tests.test_spike2_mode_aside import BLOCK_STUBS, _build
    anchor = next(new for _old, new in BLOCK_STUBS if "pm_block_game_modes" in new)
    tail = anchor[anchor.index("int pm_block_game_modes"):]
    stubs = BLOCK_STUBS + [(tail, tail + "\nint pm_game_wizard_named(const char *name, int how) "
                            "{ printf(\"GAMEWIZARD %s how %d at %lu\\n\", name, how, now_ms); "
                            "return how == PM_WIZARD_START ? PM_WIZARD_STARTED : PM_WIZARD_LIT; }")]
    return _build(tmp_path_factory, stubs, "gamewizard")


@pytest.fixture(scope="module")
def harness_wizard(tmp_path_factory):
    return _harness(tmp_path_factory)


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


AHOY = "name AHOY\ntrigger 0x08000000 1\nstarts once_per_game\ngame_wizard start Ahoy Mr. Bond\n"


def test_the_mode_file_hands_it_over_instead_of_running(harness_wizard, tmp_path):
    out = _run(harness_wizard, tmp_path, AHOY, "shot", "0x08000000", "tick", "200")
    assert "NOT VALID" not in out
    assert '"AHOY": when it starts, the game\'s mini-wizard "Ahoy Mr. Bond" is started instead' in out
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMEWIZARD ")] == \
        ["GAMEWIZARD Ahoy Mr. Bond how 1"], out
    assert "AHOY START (trigger shot): the game's Ahoy Mr. Bond, started for player 1" in out
    assert "AHOY END" not in out and "own screen" not in out


def test_how_often_still_holds_and_light_is_light(harness_wizard, tmp_path):
    out = _run(harness_wizard, tmp_path, AHOY, "shot", "0x08000000", "tick", "30", "shot", "0x08000000", "tick", "30")
    assert out.count("GAMEWIZARD ") == 1 and "AHOY not started (trigger shot): already ran this game" in out
    out = _run(harness_wizard, tmp_path, AHOY.replace("start Ahoy", "light Ahoy").replace("starts once_per_game\n", ""),
               "shot", "0x08000000", "tick", "30", "shot", "0x08000000", "tick", "30")
    assert [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMEWIZARD ")] == \
        ["GAMEWIZARD Ahoy Mr. Bond how 0"] * 2
    assert "the game's Ahoy Mr. Bond, lit for its start shot for player 1" in out


def test_a_bad_how_is_skipped_and_the_file_is_not_valid(harness_wizard, tmp_path):
    out = _run(harness_wizard, tmp_path, AHOY.replace("game_wizard start", "game_wizard later"),
               "shot", "0x08000000", "tick", "30")
    assert 'game_wizard "later Ahoy Mr. Bond" is not light or start - skipped' in out
    assert "NOT VALID" in out and "GAMEWIZARD" not in out


# ---- the runtime -------------------------------------------------------------------------------
def test_the_runtime_keeps_a_refused_start_lit_and_lights_a_start_while_a_mode_blocks():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    veto = src[src.index("static int on_block_start("):]
    veto = veto[:veto.index("\n}\n")]
    assert veto.index("wizard_refused(block_hooked[hook_n]);") < veto.index("return 1;")
    wiz = src[src.index("int pm_game_wizard(int n, int how)"):]
    wiz = wiz[:wiz.index("\n}\n")]
    assert wiz.index("block_owner && running == block_owner") < wiz.index('fn("wizard_start")')
    assert "wizards_tick();" in src[src.index("static void on_tick(unsigned *r)"):]
    assert "wizards_arm();" in src and "PM_CAN_GAME_WIZARDS" in (SDK / "pad_mode.h").read_text(encoding="utf-8")


# ---- the blocks --------------------------------------------------------------------------------
PROG = {"name": "FILMS", "seconds": 30, "vars": [], "scripts": [
    {"hat": {"kind": "event", "event": "film_frwl"}, "do": [{"op": "game_wizard", "name": "Ahoy Mr. Bond",
                                                             "how": "start"}]},
    {"hat": {"kind": "event", "event": "film_goldfinger"}, "do": [{"op": "game_wizard",
                                                                   "name": "Goldfinger's Jackpot"}]}]}


def test_the_block_hands_one_over_by_name_and_is_refused_where_there_is_none():
    assert BM.problems(PROG, game_wizards=NAMES) == [] and BM.problems(PROG) == []
    assert BM.problems(PROG, game_wizards=[]) == [
        "Script 1 hands the player a mini-wizard of the game's, which a mode cannot do on this card's game.",
        "Script 2 hands the player a mini-wizard of the game's, which a mode cannot do on this card's game."]
    bad = {**PROG, "scripts": [{"hat": {"kind": "mode_start"}, "do": [
        {"op": "game_wizard", "name": "Nope"}, {"op": "game_wizard", "name": ""},
        {"op": "game_wizard", "name": "Ahoy Mr. Bond", "how": "later"}]}]}
    assert BM.problems(bad, game_wizards=NAMES) == [
        "Script 1 hands the player the game's mini-wizard Nope, which this card's game does not have.",
        "Script 1 hands the player the game's mini-wizard with none chosen.",
        "Script 1 lights the game's mini-wizard or starts it."]
    c = BM.to_c(BM.normalize(PROG), "films")
    assert 'game_wizard("Ahoy Mr. Bond", 1);' in c and 'game_wizard("Goldfinger\'s Jackpot", 0);' in c
    assert "pm_game_wizard_named(name, start ? PM_WIZARD_START : PM_WIZARD_LIGHT)" in c
    assert "pm_game_wizard_named" not in BM.to_c(BM.normalize({**PROG, "scripts": []}), "x")


def test_the_blocks_c_builds_with_build_mode_sh(tmp_path):
    if os.name == "nt":
        pytest.skip("build_mode.sh runs under bash with arm-linux-gnueabihf-gcc (WSL or Linux)")
    if not shutil.which("bash") or not shutil.which("arm-linux-gnueabihf-gcc"):
        pytest.skip("no arm-linux-gnueabihf-gcc here")
    (tmp_path / "films.c").write_text(BM.to_c(BM.normalize(PROG), "films"), encoding="utf-8")
    r = subprocess.run(["bash", str(SDK / "build_mode.sh"), "-o", str(tmp_path / "mode.so"),
                        str(tmp_path / "films.c"), str(SDK / "mode_file.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "warning" not in (r.stdout + r.stderr).lower()


def test_the_docs_name_the_key_and_the_call():
    doc = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    assert re.search(r"\| `game_wizard` \| `light\|start <name>`", doc)
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "## The game's own mini-wizards (PAD-436)" in sdk and "pm_game_wizard" in sdk


# ---- the Modes tab -------------------------------------------------------------------------------
def test_the_tab_offers_them_on_bond_and_greys_them_elsewhere(tmp_path):
    from tests.test_webui_modes import _card_project, _project, _wait
    from tests.webui_harness import web_app
    from pinball_decryptor.core import preview
    old = preview.enabled
    preview.enabled = lambda feature: feature == "modes"
    try:
        proj = _card_project(tmp_path / "bond", "james_bond_le-1_06_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            slug = w.call("modes.new")
            st = w.state("modes")
            assert st["form"]["game_wizard"] == "(none)" and st["form"]["wizard_how"] == "light"
            assert not st["dis"]["wizard"] and "wizard" not in st["reasons"]
            assert st["profile"]["game_wizards"][1] == {"name": "Ahoy Mr. Bond", "film": "From Russia With Love"}
            assert st["profile"]["wizard_shot"] == "Right ramp"
            path = proj / "modes" / slug / "mode.json"
            w.call("ui.set", "modes", "f:start_event", "From Russia With Love done")
            w.call("ui.set", "modes", "f:starts_kind", "event")
            w.call("ui.set", "modes", "f:game_wizard", "Ahoy Mr. Bond")
            w.call("ui.set", "modes", "f:wizard_how", "start")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("wizard_how") == "start")
            saved = json.loads(path.read_text("utf-8"))
            assert saved["game_wizard"] == "Ahoy Mr. Bond" and saved["starts_on"] == "event film_frwl"
            assert _wait(w, lambda: w.state("modes")["status"] == "Ready to build.")
            w.call("ui.set", "modes", "f:game_wizard", "(none)")
            assert _wait(w, lambda: json.loads(path.read_text("utf-8")).get("game_wizard") == "")
            w.call("modes.new_blocks_mode", "Films")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["game_wizards_off"] == "" and [x["name"] for x in ch["game_wizards"]] == NAMES
            assert ch["wizard_shot"] == "Right ramp"
        proj = _card_project(tmp_path / "gz", "godzilla_le-1_16_0.raw")
        with web_app(tmp_path, mfr="stern") as w:
            _project(w, proj)
            w.call("modes.new")
            st = w.state("modes")
            assert st["dis"]["wizard"] and "Godzilla Premium/LE 1.16" in st["reasons"]["wizard"]
            assert st["profile"]["game_wizards"] == []
            w.call("modes.new_blocks_mode", "Films")
            ch = w.state("modes")["code"]["blocks"]["choices"]
            assert ch["game_wizards_off"].startswith("Not on this game: The app has not found Godzilla Premium/LE")
    finally:
        preview.enabled = old
