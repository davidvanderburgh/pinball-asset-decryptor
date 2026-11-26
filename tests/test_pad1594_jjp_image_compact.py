"""PAD-1594: a JJP extract's raw image lands compact in the output folder.

partclone restores only the used blocks, so the image in WSL is sparse; the
rsync that moves it onto the Windows drive (PAD-1592) wrote every zero, and
a ~34 GB card sat at full size.  The move now compacts the copy in place (core.sparse_card.compact_file): same bytes,
same modified time, only its used blocks on disk.
"""
import hashlib
import os
import shutil

import pytest

from pinball_decryptor.core import sparse_card
from pinball_decryptor.plugins.jjp import pipeline as P

MIB = 1024 * 1024


def _dense_card(path):
    """A 16 MiB 'card' with data in two places and zeros elsewhere,
    written in full so every block is allocated (what rsync leaves)."""
    with open(path, "wb") as f:
        f.write(b"\x00" * (16 * MIB))
        f.seek(0)
        f.write(b"\xa5" * 4096)                 # superblock-ish start
        f.seek(9 * MIB)
        f.write(os.urandom(MIB))                # a used region mid-card
    os.utime(path, (1_700_000_000, 1_700_000_000))


def _sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


class _Exec:
    """rsync copies src to the host path in full; stat reports both sizes."""

    def __init__(self, src, host):
        self.src, self.host = src, host
        self.cmds = []

    def stream(self, cmd, timeout=None):
        self.cmds.append(cmd)
        shutil.copyfile(self.src, self.host)
        shutil.copystat(self.src, self.host)
        yield " 16,777,216 100%  1.00MB/s    0:00:01 (xfr#1, to-chk=0/1)"

    def run(self, cmd, timeout=None):
        self.cmds.append(cmd)
        if cmd.startswith("stat -c%s"):
            n = str(os.path.getsize(self.host))
            return f"{n}\n{n}\n"
        if cmd.startswith("rm -f"):
            os.remove(self.src)
        return ""


def _pipe(ex):
    pipe = object.__new__(P.DecryptionPipeline)
    pipe.executor = ex
    pipe.logs = []
    pipe.log = lambda msg, level="info": pipe.logs.append((level, msg))
    pipe.progress = []
    pipe.on_progress = lambda *a, **k: pipe.progress.append(a)
    pipe.cancelled = False
    return pipe


@pytest.fixture
def moved(tmp_path):
    src = tmp_path / "wsl" / "jjp_raw_WizardOfOz-v08.02.img"
    src.parent.mkdir()
    _dense_card(str(src))
    host = tmp_path / "out" / src.name
    host.parent.mkdir()
    return str(src), str(host)


def test_moved_image_is_compact_same_bytes_same_mtime(moved):
    src, host = moved
    want = _sha(src)
    ex = _Exec(src, host)
    pipe = _pipe(ex)

    assert pipe._move_image(src, "/mnt/c/out/x.img", host)

    rsync = next(c for c in ex.cmds if c.startswith("rsync"))
    assert "--chmod=F644" in rsync
    assert "--sparse" not in rsync      # 7-9x slower onto /mnt/c
    assert not os.path.exists(src), "the WSL source must go"
    assert _sha(host) == want
    assert int(os.path.getmtime(host)) == 1_700_000_000
    on_disk = sparse_card.on_disk_size(host)
    if sparse_card.takes_less(host):
        # ~1 MiB + 4 KiB of data; NTFS/ext4 round up to their clusters
        assert on_disk <= 3 * MIB, on_disk
        assert any("Game image takes" in m for _, m in pipe.logs)
    else:   # a filesystem with no holes: kept whole, one note, still moved
        assert any("stays at full size" in m for _, m in pipe.logs)


def test_cancel_while_compacting_keeps_the_image_whole(moved, monkeypatch):
    src, host = moved
    want = _sha(src)
    pipe = _pipe(_Exec(src, host))
    calls = []

    def cancel():
        calls.append(1)
        if len(calls) > 1:      # the move's own progress line passes
            raise P.PipelineError("Canceled", "Operation canceled by user.")
    pipe._check_cancel = cancel

    assert pipe._move_image(src, "/mnt/c/out/x.img", host)
    assert _sha(host) == want
    assert int(os.path.getmtime(host)) == 1_700_000_000
    assert not sparse_card.takes_less(host)
    assert any("Compacting canceled" in m for _, m in pipe.logs)


def test_already_compact_image_is_not_read_again(moved, monkeypatch):
    src, host = moved
    pipe = _pipe(_Exec(src, host))
    monkeypatch.setattr(sparse_card, "takes_less", lambda p, *a, **k: True)
    monkeypatch.setattr(sparse_card, "compact_file",
                        lambda *a, **k: pytest.fail("compacted twice"))
    assert pipe._move_image(src, "/mnt/c/out/x.img", host)


def test_compact_error_is_a_note_not_a_failed_move(moved, monkeypatch):
    src, host = moved
    pipe = _pipe(_Exec(src, host))

    def boom(*a, **k):
        raise PermissionError("in use")
    monkeypatch.setattr(sparse_card, "compact_file", boom)
    assert pipe._move_image(src, "/mnt/c/out/x.img", host)
    assert any("stays at full size (in use)" in m for _, m in pipe.logs)


def test_cleanup_and_mod_fallbacks_pass_the_host_path():
    import inspect
    srcs = inspect.getsource(P)
    calls = [ln.strip() for ln in srcs.splitlines()
             if "self._move_image(" in ln and "def " not in ln]
    assert len(calls) == 3, calls
    assert all("win_path)" in c for c in calls), calls


def test_read_only_copy_is_still_compacted(moved):
    """partclone leaves the image 0400; a copy that kept it is read-only
    on Windows and could not be opened to punch its holes."""
    src, host = moved
    want = _sha(src)
    ex = _Exec(src, host)
    real = ex.stream

    def stream(cmd, timeout=None):
        yield from real(cmd, timeout)
        os.chmod(host, 0o444)
    ex.stream = stream
    pipe = _pipe(ex)
    assert pipe._move_image(src, "/mnt/c/out/x.img", host)
    assert os.access(host, os.W_OK)
    assert _sha(host) == want
    assert not any("stays at full size" in m for _, m in pipe.logs), pipe.logs
