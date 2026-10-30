"""PAD-855: a build from a card an earlier build grew drops that build's records nothing plays.

An owner's Godzilla Heisei card was built by an earlier version with its music modes' files in
image.bin (records appended past the stock array, left un-pointed: the mode runtime swapped
their keys in).  The extract brought the modes back, the next build added the same files
again, and the earlier copies stayed: image.bin at 2,010 MB, and a 3-minute song refused for
want of room beside it.  :func:`engine._ungrow_dead_records` cuts image.bin back to its stock
records when some appended ones are named by no play table, points the descriptors of the
ones still played back at their stock records, and hands those back decoded, for the build to
grow them again as they were.

Proven on a real card (the V2.1 Kaiju Edition build, 137 appended records, 12 of them dead):
the cut-back file is byte for byte stock Godzilla LE 1.16's size and directory, and all 2614
descriptor sites name the stock keys with the stock durations and waits.  Here the emulator,
the directory cipher and the play-table reader are stand-ins.
"""
import struct
import wave

import pytest

np = pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import engine as E            # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import emulator as EM  # noqa: E402
from pinball_decryptor.plugins.stern.spike2 import masterdir as MD  # noqa: E402

MASK = 0xE0001FFF
N = 4                       # stock records
MD_OFF = 0x1000             # the stock array, grown in place
FILE_END = 0x3000


def _key(n):
    return struct.pack("<II", 0x1000 + n, n & 0x1FFF)


def _rows():
    """Stock records 0..3, then appended 4 (idx 1 grown: played), 5 (idx 2: a music
    mode's file, dead) and 6 (idx 3 grown: played)."""
    stock = [dict(idx=i, body_off=0x100 * (i + 1), length=400, chan=1, stride=1,
                  identity=("s", i), findkey=_key(i)) for i in range(N)]
    app = [dict(idx=4, body_off=MD_OFF + 0x200, length=900, chan=1, stride=1,
                identity=("s", 1), findkey=_key(40)),
           dict(idx=5, body_off=MD_OFF + 0x800, length=1500, chan=2, stride=1,
                identity=("s", 2), findkey=_key(50)),
           dict(idx=6, body_off=MD_OFF + 0x1400, length=700, chan=1, stride=1,
                identity=("s", 3), findkey=_key(60))]
    return stock, app


def _site(sid, key, duration, off):
    """A play-table site naming *key*, its bytes whitened by a fixed keystream."""
    return E._DescSite(sid, off, b"\x5a" * 8, key, off + 8, b"\xa5" * 4, duration,
                       off + 12, b"\x3c" * 4, duration - 100)


class _FakeEmu:
    stock_only = False

    def __init__(self, gr, img, **_k):
        self.img = img

    def boot(self):
        pass

    def close(self):
        pass

    def decode(self, p):
        n = EM.emitted_length(p["length"])
        return (np.arange(n, dtype=np.int64) % 200 - 100,
                np.zeros(n, np.int64) if p["chan"] == 2 else None, p["chan"] == 2)

    def derive_params(self, **_k):
        stock, app = _rows()
        return stock + ([] if self.stock_only else app)


@pytest.fixture
def card(tmp_path, monkeypatch):
    img = tmp_path / "image.bin"
    data = bytearray(FILE_END)
    struct.pack_into("<I", data, MD.HDR_MD_OFF, MD_OFF)
    struct.pack_into("<I", data, MD.HDR_COUNT, N + 3)
    img.write_bytes(bytes(data))
    monkeypatch.setattr(EM, "Spike2Emu", _FakeEmu)
    monkeypatch.setattr(E, "_desc_key_mask", lambda *a, **k: MASK)
    monkeypatch.setattr(E, "_params_cache_dir", lambda: str(tmp_path / "cache"))
    monkeypatch.setattr(E, "_fingerprint", lambda *a: "f" * 64)

    class _Dir:
        count = N + 3
        records = b"\x11" * (MD.RECORD_SIZE * (N + 3))

        def with_records(self, records, count):
            d = _Dir()
            d.records, d.count = records, count
            return d

    written = []

    def _write(d, emu):
        written.append((d.count, d.md_off, len(d.records)))
        return {d.md_off: b"\xee" * MD.tail_len(d.count), MD.HDR_COUNT: struct.pack("<I", d.count)}

    monkeypatch.setattr(MD, "read_directory", lambda path, emu: _Dir())
    monkeypatch.setattr(MD, "write_directory", _write)
    _FakeEmu.stock_only = False
    return img, written


def _params():
    stock, app = _rows()
    return EM.collapse_shadowed(stock + app)


def _sites(dead_named=False):
    s = [_site(10, _key(40), 5000, 0x80), _site(11, _key(60), 3000, 0xa0),
         _site(12, _key(0), 2000, 0xc0)]
    if dead_named:
        s.append(_site(13, _key(50), 1000, 0xe0))
    return s


def _plain(raw, ks):
    return bytes(a ^ b for a, b in zip(raw, ks))


