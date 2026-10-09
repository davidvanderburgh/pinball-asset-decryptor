"""PAD-420: a port whose mode TABLE is not this build's must not crash the game.

A derived port once carried another title's mode count: pad_mode_runtime.c's walk of the table read past it into
whatever followed and the game died in stock_class. The runtime now checks each entry against the process's
mappings before it follows it (stock_entry_ok: an aligned, readable object, its typeinfo word readable; then for a
mode, stock_slot_ok: its vtable readable through the ACTIVE slot, the slot's function executable), leaves one that is
not out (said once), keeps each entry's class, and turns the route off when the table is not readable or most of its
entries are not objects.

PAD-483: a real table holds the title's other rules too (30 of Venom LE 1.07's 94 entries are crule objects whose
vtables end before the ACTIVE slot). The first cut checked the slot before the class and left 19 of them out on the
real Venom port in the emulator; such an entry is an object of another class (0), never called, never said.

Lifted verbatim from the runtime and compiled for the HOST, with the fake game's objects at fixed low addresses and
entries that would crash the harness if the walk followed them (skips without an ELF C compiler, as the other
harness tests do).
"""
import pathlib

from tests.test_spike2_mode_roster import _host_run, _lift

SDK = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"


def _src():
    return RUNTIME.read_text(encoding="utf-8")


def _between(src, start, end):
    i = src.index(start)
    return src[i:src.index(end, i)]


_HARNESS = r"""
#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
static void say(const char *fmt, ...)
{
    va_list ap;
    va_start(ap, fmt);
    printf("SAY ");
    vprintf(fmt, ap);
    va_end(ap);
    putchar('\n');
}
static unsigned long now = 100000;
unsigned long pm_ms(void) { return now; }
static unsigned port_table = 0x30004000u;
static long port_count = 7;
static unsigned data(const char *name)
{
    if (!strcmp(name, "stock_mode_table")) return port_table;
    if (!strcmp(name, "typeinfo_cmode")) return 0x30000100u;
    if (!strcmp(name, "typeinfo_cmode_mball")) return 0x30000200u;
    return 0;
}
long pm_port_value(const char *name, long fallback)
{
    if (!strcmp(name, "stock_mode_count")) return port_count;
    if (!strcmp(name, "stock_slot_active")) return 17;
    return fallback;
}
@HEX@
@MAPS@
static int reads;
#define maps_read() (reads++)
@GUARD@
#undef maps_read
#define W(a) (*(unsigned *)(unsigned long)(a))
int main(void)
{
    long i, n, slot;
    const unsigned *tab;
    if (mmap((void *)0x30000000ul, 0x10000, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS | MAP_FIXED, -1, 0)
        != (void *)0x30000000ul) { puts("NO MMAP"); return 1; }
    maps_line_s("30000000-30010000 rw-p 00000000 00:00 0");
    maps_line_s("30010000-30011000 r-xp 00000000 08:01 7 /games/x/game");
    /* typeinfos {vptr, name, base}: cmode, cmode_mball (a cmode), a mode, a multiball, a rule (no cmode) */
    W(0x30000100) = 0x30000f00; W(0x30000108) = 0;
    W(0x30000200) = 0x30000f00; W(0x30000208) = 0x30000100;
    W(0x30000300) = 0x30000f00; W(0x30000308) = 0x30000100;
    W(0x30000400) = 0x30000f00; W(0x30000408) = 0x30000200;
    W(0x30000500) = 0x30000f00; W(0x30000508) = 0;
    W(0x30000ffc) = 0x30000300; for (i = 0; i < 40; i++) W(0x30001000 + 4 * i) = 0x30010010;   /* a mode's vtable */
    W(0x30001ffc) = 0x30000400; for (i = 0; i < 40; i++) W(0x30002000 + 4 * i) = 0x30010010;   /* a multiball's */
    W(0x30004ffc) = 0x30000300; for (i = 0; i < 40; i++) W(0x30005000 + 4 * i) = 0x40000000;   /* slots not code */
    /* a rule's SHORT vtable: three slots of code, then the next class's words (the ACTIVE slot is no code) */
    W(0x30006004) = 0x30000500; for (i = 0; i < 3; i++) W(0x30006008 + 4 * i) = 0x30010010;
    W(0x30003000) = 0x30001000;                     /* a mode */
    W(0x30003100) = 0x30002000;                     /* a multiball */
    W(0x30003200) = 0x60000000;                     /* its vtable is not mapped */
    W(0x30003300) = 0x30005000;                     /* a mode whose vtable's ACTIVE slot is not code */
    W(0x30003400) = 0x30006008;                     /* a rule: an object of another class (Venom's crule) */
    W(0x30004000) = 0x30003000; W(0x30004004) = 0x30003100; W(0x30004008) = 0;
    W(0x3000400c) = 0x50000000;                     /* not mapped at all */
    W(0x30004010) = 0x30003001;                     /* not aligned */
    W(0x30004014) = 0x30003200;
    W(0x30004018) = 0x30003400;
    tab = stock_table(&n, &slot);
    printf("TABLE %d %ld %ld\n", tab != 0, n, slot);
    for (i = 0; i < n; i++) printf("E%ld %d\n", i, stock_entry_class(i, tab, n, slot));
    for (i = 0; i < n; i++) printf("F%ld %d\n", i, stock_entry_class(i, tab, n, slot));   /* kept: said once */
    printf("OFF %d READS %d\n", stock_table_off, reads);
    W(0x30004008) = 0x30003300;                     /* one more bad entry: 4 of 7 - the route goes off */
    i = stock_entry_class(2, tab, n, slot);
    printf("G2 %ld OFF %d\n", i, stock_table_off);
    printf("AFTER %d\n", stock_table(&n, &slot) != 0);   /* off: no table */
    stock_table_off = 0;
    port_table = 0x50000000u;                       /* a table that is not readable */
    i = stock_table(&n, &slot) != 0;
    printf("UNREADABLE %ld OFF %d\n", i, stock_table_off);
    return 0;
}
"""


