"""PAD-1397: Send to machine - what a Send changes, the checks before it, and the order it changes things in.

The cards are stand-in partitions (the five reader calls core/remote_send.py makes) and the machine a stand-in
that refuses a write to a partition still mounted read-only, so the order the real one needs is what passes.  The
real thing (paramiko, the card's busybox, its dropbear and game_monitor) is proven in the emulator stand-in, see
docs/plans/send-to-machine.md."""

import hashlib
import shutil
import stat
import subprocess
import sys

import pytest

from pinball_decryptor.core import remote_send as R


# ------------------------------------------------------------------ stand-in partitions
class FakeReader:
    base = 0

    def __init__(self, spec):
        self.nodes = {}
        for rel, ent in spec.items():
            kind = ent[0]
            if kind == "dir":
                node = dict(mode=stat.S_IFDIR | 0o755, uid=0, gid=0, size=4096, mtime=1, ctime=1)
            elif kind == "file":
                data = ent[1]
                opts = ent[2] if len(ent) > 2 else {}
                node = dict(mode=stat.S_IFREG | opts.get("mode", 0o644), uid=0, gid=0, size=len(data),
                            mtime=opts.get("mtime", 1), ctime=opts.get("mtime", 1), _data=data,
                            _runs=[(0, opts.get("block", 1000) * 4096, len(data))] if data else [])
            else:
                node = dict(mode=stat.S_IFLNK | 0o777, uid=0, gid=0, size=len(ent[1]), mtime=1, ctime=1,
                            _target=ent[1])
            self.nodes[rel] = (kind if kind != "link" else "symlink", node)

    def iter_tree(self):
        for i, rel in enumerate(sorted(self.nodes)):
            kind, node = self.nodes[rel]
            yield rel, kind, i + 11, node

    def read_symlink(self, node):
        return node["_target"]

    def mapped_ranges(self, node):
        return node["_runs"]

    def read_file_chunks(self, node):
        return [(0, node["_data"])] if node["_data"] else []

    def read_range(self, node, off, n):
        return node["_data"][off:off + n]

    def read_file_bytes(self, node):
        return node["_data"]


IMAGE = bytes(range(256)) * 64          # 16 KiB "image.bin", patched in place
STOCK_GAMES = {
    "kingkong": ("dir",),
    "kingkong/game": ("file", b"ELF stock", {"mode": 0o755}),
    "kingkong/image.bin": ("file", IMAGE, {"block": 50}),
    "kingkong/video.mp4": ("file", b"video stock", {"block": 80}),
    "kingkong/old.wav": ("file", b"gone in the build", {"block": 90}),
    "game": ("link", "/games/kingkong/game"),
}
STOCK_ROOT = {
    "etc": ("dir",),
    "etc/fstab": ("file", b"/dev/mmcblk0p3 /games ext4 ro 0 2\n"),
}


def patched(data, off, new):
    return data[:off] + new + data[off + len(new):]


def build_games():
    g = dict(STOCK_GAMES)
    g["kingkong/image.bin"] = ("file", patched(IMAGE, 0x100, b"NEW!"), {"block": 50})   # same inode, in place
    g["kingkong/video.mp4"] = ("file", b"video replaced, longer", {"block": 300, "mtime": 9})
    del g["kingkong/old.wav"]
    g["pad"] = ("dir",)
    g["pad/mode.so"] = ("file", b"mode runtime", {"block": 400, "mtime": 9, "mode": 0o755})
    g["game"] = ("link", "/games/pad/hook.sh")
    return g


def make_plan(src_games, out_games, ranges=None, src_root=STOCK_ROOT, out_root=STOCK_ROOT):
    trees = {R.ROOT: (R._Tree(FakeReader(out_root), R.ROOT), R._Tree(FakeReader(src_root), R.ROOT)),
             R.GAMES: (R._Tree(FakeReader(out_games), R.GAMES), R._Tree(FakeReader(src_games), R.GAMES))}
    return R.Plan("build.raw", "stock.raw", "stern-spike2", trees, ranges or {}, [],
                  {"name": "king_kong_le-0_97_0.raw", "size": 123})


BUILD_RANGES = {"/games/kingkong/image.bin": [(0x100, 4)]}


