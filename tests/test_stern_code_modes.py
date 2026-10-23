"""A CODE mode carries its own clip, screen, music and calls through the project (the intricate modes'
own audio and video): plugins/stern/code_modes.py, the code half of Write (mode_write), and the SDK
header the mode reads them with (tools/spike2_emu/modes/sdk/pad_mode_assets.h).

Desk only: no card, no rig. (PAD-691: the code examples and the film recipes they were cut by are out of the
app, and their tests with them.) The compile of the code modes (build_mode.sh in the app's Linux) is stubbed where Write is planned.
"""
import json
import os
import re
import wave

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_runtime as MR
from pinball_decryptor.plugins.stern import mode_sounds as MS
from pinball_decryptor.plugins.stern import mode_write as MW

GZ = MP.GODZILLA_PRO_1_15
SDK = MR.sdk_dir()


def _wav(path, seconds, ch=1, hz=440.0):
    n = int(seconds * 44100)
    t = np.arange(n) / 44100.0
    x = (8000 * np.sin(2 * np.pi * hz * t)).astype("<i2")
    if ch == 2:
        x = np.stack([x, x], 1).ravel()
    with wave.open(path, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(x.tobytes())


def _code_project(tmp_path, slug="ghidorah_heads", calls=("sever", "won", "lost"), music=True, source=None):
    project = str(tmp_path / "project")
    folder = MP.mode_folder(project, slug)
    os.makedirs(folder)
    with open(os.path.join(folder, slug + ".c"), "w") as f:
        f.write(source or '#define MODE_NAME          "KING GHIDORAH"\n')
    spec = CM.CodeAssets(name="KING GHIDORAH", seconds=85, screen=True)
    if music:
        _wav(os.path.join(folder, "music.wav"), 2.0, ch=2)
        spec.music = "music.wav"
    for cue in calls:
        _wav(os.path.join(folder, cue + ".wav"), 1.5)
    spec.calls = {cue: (cue + ".wav") for cue in calls}
    CM.save(project, slug, spec)
    return project


# ---- the project's side ---------------------------------------------------------------------------
def test_a_code_mode_is_its_c_file_without_a_mode_file(tmp_path):
    project = _code_project(tmp_path)
    MP.new_mode(project, "QUIET", MP.ModeSpec(name="QUIET", screen=False, clip="none"))
    assert CM.code_slugs(project) == ["ghidorah_heads"]
    slug, spec = CM.list_code(project)[0]
    assert slug == "ghidorah_heads" and spec.name == "KING GHIDORAH" and spec.seconds == 85
    assert spec.call_list() == [("sever", "sever.wav", 4), ("won", "won.wav", 4), ("lost", "lost.wav", 4)]
    assert CM.validate(spec, MP.mode_folder(project, slug)) == []


def test_a_code_mode_without_assets_json_carries_nothing_and_is_named_by_its_source(tmp_path):
    project = str(tmp_path / "p")
    folder = MP.mode_folder(project, "blitz")
    os.makedirs(folder)
    with open(os.path.join(folder, "blitz.c"), "w") as f:
        f.write('#define MODE_NAME        "BLITZ RUSH"\n')
    (slug, spec), = CM.list_code(project)
    assert spec.name == "BLITZ RUSH" and not spec.has_assets()
    os.remove(os.path.join(folder, "blitz.c"))
    with open(os.path.join(folder, "blitz.c"), "w") as f:
        f.write("/* a mode */\n")
    assert CM.list_code(project)[0][1].name == "BLITZ"


def test_a_fresh_code_modes_default_assets_read_as_nothing_of_its_own(tmp_path):
    """What New code mode writes beside the template (mode_tryit) is a file this module reads as
    a code mode with no screen, clip, music or call, so Write's code path and Try it's compile-only
    path both see it the way they saw a folder with no assets.json at all."""
    from pinball_decryptor.plugins.stern import mode_tryit as MT
    project = str(tmp_path / "p")
    os.makedirs(project)
    slug, _path = MT.new_code_mode(project, "Blitz Rush")
    with open(os.path.join(MP.mode_folder(project, slug), CM.ASSETS_FILE), encoding="utf-8") as f:
        data = json.load(f)
    assert data["format"] == CM.FORMAT and data["name"] == "Blitz Rush" and data["screen"] is False
    assert data["clip"] == "" and data["music"] == "" and data["calls"] == {}
    (got, spec), = CM.list_code(project)
    assert got == slug and spec.name == "Blitz Rush" and not spec.has_assets()
    assert CM.validate(spec, MP.mode_folder(project, slug)) == []
    assert MW.code_mode_list(project) == [(slug, spec)]


def test_what_is_wrong_with_a_code_modes_assets_is_said(tmp_path):
    spec = CM.CodeAssets(name="X", seconds=0, calls={"Bad Cue": "a.wav", "ok": {"wav": "", "priority": 9}},
                         music="gone.wav")
    probs = " ".join(CM.validate(spec, str(tmp_path)))
    for needle in ("seconds is the longest the mode runs", "'Bad Cue' is 1 to 15", "priority is 1 to 7",
                   "the ok call names no WAV", "the music file gone.wav is not in"):
        assert needle in probs, needle


def test_a_code_mode_lists_the_games_modes_it_holds_off(tmp_path):
    """PAD-363: `block_modes` in its assets file reaches the runtime file (ids 0-127); give_way writes none."""
    spec = CM.CodeAssets(name="X", block_modes=[70, 21, 21])
    assert not [p for p in CM.validate(spec, str(tmp_path)) if "block_modes" in p]
    assert "block_modes 21 70" in CM.runtime_text("x", spec, GZ).splitlines()
    spec.game_modes = "give_way"
    assert not any(ln.startswith("block_modes") for ln in CM.runtime_text("x", spec, GZ).splitlines())
    spec.block_modes = [128]
    assert any("block_modes is a list of the game's mode ids, 0 to 127" in p for p in CM.validate(spec, str(tmp_path)))


def test_a_broken_assets_json_stops_the_list_with_its_name(tmp_path):
    project = _code_project(tmp_path)
    with open(os.path.join(MP.mode_folder(project, "ghidorah_heads"), CM.ASSETS_FILE), "w") as f:
        f.write("{not json")
    with pytest.raises(CM.CodeModeError, match="ghidorah_heads"):
        CM.list_code(project)
    with pytest.raises(MW.ModeWriteError, match="ghidorah_heads"):
        MW.code_mode_list(project)


# ---- the runtime file ---------------------------------------------------------------------------------
def test_the_assets_file_names_only_what_the_build_carried(tmp_path):
    project = _code_project(tmp_path)
    (slug, spec), = CM.list_code(project)
    spec.clip = "clip.mp4"
    used = [{"slug": slug, "key": "music", "request": 125, "sid": 618},
            {"slug": slug, "key": "call:sever", "request": 1251, "ms": 1500},
            {"slug": slug, "key": "call:won", "request": 1249, "ms": 1500},
            {"slug": "other", "key": "call:lost", "request": 1133, "ms": 900}]
    text = CM.runtime_text(slug, spec, GZ, own_sounds=used, screen=True, clip=True)
    lines = text.splitlines()
    assert lines[0].startswith("# GENERATED by the app's Write from modes/ghidorah_heads/assets.json")
    assert "name   KING GHIDORAH" in lines
    assert "screen PadMode_ghidorah_heads_Screen PadMode_ghidorah_heads_Screen.PadMode_ghidorah_heads_Screen_Words" in lines
    assert "clip   start PadMode_ghidorah_heads_Clip" in lines
    assert "music  125 618" in lines
    assert "call   sever 1251 1500 4" in lines and "call   won 1249 1500 4" in lines
    assert not any("lost" in ln for ln in lines)          # another mode's carrier is not this one's
    assert text.endswith("\n") and "—" not in text


def test_the_assets_file_names_every_clip_by_its_cue(tmp_path):
    """hud-layers: a clip per cue - the old start clip keeps its name, every other is
    PadMode_<slug>_<Cue>, one line each, in the order the assets name them."""
    project = _code_project(tmp_path)
    (slug, spec), = CM.list_code(project)
    spec.clips = {"intro": "intro.mp4", "loop": "loop.mp4", "sever": "sever.mp4"}
    spec.hud = {"title": "KING GHIDORAH"}
    assert spec.clip_list() == [("intro", "intro.mp4"), ("loop", "loop.mp4"), ("sever", "sever.mp4")]
    text = CM.runtime_text(slug, spec, GZ, clip=True)
    assert "clip   intro PadMode_ghidorah_heads_Intro" in text.splitlines()
    assert "clip   loop PadMode_ghidorah_heads_Loop" in text.splitlines()
    assert "clip   sever PadMode_ghidorah_heads_Sever" in text.splitlines()
    assert CM.clip_name(slug, "start") == "PadMode_ghidorah_heads_Clip"
    spec.clip = "clip.mp4"                            # an old start clip beside an intro is not added twice
    assert [c for c, _f in spec.clip_list()] == ["intro", "loop", "sever"]
    assert "3 clips of its own (intro, loop, sever)" in CM.describe(slug, spec, prof=GZ)
    assert "its own HUD at the screen's edges" in CM.describe(slug, spec, prof=GZ)


def test_the_sdk_header_reads_the_file_the_build_writes():
    """pad_mode_assets.h's parser and runtime_text agree on every key and column."""
    src = open(os.path.join(SDK, "pad_mode_assets.h"), encoding="utf-8").read()
    for key in ('"name"', '"clip"', '"music"', '"call"', '"start"'):
        assert key in src, key
    assert '"/usr/local/padmode/", "/dump/"' in src and '"%s%s.assets"' in src
    assert "__attribute__((weak, visibility(\"hidden\"))) struct pa_music_state pa_music" in src
    declared = set(re.findall(r"\b(pm_\w+)\s*\(", open(os.path.join(SDK, "pad_mode.h"), encoding="utf-8").read()))
    used = set(re.findall(r"\b(pm_\w+)\s*\(", src))
    assert used <= declared, used - declared
    assert not re.search(r"\b(malloc|printf|fopen|sleep|usleep)\s*\(", src)


# ---- the sounds, from the same allocator ------------------------------------------------------------
def test_code_sounds_take_carriers_no_form_mode_or_other_sound_has(tmp_path):
    project = _code_project(tmp_path)
    code = CM.list_code(project)
    said = []
    got = MW.choose_code_sounds(project, code, (True, ""), GZ, taken=[1251, 1295], taken_beds=[257],
                                log=lambda m, *a: said.append(m))
    assert [u["key"] for u in got] == ["music", "call:sever", "call:won", "call:lost"]
    music = got[0]
    assert music["request"] == 125 and music["sid"] != 257 and music["seconds"] == 85 and music["music"]
    calls = [u["request"] for u in got[1:]]
    assert 1251 not in calls and 1295 not in calls and len(set(calls)) == 3
    assert all(r in MS._JP_CALLS for r in calls)
    assert not said


def test_code_sounds_off_or_on_a_title_without_carriers_are_left_out_with_a_line(tmp_path):
    project = _code_project(tmp_path)
    code = CM.list_code(project)
    said = []
    assert MW.choose_code_sounds(project, code, (False, "PAD_STERN_MODE_SOUND=0"), GZ,
                                 log=lambda m, *a: said.append(m)) == []
    assert "own sounds are off" in said[-1] and "KING GHIDORAH" in said[-1]
    tmnt = MP.profile_from_port(MR.port_file("turtles_pro", "1.58"))      # not the latest: no carriers
    assert MW.choose_code_sounds(project, code, (True, ""), tmnt, log=lambda m, *a: said.append(m)) == []
    assert "no stock requests to carry them" in said[-1]


def test_a_code_modes_calls_share_the_carriers_less_the_ones_re_pointed_for_good(tmp_path):
    """hud-layers: a swapped call is not given a carrier of its own at the desk: it gets every call
    carrier the title has, less the ones re-pointed for good (*taken*), from its rank in its mode on
    (longest first). The engine picks the one it takes, distinct within the mode."""
    cues = ["c%02d" % i for i in range(16)]
    project = _code_project(tmp_path, calls=cues, music=False)
    said = []
    got = MW.choose_code_sounds(project, CM.list_code(project), (True, ""), GZ,
                                taken=list(MS._JP_CALLS[:10]), log=lambda m, *a: said.append(m))
    left = list(MS._JP_CALLS[10:])
    assert len(got) == 16 and not said
    for u in got:
        assert u["swap"] and sorted(u["candidates"]) == sorted(left) and u["request"] == u["candidates"][0]
    firsts = [u["candidates"][0] for u in got]
    assert set(firsts) == set(left)                   # each rank starts at another carrier


# ---- Write's plan -------------------------------------------------------------------------------------
def _stub_compile(monkeypatch, calls):
    def fake(sources, out, log=None, executor=None, timeout=600):
        calls.append(list(sources))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "wb") as f:
            f.write(b"\x7fELF compiled")
        return out
    monkeypatch.setattr(MW, "compile_code_object", fake)


