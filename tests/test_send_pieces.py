"""PAD-1435: Send to machine builds changed files from 64 KB pieces the machine already has anywhere among the
files it rewrites (send_pieces.plan + remote_send.pieces_prepare/pieces_run), the machine's helper doing the
hashing and copying (resources/pieces/padpieces)."""
import hashlib
import os
import random
import shutil
import subprocess
import sys
import tempfile

import pytest

from pinball_decryptor.core import remote_send as R
from pinball_decryptor.core import send_pieces as SP
from tests.test_remote_send import (FakeMachine, FakeTarget, FullMachine, NEW_ROOT, NEW_VERSION, SSH_ROOT,
                                    STOCK_GAMES, _counting, as_machine, make_plan)

P = 64                                   # the pieces' size in these tests


@pytest.fixture(autouse=True)
def small_pieces(monkeypatch):
    monkeypatch.setattr(SP, "PIECE", P)


def rnd(n, seed):
    return random.Random(seed).randbytes(n)


def hashes(data):
    return len(data), [hashlib.sha1(data[i:i + P]).hexdigest() for i in range(0, len(data), P)]


def pieces(data):
    return [(hashlib.sha1(data[i:i + P]).hexdigest(), len(data[i:i + P])) for i in range(0, len(data), P)]


def run(old, new):
    """Plan *new* ({path: bytes}) over the machine's *old* files changed in place, do it as the machine would (the
    copies in order on the files as they are, then the sends, then each file cut to size) and check the result."""
    index = {p: hashes(d) for p, d in old.items() if p in new}
    plan = SP.plan(index, [(p, pieces(d)) for p, d in new.items()])
    files = SP.apply(old, plan)
    for path, ranges in plan.sends.items():
        f = files.setdefault(path, bytearray())
        for off, n in ranges:
            if len(f) < off + n:
                f.extend(bytes(off + n - len(f)))
            f[off:off + n] = new[path][off:off + n]
    for path, data in new.items():
        assert bytes(files[path][:len(data)]) == data, path
    assert plan.kept + plan.copied + plan.sent == sum(len(d) for d in new.values())
    return plan


# ------------------------------------------------------------------ the plan
def test_pieces_moved_within_a_file_and_between_files_are_copied_not_sent():
    a, b, c = rnd(P * 20, 1), rnd(P * 12, 2), rnd(P * 8, 3)
    old = {"/games/x.asset": a, "/games/y.asset": b}
    new = {"/games/x.asset": rnd(P * 3, 4) + a[:P * 15] + b[P * 2:P * 6],     # shifted by 3 pieces, plus y's
           "/games/y.asset": b[:P * 4] + c,                                    # kept, then new
           "/games/z.asset": a[P * 10:P * 18] + rnd(100, 5)}                   # a new file from x's old pieces
    plan = run(old, new)
    assert plan.kept == P * 4
    assert plan.copied == P * (15 + 4 + 8)
    assert plan.sent == P * 3 + P * 8 + 100


def test_two_files_that_swap_their_pieces_still_come_out_right():
    a, b = rnd(P * 6, 6), rnd(P * 6, 7)
    plan = run({"/games/a": a, "/games/b": b}, {"/games/a": b, "/games/b": a})
    assert plan.broken >= 1                  # the cycle: one side is sent, the other copied first
    assert plan.copied >= P * 6


def test_a_file_shifted_along_itself_is_copied_from_the_end_back():
    a = rnd(P * 30, 8)
    plan = run({"/games/v": a}, {"/games/v": rnd(P, 9) + a})
    assert plan.copied == P * 30 and plan.sent == P
    assert plan.broken == 0


def test_a_shorter_file_and_a_short_last_piece():
    a = rnd(P * 10 + 17, 10)
    run({"/games/s": a}, {"/games/s": a[P * 2:P * 7] + a[-17:]})
    run({"/games/s": a}, {"/games/s": a + a[:P * 3 + 5]})


