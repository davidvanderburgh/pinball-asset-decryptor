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
        for path, target, _u, _g in links:
            self._w(path)
            self.fs[path] = ("link", target, 0o777)
        for path, _is_dir in deletes:
            self._w(path)
            self.fs.pop(path, None)
        self.events.append(("commit",))

    def write_ranges(self, path, ranges):
        self._w(path)
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
    target = FakeTarget(NEW_VERSION, NEW_ROOT, layout={1: (8192, 16384), 2: (24576, 688128), 3: (712704, 2000000)})
    with pytest.raises(R.SendError, match="partition 3 is placed or sized differently"):
        R.check_layout(target, FullMachine().layout())
    with pytest.raises(R.SendError, match="the machine has partition 4"):
        R.check_layout(FakeTarget(NEW_VERSION, NEW_ROOT), {**FullMachine().layout(), 4: (9, 2)})


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
