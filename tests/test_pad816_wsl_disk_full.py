"""A card cache copy must not fill the Windows drive behind WSL (PAD-816).

A reporter's first Rush LE boot started caching the 14.7 GB card into Ubuntu's
ext4.vhdx on a C: with a few GB left. Inside WSL `df` reports the virtual disk
(1 TB), so the copy started; the vhdx could not grow, ext4 remounted the whole
distro read-only at 3.6 GB, and from then on every start said "LOG=... is not
writable here - fix or unset LOG" while the setup button ended "this PC can
run the emulator now".

Now the app names the drive the vhdx is on (PAD_HOST_DRIVE) and the copier
counts its free space, and a read-only disk is named as one, with the cure.
"""
import os
import re
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH
from pinball_decryptor.webui import emulate_core

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools", "spike2_emu")

def _text(name):
    with open(os.path.join(RIG, name), encoding="utf-8") as fh:
        return fh.read()


def _funcs(src, *names):
    text = _text(src)
    out = []
    for n in names:
        m = re.search(r"^%s\(\) \{.*?^\}\n" % re.escape(n), text, re.S | re.M)
        assert m, n
        out.append(m.group(0))
    return "".join(out)


def _bash(script):
    return subprocess.run(["bash", "-s"], input=script.encode(), stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=120).stdout.decode("utf-8", "replace")


# Units are KB, unscaled: the image is 14 MB (need 14336 KB), keeps are 0, and df is a stand-in that says 1 TB for
# the cache's own disk - the virtual size - and $HOSTFREE for the Windows drive.
DRIVER = r"""
set -u
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
CACHE=$T/cache; CARDS=$T/cards; LIBRARY=$T/nolib; CACHE_KEEP_GB=0; PAD_HOST_KEEP_FREE_GB=0
mkdir -p "$CACHE" "$CARDS" "$T/img" "$T/win"
echo 0 > "$CACHE/.limit_gb"
df() { local a; for a; do :; done
       echo Avail; if [ "$a" = "$T/win" ]; then echo "$HOSTFREE"; else echo 1073741824; fi; }
truncate -s 14M "$T/img/rush.raw"
run() {   # <case> <host free KB> [<evictable entry MB>]
    rm -f "$CACHE"/*.raw "$CACHE"/*.src "$CACHE"/*.boot
    if [ -n "${3:-}" ]; then
        truncate -s 1M "$T/img/old.raw"
        head -c "${3}M" /dev/zero > "$CACHE/old.raw"; cache_stamp "$T/img/old.raw" > "$CACHE/old.src"
    fi
    HOSTFREE=$2
    cache_make_room "$T/img/rush.raw" "$CACHE/rush.raw" 2>&1; echo "$1 rc=$?"
}
PAD_HOST_DRIVE=$T/win
run tight 6000
run roomy 20000
run evict 6000 12
run short 1000 12
unset PAD_HOST_DRIVE
run nodrive 6000
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.skipif(sys.platform == "darwin", reason="the rig's scripts speak GNU stat/du")
def test_the_copier_counts_the_windows_drive():
    script = _funcs("cardmount.sh", "cache_stamp", "stamp_key", "cache_valid", "copier_alive", "cache_pinned",
                    "label_mounted", "cache_readers", "cache_in_use", "cache_source_state", "cache_limit_gb",
                    "cache_used_kb", "host_free_kb", "cache_make_room") + DRIVER
    out = _bash(script)
    lines = out.splitlines()
    # 6 MB free on the drive for a 14 MB copy and nothing to evict: refused, naming the drive, booting off the card
    assert "tight rc=1" in lines, out
    assert any(l.startswith("[card] the Windows drive behind WSL (") and "is too full to cache this card" in l
               and "running off the original" in l for l in lines), out
    assert "roomy rc=0" in lines, out
    # an evicted 12 MB entry frees blocks inside the vhdx the copy reuses: 6 + 12 >= 14
    assert "evict rc=0" in lines, out
    assert "[card] evicting cached old (least recently booted) to make room" in lines, out
    # 1 + 12 < 14: everything evictable went and it still does not fit
    assert "short rc=1" in lines, out
    # without the drive (another platform, or the app could not find the vhdx) it is the old check, untouched
    assert "nodrive rc=0" in lines, out


RO_DRIVER = r"""
set -u
T=$(mktemp -d)
mkdir -p "$T/rw" "$T/ro"
pad_disk_readonly "$T/rw" && echo "rw readonly" || echo "rw writable"
ls -A "$T/rw" | wc -l | sed 's/^/rw left /'
chmod 0555 "$T/rw"; pad_disk_readonly "$T/rw" && echo "mode readonly" || echo "mode not readonly"; chmod 0755 "$T/rw"
if unshare -rm sh -c "mount -t tmpfs -o ro none '$T/ro'" 2>/dev/null; then
    export -f pad_disk_readonly pad_disk_readonly_say
    unshare -rm bash -c "mount -t tmpfs -o ro none '$T/ro' && {
        pad_disk_readonly '$T/ro' && echo 'ro readonly' || echo 'ro writable'
        PAD_HOST_DRIVE='$T/rw' pad_disk_readonly_say watch; }" 2>&1
