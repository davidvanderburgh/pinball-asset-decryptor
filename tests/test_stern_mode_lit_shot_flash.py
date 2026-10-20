"""PAD-642: James Bond 007's lit-shot flash as one of the game's light shows a mode can play, and a form mode's show on
each hit of a shot that scores.

A Bond LE owner: "Everytime a lit insert is hit in a mode in James Bond LE there is a lightshow that quickly alternates
inserts and GI in a 1.5-2second show. Would like to see this lightshow as an option in custom modes so those could be
consistent." The flash has no process body of its own: every mode of the game's answers its lit shot with a call
(LE 1.06 0x19e534, Pro 1.06 0x19cd44) that starts its GI and insert shows through the game's own show starter, in a
colour, three times over. Emulator-proven on both builds (the call made, the two shows running with the colour, the 3
repeats and the game's own priority, stopped at their 2 s and by a new show).

What is worth failing on:
  * THE PORTS NAME THE CALL: ten Lit shot flash shows (the game's colours 1-10), each the call with its colour, the
    game's two show numbers it starts and the game's "stop every show with this number".
  * THE RUNTIME MAKES THE CALL instead of starting a process, with every limit of a show, and stops it by number.
  * A FORM MODE PLAYS ONE ON EACH SCORING HIT (`show_hit`), in place of the shot's white flash.
"""
import os
import pathlib
import re
import subprocess

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
COLOURS = ["white", "red", "green", "blue", "cyan", "magenta", "purple", "yellow", "orange", "dark orange"]
BUILDS = {  # port: (the call, the game's show numbers it starts, the game's stop-by-number)
    "james_bond_le-1.06": (0x19e534, "450 448", 0x2fce04),
    "james_bond_pro-1.06": (0x19cd44, "448 446", 0x207220),
}
LE = MP.profile_from_port(str(SDK / "ports" / "james_bond_le-1.06.port"))
PRO = MP.profile_from_port(str(SDK / "ports" / "james_bond_pro-1.06.port"))
GZ = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))


@pytest.fixture(autouse=True)
def _titles(monkeypatch):
    for p in (LE, PRO, GZ):
        monkeypatch.setitem(MP.PROFILES, p.key, p)


def _spec(p, **kw):
    spec = MP.blank_spec(p)
    for k, v in kw.items():
        setattr(spec, k, v)
    return spec


def _key(spec, key):
    return [line.split(None, 1)[1] for line in MP.runtime_cfg(spec, "ls").splitlines()
            if line and not line.startswith("#") and line.split(None, 1)[0] == key]


# ---- the ports -------------------------------------------------------------------------------
@pytest.mark.parametrize("port", sorted(BUILDS))
def test_the_port_names_the_flash_by_its_call_in_each_colour(port):
    call, numbers, stop = BUILDS[port]
    text = (SDK / "ports" / (port + ".port")).read_text(encoding="utf-8")
    assert re.search(r"^site show_stop_number\s+0x%08x 0xe92d4070 0x[0-9a-f]{8}$" % stop, text, re.M)
    calls = [int(n) for n in re.findall(r"^value show_call_(\d+)\s", text, re.M)]
    assert len(calls) == 10
    for colour, n in enumerate(calls, 1):
        assert re.search(r"^site show_%d\s+0x%08x 0xe92d4010 0xe1a04000\s" % (n, call), text, re.M), n
        assert re.search(r"^value show_call_%d\s+%d$" % (n, colour), text, re.M), n
        assert re.search(r"^text show_numbers_%d\s+%s$" % (n, numbers), text, re.M), n
        assert re.search(r"^text show_name_%d\s+Lit shot flash %s$" % (n, COLOURS[colour - 1]), text, re.M), n
        assert re.search(r"^text show_kind_%d\s+accent$" % n, text, re.M), n
        assert re.search(r"^value show_secs_%d\s+2$" % n, text, re.M), n


