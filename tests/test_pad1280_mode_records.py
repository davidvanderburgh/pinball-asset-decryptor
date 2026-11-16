"""PAD-1280: records of the owner's own on the game's high-score table.

Peanutsfr: "create custom High Score entries in the HSTD section, including for the machine's built-in modes" - a name,
a description, the mode it belongs to, points or a count of the shots and goals picked; edit and delete them; kept
with the project. The app's side (plugins/stern/mode_records.py, the Modes tab's High scores dialog, records.cfg at
Write) is tested here directly; the runtime's records section (pad_mode_runtime.c "records of the owner's own") is
lifted verbatim and played through a model two-player game: what each record counts, a play's best kept, the attract
mode's pages. Filing a record through the game's own initials entry is proven on the emulator (docs/plans/
pad1280_mode_records.md)."""
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import mode_records as MR
from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = RUNTIME.parent / "ports"
GZ_CARD = r"D:\Pinball\images\Stern\spike2\godzilla_le-1_16_0_spike2.Release.8G.sdcard.raw"


# ---- the runtime, lifted -----------------------------------------------------------------------------------------
MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
static void say(const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); printf("\n"); }
#define pm_snprintf snprintf
static int str_starts(const char *s, const char *p) { return !strncmp(s, p, strlen(p)); }
#define CHG_REC_SIZE 96
static unsigned chg_rec_check_at = 88, chg_rec_score_at = 72, chg_rec_score_size = 8;
@HELPERS@
@DECL@
/* the model game: the player up, the game's number, scores, a champion count, which records' modes run */
static unsigned game_no = 3, up = 1, in_game = 1;
static unsigned long long score[5], jets[5];
static int mode_on[16];
static unsigned chg_game_now(void) { return game_no; }
static unsigned pm_player(void) { return up; }
static int pm_in_game(void) { return in_game && up; }
static uint64_t pm_score(unsigned p) { return score[p]; }
static int rec_running(const struct rec *r) { return r->where == 0 ? 1 : r->where < 0 ? 0 : mode_on[r - recs]; }
static unsigned long long rec_cat_value(unsigned cat, unsigned p) { return cat == 4 ? jets[p] : 0; }
@FNS@
static void audit(unsigned id, unsigned n) { unsigned r[2] = { id, n }; on_rec_audit(r); }
static void show(void)
{
    int i;
    for (i = 0; i < rec_n; i++)
        printf("value %s p1 %llu p2 %llu\n", recs[i].name, rec_value(&recs[i], 1), rec_value(&recs[i], 2));
}
int main(void)
{
    static const char *const cfg[] = {
        "# PAD-1280: a comment",
        "rec 1 points run g20:0x7b5a68 - KING OF THE MONSTERS",
        "rec 2 count game - a5,a6 BUILDING SMASHER",
        "rec 3 count run g1:0x7b4cb8 a7,c4 RAMPS AND JETS",
        "rec 4 points game own - MY MODE TOTAL",
        "own 4 Biollante",
        "rec 6 points run - - OUT OF ORDER",
        "rec 5 count run - - NO COUNTS",
        "rec 5 bogus run - - BAD MEASURE",
        "rec 5 points run g7 - NO OBJECT",
        "rec 5 points run - - ",
        0 };
    int i;
    unsigned k;
    char names[40][40], title[48], file[4096], out[4096];
    unsigned char rec[CHG_REC_SIZE];
    long n = 0;
    for (i = 0; cfg[i]; i++) rec_line(cfg[i]);
    printf("records %d\n", rec_n);
    for (i = 0; i < rec_n; i++) {
        printf("rec %d count %d per_game %d where %d obj %x own %s ids", i + 1, recs[i].count, recs[i].per_game,
               recs[i].where, recs[i].obj, recs[i].own);
        for (k = 0; k < recs[i].n_ids; k++) printf(" %x", recs[i].ids[k]);
        printf(" name %s key %s\n", recs[i].name, recs[i].key);
    }
    printf("name is %d %d %d\n", rec_name_is("Biollante", "BIOLLANTE"), rec_name_is("BIOLLANTE", "BIOLLANTE 2"),
           rec_name_is("", ""));
    /* game 3: two players, two balls each */
    rec_tick();                                                   /* a new game: every count from 0 */
    /* p1 ball 1: KOTM runs (1 and 4 on), 5000 in it, then it ends; a building hit; then KOTM again, 2000 */
    up = 1; rec_tick();
    mode_on[0] = 1; mode_on[3] = 1; rec_tick();                   /* it starts: the start's points are not its */
    score[1] += 5000; audit(5, 1); rec_tick();
    score[1] += 300; mode_on[0] = 0; rec_tick();                  /* the last shot ended it: still its */
    score[1] += 100000; rec_tick();                               /* after it: not its */
    mode_on[0] = 1; rec_tick(); score[1] += 2000; rec_tick(); mode_on[0] = 0; rec_tick();
    mode_on[3] = 0; rec_tick();
    /* p2 ball 1: Godzilla Multiball (record 3) - ramps (a7) and jets (c4) while it runs */
    up = 2; rec_tick();
    mode_on[2] = 1; rec_tick();
    audit(7, 1); audit(7, 1); jets[2] += 3; audit(99, 5); audit(6, 2); rec_tick();
    mode_on[2] = 0; rec_tick();
    audit(7, 1); jets[2] += 10; rec_tick();                       /* after the multiball: not counted for 3 */
    /* p1 ball 2: KOTM a third time, 7000: the best play */
    up = 1; rec_tick();
    mode_on[0] = 1; rec_tick(); score[1] += 7000; rec_tick(); score[1] += 1; rec_tick();
    /* the game ends with it running: the play still counts */
    show();
    for (i = 0; i < rec_n; i++) for (k = 1; k <= 4; k++) rec_close(&recs[i], k);
    show();
    /* a new game forgets them */
    game_no++; rec_tick(); show();
    /* the attract pages: records after the co-op awards, only one with a champion shows */
    k = (unsigned)rec_page_names(names, 0, 40);
    printf("pages %u first %d%c\n", k, names[0][0], names[0][1]);
    chg_rec_fresh(rec, "DAV");
    for (i = 0; i < 8; i++) rec[chg_rec_score_at + i] = (unsigned char)((14301ull >> (8 * i)) & 0xff);
    { unsigned short c = chg_rec_check(rec); rec[chg_rec_check_at] = (unsigned char)c; rec[chg_rec_check_at + 1] = (unsigned char)(c >> 8); }
    n = chg_rec_put(file, 0, recs[0].key, rec, out, sizeof out);
    memcpy(file, out, (size_t)n);
    chg_rec_fresh(rec, "");
    n = chg_rec_put(file, n, recs[1].key, rec, out, sizeof out);  /* a record with no champion yet: score 0 */
    memcpy(file, out, (size_t)n);
    for (i = 0; i < (int)k; i++) {
        int got = rec_page(names[i], file, n, rec, title, sizeof title);
        printf("page %d got %d", i, got);
        if (got > 0) printf(" title %s initials %s score %llu", title, (const char *)rec + 32, chg_rec_score(rec));
        printf("\n");
    }
    printf("other name %d\n", rec_page("KING OF THE MONSTERS", file, n, rec, title, sizeof title));
    return 0;
}
"""

HELPERS = ("static int hexval(int c)", "static uint64_t number(const char **p, int *ok)")
FNS = ("static unsigned short chg_rec_check(const unsigned char *rec)",
       "static unsigned long long chg_rec_score(const unsigned char *rec)",
       "static void chg_rec_fresh(unsigned char *rec, const char *initials)",
       "static int chg_rec_line_is(const char *b, long i, long e, const char *name)",
       "static int chg_rec_find(const char *b, long n, const char *name, unsigned char *rec)",
       "static long chg_rec_put(const char *b, long n, const char *name, const unsigned char *rec, char *out, long cap)",
       "static int rec_name_is(const char *a, const char *b)",
       "static void rec_line(const char *s)",
       "static unsigned long long rec_value(const struct rec *r, unsigned p)",
       "static void rec_close(struct rec *r, unsigned p)",
       "static void rec_tick(void)",
       "static void on_rec_audit(pm_reg *r)",
       "static int rec_page_names(char names[][40], int n, int cap)",
       "static int rec_page(const char *name, const char *b, long n, unsigned char *rec, char *title, unsigned cap)")


def _decl(src):
    """The records section's declarations, verbatim: from its #defines to the last of its globals."""
    m = re.search(r"#define REC_MAX 12.*?static unsigned long long rec_val\[5\];[^\n]*\n", src, re.S)
    assert m
    return m.group(0)


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    helpers = "\n".join(R._lift(src, sig + "\n{") for sig in HELPERS)
    fns = "\n".join(R._lift(src, sig + "\n{") for sig in FNS)
    code = MAIN.replace("@HELPERS@", helpers).replace("@DECL@", _decl(src)).replace("@FNS@", fns)
    return R._host_run(tmp_path, code).splitlines()


