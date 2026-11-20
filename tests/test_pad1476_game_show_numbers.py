"""PAD-1476: any light show the game's own modes start, picked for a mode of the user's (its Lights page, a blocks
mode's "Play the game's light show") or for the co-op intro, played by the game's OWN number for it.

DoomWalrus666 (Godzilla): "I would like to select from an existing game light show to add to a custom mode or my
Co-op teams intro video." The shows each of the game's modes starts are read off its program (PAD-1475,
clip_shows.ShowReading.modes); every port now carries the game's show starter, its "stop every show with this
number" (found off the starter: clip_shows.locate_stopper) and its table's size, so the runtime can start and stop
any of them (pad_mode_runtime.c pm_game_show_number, ci_show_start)."""
import pathlib
import re

import pytest

from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import clip_shows as SH
from pinball_decryptor.plugins.stern import coop_play as CP
from pinball_decryptor.plugins.stern import mode_project as MP

ROOT = pathlib.Path(__file__).resolve().parents[1]
SDK = ROOT / "tools" / "spike2_emu" / "modes" / "sdk"
RUNTIME = (SDK / "pad_mode_runtime.c").read_text(encoding="utf-8")
LE = MP.profile_from_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
OLD_PRO = MP.GODZILLA_PRO_1_15


def _lines(port):
    return [ln.split("#", 1)[0].split() for ln in port.read_text(encoding="utf-8").splitlines()]


# ---- the ports ---------------------------------------------------------------------------------------------------
def test_every_port_can_start_and_stop_the_games_shows_by_number():
    ports = sorted((SDK / "ports").glob("*.port"))
    assert len(ports) >= 69
    for port in ports:
        lines = _lines(port)
        names = [(p[0], p[1]) for p in lines if len(p) >= 2]
        for need in (("site", "show_start"), ("site", "show_stop_number"), ("value", "show_count")):
            assert names.count(need) == 1, (port.name, need)
        stop = next(p for p in lines if p[:2] == ["site", "show_stop_number"])
        assert int(stop[3], 0) >> 16 == 0xE92D, port.name                       # push {...}: a function's start
        count = int(next(p for p in lines if p[:2] == ["value", "show_count"])[2])
        assert 100 <= count <= 600, port.name
        assert MP._show_numbers(MP.read_port(str(port))) == count, port.name


def test_bonds_hand_named_stoppers_are_the_ones_the_locator_finds():
    """PAD-642 named James Bond LE/Pro 1.06's by hand; port_show_numbers.py left them and found the same two (its
    sweep: one function fits on each of 82 Spike 2 builds)."""
    for name, va in (("james_bond_le-1.06", 0x2FCE04), ("james_bond_pro-1.06", 0x207220)):
        stop = next(p for p in _lines(SDK / "ports" / (name + ".port")) if p[:2] == ["site", "show_stop_number"])
        assert int(stop[2], 0) == va


def test_godzillas_stopper_is_the_one_read_by_hand():
    stop = next(p for p in _lines(SDK / "ports" / "godzilla_le-1.16.port") if p[:2] == ["site", "show_stop_number"])
    assert (int(stop[2], 0), int(stop[3], 0), int(stop[4], 0)) == (0x3F3BD8, 0xE92D4070, 0xE3066278)


class _Prog:
    """A program of a few words: Godzilla LE 1.16's starter head and its stopper (0x3f3bd8), the process fork
    beside it (which copies the number, never compares it), at their own addresses."""

    def __init__(self, words):
        self.w = words

    def word(self, va):
        return self.w[va]

    def movwt_sites(self, value):
        lo, hi = value & 0xFFFF, value >> 16
        out = []
        for va, w in self.w.items():
            m = SH._movwt(w)
            m2 = SH._movwt(self.w.get(va + 4, 0))
            if m and m[1] == 0 and m[2] == lo and m2 and m2[1] == 1 and m2[2] == hi and m2[0] == m[0]:
                out.append(va)
        return out

    def func_start(self, va):
        while va - 4 in self.w:
            va -= 4
        return va


def _words(base, ws):
    return {base + 4 * i: w for i, w in enumerate(ws)}


STARTER = _words(0x1F34D4, [0xE92D47F0, 0xE2508000, 0x0A000054, 0xE30C3158, 0xE340305F, 0xE5933000, 0xE1580003,
                            0x2A000050, 0xE3069278, 0xE340907D, 0xE5994000, 0x11C089B6, 0xE8BD87F0])
