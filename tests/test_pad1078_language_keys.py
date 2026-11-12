"""PAD-1078 (DoomWalrus666, Godzilla): "holding the right flipper and pressing start button also changes the language to
Japanese", and in co-op "selecting a character is also changing the language".

Godzilla's PLAYER LANGUAGE SELECT is RuleCities' switch method (`site language_keys`): it flips the player up between
English and Japanese at each release of a flipper BUTTON, which reaches it as the cabinet input 137 / 139, not as the
playfield records 60 / 59 that PAD-1051 keeps from the game. The runtime vetoes the method for a flipper's key while the
co-op pick has that flipper or still hides it (pad_mode_runtime.c "PAD-1078"); emulator-proven on Godzilla LE 1.16.
"""
import os
import pathlib
import struct

import pytest

from tests import test_pad1051_pick_buttons_hidden as H
from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "ports"
SITES = {"godzilla_le-1.16": 0x13f7d0, "godzilla_pro-1.15": 0x13c3b8, "godzilla_pro-1.16": 0x13c3b8}

VETO_MAIN = r"""
#include <stdio.h>
static unsigned coop_left = 60;
static struct { unsigned button; } coop = { 59 };
static int edge_hid_n, pick_has, still_hidden;
static struct { int film_veto; unsigned long film_at; } ci;   /* PAD-1114: the intro's held-flipper veto: none here */
static int ci_film_due(void) { return 0; }
static int coop_hides(unsigned id) { return pick_has && (id == 59 || id == 60); }
static int edge_hidden(unsigned id) { return still_hidden && id == 59 ? 0 : -1; }
@FN@
static void row(const char *what)
{
    printf("%s %d%d%d\n", what, coop_language_veto(137, 137, 139), coop_language_veto(139, 137, 139),
           coop_language_veto(59, 137, 139));
}
int main(void)
{
    row("no pick");
    pick_has = 1; row("the pick has the flippers");
    pick_has = 0; edge_hid_n = 1; still_hidden = 1; row("the right one still hidden");
    still_hidden = 0; row("given back");
    coop_left = 0; pick_has = 1; row("no left in coop.cfg");
    return 0;
}
"""


def test_the_language_select_is_kept_from_a_flipper_the_pick_has(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static int coop_language_veto(unsigned sw, unsigned left_key, unsigned right_key)\n{")
    out = R._host_run(tmp_path, VETO_MAIN.replace("@FN@", fn)).splitlines()
    assert "no pick 000" in out                                  # the game's own select, as stock
    assert "the pick has the flippers 110" in out                # both keys kept; any other switch never
    assert "the right one still hidden 010" in out               # the release of a flipper held through Start
    assert "given back 000" in out                               # after the pick: the flippers choose the language
    assert "no left in coop.cfg 010" in out


def test_the_veto_is_hooked_beside_the_pick():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "hook_veto(fn(\"language_keys\"), on_language_keys)" in src
    hook = R._lift(src, "static int on_language_keys(unsigned *r)\n{")
    assert 'pm_port_value("language_keys_left", 137)' in hook and 'pm_port_value("language_keys_right", 139)' in hook


@pytest.mark.parametrize("port", sorted(SITES))
def test_every_godzilla_port_names_the_language_select(port):
    text = (PORTS / (port + ".port")).read_text(encoding="utf-8")
    line = next(ln for ln in text.splitlines() if ln.startswith("site language_keys"))
    assert int(line.split()[2], 16) == SITES[port]
    assert line.split()[3:5] == ["0xe92d40f8", "0xe1a04001"]     # push {r3-r7, lr}; mov r4, r1 (the switch)
    assert "value language_keys_left   137" in text and "value language_keys_right  139" in text


@pytest.mark.skipif(not os.path.isfile(H.ELF), reason="no Godzilla LE 1.16 program here")
def test_godzillas_language_select_flips_on_the_flipper_keys():
    from elftools.elf.elffile import ELFFile
    with open(H.ELF, "rb") as f:
        data = f.read()
        segs = [(s["p_vaddr"], s["p_offset"], s["p_filesz"]) for s in ELFFile(f).iter_segments()
                if s["p_type"] == "PT_LOAD"]

    def word(va):
        for v, o, n in segs:
            if v <= va < v + n:
                return struct.unpack_from("<I", data, o + va - v)[0]

    assert word(0x13f7d0) == 0xe92d40f8 and word(0x13f7d4) == 0xe1a04001
    assert word(0x13f844) == 0xe3540089                          # cmp r4, #137: the left flipper key
    assert word(0x13f854) == 0xe354008b                          # cmp r4, #139: the right
    assert word(0x13f8bc) == 0xe2877001 and word(0x13f8c0) == 0xe2077001   # flag + 1, & 1: English <-> Japanese


def test_the_how_to_pick_step_fits_the_top_line():
    """Godzilla LE's top line shows 20 characters, then its own CREDITS text (emulator: "ACTION OR LAUNCH TO CREDITS")."""
    import re
    how = R._lift(RUNTIME.read_text(encoding="utf-8"), "static const char *coop_pick_how(void)\n{")
    words = re.findall(r'"([A-Z][A-Z/ ]*)"', how)
    assert words == ["ACTION/LAUNCH PICKS", "ACTION PICKS"]
    assert all(len(w) <= 20 for w in words)
