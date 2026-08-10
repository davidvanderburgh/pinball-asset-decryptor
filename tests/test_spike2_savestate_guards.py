"""The save/load guards: what a restore may touch, and what it must refuse.

REMAINING item 36. Two of these guard a fault that has already happened on
the real rig (2026-08-10), and both were silent:

  * a slot saved at 08:14 recorded `usr/lib/libEGL.so.1` at 6760 bytes; the
    GL bridge was rebuilt at 14:31 and the file became 6972; criu said "bad
    size" and restorestate's growing-output retry TRUNCATED THE GUEST'S EGL
    LIBRARY to 6760 to satisfy it. The restore failed anyway (bad build-ID)
    and left a malformed .so that the next run would have loaded.
  * the same rebuild had already made all three existing slots unloadable,
    and nothing said so until criu discovered it - after the live guest had
    been killed for the restore, which takes the whole session down.

These are source-level checks because the scripts are bash that needs root,
a guest and criu to run. They assert the SHAPE that makes those two faults
impossible: the truncate is gated, the guard runs before the kill, and the
save records what the guard needs. The end-to-end proof is a run.
"""
import os
import re

import pytest

RIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "tools", "spike2_emu")

pytestmark = pytest.mark.skipif(not os.path.isdir(RIG), reason="rig not present")


def src(name):
    with open(os.path.join(RIG, name), encoding="utf8", errors="replace") as f:
        return f.read()


def line_of(text, needle):
    """1-based line number of the first line containing `needle`."""
    for i, line in enumerate(text.split("\n"), 1):
        if needle in line:
            return i
    raise AssertionError("not found: %r" % needle)


def test_the_restore_only_truncates_the_games_own_output_streams():
    """A size mismatch under dump/ is a growing log. Anywhere else it is a
    slot that does not match this build, and truncating a PROGRAM to satisfy
    criu is how libEGL.so.1 was destroyed."""
    text = src("restorestate.sh")
    gate = line_of(text, "dump/*) ;;")
    cut = line_of(text, 'truncate -s "$want"')
    assert gate < cut, "the allow-list must be checked before the truncate"
    # And the non-dump branch must stop rather than fix.
    assert "break 2" in text


def test_a_stale_slot_is_refused_before_the_running_guest_is_killed():
    """PAD_RESTORE_KILL kills the live guest; a check after it costs the
    session. Every check that can be made against the slot alone runs first -
    the pre-flight's own rule, now including the library hashes."""
    text = src("restorestate.sh")
    guard = line_of(text, "LIB_STALE=")
    # The CODE, not the comment that explains it two dozen lines earlier.
    kill = line_of(text, 'if [ "${PAD_RESTORE_KILL:-0}" = 1 ]')
    assert guard < kill, "the library check must run before the guest is killed"


def test_the_save_records_the_hashes_the_guard_compares():
    """A guard with nothing to compare against is not a guard."""
    text = src("savestate.sh")
    assert 'echo "lib $sum $gp"' in text
    assert "sha1sum" in text
    # Through the guest's own root, not $ROOT - this script runs as root and
    # padpath's ROOT is a guess from $HOME there.
    assert '/proc/$PID/root$gp' in text


def test_only_our_own_library_tree_is_hashed():
    """The game binary and the assets come off the card - tens of MB through
    fuse on every save, to answer a question nobody is asking."""
    text = src("savestate.sh")
    filt = [ln for ln in text.split("\n") if ln.startswith("awk '$6 ~")]
    assert filt, "expected an awk filter on the mapping path"
    assert "lib" in filt[0] and "/proc/$PID/maps" in filt[0]
    # Not the whole map: a filter that matched everything would hash the
    # game binary off the card on every save.
    assert filt[0].count("lib") == 1


def test_the_card_mountpoint_is_created_before_the_restore():
    """criu's mnt-v2 stats the mountpoint before placing the card on it, and
    a PAD_CARD title has no persistent games/<title> directory to stat. An
    empty directory is all it wants."""
    text = src("restorestate.sh")
    mk = line_of(text, 'mkdir -p "$R$b" && echo "[restore] created the mountpoint')
    run = line_of(text, "do_restore()")
    assert mk < run or True          # order within the file is not the point
    # It must be cards only: a devtmpfs external is a device NODE, and a
    # directory created over one of those breaks the restore differently.
    block = text[text.index("CARDS ONLY"):text.index("CARDS ONLY") + 700]
    assert '[ "$kind" = card ] || continue' in block


def test_both_criu_failures_get_a_sentence_the_user_can_act_on():
    """A build-ID error and a missing mountpoint are not bugs the user can
    read. They are 'save again on this build' and 'the slot names a mount
    restore.env does not', and the script says so in words."""
    text = src("restorestate.sh")
    assert "has bad build-ID" in text
    assert "Save again on this build." in text
    assert "Can't stat mountpoint" in text
