"""PAD-608: the music modes' files (PAD-494) and the sounds in turn (PAD-565) can go into a sound
bank when image.bin is full, as the modes' own sounds (PAD-595) and the longer replacements of the
game's own (PAD-606) do.

The game plays a bank's sound only under a sound id of the bank's own (it streams from the file of
the id's category), and those files are switched at run time, so each one gets a bank fragment for
every game sound id that plays its slot (a song in parts is played by its opening ids and its "NO
INTRO" ids: one record, several fragments, each with that id's own descriptor naming the bank's
record), and the runtime points the game's request lists at the bank's ids at the play worker's
entry whenever the setting or the turn wants that file (``bsid`` / ``tsid`` lines). The card's
record names such a file's record as ``<bank>:<record>``, and an extract decodes it back.

Fast, no card and no firmware: the request lists come from the synthetic ELF of
``test_stern_sound_requests``. The end to end proof (a Try it set of stock Godzilla LE 1.16 on
the rig, the files heard in the game's own capture) is the ticket's.
"""
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern import media_share as MS
from pinball_decryptor.plugins.stern import sound_modes as SMo
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_pad606_game_sounds_in_banks import FRAGS, _head, _site
from tests.test_stern_sound_requests import make_elf

HERE = os.path.dirname(os.path.abspath(__file__))
RUNTIME = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")
TUNE = "audio/idx2241 - SE GZ MX TUNE 16.wav"
CALL = "audio/idx1239.wav"
MASK = 0xE0001FFF


def _record(word=0x10 ^ 0xDEADBEEF):
    r = bytearray(24)
    struct.pack_into("<I", r, 16, word)
    return bytes(r)


# --------------------------------------------------------------------------
# the bank: fragments past the records that play one of them
# --------------------------------------------------------------------------
def test_a_bank_gives_a_record_more_fragments_past_the_records():
    d, places = SB.plan_bank([SB.BankEdit(2241, _record(), 0x10, 0x30, 1000),
                              SB.BankEdit(1239, _record(), 0x10, 0x20, 500)],
                             aliases=[2241, 2241, 1239])
    recs = SB.records(places)
    assert [(p.idx, p.new_idx, p.record) for p in places] == [
        (2241, 0, None), (1239, 1, None), (2241, 2, 0), (2241, 3, 0), (1239, 4, 1)]
    assert [SB.record_of(p) for p in places] == [0, 1, 0, 0, 1]
    assert recs == places[:2] and d.count == 2
    # five fragments in the table before the bodies (which start past room for
    # MD.GROW_SLOTS of them, PAD-677), five descriptor slots after them
    tables = MD.GROW_SLOTS * SB.DEFAULT_STRIDE * SB.FRAG_SLOT + 16
    assert recs[0].body_off == MD.align16(SB.HDR_LEN + tables) + MD.BODY_PAD
    desc0 = MD.align16(recs[1].body_off + 500 + MD.BODY_PAD)
    assert [p.desc_off for p in places] == [desc0 + SB.DESC_SLOT * n for n in range(5)]
    # an alias plays its record's body
    assert places[2].body_off == recs[0].body_off and places[4].body_off == recs[1].body_off
    # the sid map is still one word a record
    assert d.md_off == MD.align16(desc0 + 5 * SB.DESC_SLOT) + SB.sid_map_len(2)
    assert d.file_size() == SB.bank_bytes([1000, 500], aliases=3)
    assert SB.bank_bytes([1000, 500], aliases=3) > SB.bank_bytes([1000, 500])
    with pytest.raises(SB.SoundBankError):
        SB.plan_bank([SB.BankEdit(1, _record(), 0x10, 0x30, 10)], aliases=[2])
    # without aliases nothing moved (PAD-595 / PAD-606 banks)
    d0, p0 = SB.plan_bank([SB.BankEdit(1, _record(), 0x10, 0x30, 10)])
    assert [p.record for p in p0] == [None] and d0.file_size() == SB.bank_bytes([10])


