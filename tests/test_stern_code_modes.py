"""A CODE mode carries its own clip, screen, music and calls through the project (the intricate modes'
own audio and video): plugins/stern/code_modes.py, the code half of Write (mode_write), and the SDK
header the mode reads them with (tools/spike2_emu/modes/sdk/pad_mode_assets.h).

Desk only: no card, no rig. The film cuts run on a SYNTHETIC film made with ``ffmpeg -f lavfi`` and
named like a film of the collection (nothing of a real film is in the repo), and skip without ffmpeg.
The compile of the code modes (build_mode.sh in the app's Linux) is stubbed where Write is planned.
"""
import json
import os
import re
import subprocess
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
EX = os.path.join(SDK, "examples")


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
    tmnt = MP.profile_from_port(MR.port_file("turtles_pro", "1.59"))
    assert MW.choose_code_sounds(project, code, (True, ""), tmnt, log=lambda m, *a: said.append(m)) == []
    assert "no stock requests to carry them" in said[-1]


def test_a_code_mode_asking_more_calls_than_carriers_keeps_the_ones_it_got(tmp_path):
    cues = ["c%02d" % i for i in range(16)]
    project = _code_project(tmp_path, calls=cues, music=False)
    said = []
    got = MW.choose_code_sounds(project, CM.list_code(project), (True, ""), GZ,
                                taken=list(MS._JP_CALLS[:10]), log=lambda m, *a: said.append(m))
    assert len(got) == len(MS._JP_CALLS) - 10
    assert any("is not put on this card" in s for s in said)


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
def test_the_five_intricate_modes_are_the_code_examples_and_their_recipes_fit():
    assert CM.example_names() == ["KING GHIDORAH", "OXYGEN DESTROYER", "MASER BARRAGE", "FINAL WARS", "ANGUIRUS"]
    for ex in CM.EXAMPLES:
        src = open(os.path.join(EX, ex["source"]), encoding="utf-8").read()
        assert '#define FOLDER             "%s"' % ex["slug"] in src
        for h in ex["headers"]:
            assert os.path.isfile(os.path.join(EX, h))
        r = ex["recipe"]
        assert 0 < r["clip"]["length"] <= 8.0 and r["clip"]["crop"] in ("fill", "letterbox")
        assert 10.0 <= r["music"]["length"] <= 30.0
        assert abs(r["music"]["length"] * 100 - round(r["music"]["length"] * 100)) < 1e-6   # 10 ms steps
        cues = set(re.findall(r'pa_call\(&own, (?:[^"]*\? )?"(\w+)"(?: : "(\w+)")?', src))
        named = {c for pair in cues for c in pair if c}
        assert set(r["calls"]) <= named, (ex["name"], set(r["calls"]) - named)
        for cue, c in r["calls"].items():
            assert 0 < c["length"] <= 4.0 and CM.CUE_RE.match(cue)
        for part in [r["clip"], r["art"], r["music"]] + list(r["calls"].values()):
            assert part["film"] in CM.FILMS and part["film"] in CM.FILM_TITLES
            assert "—" not in part.get("what", "")
    total = sum(len(ex["recipe"]["calls"]) for ex in CM.EXAMPLES)
    assert total <= len(MS._JP_CALLS)                  # every call of the five has a carrier
    assert len(CM.EXAMPLES) <= len(MS._BEDS_LE116)     # and every music a bed of its own


def test_an_example_without_its_films_is_added_with_its_code_and_says_which(tmp_path):
    project = str(tmp_path / "p")
    os.makedirs(project)
    slug, missing = CM.add_example(project, "OXYGEN DESTROYER", dirs=[str(tmp_path)])
    assert slug == "oxygen_destroyer" and missing == ["g54", "des95"]
    folder = MP.mode_folder(project, slug)
    assert sorted(os.listdir(folder)) == ["assets.json", "intricate_kit.h", "oxygen_destroyer.c"]
    spec = CM.load(project, slug)
    assert spec.screen and not spec.clip and not spec.music and not spec.calls
    assert spec.film["recipe"]["music"]["film"] == "des95"
    assert "Godzilla (1954)" in CM.missing_words(missing) and " and " in CM.missing_words(missing)
    with pytest.raises(CM.CodeModeError, match="already in this project"):
        CM.add_example(project, "OXYGEN DESTROYER")


# ---- cutting from a film (a synthetic one) ---------------------------------------------------------------
def _ffmpeg():
    from pinball_decryptor.core import audio
    ff = audio.find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    return ff


