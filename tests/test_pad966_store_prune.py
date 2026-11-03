"""The card store is pruned to what a boot can use, and a card already on it boots where it lies (PAD-966).

David, 2026-11-03: "compact them as much as possible ... ideally we should not be caching the whole raw sd card,
only what is necessary. even more ideally, not duplicating bytes from the raw sd card at all". Measured first: every
copy in the store was already at cardcopy.py's used-block floor, so the 548 GB were in WHAT was kept - 173 GB of
library and 375 GB no boot could use. Thirty of those were copies stamped against THEMSELVES: ~/cardcache is a
symlink to the store, and on 2026-10-29 those copies were booted as cards by that path, so cardmount.sh copied each
onto itself and re-stamped it with its own size+mtime. Now such an image is booted where it lies (no copy, no
re-stamp), such an entry reads as dead, and --cache-prune takes the dead and the stale in one pass.
"""
import os
import re
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH

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


FUNCS = ("cache_stamp", "stamp_key", "cache_valid", "copier_alive", "cache_pinned", "label_mounted",
         "cache_readers", "cache_in_use", "cache_source_state", "on_cache_disk", "cache_prune")

# One bash (WSL's on this machine), its own scratch folder: a cache with a library entry, one stamped against
# itself, an older version, a fresh custom build, one a run holds, and a copy that never finished.
SETUP = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE=$T/cache; CARDS=$T/cards; LIBRARY=$T/lib
mkdir -p "$CACHE" "$CARDS" "$LIBRARY/older versions" "$T/desk"
cache_kind() { echo "${KIND:-distro}"; }
NOW=$(date +%s)
img() { truncate -s "$2" "$1"; touch -d "@$3" "$1"; }
entry() {   # <label> <image> <days since the last boot>
    truncate -s "$(stat -c %s "$2")" "$CACHE/$1.raw"; cache_stamp "$2" > "$CACHE/$1.src"
    : > "$CACHE/$1.boot"; touch -d "@$((NOW - $3 * 86400))" "$CACHE/$1.boot"
}
img "$LIBRARY/new_le-1_10_0.raw" 2M 1000;  entry new_le "$LIBRARY/new_le-1_10_0.raw" 400       # the library's
img "$LIBRARY/older versions/new_le-1_09_0.raw" 2M 900; entry old_le "$LIBRARY/older versions/new_le-1_09_0.raw" 40
img "$T/desk/custom.raw" 2M 800; entry custom "$T/desk/custom.raw" 2                             # booted this week
img "$T/desk/live.raw" 2M 700; entry live "$T/desk/live.raw" 90
truncate -s 2M "$CACHE/self.raw"; touch -d "@$((NOW - 5 * 86400))" "$CACHE/self.raw"
cache_stamp "$CACHE/self.raw" > "$CACHE/self.src"                                                # stamped against itself
truncate -s 1M "$CACHE/half.raw.partial"; : > "$CACHE/half.src"                                  # never finished
cache_readers() { echo "$CACHE/live.raw"; }                                                      # a run reads live
"""


def _run(script):
    out = subprocess.run(["bash", "-s"], input=script.encode(), stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, timeout=60).stdout.decode("utf-8", "replace")
    return out.splitlines()


linux_bash = pytest.mark.skipif(not HAS_BASH or sys.platform == "darwin",
                                reason="cardmount.sh is the rig's (WSL/Linux) and speaks GNU stat/touch")


@linux_bash
def test_a_copy_stamped_against_itself_is_dead_and_an_image_on_the_store_boots_in_place():
    lines = _run(_funcs(*FUNCS) + SETUP + r"""
echo "self=$(cache_source_state self) new_le=$(cache_source_state new_le) old_le=$(cache_source_state old_le)"
on_cache_disk "$CACHE/self.raw" && echo "in cache: in place"
on_cache_disk "$LIBRARY/new_le-1_10_0.raw" || echo "distro disk: library image is copied"
KIND=store on_cache_disk "$LIBRARY/new_le-1_10_0.raw" && echo "store disk: library image in place"
on_cache_disk "$T/nowhere.raw" || echo "missing image: not in place"
""")
    assert "self=changed new_le=ok old_le=ok" in lines
    assert "in cache: in place" in lines
    assert "distro disk: library image is copied" in lines
    assert "store disk: library image in place" in lines
    assert "missing image: not in place" in lines


@linux_bash
def test_the_prune_takes_the_dead_and_the_stale_and_keeps_the_library_and_the_live():
    lines = _run(_funcs(*FUNCS) + SETUP + r"""
