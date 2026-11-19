"""The PAD storage on C: stops running away (PAD-1453).

David, 2026-11-19: "our pad storage on disk c has gotten way out of control... using over 500GB is insane here."
The card store's file was 550 GB on C:; its cache had no size cap (103 GB, nearly all ticket scratch); and of the
431 GiB it held, only 189 GiB was unique 4 KiB blocks (LE/Pro pairs, custom builds of stock cards).

Now: the store's cache has a cap (25 GB); a prune evicts down to it; an entry whose image was deleted from a folder of
the user's own is the LAST COPY and nothing automatic takes it; the store is XFS and storededupe.py shares identical
blocks between files; pytest keeps only a failed test's tmp_path.
"""
import configparser
import os
import re
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH
from pinball_decryptor.core import space_keeper as sk
from pinball_decryptor.webui import emulate_core

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
NOW = 1_800_000_000
DAY = 86400


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


def _bash(script):
    return subprocess.run(["bash", "-s"], input=script.encode(), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=120).stdout.decode("utf-8", "replace")


needs_bash = pytest.mark.skipif(not HAS_BASH or sys.platform == "darwin",
                                reason="cardmount.sh is the rig's (WSL/Linux) and speaks GNU stat/touch")


@needs_bash
def test_scratch_folders_and_folders_of_your_own_are_told_apart():
    out = _bash(_funcs("src_is_scratch") + r"""
for p in /mnt/c/tmp/PAD-1235/A.raw /tmp/pad1279_e2e/empty.img /var/tmp/x/y.raw \
         /mnt/c/Users/u/AppData/Local/Temp/pytest-of-u/p/w.raw /mnt/d/tmp/pad_cardstage_1442/g.raw \
         "/mnt/c/Users/u/OneDrive/Desktop/HEISEI/build/v36.raw" /mnt/d/Pinball/images/Stern/spike2/x.raw \
         /home/u/cards/mine.raw; do
  if src_is_scratch "$p"; then echo "scratch $p"; else echo "own $p"; fi
done
""")
    lines = out.splitlines()
    assert lines[:5] == ["scratch /mnt/c/tmp/PAD-1235/A.raw", "scratch /tmp/pad1279_e2e/empty.img",
                         "scratch /var/tmp/x/y.raw",
                         "scratch /mnt/c/Users/u/AppData/Local/Temp/pytest-of-u/p/w.raw",
                         "scratch /mnt/d/tmp/pad_cardstage_1442/g.raw"], out
    assert lines[5:] == ["own /mnt/c/Users/u/OneDrive/Desktop/HEISEI/build/v36.raw",
                         "own /mnt/d/Pinball/images/Stern/spike2/x.raw", "own /home/u/cards/mine.raw"], out