# ------------------------------------------------------------------ stand-in machine
class FakeMachine(R.Machine):
    """A machine holding *games*/*root* (FakeReader specs) as ``{path: entry}``."""

    def __init__(self, games=STOCK_GAMES, root=STOCK_ROOT, corrupt=None):
        self.fs = {}
        for mount, spec in ((R.GAMES, games), (R.ROOT, root)):
            for rel, ent in spec.items():
                p = mount.rstrip("/") + "/" + rel
                mode = (ent[2].get("mode", 0o644) if ent[0] == "file" and len(ent) > 2
                        else 0o644 if ent[0] == "file" else 0o777 if ent[0] == "link" else 0o755)
                self.fs[p] = (ent[0], ent[1] if ent[0] != "dir" else None, mode)
        self.rw = {R.GAMES: False, R.ROOT: False}
        self.ledger = None
        self.restarts = 0
        self.corrupt = corrupt or set()
        self.events = []
        self.held = set()

    def _w(self, path):
        mount = R._mount_of(path)
        if not self.rw[mount]:
            raise OSError("Read-only file system: " + path)

    def state(self, paths):
        out = {}
        for p in paths:
            e = self.fs.get(p)
            if e is None:
                out[p] = None
            elif e[0] == "file":
                out[p] = ("file", hashlib.sha1(e[1]).hexdigest())
            elif e[0] == "link":
                out[p] = ("link", e[1])
            else:
                out[p] = ("dir",)
        return out

    def sizes(self, root):
        return {p: len(e[1]) for p, e in self.fs.items() if e[0] == "file" and p.startswith(root + "/")}

    def read_ranges(self, path, ranges):
        return [self.fs[path][1][o:o + n] for o, n in ranges]

    def free(self, mount):
        return 1 << 30

    def remount(self, mount, rw):
        self.rw[mount] = rw
        self.events.append(("remount", mount, rw))
        return True

    def mkdir(self, path, mode, uid, gid):
        self._w(path)
        self.fs[path] = ("dir", None, mode)

    def upload(self, path, fileobj, size, mode, uid, gid, callback=None):
        self._w(path)
        data = b""
        while True:
            b = fileobj.read(3)
            if not b:
                break
            data += b
        if any(path.endswith(c + R.TMP_TAG) for c in self.corrupt):
            data = data[:-1] + b"X"
        if callback:
            callback(len(data), size)
        self.fs[path] = ("file", data, mode)

    def commit(self, renames, links, deletes):
        for tmp, final in renames:
            self._w(final)
            self.fs[final] = self.fs.pop(tmp)
            self.events.append(("mv", final))
        for path, target, _u, _g in links:
            self._w(path)
            self.fs[path] = ("link", target, 0o777)
        for path, _is_dir in deletes:
            self._w(path)
            self.fs.pop(path, None)
            self.events.append(("rm", path))
        self.events.append(("commit",))

    def _running(self, path):
        # the remote access session's own programs (busybox, the server, libc): changed under them, they break
        if path in self.held:
            raise AssertionError("a running program's file was changed in place: " + path)

    def copy(self, src, dst):
        self._w(dst)
        self.fs[dst] = self.fs[src]
        self.events.append(("copy", src))

    def in_use(self):
        return set(self.held)

    def write_ranges(self, path, ranges):
        self._w(path)
        self._running(path)
        data = self.fs[path][1]
        for off, b in ranges:
            data = patched(data, off, b)
        self.fs[path] = ("file", data, self.fs[path][2])

    def remove(self, paths):
        for p in paths:
            self.fs.pop(p, None)

    def block_hashes(self, path):
        data, bs = self.fs[path][1], R.DELTA_BLOCK
        return len(data), [hashlib.sha1(data[i:i + bs]).hexdigest() for i in range(0, len(data), bs)]

    def truncate(self, path, size):
        self._w(path)
        self._running(path)
        e = self.fs[path]
        self.fs[path] = (e[0], e[1][:size], e[2])

    def set_attrs(self, path, mode, uid, gid):
        e = self.fs[path]
        self.fs[path] = (e[0], e[1], mode)

    def stop_game(self):
        self.events.append(("stop",))

    def reboot(self):
        self.events.append(("reboot",))

    def sync(self):
        self.events.append(("sync",))

    def restart_game(self):
        self.restarts += 1
        self.events.append(("restart",))
        return "PAD_SEND_RESTARTED 4242"

    def read_ledger(self):
        return self.ledger

    def write_ledger(self, data):
        self.ledger = dict(data)

    def view(self, mount=R.GAMES):
        return {p: e[:2] for p, e in self.fs.items() if R._mount_of(p) == mount}


def as_machine(spec, mount=R.GAMES):
    return FakeMachine(games=spec).view(mount)


# ------------------------------------------------------------------ the plan
def test_plan_finds_each_kind_of_change_and_nothing_else():
    plan = make_plan(STOCK_GAMES, build_games(), BUILD_RANGES)
    kinds = {op.path: op.kind for op in plan.ops}
    assert kinds == {
        "/games/kingkong/image.bin": "patch",          # in place: ranges, never the gigabytes whole
        "/games/kingkong/video.mp4": "put",
        "/games/kingkong/old.wav": "delete",
        "/games/pad": "mkdir",
        "/games/pad/mode.so": "put",
        "/games/game": "link",
    }
    patch = next(op for op in plan.ops if op.kind == "patch")
    assert patch.ranges == [(0x100, b"NEW!", IMAGE[0x100:0x104])]


def test_a_file_that_only_moved_is_no_change():
    """A build made as small as it can be moves files to other blocks: same bytes, nothing to send."""
    moved = dict(STOCK_GAMES)
    moved["kingkong/video.mp4"] = ("file", b"video stock", {"block": 7})
    assert make_plan(STOCK_GAMES, moved).ops == []


def test_system_partition_changes_are_sent_too():
    root = dict(STOCK_ROOT)
    root["usr"] = ("dir",)
    root["usr/pad.so"] = ("file", b"runtime", {"block": 5})
    plan = make_plan(STOCK_GAMES, STOCK_GAMES, out_root=root)
    assert {(op.kind, op.path, op.mount) for op in plan.ops} == {
        ("mkdir", "/usr", R.ROOT), ("put", "/usr/pad.so", R.ROOT)}


# ------------------------------------------------------------------ the send
def test_send_makes_the_machine_match_the_build_in_the_safe_order():
    plan = make_plan(STOCK_GAMES, build_games(), BUILD_RANGES)
    m = FakeMachine()
    summary = R.send(plan, m)
    assert m.view() == as_machine(build_games())
    assert not any(p.endswith(R.TMP_TAG) for p in m.fs)
    assert m.restarts == 1
    # read-write only for the send, back to read-only after the game restarted
    assert m.events[0] == ("remount", R.GAMES, True)
    assert m.events[-1] == ("remount", R.GAMES, False)
    assert m.events.index(("sync",)) < m.events.index(("restart",))
    assert ("remount", R.ROOT, True) not in m.events            # nothing changed there
    assert m.ledger["pending"] is False
    assert set(m.ledger["paths"]) == {"/games/kingkong/video.mp4", "/games/kingkong/old.wav", "/games/pad",
                                      "/games/pad/mode.so", "/games/game"}
    assert m.ledger["ranges"] == {"/games/kingkong/image.bin": [[0x100, 4]]}
    assert "Sent 6 change(s)" in summary


