"""PAD-559: a save state of a run with YOUR EDITS applied.

A Bond LE owner testing his own modes pressed Save state and got
"[save] FAILED (exit 1):" with nothing after the colon. Two faults:

  * criu refused the save. The app's override set (PAD-103) binds every
    edited card file from the staged set over the card's copy, and a new
    file arrives through a read-only overlay. Neither is a mount criu can
    place on its own: "112:./games/james_bond_le/<file> doesn't have a
    proper root mount" for the binds, and for the overlay a dump that works
    and a restore that cannot mount it back (its lowerdir names a path that
    only meant something inside the dead guest's namespace). Every save of
    a run with edits failed.
  * the window's status bar shows the last TAGGED line, and criu's reason
    was printed indented under the FAILED line - untagged, so dropped.

The end-to-end proof is a run (Bond LE 1.06 stock card, one edited file and
one new file: save, load, the restored guest reads both). These pin the
shape, the path translation the save depends on, and the status-bar line.
"""
import os
import subprocess
import sys

import pytest

from tests.conftest import HAS_BASH

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")

if RIG not in sys.path:
    sys.path.insert(0, RIG)


def src(name):
    with open(os.path.join(RIG, name), encoding="utf8", errors="replace") as f:
        return f.read()


def line_of(text, needle):
    for i, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return i
    raise AssertionError("not found: %r" % needle)


# The guest's and the host's mountinfo from the real failing run (slot 1,
# PAD-Runtime, Bond LE card, one edited file + one new file under assets/).
GUEST_MI = """\
90 48 0:37 / / rw,relatime - overlay padslot1 rw,lowerdir=/home/pad/spike2root,upperdir=/home/pad/padslots/1/upper,workdir=/home/pad/padslots/1/work
91 90 0:40 / /proc rw,relatime - proc proc rw
96 90 0:37 /games /games rw,relatime - overlay padslot1 rw,lowerdir=/home/pad/spike2root,upperdir=/home/pad/padslots/1/upper,workdir=/home/pad/padslots/1/work
99 96 0:39 /james_bond_le /games/james_bond_le rw,nosuid,nodev,relatime - fuse.ext4 /mnt/d/x.raw rw,user_id=0,group_id=0,allow_other
100 90 0:5 /null /dev/null rw,nosuid,relatime - devtmpfs none rw
114 99 0:45 / /games/james_bond_le/assets rw,relatime - overlay overlay ro,lowerdir=/home/pad/padslots/1/override/james_bond_le/assets:/home/pad/padslots/1/root/games/james_bond_le/assets,redirect_dir=on
115 114 8:64 /home/pad/padslots/1/override/james_bond_le/assets/new.txt /games/james_bond_le/assets/new.txt rw,relatime - ext4 /dev/sde rw
116 99 8:64 /home/pad/padslots/1/override/james_bond_le/coil.hex /games/james_bond_le/coil.hex rw,relatime - ext4 /dev/sde rw
"""
HOST_MI = """\
644 629 8:64 / / rw,relatime - ext4 /dev/sde rw
44 644 0:37 / /home/pad/padslots/1/root rw,relatime - overlay padslot1 rw,lowerdir=/home/pad/spike2root
45 644 0:39 / /home/pad/padslots/1/card/james_bond_le-1_06_0 rw,nosuid,nodev,relatime - fuse.ext4 /mnt/d/x.raw rw
"""


def _helpers():
    """savestate.sh's path helpers, reading the two fixtures instead of /proc."""
    text = src("savestate.sh")
    start = text.index("host_path() {")
    end = text.index("\n}\n", text.index("lower_host() {")) + 3
    return (text[start:end]
            .replace("/proc/self/mountinfo", '"$HOSTMI"')
            .replace('"/proc/$PID/mountinfo"', '"$GUESTMI"'))


