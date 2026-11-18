"""PAD-1402: saved progress - numbers a mode keeps between games (a Story mode's chapter, New Game Plus, a character
unlocked for good). The runtime's store (pad_mode_runtime.c "SAVED PROGRESS": /dump/pad_saved_progress, owner key
value per line, the oldest lines dropped when full) is lifted verbatim and driven on the host; the app's side - the
blocks' "saved" variables, the SAVED PROGRESS service-menu row (Keep / Clear, Clear its default so a factory reset
clears it), saved.cfg and its way onto the card - is tested directly. The whole of it (games, a power cycle, a
factory reset) is proven in the emulator on X-Men LE and Pro 0.98 (docs/plans/pad1402_saved_progress.md)."""
import json
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import blocks_sim as BS
from pinball_decryptor.plugins.stern import menu_settings as MS
from pinball_decryptor.plugins.stern import saved_progress as SP
from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
SDK = REPO / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
EMU = REPO / "tools" / "spike2_emu"


def _story(reset="saved", everyone="saved_all", shared=False):
    num = lambda v: {"k": "num", "v": v}                            # noqa: E731
    return {"name": "STORY", "seconds": 0, "ends_on_drain": True, "screen": False,
            "vars": [{"name": "chapter", "reset": reset, "shared": shared}, {"name": "unlocked", "reset": everyone},
                     {"name": "hits", "reset": "ball"}, {"name": "this game", "reset": "game"}],
            "timers": [],
            "scripts": [{"hat": {"kind": "ball_end"}, "do": [
                {"op": "change", "var": "chapter", "by": num(1)}, {"op": "change", "var": "unlocked", "by": num(1)},
                {"op": "change", "var": "hits", "by": num(1)}, {"op": "change", "var": "this game", "by": num(1)}]}]}


