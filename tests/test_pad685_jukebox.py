"""PAD-685 (an owner rebuilding The Beatles: "a weighted song selection", 60 and more songs, any of them in any
song mode, never the same twice in a game, each with its own intro video): THE JUKEBOX.

The project lists its songs (``jukebox`` ``{"songs": [{"audio", "video", "weight"}]}``); a Write puts each
song's audio in the sound bank whole as a record of its own (the sounds in turn's road under a pseudo mode
of its own), each song's video in the video bank as ``PadJukebox<k>`` (the random clips' road), and
``jmode`` / ``jsong`` lines in sounds.cfg; pad_mode_runtime.c "the jukebox" draws a song at each song
mode's start and hands it every record and intro clip of that mode."""

import os
import re
import shutil
import subprocess
import sys

import pytest

from pinball_decryptor.plugins.stern import clip_variants as CV
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import jukebox as JB
from pinball_decryptor.plugins.stern import sound_modes as SMo

HERE = os.path.dirname(os.path.abspath(__file__))
SDK = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
PORT = os.path.join(SDK, "ports", "beatles-1.29.port")


class _Prof:
    game_dir, version, label = "beatles", "1.29", "The Beatles 1.29"

    def lcd(self, which):
        return "assets/lcd/auto_loaded/60ed7e5036b8ce09d35a3e101ea6fc1380b37d97"


class _Other:
    game_dir, version, label = "godzilla_le", "1.16", "Godzilla Premium/LE 1.16"


# ---- the project's record ------------------------------------------------------------------------
def test_the_record_keeps_each_song_s_audio_video_and_weight():
    box = JB.clean({"songs": [{"audio": "a.wav", "video": "a.mov", "weight": 3},
                              {"audio": "b.wav", "weight": 9}, {"audio": "c.wav", "weight": "x"},
                              {"video": "no audio.mov"}, {"audio": "  "}, "junk"]})
    assert [(s.audio, s.video, s.weight) for s in box.songs] == [
        ("a.wav", "a.mov", 3), ("b.wav", "", 3), ("c.wav", "", JB.DEFAULT_WEIGHT)]
    again = JB.clean(JB.to_json(box))
    assert [(s.audio, s.video, s.weight) for s in again.songs] == [
        ("a.wav", "a.mov", 3), ("b.wav", "", 3), ("c.wav", "", 2)]
    assert JB.to_json(JB.Jukebox()) is None
    assert len(JB.clean({"songs": [{"audio": "%d.wav" % i} for i in range(200)]}).songs) == JB.MAX_SONGS


def test_the_record_lives_in_the_project_s_sidecar(tmp_path):
    JB.save(str(tmp_path), JB.Jukebox(songs=[JB.Song("a.wav", "a.mov", 1)]))
    assert [(s.audio, s.video, s.weight) for s in JB.load(str(tmp_path)).songs] == [("a.wav", "a.mov", 1)]
    JB.save(str(tmp_path), JB.Jukebox())
    assert not JB.load(str(tmp_path)).any


# ---- which titles ---------------------------------------------------------------------------------
def test_the_beatles_has_five_song_modes_and_nothing_else_has_a_jukebox():
    modes = JB.song_modes(_Prof())
    assert [m.name for m in modes] == ["All My Loving", "Drive My Car", "I Should Have Known Better",
                                       "Ticket to Ride", "It Won't Be Long"]
    assert [m.records for m in modes] == [(419, 848), (200, 417), (753, 669), (722, 431), (42, 667)]
    assert JB.title_refusal(_Prof()) == ""
    assert "not offered" in JB.title_refusal(_Other())
    assert JB.title_refusal(None) == JB.NO_TITLE


def test_each_song_mode_s_start_is_a_site_of_the_beatles_port():
    with open(PORT, encoding="utf-8") as f:
        port = f.read()
    for m in JB.song_modes(_Prof()):
        assert re.search(r"^site %s\s" % m.site, port, re.M), m.site
        assert len(m.intros) == len(m.clips) == 2 and len(m.records) == 2
    assert re.search(r"^site surface_set_video\s", port, re.M)
    assert re.search(r"^site sound_lookup\s", port, re.M)