@pytest.mark.skipif(not HAS_BASH, reason="no usable bash")
def test_the_edits_are_found_on_this_side_of_the_guest():
    script = (
        'T=$(mktemp -d); HOSTMI=$T/h; GUESTMI=$T/g\n'
        "cat > $HOSTMI <<'EOF'\n" + HOST_MI + "EOF\n"
        "cat > $GUESTMI <<'EOF'\n" + GUEST_MI + "EOF\n"
        + _helpers() +
        'echo "root=$GUEST_ROOT_HOST"\n'
        'host_path 8:64 /home/pad/padslots/1/override/james_bond_le/coil.hex\n'
        'host_path 0:39 /james_bond_le\n'
        'lower_host /home/pad/padslots/1/override/james_bond_le/assets 114\n'
        'lower_host /home/pad/padslots/1/root/games/james_bond_le/assets 114\n'
        'rm -rf $T\n')
    r = subprocess.run(["bash", "-s"], input=script.encode().replace(b"\r", b""),
                       capture_output=True, timeout=60)
    out = r.stdout.decode().replace("\r", "").split("\n")
    assert r.returncode == 0, r.stderr.decode()
    assert out[:5] == [
        # no trailing slash: the root's own path, which the overlay names
        "root=/home/pad/padslots/1/root",
        # an edited file: the staged set's copy on the host disk
        "/home/pad/padslots/1/override/james_bond_le/coil.hex",
        # the card's title directory through its fuse mount
        "/home/pad/padslots/1/card/james_bond_le-1_06_0/james_bond_le",
        # the set's layer is a host path already
        "/home/pad/padslots/1/override/james_bond_le/assets",
        # the card's layer, named by its pre-pivot path, resolved through
        # the guest's card bind - NOT the slot root, where nothing is
        "/home/pad/padslots/1/card/james_bond_le-1_06_0/james_bond_le/assets",
    ], out


def test_save_records_edits_as_externals_not_the_rootfs():
    text = src("savestate.sh")
    assert 'echo "bind $key $mp $src"' in text
    assert 'echo "ovl $key $mp $hl"' in text
    # the slot root and its self-binds stay criu's: skipped by device
    assert '[ "$majmin" = "$GUEST_ROOT_MM" ] && continue' in text
    assert '"$GUEST_ROOT_FR"/*' in text
    # the overlay case is reached: overlay is no longer in the ignore list
    ignore = text[text.index("    proc|sysfs|tmpfs|"):]
    ignore = ignore[:ignore.index(")")]
    assert "overlay" not in ignore and "devtmpfs" not in ignore
    assert line_of(text, "    overlay)") < line_of(text, '"$CRIU" dump')


def test_restore_rebinds_the_edits_and_checks_them_before_the_kill():
    text = src("restorestate.sh")
    kill = line_of(text, "killing just the guest")
    for needle in ('[ "$kind" = bind ] || continue',
                   '[ "$kind" = ovl ] || continue'):
        assert line_of(text, needle) < kill, needle
    assert "    bind)" in text and "    ovl)" in text
    # rebuilt off /run: nsclean unmounts tmpfs, and the overlay went with it
    assert "mktemp -d /var/tmp/pad_ovl." in text
    assert "/run/pad_ovl" not in text
    # and nsclean keeps every mount an external lives on
    assert 'grep -qxF -- "\\$mp" "$NSKEEP"' in text


class _R:
    def __init__(self, out):
        self.stdout, self.stderr = out.encode(), b""


def test_the_status_bar_names_crius_reason():
    import playfield
    out = (
        "[savegame] slot 'slot1'  <-  james_bond_le (pid 141435)\n"
        "[save] guest pid 141435, root /\n"
        "[save] FAILED (exit 1):\n"
        "    (00.003046) Error (criu/mount.c:753): mnt: 112:./games/x.hex"
        " doesn't have a proper root mount\n"
        "    (00.003679) Error (criu/cr-dump.c:2111): Dumping FAILED.\n"
        "[save] could not save: mnt: 112:./games/x.hex doesn't have a proper"
        " root mount\n"
        "[savegame] FAILED\n")
    assert playfield.state_reply("savegame.sh", _R(out)) == (
        "[save] could not save: mnt: 112:./games/x.hex doesn't have a proper"
        " root mount")
    text = src("savestate.sh")
    assert line_of(text, 'echo "[save] FAILED (exit $RC):"') < \
        line_of(text, 'echo "[save] could not save:')


