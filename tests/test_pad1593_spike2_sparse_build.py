"""PAD-1593: a Spike 2 build's card copy is written compact (sparse).

The build used to lay a full-size copy of the card at build/<card>-modified.raw
(shutil.copyfile: 7 to 28 GB, the card's free space written out as zeros).  It
now goes through core.sparse_card.sparse_copy, as the Spike 3 build does: the
zero runs stay holes, the file reads back byte for byte what a plain copy
gives, and a drive that cannot keep holes gets the zeros written instead.  The
real-card proof (Deadpool Pro 1.16: 7.86 GB -> 4.73 GB on disk, every file the
same as a plain-copy build, boots on the rig) is in the ticket; these pin it.
"""
import os
import sys

import pytest

from pinball_decryptor.core import rawdevice as rd
from pinball_decryptor.core import sparse_card
from pinball_decryptor.plugins.stern import engine

MB = 1024 * 1024


def _card(tmp_path):
    """8 MiB: data, then 6 MiB of zeros (the card's free space), then data."""
    src = tmp_path / "card.raw"
    with open(src, "wb") as f:
        f.write(b"HEAD" * (MB // 4))
        f.write(bytes(6 * MB))
        f.write(b"TAIL" * (MB // 4))
    return src


def _build(tmp_path, monkeypatch, src, lines):
    out = tmp_path / "out.raw"
    monkeypatch.setattr(engine, "_linux_partitions", lambda p: [])
    # one patch lands in the free space: a write into a hole must read back
    patch_at = 3 * MB + 17
    monkeypatch.setattr(engine, "_compute_patches",
                        lambda *a, **k: ({patch_at: b"PATCHED!"}, (1, 0, 0, 0),
                                         None, None, None))

    def fake_apply(out_f, writes):
        for off, b in writes.items():
            out_f.seek(off)
            out_f.write(b)
    monkeypatch.setattr(engine, "_apply_writes", fake_apply)
    engine.write_image(str(src), str(tmp_path), str(out),
                       log=lambda m, l="info": lines.append((m, l)))
    want = bytearray(src.read_bytes())
    want[patch_at:patch_at + 8] = b"PATCHED!"
    return out, bytes(want)


def test_the_build_copy_is_sparse_and_reads_back_the_same(tmp_path, monkeypatch):
    src = _card(tmp_path)
    called = []
    real = sparse_card.sparse_copy
    monkeypatch.setattr(sparse_card, "sparse_copy",
                        lambda s, d, **k: (called.append(d), real(s, d, **k)))
    lines = []
    out, want = _build(tmp_path, monkeypatch, src, lines)
    assert called, "the build's card copy did not go through sparse_copy"
    assert out.read_bytes() == want
    if sys.platform == "win32":
        # NTFS keeps the free space as holes: well under the 8 MiB
        assert sparse_card.on_disk_size(str(out)) < 4 * MB
        assert any("The card copy takes" in m and "on disk of its" in m
                   for m, _l in lines)


def test_a_drive_without_sparse_files_gets_a_whole_copy(tmp_path, monkeypatch):
    src = _card(tmp_path)
    monkeypatch.setattr(rd, "sparse_truncate", lambda f, size: False)
    lines = []
    out, want = _build(tmp_path, monkeypatch, src, lines)
    assert os.path.getsize(out) == len(want)
    assert out.read_bytes() == want
    # a full-size copy says nothing about holes
    assert not any("The card copy takes" in m for m, _l in lines)


def test_trailing_zeros_keep_the_card_size(tmp_path, monkeypatch):
    # a card whose last bytes are zeros is still its whole size
    src = tmp_path / "card.raw"
    src.write_bytes(b"DATA" * (MB // 4) + bytes(3 * MB))
    out, want = _build(tmp_path, monkeypatch, src, [])
    assert os.path.getsize(out) == os.path.getsize(src)
    assert out.read_bytes() == want


def test_the_engine_no_longer_copies_the_card_with_copyfile():
    import inspect
    src = inspect.getsource(engine.write_image)
    assert "sparse_card.sparse_copy(_lp(original_path), _lp(output_path))" in src
    assert "shutil.copyfile(_lp(original_path), _lp(output_path))" not in src
