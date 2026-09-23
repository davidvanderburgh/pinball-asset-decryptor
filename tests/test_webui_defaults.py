"""The web Defaults tab (Tk "Default Settings"): webui/tabs/defaults.py.

Mirrors the Tk guards in tests/test_gui_settings_form.py and
tests/test_gui_settings_all_list.py against the web service, plus the
state the page renders, the page's calls, and the attributes the run logic
(app.App._apply_staged_settings_to_build) reads off the window.
"""

import json
import os

import pytest

from tests.webui_harness import web_app

MOD = "pinball_decryptor.webui.tabs.defaults"


def _row(name, label, group, default, lo, hi, kind="number", status="",
         labels=None, scale=1, step=1):
    return {"name": name, "label": label, "kind": kind, "help": "",
            "scale": scale, "labels": labels, "group": group,
            "status": status, "default": default, "min": lo, "max": hi,
            "step": step}


# One in-range toggle, an enum, a service-menu number, one champion score
# with no name record, one whose shipped default is below its own minimum
# (the Led Zeppelin shape) and one score that belongs to a board slot.
ROWS = [
    _row("AD_FREE_PLAY", "Free Play", "Game", 0, 0, 1, kind="toggle"),
    _row("AD_LANGUAGE", "Language", "Game", 0, 0, 2, kind="enum",
         labels={0: "English", 1: "German", 2: "French"}),
    _row("AD_SOUND_MASTER_VOLUME_SETTING", "Master Volume", "Sound",
         30, 0, 63, status="service"),
    _row("AD_BLACK_DOG_CHAMPION", "Black Dog Champion", "High scores",
         10_000_000, 5_000_000, 1_000_000_000, step=1_000_000),
    _row("AD_ELECTRIC_MAGIC_FRENZY_CHAMPION",
         "Electric Magic Frenzy Champion", "High scores",
         2_000_000, 5_000_000, 1_000_000_000, step=1_000_000),
    _row("AD_GRAND_CHAMPION_SCORE", "Grand Champion Score", "High scores",
         75_000_000, 5_000_000, 1_000_000_000, step=1_000_000),
]


def _all(label, status, default=0, lo=0, hi=1, adj_id=1, labels=None):
    return {"id": adj_id, "name": "AD_" + label.replace(" ", "_"),
            "label": label, "default": default, "min": lo, "max": hi,
            "step": 1, "labels": labels, "status": status}


EVERY = [
    _all("FREE PLAY", "", adj_id=0x54),
    _all("MASTER VOLUME SETTING", "service", 64, 0, 64, adj_id=0x10),
    _all("ALLOW TOPPER CHEATS", "debug", adj_id=0xD4),
    _all("THIS IS THE WAY DEBUG", "debug", 3, 0, 9, adj_id=0xD3),
    _all("COIL PULSE TEST CHANGED", "debug", adj_id=0xD5),
]

PLAN = {"first": 0x7F, "last": 0xD2, "call": 0, "off": 0, "form": "mov",
        "candidates": [
            {"id": 0xD3, "name": "AD_THIS_IS_THE_WAY_DEBUG"},
            {"id": 0xD4, "name": "AD_ALLOW_TOPPER_CHEATS"},
            {"id": 0xD5, "name": "AD_COIL_PULSE_TEST_CHANGED"}]}


class _Hstd:
    def __init__(self):
        self.rows = [
            {"index": 0, "offset": 0, "label": " GRAND CHAMPION ",
             "display": "GRAND CHAMPION",
             "adjustment": "AD_GRAND_CHAMPION_SCORE",
             "initials": "ZEP", "name": "ROBERT",
             "initials_max": 3, "name_max": 8},
            {"index": 1, "offset": 8, "label": " HIGH SCORE #1 ",
             "display": "HIGH SCORE #1", "adjustment": None,
             "initials": "JPP", "name": "JIMMY",
             "initials_max": 3, "name_max": 0},
        ]


def _svc(w):
    return w.window.service("defaults")