# ---- round 2: the save's freeze is time the game must not see -------------
# The reporter's SECOND save held the game ~13 s; its dispatch watchdog
# (10 s absolute deadline, exit 5) ended it seconds after the thaw. Pause
# credits frozen time to padsw's paused_ms before the SIGCONT; the save now
# does the same. Rig proof: a save stretched 12 s past criu ended Bond LE with
# GAME EXIT DISPATCH TIMEOUT on the shipped scripts and left it running with
# the fix (16.4 s credited).

def test_the_freeze_is_credited_before_every_thaw():
    text = src("savestate.sh")
    lines = text.split("\n")
    cont = [i for i, l in enumerate(lines, 1)
            if l.strip().startswith('kill -CONT "$PID"')]
    assert cont, "no thaw found"
    # the FIRST thaw of each path is preceded by its credit
    for n in (cont[0], next(i for i in cont if i > line_of(text, "# --- thaw"))):
        before = "\n".join(lines[max(0, n - 6):n - 1])
        assert "credit_freeze" in before, n
    # the moment criu starts is taken BEFORE it runs
    assert line_of(text, "T_CRIU0=$(date +%s%3N)") < line_of(text, '"$CRIU" dump')
    # a game paused DURING the save is left to Pause's own credit
    paused = text[text.index("Pause was pressed during the save"):]
    paused = paused[:paused.index("\nelse\n")]
    assert "credit_freeze" not in paused.replace("No credit", "")


@pytest.mark.skipif(not HAS_BASH, reason="no usable bash")
def test_the_credit_starts_at_the_seize_and_errs_short():
    text = src("savestate.sh")
    fn = text[text.index("credit_freeze() {"):]
    fn = fn[:fn.index("\nPYEOF\n}\n") + len("\nPYEOF\n}\n")]
    script = (
        'T=$(mktemp -d); DDIR=$T\n'
        "printf '(00.000100) Version: 4.1\n(00.300000) Seized task 42, state 1\n' > $T/dump.log\n"
        'command -v python3 >/dev/null || { echo NOPY; exit 0; }\n'
        # the rig's GNU date gives milliseconds with %3N; macOS's BSD date
        # prints the "3N" literally, so stand in for it there
        'case $(date +%s%3N) in *[!0-9]*) date() { python3 -c "import time; print(int(time.time() * 1000))"; };; esac\n'
        'python3 -c "import struct,sys; b=bytearray(4096); struct.pack_into(\'<I\',b,0,0x53444150);'
        ' struct.pack_into(\'<I\',b,1088,500); open(sys.argv[1],\'wb\').write(b)" $T/padsw\n'
        'GSW=$T/padsw\n'
        "SWPY=$(wslpath -u '" + RIG + "' 2>/dev/null || echo '" + RIG + "')\n"
        'T_CRIU0=$(( $(date +%s%3N) - 5300 ))\n'
        + fn +
        'credit_freeze\n'
        'python3 -c "import struct,sys; print(\'total\', struct.unpack_from(\'<I\', open(sys.argv[1],\'rb\').read(), 1088)[0])" $T/padsw\n'
        'rm -rf $T\n')
    r = subprocess.run(["bash", "-s"], input=script.encode().replace(b"\r", b""),
                       capture_output=True, timeout=60)
    out = r.stdout.decode().replace("\r", "")
    if "NOPY" in out:
        pytest.skip("no python3 in that bash")
    assert r.returncode == 0, r.stderr.decode()
    total = int(out.split("total ")[1].split()[0])
    # 500 already held + 5300 ms since criu started - 300 ms before the seize
    # - 1 ms short: ~4999, never more (a credit past the gap steps the
    # game's clock backwards)
    assert 500 + 4999 <= total <= 500 + 4999 + 200, out
    assert "frozen 5.0 s" in out or "frozen 5.1 s" in out or "frozen 5.2 s" in out, out


