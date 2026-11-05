"""PAD-1005: a music mode's own files in turn (PAD-638) go into sound banks with their mode file.

An owner's Godzilla card with three songs at random on each of seven multiball tracks was refused
for room: the files in turn of a music mode's file were kept in image.bin (they were turned at the
mode file's record key, which a bank record is never played by), fourteen whole songs, 2,390 MB of
image.bin in the reproduction, past the 2,182 MB the machine maps beside its banks. Now they go into
banks with the mode file, each a bank sound id of its own (a ``tsid`` line with the mode in a 6th
field), and the runtime turns them at the play worker, in that mode alone; a set one of which has
to stay in image.bin all stays.

Fast, no card and no firmware (the synthetic request lists of ``test_stern_sound_requests``, as
PAD-608's tests). The end to end proof (the reporter's shape built on stock Godzilla Pro 1.16 and
the songs heard at random on the rig) is the ticket's.
"""
import os
import struct

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo
from tests.test_pad606_game_sounds_in_banks import _head, _site
from tests.test_pad608_music_files_in_banks import MASK, RUNTIME, _lists
from tests.test_stern_sound_requests import make_elf

BOC = "audio/idx0601.wav"


def _banks(monkeypatch, tmp_path, used):
    elf, _reg = make_elf(_lists())
    (tmp_path / "game").write_bytes(elf)
    (tmp_path / "image.bin").write_bytes(_head())
    key = {i: struct.pack("<II", 0x1000 + i, i) for i in range(12)}
    params = [{"idx": i, "findkey": key[i], "length": 44100 * (30 if i == 2 else 1)}
              for i in range(12)]
    sites = [_site(20, key[1]), _site(20, key[2]),     # sid 20: idx 1 (opening), then idx 2 (body)
             _site(21, key[2]),                        # sid 21: the body alone
             _site(25, key[7])]                        # sid 25: idx 7 alone
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: MASK)

    def no_descriptors(*a, **k):        # (a song in parts would need them read whole)
        raise RuntimeError("no resolver")
    monkeypatch.setattr(E, "_wide_descriptors_once", no_descriptors)
    lines = []
    got = E._sound_modes_for_banks(str(tmp_path / "game"), str(tmp_path / "image.bin"), params,
                                   sites, used, [], {}, lambda m, *a: lines.append(m))
    return got, lines


def test_a_mode_file_and_its_files_in_turn_go_into_banks_together(monkeypatch, tmp_path):
    used = [{"rel": BOC, "slot": 7, "mode": 2, "host": 50},
            {"rel": BOC, "slot": 7, "mode": SMo.mode_turn(2, 2), "host": 51},
            {"rel": BOC, "slot": 7, "mode": SMo.mode_turn(2, 3), "host": 52}]
    (frags, sids, seqs), _lines = _banks(monkeypatch, tmp_path, used)
    assert sorted(frags) == [50, 51, 52] and seqs == []
    assert [(u["mode"], s) for u, s in frags[51]] == [(SMo.mode_turn(2, 2), 25)]
    assert sids == set()                 # no sound id has to stay the game's
    # and none of them is held in image.bin for its turns
    assert E._sm_turn_hosts(used, frags) == set()


def test_a_set_one_of_which_stays_in_image_bin_all_stays(monkeypatch, tmp_path):
    """The mode file plays sid 20's song without being one (no "song"): it stays in image.bin, so
    its file in turn, which alone could go, stays with it, turned at its record key there."""
    used = [{"rel": BOC, "slot": 1, "mode": 2, "host": 50},
            {"rel": BOC, "slot": 1, "mode": SMo.mode_turn(2, 2), "host": 51, "song": {20: [2]}}]
    (frags, sids, seqs), lines = _banks(monkeypatch, tmp_path, used)
    assert frags == {} and seqs == []
    assert 20 in sids                    # its sound ids stay the game's
    assert any("idx0601.wav's mode 2 file 2 in turn" in m and "stays in image.bin rather than a "
               "sound bank: the slot's file for mode 2 does" in m for m in lines), lines
    assert E._sm_turn_hosts(used, frags) == {50}