def test_the_songs_are_made_like_the_longest_song_mode_record(tmp_path):
    (tmp_path / "audio").mkdir()
    for idx, size in ((848, 10), (667, 30), (669, 20), (5, 99)):
        (tmp_path / "audio" / ("idx%04d.wav" % idx)).write_bytes(b"x" * size)
    assert JB.host_slot(str(tmp_path), _Prof()) == "audio/idx0667.wav"
    assert JB.slot_rel(str(tmp_path), 848) == "audio/idx0848.wav"
    assert JB.slot_rel(str(tmp_path), 1) == ""


# ---- the build's files ------------------------------------------------------------------------------
def test_a_jukebox_song_is_a_file_in_turn_of_its_own_never_a_music_mode_s():
    k = SMo.juke_mode(3)
    assert SMo.is_juke(k) and SMo.is_turn(k) and not SMo.is_mode_turn(k) and not SMo.is_attract(k)
    assert SMo.turn_of(k) == 3
    assert not SMo.is_juke(SMo.mode_turn(8, 16)) and SMo.is_mode_turn(SMo.mode_turn(8, 16))
    assert SMo.who(k) == "Jukebox" and SMo.what("audio/idx0667.wav", k) == "song 3"
    m = SMo.Modes(jukebox=["a.wav", "b.wav"])
    assert m.any and m.files() == []                   # until a build names the slot they are made like
    m.juke_rel = "audio/idx0667.wav"
    assert m.files() == [("audio/idx0667.wav", SMo.juke_mode(1), "a.wav"),
                         ("audio/idx0667.wav", SMo.juke_mode(2), "b.wav")]
    assert m.level("audio/idx0667.wav", SMo.juke_mode(1)) == 0


def test_the_runtime_table_names_the_song_modes_and_the_songs():
    text = SMo.cfg_text(0, 0, [], True, jukebox={
        "modes": [("block_start_3", ["FeatureStarts.Spinner_Start", "Short.Spinner"],
                   [bytes.fromhex("46bf4c72d2500080"), bytes.fromhex("161b497d4c7a0000")])],
        "songs": [(3, b"\x01" * 8, "PadJukebox1"), (1, b"\x02" * 8, "")]})
    assert text.splitlines()[1:] == [
        "only",
        "jmode\tblock_start_3\tFeatureStarts.Spinner_Start,Short.Spinner\t46bf4c72d2500080,161b497d4c7a0000",
        "jsong\t3\t0101010101010101\tPadJukebox1",
        "jsong\t1\t0202020202020202\t-"]
    assert "jmode" not in SMo.cfg_text(0, 0, [], True, jukebox={"modes": [], "songs": []})


def _juke_modes(tmp_path, songs):
    m = SMo.Modes(jukebox=[s.audio for s in songs], juke_rel="audio/idx0667.wav")
    m.juke_plan = {"box": JB.Jukebox(songs=songs), "prof": _Prof()}
    return m


def test_the_build_writes_each_song_mode_and_each_song_that_landed(tmp_path):
    video = tmp_path / "s1.mov"
    video.write_bytes(b"v")
    songs = [JB.Song("s1.wav", str(video), 3), JB.Song("s2.wav", "", 1), JB.Song("s3.wav", "gone.mov", 2)]
    params = [{"idx": i, "findkey": bytes([i % 256]) * 8} for m in JB.song_modes(_Prof()) for i in m.records]
    params += [{"idx": 900, "findkey": b"A" * 8, "grown": True},
               {"idx": 901, "findkey": b"B" * 8, "grown": True},
               {"idx": 902, "findkey": b"C" * 8, "grown": True}]
    used = [{"rel": "audio/idx0667.wav", "slot": 667, "mode": SMo.juke_mode(k), "host": 899 + k, "db": 0}
            for k in (1, 2, 3)]
    used[2]["bank"], used[2]["bank_idx"] = 4, 7          # a song in a sound bank has no key to swap in
    logs = []
    path = E._sound_modes_cfg("gr", {}, params, {}, used, _juke_modes(tmp_path, songs), True,
                              str(tmp_path / "out"), lambda t, lvl="info": logs.append((lvl, t)))
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    jm = [ln for ln in lines if ln.startswith("jmode")]
    assert jm[0] == "jmode\tblock_start_0\tFeatureStarts.Frenzy_Start,Feature_Starts_Short.Frenzy_Start_Short\t%s,%s" % (
        (bytes([419 % 256]) * 8).hex(), (bytes([848 % 256]) * 8).hex())
    assert len(jm) == 5
    assert [ln for ln in lines if ln.startswith("jsong")] == [
        "jsong\t3\t%s\tPadJukebox1" % (b"A" * 8).hex(),
        "jsong\t1\t%s\t-" % (b"B" * 8).hex()]                 # no video, and song 3 is in a bank
    assert not [ln for ln in lines if ln.startswith(("turn", "tsid", "random"))]
    assert any("song 3" in t and "left out" in t for lvl, t in logs if lvl == "warning")
    # the card's record names the songs that landed
    assert "#jsong\t1\t667\t900\t-\taudio/idx0667.wav\ts1.wav" in lines
    assert not any(ln.startswith("#jsong\t3\t") for ln in lines)