# ---- round 3: a LOAD wakes the game where the save stopped it -------------
# The reporter's slot came back and ended itself at once, both from a running
# game and from a fresh Launch: "worst gap 10392 ms", then exit 5 from
# 0x1c49c (GAME EXIT DISPATCH TIMEOUT). criu restores the guest into a time
# namespace that hides the time the slot sat on disk, but not the seize-to-
# restore stretch, and on a slow PC that passes the game's 10 s watchdog.
# Rig proof: a restore stalled 12 s ended Bond LE exactly so on v1.187.6
# (worst gap 18615 ms, exit 5 from 0x1c49c); with this the restored game's
# first video line read "worst gap 43 ms" and it ran on.

def test_the_save_records_when_the_game_was_seized():
    text = src("savestate.sh")
    assert line_of(text, "T_CRIU0=$(date +%s%3N)") < line_of(text, "MONO0=$(python3")
    assert line_of(text, "MONO0=$(python3") < line_of(text, '"$CRIU" dump')
    assert line_of(text, '"$CRIU" dump') < line_of(text, 'echo "frozen_at $(( MONO0 + SEIZE_OFF ))')
    # recorded only for a dump that worked: after the failure branch's exit
    fail = text.index('echo "[save] FAILED (exit $RC):"')
    assert text.index('echo "frozen_at') > text.index("\nfi\n", fail)


def test_the_load_credits_the_restored_game_before_it_runs():
    text = src("restorestate.sh")
    # criu leaves the restored tree stopped, so the credit lands first
    assert "restore.log -d --leave-stopped" in text
    credit = line_of(text, 'awk \'$1 == "frozen_at" {print $2, $3; exit}\'')
    thaw = line_of(text, 'kill -CONT "${d#/proc/}"')
    assert line_of(text, '[restore] ok - guest restored') < credit < thaw
    # the restored game's own clock: ours plus its time namespace's offset
    assert "timens_offsets" in text and '"monotonic"' in text
    # the thaw reaches every task of the restored tree, not just its init
    assert 'readlink "$d/ns/pid"' in text
    # an older slot is credited the restore's own duration, measured from
    # the start of the criu attempt that worked
    assert line_of(text, "REST0=$(python3") < line_of(text, "    do_restore")
    assert '"${REST0:--}"' in text and "the restore took %.1f s" in text