def test_write_plans_a_code_mode_with_its_object_and_assets_file(tmp_path, monkeypatch):
    from tests.test_stern_mode_write import _stub_build
    project = _code_project(tmp_path)
    _stub_build(monkeypatch)
    compiled = []
    _stub_compile(monkeypatch, compiled)
    port = tmp_path / "godzilla_pro-1.15.port"
    port.write_text("game godzilla_pro\nversion 1.15\n")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: str(port))
    monkeypatch.setattr(CM, "profile_for", lambda project, code=(): GZ)
    code = CM.list_code(project)
    own = MW.choose_code_sounds(project, code, (True, ""), GZ)
    own = [dict(u, idx=100 + i, ms=1500 if not u["music"] else None) for i, u in enumerate(own)]
    res = MW.plan(project, b"HUD", b"BANK", b"\x7fELF", str(tmp_path / "scratch"), own_sounds=own)
    assert res is not None and res.code and res.object.endswith("mode.so")
    assert compiled == [[CM.source_path(project, "ghidorah_heads")]]
    (name, path), = res.asset_files
    assert name == "ghidorah_heads.assets"
    text = open(path, encoding="utf-8").read()
    assert "music  125 %d" % own[0]["sid"] in text and "call   sever %d 1500 4" % own[1]["request"] in text
    assert any(ln.startswith("KING GHIDORAH (code mode): its code (ghidorah_heads.c)") for ln in res.lines)
    pay = MW.p2_payload(res, str(tmp_path / "p2"))
    assert open(pay["so"], "rb").read() == b"\x7fELF compiled"          # not the pinned object
    assert [os.path.basename(a) for a in pay["assets"]] == ["ghidorah_heads.assets"] and pay["cfgs"] == []

    class Ex:
        def to_exec_path(self, p):
            return "/x/" + os.path.basename(p)
    cmd = MW.install_command(Ex(), str(tmp_path / "card.raw"), pay, 1)
    assert "--asset /x/ghidorah_heads.assets" in cmd and "--cfg" not in cmd