echo "--- dry 30"; DRY=1 cache_prune 30
ls "$CACHE" | sed -n 's/\.raw$//p' | tr '\n' ' '; echo
echo "--- 30"; DRY=0 cache_prune 30
ls "$CACHE" | sed -n 's/\.raw$//p' | tr '\n' ' '; echo
ls "$CACHE"/half* 2>/dev/null | wc -l
echo "--- 0"; cache_prune 0
ls "$CACHE" | sed -n 's/\.raw$//p' | tr '\n' ' '; echo
""")
    text = "\n".join(lines)
    dry, thirty, zero = text.split("--- dry 30")[1].split("--- 30")[0], text.split("--- 30")[1].split("--- 0")[0], \
        text.split("--- 0")[1]
    # the dry run names the same takes and leaves every file where it was
    assert re.search(r"^prune\tdead: .*\tself\t", dry, re.M)
    assert re.search(r"^prune\tnot booted in 30 days \(ok\)\told_le\t", dry, re.M)
    assert re.search(r"^prune\tunfinished copy\thalf\t", dry, re.M)
    assert re.search(r"^kept\tpinned\tnew_le\t", dry, re.M)
    assert re.search(r"^kept\tin use\tlive\t", dry, re.M)
    assert re.search(r"^kept\tbooted 2 days ago\tcustom\t", dry, re.M)
    assert re.search(r"^pruned\t3\t\d+\t3\t\d+$", dry, re.M)
    assert "custom live new_le old_le self" in dry
    # the real run takes them: the library's, the one in use and this week's stay; the half copy's sidecar goes too
    assert "custom live new_le" in thirty and "old_le" not in thirty.split("pruned")[1] and "self" not in \
        thirty.split("pruned")[1]
    assert "\n0\n" in thirty or thirty.strip().endswith("0")
    # keep 0: only the library's and the live stay
    assert re.search(r"^prune\tnot the library's \(ok\)\tcustom\t", zero, re.M)
    assert zero.strip().endswith("live new_le")


def test_the_modes_the_fill_and_the_store_script_know_the_prune_and_the_in_place_boot():
    cm = _text("cardmount.sh")
    assert '"--cache-prune"' in cm and "--keep-days" in cm and "--dry" in cm
    # a boot never copies an image that already lives on the store, and the space check says so (nothing to copy)
    pick = cm[cm.index("cache_pick() {"):]
    assert pick.index('on_cache_disk "$img"') < pick.index('cache_valid "$img" "$copy" "$stamp"')
    check = cm[cm.index("cache_check() {"):cm.index("cache_kind() {")]
    assert 'on_cache_disk "$img"' in check and "need=0" in check
    pre = _text("precache.sh")
    assert "in the library  $name" in pre
    ps = _text("cardstore.ps1")
    assert "'prune'" in ps and "--cache-prune --keep-days $KeepDays" in ps and "fill -Path" in ps


# --------------------------------------------------------------------- the library lives on the store, once
@linux_bash
def test_a_raw_in_the_intake_folder_boots_from_its_library_copy():
    """David: "I want to be storing ONE copy of a disk image". The library is /mnt/wsl/cards/library; the raw it
    was taken from (same name, same size+mtime) is booted from the library file by whatever path names it."""
    lines = _run(_funcs("cache_stamp", "stamp_key", "on_cache_disk", "library_copy", "cache_pick") + r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE=$T/cache; STORE_LIBRARY=$T/lib; LIBRARY=$T/lib
mkdir -p "$CACHE" "$T/lib" "$T/intake"
cache_kind() { echo distro; }    # here intake and library share one device; on David's PC the intake is D:
truncate -s 2M "$T/intake/gz-1_16_0.Release.8G.sdcard.raw"; touch -d @1000 "$T/intake/gz-1_16_0.Release.8G.sdcard.raw"
truncate -s 2M "$T/lib/gz-1_16_0.Release.8G.sdcard.raw";    touch -d @1000 "$T/lib/gz-1_16_0.Release.8G.sdcard.raw"
truncate -s 2M "$T/intake/new.raw"; touch -d @2000 "$T/intake/new.raw"
truncate -s 2M "$T/lib/new.raw";    touch -d @1500 "$T/lib/new.raw"                 # rebuilt since: a new identity
echo "taken: $(library_copy "$T/intake/gz-1_16_0.Release.8G.sdcard.raw")"
library_copy "$T/intake/new.raw" || echo "rebuilt: no library copy"
library_copy "$T/lib/new.raw" || echo "the library file itself: not a copy of itself"
LIBRARY=$T/intake library_copy "$T/intake/gz-1_16_0.Release.8G.sdcard.raw" || echo "no store library: nothing"
echo "pick: $(cache_pick "$T/intake/gz-1_16_0.Release.8G.sdcard.raw" gz-1_16_0 2>&1 | tr '\n' ' ')"
""")
    T = [l for l in lines if l.startswith("taken: ")][0][len("taken: "):].rsplit("/lib/", 1)[0]
    assert "taken: %s/lib/gz-1_16_0.Release.8G.sdcard.raw" % T in lines
    assert "rebuilt: no library copy" in lines
    assert "the library file itself: not a copy of itself" in lines
    assert "no store library: nothing" in lines
    assert ("pick: [card] gz-1_16_0.Release.8G.sdcard.raw is in the card library - booting it from there "
            "%s/lib/gz-1_16_0.Release.8G.sdcard.raw " % T) in lines