def test_records_cfg_is_read_line_by_line(tmp_path):
    out = _run(tmp_path)
    assert "records 4" in out                                   # out of order, no counts, bad measure, no object, no name
    assert "rec 1 count 0 per_game 0 where 1 obj 7b5a68 own  ids name KING OF THE MONSTERS key RECORD:KING OF THE " \
           "MONSTERS" in out
    assert "rec 2 count 1 per_game 1 where 0 obj 0 own  ids 5 6 name BUILDING SMASHER key RECORD:BUILDING SMASHER" in out
    assert "rec 3 count 1 per_game 0 where 1 obj 7b4cb8 own  ids 7 80000004 name RAMPS AND JETS key " \
           "RECORD:RAMPS AND JETS" in out
    assert "rec 4 count 0 per_game 1 where 2 obj 0 own Biollante ids name MY MODE TOTAL key RECORD:MY MODE TOTAL" in out
    assert "name is 1 0 1" in out


def test_each_record_counts_only_while_its_mode_runs(tmp_path):
    out = _run(tmp_path)
    vals = [line for line in out if line.startswith("value ")]
    # during the game, the play still going counts: KOTM's plays 5300 / 2000 / 7001 - the best is the one running
    assert vals[0] == "value KING OF THE MONSTERS p1 7001 p2 0"
    # a whole game's count: building hits (a5) and building thrus (a6) anywhere, by whoever was up
    assert vals[1] == "value BUILDING SMASHER p1 1 p2 2"
    # the multiball's ramps (a7) and jets (c4) while it ran for player 2 - not the ones after it
    assert vals[2] == "value RAMPS AND JETS p1 0 p2 5"
    # a mode of the card's, the whole game's total of it: 5300 + 100000 + 2000 while it ran
    assert vals[3] == "value MY MODE TOTAL p1 107300 p2 0"
    # every play closed at the game's end: the best play stays
    assert vals[4] == "value KING OF THE MONSTERS p1 7001 p2 0"
    # a new game: every count from 0
    assert vals[8:12] == ["value KING OF THE MONSTERS p1 0 p2 0", "value BUILDING SMASHER p1 0 p2 0",
                          "value RAMPS AND JETS p1 0 p2 0", "value MY MODE TOTAL p1 0 p2 0"]


