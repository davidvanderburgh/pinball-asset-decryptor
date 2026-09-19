"""Item 154 display: display priority for our modes, riding on the game's own display arbitration.

- ``priority <n>`` in a mode file (tools/spike2_emu/modes/sdk/mode_file.c): parsed, held with
  ``pm_display_priority`` at the start (before the screen and the clip) and given up at every end.
  mode_file.c is compiled for the HOST against stubs of the SDK calls (skips without an ELF C compiler).
- The runtime's decisions, lifted verbatim from pad_mode_runtime.c: which of the game's layered displays
  wait for a hold, and pm_set_text sending only a CHANGE (a mode may write its words every tick).
- Both Godzilla ports' display lines, checked against the game programs when they are present (skips
  otherwise): the effect table, the layered-display table, the waiter's call of the layered priority.
- Every port fits the buffer the runtime reads a port into (the display lines grew the Godzilla ports).
"""
import os
import pathlib
import re
import struct
import subprocess

import pytest

from tests.test_spike2_mode_roster import HARNESS, _cc, _host_run, _lift, weak_stubs

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports"

ELVES = {
    "godzilla_pro-1.15.port": [os.environ.get("PAD_GODZILLA_PRO_115_GAME", ""),
                               r"C:\tmp\radium_scene_re\godzilla_pro_1_15\game",
                               "/mnt/c/tmp/radium_scene_re/godzilla_pro_1_15/game"],
    "godzilla_le-1.16.port": [os.environ.get("PAD_GODZILLA_LE_116_GAME", ""),
                              r"C:\tmp\kaiju_premium\stock\game", "/mnt/c/tmp/kaiju_premium/stock/game"],
}


# ---- the mode file's `priority` key ------------------------------------------------------------------
DISPLAY_STUB = r"""
int pm_display_priority(unsigned p) { printf("DISPLAY %u\n", p); return 1; }
int main(int argc"""