def test_write_tables_points_an_alias_fragment_at_its_own_descriptor(tmp_path):
    import random
    rnd = random.Random(608)
    vf2 = bytes(rnd.getrandbits(8) for _ in range(SB.VF2_WINDOW + SB.DESC_SLOT))
    places = [SB.BankPlacement(7, 0, 0x100, 10, 20, 0x2000),
              SB.BankPlacement(7, 1, 0x100, 10, 20, 0x2050, record=0)]
    path = tmp_path / "image-sc03.bin"
    path.write_bytes(b"\0" * 0x2200)
    descs = {0: b"\x05\x01\x01" + b"A" * 30, 1: b"\x05\x1c\x01" + b"B" * 20}
    ks = SB.write_tables(str(path), places, descs, vf2, lambda off: off & 0x2a6, stride=5)
    data = path.read_bytes()
    for pl in places:
        slot = pl.new_idx * 5
        word, _hi = struct.unpack_from("<II", data, SB.HDR_LEN + slot * SB.FRAG_SLOT)
        assert word ^ struct.unpack_from("<I", vf2, SB.slot_vf2_offset(slot))[0] == pl.desc_off
        raw = data[pl.desc_off:pl.desc_off + len(descs[pl.new_idx])]
        assert bytes(a ^ b for a, b in zip(raw, vf2[ks[pl.new_idx]:])) == descs[pl.new_idx]


# --------------------------------------------------------------------------
# sounds.cfg and the card's record
# --------------------------------------------------------------------------
def test_the_runtime_table_names_each_bank_sound_id_beside_the_game_s():
    slot = bytes.fromhex("9ad919226f1d0000")
    text = SMo.cfg_text(0x7A4E78, 2, [], False, bsids=[(2, 2541, 0x30000), (2, 2500, 0x30001)],
                        tsids=[(2, slot, 16, 0x30002)])
    assert text.splitlines()[1:] == ["setting\t0x007a4e78\t2", "bsid\t2\t2541\t196608",
                                     "bsid\t2\t2500\t196609",
                                     "tsid\t2\t9ad919226f1d0000\t16\t196610"]


def test_the_card_record_names_a_bank_record_and_an_extract_reads_it_back():
    m = SMo.clean({"names": ["", "Orchestral"], "slots": {TUNE: {"2": "C:/x/Tune.wav"}},
                   "turns": {CALL: ["C:/x/B.wav", "C:/x/C.wav"]}})
    used = [{"rel": TUNE, "slot": 2241, "mode": 2, "host": 900, "db": 0, "lines": 4,
             "bank": 3, "bank_idx": 0},
            {"rel": CALL, "slot": 1239, "mode": SMo.turn_mode(2), "host": 901, "db": None,
             "lines": 1, "bank": 3, "bank_idx": 1},
            {"rel": CALL, "slot": 1239, "mode": SMo.turn_mode(3), "host": 902, "db": None,
             "lines": 1}]
    text = SMo.cfg_text(0, 2, [], False, record=SMo.card_record(m, used))
    assert "#file\t2\t2241\t3:0\t0\t" in text and "#turn\t2\t1239\t3:1\t-\t" in text
    assert "#turn\t3\t1239\t902\t-\t" in text
    rec = SMo.read_card_record(text)
    assert rec["files"] == [{"mode": 2, "slot": 2241, "host": 0, "bank": 3, "db": 0, "rel": TUNE,
                             "name": "Tune.wav"}]
    assert rec["turns"][0] == {"turn": 2, "slot": 1239, "host": 1, "bank": 3, "db": None,
                               "rel": CALL, "name": "B.wav"}
    assert "bank" not in rec["turns"][1] and rec["turns"][1]["host"] == 902
    assert SMo.card_bank_records(rec) == {3: {0, 1}}
    assert SMo.card_bank_records(None) == {}


