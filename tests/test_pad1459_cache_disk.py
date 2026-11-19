"""A user's Spike 2 card cache on a disk of its own, sharing identical blocks (PAD-1459).

A user has no card store (cardstore.ps1 is David's), so their cards were cached inside a Linux disk that only ever
grows on C:, and the cache is mostly the same blocks over and over: a custom build is the stock card with a few files
changed, an LE card shares 73-80% with its Pro. The app now makes pad-cardcache.vhdx (XFS with reflink, mkfs.xfs
fetched pinned), attaches it at /mnt/wsl/padcache, moves the old cache in once, shares each new copy's blocks after it
lands, and counts the cache's limit by the disk's real use - measured on the emulator machine: six Godzilla builds
38.0 GB by du, 16.8 GB on the disk.
"""
import os
import re
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH
from pinball_decryptor.core import rigdata, wsl_place
from pinball_decryptor.webui import emulate_core

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(REPO, "tools", "spike2_emu")


def _text(*parts):
    with open(os.path.join(REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def _funcs(*names):
    cm = _text("tools", "spike2_emu", "cardmount.sh")
    out = []
    for n in names:
        m = re.search(r"^%s\(\) \{.*?^\}\n" % re.escape(n), cm, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return "".join(out)


# ---------------------------------------------------------------- the disk (rigdata)
class _Fake:
    """wsl.exe / diskpart / lsblk as the app meets them on a user's PC."""

    def __init__(self, path, mkfs_rc=0):
        self.path, self.mkfs_rc, self.calls = path, mkfs_rc, []
        self.attached = self.mounted = False

    def __call__(self, args, timeout=None, distro=None):
        self.calls.append((args, distro))
        if args[:3] == ["cmd", "/c", "diskpart"]:
            script = open(args[-1], encoding="ascii").read()
            assert 'file="%s"' % self.path in script
            self.max_mb = int(re.search(r"maximum=(\d+)", script).group(1))
            open(self.path, "wb").close()
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:2] == ["lsblk", "-ndo"]:
            return subprocess.CompletedProcess(args, 0, b"sda\nsdb\n" + (b"sdc\n" if self.attached else b""), b"")
        if args[:2] == ["wsl.exe", "--mount"]:
            if "--bare" in args:
                self.attached = True
            else:
                self.mounted = True
            return subprocess.CompletedProcess(args, 0, b"ok", b"")
        if args[:2] == ["wsl.exe", "--unmount"]:
            self.attached = False
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if args[:2] == ["bash", "/rig/cachedisk.sh"]:
            return subprocess.CompletedProcess(args, self.mkfs_rc, b"formatted" if not self.mkfs_rc else b"",
                                               b"" if not self.mkfs_rc else b"could not download xfsprogs")
        if args[:2] == ["bash", "-c"]:
            return subprocess.CompletedProcess(args, 0, b"mounted" if self.mounted else b"no", b"")
        raise AssertionError(args)


def _user(monkeypatch, tmp_path):
    monkeypatch.setattr(rigdata.sys, "platform", "win32")
    monkeypatch.setenv("PAD_CARDS_DISK", str(tmp_path / "pad-cards.vhdx"))      # no store: a user
    path = str(tmp_path / "pad-cardcache.vhdx")
    monkeypatch.setenv("PAD_CACHE_DISK", path)
    return path


def test_a_user_gets_an_xfs_cache_disk_made_formatted_and_attached(monkeypatch, tmp_path):
    path = _user(monkeypatch, tmp_path)
    run = _Fake(path)
    said = []
    mkfs = ["bash", "/rig/cachedisk.sh", "mkfs"]
    assert rigdata.ensure_cache_disk("PAD-Runtime", mkfs, size_gb=96, log=said.append, runner=run) \
        == "/mnt/wsl/padcache"
    assert os.path.isfile(path) and run.max_mb == 96 * 1024
    assert "card cache a disk of its own" in said[0] and "96 GB" in said[0]
    calls = [c for c, _ in run.calls]
    # formatted bare, on the ONE device that appeared, as root in the runtime, through the rig's cachedisk.sh
    assert (mkfs + ["/dev/sdc"], "PAD-Runtime") in run.calls
    assert ["wsl.exe", "--mount", "--vhd", path, "--bare"] in calls
    assert calls.index(["wsl.exe", "--unmount", path]) > calls.index(mkfs + ["/dev/sdc"])
    # then attached by name, as XFS, so every distro sees /mnt/wsl/padcache
    assert calls[-1] == ["wsl.exe", "--mount", "--vhd", path, "--name", "padcache", "--type", "xfs"]
    # a second Start: made already and mounted, nothing but the question
    n = len(run.calls)
    assert rigdata.ensure_cache_disk("PAD-Runtime", mkfs, runner=run) == "/mnt/wsl/padcache"
    assert [c for c, _ in run.calls[n:]] == [["bash", "-c", rigdata._CACHE_DISK_IS_MOUNTED]]


def test_never_made_beside_the_card_store_and_never_off_windows(monkeypatch, tmp_path):
    path = _user(monkeypatch, tmp_path)
    (tmp_path / "pad-cards.vhdx").write_bytes(b"x")              # David's store holds the cache there
    run = _Fake(path)
    assert rigdata.ensure_cache_disk("PAD-Runtime", ["bash", "/rig/cachedisk.sh", "mkfs"], runner=run) is None
    assert run.calls == [] and not os.path.exists(path)
    os.remove(tmp_path / "pad-cards.vhdx")
    monkeypatch.setattr(rigdata.sys, "platform", "linux")
    assert rigdata.ensure_cache_disk("PAD-Runtime", ["bash", "/rig/cachedisk.sh", "mkfs"], runner=run) is None
    assert run.calls == []


def test_a_disk_that_could_not_be_formatted_is_deleted_again(monkeypatch, tmp_path):
    path = _user(monkeypatch, tmp_path)
    run = _Fake(path, mkfs_rc=1)
    with pytest.raises(RuntimeError, match="could not put a filesystem on the card cache disk: could not download"):
        rigdata.ensure_cache_disk("PAD-Runtime", ["bash", "/rig/cachedisk.sh", "mkfs"], size_gb=96, runner=run)
    # an empty file would mount as nothing on the next Start: it goes, and the next Start makes it afresh
    assert not os.path.exists(path)
    assert ["wsl.exe", "--unmount", path] in [c for c, _ in run.calls]


def test_the_disk_is_sized_from_the_cache_limit_or_what_the_old_cache_holds():
    assert rigdata.cache_disk_size_gb() == 64 + 32
    assert rigdata.cache_disk_size_gb(128, 20) == 128 + 32
    assert rigdata.cache_disk_size_gb(64, 150) == 150 + 32         # an old cache past its limit still fits


def test_manage_disk_space_lists_and_keeps_it_off_a_hard_disk(monkeypatch, tmp_path):
    monkeypatch.setenv("PAD_CARDS_DISK", str(tmp_path / "pad-cards.vhdx"))
    path = str(tmp_path / "pad-cardcache.vhdx")
    monkeypatch.setenv("PAD_CACHE_DISK", path)
    open(path, "wb").close()
    monkeypatch.setenv("PAD_DATA_DISK", str(tmp_path / "none.vhdx"))
    items = {i["key"]: i for i in wsl_place.items() if i["key"] != "distro"}
    assert items["cardcache"]["path"] == path and items["cardcache"]["label"] == "the Spike 2 card cache"
    assert "cardcache" in wsl_place.SLOW_STAYS


def test_the_compact_task_compacts_it():
    ps = _text("tools", "spike2_emu", "padcompact.ps1")
    assert "data\\pad-cardcache.vhdx'); distro = $probe; path = '/mnt/wsl/padcache'" in ps


# ---------------------------------------------------------------- mkfs.xfs, pinned
def test_mkfs_xfs_is_pinned_to_the_runtimes_own_snapshot_by_hash():
    sx = _text("tools", "spike2_emu", "storexfs.sh")
    snap = re.search(r"^ARG SNAPSHOT=(\S+)", _text("tools", "runtime", "Dockerfile"), re.M).group(1)
    assert "https://snapshot.ubuntu.com/ubuntu/%s/pool/main" % snap in sx
    pins = re.findall(r"^(\S+\.deb) ([0-9a-f]{128})$", sx, re.M)
    assert sorted(p.split("/")[-1].split("_")[0] for p, _ in pins) == ["libinih1", "liburcu8t64", "xfsprogs"]
    # every download is checked before anything is unpacked, and a mismatch refuses
    assert 'sha512sum "$f"' in sx and "SHA-512 differs) - refused" in sx
    # the cache disk is labelled as itself
    assert '-L "${3:-cards}"' in sx and "storexfs.sh\" mkfs \"$dev\" padcache" in _text("tools", "spike2_emu",
                                                                                       "cachedisk.sh")


# ---------------------------------------------------------------- cardmount.sh on the disk
DRIVER = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE_DISK=$T/padcache; mkdir -p "$CACHE_DISK/cardcache"
truncate -s 3M "$CACHE_DISK/cardcache/a.raw" "$CACHE_DISK/cardcache/b.raw"
echo 1000 > "$CACHE_DISK/.base_kb"
mountpoint() { return 0; }
df() { echo Used; echo 5000; }
CACHE=$CACHE_DISK/cardcache
echo "kind $(cache_kind) limit $(cache_limit_gb) used $(cache_used_kb)"
CACHE=/mnt/wsl/cards/cardcache; echo "kind $(cache_kind)"
CACHE=$T/home/cardcache; mkdir -p "$CACHE"; truncate -s 2M "$CACHE/c.raw"; echo "c" > "$CACHE/c.raw"
echo "kind $(cache_kind) used_is_du $( [ "$(cache_used_kb)" -lt 100 ] && echo yes)"
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.skipif(sys.platform == "darwin", reason="cardmount.sh is the rig's (WSL/Linux)")
def test_on_the_disk_the_limit_counts_the_disks_real_use_not_du():
    out = subprocess.run(["bash", "-s"], input=(_funcs("cache_kind", "cache_limit_gb", "cache_used_kb") + DRIVER)
                         .encode(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                         timeout=60).stdout.decode("utf-8", "replace")
    lines = out.splitlines()
    # 5000 KB used on the disk, 1000 of them the empty filesystem's: 4000 - not the files' 6 MB by du
    assert "kind disk limit 64 used 4000" in lines, out
    assert "kind store" in lines and "kind distro used_is_du yes" in lines, out


SETTLE = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE_DISK=$T/padcache; CACHE=$CACHE_DISK/cardcache; mkdir -p "$CACHE"
echo "9000 7000 5000 4000 4000 4000 4000" > "$T/seq"
df() { local s; read -r -a s < "$T/seq"; echo Used; echo "${s[0]}"; echo "${s[*]:1}" > "$T/seq"; [ -n "${s[1]:-}" ] || echo 4000 > "$T/seq"; }
sleep() { :; }
sync() { :; }
cache_settle; echo "settled at $(df | tail -1)"
echo "9000 7000" > "$T/seq"; DRY=1 cache_settle; echo "dry left $(cat "$T/seq")"
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.skipif(sys.platform == "darwin", reason="cardmount.sh is the rig's (WSL/Linux)")
def test_after_an_eviction_it_waits_for_xfs_to_give_the_blocks_back():
    # measured: six shared Godzilla builds deleted, the disk read 9.7 GB used for a minute before 1.96 - and the
    # limit, measuring at once, evicted every other card
    out = subprocess.run(["bash", "-s"], input=(_funcs("cache_kind", "cache_settle") + SETTLE).encode(),
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60).stdout.decode()
    lines = out.splitlines()
    assert "settled at 4000" in lines, out              # read down to where it stopped falling
    assert "dry left 9000 7000" in lines, out           # a dry run deletes nothing and waits for nothing


def test_the_copier_shares_blocks_after_the_copy_off_the_boot_path():
    cm = _text("tools", "spike2_emu", "cardmount.sh")
    body = cm[cm.index('setsid bash -c \'\n            img="$1"'):]
    body = body[:body.index("</dev/null >>")]
    assert "'" not in body[body.index("\n"):body.rindex("' _ ")]      # the copier body is one quoted string
    published, freed, shared = (body.index('mv "$copy.partial" "$copy"'), body.index('rm -f "$pidf"'),
                                body.index("storededupe.py\" dedupe --quiet-s 0"))
    assert published < freed < shared                   # the copy is out and done before blocks are shared
    assert "nice -n 19 ionice -c3 flock" in body
    assert '"$( [ "$(cache_kind)" = disk ] && echo "$CACHE_DISK" )"' in body   # only on the cache disk


def test_a_cache_entry_list_says_which_kind_of_disk_it_is_on():
    meta = emulate_core.parse_cache_meta("limit\t64\t16766020\t/mnt/wsl/padcache/cardcache\tdisk\n")
    assert meta["kind"] == "disk" and meta["store"] is False and meta["used_kb"] == 16766020


def test_storededupe_takes_a_just_finished_copy():
    sys.path.insert(0, RIG)
    try:
        sd = __import__("storededupe")
    except SystemExit:                                     # no numpy here: the rig's distros have it
        pytest.skip("storededupe needs numpy")
    finally:
        sys.path.remove(RIG)
    import tempfile
    import time
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "fresh.raw")
        with open(p, "wb") as fh:
            fh.truncate(2 << 20)
        assert sd.big_files(d) == []                       # written just now: left alone by default
        assert [x[0] for x in sd.big_files(d, quiet_s=0)] == [p]
        os.utime(p, (time.time() - 3600,) * 2)
        assert [x[0] for x in sd.big_files(d)] == [p]