STOPPER = _words(0x3F3BD8, [0xE92D4070, 0xE3066278, 0xE340607D, 0xE5964000, 0xE3540000, 0x0A000018, 0xE1A05000,
                            0xE3A02000, 0xEA000002, 0xE5944084, 0xE3540000, 0x0A00000E, 0xE1D439B6, 0xE1530005,
                            0x1AFFFFF9, 0xEBFFFC6F, 0xEBFFFC33, 0xE8BD8070])
FORK = _words(0x3F3140, [0xE92D43F8, 0xE3065278, 0xE340507D, 0xE5953004, 0xEBFFFF9C, 0xEBFFFF9C, 0xE1D569B6,
                         0xE1A00000, 0xE8BD83F8])


def test_the_locator_finds_the_stopper_and_not_the_fork():
    prog = _Prog({**STARTER, **STOPPER, **FORK})
    assert SH._number_facts(prog, 0x1F34D4)[1] == 0x96
    assert SH.locate_stopper(prog, 0x1F34D4) == 0x3F3BD8
    assert SH.locate_stopper(_Prog({**STARTER, **FORK}), 0x1F34D4) == 0     # the fork alone is no stopper


# ---- the mode ----------------------------------------------------------------------------------------------------
def test_a_show_by_number_is_checked_against_the_builds_table():
    assert MP.show_number("#211") == 211 and MP.show_number("Strobe burst") == 0 and MP.show_number("#") == 0
    assert MP.show_words("#211") == "light show 211" and MP.show_words("Blue fade") == "Blue fade"
    assert MP.game_show_ok(LE, "#211") and MP.game_show_ok(LE, "Strobe burst")
    assert not MP.game_show_ok(LE, "#361") and not MP.game_show_ok(LE, "#0")
    spec = MP.ModeSpec(name="Kaiju", title=LE.key, show_start="#211", show_end="#348", show_hit="#359")
    assert MP.validate_shows(spec, LE) == []
    assert MP.show_lines(spec, LE) == ["show_start     #211", "show_end       #348", "show_hit       #359"]
    bad = MP.validate_shows(MP.ModeSpec(name="Kaiju", title=LE.key, show_start="#400"), LE)
    assert bad == ["Godzilla Premium/LE 1.16 cannot play the game's light show 400 at the mode's start: its "
                   "numbers are 1-360."]


def test_a_mode_taken_to_another_build_drops_its_numbered_shows():
    """Another build numbers its shows its own way, so a number is never carried over; a named one still is."""
    spec = MP.ModeSpec(name="Kaiju", title=LE.key, show_start="#211", show_end="Blue fade")
    pro = MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port"))
    out, _words_ = MP.retarget(spec, pro)
    assert out.show_start == "" and out.show_end == "Blue fade"