def _synthetic_film(folder, name, ffmpeg, seconds=14):
    """A small film under a collection file name: a test pattern and a stereo chord."""
    os.makedirs(folder, exist_ok=True)
    out = os.path.join(folder, name)
    r = subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc2=s=640x360:r=24:d=%d" % seconds, "-f", "lavfi", "-i",
                        "aevalsrc=exprs='0.3*sin(2*PI*220*t)+0.2*sin(2*PI*330*t)|0.3*sin(2*PI*277*t)':s=48000:d=%d"
                        % seconds, "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", out],
                       capture_output=True)
    if r.returncode != 0 or not os.path.isfile(out):
        pytest.skip("this ffmpeg cannot make the synthetic film: %s" % r.stderr[-200:])
    return out


def test_an_examples_recipe_is_cut_with_the_film_cutter(tmp_path):
    ff = _ffmpeg()
    films = str(tmp_path / "films")
    _synthetic_film(films, CM.FILMS["fw04"], ff)
    ex = {"name": "TEST WARS", "slug": "test_wars", "seconds": 40,
          "recipe": {"clip": {"film": "fw04", "from": 1.0, "length": 3.0, "crop": "fill"},
                     "art": {"film": "fw04", "at": 2.0, "crop": "letterbox", "band": 60, "band_below": True},
                     "music": {"film": "fw04", "from": 2.0, "length": 10.0},
                     "calls": {"won": {"film": "fw04", "from": 3.0, "length": 1.5},
                               "spike": {"film": "fw04", "from": 4.0, "length": 1.0, "priority": 3}}}}
    project = str(tmp_path / "p")
    spec = CM.cut_example(project, "test_wars", ex, [films], ffmpeg=ff)
    folder = MP.mode_folder(project, "test_wars")
    assert spec.clip == "clip.mp4" and spec.screen_art == "screen.png" and spec.words_on_art
    assert spec.music == "music.wav" and spec.calls == {"won": "won.wav", "spike": {"wav": "spike.wav", "priority": 3}}
    assert spec.film["dir"] == films
    from PIL import Image
    art = Image.open(os.path.join(folder, "screen.png"))
    assert art.width == 640 and art.height % 4 == 0
    band = np.asarray(art.convert("RGB"))[-50:, :, :]
    assert band.max() < 40                                 # the words' band under the frame is dark
    with wave.open(os.path.join(folder, "music.wav")) as w:
        assert (w.getnchannels(), w.getframerate(), w.getnframes()) == (2, 44100, 1000 * 441)
        loop = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, 2).astype(float)
    assert MS._seam_ok(loop / 32768.0)                     # it runs from its end into its start
    for cue, ch in (("won", 1), ("spike", 1)):
        with wave.open(os.path.join(folder, cue + ".wav")) as w:
            assert w.getnchannels() == ch and w.getframerate() == 44100
    assert CM.validate(spec, folder) == []


def test_the_screen_words_sit_on_the_pictures_band(tmp_path):
    from pinball_decryptor.plugins.stern import mode_assets as MA
    project = _code_project(tmp_path)
    folder = MP.mode_folder(project, "ghidorah_heads")
    from PIL import Image
    Image.new("RGB", (640, 360), (200, 50, 50)).save(os.path.join(folder, "frame.png"))
    CM.compose_art(os.path.join(folder, "frame.png"), os.path.join(folder, "screen.png"))
    spec = CM.load(project, "ghidorah_heads")
    spec.screen_art, spec.words_on_art = "screen.png", True
    CM.save(project, "ghidorah_heads", spec)
    (screen,) = MA._code_screens(project, CM.list_code(project), GZ)
    assert screen["name"] == "PadMode_ghidorah_heads_Screen" and screen["words"] == "KING GHIDORAH"
    assert screen["words_at"] == (20.0, 346.0)
    assert screen["words_name"] == "PadMode_ghidorah_heads_Screen_Words"
    art = np.asarray(screen["art_rgba"])
    assert art.shape[:2] == (360, 640) and art[-5:, :, :3].max() < 60 and art[10, 10, 0] == 200
    spec.words_on_art = False
    CM.save(project, "ghidorah_heads", spec)
    (screen,) = MA._code_screens(project, CM.list_code(project), GZ)
    assert screen["words_at"] is None                        # under the picture, as a form mode's


def test_the_recipes_file_is_plain_json_with_the_films_named():
    doc = json.load(open(os.path.join(EX, CM.RECIPES_FILE), encoding="utf-8"))
    assert set(doc["films"]) == set(doc["titles"])
    for name in doc["films"].values():
        assert name.endswith(".mp4") and "\\" not in name and "/" not in name