def test_no_song_mode_in_the_bank_leaves_the_jukebox_off(tmp_path):
    songs = [JB.Song("s1.wav", "", 2)]
    params = [{"idx": 900, "findkey": b"A" * 8, "grown": True}]
    used = [{"rel": "audio/idx0667.wav", "slot": 667, "mode": SMo.juke_mode(1), "host": 900, "db": 0}]
    logs = []
    got = E._jukebox_lines(params, used, _juke_modes(tmp_path, songs), lambda t, lvl="info": logs.append(t))
    assert got is None and any("not put on this card" in t for t in logs)


def test_a_song_is_never_cut_to_its_slot_s_length(tmp_path, monkeypatch):
    """the game plays a record it is handed whole (emulator: a 55 s record in a 19.7 s opening's place,
    the body looked up 55 s later), so a song is not cut as a file in turn is"""
    cut = []
    monkeypatch.setattr(SMo, "convert", lambda project, rel, mode, src, log=None: src)
    monkeypatch.setattr(SMo, "cut", lambda wav, frames: cut.append(frames) or wav)
    monkeypatch.setattr(E, "_wav_frames_44k", lambda wav: 44100 * 100)
    params = [{"idx": 667, "length": 44100 * 55, "chan": 2, "findkey": b"S" * 8},
              {"idx": 5, "length": 44100 * 90, "chan": 2, "findkey": b"H" * 8}]
    m = SMo.Modes(jukebox=["song.wav"], juke_rel="audio/idx0667.wav")
    _edits, grows, used = E._sound_modes_grow(str(tmp_path), params, {}, {}, m, lambda *a, **k: None)
    assert not cut
    assert used and used[0]["frames"] == 44100 * 100 and used[0]["mode"] == SMo.juke_mode(1)
    # a file in turn of the same slot still is
    m = SMo.Modes(turns={"audio/idx0667.wav": ["b.wav"]})
    E._sound_modes_grow(str(tmp_path), params, {}, {}, m, lambda *a, **k: None)
    assert len(cut) == 1 and 44100 * 54 < cut[0] <= 44100 * 55   # its slot's length as the card plays it


# ---- the intro videos -------------------------------------------------------------------------------
def test_the_intro_videos_are_made_like_the_first_song_mode_s_intro(tmp_path, monkeypatch):
    (tmp_path / "video").mkdir()
    (tmp_path / "video" / "FeatureStarts_Frenzy_Start.mov").write_bytes(b"x")
    a, b = tmp_path / "a.mov", tmp_path / "b.mov"
    a.write_bytes(b"a")
    b.write_bytes(b"b")
    JB.save(str(tmp_path), JB.Jukebox(songs=[JB.Song("1.wav", str(a)), JB.Song("2.wav", ""),
                                             JB.Song("3.wav", str(b)), JB.Song("4.wav", "gone.mov")]))
    assert CV.jukebox_clips(str(tmp_path), _Prof()) == (
        "video/FeatureStarts_Frenzy_Start.mov", [(1, str(a)), (3, str(b))])
    assert CV.jukebox_clips(str(tmp_path), _Other()) is None
    monkeypatch.setenv(JB.GATE_ENV, "0")
    assert CV.jukebox_clips(str(tmp_path), _Prof()) is None


