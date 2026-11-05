"""PAD-1012: a song in two of the jukebox's pools is not played in both in one game.

The owner who asked for pools (PAD-1007) adds some songs to more than one pool, and asked that a song played
in one pool (one of the five song modes) is not picked again in the same game by another (a multiball or the
background music), telling them alike by name. Write gives each pool's copy of a song one number (the jsong
line's 6th field); the runtime's draw passes over a song whose copy in another pool was drawn since the game
started. The draw itself is run in the compiled harness of test_pad685_jukebox.py.
"""
import re

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import jukebox as JB
from pinball_decryptor.plugins.stern import sound_modes as SMo
from tests.test_pad685_jukebox import RUNTIME, _Prof, draws  # noqa: F401 - draws is a fixture
from tests.test_pad1007_jukebox_pools import _modes


# ---- Write -----------------------------------------------------------------------------------------
def _lines(songs):
    params = [{"idx": i, "findkey": bytes([i % 251]) * 8} for m in JB.song_modes(_Prof()) for i in m.records]
    params += [{"idx": 900 + k, "findkey": bytes([65 + k]) * 8, "grown": True} for k in range(len(songs))]
    used = [{"rel": "audio/idx0667.wav", "slot": 667, "mode": SMo.juke_mode(k), "host": 899 + k, "db": 0}
            for k in range(1, len(songs) + 1)]
    logs = []
    got = E._jukebox_lines(params, used, _modes(songs), lambda t, lvl="info": logs.append((lvl, t)))
    return got, logs


def test_a_song_in_two_pools_carries_one_number_on_each_copy():
    songs = [JB.Song("C:/a/Hey Jude.wav", "", 3), JB.Song("C:/a/Help.wav", "", 2),
             JB.Song("D:/b/hey jude.mp3", "", 1, "background"), JB.Song("C:/a/Taxman.wav", "", 2, "background"),
             JB.Song("C:/a/Help.wav", "", 2, "special")]
    got, logs = _lines(songs)
    assert got["songs"] == [(3, b"A" * 8, "", 0, 1), (2, b"B" * 8, "", 0, 2), (1, b"C" * 8, "", 2, 1),
                            (2, b"D" * 8, "", 2), (2, b"E" * 8, "", 1, 2)]
    assert any("2 song(s) are in more than one pool" in t for _l, t in logs)


def test_one_file_on_one_record_is_one_song_whatever_its_name():
    # Write plays one file added to two pools from one record (the same host): that is one song too
    # (c.wav is a.wav's file under another name), as are two files of one name (b.wav)
    songs = [JB.Song("a.wav", "", 2), JB.Song("b.wav", "", 2, "special"), JB.Song("c.wav", "", 2, "background"),
             JB.Song("b.wav", "", 2, "background")]
    params = [{"idx": i, "findkey": bytes([i % 251]) * 8} for m in JB.song_modes(_Prof()) for i in m.records]
    params += [{"idx": 900, "findkey": b"A" * 8, "grown": True}, {"idx": 901, "findkey": b"B" * 8, "grown": True}]
    used = [{"rel": "audio/idx0667.wav", "slot": 667, "mode": SMo.juke_mode(k), "host": host, "db": 0}
            for k, host in ((1, 900), (2, 901), (3, 900), (4, 901))]
    got = E._jukebox_lines(params, used, _modes(songs), lambda *a: None)
    assert [g[4:] for g in got["songs"]] == [(1,), (2,), (1,), (2,)]


def test_songs_in_one_pool_only_carry_no_number():
    got, logs = _lines([JB.Song("a.wav", "", 2), JB.Song("b.wav", "", 2, "special")])
    assert got["songs"] == [(2, b"A" * 8, "", 0), (2, b"B" * 8, "", 1)]
    assert not any("more than one pool" in t for _l, t in logs)


def test_the_number_follows_the_pool_on_the_line():
    text = SMo.cfg_text(0, 0, [], True, jukebox={
        "modes": [("block_start_3", ["A"], [b"\x01" * 8], 0)],
        "songs": [(3, b"\x04" * 8, "PadJukebox1", 0, 1), (1, b"\x05" * 8, "", 2, 1), (2, b"\x06" * 8, "", 0),
                  (2, b"\x07" * 8, "", 1)]})
    assert [ln for ln in text.splitlines() if ln.startswith("jsong")] == [
        "jsong\t3\t0404040404040404\tPadJukebox1\t0\t1",        # the pool written (0) so the number is 6th
        "jsong\t1\t0505050505050505\t-\t2\t1",
        "jsong\t2\t0606060606060606\t-",                       # an old line, as before
        "jsong\t2\t0707070707070707\t-\t1"]


# ---- the runtime -----------------------------------------------------------------------------------
def test_the_runtime_reads_the_number_and_forgets_at_each_new_game():
    with open(RUNTIME, encoding="utf-8") as f:
        src = f.read()
    assert "jsong_line(f[1], f[2], n >= 4 ? f[3] : 0, n >= 5 ? f[4] : 0, n >= 6 ? f[5] : 0);" in src
    assert int(re.search(r"char \*f\[(\d+)\]", src[src.index("static void sndm_line"):]).group(1)) >= 6
    assert "if (game != juke_in_game_of)" in src and "juke_in_game[i] = 1;" in src


# songs 0-3 the song modes' (pool 0), 4-6 the background's (pool 2); song 0 and song 4 are one song (1)
_ONE_IN_TWO = ["2:0:1", "2", "2", "2", "2:2:1", "2:2", "2:2"]


def test_a_song_played_in_one_pool_is_not_drawn_in_another_that_game(draws):
    got = draws(_ONE_IN_TWO, 4000, "g02")              # each game: a song mode, then the background
    games = list(zip(got[0::2], got[1::2]))
    assert not [g for g in games if g == (0, 4)]
    assert {b for a, b in games if a != 0} == {4, 5, 6}     # the background still draws it in other games
    assert {a for a, _b in games} == {0, 1, 2, 3}


def test_a_pool_left_with_only_that_song_still_plays_it(draws):
    # one song mode song, the same song and one other in the background: game after game the song mode plays
    # song 0, so the background never draws its copy (2) while it has song 1 - the last-few window gives way
    got = draws(["2:0:1", "2:2", "2:2:1"], 400, "g02")
    assert set(got[0::2]) == {0} and set(got[1::2]) == {1}
    # the background first: then the song mode, whose pool has only that song, plays it all the same
    got = draws(["2:0:1", "2:2", "2:2:1"], 400, "g20")
    assert set(got[1::2]) == {0}


def test_the_same_pool_s_own_rule_is_unchanged(draws):
    # the song drawn twice in its own pool in a game: only the last-few rule, as before PAD-1012
    got = draws(["2:0:1", "2:0", "2:2:1"], 600, "g000")
    assert set(got) == {0, 1}
    assert all(a != b for a, b in zip(got, got[1:]))


def test_the_harness_shows_the_copy_drawn_when_it_has_no_number(draws):
    games = list(zip(*[iter(draws(["2", "2", "2", "2", "2:2", "2:2", "2:2"], 4000, "g02"))] * 2))
    assert [g for g in games if g == (0, 4)]                # untagged: the two are two songs, both may play
