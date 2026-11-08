"""PAD-1017: co-op play on the card - the Write tab's tick, the build's gate, coop.cfg beside the runtime, and the
titles it is offered on (the latest of each title without co-op of its own)."""
import os
import re

import pytest

from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.plugins.stern import sound_modes as SMo

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GZ_ELF = "C:/tmp/PAD-1010/elfs/godzilla_le-1_16_0_spike2.elf"


def _read(p):
    with open(p, encoding="utf-8") as f:
        return f.read()


def _latest():
    """The newest profile of each title."""
    best = {}
    for p in MP.profiles().values():
        v = tuple(int(x) for x in p.version.split("."))
        if p.game_dir not in best or v > best[p.game_dir][0]:
            best[p.game_dir] = (v, p)
    return [p for _v, p in best.values()]


def test_offered_on_every_latest_title_without_its_own_coop():
    latest = _latest()
    own = [p for p in latest if SMo.title_key(p).startswith(CP.OWN_COOP)]
    offered = [p for p in latest if not CP.title_refusal(p)]
    assert len(latest) == 53 and len(own) == 15
    assert len(offered) == 38
    assert {SMo.title_key(p) for p in offered} >= {"godzilla_le-1.16", "james_bond_le-1.06", "jurassic_park_the_pin-1.05"}
    for p in own:
        assert CP.title_refusal(p) == CP.OWN % p.label
    assert CP.title_refusal(None) == CP.NO_TITLE


@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_coop_cfg_names_the_right_flipper_button():
    with open(GZ_ELF, "rb") as f:
        elf = f.read()
    assert CP.cfg_text(elf).startswith("coop on\nbutton 59\naward ")    # PAD-1028: then the awards ticked


def test_no_flipper_buttons_no_cfg():
    with pytest.raises(CP.CoopError):
        CP.cfg_text(b"not a program")


def test_the_plan_puts_coop_cfg_beside_the_runtime(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import mode_write as MW
    prof = MP.profile_for_card("godzilla", "1.16") if hasattr(MP, "profile_for_card") else None
    prof = prof or next(p for p in MP.profiles().values() if SMo.title_key(p) == "godzilla_le-1.16")
    monkeypatch.setattr(CP, "cfg_text", lambda elf, awards=None, characters=None, sites=(), values=None, setting=0,
                        only=False: "coop on\nbutton 59\n")
    monkeypatch.setattr(MW, "find_port", lambda prof, elf: MP.port_path(prof))
    result = MW.plan(str(tmp_path), b"", b"", b"elf", str(tmp_path / "scratch"), modes_on=False,
                     coop=True, coop_prof=prof)
    assert result is not None and result.build is None
    assert _read(result.coop_file) == "coop on\nbutton 59\n"
    assert any(line.startswith("co-op play: hold the right flipper button") for line in result.lines)


def test_the_card_install_and_the_emulator_carry_coop_cfg():
    install = _read(os.path.join(REPO, "tools", "spike2_emu", "mode_install.py"))
    assert '("coop.cfg", 0o100644)' in install
    assert re.search(r'STANDALONE_FILES = \([^)]*"coop\.cfg"', install)
    for rel in ("cardmodes.sh", "tryit.sh"):
        text = _read(os.path.join(REPO, "tools", "spike2_emu", "modes", rel))
        assert '"$DUMP/coop.cfg"' in text or '"$DUMP"/coop.cfg' in text
    stage = _read(os.path.join(REPO, "pinball_decryptor", "plugins", "stern", "mode_write.py"))
    assert 'if getattr(result, "coop_file", ""):' in stage


def test_the_modes_tab_tick_saves_the_choice_and_says_how_teammates_join(tmp_path, monkeypatch):
    """David (PAD-1017): co-op is a part of the mode maker - its tick is on the Modes tab, not the Write tab."""
    from pinball_decryptor.webui.tabs import modes as M
    from pinball_decryptor.webui.tabs import write as W
    from pinball_decryptor.core import staged_changes

    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    staged_changes.save(str(tmp_path), {"audio": {"x": "y"}})
    assert svc.set_coop(True) is True
    data = staged_changes.load(str(tmp_path))
    assert data[CP.STAGED_KEY] == {"on": True} and data["audio"] == {"x": "y"}
    assert state["coop_shown"] is True and state["coop_on"] is True
    assert state["coop_note"].startswith("On the card: Hold the right flipper button and press Start")
    assert state["coop_note"].endswith("Its scores stay off Insider Connected.")
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "Venom LE 1.07 has co-op play of its own.")
    svc._publish_coop(str(tmp_path))
    assert state["coop_note_kind"] == "err"
    assert svc.set_coop(False) is True
    assert CP.STAGED_KEY not in staged_changes.load(str(tmp_path))
    assert state["coop_on"] is False and state["coop_locked"] is True    # PAD-1062: greyed out, why under it
    assert state["coop_note"] == "Venom LE 1.07 has co-op play of its own." and state["coop_note_kind"] == ""
    # the Write tab has no co-op tick any more
    assert not hasattr(W.WriteTab, "set_coop")
    js = _read(os.path.join(REPO, "pinball_decryptor", "webui", "static", "js", "tabs", "write.js"))
    assert "coop" not in js
    assert 'call("modes.set_coop", v)' in _read(os.path.join(REPO, "pinball_decryptor", "webui", "static", "js",
                                                              "tabs", "modes.js"))


