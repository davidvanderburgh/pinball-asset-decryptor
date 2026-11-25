"""PAD-1584: a card rewrite sends only the chunks that changed.

After a write, every chunk's hash is remembered against the card.  The next
write onto that card writes the chunks the new image changed straight away,
and READS every other chunk off the card, leaving it alone only when the card
holds exactly those bytes.  So a stale record costs time, never a wrong
card, and the full verify still runs after it."""

import json
import os

import pytest

from pinball_decryptor.core import rawdevice as rd
from tests.test_flash_card_read_errors import _SEC, _menu_case
from tests.test_stern_flash import _pattern

_CH = 64 * 512                  # a small chunk, so an image has many
_N = 40


@pytest.fixture(autouse=True)
def _small_chunks(monkeypatch):
    monkeypatch.setattr(rd, "_FLASH_CHUNK", _CH)


def _written(monkeypatch, path):
    """``[(offset, length)]`` of every write to *path* from here on (a new
    list each call; the spy is put in once)."""
    seen = []
    if not getattr(rd._FdIO.write, "_pad_spy", False):
        real_seek, real_write = rd._FdIO.seek, rd._FdIO.write

        def seek(self, pos):
            self._pad_at = pos
            return real_seek(self, pos)

        def write(self, data):
            n = real_write(self, data)
            for want, into in _SPY:
                if os.path.abspath(self.path) == os.path.abspath(want):
                    into.append((self._pad_at, n))
            self._pad_at += n
            return n
        write._pad_spy = True
        monkeypatch.setattr(rd._FdIO, "seek", seek)
        monkeypatch.setattr(rd._FdIO, "write", write)
    _SPY[:] = [(path, seen)]
    return seen


_SPY = []


def _bytes(seen):
    return sum(n for _p, n in seen)


def _case(tmp_path):
    img = tmp_path / "img.raw"
    img.write_bytes(_pattern(_N * _CH))
    card = tmp_path / "card.raw"
    card.write_bytes(b"\xA5" * (_N * _CH + 8192))
    return str(img), str(card)


def _poke(path, at, data):
    with open(path, "r+b") as f:
        f.seek(at)
        f.write(data)


def _flash(img, card, **k):
    log = []
    k.setdefault("skip_free", False)
    rd.flash_image_to_device(img, card, eject=False,
                             log=lambda m, _l="": log.append(m), **k)
    return log


def test_second_write_sends_only_the_changed_chunk(tmp_path, monkeypatch):
    img, card = _case(tmp_path)
    _flash(img, card)
    _poke(img, 17 * _CH + 100, b"NEW BYTES")
    seen = _written(monkeypatch, card)
    log = _flash(img, card)
    assert seen and all(17 * _CH <= p < 18 * _CH for p, _n in seen)
    assert _bytes(seen) == _CH
    assert open(card, "rb").read(_N * _CH) == open(img, "rb").read()
    assert any("was already on the card and was left as it was" in m
               for m in log)
    assert any("Card verified" in m for m in log)


def test_first_write_onto_a_card_writes_it_all(tmp_path, monkeypatch):
    img, card = _case(tmp_path)
    seen = _written(monkeypatch, card)
    _flash(img, card)
    assert _bytes(seen) == _N * _CH


