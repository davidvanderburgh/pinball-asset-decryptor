"""PAD-1283: a mode's lamps and the game's own light shows on a Spike 3 (64-bit ARM) game.

What the work found, held here at the desk (no card, no emulator):
- the lamp layer and the game's show processes read the game's structs with 4-byte pointers. Star Wars ELG 1.10's
  Spike 3 build has the same code with 8-byte ones: the layer heads (free, active) a pointer each, a lamp group's
  priority at +8 and next at +32 (Spike 2: +4, +20), its owner event at +24, the 40-byte slot unchanged; a process
  record 376 bytes, next at +232, the show id at +258, four {fn, arg} exit hooks of 16 bytes at +0x138.
- the allocator keeps its fourth argument as a callback (+16) that its compositor calls when it is not 0, so the
  runtime passes all four pointer-sized.
- s3port.py reads all of it off the program (light_engine), carries the Spike 2 port's shows by their record in the
  show table (ELG: 5 of 7 - Spike 3's table has 128 shows, Spike 2's 137) and its lamp lines by name (67 of 68).
Emulator proof: docs/plans/spike3_modes.md "Lamps and light shows on Spike 3 (PAD-1283)".
Spike 2's mode.so stays byte-identical (tests/test_stern_mode_runtime.py holds the prebuilt).
"""
import importlib.util
import os
import pathlib
import re

import pytest

from tests.test_spike2_mode_roster import _lift

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"
# the two Star Wars ELG 1.10 programs, where a machine keeps them (PAD-1271's scratch): the reader's real-program test
ELG2, ELG3 = r"C:\tmp\PAD-1271\elg2.game", r"C:\tmp\PAD-1271\elg3.game"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _s3port():
    spec = importlib.util.spec_from_file_location("s3port", ROOT / "tools" / "spike3_emu" / "s3port.py")
    S = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(S)
    return S


# ---- the runtime ----------------------------------------------------------------------------------------------
def test_the_lamp_layer_reads_its_pointers_pointer_sized():
    src = _src()
    first = _lift(src, "static unsigned char *lamp_first_layer(void)")
    assert "*(pm_addr *)(unsigned long)(heads + PM_PTR)" in first and "heads + 4" not in first
    nxt = _lift(src, "static unsigned char *lamp_next_layer(unsigned char *g)")
    assert '*(pm_addr *)(g + pm_port_value("lamp_group_next", 20))' in nxt
    slot = _lift(src, "static unsigned char *lamp_slot(unsigned char *group, unsigned light)")
    assert "base = *(pm_addr *)group;" in slot and "*(unsigned *)group" not in slot
    new = _lift(src, "static unsigned char *lamp_group_new(unsigned prio)")
    assert 'pm_addr cur = data("event_current")' in new and "*(pm_addr *)(unsigned long)cur = 0;" in new
    lights = _lift(src, "int pm_lights_as(unsigned owner, const char *command)")
    assert 'pm_addr cur = data("event_current");' in lights
    assert not re.search(r'unsigned [a-z, =0]*\bcur = data\("event_current"\)', src)


def test_the_allocator_gets_four_pointer_sized_arguments():
    """the 64-bit allocator stores the fourth as a callback its compositor calls when it is not 0"""
    src = _src()
    assert "typedef pm_addr (*lamp_group_fn)(pm_addr, pm_addr, pm_addr, pm_addr);" in src
    assert src.count("(lamp_group_fn)(unsigned long)") == 2
    assert not re.search(r'\((void \*|unsigned long) \(\*\)\(unsigned, unsigned, unsigned, unsigned\)\)\(unsigned long\)'
                         r'(f|fn\("lamp_group"\))', src)


def test_a_show_process_record_and_its_exit_hooks_are_pointer_sized():
    src = _src()
    assert "typedef pm_addr (*proc_create_fn)(unsigned, void (*)(void), unsigned);" in src
    assert src.count("((proc_create_fn)(unsigned long)fn(\"proc_create\"))") == 2
    hook = _lift(src, "static int show_exit_hook(pm_addr rec)")
    assert "pm_addr *slot = (pm_addr *)(unsigned long)(rec + off + 2u * (unsigned)PM_PTR * i);" in hook
    assert "slot[0] = (pm_addr)(unsigned long)show_exit;" in hook
    assert "static void show_exit(pm_addr rec, pm_addr arg)" in src
    show = _lift(src, "int pm_game_show(int n)")
    assert "pm_addr rec;" in show


