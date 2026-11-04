"""PAD-994: a build with music modes moved every longer call of the game's into a sound bank
beside them (PAD-749), and a sound the game plays once from a bank keeps its channel after it
ends (emulator, Godzilla Pro 1.16: request 1900's 7.4 s call held channel 7 for 225 s and every
request after it waited). While image.bin has room, only the music modes' looping files move."""
from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec

# Godzilla Pro 1.16's own scripts: sid 1554 (request 1900, a call: wait, then the music back
# up) and a looping tune's (11 01 03 00 after its record)
CALL = bytes.fromhex("0502014b73000002000109002800000014000000140001000000090220000000190000001900"
                     "010000000b00000005057f76b992e3df100a6d000009003c0000")
TUNE = CALL[:46] + bytes.fromhex("0505aabbccddeeff") + E._MUSIC_LOOP_TAIL


def _plan(monkeypatch, tmp_path, sm_frags, sm_loops, game_sids=None, used=()):
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in (1, 2, 3)]
    grows = {1: (100, 4000), 2: (100, 3000), 3: (100, 2000)}
    monkeypatch.delenv(BB.BANK_CAP_ENV, raising=False)       # everything fits in image.bin
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(4)), 4, 0x9000, 0))
    lines = []
    got = E._plan_sound_banks("game", str(img), params, {i: "s.wav" for i in grows}, grows,
                              {1: grows[1]}, list(used), _Reader(), None, None,
                              lambda m, *a: lines.append(m), game_sids=game_sids or {},
                              sm_frags=sm_frags, sm_loops=sm_loops)
    return got, lines


def _frags():
    u = {"rel": "a.wav", "mode": 2, "name": "SONG", "host": 2}
    return {2: [(u, 20)], 3: [(dict(u, host=3, rel="b.wav"), 21)]}


def test_the_users_longer_calls_stay_in_image_bin_beside_looping_music_mode_files(monkeypatch, tmp_path):
    (plan, edits2, grows2), _l = _plan(monkeypatch, tmp_path, _frags(), {2, 3}, {1: 501})
    assert sorted(plan.grows) == [2, 3] and plan.game == {}
    assert sorted(grows2) == [1] and sorted(edits2) == [1]


def test_a_music_mode_file_the_game_plays_once_stays_in_image_bin(monkeypatch, tmp_path):
    (plan, _e, grows2), lines = _plan(monkeypatch, tmp_path, _frags(), {2}, {1: 501})
    assert sorted(plan.grows) == [2] and sorted(grows2) == [1, 3]
    assert any("idx 3's music mode file stays in image.bin" in m and "keeps its sound channel" in m
               for m in lines)


def test_no_looping_music_mode_file_is_the_build_it_was(monkeypatch, tmp_path):
    (plan, _e, grows2), _l = _plan(monkeypatch, tmp_path, _frags(), set(), {1: 501})
    assert plan is None and sorted(grows2) == [1, 2, 3]


def test_loops_at_end_reads_the_script_after_the_last_record():
    assert not E._loops_at_end(CALL)
    assert E._loops_at_end(TUNE)
    assert not E._loops_at_end(b"") and not E._loops_at_end(None)
    # a tune played once (the DJ Mixer's tracks: 11 01 00) is not a loop
    assert not E._loops_at_end(TUNE[:-4] + bytes.fromhex("11010000"))
    # Godzilla Pro 1.16's TUNE 1 (sid 2544)
    assert E._loops_at_end(bytes.fromhex("05010169b3030001000002000807000b00000051f0b231f4989b"
                                         "4f11010300e010a2d9e697fee7fd3ef6d056680ea3ee0f1af9"))


def test_sm_loop_hosts_asks_every_sound_id_of_a_file(monkeypatch):
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites: 0)
    monkeypatch.setattr(E, "_wide_descriptors_once",
                        lambda gr, im, params, mask: {20: (TUNE, [2]), 21: (CALL, [3]),
                                                      22: (TUNE, [4])})
    u = {"rel": "a.wav", "mode": 2, "host": 2}
    frags = {2: [(u, 20)], 3: [(u, 21)], 4: [(u, 22), (u, 21)], 5: [(u, 99)]}
    seq_loop = BB.ModeSeq(hosts=[6, 7], lines=[], descs={30: TUNE, 31: TUNE}, parts=[], grown={})
    seq_once = BB.ModeSeq(hosts=[8], lines=[], descs={32: TUNE, 33: CALL}, parts=[], grown={})
    got = E._sm_loop_hosts("g", "i", [], [], frags, [seq_loop, seq_once])
    assert got == {2, 6, 7}


def test_sm_loop_hosts_keeps_everything_in_image_bin_when_the_scripts_cannot_be_read(monkeypatch):
    def boom(*a):
        raise RuntimeError("the game's descriptor resolver could not be located")
    monkeypatch.setattr(E, "_desc_key_mask", lambda params, sites: 0)
    monkeypatch.setattr(E, "_wide_descriptors_once", boom)
    assert E._sm_loop_hosts("g", "i", [], [], {2: [({}, 20)]}, []) == set()
