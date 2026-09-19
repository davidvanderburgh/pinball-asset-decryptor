"""Tests for :mod:`pinball_decryptor.plugins.stern.video_bank`.

A clip of a mode's own is one more entry in the in-game video bank scene's two clip
maps. The bar is that NOTHING stock moves: every stock clip keeps its name, id, path
and size, and taking our two entries back out gives the stock file byte for byte.
That is checked on Godzilla Pro 1.15's real bank (game data outside the repo, skipped
where absent, as on CI) and structurally on a synthetic bank built from the grammar,
along with the refusals. Desk work only: no card, no emulator, no rig.
"""

import hashlib
import os
import struct

import pytest

from pinball_decryptor.plugins.stern import video_bank as VB

CORPUS = r"C:\tmp\radium_scene_re\godzilla_pro_1_15"
BANK = os.path.join(CORPUS, "auto_loaded_%s.radium" % VB.GODZILLA_PRO_BANK)
BANK_MD5 = "fe35b5b897c2b0df6fe583b0168a6cda"
F = VB.FLAG


def _s(t):
    b = t.encode("latin1")
    return struct.pack("<Q", len(b)) + b


def _video(names, first, start_id=2, sizes=None):
    out = struct.pack("<I", 2) + _s("video.test") + struct.pack("<IIIB", 1360, 768, 1, 0)
    out += struct.pack("<Q", len(names))
    for i, n in enumerate(names):
        cid = start_id + i
        if first:
            out += _s(n) + struct.pack("<I", F | cid) + _s("2.asset/%d.asset" % i)
            out += struct.pack("<I", (sizes or {}).get(n, 1000 + i))
        else:
            out += _s(n) + struct.pack("<I", cid)
    return out


def synthetic(names=("Alpha", "Delta", "zeta")):
    """A bank laid out exactly like the stock one: library, stage, one VideoSurface node."""
    names = list(names)
    n = len(names)
    out = b"\x01" + struct.pack("<Q", 1) + struct.pack("<I", 2) + struct.pack("<I", F | 1) + _s("Video")
    out += struct.pack("<I", F | 1) + _video(names, True)
    out += struct.pack("<QQ", 0, 0) + struct.pack("<II5f", 1360, 768, 12.0, 0, 0, 0, 1.0)
    out += struct.pack("<I", 0) + _s("") + struct.pack("<I", 2) + struct.pack("<Q", 1)
    node = struct.pack("<I", F | (n + 2)) + _s("VideoSurface") + struct.pack("<I", 1)
    node += struct.pack("<Q", 2) + struct.pack("<IB", 1, 1) + struct.pack("<IB", 2, 1)
    node += struct.pack("<Q", 0)
    node += struct.pack("<Q", 1) + struct.pack("<I", 1) + struct.pack("<16f", *([1.0] + [0.0] * 15))
    node += struct.pack("<Q", 1) + struct.pack("<III", 1, 1, F | (n + 3)) + _video(names, False)
    node += struct.pack("<Q", 0)
    out += node + struct.pack("<QQ", 0, 0)
    out += struct.pack("<Q", 2) + _s("Normal") + struct.pack("<I", 1) + _s("SquareCrop") + struct.pack("<I", 2)
    return out


def _strip(new, name):
    """Remove the clip ``name`` from both maps again and restore the counts."""
    bank = VB.parse(new)
    out = bytearray(new)
    for vm in (bank.surface, bank.library):          # later map first
        clip = next(c for c in vm.entries if c.name == name)
        del out[clip.start:clip.end]
        struct.pack_into("<Q", out, vm.count_at, len(vm.entries) - 1)
    return bytes(out)


# ---- synthetic ------------------------------------------------------------------------
def test_synthetic_bank_walks():
    bank = VB.parse(synthetic())
    assert [c.name for c in bank.library.entries] == ["Alpha", "Delta", "zeta"]
    assert [c.path for c in bank.library.entries] == ["2.asset/0.asset", "2.asset/1.asset", "2.asset/2.asset"]
    assert bank.surface_node == "VideoSurface"
    assert bank.labels == [("Normal", 1), ("SquareCrop", 2)]
    assert bank.max_id == 6
    assert VB.next_path(bank) == "2.asset/3.asset"


