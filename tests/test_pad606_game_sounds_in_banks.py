"""PAD-606: a longer replacement of one of the GAME's own sounds can go into a sound bank.

A cat-0 sid's descriptor can only name an image.bin record (the key's category bits come
from the sid), so a game sound in a bank is played by a sid of the bank's category, and the
game is made to play that sid: its request table's sid lists, which the play worker reads at
every play, name the bank sid where they named the game's (how the music titles play their
own banks' songs).  The bank keeps a sid map saying which game sid each sound stands in
for, so a later Write of the same card can put the lists back.

Fast, no card and no firmware: the request lists come from the synthetic ELF of
``test_stern_sound_requests``; the emulator-gated end (the banked game sounds played in the
game's own capture) is the ticket's rig proof.
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_stern_sound_requests import make_elf

FRAGS = 64


def _head(frags=FRAGS, sounds=40):
    """An image.bin head container_counts accepts: its own size, then the fragment and
    sound words at 0x5c / 0x60."""
    h = bytearray(0x200)
    struct.pack_into("<Q", h, 0, 0xB0)
    struct.pack_into("<III", h, 0x58, 0, frags, sounds)
    struct.pack_into("<I", h, 0x28, 0xF8)
    return bytes(h)


def _lists():
    """Request chains over sids 0..FRAGS-1: sid 5 in two requests, sid 7 in one with
    another sid, sid 9 in none."""
    out = [[(i * 3) % FRAGS] for i in range(FRAGS)]
    out = [[s for s in l if s not in (5, 7, 9)] or [11] for l in out]
    out[1] = [5]
    out[2] = [7, 12]
    out[3] = [5, 13]
    out[0] = [FRAGS - 1]
    out.append([])
    return out


def _site(sid, payload, duration=4000):
    return E._DescSite(sid, 0x1000 + sid * 0x40, b"\0" * 8, payload, 0x1004 + sid * 0x40,
                       b"\0" * 4, duration)


# --------------------------------------------------------------------------
# the bank's sid map
# --------------------------------------------------------------------------
def _bank_file(n, orig, trailer=SB.PAD_TRAILER):
    """A bank-shaped file of *n* records: header, sid map, then a directory tail with
    *trailer* where :func:`.soundbank.is_pad_bank` reads it."""
    md_off = 0x400 + SB.sid_map_len(n)
    size = md_off + MD.tail_len(n)
    data = bytearray(size)
    data[0:SB.HDR_LEN] = SB.bank_header(size, md_off, n, n)
    data[md_off - SB.sid_map_len(n):md_off] = SB.sid_map_block(orig, n)
    at = md_off + MD.align16(MD.RECORD_SIZE * n) + 4
    data[at:at + 4] = trailer
    return bytes(data)


def test_the_sid_map_names_the_game_sid_each_bank_sound_stands_in_for():
    data = _bank_file(3, {0: 1251, 2: 618})
    assert SB.read_sid_map(data) == {0: 1251, 2: 618}       # fragment 1: a mode's own
    # a vendor bank, and a bank built before PAD-606 (no map), read as none
    assert SB.read_sid_map(_bank_file(3, {0: 1}, trailer=b"\0\0\0\0")) == {}
    old = bytearray(_bank_file(3, {0: 1}))
    old[0x400:0x404] = b"\0\0\0\0"
    assert SB.read_sid_map(bytes(old)) == {}
    assert SB.read_sid_map(b"not a bank") == {}


def test_plan_bank_leaves_room_for_the_sid_map_before_the_directory(tmp_path):
    d, places = SB.plan_bank([SB.BankEdit(4, b"\0" * 24, 0x10, 0x30, 1000)])
    desc_end = places[0].desc_off + SB.DESC_SLOT
    assert d.md_off == MD.align16(desc_end) + SB.sid_map_len(1)
    assert SB.bank_bytes([1000]) == d.file_size()
    p = tmp_path / "image-sc01.bin"
    p.write_bytes(b"\0" * d.file_size())
    SB.write_sid_map(str(p), d.md_off, 1, {0: 77})
    raw = p.read_bytes()
    assert raw[d.md_off - SB.sid_map_len(1):][:12] == SB.SID_MAP_MAGIC + struct.pack("<II", 1, 77)


def test_card_sid_map_reads_the_banks_of_ours_by_their_category():
    class Reader(object):
        files = {"/g/image-sc03.bin": _bank_file(2, {1: 1251}),
                 "/g/image-sc01.bin": _bank_file(2, {}, trailer=b"\0\0\0\0"),
                 "/g/image.bin": b"x" * 64}

        def iter_regular_files(self, **kw):
            return iter([(p, 0, {"size": len(d), "p": p}) for p, d in self.files.items()])

        def read_range(self, node, off, n):
            return self.files[node["p"]][off:off + n]

    assert BB.card_sid_map(Reader()) == {SB.bank_sid(3, 1): 1251}


def test_a_sound_too_big_for_a_bank_slice_gets_a_bank_of_its_own():
    edits = [SB.BankEdit(i, b"\0" * 24, 1, 2, b) for i, b in enumerate((600, 5000, 600))]
    limit = SB.bank_bytes([600, 600]) + 8
    banks = SB.split_banks(edits, limit=limit, alone=SB.bank_bytes([5000]))
    assert [[e.idx for e in b] for b in banks] == [[1], [0, 2]]
    with pytest.raises(SB.SoundBankError):
        SB.split_banks(edits, limit=limit)


# --------------------------------------------------------------------------
# the game's request lists
# --------------------------------------------------------------------------
def test_request_list_slots_find_every_place_a_list_names_a_sid():
    elf, _reg = make_elf(_lists())
    slots = BB.request_list_slots(elf, _head())
    assert len(slots[5]) == 2 and len(slots[7]) == 1 and 9 not in slots
    for off in slots[5]:
        assert struct.unpack_from("<I", elf, off)[0] == 5
    assert BB.request_list_slots(b"\0" * 64, _head()) == {}


def test_list_writes_point_a_banked_sid_at_its_bank_and_put_an_earlier_one_back():
    elf, _reg = make_elf(_lists())
    slots = BB.request_list_slots(elf, _head())
    b_new, b_old = SB.bank_sid(2, 0), SB.bank_sid(1, 4)
    w = BB.list_writes(slots, {}, {5: b_new})
    assert sorted(w) == sorted(slots[5]) and set(w.values()) == {struct.pack("<I", b_new)}
    # a card an earlier Write gave a bank sid for 7: the stock view counts it as 7
    card = bytearray(elf)
    for o in slots[7]:
        card[o:o + 4] = struct.pack("<I", b_old)
    cslots = BB.request_list_slots(bytes(card), _head())
    assert BB.stock_slots(cslots, {b_old: 7})[7] == slots[7]
    # this Write keeps 7 in image.bin: the game's sid again
    assert BB.list_writes(cslots, {b_old: 7}, {}) == {o: struct.pack("<I", 7) for o in slots[7]}
    # ... or puts it in a bank of its own
    assert BB.list_writes(cslots, {b_old: 7}, {7: b_new}) == {
        o: struct.pack("<I", b_new) for o in slots[7]}
    # an earlier bank sid for a sound this Write leaves alone is not in old_map: it stays
    assert BB.list_writes(cslots, {}, {5: b_new}) == w


def test_game_sound_sids_take_a_sound_one_listed_sid_plays_and_say_why_not_the_rest():
    elf, _reg = make_elf(_lists())
    slots = BB.request_list_slots(elf, _head())
    mask = 0xE0001FFF
    key = {i: struct.pack("<II", 0x1000 + i, i) for i in range(10)}
    byidx = {i: {"idx": i, "findkey": key[i]} for i in range(10)}
    sites = [_site(5, key[1]),                       # idx 1: sid 5, in two requests
             _site(7, key[2]),                       # idx 2: sid 7
             _site(9, key[3]),                       # idx 3: sid 9, in no request
             _site(12, key[4]), _site(13, key[4]),   # idx 4: two sids
             _site(14, key[5]), _site(14, key[6]),   # idx 5: sid 14 in two parts
             _site(15, key[7])]                      # idx 7: a mode's request plays sid 15
    grows = {i: (100, 1000) for i in (1, 2, 3, 4, 5, 7, 8)}
    ok, why = BB.game_sound_sids(grows, byidx, sites, mask, slots, exclude={15})
    assert ok == {1: 5, 2: 7}
    assert "other than through its sound requests" in why[3]
    assert why[4].startswith("2 of the game's sound ids")
    assert "one of 2 parts" in why[5]
    assert "a mode of this card plays" in why[7]
    assert why[8] == "no sound id of the game's plays it"


# --------------------------------------------------------------------------
# the engine
# --------------------------------------------------------------------------
def _image(tmp_path, md_off=1000, count=10):
    img = tmp_path / "image.bin"
    h = bytearray(_head())
    struct.pack_into("<I", h, 0x40, md_off)
    struct.pack_into("<I", h, 0x60, count)
    img.write_bytes(bytes(h))
    return img


def _rec(i):
    r = bytearray(range(24))
    struct.pack_into("<I", r, 0, 0x1000 * i)
    struct.pack_into("<I", r, 16, 0x100 ^ 0xDEADBEEF)
    return bytes(r)


class _Reader(object):
    def iter_regular_files(self, **kw):
        return iter([("/godzilla_le/image.bin", 5, {})])


def test_plan_sound_banks_moves_the_users_longer_game_sounds_into_a_bank(monkeypatch, tmp_path):
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in (1, 2, 3)]
    byidx = {p["idx"]: p for p in params}
    grows = {1: (100, 4000), 2: (100, 3000), 3: (100, 2000)}
    audio_edits = {i: "s%d.wav" % i for i in grows}
    cap = E._grown_bank_bytes(1000, 10, [E._grown_body_bytes(byidx[3], 2000)])
    monkeypatch.setenv(BB.BANK_CAP_ENV, str(cap))
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(4)), 4, 0x9000, 0))
    lines = []
    # no modes at all: 1 and 2 can move (3 is played by two sids, say)
    plan, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None, None,
        lambda m, *a: lines.append(m), game_sids={1: 501, 2: 502},
        game_why={3: "2 of the game's sound ids play it"})
    assert plan is not None
    assert sorted(plan.grows) == [1, 2] and plan.game == {1: 501, 2: 502}
    assert sorted(grows2) == [3] and sorted(edits2) == [3]
    assert [e.idx for e in plan.banks[0][1]] == [1, 2]
    assert any("the game's sound id 501 (idx 1)" in m for m in lines)
    assert any("idx 3 stays in image.bin rather than a sound bank: 2 of the game's sound "
               "ids play it" in m for m in lines)
    assert any("The longer sounds go into 1 sound bank(s)" in m for m in lines)
    # everything fits: nothing moves
    monkeypatch.delenv(BB.BANK_CAP_ENV)
    plan, e3, g3 = E._plan_sound_banks("game", str(img), params, audio_edits, grows, dict(grows),
                                       [], _Reader(), None, None, lambda *a: None,
                                       game_sids={1: 501, 2: 502})
    assert plan is None and e3 == audio_edits and g3 == grows


def test_a_game_sound_too_long_for_a_slice_gets_a_bank_of_its_own(monkeypatch, tmp_path):
    """Every bank with a sound playing stays mapped beside image.bin (Godzilla LE 1.16:
    0x43cdcc takes a reference at a sound's start, 0x43c254 drops it, 0x3b57d8 unmaps only
    the idle ones), so a bank is cut at an eighth of what image.bin leaves; a game sound
    longer than that gets a bank to itself as a mode's song does (PAD-777), and only one
    too long for even that stays in image.bin."""
    img = _image(tmp_path)
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in (1, 2)]
    grows = {1: (100, 4_000_000), 2: (100, 1000)}          # a 16 MB body and a small one
    audio_edits = {i: "s%d.wav" % i for i in grows}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "MAPPED_MAX", 8 * 10_000_000)  # 10 MB a bank
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(3)), 3, 0x9000, 0))

    def plan():
        lines = []
        got = E._plan_sound_banks(
            "game", str(img), params, audio_edits, grows, dict(grows), [], _Reader(), None,
            None, lambda m, *a: lines.append(m), game_sids={1: 501, 2: 502})
        return got, lines

    (p, edits2, grows2), lines = plan()
    assert p.game == {1: 501, 2: 502} and grows2 == {} and edits2 == {}
    assert sorted(len(g) for _c, g in p.banks) == [1, 1]
    assert any("get a bank of their own" in m for m in lines)
    # past the biggest bank Stern ships it stays in image.bin
    monkeypatch.setattr(SB, "BANK_MAX_SEEN", 12_000_000)
    (p, edits2, grows2), lines = plan()
    assert p.game == {2: 502} and sorted(grows2) == [1] and sorted(edits2) == [1]
    assert any("idx 1 stays in image.bin rather than a sound bank: at 16.0 MB" in m
               for m in lines)


def test_longer_game_songs_leave_a_music_mode_file_room(monkeypatch, tmp_path):
    """PAD-777: game songs a little past a slice used to stay in image.bin, which grew it,
    which shrank the slice so more stayed, until a music mode's file had 0 MB (Iron Maiden
    LE 1.18: image.bin 2,428 MB).  They go into banks of their own, image.bin keeps its
    size and the file gets its bank."""
    img = _image(tmp_path)
    mb = 1_000_000
    frames = lambda n: (n * mb - 4096) // 4 - 2000          # a stereo body of about n MB
    # 100 MB of memory, 10 MB slices: six game songs from 10.5 to 13 MB, a 30 MB mode song
    grows = {i: (100, frames(10 + i / 2.0)) for i in range(1, 7)}
    grows[8] = (100, frames(30))
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in grows]
    used = [{"idx": 8, "music": True, "sid": 618, "key": "music", "name": "SONG"}]
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "MAPPED_MAX", 160 * mb)
    monkeypatch.setattr(SB, "BANK_SLICE", 10 * mb)
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(9)), 9, 0x9000, 0))
    lines = []
    p, edits2, grows2 = E._plan_sound_banks(
        "game", str(img), params, {i: "s.wav" for i in grows}, grows, {}, used, _Reader(),
        None, None, lambda m, *a: lines.append(m), game_sids={i: 500 + i for i in range(1, 7)})
    assert grows2 == {} and edits2 == {}
    assert sorted(p.game) == [1, 2, 3, 4, 5, 6]
    assert sorted(e.idx for _c, g in p.banks for e in g) == [1, 2, 3, 4, 5, 6, 8]
    assert not any("stays in image.bin" in m for m in lines)


def test_build_sound_banks_plays_a_game_sound_by_its_own_descriptor_and_maps_its_sid(
        monkeypatch, tmp_path):
    from pinball_decryptor.plugins.stern.spike2 import emulator as EM
    img = tmp_path / "image.bin"
    img.write_bytes(_head())
    params = [{"idx": 40, "chan": 1, "length": 1000, "findkey": b"\x01" * 8}]
    plan = E._BankPlan([(1, [SB.BankEdit(40, b"\0" * 24, 1000, 5000, 20000)])], {40: "a.wav"},
                       {40: (1000, 5000)}, "godzilla_le")
    plan.game = {40: 501}
    d, places = SB.plan_bank([SB.BankEdit(40, b"\0" * 24, 1000, 5000, 20000)])
    bank = tmp_path / "image-sc01.bin"
    bank.write_bytes(SB.bank_header(d.file_size(), d.md_off, 1, 1) + b"\0" * (
        d.file_size() - SB.HDR_LEN))
    (tmp_path / "game").write_bytes(b"\0" * 64)

    class FakeEmu(object):
        def __init__(self, *a, **k):
            pass

        def boot(self):
            return self

        def close(self):
            pass

    monkeypatch.setattr(EM, "Spike2Emu", FakeEmu)
    monkeypatch.setattr(E, "_mode_music_level_refs", lambda *a, **k: {})
    monkeypatch.setattr(BB, "stage_bank", lambda *a, **k: (str(bank), places))
    rows = [{"idx": 0, "host": 40, "length": 5000, "findkey": b"\xaa" * 8}]
    monkeypatch.setattr(BB, "chain_encode", lambda *a, **k: (rows, {}, 0))
    monkeypatch.setattr(BB, "verify_bank", lambda *a, **k: rows)
    tables = {}

    def write_tables(gr, im, path, cat, pl, rws, carriers, durations, music_idx, log):
        tables.update(carriers=carriers, durations=durations, music=set(music_idx))
        return {r["idx"]: (SB.bank_sid(cat, r["idx"]), b"\x05", 0) for r in rws}

    monkeypatch.setattr(BB, "write_bank_tables", write_tables)
    monkeypatch.setattr(BB, "verify_tables", lambda *a, **k: None)
    sites = [_site(501, b"\x01" * 8, duration=E._duration_units(1000) + 7)]
    E._build_sound_banks(str(tmp_path / "game"), str(img), params, sites, plan, [], set(), {},
                         str(tmp_path), None, lambda *a, **k: None)
    assert tables["carriers"] == {40: 501} and tables["music"] == set()
    # its own descriptor's duration, moved by the growth (a base of 7 kept)
    new = (E._duration_units_emitted(5000) if E._mode_family_on()
           else E._duration_units(5000))
    assert tables["durations"] == {40: new + 7}
    assert plan.banked == {501: 0x10000}
    raw = bank.read_bytes()
    at = d.md_off - SB.sid_map_len(1)
    assert raw[at:at + 12] == SB.SID_MAP_MAGIC + struct.pack("<II", 1, 501)


def test_sound_list_writes_go_into_a_staged_program_or_in_place(tmp_path):
    elf, _reg = make_elf(_lists())
    slots = BB.request_list_slots(elf, _head())
    img = tmp_path / "image.bin"
    img.write_bytes(_head())
    staged = tmp_path / "game_real"
    staged.write_bytes(elf)
    lines = []
    w, ov, n = E._sound_list_writes(None, None, str(staged), str(img), {}, {5: 0x10000}, set(),
                                    lambda m, *a: lines.append(m))
    assert (w, ov, n) == ([], {}, 2)
    out = staged.read_bytes()
    assert all(struct.unpack_from("<I", out, o)[0] == 0x10000 for o in slots[5])
    assert any("2 place(s)" in m for m in lines)

    class Reader(object):
        def read_file_bytes(self, node):
            return elf

        def disk_ranges(self, node, off, n):
            return [(0x100000 + off, n)]

    w, ov, n = E._sound_list_writes(Reader(), {"i_block": b"x"}, None, str(img), {},
                                    {7: 0x10001}, set(), lambda *a: None)
    assert n == 1 and ov == {slots[7][0]: struct.pack("<I", 0x10001)}
    assert w == [(0x100000 + slots[7][0], struct.pack("<I", 0x10001))]
    # a banked sid no list names would leave the card playing the original
    with pytest.raises(RuntimeError, match="no sound request"):
        E._sound_list_writes(Reader(), {"i_block": b"x"}, None, str(img), {}, {9: 0x10002},
                             set(), lambda *a: None)


def test_a_long_mode_song_gets_the_room_left_beside_the_other_banks(monkeypatch, tmp_path):
    """PAD-607 with PAD-606 (David's middle rule): every bank with a sound playing stays
    mapped beside image.bin, so a long song's own bank gets MAPPED_MAX less image.bin and
    the (up to 7) other banks that can play beside it; one longer than that is refused by
    name with how big it may be."""
    img = _image(tmp_path)
    mb = 1_000_000
    frames = lambda n: (n * mb - 4096) // 4 - 2000          # a stereo body of about n MB
    small = {i: (100, frames(4)) for i in (1, 2, 3, 4)}       # four 4 MB calls
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "MAPPED_MAX", 80 * mb)           # 10 MB slices: two calls a bank
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(7)), 7, 0x9000, 0))

    def plan(song_mb):
        grows = dict(small)
        grows[6] = (100, frames(song_mb))
        params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in grows]
        used = [{"idx": i, "swap": True, "key": "call:%d" % i, "name": "M%d" % i} for i in small]
        used.append({"idx": 6, "music": True, "sid": 618, "key": "music", "name": "SONG"})
        lines = []
        got = E._plan_sound_banks("game", str(img), params, {i: "s.wav" for i in grows}, grows,
                                  {}, used, _Reader(), None, None, lambda m, *a: lines.append(m))
        return got[0], lines

    p, lines = plan(50)                                      # 80 - 16 MB of calls: room 64
    sizes = sorted(SB.bank_bytes([e.body_bytes for e in g]) for _c, g in p.banks)
    assert len(p.banks) == 3 and sizes[-1] > 49 * mb and sum(sizes) <= 80 * mb
    assert any("get a bank of their own" in m for m in lines)
    with pytest.raises(RuntimeError, match=r"SONG's .* beside the 2 other bank\(s\)"):
        plan(70)