# ---- the runtime's store, lifted -----------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
#include <string.h>
#define pm_snprintf snprintf
#define SAVED_MAX 160
#define SAVED_KEY_MAX 48
#define SAVED_OWNER_MAX 40
@FNS@
static char buf[SAVED_MAX + 1];
static long n;
static void put(const char *o, const char *k, long long v)
{
    long m = sv_put_in(buf, n, SAVED_MAX, o, k, v);
    if (m < 0) { printf("refused %s %s\n", o, k); return; }
    n = m;
    buf[n] = 0;
}
static void get(const char *o, const char *k)
{
    long long v;
    if (sv_get_in(buf, n, o, k, &v)) printf("get %s %s %lld\n", o, k, v);
    else printf("get %s %s none\n", o, k);
}
int main(void)
{
    char owner[SAVED_OWNER_MAX];
    unsigned char login[16] = { 0 };
    unsigned i;
    printf("ok %d %d %d %d %d %d\n", sv_key_ok("story:chapter"), sv_key_ok("shared:maser_won"), sv_key_ok(""),
           sv_key_ok("has space"), sv_key_ok("abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstuv"),
           sv_key_ok("abcdefghijklmnopqrstuvwxyzabcdefghijklmnopqrstu"));
    put("p1", "story:chapter", 3);
    put("p2", "story:chapter", 1);
    put("m", "story:unlocked", 1);
    put("p1", "story:chapter", -4);
    printf("text [%s]\n", buf);
    get("p1", "story:chapter");
    get("p2", "story:chapter");
    get("p3", "story:chapter");
    get("m", "story:unlocked");
    get("p1", "story:chap");
    for (i = 0; i < 8; i++) {
        char k[16];
        snprintf(k, sizeof k, "k%u", i);
        put("p4", k, 1000000000000LL + i);
    }
    printf("full [%s] %ld\n", buf, n);
    get("p1", "story:chapter");
    get("p4", "k7");
    sv_owner_of(0, login, owner, sizeof owner); printf("owner0 %s\n", owner);
    sv_owner_of(2, login, owner, sizeof owner); printf("owner2 %s\n", owner);
    for (i = 0; i < 16; i++) login[i] = (unsigned char)(0xa0 + i);
    sv_owner_of(3, login, owner, sizeof owner); printf("owner3 %s\n", owner);
    sv_owner_of(3, 0, owner, sizeof owner); printf("owner3none %s\n", owner);
    return 0;
}
"""
FNS = ("static int sv_key_ok(const char *k)",
       "static int sv_line_is(const char *b, long i, long e, const char *owner, const char *key)",
       "static int sv_get_in(const char *b, long n, const char *owner, const char *key, long long *v)",
       "static long sv_put_in(char *b, long n, long cap, const char *owner, const char *key, long long v)",
       "static void sv_owner_of(unsigned p, const unsigned char *login, char *out, unsigned cap)")


def test_the_store_keeps_finds_and_makes_room(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    code = MAIN.replace("@FNS@", "\n".join(R._lift(src, sig + "\n{") for sig in FNS))
    out = R._host_run(tmp_path, code).splitlines()
    assert out[0] == "ok 1 1 0 0 0 1"
    # a changed value moves to the end; every owner's own
    whole = "\n".join(out)
    assert "text [p2 story:chapter 1\nm story:unlocked 1\np1 story:chapter -4\n]" in whole
    k = out.index("get p1 story:chapter -4")
    assert out[k:k + 5] == ["get p1 story:chapter -4", "get p2 story:chapter 1", "get p3 story:chapter none",
                            "get m story:unlocked 1", "get p1 story:chap none"]
    full = next(l for l in out if l.startswith("]") and l[1:].strip().isdigit())
    assert int(full[1:]) <= 160                         # never past the cap: the oldest lines made room
    assert "get p1 story:chapter none" in out and "get p4 k7 1000000000007" in out
    assert "owner0 m" in out and "owner2 p2" in out and "owner3none p3" in out
    assert "owner3 ua0a1a2a3a4a5a6a7a8a9aaabacadaeaf" in out


def test_the_runtime_arms_ticks_and_names_its_files():
    src = RUNTIME.read_text(encoding="utf-8")
    assert 'static const char SAVED_FILE[] = "/dump/pad_saved_progress";' in src
    assert '"/usr/local/padmode/saved.cfg", "/dump/saved.cfg"' in src
    assert '"/games/pad/padmode/saved.cfg", "/dump/saved.cfg"' in src           # Spike 3's card
    tick = R._lift(src, "static void on_tick(pm_reg *r)\n{")
    assert "saved_tick();" in tick
    boot = R._lift(src, "static void pad_mode_start(void)\n{")
    assert boot.index("mset_arm();") < boot.index("saved_arm();")              # its row may be a shared one
    st = R._lift(src, "static void saved_tick(void)\n{")
    assert "SAVED_SETTLE_MS" in st and "sv_settled(v, !sv_clear_boot)" in st and "sv_nvm_tick(now)" in st
    hdr = (SDK / "pad_mode.h").read_text(encoding="utf-8")
    for name in ("pm_saved_get", "pm_saved_put", "pm_saved_stamp"):
        assert name in hdr and re.search(r"\b%s\(" % name, src)
    stubs, names = R.weak_stubs(hdr)
    assert {"pm_saved_get", "pm_saved_put", "pm_saved_stamp"} <= names     # a long long return parses too


ROW = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#define pm_snprintf snprintf
#define SAVED_MAX 4096
#define SAVED_KEY_MAX 48
#define SAVED_OWNER_MAX 40
#define SAVED_KEEP 1u
#define SAVED_CLEAR 2u
#define SAVED_MARK_OWNER "!"
#define SAVED_MARK_KEY "row"
static void say(const char *f, ...) { va_list a; va_start(a, f); printf("say: "); vprintf(f, a); va_end(a); printf("\n"); }
static char sv_buf[SAVED_MAX + 1];
static long sv_len;
static int sv_clear_own;
static unsigned sv_nvm_gen = 7, row = 2, clears;
static unsigned long long nvm_now = (7ull << 32) | 0x1234;        /* the game's newest settings generation */
static unsigned long long sv_nvm_stamp(void) { return nvm_now; }
static void sv_flush(const char *why) { (void)why; }
static void sv_clear(const char *why) { sv_len = 0; sv_buf[0] = 0; clears++; printf("clear: %s\n", why); }
static unsigned long long sv_clear_at = 1;
static void sv_setting_put(unsigned long long a, unsigned v) { (void)a; row = v; }
@FNS@
static void boot_reads(unsigned v)
{
    row = v;
    sv_clear_own = 0;
    sv_settled(v, 1);
    if (sv_clear_own) sv_settled(row, 0);              /* the runtime's own Keep settles in turn */
    printf("boot %u -> clears %u, row %u, mark %lld\n", v, clears, row, sv_pending());
}
int main(void)
{
    boot_reads(SAVED_CLEAR);                       /* the row's first boot: its default */
    boot_reads(SAVED_CLEAR);                       /* power cycle, the game never saved the Keep: the old Clear */
    nvm_now = (8ull << 32) | 0x99;                 /* a factory reset: the game saved its settings (defaults) */
    boot_reads(SAVED_CLEAR);
    boot_reads(SAVED_KEEP);                        /* Guided Setup's Save & Exit stored the Keep */
    boot_reads(SAVED_KEEP);
    sv_settled(SAVED_CLEAR, 0);                    /* the operator picks Clear while the game runs */
    printf("live -> clears %u, row %u\n", clears, row);
    return 0;
}
"""
ROW_FNS = ("static int sv_line_is(const char *b, long i, long e, const char *owner, const char *key)",
           "static int sv_get_in(const char *b, long n, const char *owner, const char *key, long long *v)",
           "static long sv_put_in(char *b, long n, long cap, const char *owner, const char *key, long long v)",
           "static long long sv_pending(void)", "static void sv_mark(long long stamp)",
           "static void sv_settled(unsigned v, int first)")