def test_a_mode_table_that_is_not_this_games_is_left_out_not_followed(tmp_path):
    src = _src()
    maps = _between(src, "#define N_MAPS", "/* ---- rule 2:")
    maps += "\nstatic void maps_line_s(const char *s) { maps_line(s, s + strlen(s)); }\n"
    guard = "\n".join([
        _lift(src, "static int stock_class(const unsigned *obj)"),
        _between(src, "#define N_STOCK_TABLE", "static int stock_entry_ok("),
        _lift(src, "static int stock_entry_ok("),
        _lift(src, "static int stock_slot_ok("),
        _lift(src, "static int stock_entry_class("),
        _lift(src, "static const unsigned *stock_table("),
    ])
    code = (_HARNESS.replace("@HEX@", _lift(src, "static int hexval(")).replace("@MAPS@", maps)
            .replace("@GUARD@", guard))
    out = _host_run(tmp_path, code, flags=("-Wno-unused-function", "-Wno-unused-variable", "-Wno-int-to-pointer-cast"))
    lines = out.splitlines()
    assert "TABLE 1 7 17" in lines, out
    # the rule (6) is an object of another class: 0, as the walk before the guard had it - not left out, not said
    assert [l for l in lines if l.startswith("E")] == ["E0 1", "E1 2", "E2 -1", "E3 -1", "E4 -1", "E5 -1", "E6 0"], out
    assert [l for l in lines if l.startswith("F")] == ["F0 1", "F1 2", "F2 -1", "F3 -1", "F4 -1", "F5 -1", "F6 0"], out
    said = [l for l in lines if l.startswith("SAY stock modes: entry")]
    assert len(said) == 4 and "0x50000000" in said[0] and "0x30003001" in said[1] and "0x30003200" in said[2], out
    assert "0x30003300" in said[3], out               # the mode whose slot is not code, said when it came
    assert not any("0x30003400" in l for l in lines), out   # the rule never
    assert "OFF 0 READS 1" in lines, out               # 3 of 7: still on; the maps read afresh once (5 s)
    assert "G2 -1 OFF 1" in lines and "AFTER 0" in lines, out   # 4 of 7: off
    assert any("is not this game's" in l for l in lines), out
    assert "UNREADABLE 0 OFF 1" in lines and any("is not readable in this game" in l for l in lines), out


def test_the_walks_check_each_entry_before_following_it():
    """Both walks of the table (the base-play tick and the question) go through stock_entry_class, never straight
    to stock_class, and take the table from stock_table."""
    src = _src()
    for sig in ("static void stock_generic_tick(void)", "static int stock_generic(unsigned kinds)"):
        body = _lift(src, sig)
        assert "stock_table(&n, &slot)" in body and "stock_entry_class(i, tab, n, slot)" in body, sig
        assert "stock_class(" not in body, sig
    # PAD-483: the class first, and the ACTIVE slot asked of a mode only (a rule's vtable may end before it)
    entry = _lift(src, "static int stock_entry_class(")
    assert entry.index("stock_entry_ok(o)") < entry.index("stock_class(o)") < entry.index("stock_slot_ok(o, slot)")
    assert "!(c = stock_class(o)) || stock_slot_ok(o, slot)" in entry
