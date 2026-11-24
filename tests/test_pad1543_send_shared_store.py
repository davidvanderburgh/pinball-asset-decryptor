"""PAD-1543: a Send to a machine running a multi-boot card whose games share one store of files.

On that card (mkmulticard's store layout) every file of every game is a hard link into ``/games/.blobs``: one
file, held once, under the store's name for it and under each game's own.  A Send took each name for a file of
its own.  A changed file was then sent and held once per name, and worse: a file two games share, changed for one
game in place, changed under the other game's name too.

The image is a stand-in partition whose reader gives two names the same inode; the machine a stand-in that keeps
inodes, so a write through one name shows under every other."""

import hashlib

import pytest

from pinball_decryptor.core import remote_send as R
from tests.test_remote_send import STOCK_ROOT, FakeReader, FakeTarget, FullMachine, _counting


def blob(data):
    return ".blobs/" + hashlib.sha1(data).hexdigest()


def store(games):
    """A store-layout game partition from ``{game's name for a file: bytes}``: each distinct content once under
    ``.blobs``, every game's name another name of it (``("same", the store's name)``)."""
    spec = {".blobs": ("dir",)}
    for rel, data in sorted(games.items()):
        parts = rel.split("/")
        for i in range(1, len(parts)):
            spec["/".join(parts[:i])] = ("dir",)
        spec.setdefault(blob(data), ("file", data))
        spec[rel] = ("same", blob(data))
    return spec


def flat(spec):
    return {rel: (spec[ent[1]] if ent[0] == "same" else ent) for rel, ent in spec.items()}


class StoreReader(FakeReader):
    """FakeReader whose ``("same", other)`` entries are other names of *other*'s inode."""

    def __init__(self, spec):
        self.same = {rel: ent[1] for rel, ent in spec.items() if ent[0] == "same"}
        super().__init__({rel: ent for rel, ent in spec.items() if ent[0] != "same"})
        for rel, first in self.same.items():
            self.nodes[rel] = self.nodes[first]

    def iter_tree(self):
        order = sorted(self.nodes)
        for rel in order:
            kind, node = self.nodes[rel]
            yield rel, kind, order.index(self.same.get(rel, rel)) + 11, node


class StoreTarget(FakeTarget):
    def __init__(self, games, root=STOCK_ROOT):
        super().__init__(flat(games), root)
        self.trees[R.GAMES] = R._Tree(StoreReader(games), R.GAMES)


class StoreMachine(FullMachine):
    """FullMachine that keeps inodes: a file changed through one of its names is changed under all of them."""

    def __init__(self, games, linked=True, ids=True):
        super().__init__(games=flat(games))
        self.ino, self._next, self._ids = {}, 100, ids
        for rel, ent in games.items():
            if ent[0] == "file":
                self.ino["/games/" + rel] = self._new()
        for rel, ent in games.items():
            if ent[0] == "same":
                self.ino["/games/" + rel] = self.ino["/games/" + ent[1]] if linked else self._new()

    def _new(self):
        self._next += 1
        return self._next

    def _spread(self, path):
        for p, n in self.ino.items():
            if n == self.ino.get(path) and p != path:
                self.fs[p] = self.fs[path]

    def write_ranges(self, path, ranges):
        super().write_ranges(path, ranges)
        self._spread(path)

    def truncate(self, path, size):
        super().truncate(path, size)
        self._spread(path)

    def set_attrs(self, path, mode, uid, gid):
        super().set_attrs(path, mode, uid, gid)
        self._spread(path)

    def upload(self, path, fileobj, size, mode, uid, gid, callback=None):
        super().upload(path, fileobj, size, mode, uid, gid, callback)
        if path in self.ino:
            self._spread(path)                  # written over what was there: the same file, every name of it
        else:
            self.ino[path] = self._new()

    def copy(self, src, dst):
        super().copy(src, dst)
        self.ino[dst] = self._new()

    def commit(self, renames, links, deletes):
        for tmp, final in renames:
            self.ino[final] = self.ino.pop(tmp)
        for path, _t, _u, _g in links:
            self.ino.pop(path, None)
        for path, _is_dir in deletes:
            self.ino.pop(path, None)
        super().commit(renames, links, deletes)

    def remove(self, paths):
        super().remove(paths)
        for p in paths:
            self.ino.pop(p, None)

    def hardlink(self, pairs):
        for src, path in pairs:
            self._w(path)
            assert self.fs[src][0] == "file", src
            self.fs[path], self.ino[path] = self.fs[src], self.ino[src]
            self.events.append(("ln", path))

    def file_ids(self, paths):
        if not self._ids:
            return None
        return 0, {p: (len(self.fs[p][1]), 0, self.ino[p], 0) for p in paths
                   if p in self.fs and self.fs[p][0] == "file"}

    def names(self):
        """The machine's files as sets of names of one file."""
        groups = {}
        for p, n in self.ino.items():
            if p.startswith("/games/") and not p.endswith(R.TMP_TAG):
                groups.setdefault(n, set()).add(p)
        return sorted(sorted(g) for g in groups.values())