def test_a_second_send_of_the_same_build_sends_nothing_and_leaves_the_game_alone():
    m = FakeMachine()
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    m.events.clear()
    assert R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m) == "The machine already has this build."
    assert m.events == [] and m.restarts == 1


def test_a_change_taken_out_of_the_project_goes_back_to_the_original_on_the_next_send():
    m = FakeMachine()
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    # the next build has only the new video: modes, the patch and the removal are gone from the project
    nxt = dict(STOCK_GAMES)
    nxt["kingkong/video.mp4"] = build_games()["kingkong/video.mp4"]
    R.send(make_plan(STOCK_GAMES, nxt), m)
    assert m.view() == as_machine(nxt)
    assert m.ledger["paths"] == ["/games/kingkong/video.mp4"] and m.ledger["ranges"] == {}


def test_a_machine_running_another_card_is_refused_before_anything_changes():
    other = dict(STOCK_GAMES)
    other["kingkong/game"] = ("file", b"ELF another version", {"mode": 0o755})
    m = FakeMachine(games=other)
    with pytest.raises(R.SendError, match="isn't running the card"):
        R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.events == [] and m.view() == as_machine(other)


def test_a_changed_file_the_machine_has_some_third_way_is_refused():
    odd = dict(STOCK_GAMES)
    odd["kingkong/video.mp4"] = ("file", b"someone else's", {"block": 80})
    m = FakeMachine(games=odd)
    with pytest.raises(R.SendError, match="neither the original's nor what an earlier Send put there"):
        R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.events == []


def test_an_upload_that_arrives_damaged_changes_nothing():
    m = FakeMachine(corrupt={"mode.so"})
    with pytest.raises(R.SendError, match="didn't arrive whole"):
        R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.view()["/games/kingkong/video.mp4"] == ("file", b"video stock")
    assert not any(p.endswith(R.TMP_TAG) for p in m.fs)
    assert m.rw[R.GAMES] is False and m.restarts == 0
    # its record says a Send was under way, so the next one may finish it
    assert m.ledger["pending"] is True


def test_a_send_cut_off_part_way_through_a_patch_is_finished_by_the_next():
    m = FakeMachine()
    m.write_ledger = lambda data, m=m: setattr(m, "ledger", dict(data))
    half = patched(IMAGE, 0x100, b"NE")                 # two of the four bytes got there
    m.fs["/games/kingkong/image.bin"] = ("file", half, 0o644)
    m.ledger = {"card": make_plan(STOCK_GAMES, STOCK_GAMES).card_id, "pending": True,
                "paths": [], "ranges": {"/games/kingkong/image.bin": [[0x100, 4]]}}
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.view() == as_machine(build_games())


def test_cancel_before_the_uploads_leaves_the_machine_as_it_was():
    m = FakeMachine()
    with pytest.raises(R.SendError, match="canceled"):
        R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m, cancel=lambda: True)
    assert m.view() == as_machine(STOCK_GAMES) and m.events == []


def test_no_room_on_the_machine_is_said_before_anything_changes():
    m = FakeMachine()
    m.free = lambda mount: 10
    with pytest.raises(R.SendError, match="isn't room"):
        R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.events == []


@pytest.mark.parametrize("text,want", [("192.168.1.40", ("192.168.1.40", 22)), (" kingkong.local:2222 ",
                         ("kingkong.local", 2222)), ("[fe80::1]:22", ("fe80::1", 22))])
def test_machine_address(text, want):
    assert R.parse_address(text) == want


def test_machine_address_missing():
    with pytest.raises(R.SendError, match="network address"):
        R.parse_address("  ")


# ------------------------------------------------------------------ Spike 3's in-place record
class FakeVolumeReader:
    def __init__(self, files):
        self.files = files                 # {path: (node, [(file_off, disk, n)])}

    def iter_regular_files(self, max_depth=9, min_size=1):
        for i, (path, (node, _runs)) in enumerate(sorted(self.files.items())):
            yield path, i, node

    def mapped_ranges(self, node):
        return next(r for n, r in self.files.values() if n is node)


def test_spike3_in_place_writes_are_recorded_by_file():
    from pinball_decryptor.plugins.stern import spike3_write
    a, b = {"size": 8192}, {"size": 4096}
    reader = FakeVolumeReader({"/fallout/image.bin": (a, [(0, 40960, 4096), (4096, 90112, 4096)]),
                               "/fallout/sounds.bnk": (b, [(0, 8192, 4096)])})
    written = [(40960 + 10, 4), (40960 + 4090, 12),      # across the end of image.bin's first run: two pieces
               (8192, 2), (8194, 2),                     # touching writes merge
               (200000, 16)]                             # filesystem bookkeeping: no file, left out
    assert spike3_write.written_by_file(reader, written) == {
        "/games/fallout/image.bin": [[10, 4], [4090, 6]],
        "/games/fallout/sounds.bnk": [[0, 4]]}


