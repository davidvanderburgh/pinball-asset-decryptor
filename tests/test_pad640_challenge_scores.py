"""PAD-640 (luvthatapex, Bond LE): a mode's challenge game keeps the MODE'S high score.

A challenge of a mode's own plays, to the game, as Chaos at Crab Key's challenge game, so a score that beat it went
in under CHAOS CHALLENGE. The runtime wraps the game's end-of-game high scores and, for a challenge game whose pick a
mode took, points the challenge's champion entry at a record of the mode's own, under the mode's name (MODE_SDK.md
"A mode in the game's Challenge list", "its own high score").
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
PORTS = {"james_bond_le-1.06": 5, "james_bond_pro-1.06": 5, "stranger_things-1.13": 4,
         "stranger_things_le-1.12": 4, "stranger_things_le-1.13": 4}


# ---- the finder ---------------------------------------------------------------------------
class _Mem:
    """Just what scores_lines reads: the code words, and words / strings by address."""
    def __init__(self, words, base, mem):
        self.words, self.text_va, self.mem = tuple(words), base, mem

    def off(self, va):
        return va if va in self.mem or any(a <= va < a + 4 for a in self.mem) else None

    def word(self, va):
        return self.mem[va]

    def cstr(self, va):
        v = self.mem.get(va)
        return v if isinstance(v, str) else None


def _movw(rd, v):
    return 0xE3000000 | (v >> 12 & 0xF) << 16 | rd << 12 | v & 0xFFF


def _movt(rd, v):
    return 0xE3400000 | (v >> 12 & 0xF) << 16 | rd << 12 | v & 0xFFF


def _game(titles, two_ends=False):
    """Code: the category lookup, the entry lookup and the end-of-game function's movwhi/movthi of the table; data:
    the count and the table (title at +24 -> a list whose first word is the title string's address)."""
    base, table, count_at = 0x10000, 0x7c0000, 0x5f0000
    cat = [0xE3500000, 0xE92D4008, 0x0A000000, _movw(3, count_at & 0xFFFF), _movt(3, count_at >> 16), 0xE5933000,
           0xE1500003, 0x2A000000, 0xE0800180, _movw(3, table & 0xFFFF), _movt(3, table >> 16), 0xE0830100, 0xE590301C]
    ent = [0xE1A03000, _movw(0, 0x5750), 0xE92D4010, _movt(0, 0x7a), 0xE1A04001, 0xE1A01003, 0xEB000000, 0, 0,
           0xE590001C]
    end = [0xE92D4FF0, 0xE24DD0BC, 0, 0, 0x83003000 | (_movw(3, table & 0xFFFF) & 0x000FFFFF),
           0x83403000 | (_movt(3, table >> 16) & 0x000FFFFF)]
    words = [0] * 4 + cat + [0] * 3 + ent + [0] * 3 + end + [0] * 4 + (end if two_ends else [])
    mem = {count_at: len(titles) + 1}
    for c, t in enumerate(titles, 1):
        at = table + 36 * c
        mem[at + 24] = 0x600000 + 0x100 * c
        mem[0x600000 + 0x100 * c] = 0x610000 + 0x100 * c
        mem[0x610000 + 0x100 * c] = t
    for a in range(table, table + 36 * (len(titles) + 1), 4):
        mem.setdefault(a, 0)
    return _Mem(words, base, mem), base + 4 * 4, base + 4 * (4 + len(cat) + 3), base + 4 * (4 + len(cat) + 3 + len(ent) + 3)


TITLES = ["HIGHEST SCORES", "COMBO CHAMPION", "DR. NO CHALLENGE CHAMPION", "AHOY MR. BOND CHALLENGE CHAMPION",
          "MARTINI CHAMPION", "CHALLENGE CHAMPION"]


def test_the_finder_reads_the_end_of_game_scores_and_each_challenges_category_in_order():
    e, _cat, ent, end = _game(TITLES)
    lines = [l for l in PC.scores_lines(e, 3) if not l.startswith("#")]
    assert lines == ["site  challenge_scores       0x%08x 0xe92d4ff0 0xe24dd0bc" % end,
                     "site  challenge_score_entry  0x%08x 0xe1a03000 0x%08x" % (ent, _movw(0, 0x5750)),
                     "value challenge_scores_cat_0  3", "value challenge_scores_cat_1  4",
                     "value challenge_scores_cat_2  6"]


def test_the_finder_writes_nothing_when_a_challenge_has_no_category_or_the_function_is_not_one():
    e, *_ = _game(TITLES)
    assert PC.scores_lines(e, 4) == []                   # four challenges, three champion categories
    e, *_ = _game(TITLES, two_ends=True)
    assert PC.scores_lines(e, 3) == []                   # two functions load the table that way: not the one


FW = [os.environ.get("PAD_FW_GAMES", ""), r"C:\tmp\PAD-481\fw", "/mnt/c/tmp/PAD-481/fw"]
FW_DIR = next((d for d in FW if d and os.path.isdir(d)), None)
GAMES = {"james_bond_le-1.06": "james_bond_le-1_06_0.Release.16G", "james_bond_pro-1.06": "james_bond_pro-1_06_0.Release.16G",
         "stranger_things-1.13": "stranger_things-1_13_0.Release.8G",
         "stranger_things_le-1.12": "stranger_things_le-1_12_0.Release.8G",
         "stranger_things_le-1.13": "stranger_things_le-1_13_0.Release.8G"}


@pytest.mark.parametrize("key", sorted(GAMES))
def test_the_finder_reads_each_builds_scores_off_its_own_program(key):
    game = os.path.join(FW_DIR or "", GAMES[key] + ".sdcard.raw.game")
    if not FW_DIR or not os.path.isfile(game):
        pytest.skip("the game program is not on this machine")
    lines = [l for l in PC.scores_lines(PC.Elf(game), PORTS[key]) if not l.startswith("#")]
    first = 10 if key.startswith("james_bond") else 9    # Bond: DR. NO .. HMSS; Stranger Things: DEMOGORGON ..
    assert lines[2:] == ["value challenge_scores_cat_%d  %d" % (n, first + n) for n in range(PORTS[key])]


@pytest.mark.parametrize("key", sorted(PORTS))
def test_each_challenge_port_names_its_scores_and_one_category_per_challenge(key):
    port = MP.read_port(str(SDK / "ports" / ("%s.port" % key)))
    assert {"challenge_scores", "challenge_score_entry"} <= set(port["site"])
    cats = [int(port["value"]["challenge_scores_cat_%d" % n]) for n in range(PORTS[key])]
    assert cats == list(range(cats[0], cats[0] + PORTS[key]))
    assert "challenge_scores_cat_%d" % PORTS[key] not in port["value"]


def test_the_lines_are_each_builds_own_never_a_references():
    for line in ("site challenge_scores 0x004e87dc 0xe92d4ff0 0xe24dd0bc",
                 "site challenge_score_entry 0x004e7d10 0xe1a03000 0xe3050750", "value challenge_scores_cat_4 14"):
        key, rest = line.split(" ", 1)
        assert portgen.generated(key, rest), line


# ---- the runtime -------------------------------------------------------------------------
def _host():
    from tests import test_spike2_mode_roster as R
    return R


RECORDS_MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdint.h>
#define CHG_REC_SIZE 96
static unsigned chg_rec_check_at = 88, chg_rec_score_at = 72, chg_rec_score_size = 8;
static int hexval(int c)
{
    return (c >= '0' && c <= '9') ? c - '0' : (c >= 'a' && c <= 'f') ? c - 'a' + 10
         : (c >= 'A' && c <= 'F') ? c - 'A' + 10 : -1;
}
@FNS@
int main(void)
{
    unsigned char a[CHG_REC_SIZE], b[CHG_REC_SIZE], got[CHG_REC_SIZE];
    static char t1[4096], t2[4096], t3[4096];
    long n1, n2, n3;
#ifdef SHORT_RECORDS
    chg_rec_check_at = 84; chg_rec_score_at = 80; chg_rec_score_size = 4;     /* PAD-663: The Beatles 1.29, SW ELG */
#endif
    chg_rec_fresh(a, "MXV");
    printf("fresh %s %llu check %d\n", (char *)a + 32, chg_rec_score(a),
           (a[chg_rec_check_at] | a[chg_rec_check_at + 1] << 8) == chg_rec_check(a));
    n1 = chg_rec_put("", 0, "BON APPETIT", a, t1, sizeof t1);
    memcpy(b, a, sizeof b);
    memset(b + chg_rec_score_at, 0, chg_rec_score_size);
    b[chg_rec_score_at] = 0x15; b[chg_rec_score_at + 1] = 0xcd; b[chg_rec_score_at + 2] = 0x5b; b[chg_rec_score_at + 3] = 0x07;
    memcpy(b + 32, "DAV", 4);
    { unsigned short c = chg_rec_check(b); b[chg_rec_check_at] = (unsigned char)c; b[chg_rec_check_at + 1] = (unsigned char)(c >> 8); }
    n2 = chg_rec_put(t1, n1, "YOLT WIZARD", b, t2, sizeof t2);
    n3 = chg_rec_put(t2, n2, "BON APPETIT", b, t3, sizeof t3);      /* replaces BON APPETIT's, keeps YOLT's */
    printf("lines %d %d\n", (int)(n2 / (2 * CHG_REC_SIZE + 1)), (int)(n3 / (2 * CHG_REC_SIZE + 1)));
    printf("find %d", chg_rec_find(t3, n3, "BON APPETIT", got));
    printf(" %llu %s", chg_rec_score(got), (char *)got + 32);
    printf(" %d %d %d\n", chg_rec_find(t3, n3, "YOLT WIZARD", got), chg_rec_find(t3, n3, "BON", got),
           chg_rec_find(t3, n3, "BON APPETIT X", got));
    t3[10] = t3[10] == '0' ? '1' : '0';                              /* a damaged line: its check fails */
    printf("damaged %d\n", chg_rec_find(t3, n3, "YOLT WIZARD", got) + chg_rec_find(t3, n3, "BON APPETIT", got));
    printf("room %ld\n", chg_rec_put(t2, n2, "NEW ONE", b, t3, n2 + 10));
    return 0;
}
"""


@pytest.mark.parametrize("short", [False, True])
def test_the_records_file_keeps_one_line_per_mode_and_refuses_a_damaged_one(tmp_path, short):
    """PAD-663: and so on The Beatles 1.29 / Star Wars ELG 1.10's shorter records (a u32 score at +80, the check at
    +84): a record checked at +88 there failed the game's check and the game reset the category."""
    R = _host()
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig) for sig in (
        "static unsigned short chg_rec_check(const unsigned char *rec)",
        "static unsigned long long chg_rec_score(const unsigned char *rec)",
        "static void chg_rec_fresh(unsigned char *rec, const char *initials)",
        "static int chg_rec_line_is(const char *b, long i, long e, const char *name)",
        "static int chg_rec_find(const char *b, long n, const char *name, unsigned char *rec)",
        "static long chg_rec_put(const char *b, long n, const char *name, const unsigned char *rec, char *out, long cap)"))
    main = RECORDS_MAIN.replace("@FNS@", fns)
    out = R._host_run(tmp_path, ("#define SHORT_RECORDS\n" if short else "") + main).splitlines()
    assert out[0] == "fresh MXV 0 check 1"
    assert out[1] == "lines 2 2"
    assert out[2] == "find 1 123456789 DAV 1 0 0"
    assert out[3] == "damaged 1"                     # one of the two lines is damaged, the other still reads
    assert out[4] == "room -1"