else
    echo "ro skipped"
fi
rm -rf "$T"
"""


@pytest.mark.skipif(not HAS_BASH, reason="needs bash")
@pytest.mark.skipif(sys.platform == "darwin", reason="the rig's scripts speak GNU stat/du")
def test_a_read_only_disk_is_named_as_one():
    out = _bash(_funcs("padpath.sh", "pad_disk_readonly", "pad_disk_readonly_say") + RO_DRIVER)
    lines = out.splitlines()
    assert "rw writable" in lines and "rw left 0" in lines, out          # the probe leaves nothing behind
    # a refused MODE is pad_can_write's case, not this one (and root passes it anyway)
    assert "mode readonly" not in lines, out
    if "ro skipped" in lines:
        pytest.skip("no unprivileged mount namespace here: " + out)
    assert "ro readonly" in lines, out
    say = "\n".join(l for l in lines if l.startswith("[watch]"))
    assert "THE LINUX DISK HAS GONE READ-ONLY" in say, out
    assert "GB free now" in say and "wsl --shutdown" in say, out


def test_every_place_that_hit_it_asks_first():
    watch = _text("watch.sh")
    i = watch.index('if pad_disk_readonly "$(dirname "$LOG")"; then')
    assert i < watch.index(': >> "$LOG" ||'), "the read-only check must come before the LOG probe"
    cm = _text("cardmount.sh")
    assert cm.index("if pad_disk_readonly; then pad_disk_readonly_say card") < cm.index('pad_can_write "$MNT" card')
    fix = _text("setupfix.sh")
    assert 'echo "result=readonly"' in fix
    assert fix.index("pad_disk_readonly /var/lib") < fix.index("_facts() {")
    tab = open(os.path.join(os.path.dirname(RIG), "..", "pinball_decryptor", "webui", "tabs", "emulate.py"),
               encoding="utf-8").read()
    assert 'result == "readonly"' in tab


def test_the_app_names_the_vhdx_drive(monkeypatch):
    from pinball_decryptor.core import wsl_disk
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(emulate_core.runtime, "wsl_distro", lambda *a, **k: "Ubuntu-24.04")
    monkeypatch.setattr(emulate_core, "_HOST_DRIVE", {})
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx",
                        lambda: ("Ubuntu-24.04", r"D:\WSL\Ubuntu\ext4.vhdx"))
    assert emulate_core._host_drive_env() == ["PAD_HOST_DRIVE=/mnt/d"]
    assert "PAD_HOST_DRIVE=/mnt/d" in emulate_core._rig_env()
    # not found: nothing, and the copier keeps its old check
    monkeypatch.setattr(emulate_core, "_HOST_DRIVE", {})
    monkeypatch.setattr(wsl_disk, "_default_distro_vhdx", lambda: (None, None))
    assert emulate_core._host_drive_env() == []
    monkeypatch.setattr(sys, "platform", "linux")
    assert emulate_core._host_drive_env() == []
