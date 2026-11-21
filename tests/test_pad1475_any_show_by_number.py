"""PAD-1475 (reopened): more of the game's light shows named, and any of them picked by its number.

The reading names every number of the game's show table it can (not only the ones a mode starts by a fixed number)
and gives a show whose body is one mode's own code to that mode; the show reel can play every number
(``reel_list.py --all``) and the port says which it played (``text show_reeled``); the Modes tab lists each mode's
shows, the other ones seen lighting, and offers "Another, by its number" with what the app knows of the number.
"""
import dataclasses
import importlib.util
import json
import os
import shutil
from types import SimpleNamespace

import pytest

from pinball_decryptor.plugins.stern import clip_modes as CM
from pinball_decryptor.plugins.stern import clip_shows as SH
from pinball_decryptor.plugins.stern import mode_project as MP
from pinball_decryptor.webui import modes_how as MH
from pinball_decryptor.webui.tabs import modes as MT

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
SDK = os.path.join(ROOT, "tools", "spike2_emu", "modes", "sdk")
LE = MP.profile_from_port(os.path.join(SDK, "ports", "godzilla_le-1.16.port"))


def _tool(*parts):
    path = os.path.join(ROOT, "tools", "spike2_emu", "modes", *parts)
    spec = importlib.util.spec_from_file_location(os.path.basename(path)[:-3], path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clips(sh, labels):
    return CM.CardClips(card="card", game="godzilla_le", version="1.16.0", reading=CM.Reading(labels=labels),
                        shows=sh.to_json())


SH1 = SH.ShowReading(origin="port", count=361, modes={"cmode_hedorah": [[211, 16, 1], [210, 20, 1]]},
                     names={"148": "Strobe burst"}, own={"210": "cmode_hedorah", "211": "cmode_hedorah",
                                                         "212": "cmode_hedorah", "300": "cmode_gigan"})
LABELS = {"cmode_hedorah": "Hedorah", "cmode_gigan": "Battle vs Gigan"}


def test_a_modes_own_shows_are_its_bodies_it_starts_by_no_fixed_number():
    assert SH1.own_shows("cmode_hedorah") == [212]           # 210 and 211 are started by a fixed number
    assert SH1.own_shows("cmode_gigan") == [300]
    back = SH.ShowReading.from_json(json.loads(json.dumps(SH1.to_json())))
    assert back.own == SH1.own and back.own_shows("cmode_hedorah") == [212]
    assert SH.ShowReading.from_json({}).own == {}             # a reading cached before it
    assert SH.READ_REV >= 2                                   # so a card read before is read again


def test_the_reel_says_which_numbers_it_played():
    assert MP.parse_numbers("1-3 7, 9-9 x 5-") == {1, 2, 3, 7, 9}
    port = MP.read_port(os.path.join(SDK, "ports", "godzilla_pro-1.15.port"))
    port["text"].pop("show_reeled", None)
    assert MP._show_reeled(port) is None
    port["text"]["show_reeled"] = "1-4 10"
    assert MP._show_reeled(port) == (1, 2, 3, 4, 10)
    # what a show's number is to the app: lit, played and dark, or not played
    full = dataclasses.replace(LE, show_lit=(210, 300), show_reeled=tuple(range(1, 361)))
    assert [MP.show_checked(full, n) for n in (210, 211, 300)] == ["lit", "dark", "lit"]
    first = dataclasses.replace(LE, show_lit=(210,), show_reeled=None)     # the first reels: the modes' shows only
    assert [MP.show_checked(first, n, {210, 211}) for n in (210, 211, 212)] == ["lit", "dark", ""]
    assert MP.show_checked(dataclasses.replace(LE, show_lit=None), 210, {210}) == ""


def test_the_picks_have_each_modes_own_shows_and_the_others_seen_lighting():
    tab = SimpleNamespace(_how=_clips(SH1, LABELS), _title=lambda: dataclasses.replace(
        LE, show_lit=(148, 210, 212), show_reeled=tuple(range(1, 361))))
    rows = MT.ModesTab._mode_show_rows(tab)
    assert [(r["group"], r["value"], r["label"], r["checked"]) for r in rows] == [
        ("Hedorah", "#210", "Light show 210 (Hedorah)", True),
        ("Hedorah", "#212", "Light show 212 (Hedorah)", True),         # its own, picked as it plays
        (MT.OTHER_SHOWS, "#148", "Strobe burst (148)", True)]          # 211 and 300 lit nothing; 148 is no mode's
    # the first reels played only the modes' shows: a mode's own other show is listed, not checked
    tab = SimpleNamespace(_how=_clips(SH1, LABELS), _title=lambda: dataclasses.replace(LE, show_lit=(210,)))
    rows = MT.ModesTab._mode_show_rows(tab)
    assert [(r["value"], r["checked"]) for r in rows] == [("#300", False), ("#210", True), ("#212", False)]
    assert rows[0]["group"] == "Battle vs Gigan"


def test_by_its_number_knows_every_numbers_name_and_what_the_reel_saw():
    tab = SimpleNamespace(_how=_clips(SH1, LABELS), _title=lambda: dataclasses.replace(
        LE, show_lit=(210,), show_reeled=(210, 211)))
    pick = MT.ModesTab._show_pick(tab)
    assert pick["max"] == LE.show_numbers - 1
    assert pick["names"] == {"148": "Strobe burst", "210": "Hedorah's show", "211": "Hedorah's show",
                             "212": "Hedorah's show", "300": "Battle vs Gigan's show"}
    LABELS2 = dict(LABELS, cmode_gigan="Super Spinners")                    # a name ending in s
    tab2 = SimpleNamespace(_how=_clips(SH1, LABELS2), _title=tab._title)
    assert MT.ModesTab._show_pick(tab2)["names"]["300"] == "Super Spinners' show"
    assert pick["seen"] == {"210": "lit", "211": "dark"}
    # no card read yet: the numbers still, nothing known of them; a build that cannot play one by its number: {}
    assert MT.ModesTab._show_pick(SimpleNamespace(_how=None, _title=lambda: LE)) == {
        "max": LE.show_numbers - 1, "names": {}, "seen": {}}
    assert MT.ModesTab._show_pick(SimpleNamespace(_how=None, _title=lambda: dataclasses.replace(
        LE, show_numbers=0))) == {}


def test_how_it_works_lists_the_shows_a_mode_picks_as_it_plays():
    row = MH.HowItWorksMixin._how_show(SH1, 212, 0, "lit", "Hedorah")
    assert row["tip"]["lines"][:2] == ["The game's light show 212",
                                       "This mode's own show: its code picks it as it plays (a number it works out)"]
    assert "worked" not in MH.HowItWorksMixin._how_show(SH1, 210, 1, "lit", "Hedorah")["tip"]["lines"][1]
    # unplayed by the reel is not "lights only while this mode runs"
    assert "only while" not in " ".join(MH.HowItWorksMixin._how_show(SH1, 212, 0, "", "Hedorah")["tip"]["lines"])
    assert "only while" in " ".join(MH.HowItWorksMixin._how_show(SH1, 211, 1, "dark", "Hedorah")["tip"]["lines"])


def test_the_reel_lists_every_number_and_the_verdict_writes_what_it_played(tmp_path, monkeypatch):
    rv = _tool("show_reel", "reel_verdict.py")
    assert rv.ranges([5, 1, 2, 3, 9, 10]) == "1-3 5 9-10"
    psn = _tool("port_show_numbers.py")
    shutil.copy(os.path.join(SDK, "ports", "godzilla_pro-1.16.port"), str(tmp_path / "x-1.0.port"))
    monkeypatch.setattr(psn, "PORTS", str(tmp_path))
    psn.lit_main(["", "lit", "x-1.0", "--reeled", "1-360", "263", "210"])
    psn.lit_main(["", "lit", "x-1.0", "--reeled", "1-360", "210"])          # replaced, not added
    text = (tmp_path / "x-1.0.port").read_text(encoding="utf-8")
    assert text.count("text show_reeled") == 1 and text.count("text show_lit") == 1
    port = MP.read_port(str(tmp_path / "x-1.0.port"))
    assert MP._show_lit(port) == (210,) and MP._show_reeled(port) == tuple(range(1, 361))
    psn.lit_main(["", "lit", "x-1.0", "210"])                                # an old-style verdict: no reeled line
    assert "show_reeled" not in (tmp_path / "x-1.0.port").read_text(encoding="utf-8")


def test_every_picker_offers_another_by_its_number():
    js = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")
    shownum = open(os.path.join(js, "modes_shownum.js"), encoding="utf-8").read()
    assert "Another, by its number…" in shownum and "export function useShowNumber" in shownum
    for name, used in (("modes.js", "ShowSelect"), ("modes_blocks.js", "GameShowPick"),
                       ("modes_dialogs.js", "IntroShowPick")):
        src = open(os.path.join(js, name), encoding="utf-8").read()
        assert 'from "./modes_shownum.js"' in src and "useShowNumber(" in src and used in src, name


BOND_LE = r"C:\tmp\PAD-1446\gr\james_bond_le-1_06_0.elf"


@pytest.mark.skipif(not os.path.isfile(BOND_LE), reason="James Bond LE 1.06's game program is not on this PC")
def test_bond_le_names_its_modes_own_shows():
    ctx = {}
    with open(BOND_LE, "rb") as f:
        CM.analyse(f.read(), set(), ctx=ctx)
    r = SH.analyse(game="james_bond_le", version="1.06", ctx=ctx)
    assert len(r.own) == 246 and len(set(r.own.values())) == 40
    # a show a mode starts by a fixed number has its body in that same mode's code: all but Wizard Mode Multiball's
    # 151, Super Spinners' own show
    fixed = [(m, n) for m, rows in r.modes.items() for n, _a, _c in rows if str(n) in r.own]
    assert len(fixed) == 128
    assert [(m, n, r.own[str(n)]) for m, n in fixed if r.own[str(n)] != m] == [
        ("WIZARD_MODE_MULTIBALL", 151, "SUPER_SPINNERS")]
    assert r.own_shows("DISCO_VOLANTE_MULTIBALL") == [271, 273, 274, 275, 281, 284, 286]
    assert len(r.names) >= 23                                   # the port's, over the whole table now


def test_a_show_that_stops_the_game_is_never_offered_nor_played():
    from pinball_decryptor.plugins.stern import block_modes as BM
    bond = MP.profile_from_port(os.path.join(SDK, "ports", "james_bond_le-1.06.port"))
    assert bond.show_hangs == (12, 19)
    assert MP.profile_from_port(os.path.join(SDK, "ports", "batman-1.14.port")).show_hangs == (293,)
    assert MP.show_checked(bond, 12) == "hangs"
    assert not MP.game_show_ok(bond, "#12") and MP.game_show_ok(bond, "#13")
    # the block's check and the Lights page's both refuse it
    prog = {"scripts": [{"hat": {"kind": "mode_start"}, "do": [{"op": "game_show", "name": "#12"}]}]}
    said = [w for w in BM.problems(prog, **BM.card_checks(bond)) if "light show 12" in w]
    assert said and "stops the game" in said[0]
    spec = SimpleNamespace(show_start="#12", show_end="", show_hit="")
    assert any("stops the game" in w for w in MP.validate_shows(spec, bond))
    # the How it works row says so, and the runtime refuses it whatever asks
    sh = SH.ShowReading(names={})
    assert "stops the game" in MH.HowItWorksMixin._how_show(sh, 12, 1, "hangs", "Bust Out")["tip"]["lines"][1]
    src = open(os.path.join(SDK, "pad_mode_runtime.c"), encoding="utf-8").read()
    assert 'pm_port_text("show_hangs")' in src and "if (show_hangs(num))" in src


def test_a_show_over_a_busy_playfield_is_not_called_dark(tmp_path):
    rv = _tool("show_reel", "reel_verdict.py")
    rows = []
    for t in range(0, 20000, 100):                      # quiet until 10 s, then the game's own show: ~1800 a second
        rows.append("%d %d %d" % (t, 80 if t < 10000 else 180, 90 if t < 10000 else 170))
    rows += ["5000 LOG show reel: #7 on", "15000 LOG show reel: #8 on"]
    (tmp_path / "led.txt").write_text("\n".join(sorted(rows, key=lambda r: int(r.split()[0]))) + "\n")
    got = {n: v for n, v, *_r in rv.verdict(str(tmp_path))}
    assert got == {7: "dark", 8: "busy"}


def test_bond_le_was_reeled_whole():
    bond = MP.profile_from_port(os.path.join(SDK, "ports", "james_bond_le-1.06.port"))
    assert len(bond.show_lit) >= 150 and 12 not in bond.show_reeled and 19 not in bond.show_reeled
    assert set(bond.show_lit) <= set(bond.show_reeled) and max(bond.show_reeled) <= bond.show_numbers - 1