@pytest.mark.parametrize("p", [LE, PRO], ids=lambda p: p.key)
def test_both_models_offer_the_ten_flashes_by_the_same_names(p):
    shows = {n: (k, s) for n, k, s in p.game_shows}
    for c in COLOURS:
        assert shows["Lit shot flash %s" % c] == ("accent", 2), (p.key, c)
    assert p.can("shows") and len(p.game_shows) == 22


def test_the_60th_anniversary_has_no_such_call():
    text = (SDK / "ports" / "james_bond_60th_le-1.11.port").read_text(encoding="utf-8")
    assert "Lit shot flash" not in text and "show_call_" not in text


# ---- the runtime -----------------------------------------------------------------------------
def _fn(src, head):
    body = src[src.index(head):]
    return body[:body.index("\n}\n")]


def test_the_runtime_makes_the_call_with_a_shows_limits():
    src = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
    body = _fn(src, "int pm_game_show(int n)")
    call = body.index('pm_snprintf(key, sizeof key, "show_call_%d", n);')
    # the limits of every show come first: the running mode, in a game, not while the ball ends, one at a time
    for limit in ("pm_running()", "!pm_in_game()", "ball_end_at && pm_ms() - ball_end_at < 3000ul",
                  'if (show_now.n || proc_alive(id)) show_kill("another show begins");'):
        assert body.index(limit) < call, limit
    branch = body[call:body.index("rec = ((unsigned (*)(unsigned, void (*)(void), unsigned))")]
    assert "arg = pm_port_value(key, -1);" in branch and "if (arg >= 0) {" in branch
    assert "((void (*)(unsigned))(unsigned long)at)((unsigned)arg);" in branch and "show_now.call = 1;" in branch
    # stopped at its length to the tick, as the game's own caller stops it (no margin, as a process show has)
    assert "* 1000ul : SHOW_MAX_MS;" in branch and "+ 500ul" not in branch
    assert "show_now.call = 0;" in body[body.index("rec = ((unsigned"):]
    stop = _fn(src, "static void show_call_stop(int n)")
    assert 'fn("show_stop_number")' in stop and '"show_numbers_%d"' in stop
    kill = _fn(src, "static void show_kill(const char *why)")
    assert kill.index("show_call_stop(show_now.n);") < kill.index('fn("event_cancel")')
    assert "if (show_now.n && show_now.call) return 1;" in _fn(src, "int pm_game_show_playing(void)")
    assert "if (!show_now.call && !proc_alive(" in _fn(src, "static void shows_tick(void)")


# ---- the mode: a show on each hit ------------------------------------------------------------
def test_the_mode_file_plays_it_on_each_scoring_hit():
    src = (SDK / "mode_file.c").read_text(encoding="utf-8")
    assert 'TEXT("show_hit", show_hit)' in src and "char show_hit[40];" in src
    shot = _fn(src, "static void on_shot(uint64_t mask)")
    pay = shot[:shot.index("penalty_bits(M)")]                  # in the scoring hit's own block
    assert 'if (!game_show(M, cfg.show_hit, "a shot"))\n            pm_lamp_flash(' in pay
    assert "static int game_show(" in src


def test_the_line_its_refusals_and_the_model():
    assert MP.ModeSpec().show_hit == ""
    assert not _key(_spec(LE), "show_hit")
    spec = _spec(LE, show_hit="Lit shot flash red")
    assert MP.validate(spec) == [] and _key(spec, "show_hit") == ["Lit shot flash red"]
    assert MP.validate_shows(_spec(LE, show_hit="Nope"), LE) == [
        "James Bond 007 LE 1.06 has no light show called 'Nope' to play on the mode's shots."]
    assert MP.validate_shows(_spec(LE, show_hit=3), LE) == ["The light show on its shots is a show's name."]
    assert "show_hit" in MP.MODEL_FIELDS
    # the Pro has the same ten flashes by the same names: kept; a game without them drops it, and says so
    on_pro, _dropped = MP.retarget(spec, PRO)
    assert on_pro.show_hit == "Lit shot flash red" and MP.validate(on_pro) == []
    on_gz, _dropped = MP.retarget(spec, GZ)
    assert on_gz.show_hit == ""                                  # Godzilla has no such show: dropped


