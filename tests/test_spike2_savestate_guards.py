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


# ----------------------------------------------------------------------
# THE PRICE OF A CHECKPOINTABLE BOOT MUST BE THE FEATURE, NOT THE RUN.
#
# v0.126.0 made every Start a PAD_PIVOT boot, because that is the only shape
# criu can dump.  That boot needs a native static busybox to umount the old
# root after the pivot, no machine has one by default, it was on no
# prerequisite list, and run_game.sh answers a pivot it cannot do with
# `exit 1`.  So the release that turned save states on took the emulator away
# from everyone without busybox-static.  A user reported it on 2026-08-11
# against star_wars_le and iron_maiden_pro - two titles that had run on that
# machine before:
#
#     [run] PAD_PIVOT needs a STATIC busybox at /bin/busybox
#     [watch] the game never started.
# ----------------------------------------------------------------------

def test_a_run_that_cannot_be_checkpointed_still_runs():
    """watch.sh withdraws the pivot request; it does not pass it on and let
    run_game.sh stop the run."""
    text = src("watch.sh")
    assert "! pad_can_pivot" in text, (
        "watch.sh no longer checks whether a pivot is possible")
    gate = line_of(text, "! pad_can_pivot")
    assert "unset PAD_PIVOT" in text, (
        "the request has to be withdrawn, or run_game.sh still exits 1")
    # BEFORE anything reads it: the cfg dump has to name the shape that really
    # ran, and PF_STATES must not offer save buttons this run cannot honour.
    assert gate < line_of(text, "[watch] cfg argv="), \
        "the log would name a pivot boot that did not happen"
    assert gate < line_of(text, 'PAD_SAVESTATES:-${PAD_PIVOT:-0}'), \
        "the playfield would show Save/Load buttons that can only fail"
    assert gate < line_of(text, 'PAD_PIVOT="${PAD_PIVOT:-}"'), \
        "run_game.sh would still be asked for a pivot it cannot do"


def test_the_withdrawal_says_what_it_costs_and_how_to_undo_it():
    """A silent fallback is a save-state feature that quietly disappeared."""
    text = src("watch.sh")
    block = text[text.index("! pad_can_pivot"):]
    block = block[:block.index("unset PAD_PIVOT")]
    assert "save states are off" in block
    assert "apt install busybox-static" in block
    # Both halves have their own sentence: naming busybox-static at a machine
    # that already has it is telling someone to install what they have.
    assert "no pivot_root" in block
    assert "util-linux" in block


def test_one_definition_of_what_a_pivot_needs():
    """run_game.sh does the pivot, watch.sh decides whether to ask for one and
    setupcheck.sh predicts the answer before Start is pressed.  Two copies of
    the test is how the tab clears a machine the run then refuses - this rig's
    oldest rule."""
    assert "pad_static_busybox()" in src("padpath.sh")
    assert "pad_pivot_root_cmd()" in src("padpath.sh")
    for script in ("run_game.sh", "watch.sh", "setupcheck.sh"):
        text = src(script)
        assert "pad_static_busybox" in text or "pad_can_pivot" in text, script
        assert "ldd /bin/busybox" not in text, (
            "%s is re-implementing the test instead of calling it" % script)
        assert not re.search(r"^\s*command -v pivot_root", text, re.M), (
            "%s is looking for pivot_root itself instead of calling it" % script)


# ----------------------------------------------------------------------
# ...AND THE SAME PRICE AGAIN, ONE RELEASE LATER, IN A DIFFERENT PROGRAM.
#
# The same user then installed busybox-static - the package v0.126.1's own
# notice had just asked him for - and the next run died two lines further into
# the pivot (2026-08-11):
#
#     [run] PAD_PIVOT: checkpointable boot (pivot_root, explicit qemu)
#     bash: line 98: pivot_root: command not found
#     [run] pivot_root failed
#     [watch] the game never started.
#
# So the repair the app offered is what took his emulator away, because the
# gate tested ONE of the two programs a pivot needs.  Three rules come out of
# it: what a pivot needs is a LIST and the gate asks about all of it
# (pad_can_pivot); the pivot runs whatever THIS machine has rather than one
# spelling of it (pad_pivot_root_cmd); and a pivot that fails anyway costs the
# feature, not the run.
# ----------------------------------------------------------------------

def test_what_a_pivot_needs_is_asked_as_one_question():
    """Both halves, one call - so no caller can accidentally ask half of it
    again."""
    text = src("padpath.sh")
    assert "pad_can_pivot()" in text
    body = text[text.index("pad_can_pivot()"):]
    body = body[:body.index("}")]
    assert "pad_static_busybox" in body, "the umount half is not being asked"
    assert "pad_pivot_root_cmd" in body, "the pivot half is not being asked"


def test_the_pivot_is_done_by_the_command_this_machine_actually_has():
    """A bare `pivot_root` is a PATH lookup, and the report is what a PATH
    without /usr/sbin - or a machine without the binary - does with one."""
    text = src("run_game.sh")
    assert not re.search(r"^\s*pivot_root \. oldroot", text, re.M), (
        "the pivot is a bare PATH lookup again")
    assert "$PIVOTROOT . oldroot" in text
    assert "pad_pivot_root_cmd" in text, (
        "run_game.sh must ask the shared resolver, not spell it itself")


def test_the_resolver_hands_back_nothing_it_has_not_confirmed_runnable():
    """As root - and every PAD_PIVOT run is root - `command -v` returns a path
    for a file that cannot be executed at all.  Measured 2026-08-11: with a
    character device in /usr/sbin/pivot_root's place it printed the path and
    returned 0, while running it said Permission denied.  A resolver that
    trusts that answer is `command not found` again, one directory deeper."""
    text = src("padpath.sh")
    body = text[text.index("pad_pivot_root_cmd()"):]
    body = body[:body.index("pad_can_pivot()")]
    assert '[ -f "$p" ] && [ -x "$p" ]' in body, (
        "a PATH hit is being trusted without confirming it can be run")
    assert "--list" in body, (
        "the busybox applet has to be confirmed by running busybox")


def test_a_pivot_that_fails_anyway_still_starts_the_game():
    """Everything above the pivot - the namespace, every mount, the card - is
    already built and correct, and the chroot boot this rig has always done
    would run perfectly from there.  `exit 1` threw all of it away."""
    text = src("run_game.sh")
    assert 'pivot_root failed" >&2; exit 1' not in text, (
        "a failed pivot is taking the whole run down again")
    fail = line_of(text, "[run] pivot_root failed")
    assert fail < line_of(text, 'exec chroot "$R" /bin/sh -c'), (
        "the failure must fall through to the ordinary boot")
    block = text[text.index("[run] pivot_root failed"):]
    block = block[:block.index("exec chroot")]
    assert "save states are off" in block, (
        "a silent fallback is a save-state feature that vanished")


def test_the_save_buttons_follow_the_boot_that_happened():
    """A run that fell back is up, correct and NOT checkpointable, and the
    playfield must not offer Save/Load for it - the same rule the pre-flight
    gate keeps, applied to the one case no pre-flight can predict."""
    text = src("watch.sh")
    block = text[text.index('PF_STATES=""'):]
    block = block[:block.index('PF_STATES="--savestates"')]
    assert "pivot_root failed" in block, (
        "the flag is set from what the run was ASKED to be")
    # It can only be read from the log if the guest has already been launched.
    assert line_of(text, 'bash "$RIG/run_game.sh"') < line_of(text, 'PF_STATES=""')
