"""An extra sound bank on a title that ships with one (PAD-595): ``spike2.soundbank``,
``bank_build`` and the engine's spill plan.

Fast, no card and no firmware: the bank's geometry, image.bin's category list and
the spill plan are pure.  The emulator-gated end (a bank the firmware loads and
derives, its sounds encoded along the chain) is the ticket's proof on the rig and
``docs/plans/extra_sound_banks.md``.
"""
import os
import struct

import pytest

from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB


def _image_header(cats=(), first_table=0xF8, md_off=0x6252CFCA, count=2534):
    """A Godzilla-shaped image.bin head: tables at ``0x28``, the category count at
    ``0x68`` and the ids from ``0x6c``."""
    h = bytearray(0x200)
    struct.pack_into("<I", h, 0x28, first_table)
    struct.pack_into("<I", h, 0x40, md_off)
    struct.pack_into("<I", h, 0x5C, 2599)
    struct.pack_into("<I", h, 0x60, count)
    struct.pack_into("<I", h, 0x68, len(cats))
    for i, c in enumerate(cats):
        struct.pack_into("<I", h, 0x6C + 4 * i, c)
    return bytes(h)


def _record(length_word=0x1234 ^ 0xDEADBEEF, body_off=0x100):
    r = bytearray(range(24))
    struct.pack_into("<I", r, 0, body_off)
    struct.pack_into("<I", r, 16, length_word)
    return bytes(r)