def test_an_extract_brings_back_a_file_it_decoded_out_of_a_bank(tmp_path):
    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    (proj / "audio" / "idx2241 - SE GZ MX TUNE 16.wav").write_bytes(b"RIFF tune")
    (proj / "audio" / "idx1239.wav").write_bytes(b"RIFF call")
    dec = proj / MS.MUSIC_DIR / MS.FROM_CARD_DIR
    dec.mkdir(parents=True)
    (dec / "music_cat03_0000.wav").write_bytes(b"RIFF mode two")
    m = SMo.clean({"names": ["", "Orchestral"], "slots": {TUNE: {"2": "C:/x/Tune.wav"}},
                   "turns": {CALL: ["C:/x/B.wav"]}})
    used = [{"rel": TUNE, "slot": 2241, "mode": 2, "host": 900, "db": 0, "lines": 4,
             "bank": 3, "bank_idx": 0},
            {"rel": CALL, "slot": 1239, "mode": SMo.turn_mode(2), "host": 901, "db": None,
             "lines": 1, "bank": 3, "bank_idx": 1}]
    cfg = SMo.cfg_text(0, 2, [], False, record=SMo.card_record(m, used))
    record, left = MS.music_from_card(str(proj), cfg)
    got = record["slots"]["audio/idx2241 - SE GZ MX TUNE 16.wav"]["2"]
    with open(got, "rb") as f:
        assert f.read() == b"RIFF mode two"
    assert left == [(CALL, SMo.turn_mode(2),
                     "this extract could not decode record 1 of sound bank image-sc03.bin")]
    # the read-back removes what the extract decoded once it is copied
    MS.readback(str(proj), str(proj), padmode={SMo.CFG_NAME: cfg.encode()})
    assert not dec.exists()


def test_the_extract_asks_the_card_s_record_which_bank_records_to_decode(monkeypatch):
    from pinball_decryptor.plugins.stern import mode_from_card as MFC
    m = SMo.clean({"names": ["", "Orchestral"], "slots": {TUNE: {"2": "C:/x/Tune.wav"}}})
    used = [{"rel": TUNE, "slot": 2241, "mode": 2, "host": 900, "db": 0, "lines": 4,
             "bank": 5, "bank_idx": 2}]
    cfg = SMo.cfg_text(0, 2, [], False, record=SMo.card_record(m, used)).encode()
    monkeypatch.setattr(MFC, "read_padmode", lambda *a, **k: {SMo.CFG_NAME: cfg})
    assert E._card_bank_records("card.raw", [], None) == {5: {2}}
    monkeypatch.setattr(MFC, "read_padmode", lambda *a, **k: {})
    assert E._card_bank_records("card.raw", [], None) == {}

    def boom(*a, **k):
        raise MFC.CardModesError("not a card")
    monkeypatch.setattr(MFC, "read_padmode", boom)
    assert E._card_bank_records("card.raw", [], None) == {}
    assert E._PAD_BANK_FILES == (MS.MUSIC_DIR, MS.FROM_CARD_DIR)


# --------------------------------------------------------------------------
# the build
# --------------------------------------------------------------------------
def _lists():
    """Request chains over sids 0..FRAGS-1: 20 and 21 (a song's opening and its NO INTRO id)
    each in a request, 22 in one with another sid, 23 in none, 24 a mode's own carrier's."""
    out = [[(i * 3) % FRAGS] for i in range(FRAGS)]
    out = [[s for s in l if s not in (20, 21, 22, 23, 24, 25)] or [11] for l in out]
    out[1], out[2], out[3], out[4], out[5] = [20], [21], [22, 12], [24], [25]
    out[0] = [FRAGS - 1]
    out.append([])
    return out


