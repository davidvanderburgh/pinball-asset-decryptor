"""PAD-1317: the co-op awards ceremony's own music - a track of the owner's that plays while the award cards show at a
co-op or team game's end, the game's own sounds faded under it.

DoomWalrus666: "Please add an option in the mode tab in the characters builder to add a custom audio track to play
during the award ceremony"."""
import os
import subprocess
import wave
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import sound_modes as SM
from tests import test_pad1017_coop_turns as T
from tests import test_spike2_mode_roster as R


@pytest.fixture
def project(tmp_path):
    p = tmp_path / "project"
    p.mkdir()
    return str(p)


def _file(tmp_path, name, data=b"not really a sound"):
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def _ffmpeg():
    from pinball_decryptor.core.audio import find_ffmpeg
    ff = find_ffmpeg()
    if not ff:
        pytest.skip("no ffmpeg")
    return ff


# ---- the owner's track, kept in the project --------------------------------------------------------------------------
def test_ceremony_music_kept_beside_the_ceremony_video(project, tmp_path):
    CP.save_ceremony(project, _file(tmp_path, "awards.mp4", b"video"))
    chars = CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.mp3"))
    assert chars["ceremony_sound"] == "coop/ceremony_music.mp3" and chars["ceremony"] == "coop/ceremony_video.mp4"
    assert CP.ceremony_sound_path(project) == os.path.join(project, "coop", "ceremony_music.mp3")
    CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.wav"))            # another: the old one goes
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["ceremony_music.wav", "ceremony_video.mp4"]
    CP.save_ceremony_sound(project, _file(tmp_path, "theme.mkv"))              # a video's sound is taken too
    assert CP.ceremony_sound_path(project).endswith("ceremony_music.mkv")
    CP.save_ceremony_sound(project, None)
    assert "ceremony_sound" not in CP.load_characters(project) and CP.ceremony_sound_path(project) == ""
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["ceremony_video.mp4"]
    with pytest.raises(CP.CoopError):
        CP.save_ceremony_sound(project, _file(tmp_path, "notes.txt"))


def test_the_music_alone_keeps_the_characters_record(project, tmp_path):
    CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.ogg"))
    assert CP.load_characters(project)["ceremony_sound"] == "coop/ceremony_music.ogg"


def test_settings_file_carries_the_ceremony_music(project, tmp_path):
    CP.save(project, True)
    CP.save_ceremony(project, _file(tmp_path, "awards.mp4", b"awards bytes"))
    CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.flac", b"music bytes"))
    zpath = str(tmp_path / "coop.zip")
    CP.export_settings(project, zpath)
    other = tmp_path / "other"
    other.mkdir()
    got = CP.import_settings(str(other), zpath)
    assert got["pictures"] == 2
    with open(CP.ceremony_sound_path(str(other)), "rb") as f:
        assert f.read() == b"music bytes"
    assert CP.ceremony_sound_path(str(other)).endswith("ceremony_music.flac")


def test_the_track_is_made_a_wav_no_longer_than_the_cap(project, tmp_path):
    ff = _ffmpeg()
    src = str(tmp_path / "long.mp3")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=75", "-ac", "2", src],
                   check=True)
    CP.save(project, True)
    CP.save_ceremony_sound(project, src)
    from pinball_decryptor.plugins.stern import engine as E
    lines = []
    got = E._coop_ceremony_wav(project, lambda m, *a: lines.append(m))
    assert got and os.path.basename(got).startswith("coop_ceremony_"), lines
    with wave.open(got) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 44100, 2)
        assert abs(w.getnframes() / 44100.0 - CP.CEREMONY_SOUND_MAX_SECONDS) < 0.2
    assert E._coop_ceremony_wav(project, lines.append) == got                # the cache's, not made again
    CP.save_ceremony_sound(project, None)
    assert E._coop_ceremony_wav(project, lines.append) == ""


