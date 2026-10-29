"""PAD-830: an extract's sound decode on a computer short of memory.

Eight decode emulators ran a laptop out of commit (every program Windows then
started failed, 0xc000012d); a worker's MemoryError ended the whole pool and
restarted the decode in one process; a music bank whose worker ran out of
memory came back as 0 songs, silently.  The pools are held to the memory there
is room for, and what ran out is decoded again on its own."""
import multiprocessing
import os
import wave

import numpy as np
import pytest

from pinball_decryptor.plugins.stern import engine as E
from pinball_decryptor.plugins.stern.spike2 import category as C
from pinball_decryptor.plugins.stern.spike2 import parallel as P


class _Emu:
    def __init__(self, exc=None):
        self.exc = exc

    def decode(self, p, progress=None):
        if self.exc is not None:
            raise self.exc
        return np.arange(10, dtype=np.int64), None, False


@pytest.mark.parametrize("exc,want", [
    (MemoryError("Unable to allocate 679. KiB for an array"), P.NO_MEMORY),
    (RuntimeError("Unable to allocate memory on host (UC_ERR_NOMEM)"), P.NO_MEMORY),
    (RuntimeError("bad codec"), False),
])
def test_decode_to_wav_tells_out_of_memory_from_a_bad_sound(monkeypatch, tmp_path, exc, want):
    monkeypatch.setattr(P, "_EMU", _Emu(exc))
    assert P.decode_to_wav(({"idx": 7}, str(tmp_path / "a.wav"))) == (7, want)


def test_decode_to_wav_writes_the_sound(monkeypatch, tmp_path):
    monkeypatch.setattr(P, "_EMU", _Emu())
    out = tmp_path / "a.wav"
    assert P.decode_to_wav(({"idx": 3}, str(out))) == (3, True)
    with wave.open(str(out)) as w:
        assert (w.getnchannels(), w.getnframes()) == (1, 10)


def test_out_of_memory_words():
    assert P.out_of_memory(MemoryError())
    err = OSError("The paging file is too small for this operation to complete")
    assert P.out_of_memory(err)
    assert not P.out_of_memory(ValueError("no such sound"))


def test_decode_workers_held_to_the_memory_there_is(monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    lines = []
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 3 * P.EMU_COMMIT_EXTRA)
    assert E._decode_workers("img", lambda m, lvl="info": lines.append(m)) == 3
    assert "3 sound decoder(s)" in lines[0]
    lines.clear()
    monkeypatch.setattr(P, "commit_room", lambda: None)     # Linux, macOS
    assert E._decode_workers("img", lambda m, lvl="info": lines.append(m)) == 8
    assert lines == []


class _InlinePool:
    """multiprocessing's Pool, run in this process."""
    def __init__(self, n, **kw):
        self.n = n

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def imap_unordered(self, fn, items):
        return map(fn, list(items)[::-1])

    def terminate(self):
        pass


class _Ctx:
    pools = []

    def Pool(self, n, **kw):
        self.pools.append(n)
        return _InlinePool(n, **kw)


def test_bank_that_ran_out_of_memory_is_decoded_again_alone(monkeypatch, tmp_path):
    files = [str(tmp_path / ("image-sc%02d.bin" % c)) for c in (1, 2, 3)]
    for f in files:
        open(f, "wb").close()
    monkeypatch.setattr(C, "read_category_id", lambda p: int(p[-6:-4]))
    monkeypatch.setattr(C, "_find_revalidate", lambda *a: 0x1234)
    monkeypatch.setattr(multiprocessing, "get_context", lambda kind: _Ctx())
    monkeypatch.setattr(P, "commit_room", lambda: P.COMMIT_RESERVE + 4 * P.EMU_COMMIT_EXTRA)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    tries = {}

    def worker(task):
        cat = task[3]
        tries[cat] = tries.get(cat, 0) + 1
        if cat == 2 and tries[cat] == 1:      # beside the others: no memory
            return P.NO_MEMORY, 0
        if cat == 3:                          # not even alone
            return P.NO_MEMORY, 0
        return 5, 0
    monkeypatch.setattr(C, "_bank_pool_worker", worker)
    lines = []
    _Ctx.pools = []
    n = C.extract_category_audio_parallel(
        "gr", "img", files, str(tmp_path),
        log=lambda m, lvl="info": lines.append((lvl, m)))
    assert n == 10                            # banks 1 and 2 (the second go)
    assert tries == {1: 1, 2: 2, 3: 2}
    assert _Ctx.pools == [2]                  # 4 GB of room = two bank decoders
    text = "\n".join(m for _l, m in lines)
    assert "Music bank 2 ran out of memory beside the others" in text
    assert ("error", next(m for _l, m in lines if m.startswith("Music bank(s) 3"))) in lines


def test_off_windows_the_room_is_the_ram(monkeypatch):
    """An 8 GB Mac: four sound decoders and two music-bank decoders, not eight."""
    monkeypatch.setattr(os, "sysconf", {"SC_PHYS_PAGES": 2 << 20,
                                        "SC_PAGE_SIZE": 4096}.__getitem__, raising=False)
    assert P._ram() == 8 << 30
    monkeypatch.setattr(P, "commit_room", P._ram)
    assert P.emulators_that_fit(P.emulator_commit("img"), 8) == 4
    assert P.emulators_that_fit(2 * P.emulator_commit("img"), 8) == 2
    monkeypatch.setattr(os, "sysconf", lambda k: (_ for _ in ()).throw(ValueError(k)),
                        raising=False)
    assert P._ram() is None