@pytest.fixture(scope="module")
def harness(tmp_path_factory):
    cc = _cc()
    d = tmp_path_factory.mktemp("display")
    assert HARNESS.count("int main(int argc") == 1
    (d / "harness.c").write_text(HARNESS.replace("int main(int argc", DISPLAY_STUB))
    stubs, _names = weak_stubs((SDK / "pad_mode.h").read_text(encoding="utf-8"))
    (d / "weak_stubs.c").write_text(stubs)
    for std in ("-std=gnu2x", "-std=gnu17"):
        r = subprocess.run([cc, std, "-w", "-I", str(SDK), "-c", "-o", str(d / "weak_stubs.o"), str(d / "weak_stubs.c")],
                           capture_output=True, text=True)
        if r.returncode == 0:
            break
    assert r.returncode == 0, r.stderr
    exe = d / "harness"
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-I", str(SDK), "-o", str(exe),
                        str(d / "harness.c"), str(SDK / "mode_file.c"), str(d / "weak_stubs.o")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def _run(harness, tmp_path, cfg, *args):
    (tmp_path / "mode.cfg").write_text(cfg)
    env = dict(os.environ, MODE_DIR=str(tmp_path))
    r = subprocess.run([str(harness), *args], capture_output=True, text=True, env=env, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout


RUSH = "name RUSH\ntrigger 0x08000000 1\nseconds 5\nshots 0x00300000\naward 1000000\n"


@pytest.mark.parametrize("how, end", [("ball_end", "END (ball ended)"), ("clock", "END (time ran out)")])
def test_priority_is_held_from_the_start_and_given_up_at_every_end(harness, tmp_path, how, end):
    args = ["shot", "0x08000000"] + (["ball_end"] if how == "ball_end" else ["tick", "400"])
    out = _run(harness, tmp_path, RUSH + "priority 180\n", *args)
    assert "unknown key" not in out
    assert out.count("DISPLAY 180") == 1 and out.count("DISPLAY 0") == 1
    assert out.index("DISPLAY 180") < out.index("RUSH START (trigger shot)")      # before the screen and the clip
    assert out.index("RUSH START") < out.index("DISPLAY 0") < out.index("RUSH " + end)


def test_a_mode_file_without_the_key_never_asks(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH, "shot", "0x08000000", "ball_end")
    assert "RUSH START (trigger shot)" in out and "RUSH END (ball ended)" in out
    assert "DISPLAY" not in out


def test_priority_0_is_no_priority(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH + "priority 0\n", "shot", "0x08000000", "ball_end")
    assert "unknown key" not in out and "DISPLAY" not in out


def test_priority_above_255_is_255(harness, tmp_path):
    out = _run(harness, tmp_path, RUSH + "priority 300\n", "shot", "0x08000000", "ball_end")
    assert "priority 300 is above 255 - 255 is used" in out
    assert "DISPLAY 255" in out and "DISPLAY 0" in out


@pytest.mark.parametrize("value", ["-1", "high", ""])
def test_priority_that_is_not_a_number_is_ignored(harness, tmp_path, value):
    out = _run(harness, tmp_path, RUSH + "priority %s\n" % value, "shot", "0x08000000", "ball_end")
    assert "priority needs a number 0-255" in out
    assert "DISPLAY" not in out and "RUSH START (trigger shot)" in out


# ---- the runtime's decisions, lifted ---------------------------------------------------------------
# flags and priorities of real records of the layered-display table (the same on Pro 1.15 and Premium 1.16)
LAYERED = {
    "big_loop_40": 0x11, "maser_37": 0x01, "powerlines_47": 0x01, "building_101": 0x00, "mb_start_56": 0x51,
    "battle_start_63": 0x71, "total_77": 0x34, "total_84": 0x14, "main_bg_2": 0x03, "rampage_44": 0x01,
}


def test_which_layered_displays_wait_for_a_hold(tmp_path):
    fn = _lift(RUNTIME.read_text(encoding="utf-8"), "static int disp_layered_must_wait(")
    rows = []
    for name, flags in LAYERED.items():
        for hold in (0, 180, 184, 230):
            for clip in (0, 1):
                rows.append('printf("%s %d %d %%d\\n", disp_layered_must_wait(%d, %d, 184, %d));'
                            % (name, hold, clip, flags, hold, clip))
    out = _host_run(tmp_path, "#include <stdio.h>\n" + fn + "\nint main(void) {\n" + "\n".join(rows) + "\nreturn 0; }\n")
    got = {tuple(line.split()[:3]): line.split()[3] for line in out.strip().splitlines()}

    def waits(name, hold, clip):
        return got[(name, str(hold), str(clip))] == "1"

    for name in LAYERED:                                     # no hold: the game's own order, untouched
        assert not waits(name, 0, 0) and not waits(name, 0, 1)
    assert waits("big_loop_40", 180, 0)                      # full screen: waits for any hold
    assert not waits("maser_37", 180, 0) and waits("maser_37", 180, 1)   # framed: only while our clip plays
    assert not waits("building_101", 180, 0) and waits("building_101", 180, 1)
    assert not waits("mb_start_56", 180, 0) and not waits("mb_start_56", 180, 1)  # a mode start beats 180
    assert not waits("battle_start_63", 180, 1) and not waits("total_77", 180, 1)
    assert waits("mb_start_56", 184, 0) and waits("battle_start_63", 230, 0)       # ... and waits at 184 and up
    assert waits("total_84", 230, 0)
    assert not waits("main_bg_2", 230, 1)                    # a background never waits
    assert not waits("rampage_44", 230, 0) and waits("rampage_44", 230, 1)


def test_set_text_sends_only_a_change(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    decl = re.search(r"#define TEXT_LAST \d+\nstatic struct \{[^}]*\} text_last\[TEXT_LAST\];\nstatic unsigned text_last_next;", src)
    assert decl, "the text_last cache moved"
    code = "#include <stdio.h>\n#include <string.h>\n" + _lift(src, "static int str_eq(") + "\n" + decl.group(0) + "\n" + \
        _lift(src, "static int text_unchanged(") + r"""
static int sent;
static void set(void *node, const char *w) { if (!text_unchanged(node, w)) sent++; }
int main(void)
{
    char a, b, nodes[40], big[200];
    int i;
    set(&a, "30.0 S"); set(&a, "30.0 S"); set(&a, "30.0 S"); printf("same %d\n", sent);
    set(&a, "29.9 S"); printf("changed %d\n", sent);
    set(&b, "29.9 S"); printf("other_node %d\n", sent);
    set(&a, "29.9 S"); set(&b, "29.9 S"); printf("both_same %d\n", sent);
    memset(big, 'X', 150); big[150] = 0;
    set(&a, big); set(&a, big); printf("long %d\n", sent);
    set(&a, ""); set(&a, ""); printf("empty_after_long %d\n", sent);
    for (i = 0; i < 40; i++) set(&nodes[i], "N");             /* more nodes than the cache: still correct */
    set(&nodes[0], "N"); printf("evicted %d\n", sent);
    return 0;
}
"""
    out = _host_run(tmp_path, code)
    rows = dict(line.split() for line in out.strip().splitlines())
    assert rows["same"] == "1"                      # three calls, one write
    assert rows["changed"] == "2"
    assert rows["other_node"] == "3"                # each node keeps its own words
    assert rows["both_same"] == "3"
    assert rows["long"] == "5"                      # too long to keep: always written
    assert rows["empty_after_long"] == "6"          # an empty line after a long one is written once
    assert rows["evicted"] == "47"                  # 40 new nodes, then node 0 again (evicted): written


def test_the_runtime_hooks_display_only_with_every_port_line():
    src = RUNTIME.read_text(encoding="utf-8")
    body = _lift(src, "static void display_arm(void)")
    for name in ("display_effect_start", "layered_priority", "display_effects", "layered_displays",
                 "award_screen_arg", "event_current", "display_host", "display_mode_level", "layered_waiter_call"):
        assert '"%s"' % name in body, name
    assert "can |= PM_CAN_DISPLAY_PRIORITY" in body
    assert "display_arm();" in _lift(src, "static void pad_mode_start(void)")
    header = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    flags = [int(v, 16) for v in re.findall(r"#define PM_CAN_\w+\s+(0x[0-9a-fA-F]+)u", header)]
    assert len(flags) == len(set(flags)), "two PM_CAN_ flags share a bit"


# ---- the ports -------------------------------------------------------------------------------------
def _port(name):
    lines = {}
    for line in (PORTS / name).read_text(encoding="utf-8").splitlines():
        parts = line.split("#", 1)[0].split()
        if len(parts) >= 3 and parts[0] in ("site", "data", "value"):
            lines[(parts[0], parts[1])] = [int(p, 0) for p in parts[2:]]
    return lines


def test_every_port_fits_the_runtimes_port_buffer():
    cap = int(re.search(r"#define PORT_MAX\s+(\d+)", RUNTIME.read_text(encoding="utf-8")).group(1))
    for p in sorted(PORTS.glob("*.port")):
        assert p.stat().st_size < cap, "%s is %d bytes; the runtime reads %d" % (p.name, p.stat().st_size, cap - 1)


@pytest.mark.parametrize("name", sorted(ELVES))
def test_both_godzilla_ports_name_the_display_arbitration(name):
    port = _port(name)
    for key in (("site", "display_effect_start"), ("site", "display_effect_next"), ("site", "layered_priority"),
                ("site", "display_priority_now"),
                ("data", "display_effects"), ("data", "layered_displays"), ("value", "display_host"),
                ("value", "display_mode_level"), ("value", "layered_waiter_call"), ("value", "effect_waiter_call")):
        assert key in port, key
    assert port[("value", "display_host")] == [29] and port[("value", "display_mode_level")] == [184]


class _Elf:
    def __init__(self, path):
        self.b = open(path, "rb").read()
        phoff, = struct.unpack_from("<I", self.b, 0x1C)
        phnum, = struct.unpack_from("<H", self.b, 0x2C)
        self.loads = []
        for i in range(phnum):
            t, off, va, _pa, fsz = struct.unpack_from("<IIIII", self.b, phoff + 32 * i)
            if t == 1:
                self.loads.append((va, off, fsz))

    def u32(self, va, fmt="<I"):
        for base, off, size in self.loads:
            if base <= va < base + size:
                return struct.unpack_from(fmt, self.b, off + va - base)[0]
        raise KeyError(hex(va))


@pytest.mark.parametrize("name", sorted(ELVES))
def test_the_display_lines_match_the_game(name):
    path = next((p for p in ELVES[name] if p and os.path.isfile(p)), None)
    if not path:
        pytest.skip("game program not present for %s" % name)
    e, port = _Elf(path), _port(name)
    for (kind, key), v in port.items():                      # the words of every display site
        if kind == "site" and key in ("display_effect_start", "display_effect_next", "layered_priority",
                                      "display_priority_now"):
            assert (e.u32(v[0]), e.u32(v[0] + 4)) == (v[1], v[2]), key
    effects = port[("data", "award_screen_arg")][0]
    recs, count = e.u32(effects), e.u32(effects + 4)
    assert count == 152

    def effect(i):
        return e.u32(recs + 8 * i + 4, "<H"), e.u32(recs + 8 * i + 6, "<B")

    assert effect(29) == (1, 1)                              # the layered display: a background, priority 1
    assert effect(1) == (1, 1) and effect(31) == (1, 1)      # attract, the tilt
    assert effect(128)[1] == 177 and effect(126)[1] == 201 and effect(79)[1] == 184 and effect(33)[1] == 241
    layered = port[("data", "layered_displays")][0]
    lrecs, lcount = e.u32(layered), e.u32(layered + 4)
    assert lcount == 111

    def lay(i):
        return e.u32(lrecs + 16 * i), e.u32(lrecs + 16 * i + 12, "<B")

    assert lay(40) == (0x11, 113) and lay(37) == (0x01, 111) and lay(47) == (0x01, 110) and lay(101) == (0x00, 116)
    assert lay(56) == (0x51, 135) and lay(2) == (0x03, 81)
    # the waiter's call of the layered priority returns to layered_waiter_call
    call = port[("value", "layered_waiter_call")][0] - 4
    w = e.u32(call)
    off = w & 0xFFFFFF
    off = off - 0x1000000 if off & 0x800000 else off
    assert (w & 0x0F000000) == 0x0B000000 and call + 8 + 4 * off == port[("site", "layered_priority")][0]
    # the effect waiter's call of the priority getter's wrapper returns to effect_waiter_call; the wrapper
    # tail-calls display_priority_now, so that is the return address the leaf sees
    call = port[("value", "effect_waiter_call")][0] - 4
    w = e.u32(call)
    off = w & 0xFFFFFF
    off = off - 0x1000000 if off & 0x800000 else off
    wrapper = call + 8 + 4 * off
    assert (w & 0x0F000000) == 0x0B000000
    tail = e.u32(wrapper + 12)
    toff = tail & 0xFFFFFF
    toff = toff - 0x1000000 if toff & 0x800000 else toff
    assert (tail & 0x0F000000) == 0x0A000000 and wrapper + 12 + 8 + 4 * toff == port[("site", "display_priority_now")][0]
    # the effect priority now is a two-instruction leaf (ldrb r0, [r0, #0xe]; bx lr): hooking it moves both whole
    assert port[("site", "display_priority_now")][1:] == [0xE5D0000E, 0xE12FFF1E]
    # the effect manager is the one the start function loads: *display_effects is checked against the table at run time
    assert port[("data", "display_effects")][0] > effects


# ---- item 157: a layered display a hold would keep waiting is DROPPED at its waiter ---------------------
# While a layered waiter waits the game presents no frames (the showcase run: 3.8-8.1 s freezes ending at the
# release; the integration run 1: 8.3 s), so the waiter's entry is hooked and told it may wait 0 frames.
@pytest.mark.parametrize("name", sorted(ELVES))
def test_both_godzilla_ports_name_the_layered_waiter_around_its_priority_call(name):
    port = _port(name)
    waiter = port[("site", "layered_waiter")]
    assert waiter[1] == 0xE92D4FF0                                          # push {r4-fp, lr}
    assert waiter[0] + 0x58 == port[("value", "layered_waiter_call")][0]    # its own call of the layered priority


@pytest.mark.parametrize("name", sorted(ELVES))
def test_the_layered_waiter_line_matches_the_game_and_zero_frames_returns_at_once(name):
    path = next((p for p in ELVES[name] if p and os.path.isfile(p)), None)
    if not path:
        pytest.skip("game program not present for %s" % name)
    e, port = _Elf(path), _port(name)
    w, w0, w1 = port[("site", "layered_waiter")]
    assert (e.u32(w), e.u32(w + 4)) == (w0, w1)
    assert e.u32(w + 0x10) == 0xE1A05001                                    # mov r5, r1: the frames it may wait
    assert e.u32(w + 0x30) == 0xE3550000                                    # cmp r5, #0
    beq = e.u32(w + 0x34)
    off = beq & 0xFFFFFF
    target = w + 0x34 + 8 + 4 * (off - 0x1000000 if off & 0x800000 else off)
    assert (beq & 0xFF000000) == 0x0A000000                                 # beq: no frames, straight to...
    assert (e.u32(target), e.u32(target + 8)) == (0xE3A00000, 0xE8BD8FF0)  # mov r0, #0 ... pop {.., pc}: not shown
    tail = e.u32(w + 0x1BC)                                                 # the layered display's start tail-calls it
    toff = tail & 0xFFFFFF
    assert (tail & 0xFF000000) == 0xEA000000 and w + 0x1BC + 8 + 4 * (toff - 0x1000000 if toff & 0x800000 else toff) == w


def test_the_runtime_drops_at_the_waiter_only_what_the_hold_would_keep_waiting():
    src = RUNTIME.read_text(encoding="utf-8")
    body = _lift(src, "static void on_layered_waiter(unsigned *r)")
    assert "if (!disp_prio || !r[1]) return;" in body                       # no hold: the game's own wait
    assert body.index("disp_layered_must_wait(") < body.index("r[1] = 0;")  # the same rule as the wait it replaces
    assert '"layered_waiter"' in _lift(src, "static void display_arm(void)")
