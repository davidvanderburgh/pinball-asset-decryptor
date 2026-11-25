"""PAD-1599: Manage disk space reaches what the app left in the PC's previous
Linux - found once, removed on a press (only names the app makes), and the
disk file given back to Windows, now when WSL is idle or at the app's close.

wsl.exe, the compact and the process list are fakes here; the real scan,
removal and compact are proven on a throwaway distro
(scripts/pad1599_old_distro_proof.py, docs/plans/old_distro_giveback.md)."""

import time

import pytest

from pinball_decryptor.core import disk_giveback as g
from pinball_decryptor.core import old_distro as od
from pinball_decryptor.core import runtime, space_keeper, wsl_disk

GB = 1024 ** 3
MB = 1024 ** 2
NOW = 1_800_000_000
OLD = NOW - 60 * 86400


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("PAD_SPACE_STATE", str(tmp_path / "space_keeper.json"))
    for k in ("PAD_OLD_DISTRO", "PAD_RUNTIME", "PAD_UI_CAPTURE", "PAD_UI_NO_RIG",
              "PAD_SPACE_KEEPER", "PAD_DISK_GIVEBACK"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(wsl_disk, "is_supported", lambda: True)


def _scan(*lines):
    return od.parse("\n".join(lines))


def _e(kind, path, size=GB, last=OLD):
    return "E\t%s\t%d\t%d\t%s" % (kind, size, last, path)


# ---------------------------------------------------------------------------
# What is offered
# ---------------------------------------------------------------------------

def test_offers_the_apps_names_only_largest_first():
    p = od.plan(_scan(
        _e("card", "/home/u/cardcache", 40 * GB),
        _e("rig", "/var/tmp/pad_ap/cache/tmnt", 3 * GB),
        _e("rig", "/var/tmp/pad_ap/rig0", 64 * MB),
        _e("rig", "/var/tmp/pad_ap/nv0", 2 * MB),          # settings, scores
        _e("rig", "/var/tmp/pad_ap/home", 9 * MB),          # a run's home
        _e("staging", "/var/tmp/jjp_wonka", 5 * GB),
        _e("staging", "/tmp/cgc_stage_x_1", 128 * MB),
        _e("staging", "/tmp/cgc_stage_tiny", 1000),         # under 1 MiB
        _e("card", "/home/u/cardcache_mine", GB),           # not our name
        _e("card", "/home/u/x/cardcache", GB),
        _e("card", "/home/../cardcache", GB),
        _e("staging", "/etc", GB),
        "U\t%d\t/home/u/padslots" % OLD), NOW)
    assert p["in_use"] == ""
    assert [i["path"] for i in p["items"]] == [
        "/home/u/cardcache", "/var/tmp/jjp_wonka", "/var/tmp/pad_ap/cache/tmnt",
        "/tmp/cgc_stage_x_1", "/var/tmp/pad_ap/rig0"]
    assert p["total"] == 40 * GB + 5 * GB + 3 * GB + 128 * MB + 64 * MB
    assert p["items"][0]["what"] == \
        "Spike 2 emulator: card cache (/home/u/cardcache)"
    assert p["items"][2]["what"] == "American Pinball: Unpacked game: tmnt"


@pytest.mark.parametrize("line, why", [
    ("U\t%d\t/home/u/padslots" % (NOW - 3600), "used today"),
    ("U\t%d\t/home/u/.pad-rig" % (NOW - 5 * 86400), "used 5 days ago"),
    (_e("rig", "/var/tmp/pad_ap/nv0", MB, NOW - 2 * 86400), "2 days ago"),
    ("X\t/home/u/src", "PAD is run from source in it (/home/u/src)"),
    ("L\tpad_ap", "an emulator game is running"),
    ("H\t/home/u/cardcache/x.raw", "something is using /home/u/cardcache"),
])
def test_nothing_is_offered_while_the_app_still_works_there(line, why):
    p = od.plan(_scan(_e("card", "/home/u/cardcache", 40 * GB), line), NOW)
    assert why in p["in_use"]
    assert p["items"] == [] and p["total"] == 0


def test_used_two_weeks_ago_is_left_behind():
    p = od.plan(_scan(_e("card", "/home/u/cardcache", GB,
                         NOW - od.IN_USE_SECS - 1)), NOW)
    assert p["in_use"] == "" and len(p["items"]) == 1


def test_offerable_guards_every_removal():
    assert od.offerable("card", "/root/cardcache")
    assert od.offerable("card", "/home/pad.user/cardcache")
    for bad in ("/home/u/cardcache/..", "/home/.x/cardcache", "/cardcache",
                "/home/u/cardcache2"):
        assert not od.offerable("card", bad), bad
    assert not od.offerable("rig", "/var/tmp/pad_ap/nv3")
    assert not od.offerable("staging", "/var/tmp/pad_ap/cache/x")   # a rig's
    assert not od.offerable("staging", "/var/tmp")
    assert not od.offerable("bogus", "/tmp/cgc_stage_x")


# ---------------------------------------------------------------------------
# Which distro
# ---------------------------------------------------------------------------

def _distros(monkeypatch, tmp_path, default="Ubuntu", app=runtime.DISTRO,
             names=("Ubuntu", "PAD-Runtime", "docker-desktop")):
    reg = []
    for n in names:
        d = tmp_path / n
        d.mkdir(exist_ok=True)
        (d / "ext4.vhdx").write_bytes(b"x" * 10)
        reg.append((n, str(d)))
    monkeypatch.setattr(wsl_disk, "registered_distros", lambda: reg)
    monkeypatch.setattr(wsl_disk, "default_distro_name", lambda: default)
    monkeypatch.setattr(runtime, "wsl_distro", lambda runner=None: app)


def test_previous_is_the_default_while_the_app_has_its_own(monkeypatch,
                                                           tmp_path):
    _distros(monkeypatch, tmp_path)
    prev = od.previous()
    assert prev["name"] == "Ubuntu" and prev["size"] == 10
    assert prev["vhdx"].endswith("ext4.vhdx")


@pytest.mark.parametrize("kw", [
    dict(app=None),                          # no runtime: the app works there
    dict(default="PAD-Runtime"),
    dict(default="docker-desktop"),
    dict(default=None),
    dict(default="Gone"),                    # not registered
])
def test_no_previous_linux(monkeypatch, tmp_path, kw):
    _distros(monkeypatch, tmp_path, **kw)
    assert od.previous() is None


def test_the_override_names_it(monkeypatch, tmp_path):
    _distros(monkeypatch, tmp_path, names=("Ubuntu", "PAD-Runtime", "Old"))
    monkeypatch.setenv("PAD_OLD_DISTRO", "old")
    assert od.previous()["name"] == "Old"


# ---------------------------------------------------------------------------
# One-time
# ---------------------------------------------------------------------------

@pytest.fixture
def prev(monkeypatch, tmp_path):
    d = tmp_path / "Ubuntu"
    d.mkdir()
    (d / "ext4.vhdx").write_bytes(b"x" * 100)
    p = {"name": "Ubuntu", "vhdx": str(d / "ext4.vhdx"), "size": 100}
    monkeypatch.setattr(od, "previous", lambda: dict(p))
    monkeypatch.setattr(wsl_disk, "registered_distros",
                        lambda: [("Ubuntu", str(d))])
    return p


def _fake_run(monkeypatch, out):
    calls = []

    def run(name, script, timeout=600):
        calls.append(script)
        return out(script) if callable(out) else out
    monkeypatch.setattr(od, "_run", run)
    return calls


def test_nothing_there_is_never_looked_at_again(monkeypatch, prev):
    calls = _fake_run(monkeypatch, "")
    assert od.check(NOW) is None and len(calls) == 1
    assert od.check(NOW + 400 * 86400) is None and len(calls) == 1


def test_in_use_is_looked_at_again_after_a_week(monkeypatch, prev):
    calls = _fake_run(monkeypatch, "X\t/home/u/src")
    assert od.check(NOW) is None
    assert od.check(NOW + 6 * 86400) is None and len(calls) == 1
    assert od.check(NOW + 8 * 86400) is None and len(calls) == 2
    rec = space_keeper.load_state()["old_distro"]["ubuntu"]
    assert rec["verdict"] == "in_use" and "source" in rec["why"]


def test_a_scan_that_fails_is_asked_again(monkeypatch, prev):
    def boom(*a, **k):
        raise wsl_disk.WslDiskError("wsl did not answer")
    monkeypatch.setattr(od, "_run", boom)
    assert od.check(NOW) is None
    assert "old_distro" not in space_keeper.load_state()


def test_found_then_removed_then_owed_then_done(monkeypatch, prev):
    lines = [_e("card", "/home/u/cardcache", 40 * GB),
             _e("staging", "/var/tmp/jjp_wonka", 5 * GB)]

    def out(script):
        if "rm -rf" in script:
            return "F\t%d\nT\t/: 45 GiB trimmed\n" % (45 * GB)
        return "\n".join(lines)
    calls = _fake_run(monkeypatch, out)
    found = od.check(NOW)
    assert found["total"] == 45 * GB and not found["compact_only"]
    freed, removed, kept = od.remove("Ubuntu", found["items"], NOW)
    assert (freed, kept) == (45 * GB, [])
    assert removed == ["/home/u/cardcache", "/var/tmp/jjp_wonka"]
    script = calls[-1]
    assert "'/home/u/cardcache' '/var/tmp/jjp_wonka'" in script
    assert "fstrim -v /" in script and "mountpoint -q" in script
    # the compact is owed: the window offers it alone, the close takes it
    again = od.check(NOW + 60)
    assert again["compact_only"] and again["items"] == []
    assert [o["name"] for o in od.owed()] == ["Ubuntu"]
    od.done("Ubuntu", 217 * GB, 171 * GB)
    assert od.check(NOW + 120) is None and od.owed() == []


def test_remove_takes_only_what_a_fresh_look_still_offers(monkeypatch, prev):
    state = {"n": 0}

    def out(script):
        if "rm -rf" in script:
            return "F\t%d\nK\t/var/tmp/pad_ap/rig0\n" % GB
        if "for n in pad_ap" in script:                # _RIG_BUSY: no game
            state["busy"] = True
            return ""
        state["n"] += 1
        return "\n".join([_e("card", "/home/u/cardcache"),
                          _e("rig", "/var/tmp/pad_ap/rig0")])
    calls = _fake_run(monkeypatch, out)
    items = [{"kind": "card", "path": "/home/u/cardcache"},
             {"kind": "rig", "path": "/var/tmp/pad_ap/rig0"},
             {"kind": "staging", "path": "/etc"},            # never offered
             {"kind": "staging", "path": "/tmp/cgc_stage_gone"}]
    freed, removed, kept = od.remove("Ubuntu", items, NOW)
    assert kept == ["/var/tmp/pad_ap/rig0"] and removed == ["/home/u/cardcache"]
    assert "/etc" not in calls[-1] and "cgc_stage_gone" not in calls[-1]
    # a rig's root is asked whether a game runs before anything goes
    assert state.get("busy")


def test_remove_refuses_when_the_app_is_back_at_work(monkeypatch, prev):
    _fake_run(monkeypatch, "\n".join([_e("card", "/home/u/cardcache"),
                                      "L\tpad_ap"]))
    with pytest.raises(wsl_disk.WslDiskError, match="Nothing was removed"):
        od.remove("Ubuntu", [{"kind": "card", "path": "/home/u/cardcache"}],
                  NOW)


# ---------------------------------------------------------------------------
# Giving the disk file back
# ---------------------------------------------------------------------------

def test_compact_waits_while_anything_runs(prev):
    with pytest.raises(od.Busy) as e:
        od.compact(prev, busy=lambda: ["Docker is running"],
                   release=pytest.fail, compact_fn=pytest.fail)
    assert e.value.args[0] == ["Docker is running"]


def test_compact_shuts_wsl_down_and_records(monkeypatch, prev):
    seen = []

    def compact(v):
        if not seen:
            seen.append("held")
            raise wsl_disk.VirtDiskError(32, "held")
        seen.append("ok")
        with open(v, "wb") as f:
            f.write(b"x" * 40)
    released = []
    before, after = od.compact(prev, busy=lambda: [],
                               release=released.append, compact_fn=compact)
    assert (before, after) == (100, 40)
    assert released == [prev["vhdx"]] * 2 and seen == ["held", "ok"]
    rec = space_keeper.load_state()["old_distro"]["ubuntu"]
    assert rec["verdict"] == "done" and (rec["before"], rec["after"]) == (100, 40)


def test_busy_reasons(monkeypatch, prev):
    _fake_run(monkeypatch, "a terminal: bash\n")
    r = od.busy_reasons("Ubuntu", busy_host=lambda: [],
                        distros=lambda: ["PAD-Runtime", "Ubuntu",
                                         "docker-desktop"],
                        app_scan=lambda: "SCAN_DONE")
    assert r == ["docker-desktop is running",
                 "Ubuntu is in use (a terminal: bash)"]
    _fake_run(monkeypatch, "")
    assert od.busy_reasons("Ubuntu", busy_host=lambda: [],
                           distros=lambda: ["PAD-Runtime", "Ubuntu"],
                           app_scan=lambda: "SCAN_DONE") == []
    assert od.busy_reasons("Ubuntu", busy_host=lambda: [],
                           distros=lambda: ["PAD-Runtime"],
                           app_scan=lambda: "BUSY emulator qemu\nSCAN_DONE") == \
        ["emulator qemu"]


def test_the_close_gives_an_owed_disk_back(monkeypatch, tmp_path, prev):
    """The give-back at close takes an owed disk whatever its spare and
    week, and records it done."""
    od._remember("Ubuntu", verdict="compact", checked=NOW)
    monkeypatch.setattr(g, "_default_distro_vhdx", lambda: (None, None),
                        raising=False)
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx", lambda: (None, None))
    monkeypatch.setattr(g, "runtime_distro", lambda: "PAD-Runtime")
    dl = [d for d in g.disks() if d.get("old")]      # this PC's own disks out
    assert [d.get("old") for d in dl] == ["Ubuntu"]
    st = {"giveback_checked": time.time()}           # checked an hour ago
    assert g.due(time.time(), st=st, disk_list=dl)
    sizes = {prev["vhdx"]: 100}
    monkeypatch.setattr(g, "_file_size", lambda p: sizes[p])
    compacted = []

    def compact(v):
        compacted.append(v)
        sizes[v] = 30
    rec = g.run(disk_list=dl, release=lambda v: None, compact=compact,
                busy_host=lambda: [], distros=lambda: ["PAD-Runtime"],
                wsl_script=lambda s: "SCAN_DONE", trim=lambda: None)
    assert compacted == [prev["vhdx"]] and rec["freed"] == 70
    assert od.owed() == []
    assert space_keeper.load_state()["old_distro"]["ubuntu"]["verdict"] == \
        "done"


def test_the_close_leaves_an_owed_disk_while_its_distro_runs(monkeypatch,
                                                            prev):
    od._remember("Ubuntu", verdict="compact", checked=NOW)
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx", lambda: (None, None))
    monkeypatch.setattr(g, "runtime_distro", lambda: "PAD-Runtime")
    rec = g.run(disk_list=[d for d in g.disks() if d.get("old")], release=pytest.fail, compact=pytest.fail,
                busy_host=lambda: [], distros=lambda: ["PAD-Runtime", "Ubuntu"],
                wsl_script=lambda s: "SCAN_DONE", trim=lambda: None)
    assert rec == {"busy": ["Ubuntu is running"]}
    assert [o["name"] for o in od.owed()] == ["Ubuntu"]


# ---------------------------------------------------------------------------
# The window
# ---------------------------------------------------------------------------

def test_the_section_in_the_window(tmp_path, monkeypatch):
    from pinball_decryptor.webui import shellx_disk
    from tests.test_webui_card_images import until
    from tests.webui_harness import web_app

    found = {"name": "Ubuntu", "vhdx": "C:/x/ext4.vhdx", "size": 206 * GB,
             "total": 45 * GB, "compact_only": False,
             "items": [{"kind": "card", "path": "/home/u/cardcache",
                        "size": 40 * GB, "last": OLD,
                        "what": "Spike 2 emulator: card cache (/home/u/cardcache)"},
                       {"kind": "staging", "path": "/var/tmp/jjp_wonka",
                        "size": 5 * GB, "last": OLD,
                        "what": "Jersey Jack Pinball: Emulator image: wonka"}]}
    monkeypatch.setattr(shellx_disk, "_probes_allowed", lambda: True)
    monkeypatch.setattr(shellx_disk, "_emu_helpers", lambda: None)
    monkeypatch.setattr(wsl_disk, "available", lambda: (False, "not here"))
    monkeypatch.setattr(od, "check", lambda: dict(found))
    removed = []
    monkeypatch.setattr(od, "remove", lambda name, items: (
        removed.append((name, [i["path"] for i in items])) or
        (45 * GB, [i["path"] for i in items], [])))
    busy = {"why": ["a Linux program is still open (wsl.exe)"]}

    def compact(prev, progress=None):
        if busy["why"]:
            raise od.Busy(busy["why"])
        return 206 * GB, 161 * GB
    monkeypatch.setattr(od, "compact", compact)

    with web_app(tmp_path, mfr="stern") as w:
        def old():
            return w.state("shellx")["disk"].get("old")
        w.call("shellx.disk_open")
        assert until(w, lambda: w.state("shellx")["disk"].get("old_checked")
                     and not w.state("shellx")["disk"]["busy"])
        o = old()
        assert o["head"] == "Left behind in Ubuntu"
        assert "45.00 GiB in all" in o["note"] and "206.00 GiB" in o["note"]
        assert [r["size"] for r in o["rows"]] == ["40.00 GiB", "5.00 GiB"]
        # No: nothing happens
        w.answers.append("no")
        assert w.call("shellx.old_distro_clean") is False and removed == []
        # Yes, WSL busy: removed, the compact owed
        w.answers.append("yes")
        assert w.call("shellx.old_distro_clean") is True
        assert until(w, lambda: not old()["busy"] and old()["status"])
        assert removed == [("Ubuntu", ["/home/u/cardcache",
                                       "/var/tmp/jjp_wonka"])]
        o = old()
        assert o["status"].startswith("Removed 45.00 GiB from Ubuntu.")
        assert "when you close the app" in o["status"]
        assert o["button"] == "Give the space back…" and o["rows"] == []
        # pressed again once WSL is idle: compact only, before -> after
        busy["why"] = []
        w.answers.append("yes")
        assert w.call("shellx.old_distro_clean") is True
        assert until(w, lambda: "back to Windows" in (old()["status"] or ""))
        assert len(removed) == 1                       # nothing removed again
        assert old()["status"] == ("Its disk file went from 206.00 GiB to "
                                   "161.00 GiB: 45.00 GiB back to Windows.")
        assert old()["button"] == ""
        assert w.call("shellx.disk_close") is True


def test_no_section_in_captures(tmp_path, monkeypatch):
    from tests.test_webui_card_images import until
    from tests.webui_harness import web_app
    monkeypatch.setattr(od, "check", pytest.fail)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("shellx.disk_open")
        assert until(w, lambda: w.state("shellx")["disk"].get("old_checked"))
        assert w.state("shellx")["disk"]["old"] is None