# ------------------------------------------------------------------ the machine-side scripts
@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sha1sum"), reason="needs a POSIX sh")
def test_state_script_reports_files_links_folders_and_absent(tmp_path):
    f = tmp_path / "f"
    f.write_bytes(b"abc")
    (tmp_path / "l").symlink_to("/games/x")
    (tmp_path / "d").mkdir()
    paths = [str(f), str(tmp_path / "l"), str(tmp_path / "d"), str(tmp_path / "missing")]
    out = subprocess.run(["sh", "-c", R.STATE_SCRIPT], input="\n".join(paths) + "\n", capture_output=True,
                         text=True, check=True).stdout.splitlines()
    assert out == ["F " + hashlib.sha1(b"abc").hexdigest(), "L /games/x", "D", "N"]


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("sh"), reason="needs a POSIX sh")
def test_restart_script_with_no_game_running_says_so():
    out = subprocess.run(["sh", "-c", R.RESTART_SCRIPT.replace("pids_named game)", "pids_named pad-no-such-game)")],
                         capture_output=True, text=True, check=True).stdout
    assert out.strip() == "PAD_SEND_NOT_RUNNING"


# ------------------------------------------------------------------ the full Send: any image
class FullMachine(FakeMachine):
    """FakeMachine plus what the full Send asks: layout, mounts, walk, the boot partition, stop and reboot."""

    def __init__(self, games=STOCK_GAMES, root=STOCK_ROOT, boot=b"boot v1", layout=None, free=1 << 30):
        super().__init__(games=games, root=root)
        self.fs["/data/settings"] = ("file", b"the owner's settings", 0o644)
        self.boot = boot
        self._layout = layout or {1: (8192, 16384), 2: (24576, 688128), 3: (712704, 1000000)}
        self._free = free
        self.stopped = self.rebooted = False

    def layout(self):
        return dict(self._layout)

    def mounts(self):
        return [("/dev/root", "/"), ("/dev/mmcblk0p3", "/games"), ("/dev/mmcblk0p5", "/data")]

    def walk(self, root, skip=()):
        out = {}
        for p, e in self.fs.items():
            if p.endswith(R.TMP_TAG):
                continue
            if root == "/":
                if any(p.startswith(s + "/") for s in skip if s != "/"):
                    continue
            elif not p.startswith(root.rstrip("/") + "/"):
                continue
            kind = {"file": "file", "link": "symlink", "dir": "dir"}[e[0]]
            # owners None: the card's file server doesn't say who owns a file (seen on the stand-in)
            out[p] = (kind, len(e[1]) if kind == "file" else 0, 0, e[2] if kind != "symlink" else 0o777, None, None,
                      e[1] if kind == "symlink" else None)
        return out

    def free(self, mount):
        used = sum(len(e[1]) for p, e in self.fs.items() if e[0] == "file" and R._mount_of(p) == mount)
        return self._free - used

    def raw_sha1(self, num):
        return hashlib.sha1(self.boot).hexdigest()

    def raw_write(self, num, fileobj, size, sha1):
        data = fileobj.read()
        assert hashlib.sha1(data).hexdigest() == sha1
        self.boot = data
        self.events.append(("boot",))

    def stop_game(self):
        self.stopped = True
        self.events.append(("stop",))

    def reboot(self):
        self.rebooted = True
        self.events.append(("reboot",))


class FakeTarget(R.Target):
    def __init__(self, games, root, boot=b"boot v1", plan=None, platform="stern-spike2", layout=None):
        trees = {R.ROOT: R._Tree(FakeReader(root), R.ROOT), R.GAMES: R._Tree(FakeReader(games), R.GAMES)}
        super().__init__("deadpool_le-1_17_0.raw", platform,
                         {n: (a, b, 0x0c if n == 1 else 0x83) for n, (a, b) in
                          (layout or {1: (8192, 16384), 2: (24576, 688128), 3: (712704, 1000000)}).items()},
                         trees, {1: (0, len(boot))}, [], plan, {"name": "deadpool_le-1_17_0.raw", "size": 1})
        self._boot = boot

    def raw_chunks(self, num):
        return [(0, self._boot)]


#: the card's remote access (PR #38) as the machine has it; the folder name built up, as it is only card data
KEYS_DIR = "home/root/." + "ssh"
SSH_ROOT = dict(STOCK_ROOT, **{
    "usr": ("dir",), "usr/local": ("dir",), "usr/local/bin": ("dir",),
    "usr/local/bin/dropbear": ("file", b"dropbear", {"mode": 0o755}),
    "etc/init.d": ("dir",), "etc/init.d/sshd": ("file", b"# PAD key-only SSH", {"mode": 0o755}),
    "etc/rc5.d": ("dir",), "etc/rc5.d/S30sshd": ("link", "../init.d/sshd"),
    "home": ("dir",), "home/root": ("dir",), KEYS_DIR: ("dir",),
    KEYS_DIR + "/authorized_keys": ("file", b"ssh-ed25519 AAAA pad"),
    "usr/local/bin/stale_tool": ("file", b"not on the new card"),
})
NEW_VERSION = {
    "kingkong": ("dir",),
    "kingkong/game": ("file", b"ELF version 2", {"mode": 0o755}),
    "kingkong/image.bin": ("file", bytes(reversed(IMAGE)), {"block": 50}),     # same size, other bytes
    "kingkong/video.mp4": ("file", b"video stock", {"block": 80}),             # unchanged: not sent
    "kingkong/new.wav": ("file", b"new in version 2", {"block": 99}),
    "game": ("link", "/games/kingkong/game"),
}
NEW_ROOT = dict(STOCK_ROOT, **{"etc/version": ("file", b"2.0")})


