"""PAD-1444 (David: "Network ssh compare is too slow. Can we cache this somehow?"): the machine keeps the sha1s it
worked out, each with the file's size, mtime, inode and ctime, and a compare reads again only what changed since."""

from pinball_decryptor.core import remote_send as R

from tests.test_remote_send import (BUILD_RANGES, NEW_ROOT, NEW_VERSION, SSH_ROOT, STOCK_GAMES, FakeTarget, FullMachine,
                              as_machine, build_games, make_plan)


class _Fs(dict):
    """The machine's files: any write through the kernel gives the file a new inode/ctime, as ext4 does."""

    def __init__(self, machine, init):
        super().__init__(init)
        self.m = machine
        for k in init:
            machine._touch(k)

    def __setitem__(self, k, v):
        super().__setitem__(k, v)
        self.m._touch(k)


class CachingMachine(FullMachine):
    def __init__(self, **kw):
        self.clock, self.inodes, self.meta = 1000, 0, {}
        super().__init__(**kw)
        self.fs = _Fs(self, self.fs)
        self.clock += 10                        # the card's files are older than the first look at them
        self.boot_id, self.btime = "boot-1", 900
        self.mounts_info = {R.ROOT: "179:2 /", R.GAMES: "179:3 /"}
        self.hashed, self.stated = [], []

    def _touch(self, path):
        self.inodes += 1
        self.meta[path] = (self.inodes, self.clock)

    def file_ids(self, paths):
        now = self.clock
        self.clock += 1                         # the machine's clock moves on between looks
        return now, {p: (len(self.fs[p][1]), 0) + self.meta[p] for p in paths
                     if p in self.fs and self.fs[p][0] == "file"}

    def boot_info(self):
        return {"boot": self.boot_id, "btime": self.btime, "now": self.clock, "mounts": dict(self.mounts_info)}

    def file_sha1s(self, paths):
        self.hashed.extend(paths)
        return super().file_sha1s(paths)

    def state(self, paths):
        self.stated.extend(paths)
        return super().state(paths)

    def reboot(self):
        super().reboot()
        self.boot_id += "+"
        self.btime = self.clock + 5
        self.clock += 30

    def power_cycle(self, later=3600):
        self.boot_id += "*"
        self.btime = self.clock + later
        self.clock = self.btime + 60


def _new():
    return FakeTarget(NEW_VERSION, NEW_ROOT, boot=b"boot v2")


def _no_sleep(monkeypatch):
    monkeypatch.setattr(R.time, "sleep", lambda s: None)


def test_a_second_full_send_reads_no_file_the_first_one_hashed_or_wrote(monkeypatch):
    _no_sleep(monkeypatch)
    m = CachingMachine(root=SSH_ROOT)
    R.sync(_new(), m)
    assert "/games/kingkong/video.mp4" in m.hashed          # the first compare reads them
    assert m.rebooted and m.read_hash_cache()["rebooting"]
    # what the Send put there (image.bin by delta, new.wav uploaded) is in the record with its checked sha1
    files = m.read_hash_cache()["files"]
    assert {"/games/kingkong/image.bin", "/games/kingkong/new.wav", "/games/kingkong/video.mp4"} <= set(files)
    m.hashed.clear()
    lines = []
    assert R.sync(_new(), m, log=lambda t, *a: lines.append(t)) == "The machine already has this image."
    assert m.hashed == []                                   # after PAD's own restart: nothing read again
    assert any("weren't read again" in t for t in lines)
    assert m.read_hash_cache()["boot"] == "boot-1+"         # the record taken over by the new boot


def test_a_file_changed_on_the_machine_is_compared_again_even_at_its_old_size_and_time(monkeypatch):
    _no_sleep(monkeypatch)
    m = CachingMachine(root=SSH_ROOT)
    R.sync(_new(), m)
    m.fs["/games/kingkong/video.mp4"] = ("file", b"video stOck", 0o644)    # same size, mtime: a new ctime
    m.hashed.clear()
    R.sync(_new(), m)
    assert m.hashed == ["/games/kingkong/video.mp4"]
    assert m.view() == as_machine(NEW_VERSION)


