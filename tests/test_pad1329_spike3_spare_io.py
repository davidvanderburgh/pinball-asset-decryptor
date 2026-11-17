"""PAD-1329: spare switch inputs and driver outputs (PAD-826) on Spike 3's 64-bit programs.

PAD-826's runtime read the switch service's struct, its entries and the coil table at 32-bit offsets, and the Spike 3
ports had no node-bus fire or OFF. Read in each 64-bit program's own code (Star Wars ELG 1.10's addresses):

- the fire-by-address `coil_frame` (0x5151d0: mov x3,#0; mov w2,#0; b 0x514fb0, whose opening refuses a coil above 8 -
  above 15 on Fallout LE and Transformers LE) and the board's OFF `coil_off` (0x50ee60: `8n 02 4d <coil>`);
- the switch service 0x308a10(node, bits[8]): its struct `sw_struct` (0x7477e0: +0 the entries' pointer, 48 bytes each,
  +34 the bit, +36 the board, +40 the level; +0x20 its mutex) and the node blocks, a table of their own `sw_blocks`
  (struct + 0x298; 176 bytes each: +32 the current bits, +40 a u16 id per bit).

pad_mode_runtime.c reads them pointer-sized with that layout on 64-bit ARM (Spike 2's object reads what it always
did); a fire the node bus did not take (it answers 0: Fallout's board-0 records are no node's) is refused, not
counted. The runtime's readable-memory table now merges back-to-back mappings of the same kind and keeps 4096:
Fallout LE's process under the Spike 3 emulator has more than 1024 mappings, and the heap holding its switch entries
fell off the end.

Emulator proof (2026-11-16, Spike 3 rig slots 97-99, hidden, muted; tools/spike3_emu/proofs PROOF=spare with
spare_sweep_mode.c): Star Wars ELG 1.10 - the struct checked out (69 switches), spare input 8:37 closed on the board
came as the mode's shot twice; it has no spare output (one driver board, outputs 0-8 all the game's). Fallout LE 0.82 -
input 8:15 the same; spare output 9:1 on the bus as `n9 40 01 c8 03 ..` (200 for 30 ms), a held command
`.. 3c 2c 01` (60 for 3 s) and its OFF `n9 4d 01` one second in. Pokemon LE, Star Wars 2025 LE / Pro, Transformers LE
and Walking Dead Remastered LE the same, every board's first spare output (mode_project.SPARE_IO_PROVEN).
"""
import os
import pathlib
import re
import shutil
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORTS = SDK / "ports" / "spike3"
PROOFS = ROOT / "tools" / "spike3_emu" / "proofs"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")
NAMES = ("coil_frame", "coil_off", "sw_struct", "sw_blocks")


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(signature)


def _host_run(tmp_path, code):
    cc = shutil.which("gcc") or shutil.which("cc") or shutil.which("clang")
    if not cc:
        pytest.skip("no host C compiler")
    c, exe = tmp_path / "t.c", tmp_path / "t.exe"
    c.write_text(code, encoding="utf-8")
    r = subprocess.run([cc, "-O1", "-w", "-o", str(exe), str(c)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(exe)], capture_output=True, text=True, timeout=30).stdout


def _port(path):
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        p = line.split()
        if len(p) >= 3 and p[0] in ("site", "data"):
            out[p[1]] = [int(w, 16) for w in p[2:5] if re.match(r"0x[0-9a-f]+$", w)]
    return out


# ---- the runtime ------------------------------------------------------------------------------------------------
def test_the_64_bit_layout_is_the_switch_services():
    src = _src()
    a64 = _between(src, "#if PM_A64\n/* PAD-1329", "#else\n#define SW_BLOCK(st, n) ((st) + 16u")
    for d in ('#define SW_BLOCK(st, n) (data("sw_blocks") + (pm_addr)(n) * 176u)', "#define SW_CUR  32u",
              "#define SW_IDS  40u", "#define SW_ENT  48u", "#define SW_ENT_BIT 34u", "#define SW_ENT_NODE 36u",
              "#define SW_ENT_LEVEL 40u", "#define SW_ENT_P1 16u", "#define SW_ENT_P2 24u"):
        assert d in a64, d
    check = _lift(src, "static pm_addr spare_sw_struct(")
    assert "ents = *(const pm_addr *)" in check                      # the entries' pointer, 8 bytes there
    out = _lift(src, "int pm_spare_output(")
    assert "base = *(const pm_addr *)" in out and "sizeof(pm_addr)" in out
    arm = _lift(src, "static void spare_arm(")
    assert 'data("sw_struct") && (!PM_A64 || data("sw_blocks"))' in arm


def test_a_fire_the_bus_did_not_take_is_refused_on_64_bit():
    drive = _lift(_src(), "int pm_spare_drive(")
    i = drive.index("#if PM_A64")
    assert drive.index('fn("coil_frame"))(node, &spec)') < i < drive.index("o->at[o->next] = now | 1;")
    assert "!(rc & 0xffu)" in drive[i:] and "return 0;" in drive[i:drive.index("#endif", i)]