def _load(w, rows=ROWS, every=EVERY, plan=PLAN, hstd="default",
          project=None):
    """A loaded-looking tab (a fake read result) whose staged changes land
    in *project*."""
    svc = _svc(w)
    if project is not None:
        w.run(lambda: w.window.write_assets_var.set(str(project)))
    hs = _Hstd() if hstd == "default" else hstd
    res = ("ok", object(), 3, "/game", list(rows), "C:/card.raw", hs,
           list(every), plan)
    w.run(lambda: svc._apply_result(res))
    return svc


def _staged(folder):
    p = os.path.join(str(folder), ".staged_changes.json")
    if not os.path.isfile(p):
        return {}
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _lines(svc, monkeypatch):
    out = []
    monkeypatch.setattr(svc, "log",
                        lambda text, level="info": out.append(text))
    return out


def _stage_now(w):
    """What a field losing focus does: the page's defaults.commit."""
    w.call("defaults.commit")


# ------------------------------------------------------ manufacturers
@pytest.mark.parametrize("era,visible", [("spike2", True), ("spike1", True),
                                         ("whitestar", False)])
def test_tab_follows_the_settings_editor_capability(tmp_path, era, visible):
    with web_app(tmp_path, mfr="stern", era=era) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["defaults"]["visible"] is visible
        st = w.state("defaults")
        assert st["phase"] == "empty"
        assert st["message"] == ("Set the card image on the Extract tab to "
                                 "edit its default settings.")
        assert st["reset_enabled"] is False
        assert st["era"] == era