def test_the_stock_calls_hold_their_sites_pointer_sized():
    src = _src()
    assert "static pm_addr stock161_site(const char *name)" in src
    assert "static pm_addr stock161_data(const char *name)" in src
    for name in ("show_start", "event_post_replacing", "event_cancel"):
        assert 'pm_addr f = stock161_site("%s");' % name in src
    assert "void *pm_stock_display_event(unsigned id, unsigned long handler, unsigned flags)" in src
    assert "unsigned long handler" in (SDK / "pad_stock.h").read_text(encoding="utf-8")


# ---- the port -------------------------------------------------------------------------------------------------
def _lines(kind):
    return [raw.split() for raw in PORT.read_text(encoding="utf-8").splitlines() if raw.split()[:1] == [kind]]


def test_elg_spike3_port_carries_the_lamp_layer_and_the_processes():
    sites = {t[1]: t[2] for t in _lines("site")}
    assert {k: sites[k] for k in ("lamp_group", "lamp_free_owner", "show_priority", "show_start",
                                  "event_post_replacing", "event_cancel", "proc_exists", "proc_create")} == {
        "lamp_group": "0x001a0470", "lamp_free_owner": "0x00236d30", "show_priority": "0x0041a270",
        "show_start": "0x0041a000", "event_post_replacing": "0x003151f0", "event_cancel": "0x003150f0",
        "proc_exists": "0x003156d0", "proc_create": "0x00314e80"}
    data = {t[1]: t[2] for t in _lines("data")}
    assert {k: data[k] for k in ("event_head", "event_current", "lamp_layers", "light_count")} == {
        "event_head": "0x007493d8", "event_current": "0x007493e0", "lamp_layers": "0x00735e68",
        "light_count": "0x0073ec88"}
    values = {t[1]: int(t[2], 0) for t in _lines("value")}
    assert {k: values[k] for k in ("lamp_slot_size", "lamp_slot_level", "lamp_slot_alpha", "lamp_slot_fade",
                                   "lamp_slot_used", "lamp_group_prio", "lamp_group_next", "event_next",
                                   "event_flags", "event_show_flag", "event_show_id", "proc_exit_hooks",
                                   "proc_exit_slots", "show_proc")} == {
        "lamp_slot_size": 40, "lamp_slot_level": 2, "lamp_slot_alpha": 3, "lamp_slot_fade": 8, "lamp_slot_used": 36,
        "lamp_group_prio": 8, "lamp_group_next": 32, "event_next": 232, "event_flags": 2, "event_show_flag": 0x20,
        "event_show_id": 258, "proc_exit_hooks": 0x138, "proc_exit_slots": 4, "show_proc": 13201}
    assert "lamp_group_owner" not in values and "proc_record_size" not in values


def test_elg_spike3_port_carries_five_of_the_games_shows_by_name():
    sites = {t[1]: t[2] for t in _lines("site")}
    texts = {t[1]: " ".join(t[2:]) for t in _lines("text")}
    values = {t[1]: int(t[2], 0) for t in _lines("value")}
    shows = [(sites["show_%d" % n], texts["show_name_%d" % n], values["show_secs_%d" % n]) for n in range(1, 6)]
    assert shows == [("0x00185ab0", "Wide fast strobe", 8), ("0x00157190", "Wide strobe", 8),
                     ("0x00148a20", "Wide chase", 8), ("0x00148b10", "Small fast strobe", 8),
                     ("0x00148d30", "Fast strobe", 2)]
    assert "show_6" not in sites
    text = PORT.read_text(encoding="utf-8")
    assert "(Small strobe) not carried: past the 128 shows of Spike 3's table" in text
    assert "(Small glow) not carried: past the 128 shows of Spike 3's table" in text


def test_elg_spike3_port_carries_the_lamp_lines_by_name():
    text = PORT.read_text(encoding="utf-8")
    lamps = [l for l in text.splitlines() if l.startswith("lamp ")]
    assert len(lamps) == 67
    assert all("I/O group 6 index" in l for l in lamps)
    assert any(l.startswith("lamp 66 ") and "DEATH STAR (X2)" in l and "index 51" in l for l in lamps)
    assert "# lamp NOT PLACED: no lamp named 'MILLENNIUM FALCON (OPTIONAL)' on Spike 3" in text
    assert "not carried (to measure on Spike 3): 1 scene\n" in text            # PAD-1284 carries hud, video_bank;
    #                                       PAD-1285 the held coil's and block names, PAD-1286 done_name_0


