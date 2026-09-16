"""The blip-free cave on a card an earlier blip-free Write already caved.

A modder who extracts his own built card and writes the next version from it
hands the Write a firmware whose window-read function starts with our branch
instead of its prologue.  The signature locator found nothing there, so every
such build fell back to the standard one with "this firmware isn't supported
by the blip-free cave" (PAD-160: Godzilla Pro 1.16, V1.8 -> V1.81).

Under test, with the emulator stood in for by what it measures on a caved
card (a redirected window shows up in the consumed map as only the 4 bytes the
signature check reads before redirecting):

* the old cave is recognised, and stripping it gives back the firmware it was
  built from;
* a rebuild carries the old cave's windows -- with the STOCK bytes it stashed,
  not the re-encoded bytes the card now holds there -- adds this build's, and
  is byte-identical to building every one of those sounds from the stock card;
* a text extension segment written after the old cave ends up at the end of
  the file again, so longer text can still extend it;
* a caved firmware this version can't read says so instead of blaming the
  firmware.
"""
import struct

import pytest

np = pytest.importorskip("numpy")

from pinball_decryptor.plugins.stern import engine as E, progreloc  # noqa: E402
from tests.test_stern_text_grow import (                            # noqa: E402
    PAGE, PT_GNU_STACK, PT_NOTE, TEXT_OFF, TEXT_VA, _grow_elf)

FN = TEXT_VA + 0x100                 # the window-read function
FN_OFF = TEXT_OFF + 0x100
FIRST_OFF = 0x40                     # in no sound's body
BODY = 0x1000                        # sound k's body is [k*BODY, (k+1)*BODY)
WINDOWS = (0x100, 0x600)             # two 512-byte windows per body


def _stock_firmware():
    raw = bytearray(_grow_elf()[0])
    struct.pack_into("<III", raw, FN_OFF, *E._CAVE_SIG)
    # PT_GNU_STACK as Stern ships it (Godzilla LE 1.16: p_align 0x10), which
    # is what a strip puts back.
    struct.pack_into("<I", raw, 0x34 + 2 * 32 + 28, 0x10)
    return bytes(raw)


def _stock_image():
    return bytes((i * 7 + 3) & 0xFF for i in range(8 * BODY))


@pytest.fixture
def rig(monkeypatch, tmp_path):
    """Write files and build caves the way the Write does, with the two
    emulator measurements replaced by what they return on the card."""
    def consumed(gr_path, img_path, patches, np_, log=None, progress=None):
        with open(gr_path, "rb") as f:
            cave = E._find_pad_cave(bytearray(f.read()))
        redirected = {lo for lo, _hi, _s in (cave["windows"] if cave else ())}
        out = {}
        for off in patches:
            got = []
            for w in WINDOWS:
                lo = off + w
                got.extend(range(lo, lo + (4 if lo in redirected else 0x200)))
            out[off] = np.array(got, np.int64)
        return out

    def first_off(gr_path, img_path, fn):
        assert fn == FN
        return FIRST_OFF

    monkeypatch.setattr(E, "_replaced_consumed_offsets", consumed)
    monkeypatch.setattr(E, "_capture_first_window_off", first_off)

    class Rig:
        logs = []

        def put(self, name, data):
            p = tmp_path / name
            p.write_bytes(data)
            return str(p)

        def build(self, fw, img, sounds, tag):
            out = tmp_path / tag
            out.mkdir()
            patches = {k * BODY: b"\xee" * BODY for k in sounds}
            path, _size = E._build_derive_redirect_cave(
                self.put(tag + ".fw", fw), self.put(tag + ".img", img),
                patches, np, lambda m, *a: self.logs.append(m), str(out))
            with open(path, "rb") as f:
                return f.read()

    return Rig()


def _card_image(sounds):
    """The stock image with *sounds*' bodies re-encoded, as a build left it."""
    img = bytearray(_stock_image())
    for k in sounds:
        img[k * BODY:(k + 1) * BODY] = b"\xee" * BODY
    return bytes(img)


def _loads(raw):
    return list(E._iter_phdrs(raw))