def names_on(games):
    groups = {}
    for rel, ent in games.items():
        if ent[0] in ("file", "same"):
            groups.setdefault(ent[1] if ent[0] == "same" else rel, set()).add("/games/" + rel)
    return sorted(sorted(g) for g in groups.values())


SHARED = b"a video both games play " * 200
OLD = store({"godzilla_le/video.mp4": SHARED, "godzilla_le/game": b"ELF stern",
             "img1/godzilla_le/video.mp4": SHARED, "img1/godzilla_le/game": b"ELF heisei 2.3",
             "img1/godzilla_le/song.wav": b"heisei's song " * 300})
NEW_VIDEO = SHARED[:1000] + b"HEISEI 2.4" + SHARED[1010:]
NEW = store({"godzilla_le/video.mp4": SHARED, "godzilla_le/game": b"ELF stern",
             "img1/godzilla_le/video.mp4": NEW_VIDEO, "img1/godzilla_le/game": b"ELF heisei 2.4",
             "img1/godzilla_le/song.wav": b"heisei's song " * 300,
             "img1/godzilla_le/new.wav": b"new in 2.4"})


def as_fs(games):
    return {p: e[:2] for p, e in FullMachine(games=flat(games)).fs.items() if p.startswith("/games/")}


def test_only_a_partition_with_a_store_has_names_to_link():
    tree = R._Tree(StoreReader(OLD), R.GAMES)
    links = R.store_links(tree, R.GAMES)
    assert links["/games/godzilla_le/video.mp4"] == "/games/" + blob(SHARED)
    assert links["/games/img1/godzilla_le/video.mp4"] == "/games/" + blob(SHARED)
    assert set(links.values()) == {"/games/" + rel for rel in OLD if rel.startswith(".blobs/")}
    assert not any(p.startswith("/games/.blobs/") for p in links)
    # two names of one file where there is no store (nothing PAD makes): left as a Send always took them
    plain = {rel: ent for rel, ent in OLD.items() if not rel.startswith(".blobs")}
    plain["a"] = ("file", b"x")
    plain = {rel: (("same", "a") if ent[0] == "same" else ent) for rel, ent in plain.items()}
    assert R.store_links(R._Tree(StoreReader(plain), R.GAMES), R.GAMES) == {}


def test_the_image_the_machine_already_runs_changes_nothing():
    m = StoreMachine(OLD)
    assert R.sync(StoreTarget(OLD), m) == "The machine already has this image."
    assert m.events == []


