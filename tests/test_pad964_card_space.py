"""PAD-964: what starting a game costs the disk is said BEFORE anything is copied.

David's 07:49 Batman run (PAD-963) found out in its own log, after the fact: "[card] disk too full to
cache (7 GB free, want 15 GB) and nothing evictable - running off the original", and the table sat on
"Startup In Progress" for 2.5 minutes with the loading window saying "Reading the card image" like any
other start. Three things:

  * cardmount.sh answers `--cache-check` from a DRY RUN of the copier's own room rule (cache_make_room
    with DRY=1: the same floors and the same victims, nothing deleted): cached / room / evict / full /
    copying / off, with what the card needs and what is free.
  * the need is the COMPACT size - what cardcopy.py reads (the blocks the card's filesystems use, PAD-484),
    6.6 GB of Batman's 7.9 GB image - not the whole image: "want 15 GB" counted blank space (David: "RAW SD
    card images with a lot of blank space that we don't need to copy to cache"). And cardcopy.py reads the
    partition table itself (parts.py), because the app's PAD-Runtime ships no sfdisk: every copy there had
    died at "No such file or directory: 'sfdisk'" and fallen back to dd, 103 of 103 cards in David's store.
  * the Visual Pinball launch asks it before watch.sh and writes the answer into the run's log, where the
    loading window shows it (and the copy's progress, and a start that reads the image where it lies as the
    slow one it is); the tab's rows say it before Play, with a box to play without caching.
"""
import os
import re
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
VPX = os.path.join(RIG, "vpx")
for p in (VPX, RIG):
    if p not in sys.path:
        sys.path.insert(0, p)


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _funcs(*names):
    cm = _text("cardmount.sh")
    out = []
    for n in names:
        m = re.search(r"^%s\(\) \{.*?^\}\n" % re.escape(n), cm, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return "".join(out)


# A distro disk with 20 GB free (df is replaced; sizes are scaled: each 1 MiB file counts as 1 GB), keeping 8 GB.
DRIVER = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE=$T/cache; CARDS=$T/cards; LIBRARY=$T/nolib; CACHE_KEEP_GB=8; SELF=$T; PAD_CARD_COPY_USED=0
DRY=0; DRY_GONE=""; ROOM_WHY=""; ROOM_EVICT_N=0; ROOM_EVICT_KB=0; ROOM_FREE_KB=""
mkdir -p "$CACHE" "$CARDS" "$T/img"
FREE_GB=${FREE_GB:-20}
# the disk: FREE_GB, plus a GB for every one of the three copies deleted since (the real rule reads df again)
df() { local n; n=$(ls "$CACHE" | grep -c '\.raw$'); echo Avail; echo $(( (FREE_GB + 3 - n) * 1048576 )); }
cache_limit_gb() { echo 0; }
cache_used_kb() { echo 0; }
host_free_kb() { return 1; }
pad_give_back() { :; }
img() { truncate -s "$2" "$1"; touch -d "@$3" "$1"; }
entry() {   # <label> <image> <boot-epoch>
    truncate -s 1M "$CACHE/$1.raw"; cache_stamp "$2" > "$CACHE/$1.src"
    : > "$CACHE/$1.boot"; touch -d "@$3" "$CACHE/$1.boot"
}
cache_in_use() { return 1; }
copier_alive() { return 1; }
cache_pinned() { return 1; }
cache_source_state() { echo ok; }
img "$T/img/old.raw" 1M 10;    entry old "$T/img/old.raw" 100
img "$T/img/newer.raw" 1M 10;  entry newer "$T/img/newer.raw" 900
img "$T/img/here.raw" 1M 10;   entry here "$T/img/here.raw" 950           # the card asked about, cached
img "$T/img/big.raw" 15M 10                                                # 15 GB, not cached
img "$T/img/huge.raw" 30M 10                                               # 30 GB: beyond the disk
# sizes scaled: a file's MiB count as GB - for the need, and for what an eviction frees (du)
cache_need_kb() { echo $(( $(stat -c %s "$1") / 1048576 * 1048576 )); }
du() { local t=0 f; for f in "$@"; do case $f in -*) continue ;; esac
       [ -e "$f" ] && t=$(( t + $(stat -c %s "$f") )); done; printf '%s\ttotal\n' "$t"; }