def test_a_records_champion_shows_in_the_attract_mode(tmp_path):
    out = _run(tmp_path)
    assert "pages 4 first 3A" in out
    assert "page 0 got 1 title KING OF THE MONSTERS initials DAV score 14301" in out
    assert "page 1 got -1" in out                               # no champion yet: no page
    assert "page 2 got -1" in out                               # not in the file at all
    assert "other name 0" in out                                # a mode's challenge champion is not a record's page


def test_the_runtime_files_records_after_the_games_own_and_arms_them():
    src = RUNTIME.read_text(encoding="utf-8")
    # PAD-1327: whole registers and pointer-wide words, so the same code files a Spike 3 game's records
    wrap = R._lift(src, "static unsigned scores_wrap(pm_reg r0, pm_reg r1, pm_reg r2, pm_reg r3)\n{")
    assert wrap.index("chg_scores_wrap(r0, r1, r2, r3)") < wrap.index("rec_file(r0, r1, r2, r3)")
    filing = R._lift(src, "static void rec_file(pm_reg r0, pm_reg r1, pm_reg r2, pm_reg r3)\n{")
    # the host entry is the record's, the getter answers its values, one entry, the gate, and everything put back
    for want in ("ent[0] = (pm_addr)(unsigned long)chg_rec;", "desc[1] = (pm_addr)(unsigned long)rec_get;",
                 "chg_scores_one_entry(cat, &list_was)", "chg_gate_cat = (int)cat;", "desc[1] = get_was;",
                 "ent[0] = was[0]; ent[5] = was[1]; ent[6] = was[2];", "CHG_ENT_AWARD(ent) = 0;",
                 "chg_rec_keep(b, n, r->key, chg_rec);"):
        assert want in filing, want
    assert filing.index("desc[1] = get_was;") > filing.index("chg_scores_game(r0, r1, r2, r3);")
    tick = R._lift(src, "static void on_tick(pm_reg *r)\n{")
    assert "rec_tick();" in tick
    boot = R._lift(src, "static void pad_mode_start(void)\n{")
    assert "!rec_wanted()" in boot and "rec_arm();" in boot      # a whole install: the score gate holds Insider back
    assert boot.index("insider_arm()") < boot.index("rec_arm();")


