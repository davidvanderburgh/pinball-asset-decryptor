"""PAD-749: a build with music modes puts their files into sound banks even when image.bin
could still take them. The game holds image.bin in memory for good and a bank only while it
plays: a Heisei Godzilla card with its music modes in image.bin (2,020 MB, stock 1,650) left
the city map video short of room on some first balls."""
from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec


def _plan(monkeypatch, tmp_path, sm_frags, game_sids):
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in (1, 2, 3)]
    grows = {1: (100, 4000), 2: (100, 3000), 3: (100, 2000)}
    audio_edits = {i: "s%d.wav" % i for i in grows}
    monkeypatch.delenv(BB.BANK_CAP_ENV, raising=False)       # everything fits in image.bin
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(4)), 4, 0x9000, 0))
    lines = []
    got = E._plan_sound_banks("game", str(img), params, audio_edits, grows, {1: grows[1]}, [],
                              _Reader(), None, None, lambda m, *a: lines.append(m),
                              game_sids=game_sids, sm_frags=sm_frags)
    return got, audio_edits, grows, lines


def test_music_modes_files_go_into_a_bank_although_image_bin_has_room(monkeypatch, tmp_path):
    u = {"rel": "a.wav", "mode": 2, "name": "SONG", "host": 2}
    frags = {2: [(u, 20)], 3: [(dict(u, host=3, rel="b.wav"), 21)]}
    (plan, edits2, grows2), _e, _g, lines = _plan(monkeypatch, tmp_path, frags, {1: 501})
    assert plan is not None
    # the files and the user's longer game sound beside them: image.bin keeps none of them
    assert sorted(plan.grows) == [1, 2, 3] and grows2 == {} and edits2 == {}
    assert sorted(plan.sm_frags) == [2, 3] and plan.game == {1: 501}
    assert any("held in memory for good, where a bank is held only while it plays" in m
               for m in lines)
    assert not any("past the" in m for m in lines)


def test_without_music_modes_a_build_that_fits_is_the_build_it_was(monkeypatch, tmp_path):
    (plan, edits2, grows2), audio_edits, grows, _l = _plan(monkeypatch, tmp_path, {}, {1: 501})
    assert plan is None and edits2 == audio_edits and grows2 == grows


def test_a_mode_file_with_turns_of_its_own_stays_in_image_bin_when_it_fits(monkeypatch, tmp_path):
    """PAD-638: a music mode's own files in turn are turned at that file's record key, which a
    bank record is never played by: such a file stays where it played."""
    u = {"rel": "a.wav", "mode": 2, "name": "SONG", "host": 2}
    frags = {2: [(u, 20)], 3: [(dict(u, host=3, rel="b.wav"), 21)]}
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in (1, 2, 3)]
    grows = {1: (100, 4000), 2: (100, 3000), 3: (100, 2000)}
    monkeypatch.delenv(BB.BANK_CAP_ENV, raising=False)
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(4)), 4, 0x9000, 0))
    plan, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, {i: "s.wav" for i in grows}, grows, {}, [], _Reader(), None,
        None, lambda *a: None, sm_frags=frags, sm_hold={2})
    assert sorted(plan.grows) == [3] and sorted(grows2) == [1, 2]      # (1: no bank can hold it)


def test_sm_turn_hosts_names_the_files_with_turns_of_their_own():
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    used = [{"rel": "a", "mode": 2, "host": 40}, {"rel": "a", "mode": 3, "host": 41},
            {"rel": "a", "mode": SMo.mode_turn(2, 2), "host": 42},
            {"rel": "b", "mode": 2, "host": 43}]
    assert E._sm_turn_hosts(used) == {40}