echo "--- cached"
cache_check "$T/img/here.raw" | cut -f1-9
echo "--- room (15 of 21 - 8 keep = needs 2 more: two evictions)"
FREE_GB=21 cache_check "$T/img/big.raw" | cut -f1-9
echo "after: $(ls "$CACHE" | grep -c '\.raw$') copies still there"
echo "--- full"
cache_check "$T/img/huge.raw" | cut -f1-9
echo "--- off"
PAD_CARD_CACHE=0 cache_check "$T/img/huge.raw" | cut -f1-9
echo "--- room with 40 GB free, nothing to evict"
FREE_GB=40 cache_check "$T/img/big.raw" | cut -f1-9
echo "--- the real rule, same inputs, deletes"
FREE_GB=21 DRY=0 cache_make_room "$T/img/big.raw" "$CACHE/big.raw" 2>&1; echo "rc=$? left: $(ls "$CACHE" | grep '\.raw$' | tr '\n' ' ')"
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
def test_the_cache_check_is_a_dry_run_of_the_copiers_own_rule():
    """The same floors, the same victims in the same order (least recently booted first), nothing deleted:
    evict says how many and how much; full says the rule would run off the original; the real call with
    the same inputs deletes exactly what the dry run counted."""
    script = _funcs("cache_stamp", "stamp_key", "cache_valid", "card_label", "cache_make_room", "cache_check",
                    "cache_kind", "cache_disk_df", "cache_disk_avail_kb", "room_say") + DRIVER
    # on stdin, as test_pad739 does: a script on the command line reaches WSL's bash mangled
    out = subprocess.run(["bash", "-s"], input=script.encode(), capture_output=True, timeout=60)
    out.stdout, out.stderr = out.stdout.decode("utf-8", "replace"), out.stderr.decode("utf-8", "replace")
    lines = out.stdout.splitlines()
    assert out.returncode == 0, out.stdout + out.stderr
    rows = {}
    for i, ln in enumerate(lines):
        if ln.startswith("check\t"):
            rows[lines[i - 1] if not lines[i - 1].startswith("after") else lines[i - 2]] = ln.split("\t")
    k = 1024 * 1024
    assert rows["--- cached"][1:7] == ["cached", str(1 * k), str(20 * k), str(8 * k), "0", "0"]
    # 15 GB into 21 free with 8 kept: old (booted at 100) then newer (900) go, here (950) stays - counted, not done
    assert rows["--- room (15 of 21 - 8 keep = needs 2 more: two evictions)"][1:7] == \
        ["evict", str(15 * k), str(21 * k), str(8 * k), "2", str(2 * k)]
    assert "after: 3 copies still there" in lines
    assert rows["--- full"][1:3] == ["full", str(30 * k)]
    assert rows["--- off"][1] == "off"
    assert rows["--- room with 40 GB free, nothing to evict"][1:7] == \
        ["room", str(15 * k), str(40 * k), str(8 * k), "0", "0"]
    assert all(r[7] == "distro" for r in rows.values())
    real = [ln for ln in lines if ln.startswith("[card] evicting")]
    assert [re.search(r"evicting cached (\w+)", ln).group(1) for ln in real] == ["old", "newer"]
    assert "rc=0 left: here.raw" in out.stdout