def test_the_struct_check_and_an_input_read_in_the_64_bit_layout(tmp_path):
    """spare_sw_struct / spare_level / pm_spare_switch lifted verbatim with PM_A64 1, against a fake struct laid out as
    Star Wars ELG 1.10's program lays it out: 3 switches of the game's, one entry the map does not route."""
    src = _src()
    macros = _between(src, "#define SPARE_SHOTS        8u", "static int spare_sw_ok;")
    code = r"""
#include <stdio.h>
#include <stdint.h>
#include <string.h>
typedef unsigned long pm_addr;
#define PM_A64 1
#define PMA "lx"
#define MAP_R 1
#define PM_CAN_SPARE_SWITCHES 1u
static unsigned can = PM_CAN_SPARE_SWITCHES;
static unsigned char blocks[32 * 176], ents_mem[16 * 48], devs[64];
static unsigned char st_mem[0x300];
static pm_addr data(const char *n) {
    if (!strcmp(n, "sw_struct")) return (pm_addr)st_mem;
    if (!strcmp(n, "sw_blocks")) return (pm_addr)blocks;
    return 0;
}
static int maps_has(unsigned long a, unsigned long l, unsigned how) { return a != 0; }
static void maps_read(void) {}
static int n_maps;
static void say(const char *f, ...) { printf("SAY %s\n", f); }
static int spare_sw_listen(void) { return 0; }
struct spare_shot { unsigned char node, bit, active_high; };
static struct spare_shot spare_shots[8]; static unsigned n_spare_shots;
@MACROS@
static int spare_sw_ok;
static uint64_t spare_sw_named[SW_NODES];
@STRUCT@
@LEVEL@
@SWITCH@
static void ent(unsigned id, unsigned node, unsigned bit, int mapped) {
    unsigned char *e = ents_mem + id * 48;
    *(pm_addr *)(e + 16) = (pm_addr)devs; *(pm_addr *)(e + 24) = (pm_addr)devs;
    *(unsigned short *)(e + 34) = bit; e[36] = node; e[40] = 1;
    if (mapped) *(unsigned short *)(blocks + node * 176 + 40 + 2 * bit) = id;
}
int main(void) {
    unsigned id;
    int a, b, c;
    *(pm_addr *)st_mem = (pm_addr)ents_mem;
    for (id = 1; id <= 9; id++) ent(id, 8, id + 2, 1);          /* nine of the game's switches on node 8, bits 3..11 */
    ent(10, 8, 14, 0);                                          /* an entry the map leaves out: still the game's */
    blocks[8 * 176 + 32 + 37 / 8] = 0xff;                       /* node 8's current bits: bit 37 open (1) */
    a = pm_spare_switch(8, 37); b = pm_spare_switch(8, 5); c = pm_spare_switch(8, 14);   /* before spare_sw_ok is read */
    printf("%d %d %d %d\n", a, b, c, spare_sw_ok);
    blocks[8 * 176 + 32 + 37 / 8] &= ~(1u << (37 % 8));         /* closed: active low reads 0 */
    printf("%d\n", pm_spare_switch(8, 37));
    *(unsigned short *)(blocks + 9 * 176 + 40) = 3;             /* a map id naming another board's entry */
    spare_sw_ok = 0;
    a = spare_sw_struct() != 0;
    printf("%d %d\n", a, spare_sw_ok);
    return 0;
}
"""
    code = (code.replace("@MACROS@", macros).replace("@STRUCT@", _lift(src, "static pm_addr spare_sw_struct("))
            .replace("@LEVEL@", _lift(src, "static int spare_level(")).replace("@SWITCH@", _lift(src, "int pm_spare_switch(")))
    out = [l for l in _host_run(tmp_path, code).splitlines() if not l.startswith("SAY")]
    assert out == ["0 -1 -1 1", "1", "0 -1"]


def test_the_memory_table_merges_a_run_of_one_kind(tmp_path):
    src = _src()
    maps = _between(src, "#define N_MAPS", "#if !PM_A64\n/* ---- rule 2:")
    assert re.search(r"#define N_MAPS   4096 ", maps)
    code = r"""
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
typedef unsigned long pm_addr;
#define PM_A64 1
@HEX@
@MAPS@
static void add(const char *s) { maps_line(s, s + strlen(s)); }
int main(void) {
    int i;
    char l[96];
    for (i = 0; i < 3000; i++) {                       /* Fallout under qemu: thousands of back-to-back heap pieces */
        sprintf(l, "%lx-%lx rw-p 00000000 00:00 0", 0x400000000000ul + i * 0x1000ul, 0x400000001000ul + i * 0x1000ul);
        add(l);
    }
    add("400000bb8000-400000bb9000 ---p 00000000 00:00 0");     /* a guard page: its own */
    add("400000bb9000-400000bba000 rw-p 00000000 00:00 0");
    printf("%d %d %d\n", n_maps, maps_has(0x400000000ff0ul, 0x2000, MAP_R), maps_has(0x400000bb8000ul, 8, MAP_R));
    return 0;
}
"""
    code = code.replace("@HEX@", _lift(src, "static int hexval(")).replace("@MAPS@", maps)
    assert _host_run(tmp_path, code).split() == ["3", "1", "0"]


