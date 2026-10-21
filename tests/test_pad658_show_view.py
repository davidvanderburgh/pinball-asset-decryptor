"""PAD-658: a blocks mode's light show, on the emulator's playfield view as the Modes tab's preview shows it.

David could not see his modes' light shows in the emulator. On the wire they played (a show paints every placed
insert each tick); the view missed them for two reasons, both fixed here:

- the game sends that many held inserts as LONG bitmap frames, which the shim's view (padled) dropped on the insert
  boards of a title whose dialect verdict is in (Godzilla LE 1.16) - tests/test_spike2_led_wide_settled_title.py and
  test_spike2_cabinet_lights.py carry that half;
- a one-colour insert takes one level, the colour's brightest part, and the view drew every one on its orange ramp,
  so a red or blue show read as yellow dots. The mode runtime now publishes the colour it painted (padled's paint
  plane, after version 6's hi plane). PAD-668 took the hue back off the picture - on the machine a one-colour insert
  glows in its lens's colour, never the show's - and puts it in the insert's tooltip instead
  (tests/test_spike2_playfield_web.py, test_a_mode_s_colour_on_a_one_colour_insert_is_named_not_drawn).
"""
import os
import re
import shutil
import struct
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "tools", "spike2_emu")
SDK = os.path.join(RIG, "modes", "sdk")
sys.path.insert(0, RIG)
import coilmap  # noqa: E402

from tests.test_spike2_mode_lamps import runtime  # noqa: E402,F401  (the runtime's lamp section, host-compiled)

CC = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")


def _read(*p):
    with open(os.path.join(*p), encoding="utf-8") as f:
        return f.read()


def test_the_paint_plane_is_where_padled_h_and_the_runtime_say():
    rt = _read(SDK, "pad_mode_runtime.c")
    assert int(re.search(r"#define PAINT_OFF\s+(\d+)u", rt).group(1)) == coilmap.PAINT_OFF == 13500
    assert int(re.search(r"#define PAINT_MAGIC\s+(0x[0-9a-fA-F]+)u", rt).group(1), 16) == coilmap.PAINT_MAGIC
    hdr = _read(RIG, "padled.h")
    assert "paint_magic 13500, paint_gen 13504, paint 13508" in hdr
    assert coilmap.PAINT_READ <= int(re.search(r"#define PADLED_BYTES (\d+)", hdr).group(1))