# --------------------------------------------------------------------------
# image.bin's category list
# --------------------------------------------------------------------------
def test_category_slots_read_the_count_the_ids_and_the_room_before_the_first_table():
    assert SB.category_slots(_image_header()) == (0, [], (0xF8 - 0x6C) // 4)
    count, ids, room = SB.category_slots(_image_header(cats=(1, 3, 5, 7), first_table=0x138))
    assert (count, ids) == (4, [1, 3, 5, 7])
    assert room == (0x138 - 0x6C) // 4 - 4


def test_next_category_ids_skip_the_cards_own_banks_by_list_and_by_file_name():
    assert SB.next_category_ids([], (), 1) == [1]
    assert SB.next_category_ids([1, 3, 5], ["image-sc02.bin", "image-sc04.bin"], 3) == [6, 7, 8]
    with pytest.raises(SB.SoundBankError):
        SB.next_category_ids(range(1, 100), (), 1)


def test_header_writes_name_the_new_categories_after_the_ones_the_card_has():
    w = SB.header_writes_new_categories(_image_header(), [1])
    assert w == {0x68: struct.pack("<I", 1), 0x6C: struct.pack("<I", 1)}
    w = SB.header_writes_new_categories(_image_header(cats=(1, 3), first_table=0x138), [2, 4])
    assert w == {0x68: struct.pack("<I", 4), 0x6C + 8: struct.pack("<I", 2),
                 0x6C + 12: struct.pack("<I", 4)}
    with pytest.raises(SB.SoundBankError):
        SB.header_writes_new_categories(_image_header(cats=(1,), first_table=0x138), [1])
    with pytest.raises(SB.SoundBankError):
        # no room: the ids run into the first table
        SB.header_writes_new_categories(_image_header(cats=(1, 2, 3), first_table=0x78), [4])


# --------------------------------------------------------------------------
# the bank's geometry
# --------------------------------------------------------------------------
def test_plan_bank_lays_each_body_behind_its_pad_and_the_directory_last():
    rec_a, rec_b = _record(0x10 ^ 0xDEADBEEF), _record(0x20 ^ 0xDEADBEEF, body_off=0x900)
    d, places = SB.plan_bank([
        SB.BankEdit(1898, rec_a, 0x10, 0x30, 1000),
        SB.BankEdit(1147, rec_b, 0x20, 0x50, 500),
    ])
    assert [(p.idx, p.new_idx) for p in places] == [(1898, 0), (1147, 1)]
    # the fragment table and the 16-byte data block come first, the bodies past room for
    # MD.GROW_SLOTS fragments of 5 slots, not just these 2 (PAD-677)
    tables = MD.GROW_SLOTS * SB.DEFAULT_STRIDE * SB.FRAG_SLOT + 16
    assert places[0].body_off == MD.align16(SB.HDR_LEN + tables) + MD.BODY_PAD
    assert places[1].body_off == places[0].body_off + 1000 + MD.BODY_PAD
    assert d.count == 2
    # then the descriptor block, one slot a sound, then the directory
    desc0 = MD.align16(places[1].body_off + 500 + MD.BODY_PAD)
    assert [p.desc_off for p in places] == [desc0, desc0 + SB.DESC_SLOT]
    # PAD-606: the sid map sits between them
    assert d.md_off == MD.align16(desc0 + 2 * SB.DESC_SLOT) + SB.sid_map_len(2)
    assert d.trailer == SB.PAD_TRAILER
    # a copy of the host record with only its geometry replaced
    assert d.body_off(0) == places[0].body_off
    assert d.length_word(0) == 0x10 ^ 0xDEADBEEF ^ 0x10 ^ 0x30
    assert d.identity(0) == rec_a[4:16] + rec_a[20:24]
    assert d.identity(1) == rec_b[4:16] + rec_b[20:24]
    assert d.file_size() == SB.bank_bytes([1000, 500])


def test_plan_bank_refuses_records_that_disagree_about_the_length_constant():
    with pytest.raises(SB.SoundBankError):
        SB.plan_bank([SB.BankEdit(1, _record(0x10 ^ 0xDEADBEEF), 0x10, 0x30, 10),
                      SB.BankEdit(2, _record(0x20 ^ 0xCAFEBABE), 0x20, 0x30, 10)])
    with pytest.raises(SB.SoundBankError):
        SB.plan_bank([])


def test_split_banks_fills_each_bank_to_the_limit_in_order():
    edits = [SB.BankEdit(i, _record(), 1, 2, 600) for i in range(5)]
    one = SB.bank_bytes([600])
    banks = SB.split_banks(edits, limit=SB.bank_bytes([600, 600]) + 8)
    assert [[e.idx for e in b] for b in banks] == [[0, 1], [2, 3], [4]]
    assert SB.split_banks(edits) == [edits]
    with pytest.raises(SB.SoundBankError):
        SB.split_banks(edits, limit=one - 1)


def test_write_tables_whitens_each_slot_and_descriptor_as_the_resolver_reads_them(tmp_path):
    """The resolver (read off Deadpool LE 1.16 and Godzilla LE 1.16) takes slot
    ``n * stride + k``, de-whitens its low word with four vf2 bytes at
    ``((slot >> 6) & 0x3f) << 8 | (slot & 0x7f)`` to the descriptor's offset,
    and de-whitens the descriptor with vf2 at a rule of that offset."""
    import random
    rnd = random.Random(595)
    vf2 = bytes(rnd.getrandbits(8) for _ in range(SB.VF2_WINDOW + SB.DESC_SLOT))
    places = [SB.BankPlacement(7, 0, 0x100, 10, 20, 0x2000), SB.BankPlacement(9, 1, 0x200, 10, 20, 0x2050)]
    path = tmp_path / "image-sc03.bin"
    path.write_bytes(b"\0" * 0x2200)
    descs = {0: b"\x05\x01\x01" + b"A" * 30, 1: b"\x05\x1c\x01" + b"B" * 20}
    ks = SB.write_tables(str(path), places, descs, vf2, lambda off: off & 0x2a6, stride=5)
    assert ks == {0: 0x2000 & 0x2a6, 1: 0x2050 & 0x2a6}
    data = path.read_bytes()
    for pl in places:
        for k in range(5):
            slot = pl.new_idx * 5 + k
            word, hi = struct.unpack_from("<II", data, SB.HDR_LEN + slot * SB.FRAG_SLOT)
            assert hi == 0
            o = SB.slot_vf2_offset(slot)
            assert word ^ struct.unpack_from("<I", vf2, o)[0] == pl.desc_off
        plain = descs[pl.new_idx]
        raw = data[pl.desc_off:pl.desc_off + len(plain)]
        assert bytes(a ^ b for a, b in zip(raw, vf2[ks[pl.new_idx]:])) == plain
    assert SB.slot_vf2_offset(5) == 5 and SB.slot_vf2_offset(64) == 0x140 and SB.slot_vf2_offset(0x7f) == 0x17f
    assert SB.bank_sid(1, 0) == 0x10000 and SB.bank_sid(55, 2) == 0x370002
    with pytest.raises(SB.SoundBankError):
        SB.write_tables(str(path), places, {0: b"x" * (SB.DESC_SLOT + 1), 1: b"y"}, vf2, lambda o: 0)


def test_fragment_stride_is_read_off_image_bins_own_tables():
    h = bytearray(0x100)
    struct.pack_into("<I", h, 0x28, 0xF8)
    struct.pack_into("<I", h, 0x48, 0xF8 + 2599 * 40)
    struct.pack_into("<I", h, 0x5C, 2599)
    assert SB.fragment_stride(bytes(h)) == 5
    assert SB.fragment_stride(bytes(0x100)) == SB.DEFAULT_STRIDE


def test_bank_header_has_no_fragment_table_and_points_at_the_directory():
    h = SB.bank_header(size=1000, md_off=800, count=3)
    assert len(h) == SB.HDR_LEN
    words = {o: struct.unpack_from("<I", h, o)[0] for o in range(0, SB.HDR_LEN, 4)}
    assert words[SB.HDR_FRAG_TABLE] == SB.HDR_LEN
    assert words[SB.HDR_DATA] == SB.HDR_LEN
    assert words[SB.HDR_END_WORD] == 996
    assert words[SB.HDR_MD_OFF] == 800
    assert words[SB.HDR_FRAGMENTS] == 0
    assert words[SB.HDR_COUNT] == 3
    assert all(v == 0 for o, v in words.items()
               if o not in (SB.HDR_FRAG_TABLE, SB.HDR_DATA, SB.HDR_END_WORD, SB.HDR_MD_OFF,
                            SB.HDR_COUNT))
    assert MD.header_geometry(h) == (800, 3)


def test_is_pad_bank_reads_the_trailer_word(tmp_path):
    count = 3
    md_off = MD.align16(SB.HDR_LEN + 3 * (MD.BODY_PAD + 100) + MD.BODY_PAD)
    size = md_off + MD.tail_len(count)
    ours = tmp_path / "image-sc01.bin"
    with open(ours, "wb") as f:
        f.write(SB.bank_header(size, md_off, count))
        f.write(b"\x00" * (md_off - SB.HDR_LEN))
        f.write(b"\x11" * MD.align16(24 * count) + b"SEED" + SB.PAD_TRAILER)
    assert SB.is_pad_bank(str(ours))
    theirs = tmp_path / "image-sc02.bin"
    with open(theirs, "wb") as f:
        f.write(SB.bank_header(size, md_off, count))
        f.write(b"\x00" * (md_off - SB.HDR_LEN))
        f.write(b"\x11" * MD.align16(24 * count) + b"SEED" + b"\x00\x00\x00\x00")
    assert not SB.is_pad_bank(str(theirs))
    assert not SB.is_pad_bank(str(tmp_path / "missing.bin"))
    short = tmp_path / "image-sc03.bin"
    short.write_bytes(b"\x00" * 16)
    assert not SB.is_pad_bank(str(short))


def test_bank_name_and_category_of_round_trip():
    assert SB.bank_name(7) == "image-sc07.bin"
    assert SB.category_of("image-sc07.bin") == 7
    assert SB.category_of("image.bin") is None


# --------------------------------------------------------------------------
# which sounds spill (bank_build.plan_spill), and the engine's bankable set
# --------------------------------------------------------------------------
def _img(tmp_path, md_off=1000, count=10):
    p = tmp_path / "image.bin"
    p.write_bytes(_image_header(md_off=md_off, count=count))
    return str(p)


def test_plan_spill_moves_the_largest_bankable_sounds_until_image_bin_fits(tmp_path):
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern import engine as E
    img = _img(tmp_path)
    byidx = {i: {"idx": i, "chan": 2, "length": 100} for i in range(1, 5)}
    grows = {1: (100, 1000), 2: (100, 5000), 3: (100, 3000), 4: (100, 2000)}
    md_off, count = 1000, 10
    bodies = {i: E._grown_body_bytes(byidx[i], g[1]) for i, g in grows.items()}
    # room for the two smallest only
    limit = E._grown_bank_bytes(md_off, count, [bodies[1], bodies[4]])
    kept, spilled = BB.plan_spill(grows, {1, 2, 3, 4}, byidx, img, limit=limit)
    assert sorted(kept) == [1, 4]
    assert sorted(spilled) == [2, 3]
    # a sound that is not bankable never moves, even when nothing then fits
    kept, spilled = BB.plan_spill(grows, {1, 4}, byidx, img, limit=limit)
    assert sorted(kept) == [2, 3]
    assert sorted(spilled) == [1, 4]
    # everything fits: nothing moves and the build is what it was
    kept, spilled = BB.plan_spill(grows, {1, 2, 3, 4}, byidx, img,
                                  limit=E._grown_bank_bytes(md_off, count, list(bodies.values())))
    assert kept == grows and spilled == {}


def test_image_cap_is_the_games_limit_unless_the_proof_knob_lowers_it(monkeypatch):
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern.spike2.emulator import MAX_IMAGE_BYTES
    monkeypatch.delenv(BB.BANK_CAP_ENV, raising=False)
    assert BB.image_cap() == MAX_IMAGE_BYTES
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1700000000")
    assert BB.image_cap() == 1700000000
    monkeypatch.setenv(BB.BANK_CAP_ENV, str(MAX_IMAGE_BYTES * 2))
    assert BB.image_cap() == MAX_IMAGE_BYTES
    monkeypatch.setenv(BB.BANK_CAP_ENV, "not a number")
    assert BB.image_cap() == MAX_IMAGE_BYTES


def test_bankable_sounds_are_the_swapped_calls_and_the_music_beds():
    from pinball_decryptor.plugins.stern.engine import _bankable_idx
    used = [
        {"idx": 10, "swap": True, "key": "sound_start"},            # a swapped call
        {"idx": 11, "music": True, "sid": 618, "key": "music"},     # a bed on Godzilla
        {"idx": 12, "music": True, "swap": True, "key": "music"},   # swapped music (other titles)
        {"idx": 13, "key": "sound_end"},                            # the end sound: re-pointed for good
        {"key": "sound_shot"},                                      # not located
    ]
    assert _bankable_idx(used) == {10, 11, 12}
    assert _bankable_idx([]) == set()


def test_bank_edits_copy_the_host_record_and_size_the_body_like_image_bin_grows():
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern.spike2.emulator import BLOCK
    recs = b"".join(_record(0x100 ^ 0xDEADBEEF, body_off=0x1000 * (i + 1)) for i in range(3))
    d = MD.Directory(recs, 3, 0x9000, 0)
    byidx = {1: {"idx": 1, "chan": 2, "length": 0x100}, 2: {"idx": 2, "chan": 1, "length": 0x100}}
    edits = BB.bank_edits({2: (0x100, 5000), 1: (0x100, 7000)}, byidx, d)
    assert [e.idx for e in edits] == [1, 2]
    assert edits[0].record == d.record(1) and edits[1].record == d.record(2)
    assert edits[0].new_length == 7000 + BLOCK
    assert edits[0].body_bytes == E._grown_body_bytes(byidx[1], 7000)
    assert edits[1].body_bytes == E._grown_body_bytes(byidx[2], 5000)


# --------------------------------------------------------------------------
# a bed in a bank keeps its stock key and takes the bank record's length
# --------------------------------------------------------------------------
def test_plan_descriptor_repoint_moves_a_bank_beds_duration_and_keeps_its_stock_key():
    from pinball_decryptor.plugins.stern import engine as E
    skey = bytes.fromhex("9af08101571e00a0")
    ks = bytes(range(8))
    dks = b"\x55\x66\x77\x88"
    # the bed's descriptor, naming its stock record; and another sid's, which must not move
    sites = [
        E._DescSite(618, 0x500, ks, bytes(a ^ b for a, b in zip(skey, bytes(8))), 0x4F0, dks, 400),
        E._DescSite(619, 0x600, ks, bytes(8), 0x5F0, dks, 123),
    ]
    stock_len, new_len = 132330, 644942
    writes, expect = E._plan_descriptor_repoint(
        [], sites, mask=0xE0001FFF, family=True,
        bank_beds={618: (skey, stock_len, new_len)})
    grew = E._duration_units_emitted(new_len) - E._duration_units(stock_len)
    assert expect == {618: ({skey}, (400 + grew) & 0xFFFFFFFF)}
    assert set(writes) == {0x4F0}
    assert writes[0x4F0] == bytes(a ^ b for a, b in zip(struct.pack("<I", 400 + grew), dks))
    with pytest.raises(RuntimeError):
        E._plan_descriptor_repoint([], sites, mask=0xE0001FFF, family=True,
                                   bank_beds={700: (skey, stock_len, new_len)})


def test_write_directory_refuses_an_unsettled_key_length():
    class _Session(object):
        keylen = None
        crc_init = 0

    class _Emu(object):
        _masterdir_session = _Session()

    d = MD.Directory(_record() * 2, 2, 0x100, 0)
    with pytest.raises(MD.MasterDirError):
        MD.write_directory(d, _Emu())


# --------------------------------------------------------------------------
# the engine's two steps, with the bank's own build faked
# --------------------------------------------------------------------------
def test_plan_sound_banks_takes_the_spilled_sounds_out_of_the_build_and_marks_their_modes(
        monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import bank_build as BB
    img = tmp_path / "image.bin"
    img.write_bytes(_image_header(md_off=1000, count=10))
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in (1, 2, 3, 4)]
    byidx = {p["idx"]: p for p in params}
    # 1: the end sound (re-pointed for good, never bankable); 2..4 the modes' own swaps and a bed
    grows = {1: (100, 1000), 2: (100, 5000), 3: (100, 3000), 4: (100, 2000)}
    audio_edits = {i: "s%d.wav" % i for i in grows}
    used = [{"idx": 2, "swap": True, "key": "call:a", "name": "A"},
            {"idx": 3, "music": True, "sid": 618, "key": "music", "name": "B"},
            {"idx": 4, "swap": True, "key": "call:c", "name": "C"}]
    bodies = {i: E._grown_body_bytes(byidx[i], g[1]) for i, g in grows.items()}
    cap = E._grown_bank_bytes(1000, 10, [bodies[1], bodies[4]])
    monkeypatch.setenv(BB.BANK_CAP_ENV, str(cap))
    recs = b"".join(_record(0x100 ^ 0xDEADBEEF, body_off=0x1000 * i) for i in range(5))
    monkeypatch.setattr(E, "_read_stock_directory", lambda gr, im: MD.Directory(recs, 5, 0x9000, 0))

    class Reader(object):
        def iter_regular_files(self, **kw):
            return iter([("/godzilla_le/image.bin", 5, {})])

    plan, edits2, grows2 = E._plan_sound_banks("game", str(img), params, audio_edits, grows, {},
                                               used, Reader(), None, None,
                                               lambda *a, **k: None)
    assert plan is not None
    # PAD-593: once one has to go, every bankable one goes (the game holds image.bin and
    # the bank playing in memory together, so image.bin is kept as small as it can be)
    assert sorted(plan.grows) == [2, 3, 4]
    assert sorted(grows2) == [1] and sorted(edits2) == [1]
    assert plan.wavs == {2: "s2.wav", 3: "s3.wav", 4: "s4.wav"}
    assert [c for c, _e in plan.banks] == [1]
    assert [e.idx for e in plan.banks[0][1]] == [2, 3, 4]
    assert used[0]["bank"] == used[1]["bank"] == used[2]["bank"] == 1
    # everything fits: no plan, nothing moves
    monkeypatch.delenv(BB.BANK_CAP_ENV)
    plan, e3, g3 = E._plan_sound_banks("game", str(img), params, audio_edits, grows, {}, used,
                                       Reader(), None, None, lambda *a, **k: None)
    assert plan is None and e3 == audio_edits and g3 == grows


def test_build_sound_banks_gives_each_bank_sound_its_keys_and_names_the_bank_in_image_bin(
        monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import bank_build as BB
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    img = tmp_path / "image.bin"
    img.write_bytes(_image_header())
    params = [{"idx": 618, "chan": 2, "length": 1000, "findkey": b"\x01" * 8},
              {"idx": 1251, "chan": 1, "length": 500, "findkey": b"\x02" * 8}]
    used = [{"idx": 618, "music": True, "sid": 618, "request": 125, "key": "music", "name": "KIRYU"},
            {"idx": 1251, "swap": True, "request": 1251, "key": "call:fire", "name": "KIRYU"}]
    edits = [SB.BankEdit(618, b"\0" * 24, 1000, 5000, 20000),
             SB.BankEdit(1251, b"\0" * 24, 500, 2000, 4000)]
    plan = E._BankPlan([(1, edits)], {618: "a.wav", 1251: "b.wav"},
                       {618: (1000, 5000), 1251: (500, 2000)}, "godzilla_le")
    places = [SB.BankPlacement(618, 0, 0x78, 5000, 20000, 0x6000),
              SB.BankPlacement(1251, 1, 0x4F00, 2000, 4000, 0x6050)]
    bank = str(tmp_path / "image-sc01.bin")
    with open(bank, "wb") as f:      # where the bank's sid map goes (PAD-606)
        f.write(SB.bank_header(0x7000, 0x6100, 2, 2) + b"\0" * (0x7000 - SB.HDR_LEN))
    (tmp_path / "game").write_bytes(b"\0" * 64)
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "request_sids", lambda elf, head, r: {125: [73], 1251: [900]}[int(r)])

    class FakeEmu(object):
        def __init__(self, *a, **k):
            pass

        def boot(self):
            return self

        def close(self):
            pass

    monkeypatch.setattr(EM, "Spike2Emu", FakeEmu)
    monkeypatch.setattr(E, "_mode_music_level_refs", lambda *a, **k: {})
    monkeypatch.setattr(BB, "stage_bank", lambda *a, **k: (bank, places))
    rows = [{"idx": 0, "host": 618, "length": 5000, "findkey": b"\xaa" * 8},
            {"idx": 1, "host": 1251, "length": 2000, "findkey": b"\xbb" * 8}]
    monkeypatch.setattr(BB, "chain_encode", lambda *a, **k: (rows, {}, 0x3B57D8))
    verified = []
    # the check hands back rows derived afresh, which carry no host
    monkeypatch.setattr(BB, "verify_bank",
                        lambda *a, **k: verified.append(a[3]) or [dict(r, host=None) for r in rows])
    tables = {}

    def write_tables(gr, im, path, cat, pl, rws, carriers, durations, music_idx, log):
        tables.update(carriers=carriers, durations=durations, music=set(music_idx))
        return {r["idx"]: (SB.bank_sid(cat, r["idx"]), b"\x05", 0) for r in rws}

    monkeypatch.setattr(BB, "write_bank_tables", write_tables)
    monkeypatch.setattr(BB, "verify_tables", lambda *a, **k: verified.append(("tables", a[3])))
    beds = E._build_sound_banks(str(tmp_path / "game"), str(img), params, [], plan, used, {618}, {},
                                str(tmp_path), None, lambda *a, **k: None)
    assert verified == [1, ("tables", 1)]
    # each sound's carrier sid gives its descriptor; the bed is the looping one
    assert tables["carriers"] == {618: 73, 1251: 900} and tables["music"] == {618}
    assert set(tables["durations"]) == {618, 1251}
    # the mode file points the carrier at the bank's sid: no key swap
    assert used[0]["bank"] == 1 and used[0]["bank_idx"] == 0 and used[0]["bank_sid"] == 0x10000
    assert used[1]["bank_sid"] == 0x10001 and "stock_key" not in used[1] and "our_key" not in used[1]
    assert beds == {}
    assert plan.files == [(1, bank)]
    h = img.read_bytes()
    assert struct.unpack_from("<I", h, 0x68)[0] == 1
    assert struct.unpack_from("<I", h, 0x6C)[0] == 1
    # the sid map: no game sound in this bank, only the modes' own
    raw = open(bank, "rb").read()
    assert raw[0x6100 - SB.sid_map_len(2):][:16] == SB.SID_MAP_MAGIC + struct.pack("<III", 2, 0, 0)


# --------------------------------------------------------------------------
# a card an earlier build already grew (PAD-593's layout)
# --------------------------------------------------------------------------
def test_plan_spill_measures_an_already_grown_image_bin_from_its_file_end(tmp_path):
    """The tester's Heisei card keeps its record array at 1.65 GB with the card
    builder's bodies behind it: measured from the header alone, 250 MB of beds
    looked like they fit (1.9 GB) where the file would come to 2.26 GB."""
    from pinball_decryptor.plugins.stern import bank_build as BB
    img = tmp_path / "image.bin"
    md_off, count = 1000, 10
    data = bytearray(_image_header(md_off=md_off, count=count))
    # an earlier build's bodies past the record array's tail
    data += b"\0" * (md_off + MD.tail_len(count) + MD.GROWN_TAIL_MIN + 50000 - len(data))
    img.write_bytes(bytes(data))
    params = [{"idx": i, "chan": 2, "length": 100} for i in (1, 2)]
    byidx = {p["idx"]: p for p in params}
    grows = {1: (100, 3000), 2: (100, 2000)}
    from pinball_decryptor.plugins.stern import engine as E
    bodies = {i: E._grown_body_bytes(byidx[i], g[1]) for i, g in grows.items()}
    grow_off, _c = MD.image_grow_geometry(str(img))
    assert grow_off >= len(data) - 15                   # past the earlier bodies
    # a limit with room for the smaller body past the FILE END: the header's
    # geometry alone would have said both fit
    limit = E._grown_bank_bytes(grow_off, count, [bodies[2]]) + 10
    assert E._grown_bank_bytes(md_off, count, list(bodies.values())) < limit
    kept, spilled = BB.plan_spill(grows, {1, 2}, byidx, str(img), limit=limit)
    assert sorted(spilled) == [1] and sorted(kept) == [2]


def test_bank_edits_copy_the_record_a_pre_grown_host_plays():
    from pinball_decryptor.plugins.stern import bank_build as BB
    recs = b"".join(_record(0x100 ^ 0xDEADBEEF, body_off=0x1000 * i) for i in range(6))
    d = MD.Directory(recs, 6, 0x9000, 0)
    byidx = {1: {"idx": 1, "chan": 1, "length": 0x100, "shadows": 5},
             2: {"idx": 2, "chan": 1, "length": 0x100}}
    edits = BB.bank_edits({1: (0x100, 4000), 2: (0x100, 4000)}, byidx, d)
    assert [e.idx for e in edits] == [1, 2]
    assert edits[0].record == d.record(5)        # the appended record it plays
    assert edits[1].record == d.record(2)


def test_a_bank_is_kept_within_the_emulators_window_beside_image_bin():
    from pinball_decryptor.plugins.stern.spike2.emulator import DESC_BASE
    room = SB.emulator_bank_room(2_010_400_998)       # the tester's image.bin
    assert room == 0x1_0000_0000 - DESC_BASE - 2_010_400_998 - 0x120000
    assert 390 * 10**6 < room < 410 * 10**6
    assert SB.emulator_bank_room(0x1_0000_0000) == 0


def test_banks_are_kept_as_small_as_sterns_own_and_refused_past_what_a_machine_holds(
        monkeypatch, tmp_path):
    """PAD-593: a Godzilla card with image.bin at 2,125 MB and one 136 MB bank died on the
    machine at its first bank sound ("FATAL: error 232 (Flash memory init mmap failed)"):
    the game maps image.bin and the bank playing whole, together. Banks are cut at
    BANK_SLICE, and a build whose image.bin and largest bank pass MAPPED_MAX is refused."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import bank_build as BB
    assert SB.BANK_SLICE <= 40_000_000 and SB.MAPPED_MAX == 2_142_352_388 + 39_598_976
    img = tmp_path / "image.bin"
    img.write_bytes(_image_header(md_off=1000, count=10))
    want = 16_000_000 // 4                               # each a 16 MB stereo body
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in range(1, 6)]
    grows = {i: (100, want) for i in range(1, 6)}
    audio_edits = {i: "s%d.wav" % i for i in grows}
    used = [{"idx": i, "swap": True, "key": "call:%d" % i, "name": "M%d" % i} for i in grows]
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000000")
    recs = b"".join(_record(0x100 ^ 0xDEADBEEF, body_off=0x1000 * i) for i in range(6))
    monkeypatch.setattr(E, "_read_stock_directory", lambda gr, im: MD.Directory(recs, 6, 0x9000, 0))

    class Reader(object):
        def iter_regular_files(self, **kw):
            return iter([("/godzilla_le/image.bin", 5, {})])

    lines = []
    plan, _e, _g = E._plan_sound_banks("game", str(img), params, audio_edits, grows, {}, used,
                                       Reader(), None, None, lambda m, *a: lines.append(m))
    assert all(SB.bank_bytes([e.body_bytes for e in g]) <= SB.BANK_SLICE for _c, g in plan.banks)
    assert len(plan.banks) == 3                          # two, two and one 16 MB sounds
    assert any("one for each of its %d sound channels" % SB.SOUND_CHANNELS in m for m in lines)
    # an image.bin already so big that one bank beside it passes what a machine holds
    monkeypatch.setattr(SB, "MAPPED_MAX", 20_000_000)
    with pytest.raises(RuntimeError, match="in memory at once"):
        E._plan_sound_banks("game", str(img), params, audio_edits, grows, {}, used,
                            Reader(), None, None, lambda *a: None)


def test_a_sound_too_long_for_a_slice_gets_a_bank_of_its_own():
    """PAD-607: a whole song as a mode's music does not fit a BANK_SLICE bank; it gets a
    bank to itself up to *alone*, the small sounds around it keep filling slices."""
    small = [SB.BankEdit(i, _record(), 1, 2, 600) for i in (0, 1, 3, 4)]
    song = SB.BankEdit(2, _record(), 1, 2, 5000)
    edits = small[:2] + [song] + small[2:]
    limit = SB.bank_bytes([600, 600]) + 8
    banks = SB.split_banks(edits, limit=limit, alone=SB.bank_bytes([5000]))
    assert sorted([e.idx for e in b] for b in banks) == [[0, 1], [2], [3, 4]]
    # no room for it alone: refused, as before
    with pytest.raises(SB.SoundBankError, match="alone"):
        SB.split_banks(edits, limit=limit, alone=SB.bank_bytes([5000]) - 1)
    with pytest.raises(SB.SoundBankError, match="alone"):
        SB.split_banks(edits, limit=limit)


def test_alone_bank_room_is_whats_left_beside_image_bin_up_to_sterns_biggest_bank():
    """PAD-607: image.bin + the bank playing stay within MAPPED_MAX (D&D 1.10's pair), and no
    bank is bigger than Stern ships (Rush 1.19's 218,349,330 bytes)."""
    assert SB.BANK_MAX_SEEN == 218_349_330
    # David's Godzilla build: image.bin 2,010 MB leaves 171 MB, about 16 minutes of stereo
    room = SB.alone_bank_room(2_010_400_998)
    assert room == SB.MAPPED_MAX - 2_010_400_998
    assert 16 * 4 * 44100 * 60 < room < 17 * 4 * 44100 * 60
    # Rush's own image.bin: the room is capped at Rush's own bank
    assert SB.alone_bank_room(1_836_701_778) == SB.BANK_MAX_SEEN
    assert SB.alone_bank_room(SB.MAPPED_MAX) == 0
    assert SB.alone_bank_room(SB.MAPPED_MAX + 10) == 0


def test_plan_sound_banks_gives_a_long_song_a_bank_of_its_own(monkeypatch, tmp_path):
    """PAD-607: a mode's music 100 MB long (about 9.4 minutes of stereo) beside small calls:
    the calls fill BANK_SLICE banks, the song gets a 100 MB bank, and image.bin + that bank
    stay within MAPPED_MAX. A song past the room is refused with its length in minutes."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import bank_build as BB
    img = tmp_path / "image.bin"
    img.write_bytes(_image_header(md_off=1000, count=10))
    sizes = {1: 16_000_000, 2: 100_000_000, 3: 16_000_000, 4: 16_000_000}
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in sizes]
    grows = {i: (100, n // 4) for i, n in sizes.items()}
    audio_edits = {i: "s%d.wav" % i for i in grows}
    used = [{"idx": i, "swap": i != 2, "music": i == 2, "sid": 0x99 if i == 2 else None,
             "key": "music" if i == 2 else "call:%d" % i, "name": "M%d" % i} for i in grows]
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000000")
    recs = b"".join(_record(0x100 ^ 0xDEADBEEF, body_off=0x1000 * i) for i in range(5))
    monkeypatch.setattr(E, "_read_stock_directory", lambda gr, im: MD.Directory(recs, 5, 0x9000, 0))

    class Reader(object):
        def iter_regular_files(self, **kw):
            return iter([("/godzilla_le/image.bin", 5, {})])

    lines = []
    plan, _e, _g = E._plan_sound_banks("game", str(img), params, audio_edits, grows, {}, used,
                                       Reader(), None, None, lambda m, *a: lines.append(m))
    sizes_of = {tuple(e.idx for e in g): SB.bank_bytes([e.body_bytes for e in g])
                for _c, g in plan.banks}
    assert (2,) in sizes_of and sizes_of[(2,)] > SB.BANK_SLICE
    assert all(n <= SB.BANK_SLICE for k, n in sizes_of.items() if k != (2,))
    assert len(set(c for c, _g in plan.banks)) == len(plan.banks)
    assert any("a bank of their own" in m for m in lines)
    # image.bin so big that the room beside it is under the song's 100 MB
    monkeypatch.setattr(SB, "MAPPED_MAX", 60_000_000)
    with pytest.raises(RuntimeError, match=r"M2's .* too long for this card.*minutes of stereo"):
        E._plan_sound_banks("game", str(img), params, audio_edits, grows, {}, used,
                            Reader(), None, None, lambda *a: None)
