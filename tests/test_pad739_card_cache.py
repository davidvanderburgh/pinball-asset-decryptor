"""The Spike 2 card cache stops growing for ever (PAD-739).

A user's ~/cardcache in Ubuntu reached 150 GB over a month - 25 custom Godzilla builds, 6-15 GB each - and the distro
disk 226 GB on C:. cardmount.sh evicted only when `df` said the cache's disk was nearly full, and on a distro's own
disk `df` reports the virtual size of its ext4.vhdx (up to 1 TB), so nothing was ever evicted. The app's 30-day
clean-up kept every card booted in the last month, every card never booted, every copy that never finished (not
even listed) and every copy of an image rebuilt since (never usable again).

Now: the cache keeps under a limit of its own (64 GB on a distro disk unless the user picks another in the Cache
window), takes unfinished copies and dead entries first, never a card any rig slot has mounted, and the window shows
each card's image state and use and selects what will not be missed.
"""
import os
import re
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH
from pinball_decryptor.core import space_keeper as sk
from pinball_decryptor.webui import emulate_core

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")
DAY = 86400
NOW = 1_800_000_000


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


# A distro disk: df says 1 TB free whatever the cache holds - the condition under which nothing was ever evicted.
# Sizes are scaled: each 1 MiB file counts as 1 GB (cache_used_kb is replaced to say so), and the limit is 2 GB.
DRIVER = r"""
set -u
T=$(mktemp -d); trap 'kill $HOLD 2>/dev/null; rm -rf "$T"' EXIT
CACHE=$T/cache; CARDS=$T/cards; LIBRARY=$T/nolib; CACHE_KEEP_GB=8
mkdir -p "$CACHE" "$CARDS" "$T/img" "$T/desk"
df() { echo Avail; echo 1073741824; }
cache_used_kb() { local u=0 f; for f in "$CACHE"/*.raw "$CACHE"/*.raw.partial; do
                  [ -e "$f" ] && u=$((u + $(stat -c %s "$f"))); done; echo $u; }
img() { truncate -s 1M "$1"; touch -d "@$2" "$1"; }
entry() {   # <label> <image> <boot-epoch or 0>
    truncate -s 1M "$CACHE/$1.raw"; cache_stamp "$2" > "$CACHE/$1.src"
    [ "$3" = 0 ] || { : > "$CACHE/$1.boot"; touch -d "@$3" "$CACHE/$1.boot"; }
}
img "$T/img/old.raw" 10;    entry old "$T/img/old.raw" 100
img "$T/img/inuse.raw" 10;  entry inuse "$T/img/inuse.raw" 50          # booted longest ago - but mounted
img "$T/img/recent.raw" 10; entry recent "$T/img/recent.raw" 900
img "$T/desk/custom.raw" 10; entry custom "$T/desk/custom.raw" 950
touch -d "@20" "$T/desk/custom.raw"                                      # rebuilt since: never used again
img "$T/img/gone.raw" 10;   entry gone "$T/img/gone.raw" 940; rm "$T/img/gone.raw"
truncate -s 1M "$CACHE/half.raw.partial"; echo x > "$CACHE/half.log"    # a copy that never finished
# a reader of the copy, as fuse2fs is in another rig slot: its argv names the copy, nothing is under $CARDS
bash -c 'sleep 60; :' _ "$CACHE/inuse.raw" & HOLD=$!
sleep 0.5
for l in old inuse recent custom gone; do echo "state $l $(cache_source_state $l)"; done
cache_in_use inuse && echo "inuse is in use"
cache_in_use old || echo "old is free"
echo 2 > "$CACHE/.limit_gb"; echo "limit $(cache_limit_gb)"
cache_make_room "" "" 2>&1; echo "rc=$?"
ls "$CACHE" | sed -n 's/\.raw$//p; s/\.raw\.partial$/ (partial)/p' | sort | tr '\n' ' '; echo
rm "$CACHE/.limit_gb"; echo "default $(cache_limit_gb)"
CACHE=/mnt/wsl/cards/cardcache; echo "store $(cache_limit_gb)"
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.skipif(sys.platform == "darwin",
                    reason="cardmount.sh is the rig's (WSL/Linux) and speaks GNU stat/touch; macOS has BSD ones")
def test_the_cache_keeps_under_its_limit_dead_first_never_one_in_use():
    script = _funcs("cache_stamp", "stamp_key", "cache_valid", "copier_alive", "cache_pinned", "label_mounted",
                    "cache_readers", "cache_in_use", "cache_source_state", "cache_limit_gb",
                    "cache_make_room") + DRIVER
    out = subprocess.run(["bash", "-s"], input=script.encode(), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=120).stdout.decode("utf-8", "replace")
    lines = out.splitlines()
    assert "state old ok" in lines and "state custom changed" in lines, out
    assert "state gone gone" in lines, out
    assert "inuse is in use" in lines and "old is free" in lines, out
    assert "limit 2" in lines, out
    ev = [l for l in lines if l.startswith("[card] evicting")]
    # 6 "GB" held, 2 allowed: the unfinished copy, then the two dead entries, then the oldest boot that is not in use
    assert ev == [
        "[card] evicting cached half (a copy that never finished) to keep the cache under its 2 GB limit",
        "[card] evicting cached custom (its image is gone or changed) to keep the cache under its 2 GB limit",
        "[card] evicting cached gone (its image is gone or changed) to keep the cache under its 2 GB limit",
        "[card] evicting cached old (least recently booted) to keep the cache under its 2 GB limit",
    ], out
    assert "rc=0" in lines, out
    assert "inuse recent " in lines, out            # the mounted one stays though it was booted longest ago
    assert "default 64" in lines and "store 0" in lines, out


def test_the_limit_and_the_drop_guard_in_the_script():
    cm = _text("cardmount.sh")
    drop = cm[cm.index('if [ "${1:-}" = "--cache-drop" ]; then'):cm.index('if [ "${1:-}" = "--cache-limit" ]; then')]
    # any rig slot's mount refuses the drop, not only this slot's, and a label cannot leave the folder
    assert 'cache_in_use "$l" && die' in drop
    assert "*/*|.|..) die" in drop
    # a file that stayed is reported, so the window does not count it as freed
    assert 'die "could not delete' in drop
    lim = cm[cm.index('if [ "${1:-}" = "--cache-limit" ]; then'):cm.index("IMG=${1:-}\n")]
    assert 'cache_make_room "" ""' in lim
    lst = cm[cm.index('if [ "${1:-}" = "--cache-list" ]; then'):cm.index('if [ "${1:-}" = "--cache-drop" ]; then')]
    assert "CACHE_READERS=$(cache_readers)" in lst          # one /proc pass for the whole list


# ------------------------------------------------------------------ the list
_LIST = (
    "entry\tgz_v1\t9437184\t15000000\t%d\t/mnt/c/Users/u/Desktop/gz v1.raw\n"
    "state\tgz_v1\tchanged\t-\t%d\n"
    "entry\tgz_v2\t9437184\t15000000\t0\t/mnt/c/Users/u/Desktop/gz v2.raw\n"
    "state\tgz_v2\tok\t-\t%d\n"
    "entry\tkk\t15000000\t15000000\t%d\t/mnt/e/kk.raw\n"
    "state\tkk\tunreachable\tmounted\t%d\n"
    "leftover\thalf\t600000\t%d\t-\n"
    "limit\t64\t34474368\t/home/u/cardcache\tdistro\n"
    "disk\t900000000\t1000000000\n"
) % (NOW - 2 * DAY, NOW - 9 * DAY, NOW - 40 * DAY, NOW - 50 * DAY, NOW - 60 * DAY, NOW - 3 * DAY)


def test_the_list_carries_image_state_use_and_unfinished_copies():
    rows, disk = emulate_core.parse_cache_list(_LIST)
    by = {r["label"]: r for r in rows}
    assert by["gz_v1"]["source"] == "changed" and by["gz_v1"]["use"] == ""
    assert by["gz_v2"]["boot"] == 0 and by["gz_v2"]["copied"] == NOW - 40 * DAY
    assert by["kk"]["use"] == "mounted" and by["kk"]["source"] == "unreachable"
    assert by["half"]["leftover"] is True and by["half"]["real_kb"] == 600000
    assert disk == (900000000, 1000000000)
    assert emulate_core.parse_cache_meta(_LIST) == {
        "limit_gb": 64, "used_kb": 34474368, "dir": "/home/u/cardcache", "store": False}
    # an older rig's list: no state lines, no limit - read as before
    old, _ = emulate_core.parse_cache_list("entry\ta\t1\t1\t0\t/x.raw\n")
    assert old[0]["source"] == "" and old[0]["use"] == "" and old[0]["leftover"] is False
    assert emulate_core.parse_cache_meta("entry\ta\t1\t1\t0\t/x.raw\n") is None


def test_select_unused_never_takes_one_in_use_or_the_library():
    rows, _ = emulate_core.parse_cache_list(_LIST)
    why = {r["label"]: emulate_core.cache_unused(r, NOW) for r in rows}
    assert why["gz_v1"].startswith("its image was rebuilt")
    assert why["gz_v2"] == "not used for 30 days"         # never booted: dated by its copy, 40 days old
    assert why["kk"] == ""                                # mounted by a running emulator
    assert why["half"] == "a copy that never finished"
    lib = {"label": "lib", "real_kb": 1, "boot": NOW - 400 * DAY, "pinned": True, "source": "ok"}
    assert emulate_core.cache_unused(lib, NOW) == ""
    assert emulate_core.cache_last_used({"boot": 0, "copied": 7}) == 7


def test_the_automatic_clean_up_takes_dead_and_unfinished_copies():
    rows, _ = emulate_core.parse_cache_list(_LIST)
    rows.append({"label": "deleted", "real_kb": 5, "boot": NOW - 3 * DAY, "source": "gone", "use": "",
                 "copied": NOW - 3 * DAY, "leftover": False})
    rows.append({"label": "fresh_half", "real_kb": 5, "boot": 0, "source": "", "use": "copying",
                 "copied": NOW - 3 * DAY, "leftover": True})
    plan = {p["path"]: p["why"] for p in sk.plan_cards(rows, NOW)}
    # rebuilt since: at once; never booted and copied 40 days ago: unused; an unfinished copy a day old: leftover;
    # never one in use or still copying; an image deleted 3 days ago keeps its copy (it may be the only one left)
    assert plan == {"gz_v1": "dead", "gz_v2": "unused", "half": "leftover"}