@pytest.mark.skipif(CC is None, reason="no C compiler on this host")
def test_padled_h_puts_the_plane_after_hi(tmp_path):
    hdr = _read(RIG, "padled.h")
    prog = hdr + r"""
#include <stdio.h>
#include <stddef.h>
int main(void)
{
    printf("%u %u %u %u\n", (unsigned)offsetof(struct padled_shm, paint_magic), (unsigned)offsetof(struct padled_shm,
           paint_gen), (unsigned)offsetof(struct padled_shm, paint), (unsigned)sizeof(struct padled_shm));
    return 0;
}
"""
    (tmp_path / "p.c").write_text(prog, encoding="utf-8")
    exe = tmp_path / ("p.exe" if os.name == "nt" else "p")
    r = subprocess.run([CC, "-o", str(exe), str(tmp_path / "p.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    off, gen, ents, size = (int(x) for x in subprocess.run([str(exe)], capture_output=True, text=True).stdout.split())
    assert (off, gen, ents) == (coilmap.PAINT_OFF, coilmap.PAINT_OFF + 4, coilmap.PAINT_OFF + 8)
    assert size >= coilmap.PAINT_READ


def _block(entries):
    b = bytearray(16384)
    struct.pack_into("<I", b, coilmap.PAINT_OFF, coilmap.PAINT_MAGIC)
    for k, e in entries.items():
        b[coilmap.PAINT_OFF + 8 + 8 * k:coilmap.PAINT_OFF + 14 + 8 * k] = bytes(e)
    return bytes(b)


def test_the_view_reads_the_tints_by_its_own_group_to_node_map():
    gn = {6: 8, 7: 9}
    blk = _block({0: (6, 7, 255, 0, 0, 1), 1: (7, 44, 0, 64, 255, 1), 2: (6, 9, 255, 255, 255, 0),
                  3: (5, 1, 0, 255, 0, 1)})       # off, and a group the map has no node for
    assert coilmap.paint_tints(blk, gn) == {(8, 7): (255, 0, 0), (9, 44): (0, 64, 255)}
    assert coilmap.paint_tints(bytes(16384), gn) == {}            # no runtime wrote it: no plane
    assert coilmap.paint_tints(blk[:9000], gn) == {}              # an older watch.sh's block


# the runtime's lamp section with the port's "I/O group G index I" comments (Godzilla LE 1.16's own lines)
PORT = ["lamp", "298 0x8000000 MASER  # lamp 11, I/O group 7 index 21, at 150,320",
        "lamp", "346,347,348 0x100000 LEFT RAMP  # lamp 143, I/O group 6 index 30, at 80,300",
        "lamp", "377 0 HEAT RAY L1"]


def _plane(path):
    with open(path, "rb") as f:
        d = f.read()
    magic, gen = struct.unpack_from("<II", d, coilmap.PAINT_OFF)
    ents = [tuple(d[coilmap.PAINT_OFF + 8 + 8 * k:coilmap.PAINT_OFF + 14 + 8 * k]) for k in range(3)]
    return magic, gen, ents


def test_the_runtime_publishes_a_one_colour_insert_s_colour_and_takes_it_back(runtime, tmp_path):  # noqa: F811
    shm = tmp_path / "padled"
    shm.write_bytes(bytes(16384))
    env = dict(os.environ, PAD_LED_SHM=str(shm))
    r = subprocess.run([str(runtime), *PORT, "arm", "tick", "1", "as", "A",
                        "set", "2040ff", "0", "0", "MASER,LEFT RAMP,HEAT RAY L1", "tick", "1"],
                       capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    magic, gen, ents = _plane(shm)
    assert magic == coilmap.PAINT_MAGIC and gen >= 1
    assert ents[0] == (7, 21, 0x20, 0x40, 0xff, 1)     # MASER, one colour: its group/index and the colour painted
    assert ents[1] == (0, 0, 0, 0, 0, 0)                # LEFT RAMP is RGB: the wire carries its colour itself
    assert ents[2] == (0, 0, 0, 0, 0, 0)                # HEAT RAY L1's line names no I/O place: nothing to say
    assert coilmap.paint_tints(shm.read_bytes(), {7: 9}) == {(9, 21): (0x20, 0x40, 0xff)}
    shm.write_bytes(bytes(16384))
    r = subprocess.run([str(runtime), *PORT, "arm", "tick", "1", "as", "A",
                        "set", "2040ff", "0", "0", "MASER", "tick", "1", "release", "MASER"],
                       capture_output=True, text=True, timeout=30, env=env)
    assert r.returncode == 0, r.stderr
    assert _plane(shm)[2][0][5] == 0                    # handed back to the game: no colour of ours


def test_a_block_too_small_for_the_plane_is_left_alone(runtime, tmp_path):  # noqa: F811
    shm = tmp_path / "padled"
    shm.write_bytes(bytes(8192))
    r = subprocess.run([str(runtime), *PORT, "arm", "tick", "1", "as", "A", "set", "ff0000", "0", "0", "MASER",
                        "tick", "1"], capture_output=True, text=True, timeout=30, env=dict(os.environ, PAD_LED_SHM=str(shm)))
    assert r.returncode == 0, r.stderr
    assert shm.read_bytes() == bytes(8192)


def test_the_view_draws_a_lit_insert_with_the_preview_s_glow():
    js = _read(RIG, "pfpage", "pf.js")
    css = _read(ROOT, "pinball_decryptor", "webui", "static", "css", "tabs", "modes.css")
    assert "drop-shadow(0 0 5px currentColor) drop-shadow(0 0 10px currentColor)" in css    # the preview's look
    assert "g.shadowBlur = 10 * dpr; g.fill();" in js and "g.shadowBlur = 5 * dpr; g.fill();" in js