def test_random_rewrites_of_several_files_always_come_out_right():
    rng = random.Random(11)
    for trial in range(40):
        old = {"/games/f%d" % i: rng.randbytes(P * rng.randint(1, 12) + rng.randint(0, P - 1)) for i in range(4)}
        pool = b"".join(old.values())
        new = {}
        for i in range(5):
            parts = []
            for _ in range(rng.randint(1, 6)):
                if rng.random() < 0.6:
                    k = rng.randrange(0, max(1, len(pool) // P)) * P
                    parts.append(pool[k:k + P * rng.randint(1, 4)])
                else:
                    parts.append(rng.randbytes(P * rng.randint(1, 3)))
            new["/games/f%d" % i] = b"".join(parts)
        run(old, new)


# ------------------------------------------------------------------ the Send
class PieceMachine(FullMachine):
    """A FullMachine with the piece helper: its copies are done twice, as after a connection dropped mid-batch."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.copied, self.batches = 0, 0

    def pieces_ready(self):
        return True

    def piece_hashes(self, paths):
        return {p: hashes(self.fs[p][1]) for p in paths if p in self.fs and self.fs[p][0] == "file"}

    def copy_pieces(self, copies):
        self.batches += 1
        for _again in range(2):
            fs = dict(self.fs)
            for s, so, d, do, n in copies:
                self._w(d)
                data = fs[s][1][so:so + n]
                assert len(data) == n
                cur = fs.get(d, ("file", b"", 0o644))
                buf = bytearray(cur[1])
                if len(buf) < do + n:
                    buf.extend(bytes(do + n - len(buf)))
                buf[do:do + n] = data
                fs[d] = ("file", bytes(buf), cur[2])
            self.fs = fs
        self.copied += sum(c[4] for c in copies)
        return sum(c[4] for c in copies)

    def write_ranges(self, path, ranges):
        data = self.fs[path][1]
        end = max(o + len(b) for o, b in ranges)
        if len(data) < end:
            self.fs[path] = ("file", data + bytes(end - len(data)), self.fs[path][2])
        super().write_ranges(path, ranges)


def _network(uploads, written, m):
    return sum(len(m.fs[p.replace("/." , "/").replace(R.TMP_TAG, "")][1]) for p in uploads) + sum(n for _p, n in
                                                                                                  written)


def test_full_send_builds_changed_game_files_from_pieces_the_machine_has():
    big = rnd(P * 40, 12)
    games = dict(STOCK_GAMES, **{"kingkong/scene.asset": ("file", big, {"block": 500})})
    new = dict(NEW_VERSION, **{
        "kingkong/scene.asset": ("file", rnd(P * 2, 13) + big[:P * 30], {"block": 500}),   # shifted along
        "kingkong/extra.asset": ("file", big[P * 30:] + rnd(10, 14), {"block": 600}),       # its old tail, moved
    })
    m = PieceMachine(games=games, root=SSH_ROOT)
    uploads, written = _counting(m)
    said = []
    R.sync(FakeTarget(new, NEW_ROOT), m, log=lambda t, l="info": said.append(t))
    assert m.view(R.GAMES) == as_machine(new)
    assert m.copied >= P * 40                       # the scene's 30 pieces and extra's 10 came from the machine
    net = _network(uploads, written, m)
    m2 = FullMachine(games=games, root=SSH_ROOT)    # no helper: the 1 MiB delta, as before
    u2, w2 = _counting(m2)
    R.sync(FakeTarget(new, NEW_ROOT), m2)
    assert m2.view(R.GAMES) == m.view(R.GAMES)
    assert net + P * 40 <= _network(u2, w2, m2)
    assert any("elsewhere on its card, copied there" in t for t in said)
    assert not any(p.endswith(R.TMP_TAG) for p in m.fs)


def test_full_send_without_room_for_new_files_beside_builds_them_in_place():
    big = rnd(P * 40, 15)
    games = dict(STOCK_GAMES, **{"kingkong/scene.asset": ("file", big, {"block": 500})})
    new = dict(NEW_VERSION, **{"kingkong/scene.asset": ("file", big[P * 5:], {"block": 500}),
                               "kingkong/extra.asset": ("file", big[:P * 5], {"block": 600})})
    used = sum(len(e[1]) for p, e in PieceMachine(games=games).fs.items()
               if e[0] == "file" and p.startswith("/games/"))
    m = PieceMachine(games=games, root=SSH_ROOT, free=used + R.SPARE + 300)
    R.sync(FakeTarget(new, NEW_ROOT), m)
    assert m.view(R.GAMES) == as_machine(new)
    assert m.copied >= P * 40


def test_quick_send_short_of_room_builds_the_in_place_files_from_pieces(monkeypatch):
    big = rnd(P * 40, 16)
    src = dict(STOCK_GAMES, **{"kingkong/scene.asset": ("file", big, {"block": 500})})
    out = dict(src, **{"kingkong/scene.asset": ("file", rnd(P, 17) + big[:P * 39], {"block": 500, "mtime": 9})})
    used = sum(len(e[1]) for p, e in PieceMachine(games=src).fs.items()
               if e[0] == "file" and p.startswith("/games/"))
    m = PieceMachine(games=src, free=used + R.SPARE + 10)
    R.send(make_plan(src, out, {"/games/kingkong/scene.asset": [(0, P * 40)]}), m)
    assert m.view(R.GAMES) == as_machine(out)
    assert m.copied == P * 39
    assert m.events[-1] == ("reboot",)


def test_a_machine_without_the_helper_sends_as_before():
    m = FullMachine(root=SSH_ROOT)
    R.sync(FakeTarget(NEW_VERSION, NEW_ROOT), m)
    assert m.view(R.GAMES) == as_machine(NEW_VERSION)


def test_a_dropped_connection_never_redoes_a_copy_batch_that_overwrote_what_it_read(monkeypatch):
    """Each batch is done twice by PieceMachine: a file shifted along itself, in batches of one piece's room, still
    comes out right (a batch is cut wherever a copy would overwrite a piece the batch read)."""
    monkeypatch.setattr(R, "PIECES_BATCH", P * 8)
    a = rnd(P * 60, 18)
    games = dict(STOCK_GAMES, **{"kingkong/v.asset": ("file", a, {"block": 500})})
    new = dict(NEW_VERSION, **{"kingkong/v.asset": ("file", rnd(P * 3, 19) + a[:P * 50] + a[P * 20:P * 30],
                                                    {"block": 500})})
    m = PieceMachine(games=games, root=SSH_ROOT)
    R.sync(FakeTarget(new, NEW_ROOT), m)
    assert m.view(R.GAMES) == as_machine(new)
    assert m.batches > 1


# ------------------------------------------------------------------ the machine's side
def test_the_shipped_helpers_are_the_pinned_ones():
    for sub, want in R.PIECES_SHA256.items():
        data = (R.PIECES_DIR / sub / "padpieces").read_bytes()
        assert data[:4] == b"\x7fELF"
        assert hashlib.sha256(data).hexdigest() == want, sub
        assert int.from_bytes(data[18:20], "little") == {"armv7": 0x28, "aarch64": 0xB7}[sub]


def test_ssh_piece_hashes_reads_the_helpers_answer():
    class Stub(R.SshMachine):
        def __init__(self):
            self._pieces = "/run/pad-pieces-1"

        def sh(self, script, stdin=b"", timeout=600, check=True):
            self.asked = (script, stdin)
            return 0, ("= 130 /games/a b\n" + "a" * 40 + "\n" + "b" * 40 + "\n" + "c" * 40 + "\n! /games/gone\n"
                       "= 0 /games/empty\n")
    m = Stub()
    got = m.piece_hashes(["/games/a b", "/games/gone", "/games/empty"])
    assert got["/games/a b"] == (130, ["a" * 40, "b" * 40, "c" * 40])
    assert "/games/gone" not in got
    assert got["/games/empty"] == (0, [])
    assert m.asked == ("/run/pad-pieces-1 hash %d" % P, b"/games/a b\n/games/gone\n/games/empty\n")


QEMU = {"armv7": "qemu-arm-static", "aarch64": "qemu-aarch64-static"}


@pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("qemu-arm-static"),
                    reason="runs the machine's helper under qemu (Linux with qemu-user-static)")
@pytest.mark.parametrize("sub", ["armv7", "aarch64"])
def test_the_helper_hashes_and_copies_as_python_does(sub):
    if not shutil.which(QEMU[sub]):
        pytest.skip(QEMU[sub])
    exe = [QEMU[sub], str(R.PIECES_DIR / sub / "padpieces")]
    with tempfile.TemporaryDirectory() as d:
        a, b = os.path.join(d, "a"), os.path.join(d, "b c")
        da, db = rnd(200003, 20), rnd(70000, 21)
        open(a, "wb").write(da)
        open(b, "wb").write(db)
        out = subprocess.run(exe + ["hash", "65536"], input=("%s\n%s\n%s/none\n" % (a, b, d)).encode(),
                             capture_output=True, check=True).stdout.decode()
        want = []
        for p, data in ((a, da), (b, db)):
            want.append("= %d %s" % (len(data), p))
            want += [hashlib.sha1(data[i:i + 65536]).hexdigest() for i in range(0, len(data), 65536)]
        want.append("! %s/none" % d)
        assert out.splitlines() == want
        n = os.path.join(d, "new")
        out = subprocess.run(exe + ["copy"], input=("%s\t65536\t%s\t131072\t70000\n%s\t0\t%s\t0\t1000\n"
                                                    % (a, n, b, n)).encode(),
                             capture_output=True, check=True).stdout.decode()
        assert out.strip() == "ok 71000"
        got = open(n, "rb").read()
        assert got[:1000] == db[:1000] and got[131072:] == da[65536:65536 + 70000]
