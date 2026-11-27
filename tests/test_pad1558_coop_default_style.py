"""PAD-1558 (David, Godzilla, the three-image multi-boot card: "if i do this from the stern IC menu, it doesn't have
those extra options. i can only select co-op normal"): a co-op or team game no style step asked a style for - Start
pressed on the start menu's CO-OP with no Action, a co-op game begun from the Insider Connected Home Team screen, the
right flipper held at Start - plays the card's default style, coop.cfg ``style normal|characters|enhanced``, which the
owner picks on the Modes tab's co-op panel ("Style when none is chosen"). NORMAL (the game as it is) writes no line;
the game's own STANDARD and challenges are never changed (pad_mode_runtime.c sty_default_for)."""
import json
import os
import pathlib

from pinball_decryptor.plugins.stern import coop_play as CP
from tests import test_spike2_mode_roster as R

REPO = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = REPO / "tools" / "spike2_emu" / "modes" / "sdk" / "pad_mode_runtime.c"
CHARS = [{"name": "GODZILLA 1954", "ability": "longer_save"}, {"name": "SHIN GODZILLA", "ability": ""}]


def _src():
    return RUNTIME.read_text(encoding="utf-8")


MAIN = r"""
#include <stdio.h>
#define STY_STANDARD 7u
#define STY_CHALLENGE 8u
@FN@
int main(void)
{
    static const unsigned kinds[6] = { 1u, 4u, 3u, 5u, STY_STANDARD, STY_CHALLENGE };
    unsigned k, d;
    for (k = 0; k < 6; k++) {
        for (d = 0; d < 5; d++) printf("%d", sty_default_for(kinds[k], d));
        printf("|");
    }
    printf("\n");
    return 0;
}
"""


def test_the_default_is_the_cards_for_co_op_and_teams_and_never_the_games_own(tmp_path):
    code = MAIN.replace("@FN@", R._lift(_src(), "static int sty_default_for(unsigned kind, unsigned dflt)"))
    out = R._host_run(tmp_path, code, flags=("-no-pie",)).strip()
    co_op, two_v_two, two_v_one, three_v_one, standard, challenge, _ = out.split("|")
    # no line (0) and an unknown value (4): NORMAL, as before
    assert co_op == two_v_two == two_v_one == three_v_one == "11231"
    assert standard == challenge == "11111"


def test_every_route_without_a_step_takes_the_default():
    src = _src()
    for name in ("normal", "characters", "enhanced"):
        assert 'str_starts(s, "style %s")' % name in src
    go = R._lift(src, "static void sty_menu_go(void)\n{")
    assert "smn.go_style = sty_default_for(kind, coop_card_style());" in go      # Start on the entry, no Action
    begin = R._lift(src, "static void sty_begin(unsigned kind)\n{")
    assert "sty.preset = sty_default_for(kind, coop_card_style());" in begin     # the Home Team screen's own Action
    held = R._lift(src, "static void coop_style_held(void)\n{")
    assert "unsigned d = coop_card_style();" in held and "if (!d || coop_row_styles()) return;" in held   # no line: as it was
    assert "return coop.style_default;" in R._lift(src, "static unsigned coop_card_style(void)\n{")   # PR #53: or the row's
    assert "coop.plain = coop.style == 1u;" in held
    assert R._lift(src, "static void coop_solo_check(void)\n{").count("coop_style_held();") == 1   # right flipper
    assert R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)\n{") \
        .count("coop_style_held();") == 1                                                       # a held Start
    # what a style means once it is taken is the chooser's (sty_close), unchanged
    assert "coop.plain = st == 1u;" in R._lift(src, "static void sty_close(const char *how)\n{")


def test_the_project_keeps_the_style_and_the_card_gets_its_line(tmp_path):
    project = str(tmp_path)
    assert CP.load_style(project) == "normal"
    CP.save_style(project, "normal")
    from pinball_decryptor.core import staged_changes
    assert CP.STAGED_KEY not in staged_changes.load(project)       # nothing to keep: no record made
    CP.save(project, True)
    CP.save_characters(project, {"pick": True, "list": CHARS})
    assert CP.style_line(project) == ""
    assert CP.save_style(project, "characters") == "normal"
    assert CP.load_style(project) == "characters"
    assert CP.style_line(project) == "style characters\n"
    CP.save(project, False)                                         # co-op off and on: the style kept
    CP.save(project, True)
    assert CP.load_style(project) == "characters"
    CP.save_style(project, "ENHANCED")
    assert CP.style_line(project) == "style enhanced\n"
    CP.save_style(project, "bogus")                                 # anything else: NORMAL, no line
    assert CP.load_style(project) == "normal" and CP.style_line(project) == ""
    CP.save_style(project, "characters")
    CP.save_characters(project, {"pick": False, "list": CHARS})    # no pick on: no characters to give
    assert CP.style_line(project) == ""
    mw = (REPO / "pinball_decryptor" / "plugins" / "stern" / "mode_write.py").read_text(encoding="utf-8")
    assert "text += CP.style_line(project)" in mw


def test_the_settings_file_carries_the_style(tmp_path, monkeypatch):
    import types
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: types.SimpleNamespace(label="Godzilla"))
    src = str(tmp_path / "src")
    os.makedirs(src)
    CP.save(src, True)
    CP.save_characters(src, {"pick": True, "list": CHARS})
    CP.save_style(src, "enhanced")
    out = str(tmp_path / "coop.json")
    CP.export_settings(src, out)
    assert json.load(open(out, encoding="utf-8"))["style"] == "enhanced"
    dest = str(tmp_path / "dest")
    os.makedirs(dest)
    CP.import_settings(dest, out)
    assert CP.load_style(dest) == "enhanced"


def test_the_panel_offers_the_style_and_saves_it(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import modes as M
    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    assert svc.set_coop(True) is True
    assert state["coop_style"] == "normal"
    assert [o["value"] for o in state["coop_style_opts"]] == ["normal", "characters", "enhanced"]
    assert "Insider Connected Home Team screen" in state["coop_style_tip"]
    assert svc.set_coop_style("characters") is True
    assert state["coop_style"] == "characters" and CP.load_style(str(tmp_path)) == "characters"
    js = (REPO / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes.js").read_text(encoding="utf-8")
    assert 'call("modes.set_coop_style", v)' in js and "Style when none is chosen" in js