def test_a_blocks_modes_numbered_show_is_checked_too():
    prog = {"scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "game_show", "name": "#211"}]}]}
    checks = BM.card_checks(LE)
    assert checks["show_numbers"] == 361
    said = [p for p in BM.problems(prog, **checks) if "light show" in p]
    assert said == []
    prog["scripts"][0]["do"][0]["name"] = "#999"
    said = [p for p in BM.problems(prog, **checks) if "light show" in p]
    assert len(said) == 1 and "cannot play by its number (its numbers are 1-360)" in said[0]


# ---- the runtime -------------------------------------------------------------------------------------------------
def test_the_runtime_plays_a_named_number_through_the_games_own_starter():
    named = RUNTIME[RUNTIME.index("int pm_game_show_named(const char *name)"):]
    named = named[:named.index("\n}\n")]
    assert "name[0] == '#'" in named and "pm_game_show_number(n)" in named
    start = RUNTIME[RUNTIME.index("static int show_number_start("):]
    start = start[:start.index("\n}\n")]
    assert 'fn("show_start")' in start and "OG_SELF(" in start           # ours, not refused as the game's own
    assert "num >= shownum_n" in start                                    # past the table is the game's error
    kill = RUNTIME[RUNTIME.index("static void show_kill("):]
    assert 'fn("show_stop_number"))((unsigned)-show_now.n)' in kill[:kill.index("\n}\n")]
    assert "shownum_arm();" in RUNTIME


def test_the_intro_starts_its_show_with_it_and_stops_it_as_it_ends():
    for fn_, call in (("static void ci_sound_start(", "ci_show_start();"),
                      ("static void ci_played(", 'ci_show_stop("the co-op intro is over");'),
                      ("static void ci_over(", 'ci_show_stop("the co-op intro is over");')):
        body = RUNTIME[RUNTIME.index(fn_):]
        assert call in body[:body.index("\n}\n")], fn_
    assert 'str_starts(s, "intro_show ")' in RUNTIME


# ---- the co-op intro ---------------------------------------------------------------------------------------------
def test_the_intro_keeps_its_show_and_coop_cfg_names_it_where_the_card_can():
    chars = CP._characters({"intro": "coop/intro_video.mp4", "intro_show": 211, "list": []})
    assert chars["intro_show"] == 211
    assert "intro_show" not in CP._characters({"intro": "x.mp4", "intro_show": "nope"})
    sites, values = ("show_start", "show_stop_number"), {"show_count": 361}
    assert CP.intro_show_number(chars, sites, values) == 211
    assert CP.intro_show_number(chars, ("show_start",), values) == 0                 # no stopper: none
    assert CP.intro_show_number({"intro_show": 400}, sites, values) == 0             # past the table
    assert CP.intro_show_number({}, sites, values) == 0


def test_coop_cfg_has_the_intro_show_line():
    from tests.test_pad1114_coop_intro_runtime import _elf
    elf = _elf()
    port = MP.read_port(str(SDK / "ports" / "godzilla_le-1.16.port"))
    sites = sorted(set(port["site"]) | set(port.get("data", {})))
    lines = CP.character_lines(elf, {"pick": False, "list": [], "intro": "coop/intro_video.mp4", "intro_show": 211},
                               sites, dict(port["value"]))
    assert "intro_show 211" in lines and lines.index("intro_show 211") == lines.index("intro_hold 96") + 1
    lines = CP.character_lines(elf, {"pick": False, "list": [], "intro_show": 211}, sites, dict(port["value"]))
    assert not any(re.match(r"intro_show", ln) for ln in lines)                         # no intro, no show


def test_the_intro_show_is_offered_on_the_co_op_dialog():
    js = (ROOT / "pinball_decryptor" / "webui" / "static" / "js" / "tabs" / "modes_dialogs.js").read_text("utf-8")
    assert 'call("modes.coop_intro_show"' in js and "Light show with it" in js
    from pinball_decryptor.webui.tabs import modes as M
    assert hasattr(M.ModesTab, "coop_intro_show") if hasattr(M, "ModesTab") else pytest.skip("no ModesTab")


# ---- the picks -----------------------------------------------------------------------------------------------------
def test_the_picks_are_the_modes_own_shows_grouped_by_the_mode():
    """Godzilla LE 1.16's reading (PAD-1475 sweep): Hedorah starts 211 and 210 of its own, every battle 348 too."""
    from types import SimpleNamespace

    from pinball_decryptor.plugins.stern import clip_modes as CM
    from pinball_decryptor.webui.tabs.modes import ModesTab
    sh = SH.ShowReading(origin="port", count=361, modes={
        "cmode_hedorah": [[211, 16, 1], [210, 20, 1], [348, 24, 2], [999, 28, 1]],
        "cmode_battle_vs_gigan": [[148, 40, 1], [348, 44, 1]],
        "cmode_battle_vs_megalon": [[348, 50, 1]]}, names={"148": "Strobe burst"})
    reading = CM.Reading(labels={"cmode_hedorah": "Hedorah", "cmode_battle_vs_gigan": "Battle vs Gigan",
                                 "cmode_battle_vs_megalon": "Battle vs Megalon"})
    clips = CM.CardClips(card="card", game="godzilla_le", version="1.16.0", reading=reading, shows=sh.to_json())   # as read_card names it
    tab = SimpleNamespace(_how=clips, _title=lambda: LE)
    rows = ModesTab._mode_show_rows(tab)
    assert [(r["group"], r["value"], r["label"]) for r in rows] == [
        ("Battle vs Gigan", "#148", "Strobe burst (Battle vs Gigan)"),
        ("Hedorah", "#210", "Light show 210 (Hedorah)"),
        ("Hedorah", "#211", "Light show 211 (Hedorah)"),
        ("Started by several of its modes", "#348", "Light show 348 (Hedorah, Battle vs Gigan +1)")]   # 999: past it
    other = SimpleNamespace(_how=clips, _title=lambda: MP.profile_from_port(str(SDK / "ports" / "godzilla_pro-1.16.port")))
    assert ModesTab._mode_show_rows(other) == []                  # another build's card: its numbers are not these
    assert ModesTab._mode_show_rows(SimpleNamespace(_how=None, _title=lambda: LE)) == []