def test_a_game_with_its_own_coop_greys_the_tick_out(tmp_path, monkeypatch):
    """Peanutsfr (PAD-1062): the Co-op play tick is greyed out on a game with co-op of its own, with why under it,
    and cannot be ticked there; a project ticked before still unticks; a game the app can give co-op is untouched."""
    from pinball_decryptor.webui.tabs import modes as M
    from pinball_decryptor.core import staged_changes

    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "get", lambda k: state.get(k), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    latest = {SMo.title_key(p): p for p in _latest()}
    own = next(p for k, p in latest.items() if k.startswith("jaws_"))
    gz = next(p for k, p in latest.items() if k.startswith("godzilla_") and not CP.title_refusal(p))
    title = {"prof": own}
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: title["prof"])
    svc._publish_coop(str(tmp_path))
    assert state["coop_locked"] is True and state["coop_on"] is False
    assert state["coop_note"] == CP.OWN % own.label and state["coop_note_kind"] == ""
    assert svc.set_coop(True) is False
    assert CP.STAGED_KEY not in staged_changes.load(str(tmp_path))
    # ticked before this release: still shown on, in red, and can be unticked
    CP.save(str(tmp_path), True)
    svc._publish_coop(str(tmp_path))
    assert state["coop_locked"] is False and state["coop_on"] is True and state["coop_note_kind"] == "err"
    assert svc.set_coop(False) is True and state["coop_locked"] is True
    # a game the app can give co-op, and an unread title, keep the tick
    for prof in (gz, None):
        title["prof"] = prof
        svc._publish_coop(str(tmp_path))
        assert state["coop_locked"] is False and state["coop_note"] == ""
    assert "disabled=${s.coop_locked}" in _read(os.path.join(REPO, "pinball_decryptor", "webui", "static", "js",
                                                             "tabs", "modes.js"))


def test_the_public_help_and_guide_do_not_name_it():
    """A part of the mode maker, so only its (preview) help names it."""
    from pinball_decryptor.webui import help_content as H
    assert "Co-op play" not in _read(os.path.join(REPO, "docs", "guide", "using-the-app.md"))
    src = _read(os.path.join(REPO, "pinball_decryptor", "webui", "help_content.py"))
    assert src.count('"### Co-op play') == 0
    assert any(t == "Co-op play" for t, _b in H.PREVIEW_HELP["modes"]["Modes"])


def test_the_build_gate_leaves_it_out_of_a_direct_write(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "preview_on", lambda: True)
    said = []
    assert E._coop_for_build(str(tmp_path), False, lambda m, *a: said.append(m)) is None and not said
    CP.save(str(tmp_path), True)
    assert E._coop_for_build(str(tmp_path), True, lambda m, *a: said.append(m)) is None
    assert "direct-SD write" in said[-1]


def test_the_build_leaves_it_out_without_the_mode_maker(tmp_path, monkeypatch):
    from pinball_decryptor.plugins.stern import engine as E
    from pinball_decryptor.plugins.stern import mode_write as MW
    monkeypatch.setattr(MW, "preview_on", lambda: False)
    CP.save(str(tmp_path), True)
    said = []
    assert E._coop_for_build(str(tmp_path), False, lambda m, *a: said.append(m)) is None
    assert "mode maker" in said[-1]