def test_a_form_mode_and_a_code_mode_share_the_card(tmp_path, monkeypatch):
    from tests.test_stern_mode_write import _project, _stub_build
    project = _project(tmp_path)
    folder = MP.mode_folder(project, "ghidorah_heads")
    os.makedirs(folder)
    with open(os.path.join(folder, "ghidorah_heads.c"), "w") as f:
        f.write('#define MODE_NAME          "KING GHIDORAH"\n')
    _stub_build(monkeypatch)
    _stub_compile(monkeypatch, [])
    port = tmp_path / "godzilla_pro-1.15.port"
    port.write_text("game godzilla_pro\nversion 1.15\n")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: str(port))
    res = MW.plan(project, b"HUD", b"BANK", b"\x7fELF", str(tmp_path / "scratch"))
    assert [n for n, _s in res.mode_files] == ["mode.cfg", "mode1.cfg"]
    assert [n for n, _s in res.asset_files] == ["ghidorah_heads.assets"]
    lines = MW.pending_lines(project)
    assert any(ln.startswith("KING GHIDORAH (code mode)") for ln in lines)
    assert any(ln.startswith("ATOMIC BREATH") for ln in lines)


def test_mode_install_takes_assets_and_no_mode_file():
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(SDK)))
    import mode_install as mi
    assert mi.asset_name_ok("ghidorah_heads.assets") and not mi.asset_name_ok("Bad.assets")
    assert not mi.asset_name_ok("x.cfg") and not mi.asset_name_ok(".assets")
    src = open(mi.__file__, encoding="utf-8").read()
    assert 'p.add_argument("--asset", action="append"' in src


