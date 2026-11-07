"""PAD-1028: a co-op game's awards - who of the team did best at each count, on the attract mode's champion pages.

DoomWalrus666: "At the end of a co-op mode game, could we show different awards for the players? Player that destroyed
the most jets, player that used the most ball save, player that collected the most power-ups ...". The runtime's award
code (pad_mode_runtime.c "a co-op game's awards") is lifted verbatim and played through a model co-op game: the team's
counts rise during each teammate's turn, the game's audits are counted as they come, and at the game's end each award
goes to the teammate with the most and becomes a champion page (the winner in the initials' place, the count as the
score, the award's words as the title). The app's side (coop_play.py) reads what a game can count off its program."""
import os
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from tests import test_spike2_mode_roster as R

RUNTIME = pathlib.Path(__file__).resolve().parents[1] / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
PORTS = RUNTIME.parent / "ports"
GZ_ELF = "C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf"

MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <stdint.h>
static void say(const char *f, ...) { va_list a; va_start(a, f); vprintf(f, a); va_end(a); printf("\n"); }
#define pm_snprintf snprintf
static unsigned long now_ms;
static unsigned long pm_ms(void) { return now_ms; }
static unsigned game_no = 7;
static unsigned chg_game_now(void) { return game_no; }
static struct { int on; unsigned button, game, n, turn; } coop;
static unsigned coop_teammates(void) { return coop.n; }
static int str_starts(const char *s, const char *p) { return !strncmp(s, p, strlen(p)); }
static uint64_t number(const char **p, int *ok)
{
    uint64_t v = 0;
    *ok = **p >= '0' && **p <= '9';
    while (**p >= '0' && **p <= '9') v = v * 10 + (uint64_t)(*(*p)++ - '0');
    return v;
}
#define CHG_REC_SIZE 96
static unsigned chg_rec_check_at = 88, chg_rec_score_at = 72, chg_rec_score_size = 8;
@DECL@
/* the team's counts: its points and a champion category's, as the game keeps them for its one player */
static unsigned long long team_points, team_jets;
static unsigned long long coop_award_now(const struct coop_award *a, unsigned p)
{
    (void)p;                                      /* co-op: the game's player 1, the team (PAD-1042: a team's) */
    return a->kind == COOP_AW_SCORE ? team_points : a->kind == COOP_AW_CHAMPION ? team_jets : 0;
}
@FNS@
static void audit(unsigned id, unsigned n) { unsigned r[2] = { id, n }; coop_audit_seen(r); }
int main(void)
{
    static const char *const cfg[] = {
        "score - MOST POINTS", "time - LONGEST BALL (SEC)", "audit 116 MOST BALL SAVES", "audit 168,169 MOST RAMPS",
        "champion 4 JET FIGHTER CHAMPION", "audit 114 MOST TILT WARNINGS", "audit 73 MOST EXTRA BALLS",
        "bogus 1 NOT AN AWARD", "audit - NO IDS", 0 };
    int i;
    unsigned ball, t;
    char names[24][40], title[48];
    unsigned char rec[CHG_REC_SIZE];
    for (i = 0; cfg[i]; i++) coop_award_line(cfg[i]);
    printf("awards %d\n", coop_aw_n);
    for (i = 0; i < coop_aw_n; i++) printf("award %d kind %d ids %u words %s\n", i, coop_aw[i].kind, coop_aw[i].n_ids,
                                          coop_aw[i].words);
    /* a team of 3, 2 balls each; the counts the game's one player makes during each teammate's turn */
    coop.n = 3; coop.turn = 1; team_points = 0; team_jets = 0; now_ms = 1000;
    coop_awards_begin();
    for (ball = 1; ball <= 2; ball++)
        for (t = 1; t <= 3; t++) {
            coop.turn = t;
            if (t == 1) { team_points += 1000; audit(116, 1); audit(168, 1); }
            if (t == 2) { team_points += 5000; team_jets += 2; audit(168, 1); audit(169, 1); now_ms += 90000; }
            if (t == 3) { team_points += 1000; team_jets += 2; audit(116, 1); audit(168, 1); audit(169, 1); }
            audit(999, 1);                                            /* an audit no award counts */
            now_ms += 30000;
            coop_awards_read(t, 1);
        }
    game_no++;
    coop_awards_end(3);
    i = coop_award_names(names, 0, 24);
    printf("pages %d\n", i);
    for (int k = 0; k < i; k++) {
        if (!coop_award_page(names[k], rec, title, sizeof title)) { printf("page %d none\n", k); continue; }
        printf("page %d title %s who %s score %llu check %d\n", k, title, (const char *)rec + 32,
               chg_rec_score(rec), (unsigned)(rec[88] | rec[89] << 8) == chg_rec_check(rec));
    }
    printf("other name %d\n", coop_award_page("MOST POINTS", rec, title, sizeof title));
    return 0;
}
"""

FNS = ("static unsigned short chg_rec_check(const unsigned char *rec)",
       "static unsigned long long chg_rec_score(const unsigned char *rec)",
       "static void chg_rec_fresh(unsigned char *rec, const char *initials)",
       "static void coop_award_credit(unsigned long long *last, unsigned long long now, unsigned long long *got)",
       "static void coop_awards_read(unsigned t, unsigned p)",
       "static void coop_awards_begin(void)",
       "static void coop_audit_seen(unsigned *r)",
       "static unsigned long long coop_award_winner(const unsigned long long *got, unsigned n, char *who)",
       "static void coop_awards_end(unsigned n)",
       "static int coop_award_names(char names[][40], int n, int cap)",
       "static int coop_award_page(const char *name, unsigned char *rec, char *title, unsigned cap)",
       "static void coop_award_line(const char *s)")


def _decl(src):
    """The award section's declarations, verbatim: from its #defines to the last of its globals."""
    m = re.search(r"#define COOP_AWARDS 16.*?static unsigned coop_won_game;[^\n]*\n", src, re.S)
    assert m
    return m.group(0)