def test_the_runtime_lines_name_a_mode_s_file_in_turn_by_its_own_key_and_mode():
    used = [{"rel": BOC, "slot": 601, "mode": 2, "bank": 3, "bank_sids": {2504: 0x30000}},
            {"rel": BOC, "slot": 601, "mode": SMo.mode_turn(2, 2), "bank": 3,
             "bank_sids": {2504: 0x30001}},
            {"rel": BOC, "slot": 601, "mode": SMo.mode_turn(2, 3), "bank": 4,
             "bank_sids": {2504: 0x40000}}]
    bsids, tsids = E._bank_sid_lines([], used, {}, lambda *a: None)
    key = SMo.mode_turn_key(601, 2)
    assert bsids == [(2, 2504, 0x30000)]
    assert tsids == [(2, key, 2504, 0x30001, 2), (3, key, 2504, 0x40000, 2)]
    assert [u["lines"] for u in used] == [1, 1, 1]
    # one key a slot and mode, never another's
    assert len(key) == 8 and len({SMo.mode_turn_key(s, m) for s in (601, 602) for m in (2, 3)}) == 4
    text = SMo.cfg_text(0x7A4E78, 2, [], False, bsids=bsids, tsids=tsids, randoms=[key])
    assert "tsid\t2\t%s\t2504\t196609\t2" % key.hex() in text.splitlines()
    assert "tsid\t3\t%s\t2504\t262144\t2" % key.hex() in text.splitlines()
    assert "random\t%s" % key.hex() in text.splitlines()


def test_an_extract_decodes_a_mode_s_files_in_turn_out_of_their_bank():
    m = SMo.clean({"names": ["", "Random songs"], "slots": {BOC: {"2": "C:/x/A.wav"}},
                   "mode_turns": {BOC: {"2": ["C:/x/B.wav"]}}, "mode_random": {BOC: ["2"]}})
    used = [{"rel": BOC, "slot": 601, "mode": 2, "host": 900, "db": 0, "lines": 1,
             "bank": 3, "bank_idx": 0},
            {"rel": BOC, "slot": 601, "mode": SMo.mode_turn(2, 2), "host": 901, "db": None,
             "lines": 1, "bank": 4, "bank_idx": 0}]
    rec = SMo.read_card_record(SMo.cfg_text(0, 2, [], False, record=SMo.card_record(m, used)))
    assert rec["mode_turns"][0]["bank"] == 4 and rec["mode_random"]
    assert SMo.card_bank_records(rec) == {3: {0}, 4: {0}}


def test_the_runtime_turns_a_mode_s_own_files_in_a_bank_in_that_mode_alone():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'bsid_line(f[1], f[2], f[3], f[4], n >= 6 ? f[5] : 0);' in c
    assert 'bsid_line(f[1], 0, f[2], f[3], 0);' in c
    line = c[c.index("static void bsid_line("):]
    line = line[:line.index("\n}\n")]
    assert "e->mode = slot ? (unsigned char)mm : (unsigned char)m;" in line
    now = c[c.index("static unsigned bsid_now(unsigned id, unsigned m)"):]
    now = now[:now.index("\n}\n")]
    # the mode's own file in turn first, then the mode's file, then a slot's plain turn
    first = now.index("bsid[i].mode == m && bsid[i].turn")
    second = now.index("bsid[i].mode == m && !bsid[i].turn")
    third = now.index("!bsid[i].mode && bsid[i].turn")
    assert first < second < third
    play = c[c.index("static void blist_play(unsigned request)\n{"):]
    play = play[:play.index("\n}\n")]
    # the turn moves on only in its own mode, the mode read before
    assert play.index("m = sndm_mode();") < play.index("sndt_play(&sndt[bsid[j].t])")
    assert "(!bsid[j].mode || bsid[j].mode == m)" in play


def test_the_pinned_runtime_was_built_from_these_sources():
    """(test_stern_mode_runtime checks the hashes; here: this change is in what they name)"""
    sums = os.path.join(os.path.dirname(RUNTIME), "prebuilt", "SOURCES.sha256")
    import hashlib
    with open(RUNTIME, "rb") as f:
        h = hashlib.sha256(f.read().replace(b"\r", b"")).hexdigest()
    with open(sums, encoding="utf-8") as f:
        assert "%s  pad_mode_runtime.c" % h in f.read()