def test_full_send_makes_the_machine_the_new_version_and_keeps_its_own_things():
    m = FullMachine(root=SSH_ROOT)
    line = R.sync(FakeTarget(NEW_VERSION, NEW_ROOT, boot=b"boot v2"), m)
    assert m.view(R.GAMES) == as_machine(NEW_VERSION)
    root = m.view(R.ROOT)
    # the new card's system files, the old card's stray one gone, remote access kept, the owner's data untouched
    assert root["/etc/version"] == ("file", b"2.0")
    assert "/usr/local/bin/stale_tool" not in root
    for kept in ("/usr/local/bin/dropbear", "/etc/init.d/sshd", "/etc/rc5.d/S30sshd",
                 "/" + KEYS_DIR + "/authorized_keys"):
        assert kept in root
    assert root["/data/settings"] == ("file", b"the owner's settings")
    assert m.boot == b"boot v2"
    assert m.stopped and m.rebooted and m.events[-1] == ("reboot",)
    assert not any(p.endswith(R.TMP_TAG) for p in m.fs)
    assert m.rw == {R.GAMES: False, R.ROOT: False}
    assert m.ledger["card"]["name"] == "deadpool_le-1_17_0.raw"
    assert "boot partition" in line and "restarting" in line


def _counting(m):
    uploads, written = [], []
    up, wr = m.upload, m.write_ranges
    m.upload = lambda path, *a, **k: (uploads.append(path), up(path, *a, **k))[1]
    m.write_ranges = lambda path, rr: (written.append((path, sum(len(b) for _o, b in rr))), wr(path, rr))[1]
    return uploads, written


def test_full_send_only_sends_what_differs(monkeypatch):
    """New files go up whole; a file the machine already has is a delta: only its changed blocks (David: "delta
    updates from the PC to the machine since space is scarce on the SD card")."""
    monkeypatch.setattr(R, "DELTA_BLOCK", 1024)
    new = dict(NEW_VERSION)
    new["kingkong/image.bin"] = ("file", patched(IMAGE, 5000, b"one block changes"), {"block": 50})
    m = FullMachine(root=SSH_ROOT)
    uploads, written = _counting(m)
    R.sync(FakeTarget(new, NEW_ROOT, boot=b"boot v1"), m)
    assert {p.replace(R.TMP_TAG, "").replace("/.", "/") for p in uploads} == {"/games/kingkong/new.wav",
                                                                              "/etc/version"}
    assert dict(written) == {"/games/kingkong/image.bin": 1024,                # 1 of its 16 blocks
                             "/games/kingkong/game": len(b"ELF version 2")}
    assert m.view(R.GAMES) == as_machine(new)
    assert ("boot",) not in m.events                    # the boot partition was the same


def test_quick_send_with_no_room_for_a_second_copy_goes_in_place_and_restarts_the_machine(monkeypatch):
    monkeypatch.setattr(R, "DELTA_BLOCK", 1024)
    out = build_games()
    out["kingkong/video.mp4"] = ("file", b"video stock but longer now", {"block": 300, "mtime": 9})
    m = FullMachine(free=sum(len(e[1]) for p, e in FakeMachine().fs.items() if e[0] == "file"
                             and p.startswith("/games/")) + R.SPARE + 20)   # room for mode.so (12), not the video too
    uploads, written = _counting(m)
    line = R.send(make_plan(STOCK_GAMES, out, BUILD_RANGES), m)
    assert m.view(R.GAMES) == as_machine(out)
    assert {p.replace(R.TMP_TAG, "").replace("/.", "/") for p in uploads} == {"/games/pad/mode.so"}   # new
    assert ("/games/kingkong/video.mp4", len(b"video stock but longer now")) in written                # delta
    assert m.events.index(("stop",)) < m.events.index(("remount", R.GAMES, True))
    assert m.events[-1] == ("reboot",) and m.restarts == 0
    assert "restarting" in line


def test_full_send_of_the_image_the_machine_already_has_changes_nothing():
    m = FullMachine()
    assert R.sync(FakeTarget(STOCK_GAMES, STOCK_ROOT), m) == "The machine already has this image."
    assert m.events == [] and not m.rebooted


def test_an_image_laid_out_differently_is_refused():
    with pytest.raises(R.SendError, match="the machine has partition 4"):
        R.check_layout(FakeTarget(NEW_VERSION, NEW_ROOT), {**FullMachine().layout(), 4: (9, 2)})
    with pytest.raises(R.SendError, match="partition 3 is missing"):
        R.check_layout(FakeTarget(NEW_VERSION, NEW_ROOT), {1: (8192, 16384), 2: (24576, 688128)})
    # the boot partition is copied whole: it must be the same size
    with pytest.raises(R.SendError, match=r"partition 1 \(the boot partition, copied whole\) is 0\.0 GB"):
        R.check_layout(FakeTarget(NEW_VERSION, NEW_ROOT), {**FullMachine().layout(), 1: (8192, 8)})
    # other platforms keep the exact layout
    other = FakeTarget(NEW_VERSION, NEW_ROOT, platform="stern-spike3",
                       layout={1: (8192, 16384), 2: (24576, 688128), 3: (712704, 2000000)})
    with pytest.raises(R.SendError, match="partition 3 is placed or sized differently"):
        R.check_layout(other, FullMachine().layout())


