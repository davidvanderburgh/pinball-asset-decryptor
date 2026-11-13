"""PAD-1235: a card built with music modes, written again with them.

An owner's original was a shared Godzilla card another owner had built with music modes (34 sound
banks of this app's).  Writing it again put the music modes' files into new banks beside the old
ones, so image.bin's list had room for 1 more and the Write was refused ("need 35 sound banks on
this card, and image.bin can name only 1 more"), while the same project on Stern's own card fits.
The earlier Write's banks that hold only the modes' sounds and game sounds this build puts in again
are now RETIRED: this build's banks take their names and their places in image.bin's list, and one
no new bank takes is emptied.  A bank that still holds a game sound this build leaves alone stays.

Fast, no card and no firmware (the PAD-606 planner fixtures).
"""
import struct

import pytest

from pinball_decryptor.plugins.stern import bank_build as BB
from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD
from pinball_decryptor.plugins.stern.spike2 import soundbank as SB
from tests.test_pad606_game_sounds_in_banks import _image, _rec

MB = 1_000_000


def _pad_bank(smap, count=2):
    """The bytes of a bank of this app's with the sid map *smap* ``{fragment: game sid}``."""
    md_off = 0x400
    size = md_off + MD.tail_len(count)
    b = bytearray(size)
    struct.pack_into("<I", b, SB.HDR_MD_OFF, md_off)
    struct.pack_into("<I", b, SB.HDR_COUNT, count)
    at = md_off + MD.align16(MD.RECORD_SIZE * count) + 4
    b[at:at + 4] = SB.PAD_TRAILER
    blk = SB.sid_map_block(smap, count)
    b[md_off - len(blk):md_off] = blk
    return bytes(b)


class _Card(object):
    """image.bin and the earlier Write's banks in the game's directory."""

    def __init__(self, banks):
        self.files = {"/godzilla_le/image.bin": b""}
        for cat, smap in banks.items():
            self.files["/godzilla_le/%s" % SB.bank_name(cat)] = _pad_bank(smap)

    def iter_regular_files(self, **kw):
        return iter([(p, 5, {"size": len(d), "path": p}) for p, d in self.files.items()])

    def read_range(self, node, off, n):
        return self.files[node["path"]][off:off + n]


def test_the_fake_banks_read_as_banks_of_this_apps():
    data = _pad_bank({1: 501})
    assert SB.is_pad_bank_at(lambda o, n: data[o:o + n], len(data))
    assert SB.read_sid_map(data) == {1: 501}


def _plan(monkeypatch, tmp_path, retire_touched, ids=(1, 2, 3)):
    img = _image(tmp_path)
    sizes = {1: 30 * MB, 2: 20 * MB}                      # two songs, a bank each
    params = [{"idx": i, "chan": 2, "length": 100, "findkey": bytes([i]) * 8} for i in sizes]
    grows = {i: (100, n // 4) for i, n in sizes.items()}
    audio_edits = {i: "C:/proj/audio/idx%04d - SONG %d.wav" % (i, i) for i in grows}
    monkeypatch.setenv(BB.BANK_CAP_ENV, "1000")
    monkeypatch.setattr(SB, "BANK_SLICE", 5 * MB)
    monkeypatch.setattr(SB, "MAPPED_MAX", 400 * MB)
    # image.bin names the earlier Write's three banks and has no room for a fourth
    monkeypatch.setattr(SB, "category_slots", lambda head: (len(ids), list(ids), 0))
    monkeypatch.setattr(E, "_read_stock_directory",
                        lambda gr, im: MD.Directory(b"".join(_rec(i) for i in range(3)), 3,
                                                    0x9000, 0))
    # bank 1: a music mode's files alone; bank 2: the game's sound id 777, which this build
    # leaves alone; bank 3: the game's sound id 501, which this build puts in again
    card = _Card({1: {}, 2: {0: 777}, 3: {1: 501}})
    logged = []
    plan = E._plan_sound_banks(
        "game", str(img), params, audio_edits, grows, dict(grows), [], card, None, None,
        lambda t, *a: logged.append(t), game_sids={i: 500 + i for i in grows},
        retire_touched=retire_touched)
    return plan, logged


def test_the_earlier_writes_banks_were_refused_room_before(monkeypatch, tmp_path):
    # (as the build was: image.bin's list full of the earlier Write's banks)
    with pytest.raises(E.SoundRoomError, match="image.bin can name only 0 more"):
        _plan(monkeypatch, tmp_path, None)


def test_a_rebuild_takes_the_names_of_the_earlier_writes_banks(monkeypatch, tmp_path):
    plan, logged = _plan(monkeypatch, tmp_path, {501, 502})
    plan = plan[0]
    assert sorted(plan.retired) == [1, 3]                 # not 2: sound id 777 still plays it
    assert sorted(c for c, _g in plan.banks) == [1, 3]
    assert sorted(e.idx for _c, g in plan.banks for e in g) == [1, 2]
    assert [t for t in logged if "image-sc01.bin, image-sc03.bin" in t
            and "this build's banks take their place" in t]


def test_the_header_names_the_kept_bank_and_this_builds(tmp_path):
    head = bytearray(0x200)
    struct.pack_into("<I", head, SB.HDR_FRAG_TABLE, SB.IMG_CAT_IDS + 4 * 3)   # room for 3 ids
    struct.pack_into("<I", head, SB.IMG_CAT_COUNT, 3)
    for i, c in enumerate((1, 2, 3)):
        struct.pack_into("<I", head, SB.IMG_CAT_IDS + 4 * i, c)
    with pytest.raises(SB.SoundBankError, match="room for 0 more"):
        SB.header_writes_new_categories(bytes(head), [1, 3])
    for off, b in SB.header_writes_new_categories(bytes(head), [1, 3], drop=[1, 3]).items():
        head[off:off + len(b)] = b
    assert SB.category_slots(bytes(head)) == (3, [2, 1, 3], 0)
    # a build that needs fewer banks than it retired: the list is shorter, the rest zeroed
    for off, b in SB.header_writes_new_categories(bytes(head), [4], drop=[1, 2, 3]).items():
        head[off:off + len(b)] = b
    assert SB.category_slots(bytes(head)) == (1, [4], 2)
    assert struct.unpack_from("<3I", head, SB.IMG_CAT_IDS) == (4, 0, 0)
    # no drop: as before, the new ids follow the ones there
    for off, b in SB.header_writes_new_categories(bytes(head), [5]).items():
        head[off:off + len(b)] = b
    assert SB.category_slots(bytes(head)) == (2, [4, 5], 1)