# ---- the app ------------------------------------------------------------------------------------------------------
def test_a_record_is_cleaned_as_the_card_takes_it():
    r = MR.clean({"name": "  king  of the monsters!! <3 ", "mode": "game:20", "measure": "points", "counts": ["audit:5"],
                  "per": "nonsense", "description": " most  points "})
    assert r == {"key": "", "name": "KING OF THE MONSTERS!! 3", "description": "most points", "mode": "game:20",
                 "measure": "points", "counts": [], "per": "run"}
    assert MR.clean({"name": "x" * 40})["name"] == "X" * MR.MAX_WORDS
    assert MR.clean({"name": "whole", "per": "run"})["per"] == "game"            # a whole-game record is one game's
    assert MR.clean({"name": "c", "measure": "count", "counts": ["audit:5", "audit:5", "champion:4", "bogus:1"]})[
        "counts"] == ["audit:5", "champion:4"]
    for bad in ({"name": "  "}, {"name": "c", "measure": "count"}, {"name": "m", "mode": "game:x"},
                {"name": "m", "mode": "elsewhere"}, {"name": "m", "mode": "own:  "},
                {"name": "c", "measure": "count", "counts": ["champion:%d" % i for i in range(MR.MAX_CATS + 1)]}):
        with pytest.raises(MR.RecordError):
            MR.clean(bad)


def test_records_are_kept_in_the_project(tmp_path):
    project = str(tmp_path)
    assert MR.load(project) == []
    k1 = MR.save_record(project, "", {"name": "one", "measure": "points"})
    k2 = MR.save_record(project, "", {"name": "two", "mode": "own:BIOLLANTE", "measure": "count", "counts": ["audit:7"]})
    assert (k1, k2) == ("r1", "r2")
    assert MR.save_record(project, k1, {"name": "one again", "description": "edited"}) == "r1"   # an edit keeps its key
    with pytest.raises(MR.RecordError):
        MR.save_record(project, "", {"name": "TWO"})                                         # a name another has
    assert [(r["key"], r["name"], r["description"]) for r in MR.load(project)] == [
        ("r1", "ONE AGAIN", "edited"), ("r2", "TWO", "")]
    assert MR.delete_record(project, "r1")["name"] == "ONE AGAIN"
    assert MR.delete_record(project, "r1") is None
    assert MR.save_record(project, "", {"name": "three"}) == "r1"                            # the free key again
    for i in range(MR.MAX_RECORDS - 2):
        MR.save_record(project, "", {"name": "n%d" % i})
    with pytest.raises(MR.RecordError):
        MR.save_record(project, "", {"name": "one too many"})


def test_records_cfg_names_each_game_mode_by_its_object():
    recs = [MR.clean({"name": "kotm", "mode": "game:20", "measure": "points"}),
            MR.clean({"name": "smash", "measure": "count", "counts": ["audit:5", "champion:4"]}),
            MR.clean({"name": "gone", "mode": "game:99", "measure": "points"}),
            MR.clean({"name": "mine", "mode": "own:Biollante", "measure": "points", "per": "game"})]
    text = MR.cfg_text(recs, [(20, "King of the Monsters", 0x7b5a68)])
    assert text.splitlines()[1:] == [
        "rec 1 points run g20:0x7b5a68 - KOTM",
        "rec 2 count game - a5,c4 SMASH",
        "# GONE left out: this card's game program has no mode 99 the runtime can see running",
        "rec 3 points game own - MINE",
        "own 3 Biollante"]
    with pytest.raises(MR.RecordError):
        MR.cfg_text([recs[2]], [])
    assert MR.describe(recs[0], {"game:20": "King of the Monsters"}) == "points in King of the Monsters (its best play)"
    assert MR.describe(recs[1]) == "2 counts in a whole game"


def test_a_port_that_files_champions_takes_records():
    from pinball_decryptor.plugins.stern import mode_project as MP
    gz = MP.read_port(str(PORTS / "godzilla_le-1.16.port"))
    assert MR.port_ok(gz) and MR.active_slot_known(gz)
    no = dict(gz, site={k: v for k, v in gz["site"].items() if k != "challenge_score_entry"})
    assert not MR.port_ok(no)
    # every port that names the champion framework a mode's challenge champion uses can take records (PAD-663's)
    took = [p.name for p in PORTS.glob("*.port") if MR.port_ok(MP.read_port(str(p)))]
    assert len(took) >= 46 and "godzilla_le-1.16.port" in took and "venom_le-1.07.port" in took


