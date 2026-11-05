"""PR #18: `value stock_shot_bits 32` (Munsters Pro 1.28), the game's rules with a u32 shot and u32 lit masks.

The runtime's accessors and its shot wrap, lifted verbatim from ``pad_mode_runtime.c`` and run on the host
against a stand-in rule object: a port without the line keeps the u64 layout and the (this, 0, lo, hi, factor)
call every other title has; with it the mask is 4 bytes a player and the shot is the call's second word.
The Munsters Pro 1.28 port's rule-17 slots are read off its game program where one is on this machine
(PAD_GAME_ELFS).
"""
import os
import pathlib
import struct

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
PORT = SDK / "ports" / "munsters_pro-1.28.port"

HARNESS = r"""
#include <stdio.h>
#include <stdint.h>
struct pm_mode;
struct pm_stock_rule;
struct pm_stock_handler;
typedef uint64_t (*stock_vfn8)(unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned, unsigned);
typedef int (*pm_stock_shot_fn)(unsigned id, uint64_t *shot, void *self);
struct stock_rule { unsigned id, vt, obj; int wrapped; stock_vfn8 orig; pm_stock_shot_fn fn; const struct pm_mode *fn_by;
                    const struct pm_stock_handler *h161; int in_original; };
static const struct pm_mode *current;
static long bits = 64;
static long pm_port_value(const char *name, long fallback)
{
    if (name[6] == 's' && name[7] == 'h') return bits;             /* stock_shot_bits */
    return bits == 32 ? 0x20 : 0x18;                               /* stock_field */
}
static struct stock_rule rule;
static struct stock_rule *stock_find(unsigned self) { return &rule; }
static struct stock_rule *stock161_of(struct pm_stock_rule *r) { return &rule; }
static int stock161_first(struct stock_rule *x, uint64_t *shot, unsigned s0) { return 0; }
static int stock_remap_shot(struct stock_rule *x, uint64_t *shot) { if (*shot == 0x800000ull) *shot = 0x4ull; return 0; }
static uint64_t orig(unsigned r0, unsigned r1, unsigned r2, unsigned r3, unsigned s0, unsigned s1, unsigned s2, unsigned s3)
{
    printf("orig %x %x %x %x\n", r1, r2, r3, s0);
    return 0;
}
static unsigned char obj[0x80] __attribute__((aligned(8)));
@FUNCTIONS@
int main(void)
{
    unsigned o = (unsigned)(unsigned long)obj;
    unsigned i;
    if ((unsigned long)obj != o) { printf("high\n"); return 0; }
    rule.obj = o; rule.wrapped = 1; rule.orig = orig;
    for (bits = 64; bits >= 32; bits -= 32) {
        for (i = 0; i < sizeof obj; i++) obj[i] = 0;
        printf("bits %ld\n", bits);
        printf("set %d %d\n", pm_stock_field_set(0, 2, 0x800004ull), pm_stock_field_set(0, 3, 0x100000000ull));
        for (i = 0; i < sizeof obj; i += 4)
            if (*(unsigned *)(obj + i)) printf("word +0x%x %x\n", i, *(unsigned *)(obj + i));
        printf("field %llx %llx\n", (unsigned long long)stock_field(&rule, 2), (unsigned long long)stock_field(&rule, 3));
        if (bits == 64) stock_w_shot(o, 0, 0x800000, 0, 7, 0, 0, 0);
        else stock_w_shot(o, 0x800000, 0, 0, 0, 0, 0, 0);
        pm_stock_call_original(0, 0x20ull, 5);
    }
    return 0;
}
"""


def test_a_u32_port_reads_writes_and_calls_its_rules_the_u32_way(tmp_path):
    from tests.test_spike2_mode_roster import _host_run, _lift
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(_lift(src, sig) for sig in (
        "static int stock_narrow(void)", "static uint64_t stock_field(", "int pm_stock_field_set(",
        "static uint64_t stock_w_shot(", "uint64_t pm_stock_call_original("))
    out = _host_run(tmp_path, HARNESS.replace("@FUNCTIONS@", fns), flags=("-no-pie",))
    if out.strip() == "high":
        pytest.skip("the host put the stand-in object above 4 GB")
    assert out.strip().splitlines() == [
        "bits 64",
        "set 1 1",
        "word +0x28 800004",                 # 0x18 + 8 * 2
        "word +0x34 1",                      # 0x18 + 8 * 3 + 4: the high word
        "field 800004 100000000",
        "orig 0 4 0 7",                      # (this, 0, lo, hi, factor): the remapped shot, the factor kept
        "orig 0 20 0 5",
        "bits 32",
        "set 1 0",                           # a bit past 31 has no room in the game's mask: refused
        "word +0x28 800004",                 # 0x20 + 4 * 2, and nothing at +0x2c
        "field 800004 0",
        "orig 4 0 0 0",                      # (this, shot): the remapped shot in the second word
        "orig 20 0 0 0",
    ]


def test_only_the_munsters_pro_port_is_u32():
    ports = sorted(p.name for p in (SDK / "ports").glob("*.port")
                   if "stock_shot_bits" in p.read_text(encoding="utf-8", errors="replace"))
    assert ports == ["munsters_pro-1.28.port"]
    text = PORT.read_text(encoding="utf-8")
    assert "value stock_shot_bits 32" in text and "rule 17 0x004c87c0 Spot Mode" in text
    for line in ("site coil_frame", "site coil_off", "data sw_struct"):      # PAD-826's lines stay
        assert line in text, line


def _elf():
    for d in (os.environ.get("PAD_GAME_ELFS") or "").split(os.pathsep):
        p = os.path.join(d, "munsters_pro-1_28_0.elf") if d else ""
        if p and os.path.isfile(p):
            with open(p, "rb") as f:
                return f.read()
    pytest.skip("no Munsters Pro 1.28 game program on this machine (set PAD_GAME_ELFS)")


def test_the_spot_modes_slots_are_the_game_programs():
    from pinball_decryptor.plugins.stern import stock_scan as S
    prog = S.Program(_elf())
    vt = 0x004c87c0
    slot = lambda n: prog.word(vt + 4 * n)                              # noqa: E731
    # v[11], the lit-mask getter: this + 4 * player + 0x20 (u32)
    assert [prog.word(slot(11) + 4 * k) for k in (3, 4)] == [0xe0840100, 0xe5900020]
    # v[25], the shot handler: the shot is r1 (`mov sl, r1`), tested against the same u32 mask
    assert prog.word(slot(25) + 8) == 0xe1a0a001
    assert 0xe5903020 in [prog.word(slot(25) + 4 * k) for k in range(30)]     # ldr r3, [r0, #0x20]
    assert slot(33) == 0x000d97a4                                        # START = block_start_17