def test_the_collapse_reads_the_card_as_three_grown_sounds():
    p = {r["idx"]: r for r in _params()}
    assert [p[i].get("shadows") for i in range(N)] == [None, 4, 5, 6]


def test_a_card_whose_appended_records_are_all_played_is_left_as_it_is(card):
    img, written = card
    before = img.read_bytes()
    sites = [s for s in _sites() if s.sid != 12] + [_site(13, _key(50), 1000, 0xe0)]
    assert E._ungrow_dead_records("gr", str(img), _params(), sites, lambda *a: None) is None
    assert img.read_bytes() == before and not written


def test_dead_records_cut_the_file_back_and_the_played_ones_come_back_decoded(
        card, monkeypatch):
    img, written = card
    real_derive = _FakeEmu.derive_params

    def derive(self, **k):              # the file as it is once cut back: stock records only
        _FakeEmu.stock_only = True
        return real_derive(self, **k)

    monkeypatch.setattr(_FakeEmu, "derive_params", derive)
    logs = []
    carried = E._ungrow_dead_records("gr", str(img), _params(), _sites(),
                                     lambda m, *a: logs.append(m), family=True)
    # the array cut back to the stock records, in place, and the file to its end
    assert written == [(N, MD_OFF, MD.RECORD_SIZE * N)]
    data = img.read_bytes()
    assert len(data) == MD_OFF + MD.tail_len(N)
    assert struct.unpack_from("<I", data, MD.HDR_COUNT)[0] == N
    # the played ones (idx 1 and 3) come back as their own decoded samples, not idx 2
    assert sorted(carried) == [1, 3]
    with wave.open(carried[1]) as w:
        assert w.getnframes() == EM.emitted_length(900) and w.getnchannels() == 1
    # each played site names its stock record again, its duration and wait moved back
    for s, stock_i, grown_len in ((_sites()[0], 1, 900), (_sites()[1], 3, 700)):
        assert _plain(data[s.off:s.off + 8], s.keystream) == _key(stock_i)
        grew = E._duration_units_emitted(grown_len) - E._duration_units(400)
        assert struct.unpack("<I", _plain(data[s.dur_off:s.dur_off + 4],
                                          s.dur_keystream))[0] == s.duration - grew
        assert struct.unpack("<I", _plain(data[s.wait_off:s.wait_off + 4],
                                          s.wait_keystream))[0] == s.wait - grew
    # a site of a sound never grown is not touched
    s = _sites()[2]
    assert data[s.off:s.off + 8] == b"\x00" * 8
    assert any("1 of the 3 records" in m for m in logs)


def test_the_restore_is_exactly_undone_by_the_regrow(card, monkeypatch):
    """The re-point moves a duration by emitted(new) - units(stock); the restore moved it
    back by emitted(grown) - units(stock), so growing the same length again lands it where
    the card had it."""
    img, _w = card
    real_derive = _FakeEmu.derive_params
    monkeypatch.setattr(_FakeEmu, "derive_params",
                        lambda self, **k: (setattr(_FakeEmu, "stock_only", True),
                                           real_derive(self, **k))[1])
    E._ungrow_dead_records("gr", str(img), _params(), _sites(), lambda *a: None, family=True)
    data = img.read_bytes()
    s = _sites()[0]
    restored = struct.unpack("<I", _plain(data[s.dur_off:s.dur_off + 4], s.dur_keystream))[0]
    regrow = E._duration_units_emitted(900) - E._duration_units(400)
    assert restored + regrow == s.duration


def test_an_array_moved_past_the_earlier_bodies_is_left_as_it_is(card):
    img, written = card
    data = bytearray(img.read_bytes())
    struct.pack_into("<I", data, MD.HDR_MD_OFF, FILE_END - 0x100)
    img.write_bytes(bytes(data))
    assert E._ungrow_dead_records("gr", str(img), _params(), _sites(), lambda *a: None) is None
    assert not written


def test_a_played_record_with_variants_keeps_the_card_as_it_is(card, monkeypatch):
    img, written = card
    monkeypatch.setattr(EM, "bands_of", lambda p: 2 if p.get("length") == 900 else 1)
    logs = []
    assert E._ungrow_dead_records("gr", str(img), _params(), _sites(),
                                  lambda m, *a: logs.append(m)) is None
    assert not written and "variant" in logs[0]


def test_a_carried_sound_is_levelled_against_its_own_file(tmp_path):
    path = tmp_path / "c.wav"
    x = (np.arange(1000) % 300 - 150).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(x.tobytes())
    got = E._level_ref_render(None, {}, {"chan": 1}, E._LEVEL_SELF, np, wav=str(path))
    assert got.dtype == np.int64 and list(got[:5]) == list(x[:5].astype(np.int64))
    assert E._level_ref_render(None, {}, {"chan": 1}, E._LEVEL_SELF, np) is E._LEVEL_REF_UNSET
