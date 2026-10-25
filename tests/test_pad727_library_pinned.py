"""The library stays in the card cache (PAD-727).

David, 2026-10-25, watching a 53-build sweep copy 37 cards off D: five days after the whole library was put in
the store: "Why are we copying so many images over? They should be cached on c". The store's eviction was plain
least-recently-booted, so older versions and custom builds booted on purpose pushed newest builds out. Now an entry
whose image is the library's newest build (directly in the library folder, stamp unchanged) is never evicted - not by
the copier making room, not by the app's 30-day clean-up - and an entry whose image is gone or changed goes first.
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


def _text(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _funcs(*names):
    """The named shell functions out of cardmount.sh, verbatim (each runs from `name() {` to its column-0 `}`)."""
    cm = _text("cardmount.sh")
    out = []
    for n in names:
        m = re.search(r"^%s\(\) \{.*?^\}\n" % re.escape(n), cm, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return "".join(out)


# The driver runs inside one bash (on this machine that is WSL's: nothing in the parent's environment or a Windows
# path crosses into it), makes its own scratch folder, and fakes `df` from the apparent size of what is cached.
DRIVER = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE=$T/cache; CARDS=$T/cards; LIBRARY=$T/lib; CACHE_KEEP_GB=0
mkdir -p "$CACHE" "$CARDS" "$LIBRARY/older versions" "$T/desk"
ln -s "$T/lib" "$T/junction"                  # the repo's images/ junction: the same folder by another name
CAP_KB=$((10 * 1024))
df() { local u=0 f; for f in "$CACHE"/*.raw; do [ -e "$f" ] && u=$((u + $(stat -c %s "$f") / 1024)); done
       echo Avail; echo $((CAP_KB - u)); }
img() { truncate -s "$2" "$1"; touch -d "@$3" "$1"; }
entry() {   # <label> <image> <boot-epoch>: a cached copy of <image>, last booted then
    truncate -s "$(stat -c %s "$2")" "$CACHE/$1.raw"; cache_stamp "$2" > "$CACHE/$1.src"
    : > "$CACHE/$1.boot"; touch -d "@$3" "$CACHE/$1.boot"
}
img "$LIBRARY/new_le-1_10_0.raw" 2M 1000;  entry new_le "$LIBRARY/new_le-1_10_0.raw" 100     # library, booted longest ago
img "$T/junction/new_pro-1_10_0.raw" 2M 1000; entry new_pro "$T/junction/new_pro-1_10_0.raw" 110  # library, by the junction
img "$LIBRARY/older versions/new_le-1_09_0.raw" 2M 900; entry old_le "$LIBRARY/older versions/new_le-1_09_0.raw" 300
img "$T/desk/custom.raw" 2M 800; entry custom "$T/desk/custom.raw" 500; rm "$T/desk/custom.raw"   # image gone
img "$LIBRARY/swapped-1_00_0.raw" 1M 700; entry swapped "$LIBRARY/swapped-1_00_0.raw" 400
touch -d "@701" "$LIBRARY/swapped-1_00_0.raw"                                                  # image changed since
for l in new_le new_pro old_le custom swapped; do cache_pinned $l && echo "pinned $l"; done
img "$T/want.raw" 5M 1                       # 9 MB cached of 10: room for 5 MB needs 4 MB out
cache_make_room "$T/want.raw" "$CACHE/want.raw" 2>&1; echo "rc=$?"
img "$T/big.raw" 7M 1                        # more than everything but the library's 4 MB can free
cache_make_room "$T/big.raw" "$CACHE/big.raw" 2>&1; echo "rc=$?"
ls "$CACHE" | sed -n 's/\.raw$//p' | tr '\n' ' '; echo
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.skipif(sys.platform == "darwin",
                    reason="cardmount.sh is the rig's (WSL/Linux) and speaks GNU stat/touch; macOS has BSD ones")
def test_the_library_is_never_evicted_and_dead_entries_go_first():
    script = _funcs("cache_stamp", "stamp_key", "cache_valid", "copier_alive", "cache_pinned", "label_mounted",
                    "cache_make_room") + DRIVER
    out = subprocess.run(["bash", "-s"], input=script.encode(), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=60).stdout.decode("utf-8", "replace")
    lines = out.splitlines()
    # only the two whose image is a file directly in the library, unchanged - whichever spelling copied it
    assert [l for l in lines if l.startswith("pinned ")] == ["pinned new_le", "pinned new_pro"], out
    ev = [l for l in lines if l.startswith("[card] evicting")]
    # the two dead entries first (gone, changed: equal rank, so in name order), then the older version; never the
    # library, though new_le was booted longest ago
    assert ev == ["[card] evicting cached custom (its image is gone or changed) to make room",
                  "[card] evicting cached swapped (its image is gone or changed) to make room",
                  "[card] evicting cached old_le (least recently booted) to make room"], out
    assert lines[lines.index(ev[-1]) + 1] == "rc=0", out
    assert any("nothing evictable (2 library cards kept) - running off the original" in l for l in lines), out
    assert lines[-2] == "rc=1" and lines[-1].split() == ["new_le", "new_pro"], out


def test_the_store_keeps_a_margin_and_a_distro_disk_its_floor():
    cm = _text("cardmount.sh")
    assert "LIBRARY=${PAD_CARD_LIBRARY:-/mnt/d/Pinball/images/Stern/spike2}" in cm
    # precache.sh fills exactly the folder cardmount.sh pins
    assert "LIB=${1:-/mnt/d/Pinball/images/Stern/spike2}" in _text("precache.sh")
    assert 'if [ "$CACHE" = /mnt/wsl/cards/cardcache ]; then\n    CACHE_KEEP_GB=${PAD_STORE_KEEP_FREE_GB:-2}' in cm
    assert "CACHE_KEEP_GB=${PAD_CACHE_KEEP_FREE_GB:-8}" in cm
    room = cm[cm.index("cache_make_room() {"):cm.index("cache_wait() {")]
    assert "keep=$(( CACHE_KEEP_GB * 1048576 ))" in room
    assert 'if cache_pinned "$vlabel"; then pinned=$((pinned + 1)); continue; fi' in room


def test_cache_list_names_the_library_and_the_clean_up_leaves_it():
    text = ("entry\tnew_le\t5000000\t7600000\t1000\t/mnt/d/Pinball/images/Stern/spike2/new_le.raw\n"
            "pinned\tnew_le\n"
            "entry\told_le\t5000000\t7600000\t1000\t/mnt/d/Pinball/images/Stern/spike2/older versions/old_le.raw\n"
            "disk\t100\t200\n")
    rows, disk = emulate_core.parse_cache_list(text)
    assert {r["label"]: r["pinned"] for r in rows} == {"new_le": True, "old_le": False}
    assert disk == (100, 200)
    # both unbooted for a year: the 30-day rule drops the older version only
    now = 1000 + 365 * 86400
    assert [p["path"] for p in sk.plan_cards(rows, now)] == ["old_le"]
    cm = _text("cardmount.sh")
    lst = cm[cm.index('if [ "${1:-}" = "--cache-list" ]; then'):cm.index('if [ "${1:-}" = "--cache-drop" ]; then')]
    assert "cache_pinned \"$l\" && printf 'pinned\\t%s\\n' \"$l\"" in lst


def test_every_attach_at_logon_tops_the_library_up():
    ps = _text("cardstore.ps1")
    assert "[ValidateSet('create', 'mount', 'fill', 'status', 'task')]" in ps
    mount = ps[ps.index("    'mount' {"):ps.index("    'fill' {")]
    # only after a real attach (an already-mounted store returns first), and never with -NoFill
    assert mount.index('exit 0') < mount.index("if (-not $NoFill) { & $PSCommandPath fill")
    fill = ps[ps.index("    'fill' {"):ps.index("    'task' {")]
    assert "Start-Process -WindowStyle Hidden -FilePath 'wsl.exe'" in fill and "'-u', 'root'" in fill
    assert "/precache.sh' > $log 2>&1" in fill
    # status says how much of the library is held
    assert "/cardmount.sh' --cache-list\" | Where-Object { $_ -like \"pinned`t*\" }" in ps
    assert 'Say "  library: $held of $all newest builds held, never evicted"' in ps
