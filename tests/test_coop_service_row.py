"""CO-OP PLAY back in the service menu as Off / On.

Simon (2026-11-27, agreed with daveyvandy): "PAD - Item for coop play in service menu OFF/ON. SERVICE MENU - if set to
have the item on will be able to turn coop off/on.. thats it." PAD-1443 had taken the row away (co-op games always on
the start menu). The row comes back unticked on the Service menu tab, so a project that does not tick it is exactly
PAD-1443's card; ticked, the operator gets CO-OP PLAY Off / On, On being the card with no row.
"""
import json
import os

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import engine as E

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c")


def _src():
    with open(RUNTIME, encoding="utf-8") as f:
        return f.read()


def _project(tmp_path, data):
    p = str(tmp_path / "proj")
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(p, ".staged_changes.json"), "w", encoding="utf-8") as f:
        json.dump(data, f)
    return p


def test_the_row_is_off_on_and_on_to_start_with():
    key, values, names, opts = E._CoopMenu(lambda *a: None).wanted()
    assert key == "coop_play" and values == 2 and names == ()
    assert opts == {"default": CP.MENU_DEFAULT, "help_text": CP.MENU_HELP, "onoff": True}
    assert CP.MENU_DEFAULT == 2                                     # an Off / On row counts from 1: 2 is On
    assert len(CP.MENU_HELP) <= 63                                  # the spare help lines' room


def test_the_card_says_switch_only_with_a_spike2_row():
    """coop.cfg's `switch` tells the runtime the row is Off / On (coop_row_styles); no row, no line."""
    import inspect
    body = inspect.getsource(CP.cfg_text)
    assert '("switch\\n" if setting and not wide else "")' in body
    assert body.index('"switch') < body.index('"only')


def test_the_runtime_reads_an_off_on_row_as_the_card_with_no_row():
    from tests import test_spike2_mode_roster as R
    src = _src()
    assert "return coop.setting && !coop.onoff;" in R._lift(src, "static int coop_row_styles(void)\n{")
    assert 'if (str_starts(s, "switch")) coop.onoff = 1;' in src
    # On: the start menu's own style step and default style, CO-OP PLAY with no pick, no ENHANCED STANDARD entry
    assert "!coop_row_styles()" in R._lift(src, "static int sty_wanted(void)\n{")
    assert "if (!coop_row_styles()) return coop.style == 2u;" in R._lift(src, "static int coop_classic(void)\n{")
    assert "if (!d || coop_row_styles()) return;" in R._lift(src, "static void coop_style_held(void)\n{")
    assert "coop.plain = kind == 1u && !coop_row_styles();" in src
    assert "if (coop_row_styles() && !coop_classic()) kinds[n++] = 2u;" in src
    # Off: the row's value still switches co-op off as it always did (no start menu games, Start a competing player)
    assert "coop_row_mode(*(volatile const unsigned *)(unsigned long)coop.setting) != 0u" in R._lift(
        src, "static int coop_switched_on(void)\n{")
    # Insider Connected: an Off / On card keeps PAD-1443's per-game gate (Off: no game is one of ours, all report)
    wanted = R._lift(src, "static pm_addr coop_setting_wanted(void)\n{")
    assert "return only && v && !sw ? setting_addr(v) : 0;" in wanted


def test_an_older_cards_three_value_row_keeps_its_meaning():
    """A card written before PAD-1443 (no `switch` line) still reads 0 Off, 1 Classic, 2 Enhanced."""
    from tests import test_spike2_mode_roster as R
    src = _src()
    assert "return v <= 2u ? v : v == 3u ? 2u : v <= 6u ? 1u : 0u;" in R._lift(
        src, "static unsigned coop_row_mode(unsigned v)\n{")
    assert "return coop_row_mode(*(volatile const unsigned *)(unsigned long)coop.setting) == 1u;" in R._lift(
        src, "static int coop_classic(void)\n{")


def test_the_prebuilt_runtimes_are_built_from_these_sources():
    import hashlib
    sdk = os.path.dirname(RUNTIME)
    for pin in ("SOURCES.sha256", "SOURCES64.sha256"):
        with open(os.path.join(sdk, "prebuilt", pin), encoding="utf-8") as f:
            lines = [l.split() for l in f if l.strip() and not l.startswith(("#", "compiler"))]
        got = dict((name, digest) for digest, name in lines)
        with open(RUNTIME, "rb") as f:
            assert got["pad_mode_runtime.c"] == hashlib.sha256(f.read().replace(b"\r", b"")).hexdigest()


def test_the_write_asks_for_the_row_only_when_ticked(tmp_path):
    from pinball_decryptor.plugins.stern import service_menu as SM
    p = _project(tmp_path, {"coop_play": {"on": True}})
    assert "coop_play" not in [r[0] for r in SM.wanted(p)]           # unticked: PAD-1443's card, no row
    CP.save(p, True, menu=True)
    assert "coop_play" in [r[0] for r in SM.wanted(p)]
    CP.save(p, True, menu=False)
    assert "coop_play" not in [r[0] for r in SM.wanted(p)]


