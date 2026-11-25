"""PAD-1572: the mode runtime beside spike-pinball-bluetooth's menu, which adds a Bluetooth choice to the same start menu.

On a card his launcher preloads his menu to the right of our runtime, so his set-up runs first and his picker reads its own
copy of the menu's list from then on. At a 32-bit frame site (Godzilla, Jaws, John Wick, King Kong, Metallica, X-Men) our
entry goes into the list the game READS (decoded from the site's own two words) and takes his row's place without growing
the list, so his picker puts its row back after ours and nothing is left behind. On a menu of records, and on a 64-bit
program, ours stays off the start menu while his menu is loaded. Emulator-proven in the card's preload order
(docs/validation/pad-1572-bluetooth-discovery); here the pieces run on the desk."""
import glob
import os
import re
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
RUNTIME = os.path.join(SDK, "pad_mode_runtime.c")
CC = shutil.which("gcc") or shutil.which("cc")
needs_cc = pytest.mark.skipif(not CC or os.name == "nt", reason="needs a C compiler (WSL or Linux)")


def _rt():
    with open(RUNTIME, encoding="utf-8") as f:
        return f.read()


def _lift(src, signature):
    i = src.index(signature)
    while src.find(";", i) < src.find("{", i):
        i = src.index(signature, i + 1)
    depth = 0
    for k in range(src.index("{", i), len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError("unbalanced braces after " + signature)


def _run(tmp_path, code):
    c = tmp_path / "t.c"
    c.write_text(code)
    exe = tmp_path / "t"
    subprocess.run([CC, "-std=gnu11", "-Wall", "-Werror", "-o", str(exe), str(c)], check=True)
    return subprocess.run([str(exe)], check=True, capture_output=True, text=True).stdout


def _frame_sites():
    """(port, site, w0, w1) for every 32-bit frame site ported"""
    out = []
    for port in sorted(glob.glob(os.path.join(SDK, "ports", "*.port"))):
        with open(port, encoding="utf-8") as f:
            text = f.read()
        if re.search(r"(?m)^arch\s+a64\b", text):
            continue
        for m in re.finditer(r"(?m)^site\s+(challenge_menu_frame|comp_menu_frame)\s+0x[0-9a-f]+\s+(0x[0-9a-f]+)\s+(0x[0-9a-f]+)",
                             text):
            out.append((os.path.basename(port), m.group(1), int(m.group(2), 16), int(m.group(3), 16)))
    return out


@needs_cc
def test_every_frame_site_names_the_list_the_game_reads(tmp_path):
    src = _rt()
    sites = _frame_sites()
    assert len(sites) >= 20, sites
    calls = "".join('    printf("%%lx\\n", frame_read_list_at(0x%08xu, 0x%08xu, r));\n' % (w0, w1) for _p, _s, w0, w1 in sites)
    code = ("#include <stdio.h>\ntypedef unsigned long pm_reg;\n#define FULL_REG_LAST 12\n"
            + _lift(src, "static unsigned long frame_read_list_at(") + r"""
int main(void)
{
    pm_reg r[14];
    int i;
    for (i = 0; i < 14; i++) r[i] = 0x10000u * (unsigned)(i + 1);
""" + calls + r"""
    printf("%lx\n", frame_read_list_at(0xe1a07000u, 0xe3170080u, r));     /* any other shape: 0 */
    printf("%lx\n", frame_read_list_at(0xe0833106u, 0xe51230d4u, r));     /* the load from another register: 0 */
    printf("%lx\n", frame_read_list_at(0xe0833106u, 0xe59330d4u, r));     /* an adding displacement */
    return 0;
}
""")
    got = _run(tmp_path, code).split()
    for (port, site, w0, w1), line in zip(sites, got):
        b, k = (w0 >> 16) & 15, w1 & 0xFFF
        assert int(line, 16) == 0x10000 * (b + 1) - k, (port, site)
    assert got[len(sites):] == ["0", "0", "%x" % (0x40000 + 0xd4)]


@needs_cc
def test_our_entry_takes_the_pickers_row_and_nothing_is_left_behind(tmp_path):
    """His picker (as it behaves: it appends a row borrowing the selected mode's index, and when the list's length is not
    its own it takes the list for a new menu and appends again) and two entries of ours (MODE CHALLENGE, then Prolonged
    Competition on the same frame site), over several frames: the list ends stock, ours, ours, his - no stray row."""
    src = _rt()
    code = ("#include <stdio.h>\n#define FRAME_OWN_MAX 32\n"
            "static unsigned frame_own_val[FRAME_OWN_MAX], frame_own_set[FRAME_OWN_MAX];\n"
            "static unsigned long frame_own_list;\n"
            + _lift(src, "static int frame_owned(") + "\n" + _lift(src, "static void frame_own(") + "\n"
            + _lift(src, "static unsigned frame_append_at(") + r"""
static unsigned rows[16], count, stock, borrowed, active;
static void picker(unsigned sel)                       /* the Bluetooth picker's per-frame update, as observed */
{
    if (active && count == stock + 1 && rows[count - 1] == borrowed) return;
    stock = count;
    borrowed = rows[sel];
    rows[count++] = borrowed;
    active = 1;
}
static unsigned ours(unsigned value, unsigned *at, int *set)
{
    if (!*set || *at >= count || rows[*at] != value) {
        unsigned a = frame_append_at(rows, count, 1);
        rows[a] = value;
        frame_own(rows, a);
        count = a + 1;
        *at = a;
        *set = 1;
    }
    return *at;
}
int main(void)
{
    unsigned chg_at = 0, comp_at = 0, i, f;
    int chg = 0, comp = 0;
    rows[0] = 1; rows[1] = 2; rows[2] = 4; count = 3;  /* Standard, Competition, King of the Monsters */
    for (f = 0; f < 6; f++) {
        picker(0);
        ours(4, &chg_at, &chg);                          /* MODE CHALLENGE: King of the Monsters' index again */
        ours(3, &comp_at, &comp);                        /* Prolonged Competition: its own index */
    }
    for (i = 0; i < count; i++) printf("%u ", rows[i]);
    printf("| %u %u\n", chg_at, comp_at);
    return 0;
}
""")
    assert _run(tmp_path, code).strip() == "1 2 4 4 3 1 | 3 4"


@needs_cc
def test_a_list_of_its_own_still_appends(tmp_path):
    """No copy (the game's own stack list): after the last entry, as always - even when the last repeats an earlier one."""
    src = _rt()
    code = ("#include <stdio.h>\n#define FRAME_OWN_MAX 32\n"
            "static unsigned frame_own_val[FRAME_OWN_MAX], frame_own_set[FRAME_OWN_MAX];\n"
            "static unsigned long frame_own_list;\n"
            + _lift(src, "static int frame_owned(") + "\n" + _lift(src, "static unsigned frame_append_at(") + r"""
int main(void)
{
    unsigned list[8] = { 1, 2, 4, 1 };
    printf("%u %u %u\n", frame_append_at(list, 4, 0), frame_append_at(list, 4, 1), frame_append_at(list, 3, 1));
    return 0;
}
""")
    assert _run(tmp_path, code).split() == ["4", "3", "3"]


def test_the_three_frame_hooks_append_where_the_game_reads():
    src = _rt()
    for fn, site in (("static int challenge_frame_list(", '"challenge_menu_frame"'),
                     ("static void comp_menu_frame(", '"comp_menu_frame"'),
                     ("static void team_menu_frame(", '"comp_menu_frame"')):
        body = _lift(src, fn)
        assert "frame_list_read(r, " + site in body, fn
    for fn in ("static void challenge_menu_frame(", "static void comp_menu_frame(", "static void team_menu_frame("):
        body = _lift(src, fn)
        assert "frame_append_at(list, " in body and "frame_own(list, " in body, fn


def test_records_menus_and_64_bit_step_aside_for_the_bluetooth_menu():
    src = _rt()
    assert '"/spikebt/menu.so"' in _lift(src, "static int bt_menu_loaded(")
    yields = _lift(src, "static int start_menu_yields(")
    assert "(frame && !PM_A64)" in yields
    assert 'start_menu_yields("challenge menu", 0)' in src and 'start_menu_yields("challenge menu", 1)' in src
    assert 'start_menu_yields("prolonged competition", frame)' in _lift(src, "static void comp_arm(")
    assert 'start_menu_yields("teams", frame)' in _lift(src, "static void team_menu_arm(")
