"""PAD-660 (luvthatapex, Bond LE): a mode's challenge champion is shown in the attract mode, like the game's own.

PAD-640 kept a mode's challenge high score, but the attract mode's champion pages showed only the game's. The
runtime wraps the game's last challenge champion page (HMSS CHALLENGE on Bond, FINAL SHOWDOWN CHALLENGE on Stranger
Things) and, after the game's own, runs that page again for each mode with a champion: the category's entry points at
the mode's record and the title message says the mode's name, until the page's first frame (MODE_SDK.md "Its own
high score", "In the attract mode").
"""
import os
import pathlib

import pytest

from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import portchallenge as PC
from pinball_decryptor.plugins.stern import portgen

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = SDK / "pad_mode_runtime.c"
#: each challenge port's page lines, read off its own program (PAD-660, Ghidra + the finder)
PAGES = {"james_bond_le-1.06": (0x1d6358, 0x38c6cc, 0x2fd144, 14, 0xf70),
         "james_bond_pro-1.06": (0x1d4acc, 0x252c2c, 0x207560, 14, 0xf70),
         "stranger_things-1.13": (0x17c294, 0x28809c, 0x182138, 12, 0xe19),
         "stranger_things_le-1.12": (0x19d4d8, 0x233330, 0x378f78, 12, 3483),
         "stranger_things_le-1.13": (0x19dc0c, 0x48b7a4, 0x2c7eec, 12, 0xe19)}


