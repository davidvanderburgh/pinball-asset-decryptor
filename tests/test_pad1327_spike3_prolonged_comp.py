"""PAD-1327: Prolonged Competition on a Stern Spike 3 card (round 1 of PAD-1297's "Prolonged Competition with records").

PAD-1297's census left it out of every Spike 3 build: the start menu's sites were not placed on a 64-bit program, the
runtime's menu code wrote the entry's name as a 4-byte pointer, the 64-bit hook_full was 0, and comp.cfg's flag and
captions were read off 32-bit programs only. Now:

- hook_a64.h's hook_full hands its logger x0..x8, x19..x28, x30 and the function's sp in one array by register number
  (the PAD-1322 callee step), writable; Star Wars ELG 1.10's Spike 3 menu keeps its entry count in w22;
- the menu code writes / compares the name as a pm_addr, finds the count through FULL_SP / FULL_REG_LAST and reads the
  kind at the pick from the port's register (`value challenge_menu_pick_reg`, w1 on ELG's Spike 3);
- ports/spike3/star_wars_elg-1.10.port names the menu (0x159a10, once per menu; the pick 0x159c38, every frame);
- prolonged_comp.card_lines reads a 64-bit program's flag names and message table through its relocations;
- spike3_modes.plan carries comp.cfg like the score feed (:func:`spike3_modes.comp_wanted`).

The tests that read the real programs run when PAD_S3_PROGRAMS names a folder of `<game>.game` files (each a card's
games/<game>/game). The lifted C runs on a 64-bit host compiler: Spike 3's word size.
"""
import os
import pathlib
import re
import struct
import subprocess

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import mode_write as MW
from pinball_decryptor.plugins.stern import prolonged_comp as PCo
from pinball_decryptor.plugins.stern import spike3_modes as S3M
from tests import test_spike2_mode_roster as R
from tests.test_pad1323_spike3_clips_stime import _Prog, _Reader, _tree

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
HOOK64 = SDK / "hook_a64.h"
ELG3 = SDK / "ports" / "spike3" / "star_wars_elg-1.10.port"
PROGS = os.environ.get("PAD_S3_PROGRAMS", "")


# ---- comp.cfg's numbers off a 64-bit program ---------------------------------------------------------------------
def _program(flag_at=17, head=3):
    """A 64-bit program with an FG_ name table (FG_PLAYER_COMPETITION_MODE_ACTIVE at *flag_at*) and a message table
    (CHOOSE YOUR MODE OF PLAY at id *head*, STANDARD three after it, COMPETITION five after): every pointer a
    relocation, the file's words 0, as in a PIE."""
    p = _Prog()
    p.fn(0xD65F03C0)
    names = ["FG_INVALID"] + ["FG_FLAG_%d" % k for k in range(1, 30)]
    names[flag_at] = "FG_PLAYER_COMPETITION_MODE_ACTIVE"
    flag_strs = [p.string(n) for n in names]
    texts = ["MSG %d" % k for k in range(head + 12)]
    texts[head] = "CHOOSE YOUR MODE OF PLAY"
    texts[head + 3], texts[head + 5] = "STANDARD", "COMPETITION"
    recs = []
    for t in texts:
        s = p.string(t)
        recs.append(p.words([("p", s)] * 5))
    p.words([("p", s) for s in flag_strs] + [0])
    p.words([("p", r) for r in recs] + [0])
    raw = bytearray(p.build())
    sh_off = struct.unpack_from("<Q", raw, 0x28)[0]
    struct.pack_into("<Q", raw, sh_off + 2 * 64 + 56, 24)     # .rela.dyn's entry size, as a linker writes it
    return bytes(raw)


def test_the_64_bit_program_gives_the_flag_and_both_captions():
    assert PCo.card_lines(_program()) == (17, 8, 6)
    assert PCo.card_lines(_program(flag_at=16, head=10)) == (16, 15, 13)
    text = PCo.cfg_text(_program(), only=True)
    assert PCo.cfg_values(text) == {"flag": 17, "caption": 8, "caption_end": 6} and text.endswith("only\n")