# ---- the drafter ----------------------------------------------------------------------------------------------
def test_s3port_carries_the_light_entries():
    S = _s3port()
    assert {"lamp_group", "show_priority", "show_start", "event_post_replacing", "event_cancel", "proc_exists",
            "proc_create"} <= set(S.SITES_PROVEN)
    assert {"event_head", "event_current", "lamp_layers", "light_count"} <= set(S.DATA_PROVEN)


def test_s3port_decodes_the_load_store_words():
    S = _s3port()
    assert S._ls(0xF94736B3) == ("ldr", 19, 21, 3688, None)        # ldr x19, [x21, #3688] (the free head)
    assert S._ls(0x39002274) == ("strb", 20, 19, 8, None)         # strb w20, [x19, #8] (a group's priority)
    assert S._ls(0xA9418823) == ("ldp", 3, 1, 24, 2)               # ldp x3, x2, [x1, #24] (owner, next)
    assert S._ls(0xA9010276) == ("stp", 22, 19, 16, 0)            # stp x22, x0, [x19, #16] (period, owner)
    assert S._ls(0x79420422) == ("ldrh", 2, 1, 258, None)         # ldrh w2, [x1, #258] (the show id)
    assert S._ls(0x91000000) is None
    assert S._tbz_bit(0x36280202) == (2, 5)                        # tbz w2, #5 (the show flag 0x20)
    assert S._tbz_bit(0x91000000) is None


@pytest.mark.skipif(not (os.path.isfile(ELG2) and os.path.isfile(ELG3)), reason="the Star Wars ELG programs are not here")
def test_light_engine_reads_the_elg_program():
    S = _s3port()
    ref, tgt = S.Elf(ELG2), S.Elf(ELG3)
    S.scan(ref)
    S.scan(tgt)
    lines = S.read_port(str(SDK / "ports" / "star_wars_elg-1.10.port"))
    o = S.light_engine(ref, lines, tgt, dict(lamp_group=0x1a0470, proc_create=0x314e80, show_priority=0x41a270,
                                             show_start=0x41a000))
    assert o["why"] == []
    assert o["site"]["lamp_free_owner"] == 0x236d30
    assert S.processes(tgt, 0x314e80)["site"]["proc_exit"] == 0x3146d0        # the exit that calls the hooks
    assert o["data"] == {"lamp_layers": 0x735e68, "light_count": 0x73ec88, "event_current": 0x7493e0,
                         "event_head": 0x7493d8}
    assert o["value"]["lamp_group_owner"] == 24 and o["value"]["proc_record_size"] == 376
    assert sum(1 for l in o["show"] if l.startswith("site show_")) == 5
    assert sum(1 for l in o["lamp"] if l.startswith("lamp ")) == 67
    assert S.show_table(ref, 0x13531c) == (0x559bbc, 137, 12)
    assert S.show_table(tgt, 0x41a000) == (0x6c5cb0, 128, 16)


# ---- the Modes tab --------------------------------------------------------------------------------------------
def test_the_spike3_build_offers_inserts_and_the_games_shows():
    from pinball_decryptor.plugins.stern import mode_project as MP
    assert "star_wars_elg-1.10/spike3" in MP.LAMPS_PROVEN
    s3 = MP.profiles()["star_wars_elg_1_10_spike3"]
    assert s3.can("lights") and s3.can("shows")
    assert s3.lamps and len(s3.inserts) == 66                      # DEATH STAR (X2) has two lamp lines
    from pinball_decryptor.webui import help_content as H
    row = [r for r in H.modes_games_rows() if r[0] == "Star Wars ELG 1.10 (Spike 3)"]
    assert row == [("Star Wars ELG 1.10 (Spike 3)", "\u2713", "\u2713", "\u2713", "shots",    # PAD-1284: screens;
                    # PAD-1285: the right gate; it waits for the game's modes. PAD-1286: Ball save, the game's mode
                    # places, its modes completed. PAD-1330: challenges
                    "mechanisms, light shows, challenges, game mode places, starts on game modes completed")]