# Sizes scaled as test_pad739: each 1 MiB entry counts as 1 GB, the cap is 3 GB. src_is_scratch is replaced so the
# "desk" folder (under mktemp, which is scratch by path) reads as a folder of the user's own.
PRUNE = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE=$T/cache; CARDS=$T/cards; LIBRARY=$T/nolib; CACHE_KEEP_GB=0; PAD_CARD_COPY_USED=0; SELF=$T
df() { echo Avail; echo 1073741824; }
mkdir -p "$CACHE" "$CARDS" "$T/img" "$T/desk"
src_is_scratch() { case $1 in "$T"/desk/*) return 1 ;; esac; return 0; }
cache_used_kb() { local u=0 f; for f in "$CACHE"/*.raw "$CACHE"/*.raw.partial; do
                  [ -e "$f" ] && u=$((u + $(stat -c %s "$f"))); done; echo $u; }
now=$(date +%s)
entry() {   # <label> <image> <days since boot>
    truncate -s 1M "$1"; touch -d "@$((now - 3 * 86400))" "$1"
    truncate -s 1M "$CACHE/$2.raw"; cache_stamp "$1" > "$CACHE/$2.src"
    : > "$CACHE/$2.boot"; touch -d "@$((now - $3 * 86400))" "$CACHE/$2.boot"
}
entry "$T/img/a.raw" a 9; entry "$T/img/b.raw" b 5; entry "$T/img/c.raw" c 1; entry "$T/img/d.raw" d 0
entry "$T/desk/v36.raw" v36 20; rm "$T/desk/v36.raw"            # deleted from the user's own folder: the last copy
entry "$T/img/tkt.raw" tkt 2; rm "$T/img/tkt.raw"                # deleted from scratch: gone, can go
echo 3 > "$CACHE/.limit_gb"
echo "v36=$(cache_source_state v36) tkt=$(cache_source_state tkt)"
DRY=1 cache_prune 30 >/dev/null
echo "after dry: $(ls "$CACHE" | sed -n 's/\.raw$//p' | sort | tr '\n' ' ')"
DRY=0 cache_prune 30
echo "left: $(ls "$CACHE" | sed -n 's/\.raw$//p' | sort | tr '\n' ' ')"
DRY=1; cache_make_room "" ""; echo "room rc=$? evict=$ROOM_EVICT_N"
"""


@needs_bash
def test_prune_keeps_the_last_copy_and_evicts_down_to_the_cap_least_recently_booted_first():
    script = _funcs("cache_stamp", "stamp_key", "cache_valid", "copier_alive", "cache_pinned", "label_mounted",
                    "cache_readers", "cache_in_use", "src_drive_present", "cache_source_state", "cache_limit_gb",
                    "card_label", "cache_need_kb", "room_say", "cache_settle", "cache_kind", "cache_make_room", "cache_prune") + PRUNE
    out = _bash(script)
    lines = out.splitlines()
    assert "v36=lost tkt=gone" in lines, out
    assert any(l.startswith("kept\tlast copy: its image was deleted from a folder of your own") and "\tv36\t" in l
               for l in lines), out
    # 6 held (v36 counts toward the cap but can never go), cap 3: the oldest boots go until under it
    taken = [l.split("\t")[2] for l in lines if l.startswith("prune\t")]
    assert taken == ["a", "b", "tkt"], out
    assert all("over the cache's 3 GB limit, least recently booted" in l for l in lines if l.startswith("prune\t")), out
    assert "after dry: a b c d tkt v36 " in lines, out                  # a dry run takes nothing
    assert "left: c d v36 " in lines, out
    # the copier making room never takes the last copy either
    assert "room rc=0 evict=0" in lines or "room rc=1 evict=0" in lines, out


def test_the_app_never_offers_or_takes_a_last_copy():
    lost = {"label": "v36", "source": "lost", "pinned": False, "use": "", "leftover": False,
            "boot": NOW - 90 * DAY, "copied": 0, "real_kb": 9_000_000}
    gone = dict(lost, label="tkt", source="gone")
    assert emulate_core.cache_unused(lost, NOW) == ""
    assert emulate_core.cache_unused(gone, NOW) == "its image was deleted or renamed"
    assert [p["path"] for p in sk.plan_cards([lost, gone], NOW)] == ["tkt"]
    rows, _disk = emulate_core.parse_cache_list(
        "entry\tv36\t9000000\t15000000\t%d\t/mnt/c/Users/u/Desktop/v36.raw\n"
        "state\tv36\tlost\t-\t%d\n" % (NOW - 90 * DAY, NOW - 90 * DAY))
    assert rows[0]["source"] == "lost"


def test_the_store_cache_has_a_default_cap():
    cm = _text("cardmount.sh")
    assert 'echo "${PAD_STORE_CACHE_MAX_GB:-25}"' in cm


def test_pytest_keeps_only_failed_tests_tmp_paths():
    cp = configparser.ConfigParser()
    cp.read(os.path.join(ROOT, "pytest.ini"))
    assert cp["pytest"]["tmp_path_retention_policy"] == "failed"


# ------------------------------------------------------------------ storededupe.py
np = pytest.importorskip("numpy")
sys.path.insert(0, RIG)
import storededupe as sd  # noqa: E402


def test_runs_coalesce_only_what_is_consecutive_on_both_sides_and_cap_at_16_mib():
    dst = np.array([10, 11, 12, 20, 21, 30], np.uint64)
    fid = np.array([0, 0, 0, 0, 1, 1], np.int64)
    src = np.array([5, 6, 7, 9, 3, 4], np.int64)
    assert sd._runs(dst, fid, src) == [(0, 5, 10, 3), (0, 9, 20, 1), (1, 3, 21, 1), (1, 4, 30, 1)]
    n = sd.MAX_RUN + 5
    big = sd._runs(np.arange(n, dtype=np.uint64), np.zeros(n, np.int64), np.arange(100, 100 + n, dtype=np.int64))
    assert big == [(0, 100, 0, sd.MAX_RUN), (0, 100 + sd.MAX_RUN, sd.MAX_RUN, 5)]


def test_the_index_finds_blocks_seen_before_and_nothing_else():
    idx = sd.Index()
    assert (idx.lookup(np.array([1, 2], np.uint64)) == -1).all()
    idx.add(0, np.array([7, 3], np.uint64), np.array([1, 2], np.uint64))
    idx.add(1, np.array([5], np.uint64), np.array([9], np.uint64))
    got = idx.lookup(np.array([3, 4, 5, 8], np.uint64))
    assert got.tolist() == [2, -1, (1 << 40) | 9, -1]


@pytest.mark.skipif(not hasattr(os, "SEEK_DATA"), reason="SEEK_DATA/SEEK_HOLE: Linux")
def test_a_dry_pass_finds_a_pro_inside_its_le_and_skips_holes_and_zeros(tmp_path):
    rng = np.random.default_rng(1)
    blocks = rng.integers(0, 255, size=(64, sd.BLK), dtype=np.uint8)
    le = blocks.copy()
    pro = blocks.copy()
    pro[10:12] = rng.integers(0, 255, size=(2, sd.BLK), dtype=np.uint8)     # two blocks differ
    pro[40:44] = 0                                                         # zeros are never "shared"
    (tmp_path / "le.raw").write_bytes(le.tobytes())
    (tmp_path / "pro.raw").write_bytes(pro.tobytes())
    d = sd.Deduper(sd.HashCache(None), dry=True)
    assert d.take(str(tmp_path / "le.raw")) == 0
    assert d.take(str(tmp_path / "pro.raw")) == (64 - 2 - 4) * sd.BLK


@pytest.mark.skipif(not hasattr(os, "SEEK_DATA"), reason="SEEK_DATA/SEEK_HOLE + fallocate: Linux")
def test_zero_blocks_become_holes_and_the_file_reads_and_dates_the_same(tmp_path):
    # the copy wrote a card's zero runs as real blocks and XFS preallocated past every write (Jaws Pro: 7.4 GiB of
    # data in 11.6 GiB of blocks); punch_zeros gives them back without changing a byte or the mtime
    rng = np.random.default_rng(2)
    data = rng.integers(1, 255, size=(32, sd.BLK), dtype=np.uint8)
    data[8:20] = 0
    f = tmp_path / "card.raw"
    f.write_bytes(data.tobytes())
    os.utime(f, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    before = f.stat()
    punched = sd.punch_zeros(str(f))
    after = f.stat()
    assert f.read_bytes() == data.tobytes()
    assert after.st_mtime_ns == before.st_mtime_ns and after.st_size == before.st_size
    if punched:                     # a filesystem without hole punching (some CI tmp) punches nothing, harmlessly
        assert punched == 12 * sd.BLK
        assert after.st_blocks < before.st_blocks


@pytest.mark.skipif(not hasattr(os, "SEEK_DATA") or not hasattr(os, "symlink"), reason="Linux")
def test_links_to_folders_are_copied_and_verified_as_links(tmp_path, monkeypatch):
    # os.walk lists a link to a folder among the folders: the first copy left out 191 of Spike 3's
    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "games" / "pad" / "img0" / "data").mkdir(parents=True)
    (src / "games" / "pad" / "img0" / "data" / "a.bin").write_bytes(b"x" * 100)
    os.symlink("pad/img0/data", str(src / "games" / "data"))            # to a folder
    os.symlink("data/a.bin", str(src / "games" / "pad" / "img0" / "a"))  # to a file
    dst.mkdir()
    monkeypatch.setattr(sd, "_cache_dir", lambda _r: str(tmp_path / "cache"))
    # a copy without the folder link: verify says so
    os.makedirs(str(dst / "games" / "pad" / "img0" / "data"))
    (dst / "games" / "pad" / "img0" / "data" / "a.bin").write_bytes(b"x" * 100)
    os.symlink("data/a.bin", str(dst / "games" / "pad" / "img0" / "a"))
    assert sd.cmd_verify(str(src), str(dst)) == 1
    # the copy now brings it, as a link
    assert sd.cmd_ingest(str(src), str(dst)) == 0
    assert os.path.islink(str(dst / "games" / "data")) and os.readlink(str(dst / "games" / "data")) == "pad/img0/data"
    assert sd.cmd_verify(str(src), str(dst)) == 0


def test_the_copy_sets_the_size_before_writing():
    src = _text("storededupe.py")
    body = src[src.index("def _copy_sparse"):src.index("def cmd_ingest")]
    assert body.index("os.ftruncate(dfd, size)") < body.index("os.pwrite")
    ingest = src[src.index("def cmd_ingest"):src.index("def cmd_dezero")]
    after = ingest[ingest.index("_copy_sparse(s, t, sync=st.st_size >= MIN_FILE)"):]
    assert "_syncfs(dst)" in ingest                   # small files skip their own fsync: the store is flushed once
    assert after.index("punch_zeros(t)") < after.index("_copy_meta(s, t, st)")


def test_the_weekly_compaction_only_runs_idle_and_fails_closed():
    ps = _text("padcompact.ps1")
    # due weekly, only disks holding 20 GB more than they use
    assert "[int] $MinSlackGB = 20" in ps and "[int] $EveryDays = 7" in ps
    # busy = a fresh rig lease, a ticket's process, an emulator, a card mount, anything on the shared disks
    assert "AddMinutes(-10)" in ps and "PAD_TICKET=" in ps and "*qemu*|*fuse2fs*" in ps and "'^/mnt/wsl/'" in ps
    # a scan that did not finish is a reason NOT to shut WSL down
    assert "if (-not ($out -contains 'SCAN_DONE'))" in ps
    # -e: with -- an outer shell expanded the scan's $vars to nothing and every check passed
    assert "-u root -e bash -c" in ps and "-u root -- bash" not in ps
    body = ps[ps.index("# ---- compact"):]
    assert body.index("fstrim -av") < body.index("wsl.exe --shutdown") < body.index("compact vdisk") \
        < body.index("cardstore.ps1")


def test_the_store_script_moves_the_store_by_verify_then_swap():
    ps = _text("cardstore.ps1")
    swap = ps[ps.index("    'swap' {"):ps.index("    'task' {")]
    # nothing on the store, the changes caught up, every byte compared, and only then the files swapped
    assert swap.index("storexfs.sh' busy") < swap.index("ingest --delete") < swap.index('verify $MountPoint $NewMount') \
        < swap.index("Move-Item $Path $OldPath")
    assert 'throw "verify failed: the old store stays in place"' in swap
    migrate = ps[ps.index("    'migrate' {"):ps.index("    'swap' {")]
    assert "storexfs.sh' mkfs" in migrate and "'xfs' | Set-Content \"$NewPath.fstype\"" in migrate
    assert "ingest --host $hostMnt $MountPoint $NewMount" in migrate
    sx = _text("storexfs.sh")
    assert '-m reflink=1,crc=1 -L "${3:-cards}"' in sx and "apt-get download" in sx and "dpkg-deb -x" in sx