def test_a_64_bit_program_without_the_flag_or_the_menu_is_refused():
    raw = _program().replace(b"FG_PLAYER_COMPETITION_MODE_ACTIVE", b"FG_PLAYER_SOMETHING_ELSE_ACTIVE_")
    with pytest.raises(PCo.CompError, match="names no FG_PLAYER_COMPETITION_MODE_ACTIVE"):
        PCo.card_lines(raw)
    with pytest.raises(PCo.CompError, match="no COMPETITION and STANDARD"):
        PCo.card_lines(_program().replace(b"CHOOSE YOUR MODE OF PLAY", b"CHOOSE YOUR MODE OF FUN!"))


def test_a_path_to_a_64_bit_program_reads_the_same(tmp_path):
    f = tmp_path / "game"
    f.write_bytes(_program())
    assert PCo.card_lines(str(f)) == (17, 8, 6)


# every Spike 3 program in the library (2026-11-16): (flag, COMPETITION, STANDARD)
REAL = {"star_wars_elg": (17, 1919, 1914), "fallout_le": (17, 1920, 1915), "pokemon_le": (16, 1913, 1911),
        "star_wars_2025_le": (16, 1913, 1911), "star_wars_2025_pro": (16, 1909, 1907),
        "transformers_mtmte_le": (17, 1920, 1915), "walking_dead_remastered_le": (17, 1918, 1913)}


@pytest.mark.parametrize("game", sorted(REAL))
def test_every_spike3_program_names_the_flag_and_the_captions(game):
    path = os.path.join(PROGS, game + ".game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no %s.game" % game)
    assert PCo.card_lines(path) == REAL[game]


def test_the_elg_port_sites_are_the_programs_own_words():
    path = os.path.join(PROGS, "star_wars_elg.game")
    if not PROGS or not os.path.isfile(path):
        pytest.skip("PAD_S3_PROGRAMS has no star_wars_elg.game")
    from pinball_decryptor.plugins.stern import spike3_requests as S3R
    prog = S3R.Program(open(path, "rb").read())
    port = MP.read_port(str(ELG3))
    for name in ("challenge_menu", "challenge_menu_pick"):
        va, w0, w1 = port["site"][name][:3]
        o = prog.off(va)
        assert struct.unpack_from("<II", prog.raw, o) == (w0, w1), name
    # 0x159a10 `sub w1, w22, #1` (the count made the last index); 0x159c38 `cmp w1, #4` (the kind under the cursor)
    assert port["site"]["challenge_menu"][1] == 0x510006C1 and port["site"]["challenge_menu_pick"][1] == 0x7100103F


# ---- the port and the title -------------------------------------------------------------------------------------
def test_star_wars_elg_spike3_is_offered_it():
    port = MP.read_port(str(ELG3))
    assert PCo.port_ready(port)
    v = port["value"]
    assert (v["challenge_menu_list_at"], v["challenge_menu_count_reg"], v["challenge_menu_cap"],
            v["challenge_menu_entry"], v["challenge_menu_pick_reg"]) == (248, 22, 7, 16, 1)
    # the mode challenges stay off on Spike 3: no challenge_on_flag, no menu slot of theirs
    assert "challenge_on_flag" not in v and "challenge_menu_slot" not in v
    profs = MP.profiles()
    assert PCo.title_refusal(profs["star_wars_elg_1_10_spike3"]) == ""
    # (round 2, below: the newer titles; Star Wars 2025 Pro's port has no game_start / ball_start event yet)


# ---- the runtime: the 64-bit hook_full and the menu at Spike 3's word size -----------------------------------------
def _cc():
    return R._cc()