def test_a_clear_is_answered_once_and_a_factory_reset_again(tmp_path):
    """The runtime's Keep is only the game's memory until the game saves its settings: a boot that reads the same
    Clear with the same settings generation newest is not cleared again; a newer generation (a factory reset) is."""
    src = RUNTIME.read_text(encoding="utf-8")
    code = ROW.replace("@FNS@", "\n".join(R._lift(src, sig + "\n{") for sig in ROW_FNS))
    out = [l for l in R._host_run(tmp_path, code).splitlines() if not l.startswith(("say:", "clear:"))]
    stamp7, stamp8 = (7 << 32) | 0x1234, (8 << 32) | 0x99
    assert out == ["boot 2 -> clears 1, row 1, mark %d" % stamp7,
                   "boot 2 -> clears 1, row 1, mark %d" % stamp7,
                   "boot 2 -> clears 2, row 1, mark %d" % stamp8,
                   "boot 1 -> clears 2, row 1, mark 0",
                   "boot 1 -> clears 2, row 1, mark 0",
                   "live -> clears 3, row 1"]


# ---- the blocks ------------------------------------------------------------------------------------------------
def test_saved_resets_and_their_checks():
    assert BM.SAVED_RESETS == ("saved", "saved_all")
    assert set(BM.SAVED_RESETS) <= set(BM.RESETS) and set(BM.SAVED_RESETS) <= set(BM.SHARED_RESETS)
    assert BM.uses_saved(_story()) and not BM.uses_saved(_story("game", "ball"))
    assert BM.problems(BM.normalize(_story(shared=True))) == []
    bad = _story(reset="mode", shared=True)
    assert any("saved between games" in p for p in BM.problems(BM.normalize(bad)))
    assert BM.saved_key("story", "This game") == "story:this_game"
    assert BM.saved_key("story", "Maser won", shared=True) == "shared:maser_won"
    assert len(BM.saved_key("x" * 60, "y" * 24)) <= 47


def test_the_c_keeps_saved_variables_through_new_games():
    c = BM.to_c(_story(shared=True), "story")
    assert "#define N_SAVED 2" in c
    assert 'SAVED_KEYS[N_SAVED] = {"shared:chapter", "story:unlocked"};' in c
    assert "SAVED_AT[N_SAVED] = {pad_shared_chapter, V[1]};" in c
    assert "SAVED_ALL[N_SAVED] = {0, 1};" in c
    # the new game's resets leave the saved ones (read again instead) and zero the rest
    tick = c[c.index("if (new_game()) {"):]
    block = tick[:tick.index("saved_tick();")]
    assert "pad_shared_chapter[p] = 0" not in block and "V[1][p] = 0" not in block
    assert "V[2][p] = 0" in block and "V[3][p] = 0" in block and "saved_stamp[p] = 0;" in block
    # a ball's and a mode's resets never touch them
    for when in ("ball", "mode"):
        f = c[c.index("static void reset_%s(void)" % when):]
        f = f[:f.index("}")]
        assert "pad_shared_chapter" not in f and "V[1]" not in f
    assert "pm_saved_stamp(p)" in c and "pm_saved_put(SAVED_KEYS[k]" in c
    assert "N_SAVED" not in BM.to_c(_story("game", "game"), "story")