@pytest.mark.parametrize("mfr", ["jjp", "spooky", "cgc", "williams"])
def test_other_makers_have_no_defaults_tab_but_answer_the_run_logic(
        tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["defaults"]["visible"] is False
        for name in ("staged_default_settings", "staged_high_scores",
                     "staged_menu_expose"):
            assert callable(getattr(w.window, name))


def test_every_export_the_run_logic_reads_is_ours(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        for name in svc.exports:
            assert w.window._exports[name] is svc
        assert w.window.staged_default_settings(str(tmp_path)) == {}
        assert w.window.staged_high_scores(str(tmp_path)) == {}
        assert w.window.staged_menu_expose(str(tmp_path)) == ""
        assert w.window.staged_default_settings("") == {}


def test_run_logic_reads_what_the_tab_staged(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(proj), {
        "settings": {"AD_FREE_PLAY": 1, "AD_BAD": "x"},
        "high_scores": {" GRAND CHAMPION ": {"initials": "ABC", "junk": 1}},
        "menu_expose_through": "AD_ALLOW_TOPPER_CHEATS"})
    with web_app(tmp_path, mfr="stern") as w:
        assert w.window.staged_default_settings(str(proj)) == {
            "AD_FREE_PLAY": 1}
        assert w.window.staged_high_scores(str(proj)) == {
            " GRAND CHAMPION ": {"initials": "ABC"}}
        assert w.window.staged_menu_expose(str(proj)) == \
            "AD_ALLOW_TOPPER_CHEATS"


# ------------------------------------------------------------- the form
def test_the_form_state_the_page_renders(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _load(w)
        st = w.state("defaults")
        assert st["phase"] == "ready" and st["loaded"] and st["reset_enabled"]
        form = st["form"]
        groups = [f["label"] for f in form if f["type"] == "group"]
        assert groups == ["Game", "Sound"]
        rows = {f["name"]: f for f in form if f["type"] == "row"}
        # Score adjustments leave the settings grid for High Scores.
        assert set(rows) == {"AD_FREE_PLAY", "AD_LANGUAGE",
                             "AD_SOUND_MASTER_VOLUME_SETTING"}
        assert rows["AD_FREE_PLAY"]["ui"] == "toggle"
        assert rows["AD_FREE_PLAY"]["range"] == "off / on"
        assert rows["AD_FREE_PLAY"]["on_card"] == "Off"
        assert rows["AD_LANGUAGE"]["ui"] == "enum"
        assert rows["AD_LANGUAGE"]["range"] == "3 options"
        assert rows["AD_LANGUAGE"]["options"][1] == {"value": 1,
                                                     "label": "1 - German"}
        assert rows["AD_LANGUAGE"]["on_card"] == "0 - English"
        vol = rows["AD_SOUND_MASTER_VOLUME_SETTING"]
        assert vol["ui"] == "number" and vol["range"] == "0 - 63"
        assert "different service screen" in vol["help"]
        # High Scores: the named slot with its score, the name-less slot,
        # and the two champions with no record as score-only lines.
        hs = st["hs"]
        assert [h["type"] for h in hs] == ["slot", "slot", "score", "score"]
        assert hs[0]["score"]["name"] == "AD_GRAND_CHAMPION_SCORE"
        assert hs[0]["score"]["on_card"] == "75,000,000"
        assert hs[1]["score"] is None and hs[1]["name_max"] == 0
        emf = next(h for h in hs if h["type"] == "score"
                   and h["display"].startswith("Electric"))
        assert emf["score"]["range"] == (
            "5,000,000 - 1,000,000,000  (card ships 2,000,000, outside its "
            "own range)")
        assert emf["score"]["lo"] == 2_000_000
        assert st["hs_values"][0] == {"initials": "ZEP", "name": "ROBERT"}
        assert st["values"]["AD_FREE_PLAY"] == 0


def test_a_default_outside_its_own_range_is_not_an_edit(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        assert w.run(svc._changes) == {}
        _stage_now(w)
        assert _staged(proj) == {}


def test_editing_a_field_stages_it_and_logs_both_values(tmp_path,
                                                       monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        lines = _lines(svc, monkeypatch)
        # the page's edit channel: ui.set defaults "val:<name>"
        w.call("ui.set", "defaults", "val:AD_SOUND_MASTER_VOLUME_SETTING",
               "24")
        assert w.state("defaults")["values"][
            "AD_SOUND_MASTER_VOLUME_SETTING"] == 24
        _stage_now(w)
        assert _staged(proj)["settings"] == {
            "AD_SOUND_MASTER_VOLUME_SETTING": 24}
        assert lines == ["Defaults: Master Volume 30 → 24 staged for the "
                         "next Build (card has 30)."]
        assert "1 change(s) staged" in w.state("defaults")["status"]
        # back to the card value un-stages it and says so
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", 30)
        _stage_now(w)
        assert "settings" not in _staged(proj)
        assert lines[-1] == ("Defaults: Master Volume back to the card's 30 "
                             "— no longer staged.")
        # nothing moved: nothing said
        n = len(lines)
        _stage_now(w)
        assert len(lines) == n


def test_out_of_range_row_edits_and_clamps_into_range(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        w.call("defaults.set_value", "AD_ELECTRIC_MAGIC_FRENZY_CHAMPION",
               3_000_000)
        _stage_now(w)
        assert _staged(proj)["settings"] == {
            "AD_ELECTRIC_MAGIC_FRENZY_CHAMPION": 5_000_000}


def test_toggle_enum_and_invalid_text(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        w.call("defaults.set_value", "AD_FREE_PLAY", True)
        w.call("defaults.set_value", "AD_LANGUAGE", "2")
        w.call("defaults.set_value", "AD_SOUND_MASTER_VOLUME_SETTING", "2x")
        assert w.state("defaults")["values"][
            "AD_SOUND_MASTER_VOLUME_SETTING"] is None
        assert w.run(svc._changes) == {"AD_FREE_PLAY": 1, "AD_LANGUAGE": 2}


def test_the_autostage_timer_stages_on_its_own(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        import time
        deadline = time.time() + 5
        while time.time() < deadline and not _staged(proj):
            time.sleep(0.05)
        assert _staged(proj)["settings"] == {"AD_FREE_PLAY": 1}


def test_no_project_folder_stages_nothing_and_says_why(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w)
        w.run(lambda: w.window.write_assets_var.set(""))
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        _stage_now(w)
        assert "project folder" in w.state("defaults")["status"]
        assert w.run(lambda: svc._stage_menu_expose("AD_X")) is False


def test_high_score_text_is_capped_and_staged(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        lines = _lines(svc, monkeypatch)
        w.call("ui.set", "defaults", "hs:0:initials", "ABCDE")
        w.call("ui.set", "defaults", "hs:0:name", "JOHNPAULJONES")
        # a slot with no room for a name takes none
        assert w.call("defaults.set_hs_text", 1, "name", "X") is False
        st = w.state("defaults")
        assert st["hs_values"][0] == {"initials": "ABC", "name": "JOHNPAUL"}
        _stage_now(w)
        assert _staged(proj)["high_scores"] == {
            " GRAND CHAMPION ": {"initials": "ABC", "name": "JOHNPAUL"}}
        assert any('initials "ZEP" → "ABC"' in ln for ln in lines), lines


def test_staged_values_come_back_when_the_card_is_reloaded(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    from pinball_decryptor.core import staged_changes
    staged_changes.save(str(proj), {
        "settings": {"AD_FREE_PLAY": 1, "AD_ALLOW_TOPPER_CHEATS": 1},
        "high_scores": {" GRAND CHAMPION ": {"initials": "ABC"}},
        "menu_expose_through": "AD_ALLOW_TOPPER_CHEATS"})
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        st = w.state("defaults")
        assert st["values"]["AD_FREE_PLAY"] == 1
        # a setting the curated form doesn't draw gets its row back
        assert st["values"]["AD_ALLOW_TOPPER_CHEATS"] == 1
        allrow = next(r for r in st["all"]
                      if r["name"] == "AD_ALLOW_TOPPER_CHEATS")
        assert (allrow["value"], allrow["new"]) == ("Off", "On")
        assert st["hs_values"][0]["initials"] == "ABC"
        assert st["status"] == (
            "2 setting(s) staged for the next Build; the machine's menu will "
            "be opened up to \"ALLOW TOPPER CHEATS\".")
        # adopting the staged state writes nothing
        before = _staged(proj)
        _stage_now(w)
        assert _staged(proj) == before


def test_reset_fields_clears_everything_staged(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        lines = _lines(svc, monkeypatch)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        w.call("defaults.set_hs_text", 0, "initials", "XYZ")
        _stage_now(w)
        assert w.call("defaults.menu_apply", "AD_ALLOW_TOPPER_CHEATS")
        w.call("defaults.reset")
        assert _staged(proj) == {}
        st = w.state("defaults")
        assert st["values"]["AD_FREE_PLAY"] == 0
        assert st["hs_values"][0]["initials"] == "ZEP"
        assert st["status"] == (
            "Fields reset to the image's current defaults — cleared 2 staged "
            "setting(s) and the menu widening.")
        assert lines[-1] == ("Defaults: cleared 2 staged setting(s) and the "
                             "menu widening.")


def test_error_and_empty_curated_states(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w)
        w.run(lambda: svc._apply_result(("err", ValueError("bad table"))))
        st = w.state("defaults")
        assert st["phase"] == "error"
        assert st["message"].startswith(
            "Couldn't read settings from this image:\nbad table")
        _load(w, rows=[])
        st = w.state("defaults")
        assert st["phase"] == "ready" and st["form"] == []
        assert st["message"].startswith("None of the settings with friendly")
        assert len(st["all"]) == len(EVERY)


def test_on_show_reads_the_extract_tabs_card(tmp_path, monkeypatch):
    card = tmp_path / "card.raw"
    card.write_bytes(b"x")
    seen = []

    def fake_read(path):
        seen.append(path)
        return ("ok", object(), 3, "/game", list(ROWS), path, None,
                list(EVERY), None)

    monkeypatch.setattr(MOD + ".read_image", fake_read)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.set", "extract", "input", str(card))
        w.call("ui.select_tab", "defaults")
        import time
        deadline = time.time() + 5
        while time.time() < deadline and \
                w.state("defaults").get("phase") != "ready":
            time.sleep(0.05)
        st = w.state("defaults")
        assert st["phase"] == "ready"
        assert st["image"] == os.path.normpath(str(card))
        assert seen == [os.path.normpath(str(card))]
        assert st["menu_enabled"] is False
        # a second visit with the same card does not read it again
        w.call("ui.select_tab", "extract")
        w.call("ui.select_tab", "defaults")
        w.drain()
        assert len(seen) == 1


# ------------------------------------------------------- all settings
def test_all_list_rows_legend_filter_and_sort(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _load(w)
        st = w.state("defaults")
        caps = [r["caption"] for r in st["all"]]
        assert caps[0] == "FREE PLAY  (0x54)"
        assert [r["menu"] for r in st["all"]][:3] == [
            "Adjustments", "Service menu", "Debug"]
        assert st["all_legend"].startswith("5 setting(s) — double-click")
        assert "\"Service menu\" = 1 edited" in st["all_legend"]
        assert "\"Debug\" = 3 the machine never shows" in st["all_legend"]
        w.call("ui.set", "defaults", "hidden_only", True)
        st = w.state("defaults")
        assert all(r["menu"] != "Adjustments" for r in st["all"])
        assert "5 setting(s), 4 listed" in st["all_legend"]
        w.call("ui.set", "defaults", "hidden_only", False)
        # On card opens descending; a second click flips; a third goes back
        w.call("defaults.sort_all", "value")
        st = w.state("defaults")
        assert st["sort"] == {"key": "value", "desc": True}
        assert st["all"][0]["name"] == "AD_MASTER_VOLUME_SETTING"
        w.call("defaults.sort_all", "value")
        assert w.state("defaults")["sort"] == {"key": "value", "desc": False}
        w.call("defaults.sort_all", "value")
        st = w.state("defaults")
        assert st["sort"] == {"key": None, "desc": False}
        assert st["all"][0]["name"] == "AD_FREE_PLAY"


def test_unreadable_menu_flags_nothing_and_says_so(tmp_path):
    rows = [dict(r, status=None) for r in EVERY]
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, every=rows)
        st = w.state("defaults")
        assert all(r["menu"] == "" for r in st["all"])
        assert "operator menu couldn't be read" in st["all_legend"]


def test_editing_a_hidden_setting_through_the_editor(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        lines = _lines(svc, monkeypatch)
        info = w.call("defaults.edit_info", "AD_THIS_IS_THE_WAY_DEBUG")
        assert info["caption"] == "THIS IS THE WAY DEBUG  (0xD3)"
        assert info["on_card"] == "On card: 3        0 - 9"
        assert info["ui"] == "number" and info["cur"] == 3
        assert "never show this one" in info["note"]
        assert w.call("defaults.edit_info", "AD_ALLOW_TOPPER_CHEATS")[
            "ui"] == "toggle"
        # OK with a value past the range is pulled into it
        assert w.call("defaults.edit_apply", "AD_THIS_IS_THE_WAY_DEBUG", 12)
        assert _staged(proj)["settings"] == {"AD_THIS_IS_THE_WAY_DEBUG": 9}
        row = next(r for r in w.state("defaults")["all"]
                   if r["name"] == "AD_THIS_IS_THE_WAY_DEBUG")
        assert (row["value"], row["new"]) == ("3", "9")
        assert any("THIS IS THE WAY DEBUG" in ln and "staged" in ln
                   for ln in lines), lines
        # a non-number is refused and changes nothing
        assert w.call("defaults.edit_apply", "AD_THIS_IS_THE_WAY_DEBUG",
                      "abc") is False
        # the editor opens on the pending value next time
        assert w.call("defaults.edit_info",
                      "AD_THIS_IS_THE_WAY_DEBUG")["cur"] == 9
        # Back to card value un-stages it
        assert w.call("defaults.edit_apply", "AD_THIS_IS_THE_WAY_DEBUG",
                      None, True)
        assert "settings" not in _staged(proj)


def test_spike1_card_gets_the_list_only_and_stages_by_synthetic_name(
        tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    rows = [{"id": 7, "name": "AD_7", "label": "Balls Per Game",
             "default": 3, "min": 1, "max": 10, "step": 1, "labels": None,
             "status": None}]
    with web_app(tmp_path, mfr="stern", era="spike1") as w:
        svc = _svc(w)
        w.run(lambda: w.window.write_assets_var.set(str(proj)))
        w.run(lambda: svc._apply_result(("ok_spike1", rows, "C:/s1.iso")))
        st = w.state("defaults")
        assert st["spike1"] and st["form"] == [] and st["hs"] == []
        assert st["menu_enabled"] is False
        assert w.call("defaults.edit_apply", "AD_7", 5)
        assert _staged(proj)["settings"] == {"AD_7": 5}


# ------------------------------------------------------------ the menu
def test_menu_widening_dialog_stages_by_name(tmp_path, monkeypatch):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, project=proj)
        lines = _lines(svc, monkeypatch)
        assert w.state("defaults")["menu_enabled"] is True
        info = w.call("defaults.menu_info")
        assert info["text"].startswith(
            "The machine's Feature Adjustments page stops at setting 0xD2")
        assert info["caveat"].startswith("This edits the game's code")
        # opens on the last entry that isn't a "…_CHANGED" flag
        assert info["pre"] == "AD_ALLOW_TOPPER_CHEATS"
        assert [i["n"] for i in info["items"]] == [1, 2, 3]
        assert info["items"][0]["id"] == "0xD3"
        assert w.call("defaults.menu_apply", "AD_THIS_IS_THE_WAY_DEBUG")
        assert _staged(proj)["menu_expose_through"] == \
            "AD_THIS_IS_THE_WAY_DEBUG"
        assert lines[-1] == (
            "Defaults: the machine's Adjustments menu will show 1 hidden "
            "setting(s), through \"THIS IS THE WAY DEBUG\" — staged for the "
            "next Build.")
        assert w.state("defaults")["status"] == (
            "The machine's menu will be opened up to \"THIS IS THE WAY "
            "DEBUG\" on the next Build.")
        assert w.call("defaults.menu_info")["pre"] == \
            "AD_THIS_IS_THE_WAY_DEBUG"
        w.call("defaults.menu_clear")
        assert "menu_expose_through" not in _staged(proj)
        assert lines[-1] == ("Defaults: the machine's menu will be left as "
                             "the game ships it.")


def test_no_plan_means_no_menu_dialog(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, plan=None)
        assert w.state("defaults")["menu_enabled"] is False
        assert w.call("defaults.menu_info") is None


# ------------------------------------------------------------ presets
def test_presets_save_load_auto_apply_and_delete(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        # nothing loaded: Save As… says so and asks for no name
        assert w.call("defaults.save_preset") == {"ok": False}
        assert w.asked[-1]["title"] == "Save preset"
        assert w.asked[-1]["message"].startswith("Load a card image first")
        assert len(w.asked) == 1
        _load(w, project=proj)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        w.call("defaults.set_value", "AD_BLACK_DOG_CHAMPION", 20_000_000)
        # one step, as Tk's _ask_text: the framework's text prompt
        w.answers.append("  My route ")
        r = w.call("defaults.save_preset")
        assert w.asked[-1]["kind"] == "prompt"
        assert w.asked[-1]["input"] == "str"
        assert w.asked[-1]["title"] == "Save preset"
        assert w.asked[-1]["message"] == ("Name this preset (e.g. \"My "
                                          "route\"):")
        assert r == {"ok": True, "name": "My route"}
        st = w.state("defaults")
        assert st["presets"] == ["My route"] and st["preset"] == "My route"
        assert st["auto_enabled"] is True and st["autoapply"] is False
        assert st["status"] == "Saved preset \"My route\" (6 settings)."
        blob = w.app._settings["default_settings_presets"]
        assert blob["presets"]["My route"]["AD_FREE_PLAY"] == 1
        assert blob["presets"]["My route"]["AD_BLACK_DOG_CHAMPION"] == \
            20_000_000
        # auto-apply marks the selected preset active (read at build time)
        assert w.call("defaults.toggle_auto", True)
        assert blob["active"] == "My route"
        assert w.state("defaults")["status"] == (
            "\"My route\" will be applied to every card you build.")
        # Reset, then pick the preset: its values come back
        w.call("defaults.reset")
        assert w.state("defaults")["values"]["AD_FREE_PLAY"] == 0
        w.call("defaults.pick_preset", "My route")
        assert w.state("defaults")["values"]["AD_FREE_PLAY"] == 1
        assert w.state("defaults")["status"] == "Loaded preset \"My route\"."
        # delete asks first; No keeps it
        w.answers.append("no")
        assert w.call("defaults.delete_preset") is False
        w.answers.append("yes")
        assert w.call("defaults.delete_preset") is True
        assert w.asked[-1]["message"] == "Delete preset \"My route\"?"
        st = w.state("defaults")
        assert st["presets"] == [] and st["preset"] == ""
        assert st["auto_enabled"] is False and st["autoapply"] is False
        assert blob["active"] is None


def test_auto_apply_without_a_preset_says_why(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("defaults.toggle_auto", True) is False
        assert w.asked[-1]["title"] == "Auto-apply"
        assert w.state("defaults")["autoapply"] is False


@pytest.mark.parametrize("answer", ["cancel", "", "   "])
def test_save_preset_cancelled_or_blank_saves_nothing(tmp_path, answer):
    with web_app(tmp_path, mfr="stern") as w:
        _load(w)
        w.answers.append(answer)
        assert w.call("defaults.save_preset") == {"ok": False}
        assert w.asked[-1]["kind"] == "prompt"
        st = w.state("defaults")
        assert st["presets"] == [] and st["preset"] == ""
        assert "default_settings_presets" not in w.app._settings or not \
            w.app._settings["default_settings_presets"].get("presets")


def test_a_blank_preset_pick_is_not_a_choice(tmp_path):
    """Tk's read-only combobox offered only the saved names.  A blank pick
    used to leave auto-apply ticked but greyed (so it could not be unticked)
    while the preset stayed active for every Build."""
    with web_app(tmp_path, mfr="stern") as w:
        _load(w)
        w.answers.append("P")
        w.call("defaults.save_preset")
        assert w.call("defaults.toggle_auto", True)
        before = w.state("defaults")["status"]
        assert w.call("defaults.pick_preset", "") is False
        assert w.call("defaults.pick_preset", None) is False
        st = w.state("defaults")
        assert st["preset"] == "P"
        assert st["autoapply"] is True and st["auto_enabled"] is True
        assert st["status"] == before
        # ...so the box can still be unticked, which clears the standing one
        assert w.call("defaults.toggle_auto", False)
        assert w.app._settings["default_settings_presets"]["active"] is None


def test_picking_the_selected_preset_again_reloads_it(tmp_path):
    """Tk's <<ComboboxSelected>> fired on every pick, the current one too:
    choosing the loaded preset again puts its values back over the edits."""
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        w.answers.append("P")
        w.call("defaults.save_preset")
        w.call("defaults.set_value", "AD_FREE_PLAY", 0)
        w.call("defaults.set_value", "AD_LANGUAGE", 2)
        assert w.state("defaults")["preset"] == "P"
        assert w.call("defaults.pick_preset", "P") is True
        st = w.state("defaults")
        assert st["values"]["AD_FREE_PLAY"] == 1
        assert st["values"]["AD_LANGUAGE"] == 0
        assert st["status"] == "Loaded preset \"P\"."
        _stage_now(w)
        assert _staged(proj)["settings"] == {"AD_FREE_PLAY": 1}


# ------------------------------------------------- typed numbers (IntVar)
@pytest.mark.parametrize("text,want", [
    ("24", 24), (" 24 ", 24), ("7.5", 7), ("-7.9", -7), ("1e1", 10),
    ("2x", None), ("", None), ("nan", None), ("inf", None)])
def test_a_typed_number_reads_the_way_a_tk_intvar_did(tmp_path, text, want):
    """IntVar.get(): getint, else int(getdouble()) - "7.5" read as 7."""
    with web_app(tmp_path, mfr="stern") as w:
        _load(w)
        w.call("ui.set", "defaults", "val:AD_SOUND_MASTER_VOLUME_SETTING",
               text)
        assert w.state("defaults")["values"][
            "AD_SOUND_MASTER_VOLUME_SETTING"] == want


def test_the_editor_ok_truncates_a_decimal_like_tk(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        assert w.call("defaults.edit_apply", "AD_THIS_IS_THE_WAY_DEBUG",
                      "7.5") is True
        assert _staged(proj)["settings"] == {"AD_THIS_IS_THE_WAY_DEBUG": 7}
        # no number at all: refused (Tk's OK did nothing), nothing moves
        for bad in ("abc", "", "nan"):
            assert w.call("defaults.edit_apply", "AD_THIS_IS_THE_WAY_DEBUG",
                          bad) is False
        assert _staged(proj)["settings"] == {"AD_THIS_IS_THE_WAY_DEBUG": 7}


# ------------------------------------------------------------ the page
def test_the_page_uses_the_framework_not_local_workarounds():
    """The prompt dialog kind, Field's number / length props, the table's
    column resizing and app.css's row user-select replaced the page's own
    copies; the breakpoints are the zoom-aware classes, never @media."""
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[1] / "pinball_decryptor" \
        / "webui" / "static"
    js = (root / "js" / "tabs" / "defaults.js").read_text(encoding="utf-8")
    css = (root / "css" / "tabs" / "defaults.css").read_text(encoding="utf-8")
    assert "PresetModal" not in js and "function Input(" not in js
    assert 'kind: "preset"' not in js
    assert js.count("resizable") >= 2          # the list and the menu dialog
    assert "user-select" not in css
    assert "@media" not in css
    assert "html.bp-1020 .dflt .dflt-hs" in css


def test_the_active_preset_is_overlaid_on_load(tmp_path):
    settings = {"default_settings_presets": {
        "presets": {"Club": {"AD_FREE_PLAY": 1}}, "active": "Club"}}
    with web_app(tmp_path, mfr="stern", settings=settings) as w:
        _load(w)
        st = w.state("defaults")
        assert st["preset"] == "Club" and st["autoapply"] is True
        assert st["values"]["AD_FREE_PLAY"] == 1
        assert st["status"] == (
            "preset \"Club\" is baked into every card you Build.")


# ------------------------------------------------------ Modes tab hook
def test_modes_tab_staging_is_put_into_the_form(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        from pinball_decryptor.core import staged_changes
        staged_changes.save(str(proj), {"settings": {
            "AD_SOUND_MASTER_VOLUME_SETTING": 40,
            "AD_THIS_IS_THE_WAY_DEBUG": 5}})
        w.run(lambda: w.window._modes_settings_staged(
            "AD_SOUND_MASTER_VOLUME_SETTING"))
        w.run(lambda: w.window._modes_settings_staged(
            "AD_THIS_IS_THE_WAY_DEBUG"))
        st = w.state("defaults")
        assert st["values"]["AD_SOUND_MASTER_VOLUME_SETTING"] == 40
        assert st["values"]["AD_THIS_IS_THE_WAY_DEBUG"] == 5
        # ...so the next edit keeps them staged
        w.call("defaults.set_value", "AD_FREE_PLAY", 1)
        _stage_now(w)
        assert _staged(proj)["settings"] == {
            "AD_SOUND_MASTER_VOLUME_SETTING": 40,
            "AD_THIS_IS_THE_WAY_DEBUG": 5, "AD_FREE_PLAY": 1}


def test_mod_pack_import_reload_overlays_the_folder(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    with web_app(tmp_path, mfr="stern") as w:
        _load(w, project=proj)
        from pinball_decryptor.core import staged_changes
        staged_changes.save(str(proj), {"settings": {"AD_FREE_PLAY": 1}})
        w.run(w.window.reload_assets_tabs)
        assert w.state("defaults")["values"]["AD_FREE_PLAY"] == 1