def _run(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fns = "\n".join(R._lift(src, sig + "\n{") for sig in FNS)        # the definitions, not a declaration
    return R._host_run(tmp_path, MAIN.replace("@DECL@", _decl(src)).replace("@FNS@", fns)).splitlines()


def test_each_award_goes_to_the_teammate_with_the_most(tmp_path):
    out = _run(tmp_path)
    assert "awards 7" in out                                     # an unknown kind, an audit with no ids: left out
    assert "award 3 kind 3 ids 2 words MOST RAMPS" in out        # two audits added up
    said = [l for l in out if l.startswith("co-op award: ")]
    # points: 2000 / 10000 / 2000 - the rise of the team's score in each one's turns
    assert "co-op award: MOST POINTS - PLAYER 2 (1:2000 2:10000 3:2000)" in said
    # the longest ball: teammate 2's balls took 120 s, the others' 30 s
    assert "co-op award: LONGEST BALL (SEC) - PLAYER 2 (1:30 2:120 3:30)" in said
    # a tie: each of them
    assert "co-op award: MOST BALL SAVES - PLAYERS 1+3 (1:2 2:0 3:2)" in said
    assert "co-op award: MOST RAMPS - PLAYERS 2+3 (1:2 2:4 3:4)" in said
    assert "co-op award: JET FIGHTER CHAMPION - PLAYERS 2+3 (1:0 2:4 3:4)" in said
    # nobody has any: no page
    assert "co-op award: MOST TILT WARNINGS - no one, none counted (1:0 2:0 3:0)" in said
    assert "pages 5" in out
    assert "page 0 title MOST POINTS who PLAYER 2 score 10000 check 1" in out
    assert "page 1 title LONGEST BALL (SEC) who PLAYER 2 score 120 check 1" in out
    assert "page 2 title MOST BALL SAVES who PLAYERS 1+3 score 2 check 1" in out
    assert "other name 0" in out                                 # a mode's champion is not an award's page


def test_ties_stay_short_for_the_letter_spaced_initials(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    fn = R._lift(src, "static unsigned long long coop_award_winner(const unsigned long long *got, unsigned n, char *who)")
    main = r"""
#include <stdio.h>
@FN@
int main(void)
{
    char who[24];
    unsigned long long a[4] = { 3, 3, 1, 3 }, b[4] = { 5, 5, 5, 5 }, c[2] = { 0, 0 };
    printf("[%llu %s]", coop_award_winner(a, 4, who), who);
    printf("[%llu %s]", coop_award_winner(b, 4, who), who);
    printf("[%llu %s]", coop_award_winner(c, 2, who), who);
    return 0;
}
""".replace("@FN@", fn)
    out = R._host_run(tmp_path, main)
    assert out == "[3 PLAYERS 1+2+4][5 ALL PLAYERS][0 ]"


def test_the_runtime_reads_each_turn_before_the_games_change_and_ends_with_the_game():
    src = RUNTIME.read_text(encoding="utf-8")
    change = R._lift(src, "static unsigned coop_change_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert change.index("coop_awards_read(coop.turn, 1);") < change.index("ret = coop_change_game(r0, r1, r2, r3);")
    assert change.index("coop_awards_end(n);") > change.index("ret = coop_change_game(r0, r1, r2, r3);")
    add = R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "coop_awards_begin();" in add
    tick = R._lift(src, "static void coop_tick(void)\n{")
    assert "chg_game_now() != coop_won_game" in tick             # gone from the attract mode when a game starts
    # the pages: the awards first, then the modes' champions; an award's page needs no scores file
    names = R._lift(src, "static int chg_page_names(char names[][40], int cap)")
    assert "coop_award_names(names, 0, cap)" in names
    for sig in ("static void chg_page_wrap(void)", "static unsigned chg_pages_run(int k, unsigned a0, unsigned a1, "
                "unsigned a2, unsigned a3,"):
        body = R._lift(src, sig)
        assert "coop_award_page(names[i]," in body and "if (n < 0) n = 0;" in body
    arm = R._lift(src, "static void coop_arm(void)")
    assert "coop_awards_arm();" in arm
    assert 'hook(fn("audit_add"), coop_audit_seen)' in R._lift(src, "static void coop_awards_arm(void)")


def _port_lines(text):
    return {tuple(l.split()[:2]) for l in text.splitlines() if l.strip() and not l.startswith("#")}


def test_every_latest_coop_port_names_the_audit_add_but_star_wars_home():
    """The audits' awards need the game's audit add; every port with co-op lines has it, but Star Wars Home Edition,
    whose program has none (its awards are the points, the longest ball and its champions)."""
    missing = []
    for port in sorted(PORTS.glob("*.port")):
        text = port.read_text(encoding="utf-8")
        if "coop_player_change" in text and ("site", "audit_add") not in _port_lines(text):
            missing.append(port.name)
    assert missing == ["star_wars_elg-1.10.port"]


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_godzillas_awards_are_read_off_its_program():
    with open(GZ_ELF, "rb") as f:
        elf = f.read()
    got = {a["key"]: a for a in CP.award_choices(elf)}
    assert [k for k, a in got.items() if a["on"]] == ["score", "time", "audit:balls_saved", "audit:modes_started",
                                                      "audit:extra_balls", "audit:ramps"]
    assert got["audit:balls_saved"]["ids"] == [116] and got["audit:ramps"]["ids"] == [168, 169]
    assert 266 not in got["audit:modes_started"]["ids"]          # AUD_MODE_MONSTER_RAMPAGE_SHOT: a shot, not a start
    # the reporter's own: the jets, the power-ups - the game's own champion categories, offered, not ticked
    assert got["champion:JET FIGHTER CHAMPION"]["ids"] == [4] and not got["champion:JET FIGHTER CHAMPION"]["on"]
    assert got["champion:GODZILLA POWERUP CHAMPION"]["ids"] == [51]
    assert not any("HIGH SCORE" in k or "CHALLENGE" in k for k in got)
    assert got["champion:MECHAGODZILLA MULTIBALL CHAMPION"]["words"] == "MECHAGODZILLA MULTIBALL"
    assert all(len(a["words"]) <= CP.MAX_WORDS for a in got.values())
    text = CP.cfg_text(elf, {"champion:JET FIGHTER CHAMPION": {"on": True, "words": "most  jets"},
                             "audit:ramps": {"on": False}})
    assert "award champion 4 MOST JETS" in text.splitlines()
    assert not any("MOST RAMPS" in l for l in text.splitlines())
    assert "award audit 116 MOST BALL SAVES" in text.splitlines() and "award score - MOST POINTS" in text.splitlines()


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_write_puts_the_projects_awards_in_coop_cfg(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import mode_write as MW
    from pinball_decryptor.plugins.stern import sound_modes as SMo
    with open(GZ_ELF, "rb") as f:
        elf = f.read()
    prof = next(p for p in MP.profiles().values() if SMo.title_key(p) == "godzilla_le-1.16")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: MP.port_path(prof))
    project = str(tmp_path / "project")
    os.makedirs(project)
    CP.save(project, True)
    CP.save_award(project, "champion:JET FIGHTER CHAMPION", on=True, words="most jets")
    CP.save_award(project, "time", on=False)
    result = MW.plan(project, b"", b"", elf, str(tmp_path / "scratch"), modes_on=False, coop=True, coop_prof=prof)
    with open(result.coop_file, encoding="utf-8") as f:
        lines = f.read().splitlines()
    assert lines[:2] == ["coop on", "button 59"]
    assert "award champion 4 MOST JETS" in lines and "award score - MOST POINTS" in lines
    assert not any("LONGEST BALL" in line for line in lines)
    assert any(line.startswith("co-op awards after each co-op game: MOST POINTS, ") and "MOST JETS" in line
               for line in result.lines)


def test_the_modes_tab_awards_dialog(tmp_path, monkeypatch):
    """The Awards... button shows under a co-op tick the game can take; the dialog's rows are the game's awards with the
    project's choices, and a tick, new words or Defaults are kept in the project."""
    from pinball_decryptor.webui.tabs import modes as M
    choices = [{"key": "score", "words": "MOST POINTS", "on": True, "counts": "points", "kind": "score", "ids": []},
               {"key": "champion:JET FIGHTER CHAMPION", "words": "JET FIGHTER CHAMPION", "on": False,
                "counts": "jets", "kind": "champion", "ids": [4]}]
    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k, d=None: state.get(k, d), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    monkeypatch.setattr(CP, "project_awards", lambda project: ("", CP._apply(choices, CP.load_awards(project))))
    svc.set_coop(True)
    assert state["coop_awards_ok"] is True
    assert svc.coop_awards_refresh() is True
    rows = {r["key"]: r for r in state["coop_aw"]["rows"]}
    assert rows["score"]["on"] and not rows["champion:JET FIGHTER CHAMPION"]["on"] and state["coop_aw"]["note"] == "1 ticked."
    svc.coop_award_set("champion:JET FIGHTER CHAMPION", True, None)
    svc.coop_award_set("champion:JET FIGHTER CHAMPION", None, " most jets ")
    rows = {r["key"]: r for r in state["coop_aw"]["rows"]}
    assert rows["champion:JET FIGHTER CHAMPION"]["on"] and rows["champion:JET FIGHTER CHAMPION"]["words"] == "MOST JETS"
    assert rows["champion:JET FIGHTER CHAMPION"]["stock_words"] == "JET FIGHTER CHAMPION"
    svc.coop_award_set("champion:JET FIGHTER CHAMPION", None, "   ")      # emptied: the game's own words back
    assert {r["key"]: r for r in state["coop_aw"]["rows"]}["champion:JET FIGHTER CHAMPION"]["words"] == \
        "JET FIGHTER CHAMPION"
    svc.coop_awards_defaults()
    assert CP.load_awards(str(tmp_path)) == {} and CP.load(str(tmp_path))
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "Venom LE 1.07 has co-op play of its own.")
    svc._publish_coop(str(tmp_path))
    assert state["coop_awards_ok"] is False                     # no Awards... where co-op is refused
    js = (RUNTIME.parents[4] / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_dialogs.js").read_text(
        encoding="utf-8")
    assert 'call("modes.coop_award_set", r.key, v, null)' in js and 'call("modes.coop_awards_defaults")' in js


def test_each_character_has_an_award_card_with_its_portrait(tmp_path):
    """Round 2 (DoomWalrus666: the players' character portraits next to their awards): an award card per character,
    the pick card's look, its picture in the portrait frame, and an empty words line the runtime fills."""
    from PIL import Image
    project = str(tmp_path)
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": [{"name": "GODZILLA 1954", "ability": "longer_save"},
                                                        {"name": "SHIN GODZILLA", "ability": ""}]})
    pic = tmp_path / "shin.png"
    Image.new("RGBA", (300, 200), (10, 120, 10, 255)).save(pic)
    CP.save_picture(project, 1, str(pic))
    cards = CP.award_screens(project)
    assert [c["name"] for c in cards] == ["PadCoopAward_1", "PadCoopAward_2"]
    for c in cards:
        assert c["art_rgba"].shape == (CP.AWARD_SIZE[1], CP.AWARD_SIZE[0], 4) and c["words"] == " "
        assert c["words_name"] == c["name"] + "_Words" and (c["x"], c["y"]) == CP.AWARD_AT
        assert c["words_at"][1] > CP.AWARD_WORDS_Y                   # the words in the band at the foot
    px, py = 40 + 170, 80 + 150                                        # the portrait's middle: card 2's picture
    assert tuple(cards[1]["art_rgba"][py, px][:3]) == (10, 120, 10)
    assert tuple(cards[0]["art_rgba"][py, px][:3]) != (10, 120, 10)    # card 1 has no picture: the monogram plate
    CP.save_characters(project, {"pick": False, "list": [{"name": "A"}]})
    assert CP.award_screens(project) == []