def test_the_rig_scripts_carry_the_assets_files():
    rig = os.path.dirname(SDK)
    tryit = open(os.path.join(rig, "tryit.sh"), encoding="utf-8").read()
    assert 'for f in "$S"/*.assets; do' in tryit and '"$DUMP"/*.assets' in tryit
    card = open(os.path.join(rig, "cardmodes.sh"), encoding="utf-8").read()
    assert card.count('"$1"/*.assets') == 2 and card.count('"$DUMP"/*.assets') == 2


# ---- the examples ---------------------------------------------------------------------------------------
def test_the_apps_current_kit_is_listed_as_shipped():
    """kit_shipped.txt lists the kit as it is now, so the next kit change can bring this one up to date"""
    with open(os.path.join(CM.examples_dir(), CM.KIT_FILE), "rb") as f:
        assert CM._kit_digest(f.read()) in CM.shipped_kits()


def _kit_folder(tmp_path, text):
    d = tmp_path / "modes" / "meltdown"
    d.mkdir(parents=True)
    (d / "meltdown.c").write_text("/* mode */\n")
    (d / CM.KIT_FILE).write_bytes(text)
    return d


def test_a_kit_the_app_shipped_is_brought_up_to_the_apps(tmp_path, monkeypatch):
    old = b"/* an earlier app's kit */\r\n"
    d = _kit_folder(tmp_path, old)
    monkeypatch.setattr(CM, "shipped_kits", lambda: {CM._kit_digest(old)})
    said = []
    assert CM.refresh_kit(str(d), log=lambda m, *a, **k: said.append(m)) == "refreshed"
    with open(os.path.join(CM.examples_dir(), CM.KIT_FILE), "rb") as f:
        assert (d / CM.KIT_FILE).read_bytes() == f.read()
    assert any("brought up to this app's kit" in m for m in said)
    assert CM.refresh_kit(str(d)) == "current"