def test_add_clip_goes_in_sorted_in_both_maps():
    data = synthetic()
    new, info = VB.add_clip(data, "Kaiju", 4242)
    bank = VB.parse(new)
    assert [c.name for c in bank.library.entries] == ["Alpha", "Delta", "Kaiju", "zeta"]
    assert [c.name for c in bank.surface.entries] == ["Alpha", "Delta", "Kaiju", "zeta"]
    ours = bank.library.entries[2]
    assert (ours.clip_id, ours.path, ours.size) == (7, "2.asset/3.asset", 4242)
    assert bank.surface.entries[2].clip_id == 7
    assert info == {"name": "Kaiju", "clip_id": 7, "path": "2.asset/3.asset", "size": 4242,
                    "clips": 4, "md5": hashlib.md5(new).hexdigest()}
    assert _strip(new, "Kaiju") == data


def test_add_clip_sorts_by_bytes_so_lowercase_goes_last():
    new, _ = VB.add_clip(synthetic(), "zzz", 1)
    assert [c.name for c in VB.parse(new).surface.entries][-1] == "zzz"
    new, _ = VB.add_clip(synthetic(), "Aa", 1)
    assert [c.name for c in VB.parse(new).library.entries][0] == "Aa"


@pytest.mark.parametrize("name, size, path, why", [
    ("Delta", 1, None, "already has"),
    ("has space", 1, None, "printable"),
    ("", 1, None, "printable"),
    ("Ok", 0, None, "u32"),
    ("Ok", 1, "2.asset/1.asset", "already lives"),
])
def test_add_clip_refuses(name, size, path, why):
    with pytest.raises(VB.VideoBankError, match=why):
        VB.add_clip(synthetic(), name, size, path)


def test_parse_refuses_a_file_that_does_not_end_where_the_walk_does():
    with pytest.raises(VB.VideoBankError, match="walk ended"):
        VB.parse(synthetic() + b"\x00")
    with pytest.raises(VB.VideoBankError):
        VB.parse(synthetic()[:-3])


def test_parse_refuses_a_surface_naming_a_clip_the_library_lacks():
    data = bytearray(synthetic())
    at = data.rindex(_s("zeta") + struct.pack("<I", 4))
    struct.pack_into("<I", data, at + len(_s("zeta")), 5)
    with pytest.raises(VB.VideoBankError, match="not that clip"):
        VB.parse(bytes(data))


# ---- the real Godzilla Pro 1.15 bank ---------------------------------------------------------
def _stock():
    if not os.path.exists(BANK):
        pytest.skip("stock video bank not present: %s" % BANK)
    data = open(BANK, "rb").read()
    assert hashlib.md5(data).hexdigest() == BANK_MD5
    return data


def test_stock_bank_walks_exactly():
    bank = VB.parse(_stock())
    assert bank.video_name == "video.in_game_videos"
    assert (bank.width, bank.height) == (1360, 768)
    assert len(bank.library.entries) == len(bank.surface.entries) == 598
    names = [c.name for c in bank.library.entries]
    assert names == sorted(names, key=lambda s: s.encode())
    assert "Mothra_godzilla_attack20" in names and "EndOfBallBonus_BackgroundLoop" in names
    assert bank.labels == [("LetterboxCrop", 4), ("Normal", 1), ("ScoreFrame", 2), ("SquareCrop", 3)]
    assert bank.max_id == 0x259
    assert VB.next_path(bank) == "2.asset/598.asset"


def test_stock_bank_grows_by_one_clip_and_nothing_stock_moves():
    data = _stock()
    new, info = VB.add_clip(data, "KaijuRush_Clip", 1257317)
    assert (info["clip_id"], info["path"], info["clips"]) == (0x25A, "2.asset/598.asset", 599)
    before = {c.name: (c.clip_id, c.path, c.size) for c in VB.parse(data).library.entries}
    after = {c.name: (c.clip_id, c.path, c.size) for c in VB.parse(new).library.entries}
    assert after.pop("KaijuRush_Clip") == (0x25A, "2.asset/598.asset", 1257317)
    assert after == before
    assert _strip(new, "KaijuRush_Clip") == data