def test_a_caved_firmware_is_recognised_and_strips_back_to_stock(rig):
    stock = _stock_firmware()
    caved = rig.build(stock, _stock_image(), (1, 2), "v1")

    assert E._locate_window_read_fn(bytearray(caved)) is None   # the bug
    cave = E._find_pad_cave(bytearray(caved))
    assert cave is not None and cave["fn"] == FN
    img = _stock_image()
    assert [(lo, hi) for lo, hi, _s in cave["windows"]] == [
        (k * BODY + w, k * BODY + w + 0x200) for k in (1, 2) for w in WINDOWS]
    assert all(s == img[lo:hi] for lo, hi, s in cave["windows"])

    stripped = bytearray(caved)
    assert E._strip_pad_cave(stripped)["fn"] == FN
    # The firmware it was built from, padded to the page the cave started on.
    assert bytes(stripped[:len(stock)]) == stock
    assert not any(stripped[len(stock):]) and len(stripped) % PAGE == 0
    assert E._locate_window_read_fn(stripped) == FN
    # Nothing to strip on a firmware without a cave.
    plain = bytearray(stock)
    assert E._strip_pad_cave(plain) is None and bytes(plain) == stock


def test_rebuilding_carries_the_old_windows_with_their_stock_bytes(rig):
    stock = _stock_firmware()
    v1 = rig.build(stock, _stock_image(), (1, 2), "v1")
    # V1 -> V2: sound 2 replaced again, sound 3 for the first time, written
    # from the card V1 built (whose windows for 1 and 2 hold the re-encode).
    rig.logs.clear()
    v2 = rig.build(v1, _card_image((1, 2)), (2, 3), "v2")

    assert any("already carries one from an earlier build" in m
               for m in rig.logs), rig.logs
    cave = E._find_pad_cave(bytearray(v2))
    img = _stock_image()
    assert [(lo, hi) for lo, hi, _s in cave["windows"]] == [
        (k * BODY + w, k * BODY + w + 0x200)
        for k in (1, 2, 3) for w in WINDOWS]
    assert all(s == img[lo:hi] for lo, hi, s in cave["windows"])
    # One cave, one PT_GNU_STACK spent, PT_NOTE untouched.
    assert sum(1 for p in _loads(v2) if p[5] == 7) == 1
    types = [struct.unpack_from("<I", v2, 0x34 + i * 32)[0]
             for i in range(struct.unpack_from("<H", v2, 0x2c)[0])]
    assert PT_GNU_STACK not in types and PT_NOTE in types

    # Exactly what building all three from the stock card gives: no second
    # cave, no leftover pages, nothing that grows build over build.
    rig_fresh = rig.build(stock, _stock_image(), (1, 2, 3), "fresh")
    assert v2 == rig_fresh
    assert rig.build(v2, _card_image((1, 2, 3)), (3,), "v3") == rig_fresh


def test_a_text_segment_after_the_old_cave_ends_up_last_again(rig):
    v1 = bytearray(rig.build(_stock_firmware(), _stock_image(), (1,), "v1"))
    va, off, _gap = E._append_extension_segment(
        v1, 12 + 20, 4, allow_above=False, slots=(PT_GNU_STACK, PT_NOTE))
    v1[off:off + 12] = progreloc.extension_header(12 + 20)
    v1[off + 12:off + 32] = b"A" * 20

    v2 = rig.build(bytes(v1), _card_image((1,)), (2,), "v2")
    seg = E._find_extension_segment(v2)
    assert seg is not None
    t_va, t_off, t_size, used = seg
    assert (t_va, t_size, used) == (va, PAGE, 32)
    assert t_off + t_size == len(v2)
    assert v2[t_off + 12:t_off + 32] == b"A" * 20
    assert E._text_reloc_plan(bytearray(v2))[0] is not None
    assert len(E._find_pad_cave(bytearray(v2))["windows"]) == 4


def test_a_cave_this_version_cannot_read_says_so(rig):
    caved = bytearray(rig.build(_stock_firmware(), _stock_image(), (1,), "v1"))
    cave = E._find_pad_cave(caved)
    struct.pack_into("<I", caved, cave["off"] + 54 * 4, 0)   # no RET literal
    assert E._find_pad_cave(caved) is None
    with pytest.raises(RuntimeError, match="older version of PAD"):
        rig.build(bytes(caved), _card_image((1,)), (2,), "v2")
    # And the extent cutter only ever takes whole appended pages.
    with pytest.raises(RuntimeError, match="can't be taken back out"):
        E._cut_file_extent(bytearray(caved), cave["off"] + 1, PAGE)
    with pytest.raises(RuntimeError, match="can't be taken back out"):
        E._cut_file_extent(bytearray(caved), 0, PAGE)