@pytest.fixture(scope="module")
def gz_elf():
    if not os.path.isfile(GZ_CARD):
        pytest.skip("the Godzilla LE 1.16 card is not on this computer")
    from pinball_decryptor.plugins.stern import title_reader as TR
    return TR.game_program(GZ_CARD)[2]


def test_godzillas_modes_and_counts_are_read_off_its_program(gz_elf):
    from pinball_decryptor.plugins.stern import mode_project as MP
    port = MP.read_port(str(PORTS / "godzilla_le-1.16.port"))
    modes = MR.game_modes(gz_elf, port)
    names = {n: (i, o) for i, n, o in modes}
    assert len(modes) == 26                                      # multiballs too, not only the ones a mode holds off
    assert names["Godzilla Multiball"] == (1, 0x7b4cb8) and names["King of the Monsters"] == (20, 0x7b5a68)
    counts = {c["label"]: c for c in MR.count_choices(gz_elf)}
    assert counts["Left Ramp"]["group"] == "Shots" and counts["Left Spinner spins"]["group"] == "Shots"
    assert counts["Jet Fighter Attack won"]["group"] == "Modes"
    assert counts["Balls saved"]["group"] == "Other" if "Balls saved" in counts else True
    assert counts["Jet Fighter"]["key"] == "champion:4"           # the game's own count of jets destroyed
    assert MR.game_modes(gz_elf, dict(port, value={}, site={})) == []   # no ACTIVE slot: no game modes