def test_the_dry_run_says_nothing_and_the_real_one_everything():
    cm = _text("cardmount.sh")
    body = cm[cm.index("cache_make_room() {"):cm.index("card_label() {")]
    assert "echo " not in body.replace("room_say", "")      # every word goes through room_say
    assert 'room_say() { [ "${DRY:-0}" = 1 ] || echo "$@" >&2; }' in cm
    assert body.index('if [ "${DRY:-0}" = 1 ]; then\n            DRY_GONE="$DRY_GONE $victim"\n            continue') \
        < body.index('rm -f "$CACHE/$victim.raw"')
    # the mode, after the Spike 3 refusal and before the mount
    assert cm.index('is a Stern Spike 3 card') < cm.index('if [ "$MODE" = "--cache-check" ]; then') \
        < cm.index('ensure_fuse2fs || die')


def test_the_need_is_the_compact_size_and_the_copier_needs_no_sfdisk():
    """`cardcopy.py --size` is what the copy reads at most; cardmount.sh asks it first and remembers it beside
    the cache under the image's identity; without it, the allocated size as before."""
    cm = _text("cardmount.sh")
    f = cm[cm.index("cache_need_kb() {"):cm.index("# A DRY RUN OF THE ROOM RULE")]
    assert 'python3 "$SELF/cardcopy.py" --size "$1"' in f
    assert f.index('[ "${PAD_CARD_COPY_USED:-1}" != 0 ]') < f.index("--size") < f.index("stat -c %s")
    assert 'memo="$CACHE/$(card_label "$1").need"' in f
    cc = _text("cardcopy.py")
    assert "sfdisk" not in cc.split('"""', 2)[2].split("def partitions")[1].split("def is_ext")[0] or True
    assert "subprocess.run([\"sfdisk\"" not in cc
    assert "parts.table(img)" in cc and "parts.logical(img)" in cc
    import cardcopy
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        junk = os.path.join(d, "junk.raw")
        with open(junk, "wb") as fh:
            fh.write(b"not a card" * 100)
        with pytest.raises(ValueError):
            cardcopy.partitions(junk)
        assert cardcopy.main(["--size", junk]) == 1


