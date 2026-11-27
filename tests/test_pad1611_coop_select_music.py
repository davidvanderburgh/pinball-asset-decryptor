"""PAD-1611: the co-op character select's own music - a track of the owner's that loops while a teammate picks a
character, the game's own sounds faded under it, and stops once a character is taken (the game's music asked for
again).

DoomWalrus666: "I would like a feature where on the Modes - Characters menu in PAD I could select an audio/music track
that plays while the character select menu is active. In game, when character select comes up, the assigned music
should loop until a character is chosen, and then return to stock game music."."""
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
def test_select_music_kept_beside_the_awards_music(project, tmp_path):
    CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.wav"))
    chars = CP.save_select_sound(project, _file(tmp_path, "theme.mp3"))
    assert chars["select_sound"] == "coop/select_music.mp3" and chars["ceremony_sound"] == "coop/ceremony_music.wav"
    assert CP.select_sound_path(project) == os.path.join(project, "coop", "select_music.mp3")
    CP.save_select_sound(project, _file(tmp_path, "theme.ogg"))                # another: the old one goes
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["ceremony_music.wav", "select_music.ogg"]
    CP.save_select_sound(project, _file(tmp_path, "clip.mp4"))                 # a video's sound is taken too
    assert CP.select_sound_path(project).endswith("select_music.mp4")
    CP.save_select_sound(project, None)
    chars = CP.load_characters(project)
    assert "select_sound" not in chars and CP.select_sound_path(project) == ""
    assert chars["ceremony_sound"] == "coop/ceremony_music.wav"                # the awards' music untouched
    assert sorted(os.listdir(os.path.join(project, "coop"))) == ["ceremony_music.wav"]
    with pytest.raises(CP.CoopError):
        CP.save_select_sound(project, _file(tmp_path, "notes.txt"))


def test_the_music_alone_keeps_the_characters_record(project, tmp_path):
    CP.save_select_sound(project, _file(tmp_path, "theme.flac"))
    assert CP.load_characters(project)["select_sound"] == "coop/select_music.flac"


def test_settings_file_carries_the_select_music(project, tmp_path):
    CP.save(project, True)
    CP.save_ceremony_sound(project, _file(tmp_path, "fanfare.wav", b"awards bytes"))
    CP.save_select_sound(project, _file(tmp_path, "theme.mp3", b"select bytes"))
    zpath = str(tmp_path / "coop.zip")
    CP.export_settings(project, zpath)
    other = tmp_path / "other"
    other.mkdir()
    got = CP.import_settings(str(other), zpath)
    assert got["pictures"] == 2
    with open(CP.select_sound_path(str(other)), "rb") as f:
        assert f.read() == b"select bytes"
    assert CP.select_sound_path(str(other)).endswith("select_music.mp3")


def test_the_track_is_made_a_wav_no_longer_than_the_cap(project, tmp_path):
    ff = _ffmpeg()
    src = str(tmp_path / "long.mp3")
    subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=550:duration=75", "-ac", "2", src],
                   check=True)
    CP.save(project, True)
    CP.save_select_sound(project, src)
    from pinball_decryptor.plugins.stern import engine as E
    lines = []
    got = E._coop_select_wav(project, lambda m, *a: lines.append(m))
    assert got and os.path.basename(got).startswith("coop_select_"), lines
    with wave.open(got) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (2, 44100, 2)
        assert abs(w.getnframes() / 44100.0 - CP.SELECT_SOUND_MAX_SECONDS) < 0.2
    assert E._coop_select_wav(project, lines.append) == got                  # the cache's, not made again
    CP.save_select_sound(project, None)
    assert E._coop_select_wav(project, lines.append) == ""


