"""PAD-819: "Can WSL use another drive other than C?" - Manage disk space >
Move to another drive (core/wsl_place.py).

Everything here is fakes: no wsl.exe, no shutdown, no real drive.  The real
round trip (a diskpart data disk C: -> D: -> C:, attached by WSL from D:, and
`wsl --manage --move` refused while WSL holds a distro's disk) was run on
Windows once, with C:/tmp/PAD-819/prove_move.py.
"""

import contextlib
import ntpath
import os
import sys
import types

import pytest

from pinball_decryptor.core import rigdata, runtime, wsl_place

GB = 1024 ** 3


@pytest.fixture
def place(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setenv("PAD_WSL_PLACE", str(tmp_path / "local" / "place.json"))
    for env in ("PAD_RUNTIME_DIR", "PAD_DATA_DISK", "PAD_CARDS_DISK"):
        monkeypatch.delenv(env, raising=False)
    return tmp_path


def drive(letter, free=500 * GB, fs="NTFS"):
    return {"letter": letter, "label": "", "fs": fs, "free": free,
            "total": 2000 * GB, "ok": fs in ("NTFS", "ReFS"),
            "why": "" if fs in ("NTFS", "ReFS") else "%s: WSL needs NTFS" % fs}


def item(key, path, size, **kw):
    return dict(key=key, label=kw.pop("label", key), path=path, size=size,
                pinned=kw.pop("pinned", ""), **kw)


# ---------------------------------------------------------------- the place
def test_paths_follow_the_saved_place_and_forget_it_back_home(place):
    home = os.path.join(str(place / "local"), "pinball_decryptor")
    assert wsl_place.root() == home
    assert rigdata.disk_path() == os.path.join(home, "data", "pad-data.vhdx")
    assert rigdata.cards_disk_path() == os.path.join(home, "data",
                                                     "pad-cards.vhdx")
    assert runtime.install_dir() == os.path.join(home, "runtime")

    wsl_place.save_root(r"D:\pinball_decryptor")
    assert rigdata.disk_path() == os.path.join(r"D:\pinball_decryptor",
                                               "data", "pad-data.vhdx")
    assert runtime.install_dir() == os.path.join(r"D:\pinball_decryptor",
                                                 "runtime")
    # saving the default again is forgetting
    wsl_place.save_root(home)
    assert not os.path.exists(wsl_place.place_file())
    assert wsl_place.root() == home


def test_an_environment_override_still_wins(place, monkeypatch):
    wsl_place.save_root(r"D:\pinball_decryptor")
    monkeypatch.setenv("PAD_DATA_DISK", r"E:\mine.vhdx")
    monkeypatch.setenv("PAD_RUNTIME_DIR", r"E:\rt")
    assert rigdata.disk_path() == r"E:\mine.vhdx"
    assert runtime.install_dir() == r"E:\rt"


def test_a_broken_place_file_is_the_default(place):
    os.makedirs(os.path.dirname(wsl_place.place_file()), exist_ok=True)
    with open(wsl_place.place_file(), "w") as f:
        f.write("{not json")
    assert wsl_place.root() == wsl_place.default_root()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive paths")
def test_root_on_a_drive(place, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\u\AppData\Local")
    assert wsl_place.root_on("d:") == r"D:\pinball_decryptor"
    assert wsl_place.root_on("C:\\") == r"C:\Users\u\AppData\Local" \
        "\\pinball_decryptor"


# ----------------------------------------------------------------- the plan
ITEMS = [item("distro", r"C:\rt\ext4.vhdx", 40 * GB, distro="PAD-Runtime"),
         item("data", r"C:\d\pad-data.vhdx", 2 * GB)]


def test_plan_names_what_stops_a_move(place):
    def why(letter, drives, items=ITEMS):
        return wsl_place.plan(letter, items, drives)[2]
    assert why("D:", [drive("D:")]) == ""
    assert "needs NTFS" in why("G:", [drive("G:", fs="FAT32")])
    assert why("Z:", [drive("D:")]) == "Z: is not a drive this PC has."
    assert why("C:", [drive("C:")]) == "Everything is on C: already."
    # 42 GB of disks and 5 to spare do not fit in 46
    msg = why("D:", [drive("D:", free=46 * GB)])
    assert msg.startswith("D: has 46.0 GB free; the move needs 47.0 GB")


def test_plan_moves_only_what_is_elsewhere_and_not_pinned(place):
    items = ITEMS + [item("cards", r"D:\c\pad-cards.vhdx", 300 * GB),
                     item("data", r"C:\pinned.vhdx", GB,
                          pinned="PAD_DATA_DISK")]
    moving, root, problem = wsl_place.plan("D:", items, [drive("D:")])
    assert problem == "" and root == r"D:\pinball_decryptor"
    assert [i["path"] for i in moving] == [r"C:\rt\ext4.vhdx",
                                           r"C:\d\pad-data.vhdx"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive paths")
def test_targets(place):
    root = r"D:\pinball_decryptor"
    assert wsl_place.target_of(ITEMS[0], root) == root + r"\runtime"
    own = item("distro", r"C:\x\ext4.vhdx", 1, distro="Ubuntu")
    assert wsl_place.target_of(own, root) == root + r"\wsl\Ubuntu"
    assert wsl_place.target_of(ITEMS[1], root) == root + r"\data\pad-data.vhdx"


def test_drives_refuses_what_wsl_cannot_use():
    usage = lambda p: types.SimpleNamespace(free=9 * GB, total=10 * GB)
    vols = {"C:": ("Windows", "NTFS"), "G:": ("Google Drive", "FAT32"),
            "E:": None}
    got = wsl_place.drives(["C:", "G:", "E:"], volume=vols.get, usage=usage)
    assert [(d["letter"], d["ok"]) for d in got] == [("C:", True),
                                                     ("G:", False)]
    assert got[1]["why"] == "FAT32: WSL needs NTFS"


# ----------------------------------------------------------------- the move
class FakeWsl:
    """``wsl --manage <d> --move <dest>`` that moves the file the way WSL
    does, or answers with *fail* (a list of outputs, one per call)."""

    def __init__(self, src_dir, fail=()):
        self.src_dir, self.fail, self.calls = src_dir, list(fail), []

    def __call__(self, argv, **kw):
        self.calls.append(argv)
        assert argv[:2] == ["wsl", "--manage"] and argv[3] == "--move"
        if self.fail:
            return types.SimpleNamespace(returncode=1, stdout=b"",
                                         stderr=self.fail.pop(0).encode())
        os.replace(os.path.join(self.src_dir, "ext4.vhdx"),
                   os.path.join(argv[4], "ext4.vhdx"))
        return types.SimpleNamespace(returncode=0, stdout=b"", stderr=b"")


def _setup(tmp_path, monkeypatch):
    """A C: and a D: as two folders: drive_of() reads the first letter of
    the path, so the two trees are given letters by root_on."""
    c, dd = tmp_path / "C", tmp_path / "D"
    (c / "rt").mkdir(parents=True)
    (c / "data").mkdir()
    dd.mkdir()
    (c / "rt" / "ext4.vhdx").write_bytes(b"L" * 3000)
    (c / "data" / "pad-data.vhdx").write_bytes(b"D" * 5000)
    monkeypatch.setattr(wsl_place, "root_on", lambda d: str(dd / "pad"))
    monkeypatch.setattr(wsl_place, "drive_of",
                        lambda p: "D:" if str(dd) in str(p) else "C:")
    monkeypatch.setattr(wsl_place, "SPARE_BYTES", 0)
    items = [item("distro", str(c / "rt" / "ext4.vhdx"), 3000,
                  distro="PAD-Runtime", label="the app's Linux"),
             item("data", str(c / "data" / "pad-data.vhdx"), 5000,
                  label="the data disk")]
    return c, dd, items


def _move(items, run, **kw):
    held, waits = [], []

    @contextlib.contextmanager
    def hold():
        held.append(True)
        yield
        held.append(False)
    done = wsl_place.move("D:", all_items=items, all_drives=[drive("D:")],
                          hold=hold, run=run,
                          free_disk=lambda p, say: waits.append(p), **kw)
    return done, held, waits


def test_move_copies_the_disks_then_moves_the_linux(place, monkeypatch):
    c, dd, items = _setup(place, monkeypatch)
    run = FakeWsl(str(c / "rt"))
    said = []
    done, held, waits = _move(items, run, progress=said.append)
    assert held == [True, False]
    assert waits == [i["path"] for i in items]         # WSL let go of each
    new_data = dd / "pad" / "data" / "pad-data.vhdx"
    assert new_data.read_bytes() == b"D" * 5000
    assert not (c / "data" / "pad-data.vhdx").exists()
    assert (dd / "pad" / "runtime" / "ext4.vhdx").read_bytes() == b"L" * 3000
    assert run.calls == [["wsl", "--manage", "PAD-Runtime", "--move",
                          str(dd / "pad" / "runtime")]]
    assert wsl_place.root() == str(dd / "pad")
    assert rigdata.disk_path() == str(new_data)
    assert [l for l, _ in done] == ["the data disk", "the app's Linux"]
    assert not list((dd / "pad" / "data").glob("*.part"))
    assert said and said[-1].endswith("100%")


def test_a_failed_linux_move_leaves_the_moved_disks_working(place,
                                                           monkeypatch):
    c, dd, items = _setup(place, monkeypatch)
    run = FakeWsl(str(c / "rt"), fail=["The disk is full."])
    with pytest.raises(wsl_place.MoveError) as e:
        _move(items, run)
    msg = str(e.value)
    assert "The disk is full." in msg
    assert "Moved: the data disk. They work from there; the app's Linux " \
        "stayed where it was." in msg
    # the data disk is on D: and found there; the Linux is whole on C:
    assert rigdata.disk_path() == str(dd / "pad" / "data" / "pad-data.vhdx")
    assert os.path.isfile(rigdata.disk_path())
    assert (c / "rt" / "ext4.vhdx").exists()


def test_a_held_linux_disk_is_waited_for_and_tried_again(place, monkeypatch):
    c, dd, items = _setup(place, monkeypatch)
    sharing = ("The process cannot access the file because it is being used "
               "by another process.\nError code: Wsl/Service/MoveDistro/"
               "ERROR_SHARING_VIOLATION")
    run = FakeWsl(str(c / "rt"), fail=[sharing])
    done, _held, waits = _move(items[:1], run)
    assert len(run.calls) == 2 and len(waits) == 2
    assert (dd / "pad" / "runtime" / "ext4.vhdx").exists()
    # held all three times: say what to close, and save nothing
    c, dd, items = _setup(place / "again", monkeypatch)
    run = FakeWsl(str(c / "rt"), fail=[sharing] * 3)
    os.remove(wsl_place.place_file())
    with pytest.raises(wsl_place.MoveError) as e:
        _move(items[:1], run)
    assert "Close anything else that uses WSL" in str(e.value)
    assert "try the move again" in str(e.value)
    assert not os.path.exists(wsl_place.place_file())


def test_a_copy_cut_short_switches_nothing(place, monkeypatch):
    c, dd, items = _setup(place, monkeypatch)
    cards = c / "data" / "pad-cards.vhdx"
    cards.write_bytes(b"C" * 7000)
    items.append(item("cards", str(cards), 7000, label="the card store"))
    real = wsl_place._copy

    def copy(src, dst, on_bytes):
        if src == str(cards):
            raise OSError("no room")
        return real(src, dst, on_bytes)
    monkeypatch.setattr(wsl_place, "_copy", copy)
    run = FakeWsl(str(c / "rt"))
    with pytest.raises(OSError):
        _move(items, run)
    assert run.calls == []
    assert (c / "data" / "pad-data.vhdx").exists() and cards.exists()
    assert not list(dd.rglob("*.part")) and not list(dd.rglob("*.vhdx"))
    assert not os.path.exists(wsl_place.place_file())


def test_wsl_will_not_move_a_linux_into_a_folder_with_things_in_it(
        place, monkeypatch):
    c, dd, items = _setup(place, monkeypatch)
    (dd / "pad" / "runtime").mkdir(parents=True)
    (dd / "pad" / "runtime" / "old.txt").write_text("x")
    with pytest.raises(wsl_place.MoveError) as e:
        _move(items[:1], FakeWsl(str(c / "rt")))
    assert "is not empty" in str(e.value)


@pytest.mark.skipif(sys.platform != "win32", reason="probes wsl.exe")
def test_move_supported_reads_the_help(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout="  --move <Location>\n".encode("utf-16-le"), stderr=b""))
    assert wsl_place.move_supported() == (True, "")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: types.SimpleNamespace(
        stdout=b"--resize", stderr=b""))
    ok, msg = wsl_place.move_supported()
    assert not ok and "wsl --update" in msg


# --------------------------------------------------- Manage disk space window
def test_disk_space_window_moves_to_the_picked_drive(tmp_path, monkeypatch):
    from tests.test_webui_shellx import until
    from tests.webui_harness import web_app
    from pinball_decryptor.core import host_temp
    monkeypatch.setattr(host_temp, "usage", lambda: None)
    monkeypatch.setattr(host_temp, "scan", lambda: [])
    items = [item("distro", r"C:\Users\u\AppData\Local\pinball_decryptor"
                  r"\runtime\ext4.vhdx", 40 * GB, distro="PAD-Runtime",
                  label="the app's Linux (PAD-Runtime)")]
    monkeypatch.setattr(wsl_place, "move_supported", lambda: (True, ""))
    monkeypatch.setattr(wsl_place, "drives", lambda: [
        drive("C:"), drive("D:", free=10 * GB), drive("E:"),
        drive("G:", fs="FAT32")])
    moved = []
    monkeypatch.setattr(wsl_place, "move", lambda letter, progress, all_items:
                        moved.append((letter, all_items)) or
                        [("the app's Linux (PAD-Runtime)",
                          r"E:\pinball_decryptor\runtime")])
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("shellx")
        w.call("shellx.disk_open")
        assert until(w, lambda: not w.state("shellx")["disk"]["busy"])
        assert w.state("shellx")["disk"]["can_move"] is False   # no WSL
        svc._disk_scan_id += 1
        svc._disk_apply_scan(svc._disk_scan_id, {
            "wsl_ok": True, "wsl_entries": [], "rig_entries": [],
            "host_entries": [], "emu_entries": [], "place": items})
        d = w.state("shellx")["disk"]
        assert d["can_move"] is True
        assert d["move_where"].startswith(
            "C:  The app's Linux (PAD-Runtime)  (40.00 GiB)")
        spec = w.call("shellx.disk_move_prepare")
        by = {o["letter"]: o for o in spec["drives"]}
        assert not by["C:"]["ok"] and "already" in by["C:"]["why"]
        assert not by["D:"]["ok"] and "10.0 GB free" in by["D:"]["why"]
        assert not by["G:"]["ok"] and "NTFS" in by["G:"]["why"]
        assert by["E:"]["ok"] and spec["pick"] == "E:"
        w.answers.append("no")
        assert w.call("shellx.disk_move", "E:") is False
        ask = w.asked[-1]
        assert ask["title"] == "Move to another drive"
        assert "→  " + os.path.join(r"E:\pinball_decryptor", "runtime") \
            in ask["message"]
        assert "WSL will be shut down" in ask["message"]
        assert moved == []
        w.answers.append("yes")
        w.answers.append("ok")
        assert w.call("shellx.disk_move", "E:") is True
        assert until(w, lambda: moved and w.asked[-1]["title"] == "Moved")
        assert moved[0][0] == "E:"
        assert r"E:\pinball_decryptor\runtime" in w.asked[-1]["message"]