@pytest.mark.parametrize("ids", [True, False])
def test_a_new_version_of_one_game_is_sent_once_and_the_other_game_is_untouched(monkeypatch, ids):
    """David, 2026-11-23: "if there is a new HEISEI version, can i upload it from my computer to the machine?" """
    monkeypatch.setattr(R, "DELTA_BLOCK", 1024)
    m = StoreMachine(OLD, ids=ids)
    uploads, written = _counting(m)
    R.sync(StoreTarget(NEW), m)
    assert m.view(R.GAMES) == as_fs(NEW)
    # the game that didn't change still plays its own video: the one file both played was never written to
    assert m.fs["/games/godzilla_le/video.mp4"][1] == SHARED
    assert m.fs["/games/img1/godzilla_le/video.mp4"][1] == NEW_VIDEO
    # every file once on the card, under the same names as on the image
    assert m.names() == names_on(NEW)
    # each changed file crossed the network once, under the store's name: nothing went up under a game's own
    sent = [p.replace("/.", "/", 1) if "/." + p.rsplit("/", 1)[1][1:] == p[p.rfind("/"):] else p for p in uploads]
    assert all("/.blobs/" in p for p in uploads + [p for p, _n in written]), (uploads, written)
    assert len(sent) == len(set(sent))
    # the changed video: built from the machine's old one, only the block that differs sent
    video = [n for p, n in written if blob(NEW_VIDEO).split("/")[1] in p]
    assert video == [1024]
    assert not any(p.endswith(R.TMP_TAG) for p in m.fs)
    assert m.rebooted
    # and that Send again finds nothing to do
    m2_events = len(m.events)
    assert R.sync(StoreTarget(NEW), m) == "The machine already has this image."
    assert len(m.events) == m2_events


def test_a_card_an_earlier_send_left_unlinked_is_linked_again_without_sending_a_file():
    m = StoreMachine(OLD, linked=False)
    assert m.names() != names_on(OLD)
    uploads, written = _counting(m)
    R.sync(StoreTarget(OLD), m)
    assert uploads == [] and written == []
    assert m.names() == names_on(OLD)
    assert m.view(R.GAMES) == as_fs(OLD)


def test_a_machine_that_cannot_say_which_files_are_one_has_its_names_compared_instead():
    """No stat in its busybox: every name is compared like any file, so a Send of what it has changes nothing
    (and does not restart it), and only a name whose file differs is linked."""
    m = StoreMachine(OLD, linked=False, ids=False)
    assert R.sync(StoreTarget(OLD), m) == "The machine already has this image."
    assert m.events == []
    m.rw[R.GAMES] = True
    m.write_ranges("/games/img1/godzilla_le/game", [(0, b"BAD")])
    m.rw[R.GAMES] = False
    uploads, written = _counting(m)
    R.sync(StoreTarget(OLD), m)
    assert uploads == [] and written == []
    assert ("ln", "/games/img1/godzilla_le/game") in m.events
    assert m.view(R.GAMES) == as_fs(OLD)


def test_a_store_file_gone_bad_on_the_machine_is_never_mended_in_place(monkeypatch):
    """The store's copy differs from its name (a card that took an old Send): it is replaced by a copy renamed
    over it, and the names are linked to that - a write in place would go through every name at once."""
    monkeypatch.setattr(R, "DELTA_BLOCK", 1024)
    m = StoreMachine(OLD)
    bad = "/games/" + blob(SHARED)
    m.rw[R.GAMES] = True
    m.write_ranges(bad, [(0, b"BAD!")])
    m.rw[R.GAMES] = False
    seen = []
    wr = m.write_ranges
    m.write_ranges = lambda path, rr: (seen.append(path), wr(path, rr))[1]
    R.sync(StoreTarget(OLD), m)
    assert seen and all(p.endswith(R.TMP_TAG) for p in seen)
    assert m.view(R.GAMES) == as_fs(OLD)
    assert m.names() == names_on(OLD)


def test_the_real_machine_links_by_a_copy_of_the_name_renamed_over_it():
    cmds = []
    m = R.SshMachine.__new__(R.SshMachine)
    m.sh = lambda text, **k: (cmds.append(text), (0, ""))[1]
    m.hardlink([("/games/.blobs/ab", "/games/img1/it's.wav")])
    src, tmp, name = (R._q(p) for p in ("/games/.blobs/ab", "/games/img1/.it's.wav" + R.TMP_TAG,
                                        "/games/img1/it's.wav"))
    assert cmds == ["set -e\nrm -f %s; ln %s %s; mv -f %s %s; rm -f %s" % (tmp, src, tmp, tmp, name, tmp)]