def test_a_stale_record_never_leaves_the_card_wrong(tmp_path, monkeypatch):
    """The card was changed behind the record's back (the machine wrote its
    data, another tool, a bad sector): those chunks are seen on the card and
    written again, though the record says they are as written."""
    img, card = _case(tmp_path)
    _flash(img, card)
    _poke(card, 5 * _CH + 3, b"MACHINE WROTE THIS")
    _poke(card, 30 * _CH, b"\0" * 512)
    seen = _written(monkeypatch, card)
    _flash(img, card)
    assert sorted({p // _CH for p, _n in seen}) == [5, 30]
    assert open(card, "rb").read(_N * _CH) == open(img, "rb").read()


def test_a_record_saying_changed_is_written_without_a_look(tmp_path,
                                                           monkeypatch):
    img, card = _case(tmp_path)
    _flash(img, card)
    _poke(img, 9 * _CH, b"CHANGED")
    looked = []
    real = rd.RawDeviceFile._aligned_read

    def spy(self, start, length):
        if self.writable:
            looked.append(start)
        return real(self, start, length)
    monkeypatch.setattr(rd.RawDeviceFile, "_aligned_read", spy)
    _flash(img, card)
    assert 9 * _CH not in looked
    assert 10 * _CH in looked


def test_another_card_or_a_rewritten_one_is_not_taken_for_it(tmp_path,
                                                             monkeypatch):
    img, card = _case(tmp_path)
    _flash(img, card)
    # the first chunk is not what was written there: not this record's card
    _poke(card, 0, b"ELSEWHERE")
    seen = _written(monkeypatch, card)
    _flash(img, card)
    assert _bytes(seen) == _N * _CH


def test_a_card_of_another_size_is_not_taken_for_it(tmp_path, monkeypatch):
    img, card = _case(tmp_path)
    _flash(img, card)
    with open(card, "ab") as f:
        f.write(b"\0" * 4096)
    seen = _written(monkeypatch, card)
    _flash(img, card)
    assert _bytes(seen) == _N * _CH


def test_write_every_chunk_turns_it_off(tmp_path, monkeypatch):
    img, card = _case(tmp_path)
    _flash(img, card)
    monkeypatch.setenv("PAD_WRITE_EVERY_CHUNK", "1")
    seen = _written(monkeypatch, card)
    _flash(img, card)
    assert _bytes(seen) == _N * _CH


def test_a_failed_verify_forgets_the_card(tmp_path, monkeypatch):
    img, card = _case(tmp_path)
    _flash(img, card)
    real = rd.RawDeviceFile.copy_image_onto

    def flaky(self, *a, **k):
        n = real(self, *a, **k)
        self.seek(3 * _CH)
        self.write(b"\0" * 512)
        return n
    monkeypatch.setattr(rd.RawDeviceFile, "copy_image_onto", flaky)
    _poke(img, 3 * _CH, b"CHANGED")
    with pytest.raises(rd.FlashError):
        _flash(img, card)
    assert json.load(open(os.environ["PAD_CARD_RECORD"])) == []


def test_the_record_follows_every_write(tmp_path, monkeypatch):
    """Three writes in the edit, write, test loop: each sends only its own
    change, and the record keeps one entry for the card."""
    img, card = _case(tmp_path)
    _flash(img, card)
    for n, chunk in enumerate((4, 22, 4)):
        _poke(img, chunk * _CH + n, b"EDIT %d" % n)
        seen = _written(monkeypatch, card)
        _flash(img, card)
        assert {p // _CH for p, _n in seen} == {chunk}
    assert len(json.load(open(os.environ["PAD_CARD_RECORD"]))) == 1
    assert open(card, "rb").read(_N * _CH) == open(img, "rb").read()


def test_cards_are_told_apart(tmp_path, monkeypatch):
    img, card = _case(tmp_path)
    other = tmp_path / "other.raw"
    other.write_bytes(b"\x11" * (_N * _CH + 8192))
    img2 = tmp_path / "img2.raw"
    img2.write_bytes(_pattern(_N * _CH)[::-1])
    _flash(img, card)
    _flash(str(img2), str(other))
    _poke(img, 7 * _CH, b"X")
    seen = _written(monkeypatch, card)
    _flash(img, card)
    assert {p // _CH for p, _n in seen} == {7}


def test_keep_data_is_compared_with_the_overlay_in_place(tmp_path,
                                                         monkeypatch):
    """With the card's own data kept, the chunks compared are the image with
    that data in place, which is what the card holds."""
    img, card = _case(tmp_path)
    kept = (12 * _CH + 40, b"SCORES" * 50)
    monkeypatch.setattr(rd, "card_data_overlay", lambda *a, **k: kept)
    _flash(img, card, keep_data=True)
    seen = _written(monkeypatch, card)
    _flash(img, card, keep_data=True)
    assert seen == []
    on = open(card, "rb").read()
    assert on[kept[0]:kept[0] + len(kept[1])] == kept[1]


def test_progress_says_what_was_left_alone(tmp_path):
    img, card = _case(tmp_path)
    _flash(img, card)
    lines = []
    _flash(img, card, progress=lambda d, t, s="": lines.append(s))
    assert any("already on the card" in s for s in lines)


def test_a_menu_write_sends_only_its_changed_chunks(tmp_path, monkeypatch):
    img, card = _menu_case(tmp_path)
    # the card as the app wrote it, remembered; then the menu edit
    raw = open(img, "rb").read()
    good = bytearray(raw)
    good[128 * _SEC:128 * _SEC + 64] = open(card, "rb").read()[
        128 * _SEC:128 * _SEC + 64]
    (tmp_path / "was.raw").write_bytes(bytes(good))
    with open(card, "wb") as f:
        f.write(b"\0" * len(good))
    _flash(str(tmp_path / "was.raw"), str(card))
    monkeypatch.setattr(rd, "_FLASH_CHUNK", 16 * _SEC)
    seen = _written(monkeypatch, str(card))
    n = rd.flash_menu_to_device(img, str(card))
    assert n == 128 * _SEC
    assert seen and all(128 * _SEC <= p < 144 * _SEC for p, _n in seen)
    assert open(card, "rb").read()[128 * _SEC:128 * _SEC + 16] == \
        b"A DIFFERENT MENU"
    # and the record now has the menu's new chunks: the whole flash after it
    # writes nothing
    monkeypatch.setattr(rd, "_FLASH_CHUNK", _CH)
    seen = _written(monkeypatch, str(card))
    _flash(img, str(card))
    assert seen == []