def test_a_record_from_before_a_power_cycle_is_set_aside(monkeypatch):
    """A card dumped, patched on a computer and written back keeps its inodes' sizes, times and numbers: the record
    of the boot before can't tell, so only PAD's own restart carries it over."""
    _no_sleep(monkeypatch)
    m = CachingMachine(root=SSH_ROOT)
    R.sync(_new(), m)
    dict.__setitem__(m.fs, "/games/kingkong/video.mp4", ("file", b"video stOck", 0o644))   # inode untouched
    m.power_cycle()
    m.hashed.clear()
    lines = []
    R.sync(_new(), m, log=lambda t, *a: lines.append(t))
    assert "/games/kingkong/video.mp4" in m.hashed and "/games/kingkong/image.bin" in m.hashed
    assert m.view() == as_machine(NEW_VERSION)
    assert any("compared again" in t for t in lines)


def test_a_record_of_other_partitions_is_set_aside(monkeypatch):
    _no_sleep(monkeypatch)
    m = CachingMachine(root=SSH_ROOT)
    R.sync(_new(), m)
    m.mounts_info[R.GAMES] = "179:7 /"                      # a multi-boot card's other image at /games
    m.hashed.clear()
    R.sync(_new(), m)
    assert "/games/kingkong/video.mp4" in m.hashed


def test_a_quick_send_of_the_same_build_again_hashes_none_of_its_files(monkeypatch):
    _no_sleep(monkeypatch)
    m = CachingMachine()
    R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m)
    m.stated.clear()
    assert R.send(make_plan(STOCK_GAMES, build_games(), BUILD_RANGES), m) == "The machine already has this build."
    assert not {"/games/kingkong/video.mp4", "/games/pad/mode.so"} & set(m.stated)


def test_a_machine_that_cant_say_compares_as_before():
    m = FullMachine(root=SSH_ROOT)                          # no file_ids: nothing recorded, nothing trusted
    R.sync(_new(), m)
    assert m.read_hash_cache() is None
    assert m.view() == as_machine(NEW_VERSION)


def test_a_file_changed_in_the_second_it_was_looked_at_isnt_recorded():
    c = R.HashCache(CachingMachine())
    c._note("/games/x", (5, 0, 7, 1500), ("file", "ab"), now=1500)
    assert "/games/x" not in c.files
    c._note("/games/x", (5, 0, 7, 1500), ("file", "ab"), now=1501)
    assert c.files["/games/x"] == [5, 0, 7, 1500, "ab"]
    # nor anything of a multi-boot image the Send mounts itself
    c._note(R.TEMP_MOUNT + "/p6/x", (5, 0, 7, 1), ("file", "ab"), now=9)
    assert not c._recordable(R.TEMP_MOUNT + "/p6/x")


def _ssh(answers):
    m = R.SshMachine.__new__(R.SshMachine)
    m.sh = lambda script, **kw: (0, next(v for k, v in answers if k in script))
    return m


def test_the_machines_answers_are_read():
    m = _ssh([("stat -c '%f", "1700000000\n81a4 10 1600000000 1234 1699999990 /games/a b.wav\n"
                                "41ed 4096 1 2 3 /games/dir\n")])
    assert m.file_ids(["/games/a b.wav", "/games/dir", "/games/missing"]) == (
        1700000000, {"/games/a b.wav": (10, 1600000000, 1234, 1699999990)})
    # a busybox without stat: nothing said about any file, and stat itself answers nothing
    m = _ssh([("stat -c '%f", "1700000000\n"), ("stat -c %s /", "")])
    assert m.file_ids(["/games/a"]) is None
    m = _ssh([("boot_id", "6f1c-id\n1699990000\n1700000000\n/ 179:2 /\n/games 179:3 /\n/games 179:3 /\n")])
    assert m.boot_info() == {"boot": "6f1c-id", "btime": 1699990000, "now": 1700000000,
                             "mounts": {"/": "179:2 /", "/games": "179:3 /"}}