def test_it_round_trips(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    slug, _ = MP.new_mode(str(project), spec=_spec(LE, show_hit="Lit shot flash orange"))
    assert MP.load(str(project / "modes" / slug / "mode.json")).show_hit == "Lit shot flash orange"


def test_the_lights_page_offers_it():
    from pinball_decryptor.webui.tabs import modes as M
    assert "show_hit" in M._STR_FIELDS and M._DEFAULTS["show_hit"] == "(none)"
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert 'When a shot is hit</span><${Select} value=${f.show_hit}' in js and 'k="f:show_hit"' in js


def test_the_docs_say_so():
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "**A show the game starts by a call, and a show on each hit (PAD-642).**" in sdk
    params = (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
    assert params.count("| `show_hit` |") == 2


# ---- the mode file, run (the host harness: an ELF linker, so WSL or Linux) ------------------------
@pytest.fixture(scope="module")
def harness_hits(tmp_path_factory):
    if os.name == "nt":
        pytest.skip("the harness needs an ELF linker (__start_pm_modes / __stop_pm_modes)")
    from tests.test_spike2_mode_aside import BLOCK_STUBS, _build
    anchor = next(new for _old, new in BLOCK_STUBS if "pm_block_game_modes" in new)
    tail = anchor[anchor.index("int pm_block_game_modes"):]
    stubs = BLOCK_STUBS + [(tail, tail + "\nint pm_game_show_named(const char *name) "
                            "{ printf(\"GAMESHOW %s at %lu\\n\", name, now_ms); return strcmp(name, \"Nope\") != 0; }"
                            "\nint pm_lamp_flash(uint64_t shots, unsigned rgb, unsigned ms) "
                            "{ printf(\"LAMPFLASH %llx at %lu\\n\", (unsigned long long)shots, now_ms); return 1; }")]
    return _build(tmp_path_factory, stubs, "lithit")


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    r = subprocess.run([str(harness), *args], capture_output=True, text=True,
                       env=dict(os.environ, MODE_DIR=str(tmp_path)), timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


HITS = "name HITS\ntrigger 0x08000000 1\nseconds 20\nshots 0x00300000\naward 1000\n"


def test_each_scoring_hit_plays_it_in_place_of_the_white_flash(harness_hits, tmp_path):
    out = _run(harness_hits, tmp_path, HITS + "show_hit Lit shot flash red\n", "shot", "0x08000000", "tick", "5",
               "shot", "0x00100000", "tick", "5", "shot", "0x00200000", "tick", "5", "shot", "0x00400000")
    assert 'the game\'s light show "Lit shot flash red" on each shot that scores' in out
    shows = [ln.split(" at ")[0] for ln in out.splitlines() if ln.startswith("GAMESHOW ")]
    assert shows == ["GAMESHOW Lit shot flash red"] * 2, out     # the two scoring hits: not the start, not 0x400000
    assert "LAMPFLASH" not in out
    assert 'HITS: the game\'s light show "Lit shot flash red" at a shot - playing' in out


def test_a_refused_show_or_none_leaves_the_white_flash(harness_hits, tmp_path):
    out = _run(harness_hits, tmp_path, HITS + "show_hit Nope\n", "shot", "0x08000000", "tick", "5", "shot", "0x00100000")
    assert "GAMESHOW Nope" in out and "LAMPFLASH 100000" in out
    out = _run(harness_hits, tmp_path, HITS, "shot", "0x08000000", "tick", "5", "shot", "0x00100000")
    assert "GAMESHOW" not in out and "LAMPFLASH 100000" in out