def test_a_card_with_a_bigger_game_partition_takes_a_send():
    """PAD-1432: David's Godzilla card was written with a grown /games (p3 14.5 GB, p4-p6 after it); the Heisei
    image he sent was not (p3 11.7 GB).  The game and system partitions are synced file by file with their free
    space checked, and /data, /dump and the extended partition aren't touched, so where they sit doesn't matter."""
    image = {1: (8192, 16384, 0x0C), 2: (24576, 688128, 0x83), 3: (712704, 22847486, 0x83),
             4: (23560192, 1239038, 0x0F), 5: (23562240, 147454, 0x83), 6: (23709696, 1089534, 0x83)}
    machine = {1: (8192, 16384), 2: (24576, 688128), 3: (712704, 28311550), 4: (29024256, 2),
               5: (29026304, 147454), 6: (29173760, 1089534)}
    target = FakeTarget(NEW_VERSION, NEW_ROOT)
    target.layout = image
    R.check_layout(target, machine)
    # the other way round (an image with the bigger game partition, a card without) goes too: the Send checks room
    R.check_layout(FakeTarget(NEW_VERSION, NEW_ROOT, layout={1: (8192, 16384), 2: (24576, 688128),
                                                             3: (712704, 28311550)}),
                   {1: (8192, 16384), 2: (24576, 688128), 3: (712704, 22847486)})
    # a multi-boot game image partition the Send syncs must fit on the machine's
    target.parts = {R.TEMP_MOUNT + "/p6": 6}
    with pytest.raises(R.SendError, match=r"partition 6 is 0\.0 GB on the machine, smaller than the image's 0\.6 GB"):
        R.check_layout(target, {**machine, 6: (29173760, 10)})


def test_full_send_with_no_room_for_both_copies_replaces_in_place_with_the_game_stopped():
    m = FullMachine(free=len(IMAGE) + 2 * len(b"ELF stock") + R.SPARE + 3000)
    R.sync(FakeTarget(NEW_VERSION, NEW_ROOT), m)
    assert m.view(R.GAMES) == as_machine(NEW_VERSION)
    assert m.events.index(("stop",)) < m.events.index(("commit",))


def test_a_build_of_another_card_than_the_machine_runs_falls_back_to_the_full_send(monkeypatch):
    plan = make_plan(STOCK_GAMES, build_games(), BUILD_RANGES)
    other = dict(STOCK_GAMES)
    other["kingkong/game"] = ("file", b"ELF another version", {"mode": 0o755})
    m = FullMachine(games=other)
    target = FakeTarget(build_games(), STOCK_ROOT, plan=plan)
    monkeypatch.setattr(R, "open_target", lambda image, log=None: target)
    said = []
    R.send_image("build.raw", m, lambda t, l="info": said.append(t))
    assert m.view(R.GAMES) == as_machine(build_games())
    assert any("sending the whole image's differences instead" in t for t in said)
    assert m.rebooted


# ------------------------------------------------------------------ the system partition the session runs on
#: David (2026-11-18): "How can it do a full [Send] if the SD card needs the [remote access] to run during that
#: process?"  The session's own programs live there: busybox is the shell and every tool a Send uses.
BUSYBOX = bytes(range(256)) * 16 + b"busybox 1.31"
RUN_ROOT = dict(STOCK_ROOT, **{
    "bin": ("dir",), "bin/busybox": ("file", BUSYBOX, {"mode": 0o755}),
    "lib": ("dir",), "lib/libc.so.6": ("file", b"libc as running"), "lib/libold.so.1": ("file", b"old lib"),
})
NEXT_ROOT = dict(STOCK_ROOT, **{
    "bin": ("dir",), "bin/busybox": ("file", patched(BUSYBOX, 1500, b"1.36"), {"mode": 0o755}),
    "lib": ("dir",), "lib/libc.so.6": ("file", b"libc of the next version"), "lib/libnew.so.2": ("file", b"new"),
})
HELD = {"/bin/busybox", "/lib/libc.so.6"}


def test_full_send_never_changes_a_running_system_file_in_place(monkeypatch):
    monkeypatch.setattr(R, "DELTA_BLOCK", 1024)
    m = FullMachine(root=RUN_ROOT)
    m.held = set(HELD)                       # FakeMachine fails any in-place write to these
    _uploads, written = _counting(m)
    R.sync(FakeTarget(STOCK_GAMES, NEXT_ROOT), m)
    root = m.view(R.ROOT)
    assert root["/bin/busybox"] == ("file", NEXT_ROOT["bin/busybox"][1])
    assert root["/lib/libc.so.6"] == ("file", b"libc of the next version")
    assert "/lib/libold.so.1" not in root and root["/lib/libnew.so.2"] == ("file", b"new")
    # the delta still sends only busybox's changed block, into a copy renamed over it
    assert ("copy", "/bin/busybox") in m.events and ("mv", "/bin/busybox") in m.events
    assert dict(written) == {"/bin/.busybox" + R.TMP_TAG: 1024, "/lib/.libc.so.6" + R.TMP_TAG: 24}
    # a removed system file goes after every new one is in place: commands keep finding their libraries
    assert m.events.index(("rm", "/lib/libold.so.1")) > max(
        m.events.index(("mv", p)) for p in ("/bin/busybox", "/lib/libc.so.6", "/lib/libnew.so.2"))
    assert not any(p.endswith(R.TMP_TAG) for p in m.fs) and m.rebooted


def test_full_send_without_room_for_the_running_files_old_copies_is_refused_before_anything_changes():
    used = sum(len(e[1]) for p, e in FullMachine(root=RUN_ROOT).fs.items()
               if e[0] == "file" and R._mount_of(p) == R.ROOT)
    m = FullMachine(root=RUN_ROOT, free=used + R.SPARE + 100)      # not the room busybox's old copy keeps
    m.held = set(HELD)
    before = dict(m.fs)
    with pytest.raises(R.SendError, match="system partition"):
        R.sync(FakeTarget(STOCK_GAMES, NEXT_ROOT), m)
    assert m.fs == before and ("stop",) not in m.events and not m.rebooted