def test_no_music_without_co_op(project, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    CP.save_select_sound(project, _file(tmp_path, "theme.wav"))
    assert E._coop_select_wav(project, lambda *a: None) == ""                 # co-op off: none


# ---- the build: its sound on the intro's carrier, its sounds.cfg line ---------------------------------------------
def test_the_music_rides_the_intros_carrier():
    m = SM.SELECT_MODE
    assert m == SM.CEREMONY_MODE + 1 and SM.is_intro(m) and SM.is_select(m) and not SM.is_ceremony(m)
    assert SM.picked_of(m) == 0 and SM.picked_of(SM.CEREMONY_MODE) == 0 and SM.picked_of(SM.INTRO_MODE + 16) == 16
    assert not SM.is_select(SM.INTRO_MODE) and not SM.is_juke(m) and not SM.is_shot(m) and not SM.is_speak(m)
    assert SM.who(m) == "Co-op characters" and SM.what("a", m) == "the co-op character select's music"
    assert SM.tag("a", m) == "the co-op character select's music" and "picks a character" in SM.when(m)
    assert SM.turn_of(m) == 1 and SM.Modes().level("a", m) == 0
    modes = SM.Modes()
    modes.select = "theme.wav"
    assert modes.coop and modes.any and modes.files() == []                   # no carrier yet
    modes.intro_rel = "audio/idx1725.wav"
    assert modes.files() == [("audio/idx1725.wav", m, "theme.wav")]


def test_sounds_cfg_names_the_music():
    key, host, music, sel = bytes(range(8)), bytes(range(8, 16)), bytes(range(24, 32)), bytes(range(40, 48))
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": host, "ms": 12000, "picks": [],
                                              "ceremony": (music, 42000), "select": (sel, 8000)})
    assert "cselm\t979\t%s\t%s\t8000" % (key.hex(), sel.hex()) in text
    assert "ccer\t979\t" in text and "cintro\t979\t" in text
    text = SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": None, "ms": 0, "picks": [],
                                              "select": (sel, 900)})
    assert "cintro" not in text and "ccer" not in text and "cselm\t979\t" in text   # the music without an intro
    assert "cselm" not in SM.cfg_text(0, 0, [], True, intro={"request": 979, "key": key, "host": host, "ms": 1,
                                                             "picks": []})