def test_the_tab_ticks_co_op_on_and_off_again(tmp_path, monkeypatch):
    """Ticked on a project with no co-op play, the row switches co-op play on too, and unticking it switches it off
    again; co-op play switched on at the Modes tab stays on when the row is unticked."""
    import pytest
    from tests.webui_harness import web_app
    from pinball_decryptor.webui.tabs import svcmenu
    monkeypatch.setattr(svcmenu, "_coop_refusal", lambda _cp, _p: "")    # a blank project names no game
    p = _project(tmp_path, {})
    with web_app(tmp_path / "app") as w:
        modes = w.window.service("modes")
        var = modes._project_var() if modes is not None else None
        if var is None:
            pytest.skip("no project folder variable in this window")
        w.run(lambda: var.set(p))
        w.drain()
        w.call("ui.select_tab", "svcmenu")
        w.drain()
        row = next(r for r in w.state("svcmenu")["settings"] if r["key"] == "coop_play")
        assert row["can"] and not row["on"] and row["note"] == "Not on the card: tick to add its row (and co-op play)."
        modes.set_coop = lambda on: CP.save(p, bool(on)) is not None    # the title check needs a real card
        w.call("svcmenu.set_row", "coop_play", True)
        w.drain()
        assert CP.load(p) and CP.menu_asked(p)
        w.call("svcmenu.set_row", "coop_play", False)
        w.drain()
        assert not CP.load(p) and not CP.menu_asked(p)


SWITCH_MAIN = r"""
@FNS@
static void kinds(const char *tag)
{
    unsigned k[6], n = team_menu_kinds(k), i;
    printf(" %s:", tag);
    for (i = 0; i < n; i++) printf("%u", k[i]);
}
int main(void)
{
    coop.setting = 0;                                   /* no row: PAD-1443's start menu */
    kinds("none");
    printf(",%d", coop_classic());
    coop.setting = (unsigned)(unsigned long)&row;       /* an Off / On row (coop.cfg `switch`) */
    coop.onoff = 1;
    row = 0;
    kinds("off");
    printf(",%d", coop_switched_on());
    row = 1;
    kinds("on");
    printf(",%d%d", coop_switched_on(), coop_classic());
    coop.style = 2u;                                    /* the start menu's CHARACTERS pick, as with no row */
    printf(",%d", coop_classic());
    printf("\n");
    return 0;
}
"""


def test_an_off_on_row_gives_the_start_menu_of_a_card_with_no_row(tmp_path):
    """Compiled from the runtime itself: On offers exactly what a card with no row offers (no ENHANCED STANDARD
    entry, the style the start menu's own pick), Off offers nothing."""
    from tests import test_pad1073_coop_row_three as T
    from tests import test_spike2_mode_roster as R
    R._cc()                                             # skips with no ELF toolchain (Windows, macOS)
    main = T.PRELUDE + SWITCH_MAIN.replace("@FNS@", T._fns(_src(), *T.ROW_FNS))
    out = R._host_run(tmp_path, main, flags=("-no-pie",)).strip()
    assert out == "none:1435,0 off:,0 on:1435,10,1"

def test_each_owner_keeps_co_op_always_on_unless_they_tick_the_row(tmp_path):
    """David (PR #53 review): "We need to maintain the existing option of just getting to coop in the menu. We need
    flexibility for each person since this is a modular setup." Round 2's ``menu`` flag, left in projects and co-op files
    from before PAD-1443, asks for no row: those cards keep co-op always on the start menu. Only the tick asks."""
    from pinball_decryptor.plugins.stern import service_menu as SM
    p = _project(tmp_path, {"coop_play": {"on": True, "menu": True}})
    assert not CP.menu_asked(p) and "coop_play" not in [r[0] for r in SM.wanted(p)]
    CP.save(p, True)                                               # any later save drops the old flag
    side = json.load(open(os.path.join(p, ".staged_changes.json"), encoding="utf-8"))["coop_play"]
    assert "menu" not in side and not side.get(CP.ROW_KEY)
    CP.save(p, True, menu=True)                                    # the Service menu tab's tick
    assert CP.menu_asked(p) and "coop_play" in [r[0] for r in SM.wanted(p)]
    # a co-op file carries the tick as it is; an old one's "menu" brings no row
    out = str(tmp_path / "coop.json")
    CP.export_settings(p, out)
    head = json.load(open(out, encoding="utf-8"))
    assert head[CP.ROW_KEY] is True and "menu" not in head
    q = _project(tmp_path / "q", {})
    CP.import_settings(q, out)
    assert CP.menu_asked(q)
    head[CP.ROW_KEY] = False
    head["menu"] = True
    json.dump(head, open(out, "w", encoding="utf-8"))
    r = _project(tmp_path / "r", {})
    CP.import_settings(r, out)
    assert CP.load(r) and not CP.menu_asked(r)