# ---- round 2 (DoomWalrus666, David): co-op switched in the game's own service menu ----------------------------------
@pytest.mark.skipif(not os.path.isfile(GZ_ELF), reason="no Godzilla LE 1.16 program here")
def test_the_service_menu_row_and_the_cfg_name_its_live_value():
    from pinball_decryptor.plugins.stern import menu_settings as M
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    with open(GZ_ELF, "rb") as f:
        elf = f.read()
    settings, writes, _cat, refused = M.plan_many(
        AdjustmentTable(elf), [__import__("pinball_decryptor.plugins.stern.engine", fromlist=["_"])._CoopMenu(lambda *a: None).wanted()])
    assert not refused and len(settings) == 1
    s = settings[0]
    # PAD-1042: 0 Off, 1 Co-op, 2 Team 2v2 (Off/On's 0 and 1 keep their meaning), shown as a number the way GAME ID
    # is, Off to start with
    assert (s.caption, s.values, s.low, s.default, s.kind) == ("Co-op Play", 4, 0, 0, M.number_kind(AdjustmentTable(elf)))
    assert s.kind == 2 and len(CP.MENU_HELP) <= 63
    assert CP.MENU_HELP.startswith("0 Off, 1 Co-op, 2 Team 2v2, 3 Team 2v1") and "Insider mostly off" in CP.MENU_HELP
    assert s.help == CP.MENU_HELP and s.where == "Adjustments > Machine Settings > Attract Mode"
    raw = bytearray(elf)
    for off, data in writes.items():
        raw[off:off + len(data)] = data
    assert M.check(bytes(raw), s) in ([], ["no menu page lists it"])           # the page record is placed by the Write
    head = lambda text: text[:text.find("award ")]                               # PAD-1028's award lines follow
    assert head(CP.cfg_text(elf, setting=s.live)) == "coop on\nbutton 59\nsetting 0x%08x\n" % s.live
    assert head(CP.cfg_text(elf, setting=s.live, only=True)) == "coop on\nbutton 59\nsetting 0x%08x\nonly\n" % s.live
    assert head(CP.cfg_text(elf)) == "coop on\nbutton 59\n"                    # always on: no setting line


def test_the_menu_choice_is_kept_in_the_sidecar(tmp_path):
    assert not CP.menu_asked(str(tmp_path))
    CP.save(str(tmp_path), True, menu=True)
    assert CP.load(str(tmp_path)) and CP.menu_asked(str(tmp_path))
    CP.save(str(tmp_path), True)                                               # None keeps it
    assert CP.menu_asked(str(tmp_path))
    CP.save(str(tmp_path), True, menu=False)
    assert CP.load(str(tmp_path)) and not CP.menu_asked(str(tmp_path))
    CP.save(str(tmp_path), False)
    assert not CP.load(str(tmp_path)) and not CP.menu_asked(str(tmp_path))


def test_a_spare_the_program_cannot_give_is_passed_over():
    """Iron Maiden Pro 1.18's first spare adjustment shares its row caption: the next one takes CO-OP PLAY."""
    elf = "C:/tmp/PAD-1010/elfs/iron_maiden_pro-1_18_0.elf"
    if not os.path.isfile(elf):
        pytest.skip("no Iron Maiden Pro 1.18 program here")
    from pinball_decryptor.plugins.stern import menu_settings as M
    from pinball_decryptor.plugins.stern.adjustments import AdjustmentTable
    with open(elf, "rb") as f:
        t = AdjustmentTable(f.read())
    settings, _w, _c, refused = M.plan_many(t, [(M.COOP_PLAY, 4, (), {"help_text": CP.MENU_HELP, "from_zero": True})])
    assert not refused and settings[0].key == M.COOP_PLAY


def test_the_modes_tab_sub_tick_switches_it_in_the_service_menu(tmp_path, monkeypatch):
    from pinball_decryptor.webui.tabs import modes as M
    svc = M.ModesTab.__new__(M.ModesTab)
    state = {}
    monkeypatch.setattr(svc, "set", lambda **kw: state.update(kw), raising=False)
    monkeypatch.setattr(svc, "project", lambda: str(tmp_path), raising=False)
    monkeypatch.setattr(svc, "_say", lambda *a, **k: None, raising=False)
    monkeypatch.setattr(CP, "project_title", lambda project, probe=False: object())
    monkeypatch.setattr(CP, "title_refusal", lambda prof: "")
    assert svc.set_coop_menu(True) is False                                    # co-op first
    assert svc.set_coop(True) is True and state["coop_menu"] is False
    assert svc.set_coop_menu(True) is True
    assert state["coop_on"] is True and state["coop_menu"] is True
    assert "CO-OP PLAY in the game's service menu" in state["coop_note"]
    assert "2 (Team 2v2) makes players 1 and 2 a team against players 3 and 4" in state["coop_note"]
    assert "at 0 the game plays and reports as it always has" in state["coop_note"]
    assert svc.set_coop_menu(False) is True and state["coop_menu"] is False
    assert state["coop_note"].endswith("Its scores stay off Insider Connected.")
    js = _read(os.path.join(REPO, "pinball_decryptor", "webui", "static", "js", "tabs", "modes.js"))
    assert 'call("modes.set_coop_menu", v)' in js


def test_the_build_takes_the_row_and_leaves_co_op_out_without_it():
    src = _read(os.path.join(REPO, "pinball_decryptor", "plugins", "stern", "engine.py"))
    assert "coop_menu = (_CoopMenu(log) if _coop_on and _CP_m.menu_asked(assets_dir) else None)" in src
    assert "_coop_on = False" in src and "coop_setting = coop_menu.setting.live" in src
    assert "coop_setting=coop_setting," in src