def test_the_wrap_points_the_entry_at_the_modes_record_and_puts_it_back():
    src = RUNTIME.read_text(encoding="utf-8")
    body = _host()._lift(src, "static unsigned chg_scores_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    swap = body.index("ent[0] = (unsigned)(unsigned long)chg_rec;")
    call = body.index("ret = chg_scores_game(r0, r1, r2, r3);", swap)        # PAD-663: an early return calls it too
    back = body.index("ent[0] = was[0]; ent[5] = was[1]; ent[6] = was[2];")
    assert swap < call < back                          # the game's own record is pointed back to before anything else
    assert "chg_hs.on = 0;" in body.split("if (on && ", 1)[0]       # one game's, once (PAD-663: a flag, not slot -1)
    arm = _host()._lift(src, "static void chg_scores_arm(void)")
    assert "hook_wrap(fn(\"challenge_scores\")" in arm
    assert "chg_picked(own_challenge[k].by, 0, own_challenge[k].name);" in src      # an own one plays as challenge 0's
    assert "chg_picked(challenge_by[n], n, challenge_title[n]);" in src


def test_the_docs_say_how():
    sdk = (SDK / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "challenge_scores" in sdk and "pad_challenge_scores" in sdk
    assert "its own high score" in (SDK / "MODE_PARAMETERS.md").read_text(encoding="utf-8")