def test_a_file_whose_every_sound_id_a_request_names_can_go_into_a_bank(monkeypatch, tmp_path):
    elf, _reg = make_elf(_lists())
    (tmp_path / "game").write_bytes(elf)
    (tmp_path / "image.bin").write_bytes(_head())
    key = {i: struct.pack("<II", 0x1000 + i, i) for i in range(12)}
    params = [{"idx": i, "findkey": key[i], "length": 44100 * (30 if i == 2 else 1)}
              for i in range(12)]
    sites = [_site(20, key[1]), _site(20, key[2]),     # sid 20: idx 1 (opening), then idx 2 (body)
             _site(21, key[2]),                        # sid 21: the body alone (NO INTRO)
             _site(22, key[3]), _site(22, key[4]),     # sid 22: idx 3 then idx 4, not a song
             _site(23, key[5]),                        # sid 23: idx 5, in no request
             _site(24, key[6]),                        # sid 24: idx 6, a mode's carrier plays it
             _site(25, key[7])]                        # sid 25: idx 7
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: MASK)
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "request_sids",
                        lambda elf_, head, req: [24] if req == 77 else [])
    used = [{"rel": "a", "slot": 1, "mode": 2, "host": 40, "song": {20: [2]}, "bodies": {21: [2]}},
            {"rel": "a", "slot": 1, "mode": 3, "host": 40, "song": {20: [2]}, "bodies": {21: [2]}},
            {"rel": "b", "slot": 3, "mode": 2, "host": 41},
            {"rel": "c", "slot": 5, "mode": 2, "host": 42},
            {"rel": "d", "slot": 6, "mode": 2, "host": 43},
            {"rel": "e", "slot": 7, "mode": SMo.turn_mode(2), "host": 44}]
    lines = []

    def no_descriptors(*a, **k):        # (PAD-791: a song in parts needs them read whole)
        raise RuntimeError("no resolver")
    monkeypatch.setattr(E, "_wide_descriptors_once", no_descriptors)
    frags, sids, seqs = E._sound_modes_for_banks(
        str(tmp_path / "game"), str(tmp_path / "image.bin"), params, sites, used,
        [{"request": 77}], {}, lambda m, *a: lines.append(m))
    # one record for one file in two modes: a fragment for each mode and each sound id
    assert [(u["mode"], s) for u, s in frags[40]] == [(2, 20), (2, 21), (3, 20), (3, 21)]
    assert [(u["mode"], s) for u, s in frags[44]] == [(SMo.turn_mode(2), 25)]
    assert sorted(frags) == [40, 44] and seqs == []
    # (PAD-791: the sound ids of the files that stay in image.bin stay the game's)
    assert sids == {22, 23, 24}
    text = "\n".join(lines)
    assert "sound id 22 plays sound idx 3 together with other sounds" in text
    # PAD-784: sid 23 is in no request: the game never plays it
    assert "the game never plays it: no sound request of the game's names sound id 23" in text
    assert "sound id 24 is one a mode of this card plays" in text


def test_a_bank_descriptor_names_the_bank_record_verbatim_and_nothing_else():
    key = struct.pack("<II", 0x5bf98007, 0xd73e0000 | 1 << 13)   # category bits set: a bank's key
    held = E._play_key(key, 0, MASK)
    other = struct.pack("<II", 0x12345678, 0x1fff)
    body = b"\x05\x00\x00\x10\x27\x00\x00" + b"\x07\x00" + b"\x0b\x00\x00\x00" + E._host_payload(
        b"\0" * 8, held, MASK) + b"\x11\x00" + b"\x00"
    desc = body + b"\x0b\x00\x00\x00" + other + b"\x00" * 20     # the next descriptor's bytes
    d = E._bank_descriptor(desc, 2541, len(body), held, key, MASK)
    assert d[:len(body)].count(key) == 1 and other not in d and len(d) <= SB.DESC_SLOT
    assert d[len(body):] == b"\0" * (len(d) - len(body))
    # a payload that plays another record cannot be a bank sound id's
    assert E._bank_descriptor(desc, 2541, None, held, key, MASK) is None