def test_the_library_is_the_store_the_intake_is_taken_in_and_every_gate_knows_the_new_place():
    cm = _text("cardmount.sh")
    assert "STORE_LIBRARY=/mnt/wsl/cards/library" in cm
    assert 'INTAKE=${PAD_CARD_INTAKE:-/mnt/d/Pinball/images/Stern/spike2}' in cm
    assert 'elif [ "$CACHE" = /mnt/wsl/cards/cardcache ] && [ -d "$STORE_LIBRARY" ]; then\n    LIBRARY=$STORE_LIBRARY' in cm
    check = cm[cm.index("cache_check() {"):cm.index("cache_kind() {")]
    assert 'on_cache_disk "$img" || library_copy "$img" >/dev/null' in check
    # the intake: a valid cache copy of the card is MOVED into the library, anything else copied compact, with the
    # original's mtime, and the store-less machine keeps the old cache fill
    pre = _text("precache.sh")
    assert "DEST=/mnt/wsl/cards/library" in pre
    assert 'mv "$CACHE/$label.raw" "$dest.partial"' in pre
    assert 'touch -r "$card" "$dest.partial"' in pre
    assert 'bash "$RIG/cardmount.sh" "$card" --cache-now' in pre
    # rigbatch's stager leaves a card on the store's disk alone and names a library boot for what it is
    st = _text("cardstage.sh")
    assert '/mnt/wsl/*) echo "$card" > "$S/$i"; continue ;;' in st
    assert "/mnt/wsl/cards/library/*)" in st
    # nothing may build INTO the library, by either spelling
    from pinball_decryptor.webui import multiboot_core
    sys.path.insert(0, RIG)
    try:
        import mkmulticard, selectmedia       # noqa: E401
    finally:
        sys.path.pop(0)
    for lst in (multiboot_core.LIBRARY_PREFIXES, mkmulticard.FORBIDDEN_OUTPUT_PREFIXES,
                selectmedia.FORBIDDEN_OUTPUT_PREFIXES):
        assert "/mnt/wsl/cards/library" in lst
    for p in (r"\\wsl.localhost\Ubuntu\mnt\wsl\cards\library\x.raw", r"\\wsl$\PAD-Runtime\mnt\wsl\cards\library",
              "//wsl.localhost/Ubuntu/mnt/wsl/cards/library/sub/x.raw"):
        assert multiboot_core.under_library(p, resolve=False), p
        assert multiboot_core.under_library(p), p
    assert not multiboot_core.under_library(r"\\wsl.localhost\Ubuntu\mnt\wsl\cards\cardcache\x.raw", resolve=False)
    assert not multiboot_core.under_library(r"\\wsl.localhost\Ubuntu\home\david\library\x.raw", resolve=False)


def test_the_app_reads_a_wsl_share_path_as_the_distro_does():
    """rig.wsl_path (PAD-849) spelled \\wsl.localhost\... as an SMB share to mount under /mnt/unc; it is WSL's own
    file system, and the library on the store is reached through it from Windows."""
    from pinball_decryptor.webui import rig
    assert rig.wsl_path(r"\\wsl.localhost\Ubuntu\mnt\wsl\cards\library\gz.raw") == "/mnt/wsl/cards/library/gz.raw"
    assert rig.wsl_path(r"\\wsl$\PAD-Runtime\mnt\wsl\cards\library\gz.raw") == "/mnt/wsl/cards/library/gz.raw"
    assert rig.wsl_path(r"\\NAS\Pinball\a.raw") == "/mnt/unc/nas/pinball/a.raw"        # a real share, as before
    assert rig.unc_mounts(["x", "/mnt/wsl/cards/library/gz.raw"]) == []