@pytest.mark.skipif(not HAS_BASH, reason="no usable bash")
def test_the_load_credit_is_the_time_the_game_perceives_and_errs_short():
    text = src("restorestate.sh")
    body = text[text.index("python3 - \"$R/dump/padsw\" \"${FZ_MS:--}\""):]
    body = body[body.index("<<'PYEOF'\n") + len("<<'PYEOF'\n"):body.index("\nPYEOF\n")]
    script = (
        '[ -e /proc/self/ns/time ] || { echo NOPROC; exit 0; }\n'
        'command -v python3 >/dev/null || { echo NOPROC; exit 0; }\n'
        'T=$(mktemp -d)\n'
        'python3 -c "import struct,sys; b=bytearray(4096); struct.pack_into(\'<I\',b,0,0x53444150);'
        ' struct.pack_into(\'<I\',b,1088,700); open(sys.argv[1],\'wb\').write(b)" $T/padsw\n'
        "cat > $T/credit.py <<'PYEOF'\n" + body + "\nPYEOF\n"
        "SWPY=$(wslpath -u '" + RIG + "' 2>/dev/null || echo '" + RIG + "')\n"
        # saved 7.5 s ago, on this boot; the "guest" is this shell, which
        # shares our time namespace, so no offset applies
        'FZ=$(( $(python3 -c "import time; print(int(time.monotonic()*1000))") - 7500 ))\n'
        'python3 $T/credit.py $T/padsw $FZ "$(cat /proc/sys/kernel/random/boot_id)" $$ "$SWPY" -\n'
        'python3 -c "import struct,sys; print(\'total\', struct.unpack_from(\'<I\', open(sys.argv[1],\'rb\').read(), 1088)[0])" $T/padsw\n'
        # and a save from another boot, with no time namespace: no credit
        'python3 $T/credit.py $T/padsw $FZ not-this-boot $$ "$SWPY" -\n'
        # an OLDER slot (no frozen_at) in no time namespace of its own: the
        # restore's duration is only a safe credit under criu's namespace
        'python3 $T/credit.py $T/padsw - - $$ "$SWPY" $(( $(python3 -c "import time; print(int(time.monotonic()*1000))") - 3000 ))\n'
        'python3 -c "import struct,sys; print(\'again\', struct.unpack_from(\'<I\', open(sys.argv[1],\'rb\').read(), 1088)[0])" $T/padsw\n'
        'rm -rf $T\n')
    r = subprocess.run(["bash", "-s"], input=script.encode().replace(b"\r", b""),
                       capture_output=True, timeout=60)
    out = r.stdout.decode().replace("\r", "")
    if "NOPROC" in out:
        pytest.skip("no Linux /proc in that bash")
    assert r.returncode == 0, r.stderr.decode()
    total = int(out.split("total ")[1].split()[0])
    # 700 the save held + ~7.5 s since the seize - 1 ms; never more than the
    # real gap (that would step the game's clock backwards)
    assert 700 + 7499 <= total <= 700 + 7499 + 300, out
    assert "wakes 7.5 s after it was saved" in out or "wakes 7.6 s" in out, out
    assert int(out.split("again ")[1].split()[0]) == total, out
    assert "before WSL last restarted" in out, out


@pytest.mark.skipif(not HAS_BASH, reason="no working bash")
def test_a_containers_tmpfs_dev_binds_are_externals_like_devtmpfs():
    """PAD-835: in the Mac's emulator box /dev is a tmpfs the engine filled,
    so the guest's /dev/null and /dev/tty binds read "tmpfs" and were skipped
    as a fresh tmpfs - criu then died at "./dev/tty doesn't have a proper
    root mount". The guest's own /dev/shm (root "/") stays internal. Lines
    from a real guest in the box."""
    body = src("savestate.sh")
    start = body.index("    # ★ PAD-835: A CONTAINER'S /dev IS A tmpfs.")
    block = body[start:body.index('    case "$fstype" in', start)]
    lines = {
        "/dev/null": "1349 1345 0:221 /null /dev/null rw,relatime - tmpfs dev rw,mode=755",
        "/dev/tty": "1470 1345 0:221 /null /dev/tty rw,relatime - tmpfs dev rw,mode=755",
        "/dev/shm": "1347 1345 0:232 / /dev/shm rw,relatime - tmpfs tmpfs rw",
        "/tmp": "1351 1345 0:233 /x /tmp rw,relatime - tmpfs tmpfs rw",
        "/dev/ttymxc1": "1472 1345 0:222 /0 /dev/ttymxc1 rw,relatime - devpts devpts rw",
    }
    want = {"/dev/null": "devtmpfs", "/dev/tty": "devtmpfs",
            "/dev/shm": "tmpfs", "/tmp": "tmpfs", "/dev/ttymxc1": "devpts"}
    for mp, line in lines.items():
        script = "\n".join([
            "line='%s'" % line,
            "mp=$(awk '{print $5}' <<<\"$line\")",
            "fstype=$(awk '{for(i=7;i<=NF;i++) if($i==\"-\"){print $(i+1); exit}}' <<<\"$line\")",
            block, 'echo "$fstype"', ""])
        out = subprocess.run(["bash", "-s"], input=script.encode("utf-8"),
                             stdout=subprocess.PIPE, timeout=30)
        assert out.stdout.decode().strip() == want[mp], (mp, out.stdout)