def test_the_intro_videos_go_into_the_bank_by_name_and_not_into_clips_cfg(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import video_bank as VB
    added = []

    class _Parsed:
        class library:
            entries = []

    monkeypatch.setattr(VB, "parse", lambda bank: _Parsed())
    monkeypatch.setattr(VB, "add_clip", lambda bank, name, size: (added.append(name) or bank + b"+",
                                                                   {"path": "2.asset/%d.asset" % (200 + len(added))}))
    monkeypatch.setattr(CV, "jukebox_clips", lambda project, prof: ("video/x.mov", [(1, "a.mov"), (3, "b.mov")]))
    staged = tmp_path / "staged.mov"
    staged.write_bytes(b"s")
    calls = []

    def stage_fn(project, rel, files, log=None, cancel=None, **kw):
        calls.append((rel, list(files), kw))
        return [str(staged)] * len(files)

    vb = CV.build(str(tmp_path), _Prof(), b"bank", str(tmp_path / "out"), True, variants={},
                  stage_fn=stage_fn)
    assert added == ["PadJukebox1", "PadJukebox3"]
    assert calls == [("video/x.mov", ["a.mov", "b.mov"], {"tag": "juke", "first": 1, "what": "jukebox song"})]
    assert vb.bank == b"bank++" and len(vb.new) == 2 and vb.slots == []
    with open(vb.cfg, encoding="utf-8") as f:
        assert [ln for ln in f.read().splitlines() if not ln.startswith("#")] == ["only"]


# ---- the runtime -----------------------------------------------------------------------------------
def test_the_runtime_reads_the_jukebox_lines_and_swaps_at_the_lookup_and_the_surface():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "jmode")' in c and 'str_eq(f[0], "jsong")' in c
    assert "if (juke_live && r[1] && juke_lookup(r)) return;" in c
    assert "if (sv_juke) juke_set_video(r);" in c
    assert "juke_arm();" in c
    assert re.search(r"#define JUKE_SONGS\s+%d\b" % JB.MAX_SONGS, c)


_HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
@STATE@
@FUNCS@
int main(int argc, char **argv)
{
    unsigned i, n = (unsigned)atoi(argv[1]), draws = (unsigned)atoi(argv[2]);
    for (i = 0; i < n; i++) jsong[i].weight = (unsigned char)atoi(argv[3 + i]);
    n_jsong = n;
    for (i = 0; i < draws; i++) printf("%d ", juke_draw());
    printf("\n");
    return 0;
}
"""


def _c_function(src, signature_re):
    m = re.search(signature_re, src)
    assert m, signature_re
    i, depth = src.index("{", m.start()), 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[m.start():j + 1]
    raise AssertionError(signature_re)


@pytest.fixture(scope="module")
def draws(tmp_path_factory):
    if os.name == "nt" or sys.platform == "darwin":
        pytest.skip("the harness needs a host ELF C toolchain")
    cc = next((c for c in ("gcc", "cc", "clang") if shutil.which(c)), None)
    if not cc:
        pytest.skip("no host C compiler")
    with open(RUNTIME, encoding="utf-8") as f:
        src = f.read()
    defs = "\n".join(re.findall(r"^#define JUKE_\w+.*$", src, re.M))
    jsong = src[src.index("struct jsong {"):src.index("};", src.index("struct jsong {")) + 2]
    state = (defs + "\n" + jsong + "\nstatic struct jsong jsong[JUKE_SONGS];\nstatic unsigned n_jsong;\n"
             "static short juke_recent[JUKE_RECENT];\nstatic unsigned n_juke_recent;\nstatic unsigned clipv_rng;\n")
    funcs = [_c_function(src, r) for r in (r"static unsigned clipv_rand\(void\)", r"static short juke_draw\(void\)")]
    d = tmp_path_factory.mktemp("juke")
    (d / "h.c").write_text(_HARNESS.replace("@STATE@", state).replace("@FUNCS@", "\n".join(funcs)))
    exe = d / "h"
    r = subprocess.run([cc, "-std=gnu17", "-O1", "-Wall", "-o", str(exe), str(d / "h.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def run(weights, n):
        out = subprocess.run([str(exe), str(len(weights)), str(n)] + [str(w) for w in weights],
                             capture_output=True, text=True, check=True).stdout.split()
        return [int(x) for x in out]
    return run


def test_no_song_comes_back_within_five_draws(draws):
    got = draws([2] * 12, 600)
    assert set(got) == set(range(12))
    assert all(len(set(got[i:i + 6])) == 6 for i in range(len(got) - 5))


def test_fewer_songs_than_the_window_still_draws_every_time(draws):
    got = draws([1, 1, 1], 60)
    assert all(len(set(got[i:i + 3])) == 3 for i in range(len(got) - 2))    # none of the last two
    assert draws([1], 5) == [0, 0, 0, 0, 0]


def test_a_common_song_comes_up_three_times_as_often_as_a_rare_one(draws):
    got = draws([3] * 10 + [1] * 10, 20000)
    common = sum(1 for k in got if k < 10)
    rare = len(got) - common
    assert 2.0 < common / rare < 3.5          # 3:1 weights, a little evened out by the five-song window


# ---- the Audio tab ---------------------------------------------------------------------------------
def _gui_offer(monkeypatch, juke):
    monkeypatch.setattr(SMo, "offer", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_turns", lambda project, rels, probe=True: ("not here", {}))
    monkeypatch.setattr(SMo, "offer_attract", lambda project, probe=True: "not here")
    monkeypatch.setattr(JB, "offer", lambda project, probe=True: juke)


def test_the_audio_tab_keeps_the_jukebox_s_songs(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project, _sidecar, _wav as wav
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, "")
    proj = _project(tmp_path)
    a, b = str(tmp_path / "mine" / "Hey Jude.wav"), str(tmp_path / "mine" / "Revolution.wav")
    wav(a)
    wav(b)
    v = tmp_path / "mine" / "Hey Jude intro.mp4"
    v.write_bytes(b"v")
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, proj)
        st = w.state("audio")["jukebox"]
        assert st["n"] == 0 and st["why"] == ""
        w.answers.append([a, b])
        rows = w.call("audio.jukebox_action", "add")
        assert [g["audio"] for g in rows["songs"]] == ["Hey Jude.wav", "Revolution.wav"]
        assert [g["weight_word"] for g in rows["songs"]] == ["Normal", "Normal"]
        w.answers.append(str(v))
        rows = w.call("audio.jukebox_action", "video:1")
        assert rows["songs"][0]["video"] == "Hey Jude intro.mp4" and rows["songs"][1]["video"] == ""
        rows = w.call("audio.jukebox_action", "weight:2:1")
        assert rows["songs"][1]["weight_word"] == "Rare"
        rows = w.call("audio.jukebox_action", "up:2")
        assert [g["audio"] for g in rows["songs"]] == ["Revolution.wav", "Hey Jude.wav"]
        assert _sidecar(proj)["jukebox"]["songs"] == [
            {"audio": os.path.normpath(b), "weight": 1},
            {"audio": os.path.normpath(a), "weight": 2, "video": os.path.normpath(str(v))}]
        assert w.state("audio")["jukebox"]["n"] == 2
        w.call("audio.jukebox_action", "play:2")
        assert w.state("audio")["panes"]["rep"]["name"] == "Jukebox song 2: Hey Jude.wav"
        rows = w.call("audio.jukebox_action", "off:1")
        assert [g["audio"] for g in rows["songs"]] == ["Hey Jude.wav"]
    with web_app(tmp_path / "again", mfr="stern", era="spike2") as w:      # a fresh session has them back
        _open(w, proj)
        assert w.call("audio.jukebox_open")["songs"][0]["video"] == "Hey Jude intro.mp4"


def test_a_game_with_no_song_modes_shows_no_jukebox(tmp_path, monkeypatch):
    from tests.test_webui_audio import _open, _project
    from tests.webui_harness import web_app
    _gui_offer(monkeypatch, None)
    with web_app(tmp_path, mfr="stern", era="spike2") as w:
        _open(w, _project(tmp_path))
        assert w.state("audio")["jukebox"] is None
        assert w.call("audio.jukebox_action", "add")["songs"] == []


def test_the_page_has_the_jukebox_window():
    with open(os.path.join(HERE, "..", "pinball_decryptor", "webui", "static", "js", "tabs", "audio.js"),
              encoding="utf-8") as f:
        js = f.read()
    assert 'call("audio.jukebox_open")' in js and "function JukeboxModal" in js
    for a in ('"add"', "`video:${g.k}`", "`weight:${g.k}:${v}`", "`off:${g.k}`", "`play:${g.k}`"):
        assert a in js, a
