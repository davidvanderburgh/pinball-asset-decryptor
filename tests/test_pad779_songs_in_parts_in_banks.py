"""PAD-779: a longer game song the game plays in parts can go into a sound bank.

Iron Maiden plays its songs as intro, song and outro sequences and medleys: each sound id's
descriptor names several records (sound id 974 plays idx 222, 150, 618 and 919).  A bank sound
id's descriptor can only name records of its own bank, so such a song moves with every sound
id that plays it and a copy of every record those name (the game's own decoded and copied as
they are), and each of those sound ids gets a descriptor of its own there: a fragment past the
records, named in the sid map's extension so a later Write can put the request lists back.

Fast, no card and no firmware; the real Iron Maiden LE 1.18 build and its rig run are the
ticket's proof (docs/plans/extra_sound_banks.md, "Songs in parts").
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_pad606_game_sounds_in_banks import _Reader, _image, _rec


def _key(i):
    return struct.pack("<II", 0x1000 + i, i)


def _desc(*idxs, dur=40000, pad=0):
    """A sequence descriptor: magic, two bytes, the declared duration, then one op11 a record
    (``0b 00 00 00`` + its key, then a wait), then the end."""
    d = bytearray(b"\x05\x01\x01" + struct.pack("<I", dur) + b"\x01\x00\x00")
    for i in idxs:
        d += b"\x0b\x00\x00\x00" + _key(i) + b"\x11\x01"
    d += b"\x00" + b"\x00" * pad
    return bytes(d)


def _wide(table):
    return {sid: (_desc(*idxs, pad=pad), list(idxs)) for sid, (idxs, pad) in table.items()}


# --------------------------------------------------------------------------
# the bank's layout
# --------------------------------------------------------------------------
def test_the_sid_map_extension_names_the_fragments_past_the_records(tmp_path):
    edits = [SB.BankEdit(i, b"\0" * 24, 100, 300, 1000) for i in (7, 8)]
    d, places = SB.plan_bank(edits, aliases=[7, 7, 8], desc_slot=0x60, mapped=3)
    assert [pl.desc_off - places[0].desc_off for pl in places] == [0, 0x60, 0xC0, 0x120, 0x180]
    size = SB.bank_bytes([1000, 1000], aliases=3, desc_slot=0x60, mapped=3)
    assert size == d.md_off + MD.tail_len(2)
    path = tmp_path / "image-sc01.bin"
    path.write_bytes(SB.bank_header(size, d.md_off, 2, 5) + b"\0" * (size - SB.HDR_LEN))
    raw = bytearray(path.read_bytes())
    t = d.md_off + MD.align16(MD.RECORD_SIZE * 2) + 4
    raw[t:t + 4] = SB.PAD_TRAILER
    path.write_bytes(bytes(raw))
    SB.write_sid_map(str(path), d.md_off, 2, {0: 974, 2: 960, 3: 976, 4: 943})
    assert SB.read_sid_map(path.read_bytes()) == {0: 974, 2: 960, 3: 976, 4: 943}
    # the extension sits in the room plan_bank left for it, past the descriptors
    raw = path.read_bytes()
    at = d.md_off - SB.sid_map_len(2)
    assert raw[at - 4:at] == SB.SID_MAP_EXT_MAGIC
    assert at - SB.sid_map_ext_len(3) >= places[-1].desc_off + 0x60
    # a bank without one reads as before
    SB.write_sid_map(str(path), d.md_off, 2, {0: 974})
    data = bytearray(path.read_bytes())
    data[at - 4:at] = b"\0\0\0\0"
    assert SB.read_sid_map(bytes(data)) == {0: 974}


def test_a_descriptor_slot_past_the_keystream_the_game_covers_is_refused():
    e = [SB.BankEdit(1, b"\0" * 24, 100, 300, 1000)]
    with pytest.raises(SB.SoundBankError):
        SB.plan_bank(e, desc_slot=SB.DESC_SLOT_MAX + 16)


def test_split_units_never_splits_a_song_in_parts():
    one = lambda i, n: SB.BankEdit(i, b"\0" * 24, 100, 300, n)
    units = [SB.BankUnit([one(1, 3000)]), SB.BankUnit([one(2, 2000), one(3, 2000)], 2, 0x60, 2),
             SB.BankUnit([one(4, 1000)])]
    limit = SB.unit_bytes(units[1:2])
    banks = SB.split_units(units, limit=limit)
    assert [[e.idx for u in b for e in u.edits] for b in banks] == [[1], [2, 3], [4]]
    # singles pack as split_banks packs them
    singles = [one(i, 1000) for i in range(6)]
    lim = SB.bank_bytes([1000] * 2) + 8
    assert ([[u.edits[0] for u in b] for b in SB.split_units([SB.BankUnit([e]) for e in singles],
                                                               limit=lim)]
            == SB.split_banks(singles, limit=lim))


# --------------------------------------------------------------------------
# which songs move, with what
# --------------------------------------------------------------------------
def test_game_sound_groups_take_every_sound_id_that_plays_a_song_and_every_part():
    byidx = {i: {"idx": i, "findkey": _key(i), "length": 1000} for i in range(1, 12)}
    wide = _wide({10: ([1, 2], 0), 11: ([2], 0), 12: ([2, 3], 0), 13: ([3], 0),   # a medley
                  14: ([4], 0),                                                  # alone
                  20: ([5, 6], 0),                                               # 20 unlisted
                  30: ([7, 8], 0),                                               # 8 is busy
                  40: ([9], 0), 41: ([9, 10], SB.DESC_SLOT_MAX)})                # too long
    slots = {s: [0x100] for s in wide if s != 20}
    grows = {i: (100, 5000) for i in (2, 3, 4, 5, 7, 9)}
    groups, why = BB.game_sound_groups(grows, byidx, wide, slots, busy={8})
    assert len(groups) == 1
    g = groups[0]
    assert g.grown == [2, 3] and sorted(g.sids) == [10, 11, 12, 13] and g.parts == [1, 2, 3]
    assert g.descs[12] == wide[12][0]
    assert 4 not in why                                  # game_sound_sids' case
    assert why[5] == "the game never plays it: no sound request of the game's names sound id 20"
    assert "sound idx 8, one of its parts, plays another sound" in why[7]
    assert "longer than a sound bank's can be" in why[9]
    # a sound id a mode of the card plays keeps the whole song where it is
    _g, why2 = BB.game_sound_groups({2: (100, 5000)}, byidx, wide, slots, exclude={11})
    assert _g == [] and "a mode of this card plays" in why2[2]


def test_a_sound_id_the_game_never_plays_does_not_hold_a_song_back():
    """PAD-784: Iron Maiden LE 1.18's 954 plays idx 205 alone, 949 / 956 with an intro; 978
    is a medley of 786 and 895, which 962 plays with 426.  No request names 954 or 978, and
    the game starts a sound only through its requests: the songs move with 949, 956 and
    962, 954 and 978 keep naming image.bin, and 786, which only 978 plays, stays."""
    byidx = {i: {"idx": i, "findkey": _key(i), "length": 1000} for i in range(1, 12)}
    wide = _wide({949: ([1, 2], 0), 956: ([1, 2, 3], 0), 954: ([2], 0),
                  978: ([4, 5], 0), 962: ([6, 5], 0)})
    slots = {s: [0x100] for s in (949, 956, 962)}
    grows = {i: (100, 5000) for i in (2, 4, 5, 6)}
    groups, why = BB.game_sound_groups(grows, byidx, wide, slots)
    assert [(g.grown, sorted(g.sids), g.parts) for g in groups] == [
        ([2], [949, 956], [1, 2, 3]), ([5, 6], [962], [6, 5])]
    assert why == {4: "the game never plays it: no sound request of the game's names sound "
                      "id 978"}
    # a mode of the Write that plays 954 makes it one the song moves with
    groups, why = BB.game_sound_groups({2: (100, 5000)}, byidx, wide, slots, exclude={954})
    assert groups == [] and "sound id 954 is one a mode of this card plays" in why[2]
    # no request table read: as before, nothing moves
    groups, why = BB.game_sound_groups(grows, byidx, wide, {})
    assert groups == [] and set(why) == {2, 4, 5, 6}


def test_seq_fragments_give_each_record_an_opening_sound_id_and_the_rest_aliases():
    g = BB.SeqGroup([2, 3], {10: [1, 2], 11: [2], 12: [2, 3], 13: [3]}, {}, [1, 2, 3])
    own, aliases = BB.seq_fragments(g)
    assert own == {2: 11, 3: 13, 1: 10}
    assert aliases == [(12, 2)]


def test_seq_descriptor_names_the_bank_records_and_moves_the_duration():
    d = _desc(1, 2, 3, dur=40000)
    keys = {_key(1): b"\xa1" * 8, _key(2): b"\xa2" * 8, _key(3): b"\xa3" * 8}
    out = BB.seq_descriptor(d, 974, keys, {_key(2): 1234}, E._DESC_KEY2_MASK)
    assert [pl for _o, pl in E._op11_payloads(out)] == [b"\xa1" * 8, b"\xa2" * 8, b"\xa3" * 8]
    assert struct.unpack_from("<I", out, E._DESC_DUR_OFF)[0] == 40000 + 1234
    assert len(out) == len(d)
    with pytest.raises(RuntimeError):
        BB.seq_descriptor(d, 974, {_key(1): b"\xa1" * 8}, {}, E._DESC_KEY2_MASK)


# --------------------------------------------------------------------------
# the plan and the build
# --------------------------------------------------------------------------
def _group():
    return BB.SeqGroup([2, 3], {10: [1, 2], 11: [2], 12: [2, 3, 4]},
                       {10: _desc(1, 2), 11: _desc(2), 12: _desc(2, 3, 4, pad=20)}, [1, 2, 3, 4])


def test_plan_sound_banks_puts_a_song_in_parts_into_one_bank_with_its_parts(monkeypatch,
                                                                             tmp_path):
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 1000 + i, "findkey": _key(i)} for i in range(1, 7)]
    grows = {2: (1000, 400000), 3: (1000, 300000), 6: (1000, 200000)}
    audio_edits = {2: "s2.wav", 3: "s3.wav", 6: "s6.wav", 4: "mine4.wav"}   # 4: same length
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(7)), 7,
                                                    0x9000, 0))
    lines = []
    plan, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None, None,
        lambda m, *a: lines.append(m), game_sids={6: 506}, game_seqs=[_group()])
    assert plan is not None and grows2 == {} and edits2 == {4: "mine4.wav"}
    assert plan.seq_grown == {2, 3} and plan.game == {6: 506}
    (cat, group), = [(c, g) for c, g in plan.banks if plan.seqs.get(c)]
    assert {1, 2, 3, 4} <= {e.idx for e in group}
    # the game's own parts at their own length; the user's same-length file kept for 4
    e1 = next(e for e in group if e.idx == 1)
    assert e1.new_length == 1001 and plan.wavs[1] is None and plan.wavs[4] == "mine4.wav"
    assert any("idx 1 (copied: a part of idx 2, 3)" in m for m in lines)
    # a song in parts too big for a bank stays in image.bin whole
    monkeypatch.setattr(SB, "BANK_MAX_SEEN", 1_000_000)
    lines = []
    plan, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None, None,
        lambda m, *a: lines.append(m), game_sids={6: 506}, game_seqs=[_group()])
    assert sorted(grows2) == [2, 3] and not plan.seqs
    assert any("idx 2, 3 stay in image.bin rather than a sound bank: the game plays them in "
               "parts" in m for m in lines)


def test_bank_seq_descs_give_every_sound_id_its_own_descriptor(monkeypatch):
    g = _group()
    params = [{"idx": i, "chan": 2, "length": 1000, "findkey": _key(i)} for i in range(1, 5)]
    edits = [SB.BankEdit(i, b"\0" * 24, 1000, 1000 if i in (1, 4) else 5000, 20000)
             for i in (2, 3, 1, 4)]
    # (a music mode's fragment first, on idx 1: the songs' come after it)
    _d, places = SB.plan_bank(edits, aliases=[1, 2], desc_slot=0x60, mapped=1)
    rows = [{"idx": pl.new_idx, "host": pl.idx, "length": pl.length,
             "findkey": bytes([0xa0 + pl.idx]) * 8} for pl in SB.records(places)]
    sites = [E._DescSite(10, 0, b"", _key(1), 0, b"", 0)]
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a: E._DESC_KEY2_MASK)
    with pytest.raises(RuntimeError):                     # fragment 4 is the music mode's
        E._bank_seq_descs(params, sites, [g], places, rows, False, 0)
    given, played = E._bank_seq_descs(params, sites, [g], places, rows, False, 1)
    rec = {pl.idx: pl.new_idx for pl in SB.records(places)}
    assert played == {11: rec[2], 10: rec[1], 12: 5}
    names = lambda n: [pl for _o, pl in E._op11_payloads(given[n])]
    assert names(rec[1]) == [b"\xa1" * 8, b"\xa2" * 8]
    assert names(5) == [b"\xa2" * 8, b"\xa3" * 8, b"\xa4" * 8]
    # sound id 11 plays the longer idx 2 alone: its duration moved by the growth
    dur = struct.unpack_from("<I", given[rec[2]], E._DESC_DUR_OFF)[0]
    assert dur == 40000 + E._duration_units(5000) - E._duration_units(1000)
    # idx 3 and 4 open no sound id: a descriptor naming them that nothing plays
    assert names(rec[3])[0] == b"\xa3" * 8 and names(rec[4])[0] == b"\xa4" * 8
    assert set(given) == {pl.new_idx for pl in places} - {4}