def test_the_runtime_lines_name_the_id_the_request_lists_hold():
    params = [{"idx": 1239, "findkey": b"S" * 8}]
    used = [{"rel": TUNE, "slot": 2241, "mode": 2, "bank": 3, "bank_sids": {2541: 0x30000,
                                                                            2500: 0x30001}},
            {"rel": CALL, "slot": 1239, "mode": SMo.turn_mode(3), "bank": 3,
             "bank_sids": {16: 0x30002}},
            {"rel": "audio/idx0007.wav", "slot": 7, "mode": 2, "bank": 3, "bank_sids": {}}]
    lines = []
    bsids, tsids = E._bank_sid_lines(params, used, {2500: 0x20004}, lambda m, *a: lines.append(m))
    assert bsids == [(2, 2541, 0x30000), (2, 0x20004, 0x30001)]
    assert tsids == [(3, b"S" * 8, 16, 0x30002)]
    assert [u["lines"] for u in used] == [2, 1, 0]
    assert lines == ["Music modes: idx0007.wav's file for mode 2 (Custom A) is left out: no sound "
                     "id of the game can play it from its sound bank."]


def test_the_lists_keep_an_earlier_write_s_bank_id_for_a_sound_this_one_leaves():
    class Plan(object):
        banked = {30: 0x40000}
    assert E._list_ids(Plan(), {0x20004: 2500, 0x20005: 31, 0x20006: 30}, {9: 31}) == {
        2500: 0x20004, 30: 0x40000}
    assert E._list_ids(None, {}, {}) == {}


# --------------------------------------------------------------------------
# the runtime
# --------------------------------------------------------------------------
def test_the_runtime_points_the_request_at_the_bank_s_id_at_the_play_worker():
    with open(RUNTIME, encoding="utf-8") as f:
        c = f.read()
    assert 'str_eq(f[0], "bsid")' in c and 'str_eq(f[0], "tsid")' in c
    assert "bsid_line(f[1], 0, f[2], f[3]);" in c and "bsid_line(f[1], f[2], f[3], f[4]);" in c
    # one hook on the worker for the sound log and the banks
    assert "if (blist_live) blist_play(r[0]);" in c
    # every place that hooks it goes through the one worker_hooked (PAD-645 adds the attract silence's and the
    # sound log's on a card of attract sounds alone)
    sites = c.count('hook(fn("sound_worker"), on_sound_worker)')
    assert sites >= 2 and c.count('(worker_hooked = hook(fn("sound_worker"), on_sound_worker))') == sites
    assert "(worker_hooked = hook(fn(\"sound_worker\"), on_sound_worker))" in c
    # armed before the music modes' resolver wrap, which a bank-only card does not need
    arm = c[c.index("static void sndm_arm(void)"):]
    assert arm.index("blist_arm();") < arm.index("if (n_sndt || n_bsid || att.n || n_jmode) return;")   # PAD-641
    # a pointer someone else put there (a mode's carrier, pm_sound_sid) is left alone
    play = c[c.index("static void blist_play(unsigned request)"):]
    assert "cur != e->orig && cur != (unsigned)(unsigned long)e->list[0]" in play
    # a turn the worker moves on is not moved again by the record lookup
    look = c[c.index("static void sndt_lookup(unsigned *r)\n{"):]
    assert look.index("if (t->by_worker)") < look.index("now = pm_ms();")


def test_every_shipped_port_but_one_old_build_names_the_play_worker():
    ports = os.path.join(HERE, "..", "tools", "spike2_emu", "modes", "sdk", "ports")
    lacking = []
    for name in sorted(os.listdir(ports)):
        if name.endswith(".port"):
            with open(os.path.join(ports, name), encoding="utf-8") as f:
                words = [line.split()[:2] for line in f]
            if ["site", "sound_worker"] not in words or ["data", "sound_requests"] not in words:
                lacking.append(name)
    assert lacking == ["turtles_pro-1.58.port"]
    for key in SMo.TURN_PROVEN | SMo.PROVEN:
        assert key + ".port" not in lacking