def test_the_blocks_sim_keeps_them_between_games():
    p = BM.normalize(_story())
    sim = BS.Sim(p) if hasattr(BS, "Sim") else None
    if sim is None:
        pytest.skip("no blocks simulator class")
    for name in ("chapter", "unlocked", "hits", "this game"):
        sim.vars[name] = 5
    sim.new_game()
    assert sim.vars["chapter"] == 5 and sim.vars["unlocked"] == 5
    assert sim.vars["hits"] == 0 and sim.vars["this game"] == 0


# ---- the card ------------------------------------------------------------------------------------------------
def test_the_service_menu_row():
    assert MS.SETTINGS[MS.SAVED_PROGRESS] == (None, "SAVED PROGRESS", "Saved Progress", 16)
    from pinball_decryptor.plugins.stern import engine as E
    logged = []
    job = E._SavedProgressMenu(lambda *a, **k: logged.append(a))
    assert job.wanted() == ("saved_progress", 2, ["Keep", "Clear"], {"default": 2})     # Clear: a factory reset clears
    job.fail("no spare setting")
    assert logged and "nothing on the machine clears it" in logged[0][0]


def test_saved_cfg():
    assert SP.cfg_text() == "# PAD-1402: saved progress (pad_mode_runtime.c \"SAVED PROGRESS\")\non\n"
    t = SP.cfg_text(0x63f7a0, (0x649ea8, 0x160, 0x164), "uncanny_xmen_le")
    assert t.splitlines()[1:] == ["on", "clear 0x63f7a0", "nvm /data/nv/uncanny_xmen_le/NVM",
                                  "users 0x649ea8 0x160 0x164"]
    assert "nvm" not in SP.cfg_text(0, None, "uncanny_xmen_le")          # no row: nothing to tell apart


def test_saved_into_and_the_card(tmp_path):
    from pinball_decryptor.plugins.stern import mode_write as MW
    res = type("Res", (), {})()
    res.lines, res.saved_file = [], ""
    MW.saved_into(res, b"not a program", str(tmp_path), 0x1234)
    text = (tmp_path / "saved.cfg").read_text(encoding="utf-8")
    assert "clear 0x1234" in text and "users" not in text
    assert res.saved_file == str(tmp_path / "saved.cfg")
    assert any("Insider logins were not found" in l for l in res.lines)
    import importlib.util
    spec = importlib.util.spec_from_file_location("mode_install", EMU / "mode_install.py")
    mi = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mi)
    assert ("saved.cfg", 0o100644) in mi.EXTRA_FILES and "saved.cfg" not in mi.STANDALONE_FILES
    tryit = (EMU / "modes" / "tryit.sh").read_text(encoding="utf-8")
    assert 'put "$S/saved.cfg" "$DUMP/saved.cfg"' in tryit and tryit.count('"$DUMP"/saved.cfg') == 2
    assert "pad_saved_progress" not in tryit.replace("pad_saved_progress, is the machine's", "")
    card = (EMU / "modes" / "cardmodes.sh").read_text(encoding="utf-8")
    assert card.count("saved.cfg") == 2 and "pad_saved_progress" not in card


def test_which_modes_keep_progress(tmp_path):
    from pinball_decryptor.plugins.stern import mode_project as MP
    project = str(tmp_path / "proj")
    os.makedirs(project)
    with open(os.path.join(project, ".extract_source.json"), "w", encoding="utf-8") as f:
        json.dump({"input_path": "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw",
                   "input_name": "godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"}, f)
    assert not SP.project_wants(project)
    slug, _p = BM.new_blocks_mode(project, "STORY")
    BM.save(project, slug, _story("game", "game"))
    assert not SP.project_wants(project)
    BM.save(project, slug, _story())
    assert SP.project_wants(project) and SP.mode_uses(project, slug)
    # a mode in C: its source names pm_saved_
    c_dir = os.path.join(MP.modes_dir(project), "hand_made")
    os.makedirs(c_dir)
    with open(os.path.join(c_dir, "hand_made.c"), "w", encoding="utf-8") as f:
        f.write("void f(void) { pm_saved_put(\"x:y\", 1, 2); }\n")
    assert SP.mode_uses(project, "hand_made")
    assert SP.wanted(project, [(slug, type("S", (), {"name": "STORY"})()), ("hand_made", None)]) == ["STORY",
                                                                                                    "hand_made"]
    from pinball_decryptor.plugins.stern import service_menu as SvM
    assert "saved_progress" in [w[0] for w in SvM.wanted(project, honour_off=False)]
    from pinball_decryptor.plugins.stern import spike3_menu as S3M
    assert S3M.saved_row_asked(project)
