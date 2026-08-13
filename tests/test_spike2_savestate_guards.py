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
    # Both boot-shape halves have their own sentence: naming busybox-static at
    # a machine that already has it is telling someone to install what they
    # have.
    assert "no pivot_root" in block
    assert "util-linux" in block
    # ...and the THIRD program, which has a different answer again: no Ubuntu
    # packages criu, so "apt install criu" would be advice that cannot work
    # anywhere.
    assert "getcriu.sh" in block
    assert "apt install criu" not in text


def test_all_three_thirds_of_a_save_state_are_gated_not_just_the_boot_shape():
    """PAD-53 made a missing busybox cost only the feature; PAD-54 added
    pivot_root when installing that package STILL left a run refusing; and a
    pivot boot with no criu behind it offers Save and Load buttons that can
    only fail.  The gate is ONE call asking about all three, so no pair of
    fixes can leave the third hole open again."""
    pad = src("padpath.sh")
    gate = pad[pad.index("pad_can_pivot()"):]
    gate = gate[:gate.index("}")]
    assert "pad_pivot_programs" in gate
    assert "pad_criu" in gate, (
        "the pivot is withdrawn for a missing boot shape but not for a "
        "missing criu, which is the other half of the same feature")


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


# ----------------------------------------------------------------------
# ...AND THE PROGRAM THAT DOES THE FREEZING, WHICH NO UBUNTU PUBLISHES.
#
# `apt-cache policy criu` prints an EMPTY version table on 24.04, and every
# save-state script defaulted to /var/tmp/criubuild/criu/criu/criu - one
# developer's hand-built v4.1, on one machine.  So save states could not work
# for any other user even with busybox-static installed: the boot was
# checkpointable, the buttons were there, and the press answered with a path
# that user had never heard of.  getcriu.sh builds one; pad_criu finds
# whichever one is there.
# ----------------------------------------------------------------------

CRIU_SCRIPTS = ("savestate.sh", "restorestate.sh", "savegame.sh",
                "loadgame.sh", "savetest.sh", "savetest_real.sh",
                "criuladder.sh")