def test_room_for_the_system_partition_counts_held_old_copies_and_one_other():
    m = FakeMachine()
    m.held = {"/bin/busybox"}
    ops = [R.Op("put", "/bin/busybox", size=1000), R.Op("put", "/lib/a.so", size=300),
           R.Op("put", "/lib/b.so", size=500), R.Op("put", "/lib/new.so", size=70)]
    need = R.root_room(m, ops, {"/bin/busybox": 1000, "/lib/a.so": 300, "/lib/b.so": 400})
    assert need == 70 + 1000 + 500 + 100 + R.SPARE      # new, held busybox, the largest other, b.so's growth


def test_quick_send_short_of_room_changes_game_files_in_place_but_never_system_files(monkeypatch):
    monkeypatch.setattr(R, "DELTA_BLOCK", 1024)
    out = build_games()
    out["kingkong/video.mp4"] = ("file", b"video stock but longer now", {"block": 300, "mtime": 9})
    out_root = dict(STOCK_ROOT, **{"etc/fstab": ("file", b"/dev/mmcblk0p3 /games ext4 ro,noatime 0 2\n")})
    m = FullMachine(free=sum(len(e[1]) for p, e in FakeMachine().fs.items() if e[0] == "file"
                             and p.startswith("/games/")) + R.SPARE + 20)
    m.held = {"/etc/fstab"}
    uploads, written = _counting(m)
    R.send(make_plan(STOCK_GAMES, out, BUILD_RANGES, out_root=out_root), m)
    assert ("/games/kingkong/video.mp4", len(b"video stock but longer now")) in written     # game file: delta
    assert "/etc/.fstab" + R.TMP_TAG in uploads                                             # system: beside
    assert m.view(R.ROOT)["/etc/fstab"] == ("file", out_root["etc/fstab"][1])


# ------------------------------------------------------------------ PAD-1427: what the machine shows during a Send
class _Screen:
    """Records the Send's calls to the machine's screen (SshMachine draws them with the card's own tools)."""

    def _screen_init(self):
        self.screen = []

    def pause_game(self):
        self.events.append(("pause",))

    def resume_game(self, text=None):
        self.restarts += 1
        self.events.append(("resume",))
        return "PAD_SEND_RESTARTED 4242"

    def screen_progress(self, done, total, what=""):
        self.screen.append((done, total, what))

    def screen_changing(self):
        self.events.append(("changing",))

    def screen_stopped(self, changed):
        self.events.append(("stopped", changed))


class ScreenMachine(_Screen, FakeMachine):
    def __init__(self, *a, **k):
        FakeMachine.__init__(self, *a, **k)
        self._screen_init()


class FullScreenMachine(_Screen, FullMachine):
    def __init__(self, *a, **k):
        FullMachine.__init__(self, *a, **k)
        self._screen_init()


def test_a_send_holds_the_game_and_shows_how_far_it_is_on_the_machine():
    """David: "what happens if we try to copy files over in the middle of a game on the machine? ... we need some way
    on the machine to see feedback that the update is happening (and the connection is live)"."""
    m = ScreenMachine()
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.view() == as_machine(build_games())
    assert m.events[0] == ("pause",)                                  # held before anything is touched
    assert m.events.index(("sync",)) < m.events.index(("resume",))    # back only on the new files
    assert ("changing",) not in m.events and ("stopped", False) not in m.events
    assert m.screen and all(what in ("Uploading", "Updating", "Finishing") for _d, _t, what in m.screen)
    assert m.screen[-1] == (1, 1, "Finishing")                        # PAD-1433: it reached 100%, then Finish


def test_a_send_shows_its_own_chips_and_the_time_left():
    """PAD-1433: David: "we need a separate chip for each of the phases in the progress bars"; and a Send over a
    machine's Wi-Fi takes hours, so the bar says how fast it is going and how long is left."""
    phases, bars = [], []
    p = R.SendPipeline("x.raw", "192.168.4.130", lambda *a: None, phases.append,
                       lambda cur, total, desc="": bars.append((cur, desc)), lambda *a: None)
    p._to_phase(0)
    p._send_progress(0, 100, "Comparing the game files")
    p._send_progress(50, 100, "Comparing the game files")
    p._send_progress(10 << 20, 100 << 20, "Uploading")
    p._rate[0] = (p._rate[0][0] - 10, 0)                     # ten seconds ago, so 2.1 MB/s
    p._send_progress(20 << 20, 100 << 20, "Updating")
    assert bars[-1][1] == "Sending 20.0 MB of 100.0 MB - 2.1 MB/s, less than a minute left"
    p._send_progress(1, 1, "Finishing")
    assert R.SEND_PHASES == ("Connect", "Compare", "Send", "Finish") and phases == [0, 1, 2, 3]
    assert bars[1] == (50, "Comparing the game files")
    assert bars[-1] == (100, "Finishing")


def test_the_compare_bar_moves_while_the_machine_hashes():
    """PAD-1433: the machine hashed every same-size file in one call, and the bar sat at the last partition's 99%
    for the minutes that took.  It hashes in batches now and the bar moves by the bytes hashed."""
    tree = R._Tree(FakeReader(STOCK_GAMES), R.GAMES)
    files = {p: e for p, e in tree.entries.items() if e[0] == "file"}
    mine = {p: ("file", e[1]["size"], None, e[1]["mode"], e[1]["uid"], e[1]["gid"], None)
            for p, e in tree.entries.items() if e[0] == "file"}
    calls, bars = [], []

    def hashes(paths):
        calls.append(list(paths))
        return {p: ("file", tree.sha1(files[p][1])) for p in paths}
    old = R.COMPARE_BATCH_FILES
    R.COMPARE_BATCH_FILES = 1
    try:
        R.sync_ops(tree, mine, R.GAMES, set(), [], hashes, progress=lambda d, t, w: bars.append((d, t, w)))
    finally:
        R.COMPARE_BATCH_FILES = old
    assert len(calls) == len(files) > 1 and sorted(sum(calls, [])) == sorted(files)
    assert all(w == "Comparing the game files" for _d, _t, w in bars)
    assert [d for d, _t, _w in bars] == sorted(d for d, _t, _w in bars) and bars[-1][0] == bars[-1][1]