def test_the_awards_show_on_the_winners_cards_at_the_games_end(tmp_path):
    src = RUNTIME.read_text(encoding="utf-8")
    change = R._lift(src, "static unsigned coop_change_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert change.index("coop_awards_end(n);") < change.index("coop_cards_show(n);")
    show = R._lift(src, "static void coop_cards_show(unsigned n)")
    assert "coop_won[i].mask & (1u << (t - 1))" in show and "coop_pick_of[t]" in show
    assert 'fn("proc_sleep")' in show and "COOP_CARDS_MAX_MS" in show
    assert '"award_cards on"' in R._lift(src, "static void coop_line(const char *s)")
    assert "coop_cards_find();" in R._lift(src, "static void coop_screens_tick(void)")
    find = R._lift(src, "static void coop_cards_find(void)")
    assert '"PadCoopAward_%d"' in find and '"PadCoopAward_%d.PadCoopAward_%d_Words"' in find
    end = R._lift(src, "static void coop_awards_end(unsigned n)\n{")
    assert "coop_won[coop_won_n].mask |= 1u << k;" in end
    words = R._lift(src, "static void coop_card_words_of(char *out, unsigned cap, const char *award, unsigned t, "
                         "unsigned long long value)")
    main = r"""
#include <stdio.h>
#include <stdint.h>
#define pm_snprintf snprintf
static void pm_commas(char *out, unsigned cap, uint64_t v)
{
    char t[32];
    int n = snprintf(t, sizeof t, "%llu", (unsigned long long)v), i, o = 0;
    for (i = 0; i < n && o + 2 < (int)cap; i++) { if (i && (n - i) % 3 == 0) out[o++] = ','; out[o++] = t[i]; }
    out[o] = 0;
}
@FN@
int main(void)
{
    char w[64];
    coop_card_words_of(w, sizeof w, "MOST POINTS", 2, 9982980ull);
    printf("[%s]", w);
    coop_card_words_of(w, sizeof w, "MOST RAMPS", 1, 12ull);
    printf("[%s]", w);
    return 0;
}
""".replace("@FN@", words)
    assert R._host_run(tmp_path, main) == "[MOST POINTS  PLAYER 2  9,982,980][MOST RAMPS  PLAYER 1  12]"


def test_short_words():
    assert CP.short_words("JET FIGHTER CHAMPION") == "JET FIGHTER CHAMPION"
    assert CP.short_words("GODZILLA, MOTHRA, AND RODAN VS. KING GHIDORAH CHAMPION") == "GODZILLA, MOTHRA, AND RODAN"
    assert CP.clean_words("  most   jets ") == "MOST JETS"
    assert len(CP.clean_words("x" * 40)) == CP.MAX_WORDS


def test_choices_kept_in_the_project_and_through_the_tick(tmp_path):
    p = str(tmp_path)
    CP.save(p, True)
    CP.save_award(p, "audit:ramps", on=False)
    CP.save_award(p, "champion:JET FIGHTER CHAMPION", on=True, words="most jets")
    assert CP.load_awards(p) == {"audit:ramps": {"on": False},
                                 "champion:JET FIGHTER CHAMPION": {"on": True, "words": "MOST JETS"}}
    CP.save(p, False)                                            # unticked: the choices wait for the next tick
    assert not CP.load(p) and CP.load_awards(p)["audit:ramps"] == {"on": False}
    CP.save(p, True)
    assert CP.load(p) and "champion:JET FIGHTER CHAMPION" in CP.load_awards(p)
    CP.save_award(p, None)                                       # Defaults
    assert CP.load_awards(p) == {} and CP.load(p)


def test_the_docs_say_how():
    sdk = (RUNTIME.parent / "MODE_SDK.md").read_text(encoding="utf-8")
    assert "Co-op awards" in sdk and "award champion" in sdk