def test_write_puts_the_projects_records_in_records_cfg(tmp_path, monkeypatch, gz_elf):
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    prof = next(p for p in MP.profiles().values() if SMo.title_key(p) == "godzilla_le-1.16")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: MP.port_path(prof))
    project = str(tmp_path / "project")
    os.makedirs(project)
    MR.save_record(project, "", {"name": "ramp master", "mode": "game:1", "measure": "count",
                                 "counts": ["audit:168", "audit:169"]})
    MR.save_record(project, "", {"name": "kotm", "mode": "game:20", "measure": "points"})
    result = MW.plan(project, b"", b"", gz_elf, str(tmp_path / "scratch"), modes_on=False,
                     records=MR.load(project), records_prof=prof)
    with open(result.records_file, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[1:] == ["rec 1 count run g1:0x7b4cb8 a168,a169 RAMP MASTER", "rec 2 points run g20:0x7b5a68 - KOTM"]
    assert "records: KOTM - points in King of the Monsters (its best play)" in result.lines
    assert result.build is None and result.records_file.endswith("records.cfg")


def test_records_cfg_is_staged_beside_the_runtime(tmp_path):
    """p2_payload: records.cfg goes beside the runtime on the system partition (the module's alias once shadowed
    p2_payload's own MR, the mode runtime, and the staging died before it began)."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    cfg = tmp_path / "records.cfg"
    cfg.write_text("rec 1 points game - - WHOLE GAME\n", encoding="utf-8")
    plan = MW.ModePlan(project="", profile=None, port=os.path.join(MP.PORTS_DIR, "godzilla_le-1.16.port"), build=None)
    plan.records_file = str(cfg)
    out = MW.p2_payload(plan, str(tmp_path / "out"))
    assert [os.path.basename(x) for x in out["extras"]] == ["records.cfg"]
    assert (tmp_path / "out" / "records.cfg").read_text(encoding="utf-8") == "rec 1 points game - - WHOLE GAME\n"


def test_the_build_takes_the_projects_records_with_the_mode_maker(tmp_path, monkeypatch):
    """engine._records_for_build: Write and Try it take the project's records with the mode maker on, onto an image
    file of a title that files champions; each refusal is one warning saying why."""
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    said = []
    log = lambda text, kind="info": said.append((kind, text))                  # noqa: E731
    project = str(tmp_path)
    assert E._records_for_build(project, False, log) == (None, [])          # none: nothing said
    assert said == []
    MR.save_record(project, "", {"name": "whole game", "measure": "points"})
    prof = object()
    monkeypatch.setattr(MR, "project_title", lambda project, probe=False: prof)
    monkeypatch.setattr(MR, "title_refusal", lambda p: "" if p is prof else "no")
    monkeypatch.setattr(MW, "host_refusal", lambda platform=None: "")
    monkeypatch.setattr(MW, "preview_on", lambda: False)
    assert E._records_for_build(project, False, log, ext4_available=lambda: (True, "")) == (None, [])
    assert said[-1][0] == "warning" and "mode maker" in said[-1][1]
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    assert E._records_for_build(project, True, log, ext4_available=lambda: (True, "")) == (None, [])
    assert "direct-SD" in said[-1][1]
    got_prof, recs = E._records_for_build(project, False, log, ext4_available=lambda: (True, ""))
    assert got_prof is prof and [r["name"] for r in recs] == ["WHOLE GAME"]
    assert said[-1] == ("info", "Records on the high scores: 1 (WHOLE GAME).")


def test_the_card_and_try_it_carry_records_cfg():
    from tools.spike2_emu import mode_install as MI
    assert ("records.cfg", 0o100644) in MI.EXTRA_FILES and "records.cfg" in MI.STANDALONE_FILES
    for sh in ("cardmodes.sh", "tryit.sh"):
        text = (REPO / "tools" / "spike2_emu" / "modes" / sh).read_text(encoding="utf-8")
        assert "records.cfg" in text, sh
    tryit = (REPO / "tools" / "spike2_emu" / "modes" / "tryit.sh").read_text(encoding="utf-8")
    assert 'put "$S/records.cfg" "$DUMP/records.cfg"' in tryit
    engine = (REPO / "pinball_decryptor" / "plugins" / "stern" / "engine.py").read_text(encoding="utf-8")
    assert "records=rec_list, records_prof=rec_prof" in engine


def test_the_modes_tab_high_scores_dialog(tmp_path, monkeypatch):
    """High scores... shows for a project; the dialog lists the project's records with what they count, saves a new
    or edited one, says why one cannot be kept, and deletes one."""
    from pinball_decryptor.webui.tabs import modes as M
    svc = M.ModesTab.__new__(M.ModesTab)
    state = {"rows": [{"slug": "a", "kind": "form", "name": "BIOLLANTE"}]}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k, d=None: state.get(k, d), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(MR, "project_choices", lambda project: ("", {
        "modes": [{"value": "game:20", "label": "King of the Monsters"}],
        "counts": [{"key": "audit:168", "label": "Left Ramp", "group": "Shots"}]}))
    svc._publish_records_count(str(tmp_path))
    assert state["recs_shown"] is True and state["recs_n"] == 0
    assert svc.records_refresh() is True
    modes = state["recs"]["modes"]
    assert modes[0] == {"value": "", "label": "The whole game"}
    assert {"value": "game:20", "label": "King of the Monsters", "group": "The game's own modes"} in modes
    assert {"value": "own:BIOLLANTE", "label": "BIOLLANTE", "group": "Your modes"} in modes
    assert svc.record_save("", {"name": "ramps", "measure": "count", "counts": ["audit:168"], "mode": "game:20"}) == "r1"
    row = state["recs"]["rows"][0]
    assert row["name"] == "RAMPS" and row["counts_words"] == ["Left Ramp"]
    assert row["what"] == "1 count in King of the Monsters (its best play)" and state["recs_n"] == 1
    assert svc.record_save("", {"name": "nothing ticked", "measure": "count"}) is False
    assert "Tick at least one" in state["recs"]["error"]
    assert svc.record_save("r1", {"name": "ramps", "measure": "points", "mode": "own:BIOLLANTE", "per": "game"}) == "r1"
    assert state["recs"]["rows"][0]["what"] == "points in BIOLLANTE (all of it in one game)"
    MR.save_record(str(tmp_path), "", {"name": "lost", "mode": "game:77"})
    svc.records_refresh()
    assert "not in this project's game" in state["recs"]["rows"][1]["note"]
    assert svc.record_delete("r1") is True and [r["name"] for r in state["recs"]["rows"]] == ["LOST"]
    js = (REPO / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_dialogs.js").read_text(encoding="utf-8")
    assert 'call("modes.record_save", draft.key, draft)' in js and 'call("modes.record_delete", r.key)' in js
    js = (REPO / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert "RecordsDialog" in js and "High scores…" in js


def test_the_docs_say_how():
    sdk = (RUNTIME.parent / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "records.cfg" in sdk and "PAD-1280" in sdk
    plan = (REPO / "docs" / "plans" / "pad1280_mode_records.md").read_text(encoding="utf-8")
    assert "records.cfg" in plan