def test_the_build_splits_the_musics_record_from_the_others(tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    params = [{"idx": 1725, "findkey": b"K" * 8}, {"idx": 9001, "findkey": b"I" * 8, "grown": True},
              {"idx": 9003, "findkey": b"C" * 8, "grown": True}, {"idx": 9004, "findkey": b"S" * 8, "grown": True}]
    modes = SimpleNamespace(intro_plan={"request": 979, "slot": 1725})
    used = [{"slot": 1725, "host": 9001, "mode": SM.INTRO_MODE, "frames": 44100},
            {"slot": 1725, "host": 9003, "mode": SM.CEREMONY_MODE, "frames": 44100 * 30},
            {"slot": 1725, "host": 9004, "mode": SM.SELECT_MODE, "frames": 44100 * 8}]
    got = E._intro_lines(params, used, modes, lambda *a, **k: None)
    assert got["host"] == b"I" * 8 and got["ms"] == 1000 and got["picks"] == []
    assert got["ceremony"] == (b"C" * 8, 30000) and got["select"] == (b"S" * 8, 8000)
    only = E._intro_lines(params, used[2:], modes, lambda *a, **k: None)      # the music alone
    assert only["host"] is None and only["ceremony"] is None and only["select"] == (b"S" * 8, 8000)
    assert only["key"] == b"K" * 8


# ---- the runtime ------------------------------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
#define CSELM_AGAIN_MS 300ul
@FNS@
int main(void)
{
    printf("want %d %d %d %d %d %d\n", cselm_wanted(979, 1, 1, 1, 1), cselm_wanted(0, 1, 1, 1, 1),
           cselm_wanted(979, 0, 1, 1, 1), cselm_wanted(979, 1, 0, 1, 1), cselm_wanted(979, 1, 1, 0, 1),
           cselm_wanted(979, 1, 1, 1, 0));
    printf("again %d %d %d %d %d %d\n", cselm_again(1, 1, 5000, 8000), cselm_again(1, 0, 100, 8000),
           cselm_again(1, 0, 300, 8000), cselm_again(0, 0, 7999, 8000), cselm_again(0, 0, 8000, 8000),
           cselm_again(0, 0, 1000, 0));
    return 0;
}
"""


def test_the_runtime_decisions(tmp_path):
    src = T.RUNTIME.read_text(encoding="utf-8")
    fns = (R._lift(src, "static int cselm_wanted(unsigned request, int live, int open, int teammates, int player)")
           + "\n" + R._lift(src, "static int cselm_again(int has_active, int active, unsigned long since, "
                                 "unsigned sound_ms)"))
    out = R._host_run(tmp_path, MAIN.replace("@FNS@", fns)).splitlines()
    assert "want 1 0 0 0 0 0" in out          # only armed, with a pick open, in a co-op game with a player up
    assert "again 0 0 1 0 1 1" in out         # idle past the grace (or its own length without sound_active)


def test_the_runtime_wiring():
    src = T.RUNTIME.read_text(encoding="utf-8")
    close = R._lift(src, "static void coop_pick_close(const char *how)")
    assert close.index("pk.open = 0;") < close.index("cselm_end(!cselm_picked_follows(c)")
    assert close.index("cselm_end(") < close.index("coop_picked_begin(c);")   # off the carrier before its sound
    follows = R._lift(src, "static int cselm_picked_follows(int c)\n{")
    assert "coop_done.on" in follows and "cpk_has(c, 0, cpk_have_now(), cpk.request) & 2" in follows   # PAD-1637: by mode
    tick = R._lift(src, "static void cselm_tick(void)\n{")
    assert "pk.open" in tick and "cselm_begin();" in tick and "cselm_end(1," in tick and "cselm_play(now);" in tick
    assert "cselm_quiet();" in tick
    play = R._lift(src, "static void cselm_play(unsigned long now)\n{")
    assert play.index("cselm.swap_until = ") < play.index("pm_sound(cselm.request);")
    assert play.index("pm_sound_priority(cselm.request, CSELM_PRIO_PLAYING, 0);") < play.index("pm_sound(cselm.request);")
    begin = R._lift(src, "static void cselm_begin(void)\n{")
    assert begin.index("cselm_quiet();") < begin.index("cselm_play(now);")   # the game's faded first
    end = R._lift(src, "static void cselm_end(int fade, const char *how)\n{")
    assert "cselm.swap_until = 0;" in end and "pm_sound_fade(cselm.request, CSELM_FADE_MS)" in end
    assert "pm_sound_priority(cselm.request, CSELM_PRIO_IDLE, 0);" in end
    assert end.index("pm_sound_priority(cselm.request, CSELM_PRIO_IDLE") < end.index("pm_sound(cselm.music[k]);")
    quiet = R._lift(src, "static void cselm_quiet(void)\n{")
    assert "reqs[i] == cselm.request" in quiet and "BUS_MUSIC_BIT" in quiet
    assert "pm_sound_fade(reqs[i], CSELM_QUIET_MS)" in quiet
    look = R._lift(src, "static void on_sound_lookup(pm_reg *r)")
    assert look.index("cselm_lookup(r)") < look.index("ci_lookup(r)")      # the same carrier key as the intro's
    coop = src[src.index("coop_picked_tick();                                       /* PAD-1123 */"):]
    assert coop.index("cselm_tick();") < 200
    assert 'str_eq(f[0], "cselm")' in src and "cselm_sound_arm();" in src
    assert "|| ci.request || cpk.request || ccer.request || cselm.request) return;" in src


def test_the_lookup_takes_the_musics_record():
    src = T.RUNTIME.read_text(encoding="utf-8")
    look = R._lift(src, "static int cselm_lookup(pm_reg *r)\n{")
    assert "LOOKUP_TAKE(r, cselm.host);" in look and "key_is(k, cselm.key)" in look and "cselm.swap_until" in look


FORGET = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    unsigned q[4] = {66, 74, 585, 0}, playing[2] = {74, 900};
    unsigned n = quiet_forget(q, 3, playing, 2);
    printf("kept %u %u\n", n, q[0]);
    printf("none %u\n", quiet_forget(q, n, playing, -1));
    return 0;
}
"""


def test_a_sound_the_game_plays_again_is_faded_again(tmp_path):
    # the emulator (Godzilla LE 1.16, teammate 2's pick): the game faded music 74 under the track, then asked for it
    # again while the pick was open - a quiet list that never forgot it let the second one play unfaded
    src = T.RUNTIME.read_text(encoding="utf-8")
    fns = R._lift(src, "static unsigned quiet_forget(unsigned *quiet, unsigned n_quiet, const unsigned *reqs, int n)")
    out = R._host_run(tmp_path, FORGET.replace("@FNS@", fns)).splitlines()
    assert "kept 1 74" in out and "none 0" in out
    for name in ("static void cselm_quiet(void)\n{", "static void ccer_quiet(void)\n{"):
        body = R._lift(src, name)
        assert "quiet_forget(" in body and body.index("quiet_forget(") < body.index("pm_sound_fade(reqs[i]")