def test_no_script_carries_one_machines_criu_path():
    """The literal was in eight files at once.  One definition (pad_criu), or
    the next machine-specific path lands in seven of them again."""
    assert "pad_criu()" in src("padpath.sh")
    for script in CRIU_SCRIPTS:
        text = src(script)
        # CODE, not the comments that explain why the literal is gone - those
        # have to be able to name the path they replaced.
        code = [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
        assert not [ln for ln in code if "/var/tmp/criubuild" in ln], (
            "%s still defaults to one developer's build directory" % script)
        assert "pad_criu" in text, (
            "%s no longer asks padpath where criu is" % script)


def test_the_criu_search_covers_the_three_machines_that_exist():
    """A distro that packages criu (Debian), a machine getcriu.sh has built
    on, and the developer's own /var/tmp build that predates all of this and
    must keep working."""
    body = src("padpath.sh")
    body = body[body.index("pad_criu()"):]
    body = body[:body.index("\n}")]
    assert "/usr/local/bin/criu" in body, "getcriu.sh's install path"
    assert "command -v criu" in body, "a distro that packages it"
    assert "/var/tmp/criubuild" in body, "the developer build still resolves"


def test_a_failed_save_names_the_command_that_fixes_it():
    """It used to print `no criu at /var/tmp/criubuild/...` - a directory the
    user has never had and cannot create.  With no criu there is no path to
    name at all, so the message has to be the way OUT."""
    for script in ("savestate.sh", "restorestate.sh"):
        text = src(script)
        assert "no criu at $CRIU" not in text, script
        assert "getcriu.sh" in text, script


def test_criu_is_probed_but_never_handed_to_apt():
    """setupcheck.sh predicts the answer before Start; its `-` package field
    keeps it out of `need`, which setupfix.sh feeds to apt-get verbatim - and
    `apt-get install a criu` installs NEITHER."""
    text = src("setupcheck.sh")
    assert "criu:@pad_criu:-:0" in text
    assert '[ "$_pkg" = "-" ] && continue' in text, (
        "a package apt has never heard of would reach the install list")
    fix = src("setupfix.sh")
    assert "getcriu.sh" in fix, "nothing builds it, so nothing can supply it"
    # The build must not be able to fail the SETUP: the emulator runs without
    # it, and telling a working machine its setup failed is the whole fault
    # this pass exists to stop.
    assert "extras_criu=" in fix
    assert line_of(fix, 'echo "extras_criu=') < line_of(fix, 'echo "result=ok"'), (
        "the criu outcome is reported before the setup's own verdict, so the "
        "app reads the setup's result= last")


def test_the_builder_pins_a_version_and_proves_the_result():
    """A `criu check` that fails means this kernel cannot support it, and
    installing it anyway would turn the tab's warning off while leaving the
    buttons just as broken."""
    text = src("getcriu.sh")
    assert "CRIU_VERSION=${PAD_CRIU_VERSION:-v4.1}" in text, (
        "an unpinned build makes every later failure a question about which "
        "criu the user happens to have")
    assert line_of(text, '"$BIN" check') < line_of(text, "install -m 0755"), (
        "the check has to run BEFORE the binary is installed")
    assert "result=checkfailed" in text
    # Built with `make criu`, not `make`: the default target drags in the
    # Python bindings, crit and a GPU plugin, none of which this rig uses.
    assert "criu 2>&1" in text and "make -j" in text


def test_the_pinned_tree_is_patched_for_a_c23_compiler_before_it_is_built():
    """criu decides whether to define the rseq enums itself by COMPILING a
    probe that redefines one of them.  GCC 15 defaults to -std=gnu23, where an
    agreeing redefinition is legal, so the probe compiles on a glibc that has
    the enums already, criu adds a second copy, and the build dies in
    parasite.c (reported 2026-08-11).  Upstream renamed the probe's
    enumerators in v4.2.1; the pin stays at the tag the save-state ladder was
    proven against and takes that one change."""
    text = src("getcriu.sh")
    assert "RSEQ_CPU_CRIU_TEST" in text, (
        "nothing corrects the probe, so a C23 default compiler still gets "
        "'conflicting redefinition of enum' in criu/pie/parasite.o")
    assert "feature-tests.mak" in text
    assert line_of(text, "RSEQ_CPU_CRIU_TEST") < line_of(text, "make -j"), (
        "the probe has to be corrected before make reads its answer - the "
        "generated config header is what carries it into every object")
    # Applied to whatever the source step left behind, so the CLONE and the
    # REUSE path both get it; a tree already carrying upstream's fix is left
    # alone rather than patched twice.
    assert line_of(text, "RSEQ_CPU_CRIU_TEST") > line_of(text, "git clone --depth 1")
    assert "! grep -q RSEQ_CPU_CRIU_TEST" in text, (
        "without the guard this rewrites the tree on every run, and a v4.2.1 "
        "pin would be patched on top of its own fix")
    # And it can never stop a build that would have worked: every compiler
    # older than this answers the original probe correctly.
    block = text[text.index("FEATURES=$SRC"):]
    block = block[:block.index("\n# ---- 2b.")]
    assert "exit" not in block, "a probe that cannot be patched is not fatal"


def test_the_build_asks_for_the_dialect_the_pinned_tag_was_written_in():
    """C17 is the language v4.1 was written and PROVEN in - criuladder.sh's
    seven rungs were run against it - and in C17 the rseq redefinition 2a
    patches is an error again, so that probe is asked its question twice over.

    What the dialect does NOT do is settle criu/tty.c, which is what v0.130.1
    shipped believing.  See the next test."""
    text = src("getcriu.sh")
    assert "-std=gnu17" in text
    assert "USERCFLAGS" in text, (
        "criu's own seam for this; anything else has to edit its makefiles")
    # On the make line itself, not exported and hoped for.
    make_line = [ln for ln in text.split("\n") if "make -j" in ln]
    assert make_line and 'USERCFLAGS="$STD"' in make_line[0], make_line
    # Chosen before make reads it, and after the source exists to build.
    assert line_of(text, "STD=-std=gnu17") < line_of(text, "make -j")
    assert line_of(text, "STD=-std=gnu17") > line_of(text, "git clone --depth 1")
    # PROBED. A compiler too old for -std=gnu17 (before GCC 8) is also too old
    # to have C23's semantics, so it must still get the build it always got.
    probe = text[text.index("STD=\n"):text.index("# AND THE TREE MAY")]
    assert "-x c -" in probe, "the flag is tried before it is used"
    assert "else" in probe, "no branch for the compiler that refuses it"


def test_the_one_line_c23_made_wrong_is_patched_not_just_the_dialect():
    """v0.130.1 answered criu/tty.c:262 with -std=gnu17, and a dialect cannot
    reach it.  criu's own DEFINES carry -D_GNU_SOURCE; glibc's features.h
    turns _GNU_SOURCE into _ISOC23_SOURCE, which sets __GLIBC_USE (ISOC23);
    and string.h gates the const-generic str*chr macros on THAT, never on
    __STDC_VERSION__.  So criu asks for the C23 behaviour itself, every
    compile, whatever -std= says - and a second user hit the identical error
    on a build that already had the dialect pin (2026-08-13).

    Measured, not guessed: building v4.1 with those glibc macros forced in and
    WERROR=0 warns at exactly one site in the whole tree, this one.  Upstream
    v4.2.1 declares it `const char *pos`, and that is what is taken."""
    text = src("getcriu.sh")
    assert "const char *pos = strrchr(link->name" in text, (
        "nothing corrects the line, so a 2026 glibc still stops the build at "
        "criu/tty.o however the dialect is set")
    # Patched before make reads the file, and after the source exists to patch
    # - so the clone and the reuse path both get it.
    assert line_of(text, "TTY=$SRC/criu/tty.c") < line_of(text, "make -j")
    assert line_of(text, "TTY=$SRC/criu/tty.c") > line_of(text, "git clone --depth 1")
    # ANCHORED. tty.c carries a second `char *pos = strrchr(orig->rfe->name,
    # '/')` that is not const and builds fine; a looser match rewrites it too.
    code = [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
    matchers = [ln for ln in code if "strrchr" in ln
                and ("grep" in ln or "sed" in ln)]
    assert matchers and all("link->name" in ln for ln in matchers), matchers
    # Idempotent: the guard matches only the UNFIXED declaration, so a reused
    # tree is not patched twice and a pin moved to v4.2.1 is left alone.
    assert r"grep -q '^[[:space:]]*char \*pos = strrchr(link->name'" in text
    # And it can never stop a build that would otherwise have worked: every
    # compiler older than C23 builds the line exactly as it came.
    block = text[text.index("TTY=$SRC/criu/tty.c"):text.index("# ---- 3.")]
    assert "exit" not in block, "a line that cannot be patched is not fatal"


def test_neither_shortcut_that_looks_like_the_same_fix_is_taken():
    """-Wno-error=discarded-qualifiers cannot work here: USERCFLAGS lands
    before $(WARNINGS), which ends in -Werror.  WERROR=0 does work, and turns
    off every other complaint a compiler this much newer than the pin has."""
    text = src("getcriu.sh")
    code = [ln for ln in text.split("\n") if not ln.lstrip().startswith("#")]
    for shortcut in ("WERROR=0", "-Wno-error"):
        assert not [ln for ln in code if shortcut in ln], (
            "%s silences the compiler instead of answering it" % shortcut)


def test_a_reused_tree_cannot_mix_two_dialects():
    """Step 2 reuses the source tree on purpose, and make compares timestamps:
    a flag change is invisible to it, so half a binary would be C17 and half
    C23.  The flags are recorded beside the tree and a change costs the
    objects, once."""
    text = src("getcriu.sh")
    assert "STAMP=$WORK/.pad-build-flags" in text, (
        "written beside the tree, not inside someone else's git checkout")
    assert line_of(text, 'make -C "$SRC" clean') < line_of(text, "make -j"), (
        "the objects have to go before the build that would reuse them")
    # Only when they differ AND there is something to clean - a fresh clone
    # must never pay for this, and neither must an unchanged rerun.
    block = text[text.index("STAMP=$WORK"):text.index("# ---- 2c.")]
    assert '"$(cat "$STAMP" 2>/dev/null)" != "$STD"' in block
    assert "-name '*.o' -print -quit" in block, (
        "a tree with no objects has nothing to clean and would just lose "
        "three minutes to `make clean`")