# ---- David (PR #53 review): "The user should have the option to place the co-op selection style in either place ...
# Do we have options for either or both?" - the style picked on the start menu, in the service menu, or both -----------

def test_where_the_style_is_picked_is_the_owners(tmp_path):
    from pinball_decryptor.plugins.stern import service_menu as SM
    p = _project(tmp_path, {"coop_play": {"on": True}})
    assert CP.load_place(p) == "start" and not CP.menu_asked(p)                  # as every card has it
    assert CP.menu_row(p) == (CP.MENU_VALUES, (), CP.MENU_DEFAULT, CP.MENU_HELP)  # a ticked row: Off / On
    assert CP.place_line(p, _GZ_HEAD) == ""
    CP.save_style(p, "characters")
    for place in ("service", "both"):
        CP.save_place(p, place)
        assert CP.load_place(p) == place and CP.menu_asked(p)                    # the row goes on the card
        assert "coop_play" in [r[0] for r in SM.wanted(p)]
        values, names, default, help_text = CP.menu_row(p)
        assert (values, names) == (4, ("Off", "Normal", "Characters", "Enhanced"))
        assert names[default - 1] == "Characters" and len(help_text) <= 63       # starts on the default style
        assert CP.place_line(p, _GZ_HEAD) == "styles %s\n" % place
        assert CP.place_line(p, b"\x7fELF\x02\x01" + bytes(58)) == ""            # Spike 3 keeps its own row
    CP.save(p, True)                                                             # a later save keeps the place
    assert CP.load_place(p) == "both"
    E_menu = E._CoopMenu(lambda *a, **k: None, p)
    key, values, names, opts = E_menu.wanted()
    assert (key, values, names) == ("coop_play", 4, CP.MENU_STYLE_NAMES) and opts["default"] == 3
    assert "onoff" not in opts and "from_zero" not in opts                       # a named row: stored 1 to 4
    CP.save_place(p, "start")
    assert not CP.menu_asked(p) and CP.load_place(p) == "start"


_GZ_HEAD = b"\x7fELF\x01\x01" + bytes(58)                                        # a 32-bit (Spike 2) program's head

STYLE_MAIN = r"""
@FNS@
static unsigned coop_card_style(void)
@CARD@
int main(void)
{
    unsigned v;
    coop.setting = (unsigned)(unsigned long)&row;       /* the row picks the style (coop.cfg `switch`, `styles`) */
    coop.onoff = 1;
    coop.rowsty = 1;
    coop.style_default = 3;
    for (v = 1; v <= 4; v++) {
        row = v;
        printf("%u:%d%u ", v, coop_switched_on(), coop_card_style());
    }
    row = 3;
    {
        unsigned k[6], n = team_menu_kinds(k), i;
        for (i = 0; i < n; i++) printf("%u", k[i]);
    }
    coop.rowsty = 0;                                    /* an Off / On row: the card's own default style */
    row = 1;
    printf(" %d%u\n", coop_switched_on(), coop_card_style());
    return 0;
}
"""


def test_the_runtime_reads_a_style_row(tmp_path):
    """Compiled from the runtime itself: the named row's 1 is Off, 2-4 play NORMAL, CHARACTERS, ENHANCED; the start
    menu's entries are a card's with no row; an Off / On row keeps the card's own default style."""
    from tests import test_pad1073_coop_row_three as T
    from tests import test_spike2_mode_roster as R
    R._cc()                                             # skips with no ELF toolchain (Windows, macOS)
    src = _src()
    card = R._lift(src, "static unsigned coop_card_style(void)\n{")
    card = card[card.index("{"):]
    main = T.PRELUDE + STYLE_MAIN.replace("@FNS@", T._fns(src, *T.ROW_FNS)).replace("@CARD@", card)
    out = R._host_run(tmp_path, main, flags=("-no-pie",)).strip()
    assert out == "1:01 2:11 3:12 4:13 1435 13"


def test_the_service_menu_alone_takes_the_start_menus_step_away():
    from tests import test_spike2_mode_roster as R
    src = _src()
    assert "&& coop.rowsty != 1u;" in R._lift(src, "static int sty_wanted(void)\n{")
    assert 'if (str_starts(s, "styles service")) coop.rowsty = 1u;' in src
    assert 'if (str_starts(s, "styles both")) coop.rowsty = 2u;' in src
    assert "if (coop.rowsty == 1u) coop_style_held();" in src                    # CO-OP from the start menu
    assert "else if (coop_teammates() && coop.rowsty == 1u) coop_style_held();" in src   # a team game