def _host(tmp_path, code):
    cc = _cc()
    (tmp_path / "t.c").write_text(code)
    r = subprocess.run([cc, "-std=gnu17", "-Wall", "-Wno-unused-parameter", "-Wno-unused-function", "-o",
                        str(tmp_path / "t"), str(tmp_path / "t.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return subprocess.run([str(tmp_path / "t")], capture_output=True, text=True, timeout=30).stdout


def _comp_block(src):
    i = src.index("#define COMP_KIND 0x200u")
    return src[i:src.index("/* Whether the next game is prolonged", i)]


MENU_MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned long pm_addr;
typedef unsigned long pm_reg;
#define FULL_REG_LAST 28
#define FULL_SP(r) ((unsigned char *)(unsigned long)(r)[31])
#define HOOK_SP(r) ((unsigned char *)((r) + 10))
#define MENU_KIND_AT 0u
#define MENU_CAPTION_AT 4u
#define MENU_NAME_AT 8u
static long pm_port_value(const char *k, long d)
{
    if (!strcmp(k, "challenge_menu_count_reg")) return 22;
    if (!strcmp(k, "challenge_menu_list_at")) return 248;
    if (!strcmp(k, "challenge_menu_cap")) return 7;
    if (!strcmp(k, "challenge_menu_entry")) return 16;
    if (!strcmp(k, "challenge_menu_pick_reg")) return 1;
    return d;
}
static void say(const char *f, ...) { va_list a; va_start(a, f); printf("say: "); vprintf(f, a); printf("\n"); va_end(a); }
#define pm_snprintf snprintf
@FNS@
static unsigned char frame[0x230] __attribute__((aligned(16)));
static void entry(int i, unsigned kind, unsigned short cap, const char *name)
{
    *(unsigned *)(frame + 248 + 16 * i) = kind;
    *(unsigned short *)(frame + 248 + 16 * i + 4) = cap;
    *(pm_addr *)(frame + 248 + 16 * i + 8) = (pm_addr)name;
}
int main(void)
{
    pm_reg a[32] = { 0 }, p[10] = { 0 };
    unsigned char *e = frame + 248 + 16 * 3;
    memset(frame, 0xee, sizeof frame);
    entry(0, 0, 1914, "NORMAL PLAY"); entry(1, 1, 1919, "ALL RANDOMNESS REMOVED"); entry(2, 2, 1921, "CHALLENGE");
    comp.caption = 1919; comp.caption_end = 1914;
    a[22] = 3; a[31] = (pm_reg)frame;
    comp_menu_built(a);
    printf("count %lu kind %#x caption %u name %s whole %d next %#x\n", a[22], *(unsigned *)e,
           *(unsigned short *)(e + 4), *(const char **)(e + 8), *(pm_addr *)(e + 8) == (pm_addr)comp_name_on,
           frame[248 + 16 * 4]);
    comp_menu_built(a);                                    /* the same menu again: there already, nothing added */
    printf("again %lu\n", a[22]);
    p[1] = 0x200; comp_menu_picked(p); printf("pick ours %d kind %lu\n", comp.pending, p[1]);
    p[1] = 1; comp_menu_picked(p); printf("pick game's %d kind %lu\n", comp.pending, p[1]);
    comp.on = 1;                                           /* once on, the entry ends it */
    entry(3, 0, 0, 0); memset(e, 0xee, 16); a[22] = 3; comp_menu_built(a);
    printf("on: caption %u name %s\n", *(unsigned short *)(e + 4), *(const char **)(e + 8));
    { int i; for (i = 3; i < 7; i++) entry(i, 1, 1919, "THE GAME'S"); }    /* a menu the game filled */
    a[22] = 7; comp_menu_built(a); printf("full %lu\n", a[22]);
    return 0;
}
"""


def test_the_menu_append_at_spike3s_word_size(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join([_comp_block(src)] + [R._lift(src, s) for s in (
        "static const char *comp_name(void)", "static int comp_entry_at(const unsigned char *ent, unsigned kat, unsigned nat)",
        "static unsigned *menu_count_of(pm_reg *r, unsigned char **fsp)", "static void comp_menu_built(pm_reg *r)",
        "static void comp_menu_picked(pm_reg *r)")])
    out = _host(tmp_path, MENU_MAIN.replace("@FNS@", fns)).splitlines()
    assert "count 4 kind 0x200 caption 1919 name UNTIL POWERED OFF whole 1 next 0xee" in out   # 8-byte name, no overrun
    assert "again 4" in out
    assert "pick ours 1 kind 0" in out and "pick game's 0 kind 1" in out        # ours plays as Standard (kind 0)
    assert "on: caption 1914 name ENDS PROLONGED COMPETITION" in out
    assert "full 7" in out and any("no room on the start menu" in l for l in out)


FULL_MAIN = r"""
#include <stdio.h>
typedef unsigned long pm_reg;
typedef void (*hook_fn)(pm_reg *regs);
#define PM_REG_LR 9
@FNS@
static pm_reg seen_sp, seen_lr, seen_x22, seen_x9;
static void logger(pm_reg *a) { seen_sp = a[31]; seen_lr = a[30]; seen_x22 = a[22]; seen_x9 = a[9]; a[22] += 1; a[1] = 77; }
int main(void)
{
    pm_reg r[16], x[10];
    unsigned k;
    for (k = 0; k < 16; k++) r[k] = 100 + k;
    for (k = 0; k < 10; k++) x[k] = 19 + k;
    full_call(logger, r, x);
    printf("sp %d lr %lu x22 %lu x9 %lu -> x22 %lu x1 %lu x19 %lu\n", seen_sp == (pm_reg)(r + 10), seen_lr, seen_x22,
           seen_x9, x[3], r[1], x[0]);
    return 0;
}
"""


def test_the_64_bit_hook_full_hands_every_kept_register_writable(tmp_path):
    h = HOOK64.read_text(encoding="utf-8")
    fns = R._lift(h, "static void full_call(hook_fn f, pm_reg *r, pm_reg *x)")
    out = _host(tmp_path, FULL_MAIN.replace("@FNS@", fns)).split()
    # a[31] the function's sp (r + 10), a[30] x30 (r[9]), a[22] x22 (x[3]); x9 reads 0; writes go back
    assert out == ["sp", "1", "lr", "109", "x22", "22", "x9", "0", "->", "x22", "23", "x1", "77", "x19", "19"]


def test_hook_full_is_a_real_hook_on_64_bit_now():
    h = HOOK64.read_text(encoding="utf-8")
    body = R._lift(h, "static int hook_full(pm_addr addr, hook_fn logger)\n{")
    assert "return hook_n(addr, (hook_n_fn)pm_a64_callee, (unsigned)k);" in body and "full_tab[" in body
    call = R._lift(h, "__attribute__((used, visibility(\"hidden\"))) void pm_a64_callee_call(pm_reg *r, unsigned n, pm_reg *x)")
    assert "if (full_tab[n]) full_call(full_tab[n], r, x);" in call
    assert re.search(r"#define FULL_SP\(r\) \(\(unsigned char \*\)\(\(r\) \+ 14\)\)", RUNTIME.read_text(encoding="utf-8"))


# ---- the Spike 3 build carries comp.cfg ----------------------------------------------------------------------------
class _Prof:
    game_dir = "star_wars_elg"
    label = "Star Wars ELG 1.10 (Spike 3)"


@pytest.fixture
def build(monkeypatch):
    seen = {}
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    monkeypatch.setattr(MW, "project_modes", lambda p: [])
    monkeypatch.setattr(MW, "code_mode_list", lambda p: [])
    monkeypatch.setattr(S3M, "feed_wanted", lambda p, real_card=True: ("", None))
    monkeypatch.setattr(S3M, "variants_wanted", lambda p, real_card=True: ({}, None))
    monkeypatch.setattr(S3M, "comp_wanted", lambda p, real_card=True: _Prof)
    monkeypatch.setattr(S3M, "_changed_videos", lambda p: [])
    monkeypatch.setattr(MP, "project_profile", lambda p, probe=False: (None, None))

    def plan(project, hud, bank, elf, scratch, **kw):
        seen.update(kw, elf=elf)
        r = type("R", (), {})()
        r.replaced, r.new, r.mode_names = [], [], []
        r.lines = ["prolonged competition: %s" % PCo.HOW] if kw.get("comp") else []
        return r

    def payload(result, out_dir, project=None, arch="arm"):
        seen["arch"] = arch
        return {"so": "/o/mode.so", "cfgs": [], "port": "/o/game.port", "assets": [],
                "extras": ["/o/comp.cfg"], "bundle": ""}
    monkeypatch.setattr(MW, "plan", plan)
    monkeypatch.setattr(MW, "p2_payload", payload)
    return seen


def test_a_card_of_prolonged_competition_alone_gets_comp_cfg(build, tmp_path):
    mp = S3M.plan("proj", _Reader(_tree()), str(tmp_path))
    assert mp is not None and mp.names == []
    assert build["comp"] is True and build["comp_prof"] is _Prof and build["modes_on"] is False
    assert build["elf"].startswith(b"\x7fELF\x02") and build["arch"] == "a64"   # the card's own 64-bit program
    assert [n for n, _p, _m in mp.files()] == ["mode.so", "comp.cfg", "game.port"]
    assert mp.lines == ["Prolonged Competition: " + PCo.HOW]


def test_a_multiboot_card_takes_no_prolonged_competition_and_says_so(build, monkeypatch, tmp_path):
    said = []
    monkeypatch.setattr(S3M, "card_state", lambda reader: ("multiboot", ""))
    assert S3M.plan("proj", _Reader(_tree()), str(tmp_path), log=lambda m, k="info": said.append((k, m))) is None
    assert ("warning", "Prolonged Competition: left out of this build: this is a multi-boot card; Prolonged "
            "Competition goes on a card of the one game it was made for.") in said


def test_comp_wanted_is_quiet_and_asks_the_title(monkeypatch, tmp_path):
    monkeypatch.setattr(MW, "host_refusal", lambda: "")
    monkeypatch.setattr(PCo, "load", lambda p: True)
    monkeypatch.setattr(PCo, "project_title", lambda p, probe=False: MP.profiles()["star_wars_elg_1_10_spike3"])
    assert S3M.comp_wanted("proj", real_card=False).key == "star_wars_elg_1_10_spike3"
    monkeypatch.setattr(PCo, "project_title", lambda p, probe=False: MP.profiles()["star_wars_elg_1_10"])
    assert S3M.comp_wanted("proj", real_card=False).key == "star_wars_elg_1_10"   # (Spike 2's: the title decides)
    monkeypatch.setattr(PCo, "project_title", lambda p, probe=False: None)
    assert S3M.comp_wanted("proj", real_card=False) is None                 # no title known
    monkeypatch.setattr(PCo, "load", lambda p: False)
    assert S3M.comp_wanted("proj", real_card=False) is None


def test_it_is_no_longer_left_out_of_a_spike3_build():
    assert "Prolonged Competition" not in S3M.FAMILY_LEFT_OUT
    eng = (ROOT / "pinball_decryptor" / "plugins" / "stern" / "engine.py").read_text(encoding="utf-8")
    i = eng.index("from . import spike3_modes as _S3M")
    assert '("Prolonged Competition", _comp_on)' not in eng[i:eng.index("variant_slots, variant_prof", i)]
    w = (ROOT / "pinball_decryptor" / "plugins" / "stern" / "spike3_write.py").read_text(encoding="utf-8")
    assert '"Prolonged Competition:"' in w                                  # its line names itself in the log


# ---- round 2: the newer titles (Fallout LE, Pokemon LE, Star Wars 2025 LE: menus of game-mode indices; Walking Dead
# Remastered LE: Star Wars ELG's entries) ----------------------------------------------------------------------------
PORTS3 = SDK / "ports" / "spike3"
# game: (port, frame site, its two words, list_at, count_reg | None, count_at | None, last_at | None, cursor, cap,
#        Competition index / name message, Standard index / name message)
FRAMES = {
    "fallout_le": ("fallout_le-0.82.port", 0x485A08, (0xB874DB57, 0x94116C39), 440, 22, None, None, 20, 12, 2, 1921, 1, 1916),
    "pokemon_le": ("pokemon_le-0.82.port", 0x4CC050, (0xB875D818, 0x6B18039F), 216, None, 136, 140, 21, 12, 6, 1914, 1, 1912),
    "star_wars_2025_le": ("star_wars_2025_le-0.96.port", 0x27E788, (0xB874DB16, 0x940562F9), 448, 23, None, None, 20, 10,
                          2, 1914, 1, 1912),
    "star_wars_2025_pro": ("star_wars_2025_pro-0.84.port", 0x1D1F1C, (0xB876D815, 0x94031DE4), 360, None, 156, None, 22, 4,
                           2, 1910, 1, 1908),
    "transformers_mtmte_le": ("transformers_mtmte_le-0.96.port", 0x2809D0, (0xB874DB77, 0x9409BAC3), 464, 22, None, None, 20,
                              12, 3, 1921, 1, 1916),
}


#: measured, but their start menu did not open on the rig (fresh settings; the player game-mode settings forced on
#: did not open it either): the lines are in the port as comments until it is reached
NOT_YET = ()   # every Spike 3 title with a port: emulator-proven (2026-11-16)


def _uncomment(port_name, tmp_path):
    text = (PORTS3 / port_name).read_text(encoding="utf-8")
    assert "# NOT OFFERED YET (PAD-1327)" in text
    i = text.index("# NOT OFFERED YET (PAD-1327)")
    live = text[:i] + "\n".join(l[2:] if l.startswith(("# site ", "# value ", "# data ")) else l
                                for l in text[i:].split("\n"))
    f = tmp_path / port_name
    f.write_text(live, encoding="utf-8")
    return MP.read_port(str(f))


@pytest.mark.parametrize("game", sorted(FRAMES))
def test_the_index_menu_lines(game, tmp_path):
    port_name, site, words, la, creg, cat, last, cur, cap, ci, cm, si, sm = FRAMES[game]
    port = MP.read_port(str(PORTS3 / port_name))
    if game in NOT_YET:
        assert "comp_menu_frame" not in port["site"] and not PCo.port_ready(port)
        port = _uncomment(port_name, tmp_path)          # the measured lines themselves
    assert PCo.port_ready(port)
    assert tuple(port["site"]["comp_menu_frame"][:3]) == (site,) + words
    v = port["value"]
    assert v["comp_menu_frame_moved"] == 1 and v["comp_menu_frame_list_at"] == la and v["comp_menu_frame_cap"] == cap
    assert v.get("comp_menu_frame_count_reg") == creg and v.get("comp_menu_frame_count_at") == cat
    assert v.get("comp_menu_frame_last_at") == last and v["comp_menu_frame_cursor_reg"] == cur
    assert (v["comp_menu_index"], v["comp_menu_index_msg"], v["comp_menu_end_index"], v["comp_menu_end_msg"]) == (ci, cm, si, sm)
    assert all(d in port["data"] for d in ("message_count", "message_remap", "message_table"))
    path = os.path.join(PROGS, game + ".game")
    if PROGS and os.path.isfile(path):              # the words, the frame's ldr and the names, off the program itself
        from pinball_decryptor.plugins.stern import spike3_requests as S3R
        prog = S3R.Program(open(path, "rb").read())
        w0 = struct.unpack_from("<I", prog.raw, prog.off(site))[0]
        assert (w0 & 0xFFE0FC00) == 0xB860D800 and (w0 >> 16) & 31 == cur     # ldr wt, [xn, w<cursor>, sxtw #2]
        assert struct.unpack_from("<II", prog.raw, prog.off(site)) == words
        _flag, comp, std = PCo.card_lines(path)
        assert (cm, sm) == (comp + 1, std + 1)        # ALL RANDOMNESS REMOVED / NORMAL PLAY follow their captions


def test_walking_dead_remastered_takes_star_wars_elgs_route(tmp_path):
    port = MP.read_port(str(PORTS3 / "walking_dead_remastered_le-0.92.port"))
    assert PCo.port_ready(port)
    assert tuple(port["site"]["challenge_menu"][:3]) == (0x1EF564, 0x510006C0, 0x52A88E02)       # sub w0, w22, #1
    assert tuple(port["site"]["challenge_menu_pick"][:3]) == (0x1EF5F0, 0x7100101F, 0x54005F20)  # cmp w0, #4
    v = port["value"]
    assert (v["challenge_menu_list_at"], v["challenge_menu_count_reg"], v["challenge_menu_cap"],
            v["challenge_menu_entry"], v["challenge_menu_pick_reg"]) == (296, 22, 8, 16, 0)
    assert "challenge_on_flag" not in v


#: the Spike 3 titles Prolonged Competition goes on (Transformers LE has no port yet)
OFFERED3 = {"star_wars_elg_1_10_spike3", "fallout_le_0_82_spike3", "pokemon_le_0_82_spike3",   # each emulator-proven
            "star_wars_2025_le_0_96_spike3", "walking_dead_remastered_le_0_92_spike3", "star_wars_2025_pro_0_84_spike3",
            "transformers_mtmte_le_0_96_spike3"}


def test_star_wars_2025_pros_bus_events_are_one_lower_past_56():
    port = MP.read_port(str(PORTS3 / "star_wars_2025_pro-0.84.port"))     # read off its code; game_start seen on the rig
    ev = {e[0]: e for e in port["event"]}
    text = (PORTS3 / "star_wars_2025_pro-0.84.port").read_text(encoding="utf-8")
    assert "\nevent game_start   0x4c" in text and "\nevent ball_start   0x25" in text and "event game_over    0x46" in text
    assert ev["game_start"][2:] == ev["game_over"][2:] and PCo.port_ready(port)


def test_which_spike3_titles_are_offered_it():
    profs = MP.profiles()
    offered = {k for k, p in profs.items() if k.endswith("_spike3") and not PCo.title_refusal(p)}
    assert offered == OFFERED3


FRAME_MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
typedef unsigned long pm_addr;
typedef unsigned long pm_reg;
#define FULL_REG_LAST 28
#define FULL_SP(r) ((unsigned char *)(unsigned long)(r)[31])
#define PMU "lu"
static long V_count_reg = -1, V_count_at = -1, V_last_at = -1;
static long pm_port_value(const char *k, long d)
{
    if (!strcmp(k, "comp_menu_frame_moved")) return 1;
    if (!strcmp(k, "comp_menu_frame_list_at")) return 216;
    if (!strcmp(k, "comp_menu_frame_count_reg")) return V_count_reg;
    if (!strcmp(k, "comp_menu_frame_count_at")) return V_count_at < 0 ? d : V_count_at;
    if (!strcmp(k, "comp_menu_frame_last_at")) return V_last_at;
    if (!strcmp(k, "comp_menu_frame_cap")) return 12;
    if (!strcmp(k, "comp_menu_frame_cursor_reg")) return 21;
    if (!strcmp(k, "comp_menu_index")) return 6;
    if (!strcmp(k, "comp_menu_index_msg")) return 1914;
    if (!strcmp(k, "comp_menu_end_index")) return 1;
    if (!strcmp(k, "comp_menu_end_msg")) return 1912;
    return d;
}
static void say(const char *f, ...) { va_list a; va_start(a, f); printf("say: "); vprintf(f, a); printf("\n"); va_end(a); }
static unsigned lettered; static const char *letter;
static int pm_message_set(unsigned id, const char *w) { lettered = id; letter = w; return 1; }
static void pm_message_restore(unsigned id) { if (lettered == id) lettered = 0; }
@FNS@
static unsigned char frame[0x200] __attribute__((aligned(16)));
static unsigned char f2[0x200] __attribute__((aligned(16)));
int main(void)
{
    pm_reg a[32] = { 0 };
    unsigned *list = (unsigned *)(frame + 216), *l2 = (unsigned *)(f2 + 216);
    comp.caption = 1913; comp.caption_end = 1911;
    /* Pokemon's shape: the count at sp+136, the loop's last index at sp+140; the menu {1 STANDARD, 4} */
    V_count_at = 136; V_last_at = 140;
    list[0] = 1; list[1] = 4; *(unsigned *)(frame + 136) = 2; *(unsigned *)(frame + 140) = 1;
    a[31] = (pm_reg)frame; a[21] = 0;
    comp_menu_frame(a);
    printf("A list %u count %u last %u pending %d lettered %u\n", list[2], *(unsigned *)(frame + 136),
           *(unsigned *)(frame + 140), comp.pending, lettered);
    a[21] = 2; comp_menu_frame(a);                       /* the press moved the cursor onto ours */
    printf("B count %u pending %d lettered %u %s\n", *(unsigned *)(frame + 136), comp.pending, lettered, letter);
    a[21] = 0; comp_menu_frame(a);
    printf("C pending %d lettered %u\n", comp.pending, lettered);
    /* Fallout's shape: the count in x22, no copy; a new menu (another frame), once it is on */
    V_count_at = -1; V_last_at = -1; V_count_reg = 22;
    l2[0] = 1; l2[1] = 3; a[31] = (pm_reg)f2; a[22] = 2; a[21] = 1; comp.on = 1;
    comp_menu_frame(a);
    printf("D list %u x22 %lu pending %d\n", l2[2], a[22], comp.pending);
    a[21] = 2; comp_menu_frame(a);
    printf("E pending %d lettered %u %s\n", comp.pending, lettered, letter);
    return 0;
}
"""


def test_the_index_menu_frame_at_spike3s_word_size(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    i = src.index("static unsigned long comp_frame_sp;")
    fns = "\n".join([_comp_block(src), src[i:src.index("\n\n", i)]] + [R._lift(src, s) for s in (
        "static const char *comp_name(void)", "static void comp_frame_restore(void)",
        "static unsigned comp_frame_cursor(unsigned cursor, unsigned n, unsigned left, unsigned right)",
        "static void comp_menu_frame(pm_reg *r)")])
    out = _host(tmp_path, FRAME_MAIN.replace("@FNS@", fns)).splitlines()
    assert "A list 6 count 3 last 2 pending 0 lettered 0" in out          # Competition's index again; the copy kept
    assert "B count 3 pending 1 lettered 1914 UNTIL POWERED OFF" in out    # its name lettered while the cursor is on it
    assert "C pending 0 lettered 0" in out                                 # and the game's words back as it leaves
    assert "D list 1 x22 3 pending 0" in out                               # once on: Standard's index, the count in x22
    assert "E pending 1 lettered 1912 ENDS PROLONGED COMPETITION" in out


def test_the_message_slots_are_pointer_wide():
    src = RUNTIME.read_text(encoding="utf-8")
    slot = R._lift(src, "static const char ***message_slot(unsigned idx)")
    assert 'data("message_table") + sizeof(void *) * idx' in slot and "mprotect(" in slot
    assert "4u * borrow[i].idx" not in src and 'data("message_table") + 4u * idx' not in src


# ---- the flag bitmap's layout on Spike 3 (PAD-1327 found the newer ports without it) ------------------------------
def test_every_spike3_port_names_the_64_bit_flag_layout():
    for port_file in sorted(PORTS3.glob("*.port")):
        port = MP.read_port(str(port_file))
        if "game_flags" in port.get("data", {}):
            assert port["value"].get("game_flags_at") == 0, port_file.name


def test_the_64_bit_runtime_reads_the_bitmap_at_plus_0_when_a_port_is_silent():
    src = RUNTIME.read_text(encoding="utf-8")
    assert "#define GAME_FLAGS_AT (PM_A64 ? 0 : 4)" in src
    assert 'pm_port_value("game_flags_at", 4)' not in src and src.count('pm_port_value("game_flags_at", GAME_FLAGS_AT)') == 4


def test_s3port_carries_the_layout_from_a_spike3_reference():
    s3 = (ROOT / "tools" / "spike3_emu" / "s3port.py").read_text(encoding="utf-8")
    i = s3.index("def draft_spike3(")
    body = s3[i:s3.index("\ndef ", i + 10)]
    assert 'if name == "game_flags_at":' in body and body.index('if name == "game_flags_at":') < body.index(
        'if GAME_VALUE.match(name) or name == "ball_end_event":')