def test_the_runtime_gate_holds_back_only_while_co_op_play_is_on():
    from tests import test_spike2_mode_roster as R
    src = _read(os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c"))
    body = R._lift(src, "static int insider_holding(unsigned while_at, unsigned value)")
    assert "return !while_at || (value >= 1u && value <= 3u);" in body         # no row: always; a row: 1-3
    gate = R._lift(src, "static int on_agent_begin(unsigned *r)")
    assert gate.index("insider_holding(") < gate.index("insider_achq >= 0")    # Off: nothing held, the query too
    arm = R._lift(src, "static int insider_arm(void)")
    assert "if (at && !attract_wanted() && maps_has(at, 4, MAP_R))" in arm   # only a card of co-op alone
    assert "return only ? v : 0;" in R._lift(src, "static unsigned coop_setting_wanted(void)\n{")   # ... the build says
    add = R._lift(src, "static unsigned coop_add_wrap(unsigned r0, unsigned r1, unsigned r2, unsigned r3)")
    assert "coop_switched_on() && coop_button_held()" in add                   # Off: Start adds a competing player
    assert "return *(volatile const unsigned *)(unsigned long)coop.setting == 1u;" in R._lift(
        src, "static int coop_switched_on(void)")


# ---- round 2: the gate itself, lifted and run (a host C toolchain; on Windows compile it in PAD-Runtime) ---------------
GATE_MAIN = r"""
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
static void say(const char *f, ...) { (void)f; }
static void str_copy(char *dst, unsigned cap, const char *src, unsigned n) { (void)n; strncpy(dst, src, cap - 1); }
#define INSIDER_ENDPOINT_MAX 96
static char insider_endpoint[INSIDER_ENDPOINT_MAX];
static unsigned insider_dropped[4];
static int insider_achq = 28;
static unsigned insider_achq_held;
static unsigned coop_value = 0;                       /* the CO-OP PLAY row's live value (0 Off, 1 Co-op, 2 Team 2v2) */
@BLOCKED@
@FNS@
static int ask(const char *endpoint, unsigned type)
{
    unsigned r[8] = {0};
    strcpy(insider_endpoint, endpoint);
    r[2] = type;
    return on_agent_begin(r);
}
int main(void)
{
    insider_while = (unsigned)(unsigned long)&coop_value;
    coop_value = 0;
    printf("off %d %d %d %d\n", ask("/api/v3/game/session_end", 5), ask("/api/v1/game/high_score_events", 5),
           ask("/ingest/v1/game/game_events", 5), ask("", 28));
    coop_value = 1;
    printf("on %d %d %d %d %d\n", ask("/api/v3/game/session_end", 5), ask("/api/v1/game/high_score_events", 5),
           ask("/ingest/v1/game/game_events", 5), ask("", 28), ask("/api/v1/player/properties", 5));
    coop_value = 2;                                      /* PAD-1042: Team 2v2 holds back as co-op does */
    printf("teams %d %d %d %d\n", ask("/api/v3/game/session_end", 5), ask("/api/v1/game/high_score_events", 5),
           ask("/ingest/v1/game/game_events", 5), ask("", 28));
    insider_while = 0;                                   /* a card with modes: the whole gate */
    coop_value = 0;
    printf("modes %d %d\n", ask("/api/v3/game/session_start", 5), ask("", 28));
    return 0;
}
"""


def test_the_gate_holds_back_only_while_co_op_play_is_on(tmp_path):
    from tests import test_spike2_mode_roster as R
    src = _read(os.path.join(REPO, "tools", "spike2_emu", "modes", "sdk", "pad_mode_runtime.c"))
    blocked = src[src.index("static const char *const INSIDER_BLOCKED[] = {"):]
    blocked = blocked[:blocked.index("};") + 2]
    fns = "\n".join(R._lift(src[src.index(sig + "\n{"):], sig) for sig in (     # the bodies, not a declaration
        "static int str_starts(const char *s, const char *prefix)",
        "static int insider_blocked(const char *endpoint)",
        "static int insider_holding(unsigned while_at, unsigned value)")) + "\nstatic unsigned insider_while;\n" + \
        R._lift(src, "static int on_agent_begin(unsigned *r)")
    out = R._host_run(tmp_path, GATE_MAIN.replace("@BLOCKED@", blocked).replace("@FNS@", fns),
                      flags=("-no-pie",)).splitlines()
    assert out == ["off 0 0 0 0",            # CO-OP PLAY Off: the session, high scores, events and query all go out
                   "on 1 1 1 1 0",           # On: all held back; the rest of Insider Connected still goes
                   "teams 1 1 1 1",          # PAD-1042: Team 2v2 holds back the same
                   "modes 1 1"]              # a card with modes: always held back