# ---- the finder ---------------------------------------------------------------------------
class _Mem:
    """Just what page_lines reads: the code words, and words by address."""
    def __init__(self, words, base):
        self.words, self.text_va = tuple(words), base

    def off(self, va):
        k = (va - self.text_va) // 4
        return k if 0 <= k < len(self.words) else None

    def word(self, va):
        return self.words[(va - self.text_va) // 4]


def _bl(at, target):
    return 0xEB000000 | ((target - at - 8) >> 2) & 0xFFFFFF


BASE = 0x10000


def _program(pages=1, title_calls=2, yield_shape=True):
    """A page per `pages`: push ; mov r0,#14 ; vpush ; mov r1,#0 ; sub sp ; bl rec ; .. mov r1,#0 ; mov r0,#14 ;
    bl entry ; the title (mov r0,#0xf70 ; bl text) `title_calls` times ; the frame loop's yield ; pop {.., pc}.
    Then the entry lookup, the record, the text lookup (push {r3,lr}) and the yield (movw/movt r3 ; add r1,r3,#12)."""
    words = [0] * 400
    entry, rec, text, yld = BASE + 4 * 300, BASE + 4 * 310, BASE + 4 * 320, BASE + 4 * 330
    for p in range(pages):
        k = 10 + 60 * p
        at = lambda i: BASE + 4 * (k + i)
        words[k:k + 12] = [0xE92D4FF0, 0xE3A0000E, 0xED2D8B02, 0xE3A01000, 0xE24DD07C, _bl(at(5), rec),
                           0xE2503000, 0xE58D3018, 0xE3A01000, 0xE3A0000E, _bl(at(10), entry), 0xE58D0014]
        for t in range(title_calls):
            words[k + 12 + 2 * t] = 0xE3A00EF7                      # mov r0, #0xf70
            words[k + 13 + 2 * t] = _bl(at(13 + 2 * t), text)
        words[k + 30] = _bl(at(30), yld if yield_shape else rec)
        words[k + 31] = 0xE28D0038
        words[k + 34] = 0xE8BD8FF0                                   # pop {r4-fp, pc}
    words[320:322] = [0xE92D4008, 0xE3083474]
    words[330:333] = [0xE3063DF8, 0xE3403082, 0xE283100C]
    return _Mem(words, BASE), entry


def test_the_finder_names_the_page_its_title_and_its_yield():
    e, entry = _program()
    assert [l for l in PC.page_lines(e, entry, 14) if not l.startswith("#")] == [
        "site  challenge_page        0x%08x 0xe92d4ff0 0xe3a0000e" % (BASE + 40),
        "site  challenge_page_text   0x%08x 0xe92d4008 0xe3083474" % (BASE + 4 * 320),
        "site  challenge_page_yield  0x%08x 0xe3063df8 0xe3403082" % (BASE + 4 * 330),
        "value challenge_page_cat    14",
        "value challenge_page_title  3952"]


@pytest.mark.parametrize("kw", [{"pages": 2}, {"title_calls": 1}, {"yield_shape": False}])
def test_the_finder_writes_nothing_when_the_shape_is_not_one_page(kw):
    e, entry = _program(**kw)
    assert PC.page_lines(e, entry, 14) == []
    e, entry = _program()
    assert PC.page_lines(e, entry, 13) == []                         # no page of that category


FW = [os.environ.get("PAD_FW_GAMES", ""), r"C:\tmp\PAD-660\fw", "/mnt/c/tmp/PAD-660/fw", r"C:\tmp\PAD-481\fw"]
FW_DIR = next((d for d in FW if d and os.path.isdir(d)), None)
GAMES = {"james_bond_le-1.06": "james_bond_le-1_06_0.Release.16G", "james_bond_pro-1.06": "james_bond_pro-1_06_0.Release.16G",
         "stranger_things-1.13": "stranger_things-1_13_0.Release.8G",
         "stranger_things_le-1.12": "stranger_things_le-1_12_0.Release.8G",
         "stranger_things_le-1.13": "stranger_things_le-1_13_0.Release.8G"}


@pytest.mark.parametrize("key", sorted(GAMES))
def test_the_finder_reads_each_builds_page_off_its_own_program(key):
    game = os.path.join(FW_DIR or "", GAMES[key] + ".sdcard.raw.game")
    if not FW_DIR or not os.path.isfile(game):
        pytest.skip("the game program is not on this machine")
    lines = PC.find(game)[0]
    page, text, yld, cat, title = PAGES[key]
    got = {tuple(l.split()[:2]): l.split()[2] for l in lines if "challenge_page" in l and not l.startswith("#")}
    assert got == {("site", "challenge_page"): "0x%08x" % page, ("site", "challenge_page_text"): "0x%08x" % text,
                   ("site", "challenge_page_yield"): "0x%08x" % yld, ("value", "challenge_page_cat"): str(cat),
                   ("value", "challenge_page_title"): str(title)}


@pytest.mark.parametrize("key", sorted(PAGES))
def test_each_challenge_port_names_its_last_champion_page(key):
    port = MP.read_port(str(SDK / "ports" / ("%s.port" % key)))
    page, text, yld, cat, title = PAGES[key]
    assert port["site"]["challenge_page"][0] == page
    assert port["site"]["challenge_page_text"][0] == text
    assert port["site"]["challenge_page_yield"][0] == yld
    assert int(port["value"]["challenge_page_cat"]) == cat == max(
        int(v) for k, v in port["value"].items() if k.startswith("challenge_scores_cat_"))
    assert int(port["value"]["challenge_page_title"]) == title


def test_the_lines_are_each_builds_own_never_a_references():
    for line in ("site challenge_page 0x001d6358 0xe92d4ff0 0xe3a0000e",
                 "site challenge_page_text 0x0038c6cc 0xe92d4008 0xe3083474",
                 "site challenge_page_yield 0x002fd144 0xe3063df8 0xe3403082",
                 "value challenge_page_cat 14", "value challenge_page_title 3952"):
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line


# ---- the runtime -------------------------------------------------------------------------
def _host():
    from tests import test_spike2_mode_roster as R
    return R


TITLE_MAIN = r"""
#include <stdio.h>
@FNS@
int main(void)
{
    char out[48];
    const char *cases[][2] = {
        {"BOND VS SUMO", "HMSS CHALLENGE"}, {"BON APPETIT", "FINAL SHOWDOWN CHALLENGE"},
        {"A VERY LONG MODE NAME HERE", "HMSS CHALLENGE"}, {"SUMO CHALLENGE", "HMSS CHALLENGE"},
        {"BOND VS SUMO", "CHAMPION"}, {"BOND VS SUMO", 0}, {"CHALLENGE", "HMSS CHALLENGE"}};
    unsigned k;
    for (k = 0; k < sizeof cases / sizeof cases[0]; k++) {
        chg_page_title_of(out, sizeof out, cases[k][0], cases[k][1]);
        printf("%s\n", out);
    }
    chg_page_title_of(out, 8, "BOND VS SUMO", "HMSS CHALLENGE");
    printf("%s\n", out);
    return 0;
}
"""


def test_a_modes_page_title_is_its_name_and_the_games_challenge_word_when_it_fits(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = _host()._lift(src, "static void chg_page_title_of(char *out, unsigned cap, const char *name, "
                             "const char *game_title)")
    out = _host()._host_run(tmp_path, TITLE_MAIN.replace("@FNS@", fns)).splitlines()
    assert out == ["BOND VS SUMO CHALLENGE", "BON APPETIT CHALLENGE", "A VERY LONG MODE NAME HERE",
                   "SUMO CHALLENGE", "BOND VS SUMO", "BOND VS SUMO", "CHALLENGE", "BOND VS"]


def test_the_page_shows_the_games_own_first_and_puts_the_record_back_before_a_frame():
    src = RUNTIME.read_text(encoding="utf-8")
    R = _host()
    wrap = R._lift(src, "static void chg_page_wrap(void)")
    own = wrap.index("chg_page_game();")
    point = wrap.index("chg_page_ent = ent;")
    swap = wrap.index("ent[0] = (unsigned)(unsigned long)chg_page_rec;")
    again = wrap.index("chg_page_game();", swap)
    back = wrap.index("chg_page_back();", again)
    assert own < point < swap < again < back                 # the game's page first; the put-back armed before the swap
    assert "!chg_rec_score(chg_page_rec)" in wrap       # a mode with no champion yet gets no page
    yld = R._lift(src, "static void chg_page_yield(unsigned *r)")
    assert "chg_page_back();" in yld
    assert "*chg_page_cur == chg_page_proc" in yld            # the page's own yield, not another process's
    assert wrap.index("chg_page_proc = *chg_page_cur;") < swap
    text = R._lift(src, "static const char *chg_page_text(unsigned id, unsigned r1, unsigned r2, unsigned r3)")
    assert "chg_page_ent && id == chg_page_title_id" in text
    arm = R._lift(src, "static void chg_page_arm(void)")
    # the yield hooked first, the page wrapped last: a page never runs swapped without its put-back
    assert arm.index('hook(fn("challenge_page_yield")') < arm.index('fn("challenge_page_text")') \
        < arm.index('hook_wrap(fn("challenge_page")')
    assert "chg_page_arm();" in R._lift(src, "static void chg_scores_arm(void)")
    # the end of a game never sees an attract page's record
    scores = R._lift(src, "static unsigned chg_scores_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert scores.index("chg_page_back();") < scores.index("ret = chg_scores_game(r0, r1, r2, r3);")


def test_only_the_modes_on_the_challenge_list_get_a_page():
    names = _host()._lift(RUNTIME.read_text(encoding="utf-8"), "static int chg_page_names(char names[][40], int cap)")
    assert "challenge_fn[s] && challenge_by[s]" in names and "own_challenge[s - CHALLENGE_OWN].fn" in names
    assert "challenge_words(w, name);" in names              # the capitals PAD-640 files them under


def test_the_docs_say_how():
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "challenge_page_yield" in sdk and "PAD-660" in sdk
    assert "the attract mode shows it after the game's challenge champions" in (SDK / "MODE_PARAMETERS.md").read_text(
        encoding="utf-8")