def test_an_edited_kit_is_left_as_it_is(tmp_path, monkeypatch):
    mine = b"/* my own kit */\n"
    d = _kit_folder(tmp_path, mine)
    said = []
    assert CM.refresh_kit(str(d), log=lambda m, *a, **k: said.append(m)) == "edited"
    assert (d / CM.KIT_FILE).read_bytes() == mine
    assert any("not one the app shipped" in m for m in said)


def test_a_mode_without_a_kit_is_left_alone(tmp_path):
    d = tmp_path / "modes" / "mine"
    d.mkdir(parents=True)
    assert CM.refresh_kit(str(d)) == "none"
    assert not (d / CM.KIT_FILE).exists()


def test_the_card_build_brings_the_kit_up_before_it_compiles(tmp_path, monkeypatch):
    old = b"/* an earlier app's kit */\n"
    d = _kit_folder(tmp_path, old)
    monkeypatch.setattr(CM, "shipped_kits", lambda: {CM._kit_digest(old)})
    seen = {}

    class Ex:
        def to_exec_path(self, p):
            return p

        def run(self, cmd, timeout=None):
            seen["kit"] = (d / CM.KIT_FILE).read_bytes()
            raise RuntimeError("no compiler here")

    with pytest.raises(MW.ModeWriteError):
        MW.compile_code_object([str(d / "meltdown.c")], str(tmp_path / "out" / "mode.so"), executor=Ex())
    with open(os.path.join(CM.examples_dir(), CM.KIT_FILE), "rb") as f:
        assert seen["kit"] == f.read()