def test_a_big_in_place_update_moves_the_bar_as_it_goes():
    m = FullMachine()
    out = build_games()
    seen = []
    tree = R._Tree(FakeReader(out), R.GAMES)
    path = "/games/kingkong/video.mp4"
    op = R.Op("put", path, node=tree.get(path)[1], size=tree.get(path)[1]["size"], sha1=tree.sha1(tree.get(path)[1]),
              mode=tree.get(path)[1]["mode"], uid=0, gid=0)
    old = R.DELTA_BLOCK, R.DELTA_BATCH
    R.DELTA_BLOCK, R.DELTA_BATCH = 4, 1
    m.remount(R.GAMES, True)
    try:
        R.delta_put(m, tree, op, progress=seen.append)
    finally:
        R.DELTA_BLOCK, R.DELTA_BATCH = old
    assert len(seen) > 1 and seen == sorted(seen) and seen[-1] <= op.size


def test_a_send_with_nothing_to_send_leaves_the_game_alone():
    m = ScreenMachine()
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    m.events.clear()
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    assert m.events == []


def test_a_send_stopped_short_puts_the_game_back_and_says_so():
    m = ScreenMachine()
    with pytest.raises(R.SendError, match="canceled"):
        R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m, cancel=lambda: ("pause",) in m.events)
    # nothing of the build was put in place: the machine's screen says so and the game comes back
    assert m.view()["/games/kingkong/video.mp4"] == as_machine(STOCK_GAMES)["/games/kingkong/video.mp4"]
    assert ("stopped", False) in m.events and ("resume",) not in m.events


def test_full_send_says_when_the_machine_starts_changing_and_when_it_stopped_part_way():
    m = FullScreenMachine(root=SSH_ROOT)
    R.sync(FakeTarget(NEW_VERSION, NEW_ROOT, boot=b"boot v2"), m)
    assert m.events.index(("stop",)) < m.events.index(("changing",)) < m.events.index(("reboot",))
    assert m.screen and ("stopped", True) not in m.events

    broken = FullScreenMachine(root=SSH_ROOT)

    def fail(*a, **k):
        raise R.SendError("the machine stopped answering")
    broken.upload = fail
    with pytest.raises(R.SendError):
        R.sync(FakeTarget(NEW_VERSION, NEW_ROOT, boot=b"boot v2"), broken)
    assert ("stopped", True) in broken.events and not broken.rebooted


def test_screen_text_is_four_centred_lines_of_sixteen():
    t = R.screen_text("PAD IS UPDATING", "RECEIVING 42%", "LINK OK *", "KEEP POWER ON")
    assert len(t) <= 64 and t[:16] == "PAD IS UPDATING " and t[16:32] == " RECEIVING 42%  "
    assert R.screen_text("A" * 20) == "A" * 16


# ------------------------------------------------------------------ PAD-1427: a clean, isolated update path
def _through_send_image(monkeypatch, target):
    import contextlib
    monkeypatch.setattr(R, "open_target", lambda image, log: contextlib.nullcontext(target))
    monkeypatch.setattr(R, "check_layout", lambda target, layout: None)


class HeldFull(FullScreenMachine):
    """Says whether the game was held when each read of the machine's files happened."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.reads = []

    def game_held(self):
        return ("pause",) in self.events and ("resume",) not in self.events

    def walk(self, root, skip=()):
        self.reads.append(("walk", root, self.game_held()))
        return super().walk(root, skip)

    def file_sha1s(self, paths):
        self.reads.append(("sha1", len(paths), self.game_held()))
        return super().file_sha1s(paths)


def test_every_send_holds_the_game_before_it_reads_or_changes_the_card(monkeypatch):
    """David: "I'm concerned about letting the game run while we are doing updates and I want to make sure we have
    a clean isolated update path"."""
    m = HeldFull(root=SSH_ROOT)
    _through_send_image(monkeypatch, FakeTarget(NEW_VERSION, NEW_ROOT, boot=b"boot v2"))
    R.send_image("deadpool_le-1_17_0.raw", m)
    assert m.events[0] == ("pause",)
    assert m.reads and all(held for *_x, held in m.reads)
    assert m.events.index(("pause",)) < m.events.index(("changing",)) < m.events.index(("reboot",))


def test_a_send_with_nothing_to_change_gives_the_game_back(monkeypatch):
    m = HeldFull(root=SSH_ROOT)
    _through_send_image(monkeypatch, FakeTarget(STOCK_GAMES, SSH_ROOT))
    assert R.send_image("deadpool_le-1_16_0.raw", m) == "The machine already has this image."
    assert m.events[0] == ("pause",) and m.events[-1] == ("resume",)
    assert ("changing",) not in m.events and not m.rebooted


def test_a_send_refused_before_any_change_gives_the_game_back(monkeypatch):
    m = HeldFull(root=SSH_ROOT)

    def unreadable(root, skip=()):
        raise R.SendError("The machine stopped answering; check it and Send again.")
    m.walk = unreadable
    _through_send_image(monkeypatch, FakeTarget(NEW_VERSION, NEW_ROOT, boot=b"boot v2"))
    with pytest.raises(R.SendError):
        R.send_image("deadpool_le-1_17_0.raw", m)
    assert ("stopped", False) in m.events and ("changing",) not in m.events and not m.rebooted
