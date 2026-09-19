"""Item 128: the /etc/init.d/game_monitor hook, and above all its INVERSE.

"Removing the mode leaves the card stock" is one of item 128's acceptance
clauses, so the round-trip here runs against the REAL game_monitor - the bytes
read off a stock Godzilla Pro 1.15 p2 with
`debugfs -R "cat /etc/init.d/game_monitor"`, tabs and all - and demands the text
come back byte for byte. A paraphrase would pass while the real thing failed.

These tests are written against the SPECIFICATION, not against what the module
currently does: has_hook was written wrong twice while this file was being
prepared (once always-False, once comparing a string to a list), and tests
derived from the code would have agreed with the bug both times.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "tools", "spike2_emu"))

import modehook  # noqa: E402


#: The stock script, verbatim. Tabs are real tabs: `cat -A` showed the loop body
#: as "^I$1$", which is exactly the anchor modehook keys on.
STOCK = (
    "#!/bin/sh\n"
    "\n"
    "# set up core dump\n"
    "ulimit -c unlimited\n"
    "echo /dump/core > /proc/sys/kernel/core_pattern\n"
    "\n"
    "while [ true ] ;\n"
    "do\n"
    "\t$1\n"
    "\t/usr/local/bin/boot_display&\n"
    "\teval /usr/local/bin/dprint \"\\ \\ RESTARTING\\ \\ GAME\"\n"
    "\tsleep 1\n"
    "\tpkill boot_display\n"
    "done\n"
)


def test_stock_script_is_not_hooked():
    assert modehook.has_hook(STOCK) is False
    assert "stock" in modehook.describe(STOCK)


def test_hook_then_strip_restores_the_card_byte_for_byte():
    """THE ACCEPTANCE CLAUSE: removing the mode leaves the card stock."""
    hooked = modehook.hook_game_monitor(STOCK)
    assert hooked != STOCK
    assert modehook.strip_hook(hooked) == STOCK


def test_hook_preloads_only_the_game():
    """The assignment must be command-scoped, on the $1 line and nowhere else.

    An exported LD_PRELOAD would reach boot_display, dprint and pkill on the
    restart path - and, if this hook were ever put in /etc/init.d/game instead,
    conagent. The whole reason this edit targets game_monitor is that a
    command-scoped assignment cannot leak.
    """
    hooked = modehook.hook_game_monitor(STOCK)
    lines = hooked.split("\n")
    preload = [l for l in lines if "LD_PRELOAD" in l]
    assert len(preload) == 1
    assert preload[0] == "\t\tLD_PRELOAD=" + modehook.MODE_SO + " $1"
    assert "export" not in hooked
    # the restart lines are untouched and still follow the block
    assert "\t/usr/local/bin/boot_display&" in lines
    assert "\tpkill boot_display" in lines


def test_hook_is_guarded_so_a_removed_mode_runs_stock():
    hooked = modehook.hook_game_monitor(STOCK)
    assert "\tif [ -f " + modehook.MODE_SO + " ]; then" in hooked
    assert "\t\t$1" in hooked          # the else branch is the stock invocation


def test_hook_is_idempotent():
    once = modehook.hook_game_monitor(STOCK)
    twice = modehook.hook_game_monitor(once)
    assert twice == once
    assert modehook.has_hook(once) is True


def test_has_hook_is_the_same_question_as_strip():
    """One definition of "is it hooked", not two that can drift apart."""
    hooked = modehook.hook_game_monitor(STOCK)
    assert modehook.has_hook(hooked) is (modehook.strip_hook(hooked) != hooked)
    assert modehook.has_hook(STOCK) is (modehook.strip_hook(STOCK) != STOCK)


def test_strip_on_a_stock_script_changes_nothing():
    assert modehook.strip_hook(STOCK) == STOCK


def test_refuses_a_script_with_no_anchor():
    """Never guess: a script we do not recognise is not edited at all."""
    with pytest.raises(modehook.Refused) as e:
        modehook.hook_game_monitor(STOCK.replace("\t$1\n", "\t/games/game\n"))
    assert "exactly one" in str(e.value)


def test_refuses_a_script_with_two_anchors():
    doubled = STOCK.replace("\t$1\n", "\t$1\n\t$1\n")
    with pytest.raises(modehook.Refused) as e:
        modehook.hook_game_monitor(doubled)
    assert "found 2" in str(e.value)


def test_accepts_bytes_as_well_as_text():
    hooked = modehook.hook_game_monitor(STOCK.encode("utf-8"))
    assert modehook.strip_hook(hooked.encode("utf-8")) == STOCK


def test_a_lookalike_line_is_not_the_anchor():
    """The anchor is byte-exact: one tab then $1, not `$1` with other spacing.

    mkmulticard keeps Stern's trailing space in PKILL_LINE for the same reason -
    an anchor that matches loosely is an anchor that edits the wrong card.
    """
    spaced = STOCK.replace("\t$1\n", "    $1\n")
    with pytest.raises(modehook.Refused):
        modehook.hook_game_monitor(spaced)