def test_no_music_without_co_op(project, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.wav"))
    assert E._coop_ceremony_wav(project, lambda *a: None) == ""               # co-op off: none


# ---- the build: its sound on the intro's carrier, its sounds.cfg line ---------------------------------------------
def test_the_music_rides_the_intros_carrier():
    m = SM.CEREMONY_MODE
    assert m == SM.INTRO_MODE + SM.PICKED_MAX + 1 and SM.is_intro(m) and SM.is_ceremony(m)
    assert SM.picked_of(m) == 0 and not SM.is_ceremony(SM.INTRO_MODE) and not SM.is_juke(m) and not SM.is_shot(m)
    assert SM.who(m) == "Co-op awards" and SM.what("a", m) == "the co-op awards ceremony's music"
    assert SM.tag("a", m) == "the co-op awards ceremony's music" and "award cards" in SM.when(m)
    assert SM.turn_of(m) == 1 and SM.Modes().level("a", m) == 0
    modes = SM.Modes()
    modes.ceremony = "music.wav"
    assert modes.coop and modes.any and modes.files() == []                   # no carrier yet
    modes.intro_rel = "audio/idx1725.wav"
    assert modes.files() == [("audio/idx1725.wav", m, "music.wav")]


def test_sounds_cfg_names_the_music():
    key, host, music = bytes(range(8)), bytes(range(8, 16)), bytes(range(24, 32))
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": host, "ms": 12000, "picks": [],
                                              "ceremony": (music, 42000)})
    assert "ccer\t979\t%s\t%s\t42000" % (key.hex(), music.hex()) in text
    assert "cintro\t979\t" in text
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": None, "ms": 0, "picks": [],
                                              "ceremony": (music, 900)})
    assert "cintro" not in text and "ccer\t979\t" in text                    # the music without an intro
    assert "ccer" not in SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": host, "ms": 1,
                                                            "picks": []})


def test_the_build_splits_the_musics_record_from_the_intros(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    params = [{"idx": 1725, "findkey": b"K" * 8}, {"idx": 9001, "findkey": b"I" * 8, "grown": True},
              {"idx": 9003, "findkey": b"C" * 8, "grown": True}]
    modes = SimpleNamespace(intro_plan={"request": 979, "slot": 1725})
    used = [{"slot": 1725, "host": 9001, "mode": SM.INTRO_MODE, "frames": 44100},
            {"slot": 1725, "host": 9003, "mode": SM.CEREMONY_MODE, "frames": 44100 * 30}]
    got = E._intro_lines(params, used, modes, lambda *a, **k: None)
    assert got["host"] == b"I" * 8 and got["ms"] == 1000 and got["picks"] == []
    assert got["ceremony"] == (b"C" * 8, 30000)
    only = E._intro_lines(params, used[1:], modes, lambda *a, **k: None)      # the music alone
    assert only["host"] is None and only["ceremony"] == (b"C" * 8, 30000) and only["key"] == b"K" * 8


# ---- the runtime ------------------------------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    printf("has %d %d %d\n", ccer_has(979, 1), ccer_has(0, 1), ccer_has(979, 0));
    return 0;
}
"""


def test_the_runtime_plays_it_only_when_armed(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", R._lift(src, "static int ccer_has(unsigned request, int live)")))
    assert "has 1 0 0" in out.splitlines()


def test_the_runtime_wiring():
    src = T.RUNTIME.read_text(encoding="utf-8")
    begin = R._lift(src, "static void coop_cer_begin(void)\n{")
    assert "ccer_begin();" in begin
    end = R._lift(src, "static void coop_cer_end(void)\n{")
    assert "ccer_end();" in end
    cards = R._lift(src, "static void coop_cards_show(unsigned n)")
    assert cards.index("coop_cer_begin();") < cards.index("ccer_quiet();") < cards.index("coop_cer_end();")
    play = R._lift(src, "static void ccer_begin(void)")
    assert play.index("ccer_quiet();") < play.index("pm_sound(ccer.request);")            # the game's faded first
    assert "pm_sound_priority(ccer.request, CCER_PRIO_PLAYING, 0);" in play
    assert play.index("ccer.swap_until = ") < play.index("pm_sound(ccer.request);")
    stop = R._lift(src, "static void ccer_end(void)")
    assert "pm_sound_fade(ccer.request, CCER_FADE_MS)" in stop and "ccer.swap_until = 0;" in stop
    assert "pm_sound_priority(ccer.request, CCER_PRIO_IDLE, 0);" in stop
    quiet = R._lift(src, "static void ccer_quiet(void)\n{")
    assert "reqs[i] == ccer.request" in quiet and "pm_sound_fade(reqs[i], CCER_QUIET_MS)" in quiet
    look = R._lift(src, "static void on_sound_lookup(pm_reg *r)")
    assert look.index("ccer_lookup(r)") < look.index("ci_lookup(r)")       # the same carrier key as the intro's
    assert 'str_eq(f[0], "ccer")' in src and "ccer_sound_arm();" in src
    assert "|| ci.request || cpk.request || ccer.request) return;" in src


def test_the_lookup_takes_the_musics_record():
    src = T.RUNTIME.read_text(encoding="utf-8")
    look = R._lift(src, "static int ccer_lookup(pm_reg *r)\n{")
    assert "LOOKUP_TAKE(r, ccer.host);" in look and "key_is(k, ccer.key)" in look and "ccer.swap_until" in look