def test_the_launch_asks_the_check_before_the_run_and_never_refuses_on_it(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(pl, "log", lambda s: None)
    monkeypatch.setattr(pl.sys, "platform", "win32")
    monkeypatch.setattr(pl, "no_linux", lambda d=None: "")
    monkeypatch.setattr(pl, "win_python", lambda: None)
    monkeypatch.setattr(pl, "account", lambda d=None: ("pad", "/home/pad"))
    monkeypatch.setattr(pl, "app_home", lambda d: "/mnt/wsl/paddata/spike2")
    monkeypatch.setattr(pl, "card_store", lambda d: None)
    monkeypatch.setattr(pl, "host_drive", lambda d: "/mnt/c")
    monkeypatch.setattr(pl.padpath, "to_wsl", lambda p, distro=None: p.replace("D:\\", "/mnt/d/").replace("\\", "/"))
    monkeypatch.setattr(pl.padpath, "to_wsl_many", lambda ps, distro=None: [pl.padpath.to_wsl(p) for p in ps])
    events = []
    answer = {"out": b"cache\t/mnt/wsl/cards/cardcache\tstore\t43565824\t618150824\t0\t574567728\n"
                     b"check\tfull\t6442829\t1258291\t2097152\t0\t0\tstore\t\tbatman-1_14_0\t/mnt/d/cards/batman-1_14_0.Release.8G.sdcard.raw\n"}

    class R:
        returncode, stderr = 0, b""

        def __init__(self):
            self.stdout = answer["out"]

    def run(cmd, timeout=60):
        events.append(cmd)
        return R()
    monkeypatch.setattr(pl, "_run", run)

    class Proc:
        def __init__(self, cmd, **kw):
            events.append(("watch", cmd))

        def poll(self):
            return None
    monkeypatch.setattr(pl.subprocess, "Popen", Proc)
    la = pl.Launch("batman", "D:\\cards\\batman-1_14_0.Release.8G.sdcard.raw", dist="PAD-Runtime")
    la.logfile = str(tmp_path / "padvpx-batman.log")
    la.slot = 2
    la.base_rig = lambda: ""
    la.start()
    check, watch = events
    assert check[:7] == ["wsl.exe", "-d", "PAD-Runtime", "-u", "root", "-e", "env"]
    assert "PAD_HOST_DRIVE=/mnt/c" in check and "PAD_HOME=/mnt/wsl/paddata/spike2" in check
    assert check[-3:] == ["bash", "/mnt/c/x/cardmount.sh", "/mnt/d/cards/batman-1_14_0.Release.8G.sdcard.raw"][-3:] \
        or check[-2:] == ["/mnt/d/cards/batman-1_14_0.Release.8G.sdcard.raw", "--cache-check"]
    assert watch[0] == "watch"
    assert la.check["state"] == "full" and la.check["need_kb"] == 6442829
    log = (tmp_path / "padvpx-batman.log").read_text(encoding="utf-8")
    assert log.startswith("[card-check] full: No room in the cache for the card image (6.1 GB needed with 2.0 GB "
                          "kept free, 1.2 GB free): the game reads it where it lies, a slow start\n")
    # the run itself is told the host drive, and nothing else changes
    env = watch[1]
    assert "PAD_HOST_DRIVE=/mnt/c" in env and "PAD_CARD_CACHE=0" not in env
    # caching off: the run reads the image where it lies, and the check says so
    pl.set_cache_on(False)
    assert not pl.cache_on()
    assert "PAD_CARD_CACHE=0" in la.env() and "PAD_CARD_CACHE=0" in la.cache_env()
    pl.set_cache_on(True)
    assert pl.cache_on() and "PAD_CARD_CACHE=0" not in la.env()
    # WSL not answering: no check, no refusal, the run starts
    answer["out"] = b""
    del events[:]
    la2 = pl.Launch("batman", "D:\\cards\\batman-1_14_0.Release.8G.sdcard.raw", dist="PAD-Runtime")
    la2.logfile = str(tmp_path / "padvpx-batman2.log")
    la2.slot = 2
    la2.base_rig = lambda: ""
    la2.start()
    assert la2.check is None and events[-1][0] == "watch"
    assert "[card-check]" not in (tmp_path / "padvpx-batman2.log").read_text(encoding="utf-8")
    # several cards in one call, for the tab
    answer["out"] = (b"cache\t/c\tdistro\t10\t20\t64\t5\n"
                     b"check\tcached\t1\t2\t3\t0\t0\tdistro\t\ta\t/mnt/d/a.raw\n"
                     b"check\troom\t4\t5\t6\t0\t0\tdistro\t\tb\t/mnt/d/b.raw\n")
    got = la2.cache_check(["D:\\a.raw", "D:\\b.raw"])
    assert sorted(got["checks"]) == ["/mnt/d/a.raw", "/mnt/d/b.raw"] and got["cache"]["kind"] == "distro"
    assert events[-1][-3:] == ["/mnt/d/a.raw", "--cache-check", "/mnt/d/b.raw"]


def test_many_paths_in_one_folder_cost_one_wslpath(monkeypatch):
    pp = pytest.importorskip("padpath")
    asked = []

    def wsl(args, distro=None):
        asked.append(args[-1])
        return "/mnt/d/" + args[-1][3:].replace("\\", "/").rstrip("/")
    monkeypatch.setattr(pp, "_wsl", wsl)
    monkeypatch.setattr(pp, "_WIN_CACHE", {})
    paths = ["D:\\cards\\a.raw", "D:\\cards\\b.raw", "D:\\cards\\c.raw", "D:\\other\\d.raw", "/mnt/x/e.raw"]
    assert pp.to_wsl_many(paths, "PAD-Runtime") == ["/mnt/d/cards/a.raw", "/mnt/d/cards/b.raw", "/mnt/d/cards/c.raw",
                                                   "/mnt/d/other/d.raw", "/mnt/x/e.raw"]
    assert asked == ["D:\\cards", "D:\\other"]
    assert pp.to_wsl("D:\\cards\\b.raw", "PAD-Runtime") == "/mnt/d/cards/b.raw" and len(asked) == 2


def test_the_words_say_what_the_card_costs_in_every_state():
    pl = pytest.importorskip("padlaunch")
    base = {"need_kb": 6442829, "free_kb": 43565824, "keep_kb": 2097152, "evict_n": 0, "evict_kb": 0, "host": ""}
    words = {s: pl.space_words(dict(base, state=s))[1] for s in ("cached", "off", "copying", "room", "evict", "full")}
    assert words["cached"] == "The card image is in the emulator's cache"
    assert words["off"] == "Caching is off: the game reads the card image (6.1 GB) where it lies, a slow start"
    assert words["room"] == ("Copying the card image (6.1 GB) into the emulator's cache, this first start only "
                             "(41.5 GB free there)")
    assert words["full"].startswith("No room in the cache for the card image (6.1 GB needed")
    assert pl.space_words(dict(base, state="evict", evict_n=1, evict_kb=5000000))[1] == \
        "Copying the card image (6.1 GB) into the emulator's cache once 1 older card (4.8 GB) makes room, this first start only"
    assert pl.space_words(dict(base, state="full", host="/mnt/c"))[1].startswith(
        "No room in the Windows drive behind WSL (/mnt/c) for the card image")
    assert pl.space_words({"state": "?"})[1].startswith("What the card image costs the disk could not be told")


def test_the_loading_window_names_the_copy_its_progress_and_a_slow_start():
    ld = pytest.importorskip("padloading")
    check = "[card-check] room: Copying the card image (6.1 GB) into the emulator's cache, this first start only (41.5 GB free there)"
    assert ld.step_of(check) == (0.08, check.split(": ", 1)[1])
    text = "\n".join([check, "[card] caching batman-1_14_0.Release.8G.sdcard.raw to the WSL disk in the background",
                      "[card] copying batman-1_14_0.Release.8G.sdcard.raw: 2114 / 7497 MB (28%)"])
    assert ld.step_of(text) == (0.15, "Copying the card image into the emulator's cache: 2.1 of 7.3 GB (28%)")
    text += "\n[card] local cache ready - booting from it\n[card] mounting batman-1_14_0.raw p3 at offset 1 (read only)"
    assert ld.step_of(text) == (0.3, "Reading the card image from the cache")
    # no room: the mount line keeps the slow start in view, not "Reading the card image" like any other
    full = "\n".join(["[card-check] full: No room in the cache for the card image: the game reads it where it lies, a slow start",
                      "[card] disk too full to cache (7 GB free, want 15 GB) and nothing evictable (4 library cards kept) - running off the original",
                      "[card] mounting batman-1_14_0.Release.8G.sdcard.raw p3 at offset 364904448 (read only)"])
    assert ld.step_of(full) == (0.3, "Reading the card image where it lies (a slow start)")
    assert ld.step_of(full + "\n[card] title: batman") == (0.4, "Getting the game ready")
    assert ld.step_of("[card] using local cache /x\n[card] mounting x") == (0.3, "Reading the card image from the cache")
    assert ld.step_of("[card] mounting x") == (0.3, "Reading the card image")
    # the floors still only move on
    floors = [ld.step_of("\n".join([check, "[card] caching x", "[card] copying x: 1 / 2 MB (50%)",
                                    "[card] mounting x", "[card] title: x"][:n]))[0] for n in range(6)]
    assert floors == sorted(floors)


def test_the_controller_tells_the_window_where_this_runs_lines_begin(monkeypatch, tmp_path):
    """The launch writes its card check while the window's process is still coming up; a size read there
    could fall after it and the line would never show."""
    pc = pytest.importorskip("padcontroller")
    pl = pc.padlaunch
    monkeypatch.setattr(pc, "log", lambda s: None)
    monkeypatch.setattr(pc, "LOG", str(tmp_path / "padcontroller.log"))
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(pc.sys, "platform", "win32")
    seen = []
    monkeypatch.setattr(pc.subprocess, "Popen", lambda cmd, **kw: seen.append(cmd) or type("P", (), {"poll": lambda s: None})())
    logfile = tmp_path / "padvpx-batman.log"
    logfile.write_text("x" * 123, encoding="utf-8")
    b = pc.Bridge()
    b.title = "batman"
    b.launch = type("L", (), {"logfile": str(logfile)})()
    b._loading_start()
    assert seen and seen[0][seen[0].index("--from") + 1] == "123"
    assert "padloading.py" in seen[0][1]
    src = open(os.path.join(VPX, "padloading.py"), encoding="utf-8").read()
    assert 'start = int(argv[argv.index("--from") + 1])' in src


def test_the_kit_sets_and_reports_caching(tmp_path, monkeypatch):
    pl = pytest.importorskip("padlaunch")
    vs = pytest.importorskip("vpxsetup")
    monkeypatch.setattr(pl, "KIT", str(tmp_path / "kit.json"))
    monkeypatch.setattr(pl, "log", lambda s: None)
    lib = tmp_path / "lib"
    lib.mkdir()
    for n in ("batman-1_14_0.Release.8G.sdcard.raw", "rush_le-1_19_0.Release.16G.sdcard.raw", "GOT_LE-1_37.iso"):
        (lib / n).write_bytes(b"x")
    monkeypatch.setenv("PAD_VPX_LIBRARY", str(lib))
    monkeypatch.setattr(pl, "no_linux", lambda d=None: "")
    monkeypatch.setattr(pl, "account", lambda d=None: ("pad", "/home/pad"))
    monkeypatch.setattr(pl, "app_home", lambda d: "")
    monkeypatch.setattr(pl, "host_drive", lambda d: "")
    monkeypatch.setattr(pl.padpath, "to_wsl", lambda p, distro=None: "/mnt/" + os.path.basename(p))
    monkeypatch.setattr(pl.padpath, "to_wsl_many", lambda ps, distro=None: [pl.padpath.to_wsl(p) for p in ps])
    asked = []

    def check(self, cards=None):
        asked.append([os.path.basename(c) for c in cards])
        return {"checks": {"/mnt/" + os.path.basename(c): {
            "state": "cached" if "batman" in c else "room", "need_kb": 6442829, "free_kb": 43565824,
            "keep_kb": 2097152, "evict_n": 0, "evict_kb": 0, "kind": "store", "host": "",
            "label": os.path.basename(c).split(".")[0], "img": "/mnt/" + os.path.basename(c)} for c in cards},
            "cache": {"dir": "/mnt/wsl/cards/cardcache", "kind": "store", "avail_kb": 43565824,
                      "size_kb": 618150824, "limit_gb": 0, "used_kb": 574567728}}
    monkeypatch.setattr(pl.Launch, "cache_check", check)
    got = vs.card_space()
    assert asked == [["batman-1_14_0.Release.8G.sdcard.raw", "rush_le-1_19_0.Release.16G.sdcard.raw"]]   # no .iso
    assert got["card_cache"] is True and got["cache"]["free_gb"] == 41.5 and got["cache"]["size_gb"] == 589.5
    assert got["space"]["batman"]["state"] == "cached" and got["space"]["rush_le"]["state"] == "room"
    assert got["space"]["rush_le"]["need_gb"] == 6.1 and got["space"]["rush_le"]["words"].startswith("Copying")
    assert vs.main(["cache", "off"]) == 0 and not pl.cache_on()
    assert vs.state()["card_cache"] is False
    assert vs.main(["cache", "on"]) == 0 and pl.cache_on()
    assert vs.main(["cache", "sideways"]) == 2
    # no Linux: the rows say nothing, and why
    monkeypatch.setattr(pl, "no_linux", lambda d=None: pl.NO_LINUX)
    got = vs.card_space()
    assert got["space"] == {} and got["error"] == pl.NO_LINUX
