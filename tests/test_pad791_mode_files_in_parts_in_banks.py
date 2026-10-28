"""PAD-791: a music mode's file for a song the game plays in parts can go into a sound bank.

Iron Maiden plays its songs as intro, song and outro sequences and medleys (sound id 974 plays
idx 222, 150, 618 and 919; 940 plays 575, 880 and 935).  A music mode's file plays from a bank
only under a bank sound id whose descriptor names every record the sequence plays, and a bank
sound id's descriptor can only name records of its own bank, so the file goes into a bank with a
copy of every other record its sound ids play (the game's own decoded as they are, or the
user's own replacement), files that one (mode, sound id) plays together (a medley's two songs
in one mode) share the bank, and each (mode, sound id) gets a descriptor of its own there that
the runtime points the game's request at while the mode is on (``bsid`` lines, PAD-608).

Fast, no card and no firmware; the reporter's own Iron Maiden LE 1.18 project written through
the app's pipeline and its rig run are the ticket's proof.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK, emitted_length
from tests.test_pad606_game_sounds_in_banks import _Reader, _head, _image, _rec, _site
from tests.test_pad779_songs_in_parts_in_banks import _desc, _key, _wide
from tests.test_stern_sound_requests import make_elf

MASK = E._DESC_KEY2_MASK


def _u(slot, host, mode=2, **kw):
    return dict({"rel": "audio/idx%04d.wav" % slot, "slot": slot, "mode": mode, "host": host,
                 "name": "Swapped Songs Version", "frames": 88200}, **kw)


# --------------------------------------------------------------------------
# which files move, with what
# --------------------------------------------------------------------------
def test_files_one_sound_id_plays_together_share_a_bank_with_every_other_part():
    """Iron Maiden LE 1.18's Option B: 150 and 618 (a medley: 960 plays both, 974 and 976
    with an intro and an outro), 178 (945 plays it then idx 94), 492 (935 plays the longer
    intro 307 first)."""
    byidx = {i: {"idx": i, "findkey": _key(i), "length": 1000} for i in range(1, 30)}
    wide = _wide({960: ([1, 2], 0), 974: ([3, 1, 2, 4], 0), 976: ([3, 1, 2], 0),
                  945: ([5, 6], 0), 975: ([5], 0),
                  935: ([7, 8, 9], 0), 943: ([8], 0)})
    slots = {s: [0x100] for s in wide}
    cands = {20: [_u(1, 20)], 21: [_u(2, 21)], 22: [_u(5, 22)], 23: [_u(8, 23)]}
    grows = {i: (100, 5000) for i in (20, 21, 22, 23, 7)}
    groups, why = BB.mode_seq_groups(cands, wide, slots, byidx=byidx, hosts=set(cands),
                                     grows=grows, user_grows={7: grows[7]})
    assert why == {}
    medley, s178, s492 = groups
    assert medley.hosts == [20, 21] and medley.parts == [3, 4] and medley.grown == {}
    assert [(m, s, f, [u["slot"] for u in us]) for m, s, f, us in medley.lines] == [
        (2, 960, 20, [1, 2]), (2, 974, 3, [1, 2]), (2, 976, 3, [1, 2])]
    assert medley.descs[974] == wide[974][0]
    assert s178.hosts == [22] and s178.parts == [6]
    # the user's longer intro is copied at its length; the sequence opens with it
    assert s492.parts == [7, 9] and s492.grown == {7: (100, 5000)}
    assert [(s, f) for _m, s, f, _u in s492.lines] == [(935, 7), (943, 23)]
    # a file's record opens a line with its own fragment; a part's copy never does
    assert BB.mode_seq_fragments(medley) == ({20: 0}, [(1, 3), (2, 3)])
    assert BB.mode_seq_fragments(s492) == ({23: 1}, [(0, 7)])


def test_a_mode_of_its_own_needs_no_copy_of_a_slot_another_mode_fills():
    byidx = {i: {"idx": i, "findkey": _key(i), "length": 1000} for i in range(1, 10)}
    wide = _wide({960: ([1, 2], 0)})
    slots = {960: [0x100]}
    # mode 2 fills both songs of the medley, mode 3 only the first
    cands = {20: [_u(1, 20)], 21: [_u(2, 21)], 22: [_u(1, 22, mode=3)]}
    groups, why = BB.mode_seq_groups(cands, wide, slots, byidx=byidx, hosts=set(cands))
    (two, three) = groups
    assert why == {} and two.hosts == [20, 21] and three.hosts == [22]
    assert [(m, s, f) for m, s, f, _u in two.lines] == [(2, 960, 20)] and two.parts == []
    assert [(m, s, f) for m, s, f, _u in three.lines] == [(3, 960, 22)] and three.parts == [2]
    # a whole-song file (PAD-511) names nothing else: no copy for its line
    cands = {22: [_u(1, 22, mode=3, song={960: [2]})]}
    (g,), _w = BB.mode_seq_groups(cands, wide, slots, byidx=byidx, hosts={22})
    assert g.parts == [] and g.lines[0][2] == 22


def test_what_keeps_a_file_in_parts_in_image_bin():
    byidx = {i: {"idx": i, "findkey": _key(i), "length": 1000} for i in range(1, 12)}
    wide = _wide({10: ([1, 2], 0), 11: ([3, 4], 0), 12: ([5, 6], SB.DESC_SLOT_MAX),
                  13: ([7, 8], 0), 14: ([9, 10], 0), 20: ([9, 11], 0)})
    slots = {s: [0x100] for s in wide if s != 20}
    cands = {30: [_u(1, 30)], 31: [_u(3, 31)], 32: [_u(5, 32)], 33: [_u(7, 33)],
             34: [_u(9, 34)]}
    grows = {4: (1, 2)}                                   # a mode's own sound grew idx 4
    groups, why = BB.mode_seq_groups(cands, wide, slots, exclude={13}, byidx=byidx,
                                     hosts=set(cands) | {2}, grows=grows)
    assert "sound idx 2, a part its song plays, holds another file" in why[30]
    assert "sound idx 4, a part its song plays, plays another sound" in why[31]
    assert "longer than a sound bank's can be" in why[32]
    assert why[33] == "sound id 13 is one a mode of this card plays"
    # PAD-784: sound id 20 is in no request: the game never plays it, so 11 is no part
    (g,) = groups
    assert g.hosts == [34] and g.parts == [10] and [s for _m, s, _f, _u in g.lines] == [14]


def test_sound_modes_for_banks_hands_a_file_in_parts_to_a_group(monkeypatch, tmp_path):
    lists = [[(i * 3) % 64] for i in range(64)]
    lists = [[s for s in l if s not in (20, 21, 22)] or [11] for l in lists]
    lists[1], lists[2], lists[3] = [20], [21], [22]
    lists[0] = [63]
    elf, _reg = make_elf(lists + [[]])
    (tmp_path / "game").write_bytes(elf)
    (tmp_path / "image.bin").write_bytes(_head())
    params = [{"idx": i, "findkey": _key(i), "length": 44100} for i in range(12)]
    sites = [_site(20, _key(1)), _site(20, _key(2)),     # 20: an intro, then the slot
             _site(21, _key(2)),                         # 21: the slot alone
             _site(22, _key(3))]                         # 22: another file's slot alone
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: MASK)
    wide = _wide({20: ([1, 2], 0), 21: ([2], 0), 22: ([3], 0)})
    monkeypatch.setattr(E, "_wide_descriptors_once", lambda *a, **k: wide)
    used = [_u(2, 40), _u(3, 41)]
    lines = []
    frags, sids, seqs = E._sound_modes_for_banks(
        str(tmp_path / "game"), str(tmp_path / "image.bin"), params, sites, used, [], {},
        lambda m, *a: lines.append(m), grows={40: (1, 2), 41: (1, 2)}, user_grows={})
    # every file goes into a bank: no sound id has to stay the game's
    assert sorted(frags) == [41] and sids == set()
    (g,) = seqs
    assert g.hosts == [40] and g.parts == [1]
    assert [(s, f) for _m, s, f, _u in g.lines] == [(20, 1), (21, 40)]
    assert any("goes into a sound bank with a copy of every other record those play (idx 1)"
               in m for m in lines)

    # descriptors that cannot be read keep it in image.bin, saying why
    def boom(*a, **k):
        raise RuntimeError("no resolver")
    monkeypatch.setattr(E, "_wide_descriptors_once", boom)
    lines = []
    frags, sids, seqs = E._sound_modes_for_banks(
        str(tmp_path / "game"), str(tmp_path / "image.bin"), params, sites, used, [], {},
        lambda m, *a: lines.append(m))
    assert seqs == [] and sorted(frags) == [41] and sids == {20, 21}
    # a file the runtime swaps in by key holds its slot's sound ids too
    _f, sids, _s = E._sound_modes_for_banks(
        str(tmp_path / "game"), str(tmp_path / "image.bin"), params, sites, [_u(3, 41)], [], {},
        lambda m, *a: None, fixed=[_u(2, 45, mode=SMo.turn_mode(2) + 1)])
    assert sids == {20, 21}
    text ="\n".join(lines)
    assert "could not be read (no resolver)" in text
    assert "stays in image.bin rather than a sound bank: sound id 20 plays sound idx 2 " \
           "together with other sounds" in text


# --------------------------------------------------------------------------
# the plan and the build
# --------------------------------------------------------------------------
def _group(entries=None):
    us = entries or [_u(2, 5), _u(3, 6)]
    return BB.ModeSeq([5, 6], [(2, 10, 1, us), (2, 11, 5, us[:1]), (2, 12, 5, us)],
                      {10: _desc(1, 2, 3), 11: _desc(2), 12: _desc(2, 3, pad=20)}, [1],
                      {1: (1000, 200000)})


def test_plan_sound_banks_puts_files_in_parts_into_one_bank_with_their_parts(monkeypatch,
                                                                             tmp_path):
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 1000 + i, "findkey": _key(i)} for i in range(1, 8)]
    # the files' records 5 and 6, and the user's longer intro 1 (it stays in image.bin too)
    grows = {5: (1000, 400000), 6: (1000, 300000), 1: (1000, 200000)}
    audio_edits = {5: "m5.wav", 6: "m6.wav", 1: "intro.wav"}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(8)), 8,
                                                    0x9000, 0))
    g = _group()
    lines = []
    plan, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, {1: grows[1]}, [], _Reader(), None, None,
        lambda m, *a: lines.append(m), sm_seqs=[g])
    assert plan is not None and sorted(plan.grows) == [5, 6]
    assert grows2 == {1: (1000, 200000)} and edits2 == {1: "intro.wav"}
    ((cat, group),) = plan.banks
    assert plan.sm_seqs == {cat: [g]} and sorted(e.idx for e in group) == [1, 5, 6]
    # the intro's copy at the user's length, from the user's file
    e1 = next(e for e in group if e.idx == 1)
    assert e1.new_length == 200000 + BLOCK and plan.wavs[1] == "intro.wav"
    assert all(u["bank"] == cat for _m, _s, _f, us in g.lines for u in us)
    assert any("idx 1 (copied: a part of the songs a music mode's files play)" in m
               for m in lines)
    # too big for a bank: the files stay in image.bin
    monkeypatch.setattr(SB, "BANK_MAX_SEEN", 1_000_000)
    lines = []
    plan, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, {1: grows[1]}, [], _Reader(), None, None,
        lambda m, *a: lines.append(m), sm_seqs=[_group()])
    assert plan is None and sorted(grows2) == [1, 5, 6]
    assert any("the files on records 5, 6 stay in image.bin rather than a sound bank" in m
               for m in lines)


def test_a_longer_game_song_on_a_file_s_sound_id_goes_where_the_file_goes(monkeypatch,
                                                                          tmp_path):
    """The reporter's longer songs are on the same slots as his music mode 2 files: with the
    file in a bank, the song (sound id 11's) goes into a bank of the game's too, and the
    runtime points the request at the file's bank id from the song's; with the file in
    image.bin, played under sound id 11 itself, the song stays there with it."""
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 1000 + i, "findkey": _key(i)} for i in range(1, 8)]
    grows = {5: (1000, 400000), 6: (1000, 300000), 7: (1000, 200000)}
    audio_edits = {5: "m5.wav", 6: "m6.wav", 7: "song7.wav"}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(8)), 8,
                                                    0x9000, 0))
    g = _group()._replace(grown={})
    lines = []
    plan, _e, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, {7: grows[7]}, [], _Reader(), None, None,
        lambda m, *a: lines.append(m), game_sids={7: 11}, sm_seqs=[g])
    assert grows2 == {} and plan.game == {7: 11} and sorted(plan.grows) == [5, 6, 7]
    assert sum(plan.sm_seqs.values(), []) == [g]
    # the files too big for any bank: they stay in image.bin, and the song with them
    monkeypatch.setattr(E, "_mseq_bank_bytes", lambda *a: 10 ** 12)
    lines = []
    plan, _e, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, {7: grows[7]}, [], _Reader(), None, None,
        lambda m, *a: lines.append(m), game_sids={7: 11}, sm_seqs=[_group()._replace(grown={})])
    assert plan is None and sorted(grows2) == [5, 6, 7]
    assert any("idx 7 stays in image.bin rather than a sound bank: a music mode's file its "
               "sound id 11 plays stays in image.bin" in m for m in lines)


def test_bank_mode_seq_descs_give_each_mode_and_sound_id_a_descriptor(monkeypatch):
    g = _group()
    # slot 2 is a longer replacement the user keeps in image.bin: re-pointed there, so the
    # game's own key is its stock one
    params = [{"idx": i, "chan": 2, "length": 44100, "findkey": _key(i)} for i in (1, 3, 5, 6)]
    params.append({"idx": 2, "chan": 2, "length": 99999, "findkey": b"\x99" * 8, "grown": True,
                   "stock_findkey": _key(2), "stock_length": 44100})
    lens = {5: 88200 + BLOCK, 6: 88200 + BLOCK, 1: 200000 + BLOCK}
    edits = [SB.BankEdit(i, b"\0" * 24, 44100, lens[i], 20000) for i in (5, 6, 1)]
    # (a song in parts' fragment first: the files' come after it)
    _d, places = SB.plan_bank(edits, aliases=[5, 1, 5], desc_slot=0x60)
    bank = {5: b"\xb5" * 8, 6: b"\xb6" * 8, 1: b"\xa1" * 8}
    rows = [{"idx": pl.new_idx, "host": pl.idx, "length": pl.length, "findkey": bank[pl.idx]}
            for pl in SB.records(places)]
    sites = [E._DescSite(10, 0, b"", _key(1), 0, b"", 0)]
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a: MASK)
    lines = []
    given, played = E._bank_mode_seq_descs(params, sites, [g], places, rows, False, 1,
                                           lambda m, *a: lines.append(m))
    rec = {pl.idx: pl.new_idx for pl in SB.records(places)}
    names = lambda n: [pl for _o, pl in E._op11_payloads(given[n])]
    dur = lambda n: struct.unpack_from("<I", given[n], E._DESC_DUR_OFF)[0]
    # 10: the intro's copy, then both files (a medley); its fragment the intro's alias
    assert names(4) == [bank[1], bank[5], bank[6]]
    mode = min(88200, emitted_length(lens[5])) * E._DESC_DUR_RATE // 44100
    slot = E._duration_units_emitted(44100)
    intro = E._duration_units(lens[1]) - E._duration_units(44100)
    assert dur(4) == 40000 + 2 * (mode - slot) + intro
    # 11: the first file alone, on its record's own fragment, its whole length the file's
    assert names(rec[5]) == [bank[5]] and dur(rec[5]) == mode
    # 12: the medley without the intro, an alias of the first file
    assert names(5) == [bank[5], bank[6]]
    u2, u3 = g.lines[0][3]
    assert sorted((u["slot"], s, n) for u, s, n in played) == [
        (2, 10, 4), (2, 11, rec[5]), (2, 12, 5), (3, 10, 4), (3, 12, 5)]
    # the second file's and the intro's own fragments name their records; nothing plays them
    assert names(rec[6])[0] == bank[6] and names(rec[1])[0] == bank[1]
    assert set(given) == {pl.new_idx for pl in places} - {3} and lines == []
    # a fragment a song in parts in the same bank already gave one keeps it
    given2, _p = E._bank_mode_seq_descs(params, sites, [g], places, rows, False, 1,
                                        lambda m, *a: None, taken={rec[1]})
    assert rec[1] not in given2
    # the wrong fragment where a line's should be is a bug, not a silent mix-up
    with pytest.raises(RuntimeError):
        E._bank_mode_seq_descs(params, sites, [g], places, rows, False, 0, lambda m, *a: None)


def test_a_line_whose_descriptor_names_a_record_outside_the_bank_plays_the_game_s_own(
        monkeypatch):
    g = _group()
    g = g._replace(parts=[])                               # (no copy of the intro planned)
    params = [{"idx": i, "chan": 2, "length": 44100, "findkey": _key(i)} for i in (1, 2, 3, 5, 6)]
    edits = [SB.BankEdit(i, b"\0" * 24, 44100, 88200 + BLOCK, 20000) for i in (5, 6)]
    _d, places = SB.plan_bank(edits, aliases=[5], desc_slot=0x60)
    g = g._replace(lines=[(2, 10, 5, g.lines[0][3]), g.lines[1]])
    rows = [{"idx": pl.new_idx, "host": pl.idx, "length": pl.length,
             "findkey": bytes([0xb0 + pl.idx]) * 8} for pl in SB.records(places)]
    sites = [E._DescSite(10, 0, b"", _key(1), 0, b"", 0)]
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a: MASK)
    lines = []
    given, played = E._bank_mode_seq_descs(params, sites, [g], places, rows, False, 0,
                                           lambda m, *a: lines.append(m))
    assert [(u["slot"], s) for u, s, _n in played] == [(2, 11)]
    assert len(lines) == 2 and all("plays its own sound for sound id 10" in m for m in lines)
    # its fragment still resolves (a descriptor naming its record), never pointed at
    assert set(given) == {pl.new_idx for pl in places}


def test_a_medley_s_files_share_one_runtime_line():
    params = [{"idx": 2, "findkey": b"S" * 8}]
    used = [{"rel": "a", "slot": 150, "mode": 2, "bank": 3, "bank_sids": {960: 0x30004,
                                                                          974: 0x30005}},
            {"rel": "b", "slot": 618, "mode": 2, "bank": 3, "bank_sids": {960: 0x30004,
                                                                          974: 0x30005}}]
    bsids, _t = E._bank_sid_lines(params, used, {}, lambda *a: None)
    assert bsids == [(2, 960, 0x30004), (2, 974, 0x30005)]
    assert [u["lines"] for u in used] == [2, 2]
    assert SMo.cfg_text(0, 2, [], False, bsids=bsids).count("bsid\t2\t960\t") == 1


def test_a_file_s_record_is_never_a_part_of_a_song_in_parts_if_it_can_help_it():
    """Iron Maiden LE 1.18: a 30 s file's best host by length was idx 919, the outro sound id
    974 plays past the play tables' 80 bytes after 150 and 618: as a host it kept both
    files of that medley in image.bin (a part's copy cannot hold another file)."""
    slot = {"idx": 1, "chan": 2, "length": 100, "findkey": b"k1"}
    params = [slot] + [{"idx": i, "chan": 2, "length": n, "findkey": b"k%d" % i}
                       for i, n in ((919, 1_000_000), (758, 900_000), (5, 400_000))]
    assert E._sound_mode_host(params, slot, 1_300_000, {}, set()) == 919
    assert E._sound_mode_host(params, slot, 1_300_000, {}, set(), parts={919, 758}) == 5
    # a part only when nothing else will do
    assert E._sound_mode_host(params, slot, 1_300_000, {}, {5}, parts={919, 758}) == 919


def test_a_part_in_two_banks_leaves_each_group_in_its_own(monkeypatch, tmp_path):
    """The rig proof's set: idx 307 is the user's longer intro of 492, a song in parts of the
    game's (PAD-779) AND a copy beside 492's music mode file.  Its two copies are in two banks,
    and the song's descriptors were made in the file's bank too, which has no 492 (KeyError)."""
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 1000 + i, "findkey": _key(i)} for i in range(1, 8)]
    grows = {5: (1000, 6_000_000), 6: (1000, 4_000_000), 1: (1000, 5_000_000)}
    audio_edits = {5: "m5.wav", 6: "m6.wav", 1: "intro.wav"}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(8)), 8,
                                                    0x9000, 0))
    song = BB.SeqGroup([1], {13: [1, 3]}, {13: _desc(1, 3)}, [1, 3])
    files = _group()._replace(grown={1: grows[1]})
    plan, _e, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, {1: grows[1]}, [], _Reader(), None, None,
        lambda m, *a: None, game_seqs=[song], sm_seqs=[files])
    assert grows2 == {} and len(plan.banks) == 2
    assert sum(plan.seqs.values(), []) == [song] and sum(plan.sm_seqs.values(), []) == [files]
    (scat,), (mcat,) = list(plan.seqs), list(plan.sm_seqs)
    idxs = {c: sorted(e.idx for e in g) for c, g in plan.banks}
    assert scat != mcat and idxs[scat] == [1, 3] and idxs[mcat] == [1, 5, 6]