# ---- the ports --------------------------------------------------------------------------------------------------
def test_every_spike3_port_carries_the_lines():
    ports = sorted(PORTS.glob("*.port"))
    assert len(ports) == 7
    for path in ports:
        p = _port(path)
        assert all(n in p for n in NAMES + ("coil_table", "coil_count")), path.name
        assert p["coil_frame"][1:] == [0xD2800003, 0x52800002], path.name     # mov x3, #0; mov w2, #0
        assert p["sw_blocks"][0] - p["sw_struct"][0] == 0x298, path.name
        assert "NOT PLACED" not in "".join(l for l in path.read_text(encoding="utf-8").splitlines()
                                           if re.search(r"\b(coil_frame|coil_off|sw_struct)\b", l))


def _elf_u32(path):
    b = open(path, "rb").read()
    phoff, = struct.unpack_from("<Q", b, 0x20)
    phsz, phn = struct.unpack_from("<HH", b, 0x36)
    segs = [struct.unpack_from("<IIQQQQQQ", b, phoff + i * phsz) for i in range(phn)]

    def u32(va):
        for t, _f, off, v, _p, fs, _m, _a in segs:
            if t == 1 and v <= va < v + fs:
                return struct.unpack_from("<I", b, off + va - v)[0]
    return u32


@pytest.mark.parametrize("port", sorted(p.name for p in PORTS.glob("*.port")))
def test_the_lines_are_the_programs_own(port):
    """With PAD_S3_PROGRAMS (the seven programs as <game>.game, as test_pad1287's): each site's words are the
    program's, the wrapper branches to a builder that checks the coil, and the OFF builds 02 4d."""
    game = port.rsplit("-", 1)[0]
    path = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.exists(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    u, p = _elf_u32(path), _port(PORTS / port)
    for n in ("coil_frame", "coil_off"):
        a, w0, w1 = p[n]
        assert (u(a), u(a + 4)) == (w0, w1), (port, n)
    b = u(p["coil_frame"][0] + 8)
    assert b & 0xFC000000 == 0x14000000
    tgt = p["coil_frame"][0] + 8 + 4 * ((b & 0x3FFFFFF) - (1 << 26) if b & 0x2000000 else b & 0x3FFFFFF)
    assert any(u(tgt + 4 * k) & 0xFFFFFFE0 == 0x39400020 for k in range(16))      # ldrb wC, [x1]: the coil
    assert any(u(p["coil_off"][0] + 4 * k) & 0xFFFFFFE0 == 0x5289A040 for k in range(30))   # mov wK, #0x4d02


# ---- the app ----------------------------------------------------------------------------------------------------
def test_only_the_proven_spike3_builds_offer_them():
    s3 = {k for k in MP.SPARE_IO_PROVEN if k.endswith("/spike3")}
    assert s3 == {path.stem + "/spike3" for path in PORTS.glob("*.port")}          # all seven, each proven
    assert MP.SPARE_NO_OUTPUTS == {"star_wars_elg-1.10/spike3"}
    for path in sorted(PORTS.glob("*.port")):
        port = MP.read_port(str(path)) if hasattr(MP, "read_port") else None
        if port is None:
            pytest.skip("mode_project has no read_port")
        key = path.stem + "/spike3"
        want = () if key not in s3 else ("in",) if key in MP.SPARE_NO_OUTPUTS else ("in", "out")
        assert MP._spare(port, key) == want, key
    # a Spike 3 port without its node blocks never offers the inputs
    port = MP.read_port(str(PORTS / "fallout_le-0.82.port"))
    port["data"].pop("sw_blocks")
    assert MP._spare(port, "fallout_le-0.82/spike3") == ("out",)


def test_the_proof_rig_closes_the_spare_input():
    play = (PROOFS / "play.sh").read_text(encoding="utf-8")
    body = _between(play, "\nspare)\n", ";;")
    assert '$P set "$SLOT" $io 1' in body and '$P set "$SLOT" $io 0' in body
    assert r"sed -n 's/.*sweep: input \([0-9]*\):\([0-9]*\) .*/\1 \2/p'" in body
    proof = (PROOFS / "s3proof.sh").read_text(encoding="utf-8")
    assert "PAD_S3_NBTRACE=${PAD_S3_NBTRACE:-0}" in proof and "nbtrace_$TAG.log" in proof
    sweep = (SDK / "spare_sweep_mode.c").read_text(encoding="utf-8")
    assert "pm_spare_drive(n, o, 200, 30, 60, 3000)" in sweep and "pm_spare_off(n, held[n] - 1u)" in sweep
