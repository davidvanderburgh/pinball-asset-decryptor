"""The Visual Pinball tab (PAD-802): the kit in the app, behind a preview code.

What is worth failing on:

  * THE GATE. The tab shows only with a preview code for "vpx", only on
    Windows, and only for a manufacturer the Spike 2 emulator runs; without a
    code nobody sees it.
  * THE KIT STAYS OUT OF PROCESS. The tab runs the kit's own scripts and reads
    the LAST JSON line they print; anything else (a traceback, nothing) is an
    error the page can show, never a crash.
  * PATCH WRITES INTO VISUAL PINBALL'S TABLES FOLDER, from the person's own
    download, and says so when the table is not one the kit knows.
  * THE PAD RUNTIME ROW INSTALLS IT (PAD-840). It sent people to the Emulate
    tab, which offers no install on a PC with a working Ubuntu.
"""
import json
import os
import sys
import threading
import time
import types

import pytest

from pinball_decryptor.core import preview
from pinball_decryptor.webui.tabs import vpx as V


class _Store:
    def __init__(self):
        self.d = {}

    def set(self, ns, **kw):
        self.d.setdefault(ns, {}).update(kw)

    def get(self, ns, k, default=None):
        return self.d.get(ns, {}).get(k, default)


class _Loop:
    def post(self, fn, *a):
        fn(*a)

    def call(self, fn, *a):
        return fn(*a)


class _Win:
    def __init__(self, pick=""):
        self.ctx = types.SimpleNamespace(store=_Store(), loop=_Loop())
        self.lines = []
        self.pick = pick

    def bind_var(self, *a):
        pass

    def append_log(self, text, level="info"):
        self.lines.append((level, text))

    def ask_open(self, *a, **k):
        return self.pick

    def ask_folder(self, *a, **k):
        return self.pick


def _wait(tab):
    deadline = time.time() + 10
    while (tab._busy or tab._extras_running) and time.time() < deadline:
        time.sleep(0.02)
    assert not tab._busy and not tab._extras_running


@pytest.fixture
def tab(monkeypatch, tmp_path):
    monkeypatch.setattr(V.sys, "platform", "win32")
    # PAD-942: the pictures' cache is a folder of this test's own, never the PC's
    monkeypatch.setenv("PAD_VPX_PICTURES", str(tmp_path / "pictures"))
    monkeypatch.setattr(V.os.path, "isfile", lambda p, _f=os.path.isfile: True if p.endswith("vpxsetup.py") else _f(p))
    calls = []
    state = {"registered": True, "vpx": r"C:\VP", "tables_dir": r"C:\VP\tables", "library": "",
             "cards": {}, "tables": [], "patched": [], "presets": [], "layout": ""}

    def kit(self, script, args, timeout=0, on_line=None):
        calls.append((script, list(args)))
        if args and args[0] == "state":
            return dict(state)
        return self.answers.get((script, args[0]), {"result": "ok", "_text": ""})
    monkeypatch.setattr(V.VpxTab, "_kit", kit)
    from pinball_decryptor.core import runtime
    monkeypatch.setattr(runtime, "status", lambda **k: ("ready", "Runtime 6."))
    V.VpxTab.answers = {}
    t = V.VpxTab(_Win())
    t.calls = calls
    return t


def test_the_preview_names_the_tab():
    assert preview.FEATURES.get("vpx") == "Visual Pinball"
    assert V.PREVIEW_FEATURE == "vpx"
    keys = [m[2] for m in __import__("pinball_decryptor.webui.tabs", fromlist=["TABS"]).TABS]
    assert "Visual Pinball" in keys


def test_the_tab_shows_only_with_a_code_on_windows(monkeypatch):
    from pinball_decryptor.webui import window as W
    caps = types.SimpleNamespace(emulate=True)
    mfr = types.SimpleNamespace(capabilities=caps)
    win = W.WebWindow.__new__(W.WebWindow) if hasattr(W, "WebWindow") else None
    if win is None:
        pytest.skip("no WebWindow class")
    monkeypatch.setattr(type(win), "modes_preview_on", lambda self, m=None: False)
    monkeypatch.setattr(W.sys, "platform", "win32")
    monkeypatch.setattr(preview, "_active", frozenset())
    assert win._gate(mfr)["Visual Pinball"] is False
    monkeypatch.setattr(preview, "_active", frozenset({"vpx"}))
    assert win._gate(mfr)["Visual Pinball"] is True
    # not for a manufacturer the Spike 2 emulator does not run
    assert win._gate(types.SimpleNamespace(capabilities=types.SimpleNamespace()))["Visual Pinball"] is False
    # Visual Pinball and the controller are Windows only
    monkeypatch.setattr(W.sys, "platform", "linux")
    assert win._gate(mfr)["Visual Pinball"] is False


def test_the_last_json_line_is_the_answer():
    assert V.last_json('say downloading\nprogress 0.5\n{"result": "ok"}\n') == {"result": "ok"}
    assert V.last_json("Traceback (most recent call last):\n  boom") is None
    assert V.last_json("") is None
    assert V.last_json("{not json") is None


def test_a_kit_that_prints_no_json_is_an_error_not_a_crash(monkeypatch, tmp_path):
    monkeypatch.setattr(V, "kit_python", lambda: sys.executable)
    monkeypatch.setattr(V, "kit_dir", lambda: str(tmp_path))
    (tmp_path / "broken.py").write_text("import sys\nprint('half a line')\nsys.exit(3)\n", encoding="utf-8")
    t = V.VpxTab.__new__(V.VpxTab)
    got = t._kit("broken.py", [])
    assert "exit 3" in got["error"] and "half a line" in got["error"]
    (tmp_path / "good.py").write_text("print('progress 0.1')\nprint('{\"result\": \"ok\"}')\n", encoding="utf-8")
    seen = []
    got = t._kit("good.py", [], on_line=seen.append)
    assert got["result"] == "ok" and seen == ["progress 0.1", '{"result": "ok"}']
    monkeypatch.setattr(V, "kit_python", lambda: None)
    assert "No Windows Python" in t._kit("good.py", [])["error"]


def test_showing_the_tab_reads_the_kit(tab):
    tab.on_show()
    _wait(tab)
    st = tab.window.ctx.store.d["vpx"]
    assert st["loaded"] and st["vpx"] == r"C:\VP" and st["registered"]
    assert ("vpxsetup.py", ["state"]) in tab.calls


def test_patch_writes_into_visual_pinballs_tables_folder(tab):
    tab.on_show()
    _wait(tab)
    tab.window.pick = r"D:\Downloads\Rush LE 2.0.2.vpx"
    tab.answers[("padvpx.py", "patch")] = {
        "_text": 'recognised rush_le: Rush LE ver DrHotWing\nopen "C:\\VP\\tables\\Rush LE 2.0.2 (PAD).vpx" in Visual Pinball'}
    assert tab.patch()
    _wait(tab)
    script, args = [c for c in tab.calls if c[0] == "padvpx.py"][-1]
    assert args == ["patch", os.path.normpath(r"D:\Downloads\Rush LE 2.0.2.vpx"), "--out", r"C:\VP\tables"]
    assert not [ln for ln in tab.window.lines if ln[0] == "error"]


def test_patch_says_when_the_table_is_not_one_the_kit_knows(tab):
    tab.on_show()
    _wait(tab)
    tab.window.pick = r"D:\Downloads\Some Other Table.vpx"
    tab.answers[("padvpx.py", "patch")] = {"_text": "this table is not one the kit knows; it can patch: rush_le"}
    assert tab.patch()
    _wait(tab)
    assert any("not one the app can patch" in t for _, t in tab.window.lines)


def test_nothing_runs_when_a_dialog_is_cancelled(tab):
    tab.window.pick = ""
    assert tab.patch() is False and tab.choose_vpx() is False and tab.choose_library() is False
    assert tab.download_vpx() is False
    assert not [c for c in tab.calls if c[1] and c[1][0] != "state"]


def test_play_refused_shows_as_a_warning_on_the_page(tab):
    """PAD-806: Play on a PC with no WSL comes back with the kit's reason; the
    page shows it as a warning, not the muted line an "opening..." gets."""
    tab.on_show()
    _wait(tab)
    tab.answers[("vpxsetup.py", "open")] = {"result": "The game cannot start: WSL is not installed on this PC yet."}
    assert tab.play("JP's Foo Fighters (PAD).vpx")
    _wait(tab)
    st = tab.window.ctx.store.d["vpx"]
    assert st["message"].startswith("The game cannot start") and st["message_level"] == "error"
    assert ("error", "Visual Pinball: " + st["message"]) in tab.window.lines
    tab.answers[("vpxsetup.py", "open")] = {"result": "ok"}
    assert tab.play("JP's Foo Fighters (PAD).vpx")
    _wait(tab)
    st = tab.window.ctx.store.d["vpx"]
    assert st["message"].startswith("opening") and st["message_level"] == "info"


def test_one_job_at_a_time(tab):
    tab._busy = True
    assert tab.refresh() is False and tab.play("x (PAD).vpx") is False
    tab._busy = False


def test_a_layout_is_saved_from_the_presets_the_kit_offered(tab):
    tab.set(presets=[{"key": "side", "words": "Side", "player": [0, 0, 720, 1080], "lcd": [720, 0, 1200, 675]}])
    assert tab.layout("nope") is False
    assert tab.layout("side")
    _wait(tab)
    script, args = [c for c in tab.calls if c[1] and c[1][0] == "layout"][-1]
    assert args == ["layout", "side", "[0, 0, 720, 1080]", "[720, 0, 1200, 675]"]


def test_the_runtime_row_installs_the_runtime_itself(tab, monkeypatch):
    """PAD-840: "Set it up on the Emulate tab" sent a user round install and
    reboot six times; that tab has no install for a PC with a working Ubuntu.
    The row runs the shared ladder, and the page then reads the new state."""
    from pinball_decryptor.core import runtime
    from pinball_decryptor.webui import runtime_prompt
    now = {"state": ("absent", "The runtime is not installed on this machine yet.")}
    monkeypatch.setattr(runtime, "status", lambda **k: now["state"])
    asked = []

    def ensure(say, progress=None, ask=None, on_blocked=None):
        asked.append(ask)
        progress(50, 100)
        now["state"] = ("ready", "Runtime 6 (full).")
        return "ready"
    monkeypatch.setattr(runtime_prompt, "ensure", ensure)
    tab.on_show()
    _wait(tab)
    assert tab.window.ctx.store.d["vpx"]["runtime_state"] == "absent"
    assert tab.install_runtime()
    _wait(tab)
    st = tab.window.ctx.store.d["vpx"]
    assert asked and callable(asked[0])
    assert st["runtime_state"] == "ready" and st["progress"] is None
    assert "installed" in st["message"]


def test_the_runtime_row_no_longer_points_at_the_emulate_tab():
    js = open(os.path.join(os.path.dirname(V.__file__), "..", "static", "js", "tabs", "vpx.js"),
              encoding="utf-8").read()
    assert "Set it up on the Emulate tab" not in js
    assert 'call("vpx.install_runtime")' in js


def _godzilla(tab, monkeypatch):
    """A tab whose state lists Godzilla, not patched yet; the dialog titles it asks with."""
    asked = []
    monkeypatch.setattr(tab.window, "ask_open", lambda key, title, *a, **k: asked.append(title) or tab.window.pick,
                        raising=False)
    tab.on_show()
    _wait(tab)
    tab.set(tables=[{"name": "Godzilla Limited Edition v2.6", "output": "Godzilla (PAD).vpx", "patched": False}])
    return asked


def test_a_tables_own_patch_button_names_it_in_the_dialog(tab, monkeypatch):
    """PAD-927: Patch is on the row of a table not patched yet, not one button
    at the bottom of the list."""
    asked = _godzilla(tab, monkeypatch)
    tab.window.pick = r"D:\Downloads\Godzilla LE v2.6.vpx"
    # The kit prints the made table's path in the host's own form (PAD-931:
    # a Windows path read as one whole name on the Linux and macOS runners).
    made = os.path.join(os.sep + "VP", "tables", "Godzilla (PAD).vpx")
    tab.answers[("padvpx.py", "patch")] = {"_text": 'open "%s" in Visual Pinball' % made}
    assert tab.patch("Godzilla (PAD).vpx")
    _wait(tab)
    assert asked == ["Choose your download of Godzilla Limited Edition v2.6"]
    assert not [ln for ln in tab.window.lines if ln[0] in ("error", "warning")]


def test_a_rows_patch_says_when_the_download_was_another_table(tab, monkeypatch):
    _godzilla(tab, monkeypatch)
    tab.window.pick = r"D:\Downloads\Rush LE 2.0.2.vpx"
    tab.answers[("padvpx.py", "patch")] = {"_text": r'open "C:\VP\tables\Rush LE 2.0.2 (PAD).vpx" in Visual Pinball'}
    assert tab.patch("Godzilla (PAD).vpx")
    _wait(tab)
    warned = [t for lv, t in tab.window.lines if lv == "warning"]
    assert warned and "is not Godzilla Limited Edition v2.6" in warned[0] and "Rush LE 2.0.2 (PAD).vpx" in warned[0]


def test_a_patched_tables_patch_again_runs_on_its_recorded_download(tab, monkeypatch):
    """PAD-939: "No button to do that in the app" - a patched table offers
    Patch again; with the download the kit recorded still there it runs on
    it, no dialog; a copy patched before the record asks for the download."""
    asked = _godzilla(tab, monkeypatch)
    src = r"D:\Downloads\Godzilla LE v2.6.vpx"
    tab.set(tables=[{"name": "Godzilla Limited Edition v2.6", "output": "Godzilla (PAD).vpx",
                     "patched": True, "source": src}])
    tab.answers[("padvpx.py", "patch")] = {"_text": r'open "C:\VP	ables\Godzilla (PAD).vpx" in Visual Pinball'}
    assert tab.patch("Godzilla (PAD).vpx")
    _wait(tab)
    assert asked == [] and ("padvpx.py", ["patch", os.path.normpath(src), "--out", r"C:\VP\tables"]) in tab.calls
    tab.set(tables=[{"name": "Godzilla Limited Edition v2.6", "output": "Godzilla (PAD).vpx",
                     "patched": True, "source": ""}])
    tab.window.pick = src
    assert tab.patch("Godzilla (PAD).vpx")
    _wait(tab)
    assert asked == ["Choose your download of Godzilla Limited Edition v2.6"]
    js = open(os.path.join(os.path.dirname(V.__file__), "..", "static", "js", "tabs", "vpx.js"),
              encoding="utf-8").read()
    assert 'patchBtn(t, !t.patched ? "Patch…" : t.source ? "Patch again" : "Patch again…")' in js
    assert "Your copy was patched before a fix" in js


def test_the_page_is_laid_out_for_a_set_up_pc():
    """PAD-927: no Patch button under the list, a Patch per table, and the
    window layouts as Use buttons (no radio that nothing had picked)."""
    js = open(os.path.join(os.path.dirname(V.__file__), "..", "static", "js", "tabs", "vpx.js"),
              encoding="utf-8").read()
    # PAD-941: the checklist sheet (a Modal, before the page) has a footer; the Tables card none
    assert "Patch a table" not in js and "footer=" not in js[js.index("export default function Vpx"):]
    assert 'call("vpx.patch", t.output)' in js
    assert "Radio" not in js and 'call("vpx.layout", p.key)' in js and "p.short" in js
    assert "Where you left them" in js
    assert 'call("vpx.patch_folder")' in js


def test_the_tables_are_one_labelled_column():
    """PAD-940: one table per line under labelled columns, not two or three
    CSS columns of rows with the model and the card crammed into one cell."""
    here = os.path.join(os.path.dirname(V.__file__), "..", "static")
    js = open(os.path.join(here, "js", "tabs", "vpx.js"), encoding="utf-8").read()
    css = open(os.path.join(here, "css", "tabs", "vpx.css"), encoding="utf-8").read()
    assert "vpx-grid" not in js and "columns:" not in css.replace("grid-template-columns:", "")
    for head in ("<span>Table</span>", ">By</span>", ">From</span>", ">Model</span>",
                 "<span>Card image</span>", "<span>Your copy</span>"):
        assert head in js
    assert "Get it on" not in js
    # David: Patch and Play a column each on every line, Play greyed until patched
    assert 'class="vpx-patch"' in js and 'class="vpx-play"' in js
    assert "disabled=${busy || !s.vpx || !t.patched}" in js
    # a short window scrolls the page; the Tables card is never squeezed under its rows
    assert ".vpx-page > .card { flex: 0 0 auto; }" in css


def test_a_folder_of_downloads_is_patched_in_one_go(tab, monkeypatch, tmp_path):
    """PAD-927: Patch a folder... runs every .vpx that is not a (PAD) copy
    through the patch; unknown tables and archives are counted, not errors."""
    for n in ("Rush LE 2.0.2.vpx", "Batman66_1.1.0.vpx", "Other.vpx", "Rush LE (PAD).vpx", "Bond.zip"):
        (tmp_path / n).write_bytes(b"x")
    tab.on_show()
    _wait(tab)
    tab.window.pick = str(tmp_path)
    seen = []

    def kit(self, script, args, timeout=0, on_line=None):
        if args and args[0] == "state":
            return {"registered": True, "vpx": r"C:\VP", "tables_dir": r"C:\VP\tables", "library": "",
                    "cards": {}, "tables": [], "patched": [], "presets": [], "layout": ""}
        if args and args[0] in ("titles", "coverage"):   # PAD-941: the authors' card asks after each job
            return {"titles": [], "coverage": {}}
        seen.append(args)
        name = os.path.basename(args[1])
        if name == "Other.vpx":
            return {"_text": "this table is not one the kit knows; it can patch: rush_le"}
        return {"_text": r'open "C:\VP\tables\%s (PAD).vpx" in Visual Pinball' % name[:-4]}
    monkeypatch.setattr(V.VpxTab, "_kit", kit)
    assert tab.patch_folder()
    _wait(tab)
    assert [os.path.basename(a[1]) for a in seen] == ["Batman66_1.1.0.vpx", "Other.vpx", "Rush LE 2.0.2.vpx"]
    assert all(a[2:] == ["--out", r"C:\VP\tables"] for a in seen)
    last = tab.window.lines[-1][1]
    assert "2 of 3 tables patched" in last and "1 not one the app knows (Other.vpx)" in last
    assert "1 archive skipped" in last and "Bond.zip" in last
    assert not [ln for ln in tab.window.lines if ln[0] == "error"]


# -- PAD-941: the card for table authors ---------------------------------------

def test_the_author_titles_come_from_the_kit_and_a_card_title_is_picked_first(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["godzilla_le", "rush_le", "james_bond_le"]}
    tab.window.ctx.store.set("vpx", cards={"rush_le": ["rush_le-1_19_0.Release.16G.sdcard.raw"]},
                             tables=[{"title": "rush_le", "titles": ["rush_le"]}])
    tab.on_show()
    _wait(tab)
    assert tab.get("author_titles") == ["godzilla_le", "james_bond_le", "rush_le"]
    assert ("vpxauthor.py", ["titles"]) in tab.calls
    # the first table whose card is in the folder, not the alphabetical first
    # (the kit's state call in this harness returns no cards, so the first)
    assert tab.get("author_title") in ("rush_le", "godzilla_le")
    assert tab.pick_author_title("james_bond_le") and tab.get("author_title") == "james_bond_le"
    assert not tab.pick_author_title("nosuch") and tab.get("author_title") == "james_bond_le"


def _data(**summary):
    return {"title": summary.get("title", ""), "summary": summary, "notes": [], "map": summary.get("map", ""),
            "switches": [], "coils": [], "inserts": [], "guesses": [], "wrong": [], "inventory": None,
            "starter": None, "markdown": "# x", "csv": "a,b"}


def test_the_checklist_opens_the_sheet_from_the_kits_data(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["james_bond_le"]}
    tab.on_show()
    _wait(tab)
    tab.answers[("vpxauthor.py", "data")] = _data(title="james_bond_le", switches=63, coils=17, inserts=86, ids=True)
    assert tab.checklist(False)
    _wait(tab)
    script, args = [c for c in tab.calls if c[0] == "vpxauthor.py" and c[1][0] == "data"][-1]
    assert args == ["data", "james_bond_le"]
    assert tab.get("sheet")["summary"]["switches"] == 63 and "_text" not in tab.get("sheet")
    assert tab.get("author_note").startswith("james_bond_le: 63 switches, 17 coils, 86 inserts.")
    assert tab.close_sheet() and tab.get("sheet") is None


def test_checking_a_table_passes_it_and_says_what_it_lacks(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["james_bond_le"]}
    tab.on_show()
    _wait(tab)
    tab.window.pick = r"D:\Downloads\bond.vpx"
    tab.answers[("vpxauthor.py", "data")] = _data(
        title="james_bond_le", switches=63, coils=17, inserts=86, ids=True, table="bond.vpx",
        map="james_bond_le.shadow.json", missing_switches=19, missing_coils=0, missing_inserts=0,
        guesses=10, id_mismatch=0)
    assert tab.checklist(True)
    _wait(tab)
    args = [c for c in tab.calls if c[0] == "vpxauthor.py" and c[1][0] == "data"][-1][1]
    assert args == ["data", "james_bond_le", "--table", r"D:\Downloads\bond.vpx"]
    assert ("bond.vpx against the app's map: 19 switches, 0 coils and 0 inserts the table leaves out, "
            "10 marked GUESS") in tab.get("author_note")


def test_export_writes_the_sheets_csv_markdown_or_starter(tab, tmp_path):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["godzilla_le"]}
    tab.on_show()
    _wait(tab)
    assert not tab.export("csv")                             # no sheet open
    tab.window.ctx.store.set("vpx", sheet={
        "title": "godzilla_le", "summary": {}, "inventory": {"name": "Nudge: Test.vpx"},
        "csv": "section,ok\nswitch,yes\n", "markdown": "# godzilla_le\n", "starter": {"title": "godzilla_le"}})
    asked = []

    def ask_save(key, title, initialfile="", filetypes=None, defaultextension="", initialdir=None):
        asked.append((initialfile, defaultextension))
        return str(tmp_path / initialfile)
    tab.window.ask_save = ask_save
    assert tab.export("csv") and tab.export("md") and tab.export("starter")
    assert asked == [("godzilla_le - Visual Pinball table checklist - Nudge_ Test.csv", ".csv"),
                     ("godzilla_le - Visual Pinball table checklist - Nudge_ Test.md", ".md"),
                     ("godzilla_le.starter.shadow.json", ".json")]
    assert (tmp_path / asked[0][0]).read_text(encoding="utf-8") == "section,ok\nswitch,yes\n"
    assert (tmp_path / asked[1][0]).read_text(encoding="utf-8") == "# godzilla_le\n"
    assert '"title": "godzilla_le"' in (tmp_path / asked[2][0]).read_text(encoding="utf-8")
    assert not tab.export("nosuch")


def test_a_title_with_no_tables_yet_is_a_warning_not_an_error(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["venom_le"]}
    tab.on_show()
    _wait(tab)
    tab.answers[("vpxauthor.py", "data")] = {
        "error": "No device tables for venom_le on this PC yet: play it once (the Emulate tab, or its table) and try again."}
    assert tab.checklist(False)
    _wait(tab)
    assert [lv for lv, t in tab.window.lines if "No device tables" in t] == ["warning"]
    assert "No device tables" in tab.get("author_note") and not tab.get("sheet")


def test_the_words_name_a_starter_map_and_another_titles_table():
    words = V.VpxTab._checklist_words({"title": "godzilla_le", "switches": 48, "coils": 14, "inserts": 89,
                                       "ids": True, "table": "Nudge.vpx"})
    assert "The app has no map for Nudge.vpx: a starter map is ready to save" in words
    words = V.VpxTab._checklist_words({"title": "rush_le", "asked": "stranger_things_le", "table": "Rush.vpx",
                                       "switches": 54, "coils": 17, "inserts": 72, "ids": True, "out": "o.md",
                                       "missing_switches": 0, "missing_coils": 0, "missing_inserts": 0,
                                       "guesses": 35, "id_mismatch": 3})
    assert words.startswith("Rush.vpx is rush_le's table. rush_le: 54 switches")
    assert "3 switches the map numbers otherwise than this PC's game" in words


def test_nothing_runs_when_the_checklist_dialog_is_cancelled(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["rush_le"]}
    tab.on_show()
    _wait(tab)
    tab.window.pick = ""
    assert not tab.checklist(True)
    assert not [c for c in tab.calls if c[1] and c[1][0] == "data"]


def test_coverage_is_read_once_per_sitting_and_on_check_again(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["rush_le"]}
    tab.answers[("vpxauthor.py", "coverage")] = {"coverage": {"rush_le": {"pct": 78, "switches": [44, 51],
                                                                          "coils": [7, 11], "inserts": [70, 94]}}}
    tab.on_show()
    _wait(tab)
    assert tab.get("coverage")["rush_le"]["pct"] == 78
    n = len([c for c in tab.calls if c == ("vpxauthor.py", ["coverage"])])
    assert n == 1
    tab.answers[("vpxauthor.py", "data")] = _data(title="rush_le", switches=1, coils=1, inserts=1, ids=True)
    tab.checklist(False)                                     # a job: the page reloads, coverage is kept
    _wait(tab)
    assert len([c for c in tab.calls if c == ("vpxauthor.py", ["coverage"])]) == n
    tab.refresh()
    _wait(tab)
    assert len([c for c in tab.calls if c == ("vpxauthor.py", ["coverage"])]) == n + 1


def test_a_rows_coverage_button_checks_the_download_it_was_patched_from(tab, monkeypatch):
    tab.answers[("vpxauthor.py", "titles")] = {"titles": ["rush_le", "beatles"]}
    tab.on_show()
    _wait(tab)
    monkeypatch.setattr(V.os, "startfile", lambda p: None, raising=False)
    tab.window.ctx.store.set("vpx", tables=[
        {"title": "rush_le", "titles": ["rush_le"], "output": "Rush LE 2.0.2 (PAD).vpx", "patched": True,
         "source": r"D:\dl\Rush LE 2.0.2.vpx"},
        {"title": "beatles", "titles": ["beatles"], "output": "The Beatles_007 (PAD).vpx", "patched": True, "source": ""},
        {"title": "godzilla_le", "titles": ["godzilla_le"], "output": "Godzilla (PAD).vpx", "patched": False}])
    rows = tab.get("tables")
    tab.answers[("vpxauthor.py", "data")] = _data(title="rush_le", switches=54, coils=11, inserts=94, ids=True)
    assert tab.row_checklist("Rush LE 2.0.2 (PAD).vpx")
    _wait(tab)
    args = [c for c in tab.calls if c[0] == "vpxauthor.py" and c[1][0] == "data"][-1][1]
    assert args == ["data", "rush_le", "--table", r"D:\dl\Rush LE 2.0.2.vpx"]
    tab.window.ctx.store.set("vpx", tables=rows)             # a job reloads the page's (stubbed, empty) tables
    assert tab.row_checklist("The Beatles_007 (PAD).vpx")        # no record of the download: the (PAD) copy
    _wait(tab)
    args = [c for c in tab.calls if c[0] == "vpxauthor.py" and c[1][0] == "data"][-1][1]
    assert args == ["data", "beatles", "--table", os.path.join(r"C:\VP\tables", "The Beatles_007 (PAD).vpx")]
    tab.window.ctx.store.set("vpx", tables=rows)
    assert tab.row_checklist("Godzilla (PAD).vpx")                # not patched: the game alone
    _wait(tab)
    args = [c for c in tab.calls if c[0] == "vpxauthor.py" and c[1][0] == "data"][-1][1]
    assert args == ["data", "godzilla_le"]
    assert not tab.row_checklist("nosuch.vpx")


# ---------------------------------------------------------- PAD-942 -----

def _picture_state(tmp_path):
    tables = tmp_path / "tables"
    tables.mkdir()
    (tables / "Rush LE 2.0.2 (PAD).vpx").write_bytes(b"x" * 10)
    (tables / "Other (PAD).vpx").write_bytes(b"y" * 10)
    return {"registered": True, "vpx": r"C:\VP", "tables_dir": str(tables), "library": "", "cards": {},
            "tables": [{"name": "Rush LE Tribute", "output": "Rush LE 2.0.2 (PAD).vpx", "patched": True,
                        "title": "rush_le", "titles": ["rush_le"]},
                       {"name": "Godzilla", "output": "Godzilla (PAD).vpx", "patched": False,
                        "title": "godzilla_le", "titles": ["godzilla_le"]}],
            "patched": ["Rush LE 2.0.2 (PAD).vpx", "Other (PAD).vpx"], "presets": [], "layout": ""}


def _wait_pictures(tab):
    deadline = time.time() + 10
    while (tab._pictures_running or tab._busy) and time.time() < deadline:
        time.sleep(0.02)
    assert not tab._pictures_running and not tab._busy


def test_pictures_in_the_cache_go_up_with_the_page_and_the_rest_are_read(tab, monkeypatch, tmp_path):
    """PAD-942: a patched row's picture is read from its (PAD) copy by the
    kit, once; the cache (keyed by the file) answers the next sitting."""
    state = _picture_state(tmp_path)
    cache = tmp_path / "pictures"
    cache.mkdir()
    rush = os.path.join(state["tables_dir"], "Rush LE 2.0.2 (PAD).vpx")
    other = os.path.join(state["tables_dir"], "Other (PAD).vpx")
    # Rush is in the cache already; a stale sidecar of a table no longer here is dropped
    (cache / "rush.jpg").write_bytes(b"jpg")
    (cache / (V.picture_key(rush) + ".json")).write_text(
        json.dumps({"file": str(cache / "rush.jpg"), "w": 50, "h": 100, "source": "playfield"}))
    (cache / "gone.json").write_text("{}")
    (cache / "gone.jpg").write_bytes(b"")
    kit_calls = []

    def kit(self, script, args, timeout=0, on_line=None):
        if args and args[0] == "state":
            return dict(state)
        if script == "vpxpicture.py":
            kit_calls.append(list(args))
            (cache / "Other (PAD).jpg").write_bytes(b"jpg")
            on_line("picture " + json.dumps({"table": other, "file": str(cache / "Other (PAD).jpg"),
                                             "w": 40, "h": 80, "source": "screenshot", "full": [400, 800]}))
            return {"pictures": {}, "errors": {}, "_text": ""}
        return {"result": "ok", "_text": ""}
    monkeypatch.setattr(V.VpxTab, "_kit", kit)
    tab.refresh()
    _wait(tab)
    _wait_pictures(tab)
    assert kit_calls == [[str(cache), other]]
    pics = tab.get("pictures")
    assert pics["Rush LE 2.0.2 (PAD).vpx"] == {"file": str(cache / "rush.jpg"), "w": 50, "h": 100, "source": "playfield"}
    assert pics["Other (PAD).vpx"] == {"file": str(cache / "Other (PAD).jpg"), "w": 40, "h": 80, "source": "screenshot"}
    assert "Godzilla (PAD).vpx" not in pics and tab.get("pictures_busy") == ""
    assert not (cache / "gone.json").exists() and not (cache / "gone.jpg").exists()
    assert json.load(open(cache / (V.picture_key(other) + ".json"))) == pics["Other (PAD).vpx"]
    # the next sitting: both from the cache, nothing read
    tab.refresh()
    _wait(tab)
    _wait_pictures(tab)
    assert len(kit_calls) == 1 and tab.get("pictures") == pics


def test_a_table_with_no_picture_is_remembered_as_such_until_it_changes(tab, monkeypatch, tmp_path):
    """Metallica's playfield is an HDR file: its error is kept, so the kit is
    not asked every sitting; a new copy of the file (a re-patch) asks again."""
    state = _picture_state(tmp_path)
    rush = os.path.join(state["tables_dir"], "Rush LE 2.0.2 (PAD).vpx")
    other = os.path.join(state["tables_dir"], "Other (PAD).vpx")
    cache = tmp_path / "pictures"
    kit_calls = []

    def kit(self, script, args, timeout=0, on_line=None):
        if args and args[0] == "state":
            return dict(state)
        if script == "vpxpicture.py":
            kit_calls.append(list(args))
            for path in args[1:]:
                on_line("picture " + json.dumps({"table": path, "error": "the table's playfield is not a picture the kit reads"}))
            return {"pictures": {}, "errors": {}, "_text": ""}
        return {"result": "ok", "_text": ""}
    monkeypatch.setattr(V.VpxTab, "_kit", kit)
    tab.refresh()
    _wait(tab)
    _wait_pictures(tab)
    assert kit_calls == [[str(cache), other, rush]]
    assert tab.get("pictures")["Rush LE 2.0.2 (PAD).vpx"] == {"error": "the table's playfield is not a picture the kit reads"}
    tab.refresh()
    _wait(tab)
    _wait_pictures(tab)
    assert len(kit_calls) == 1
    with open(rush, "wb") as f:
        f.write(b"z" * 20)
    tab.refresh()
    _wait(tab)
    _wait_pictures(tab)
    assert kit_calls[-1] == [str(cache), rush]


def test_the_rows_carry_a_picture_and_the_tip_shows_it_large():
    """PAD-942: the picture column at the head of every row, served as media;
    the tooltip takes an image, laid out at its size before it loads."""
    here = os.path.join(os.path.dirname(V.__file__), "..", "static")
    js = open(os.path.join(here, "js", "tabs", "vpx.js"), encoding="utf-8").read()
    ui = open(os.path.join(here, "js", "core", "ui.js"), encoding="utf-8").read()
    css = open(os.path.join(here, "css", "tabs", "vpx.css"), encoding="utf-8").read()
    app = open(os.path.join(here, "css", "app.css"), encoding="utf-8").read()
    assert "mediaUrl" in js and '<span class="vpx-pic">${picture(t)}</span>' in js
    assert "image: url, w: p.w, h: p.h" in js and 'class="vpx-nopic"' in js
    assert "spec.image" in ui and 'className = "tip-img"' in ui and "img.width = spec.w" in ui
    assert css.count("grid-template-columns: 40px") == 2
    assert ".tip.tip-pic { max-width: none; }" in app and ".tip .tip-img" in app
    # the stale note sits under the name, not under the picture
    assert ".vpx-stale { grid-column: 2 / -1;" in css


# ---- PAD-943: the other platforms' tables -----------------------------------

def _vpxsetup():
    kit = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "tools", "spike2_emu", "vpx")
    if kit not in sys.path:
        sys.path.insert(0, kit)
    return pytest.importorskip("vpxsetup")


def test_the_catalogue_names_every_platform_and_where_each_table_is():
    vs = _vpxsetup()
    cat = vs.load_catalog()
    plats, tables = cat["platforms"], cat["tables"]
    assert {"spike1", "jjp", "ap", "cgc", "dp", "spooky", "bof", "pb", "turner", "multimorphic"} <= set(plats)
    assert "sam" not in plats                   # David: SAM is Visual PinMAME's already
    # David: JJP games run only with the machine's own security key; the card says so up front
    assert "security key" in plats["jjp"]["needs"] and "H0007" in plats["jjp"]["needs"]
    assert all(p.get("name") and p.get("runs") and p.get("bridge") in ("pad", "vpm", "none") for p in plats.values())
    assert tables and all(t["platform"] in plats for t in tables)
    for t in tables:
        if t.get("url"):
            assert t["url"].startswith("https://") and t["name"] and t["where"], t
            assert t["kind"] in ("tribute", "mashup"), t    # nothing Visual PinMAME runs by itself
        else:
            assert t.get("notes"), t            # a game with no table says so
    # the Spike 1 title the kit has a map for is in it, and names the map
    assert any(t.get("title") == "got_le" and t.get("map") for t in tables)


def test_the_catalogue_rides_the_kits_state(monkeypatch):
    vs = _vpxsetup()
    monkeypatch.setattr(vs, "load_catalog", lambda: {"platforms": {"jjp": {"name": "Jersey Jack"}}, "tables": [{"platform": "jjp"}]})
    st = vs.state()
    assert st["catalog"]["platforms"]["jjp"]["name"] == "Jersey Jack"
    assert st["catalog"]["tables"] == [{"platform": "jjp"}]


def test_the_tab_starts_with_an_empty_catalogue(tab):
    assert tab.get("catalog") == {"platforms": {}, "tables": []}
    assert "Spike 1" in tab.get("catalog_tip")


# ---- PAD-943: the page is up before the slow parts are in -------------------

def test_the_page_is_up_on_the_state_alone_and_the_rest_comes_after(tab, monkeypatch):
    """David: the tables took ten seconds to show. The kit's state (half a
    second) puts the page up; the authors' titles and the coverage come in
    behind it with their own 'still looking' flags, never holding the page."""
    seen = []
    gate = threading.Event()
    orig = type(tab)._kit

    def slow_kit(self, script, args, timeout=0, on_line=None):
        if script == "vpxauthor.py":
            seen.append((args[0], self.get("loaded"), self.get("busy")))
            gate.wait(5)                         # the slow WSL walk
            if args[0] == "titles":
                return {"titles": ["rush_le", "got_le"]}
            return {"coverage": {"rush_le": {"pct": 90}}}
        return orig(self, script, args, timeout, on_line)
    monkeypatch.setattr(type(tab), "_kit", slow_kit)
    tab.on_show()
    deadline = time.time() + 5
    while not tab.get("loaded") and time.time() < deadline:
        time.sleep(0.02)
    assert tab.get("loaded") and tab.get("busy") == ""   # up, and not busy, while the titles are looked for
    assert tab.get("authors_busy") and tab.get("coverage_busy")
    assert not tab._busy                                    # a button works meanwhile
    gate.set()
    _wait(tab)
    assert seen[0][0] == "titles" and seen[0][1] is True and seen[0][2] == ""
    assert tab.get("author_titles") == ["got_le", "rush_le"] and not tab.get("authors_busy")
    assert tab.get("coverage") == {"rush_le": {"pct": 90}} and not tab.get("coverage_busy")


def test_the_last_state_seen_draws_the_page_at_once(tab, monkeypatch, tmp_path):
    cache = tmp_path / "vpx_state.json"
    monkeypatch.setattr(type(tab), "_state_cache_path", staticmethod(lambda: str(cache)))
    tab.on_show()
    _wait(tab)
    assert json.load(open(cache, encoding="utf-8"))["vpx"] == r"C:\VP"   # the fresh state is kept
    # a new tab on the same PC: the cache is on the page before the kit answers
    drawn = []
    orig = type(tab)._kit

    def kit(self, script, args, timeout=0, on_line=None):
        if args and args[0] == "state":
            drawn.append((self.get("loaded"), self.get("stale"), self.get("vpx")))
        return orig(self, script, args, timeout, on_line)
    monkeypatch.setattr(type(tab), "_kit", kit)
    t2 = V.VpxTab(_Win())
    t2.answers = {}
    t2.on_show()
    _wait(t2)
    assert drawn == [(True, True, r"C:\VP")]
    assert t2.get("loaded") and not t2.get("stale")


def test_a_kit_without_titles_leaves_the_page_usable(tab):
    tab.answers[("vpxauthor.py", "titles")] = {"error": "WSL is not answering"}
    tab.answers[("vpxauthor.py", "coverage")] = {"error": "WSL is not answering"}
    tab.on_show()
    _wait(tab)
    assert tab.get("loaded") and tab.get("author_titles") == [] and not tab.get("authors_busy")
    assert tab.get("coverage") == {} and not tab.get("coverage_busy")


# ---- PAD-943: the downloads in the folder show by themselves --------------

def _vpx_file(folder, name, script=""):
    p = folder / name
    p.write_bytes(b"vpx" + script.encode("utf-8"))
    return str(p)


def test_the_folders_downloads_are_listed_at_once_and_read_once(tmp_path, monkeypatch):
    vs = _vpxsetup()
    import padvpx
    folder = tmp_path / "tables"
    folder.mkdir()
    _vpx_file(folder, "Game of Thrones LE (Stern 2015) VPW 1.2.1.vpx")
    _vpx_file(folder, "Rush LE 2.0.2.vpx")
    _vpx_file(folder, "Rush LE 2.0.2 (PAD).vpx")
    monkeypatch.setattr(vs, "DOWNLOADS_CACHE", str(tmp_path / "cache.json"))
    reads = []

    def fitting(path):
        reads.append(os.path.basename(path))
        return [("rush_le", {"listed": True})] if "Rush" in path else []
    monkeypatch.setattr(padvpx, "fitting", fitting)
    rows = vs.downloads_in(str(folder))
    assert [r["file"] for r in rows] == ["Game of Thrones LE (Stern 2015) VPW 1.2.1.vpx", "Rush LE 2.0.2.vpx"]
    assert not any(r["read"] for r in rows)         # listed at once, not read yet
    rows = vs.read_downloads(str(folder))
    assert sorted(reads) == ["Game of Thrones LE (Stern 2015) VPW 1.2.1.vpx", "Rush LE 2.0.2.vpx"]
    got, rush = rows
    assert got["read"] and got["title"] == "" and got["catalog"]["platform"] == "spike1" \
        and got["catalog"]["game"] == "Game of Thrones"
    # the author's description rides along, for the row on the page
    assert got["catalog"]["by"] == "VPinWorkshop" and got["catalog"]["where"] == "VPUniverse"
    assert got["catalog"]["title"] == "got_le" and got["catalog"]["url"].startswith("https://")
    assert rush["read"] and rush["title"] == "rush_le"
    # read once: the cache answers the next look, a changed file is read again
    assert all(r["read"] for r in vs.downloads_in(str(folder)))
    vs.read_downloads(str(folder))
    assert len(reads) == 2
    (folder / "Rush LE 2.0.2.vpx").write_bytes(b"vpx more")
    vs.read_downloads(str(folder))
    assert len(reads) == 3
    # a known table's row takes the download its map fits
    linked = vs.link_downloads([{"titles": ["rush_le"]}, {"titles": ["godzilla_le"]}], rows)
    assert linked[0]["download"].endswith("Rush LE 2.0.2.vpx") and linked[1]["download"] == ""
    assert vs.catalog_match("KISS (Stern 2015) 2.0.vpx")["game"] == "KISS"
    assert vs.catalog_match("something else entirely.vpx") is None


def test_a_download_dropped_in_the_folder_shows_without_check_again(tab, tmp_path, monkeypatch):
    folder = tmp_path / "tables"
    folder.mkdir()
    monkeypatch.setattr(type(tab), "WATCH_S", 0.05)
    tab.on_show()
    _wait(tab)
    tab.set(tables_dir=str(folder))
    time.sleep(0.2)                                  # the watcher has seen the empty folder
    n = len([c for c in tab.calls if c == ("vpxsetup.py", ["state"])])
    _vpx_file(folder, "KISS (Stern 2015) 2.0.vpx")
    deadline = time.time() + 5
    while len([c for c in tab.calls if c == ("vpxsetup.py", ["state"])]) == n and time.time() < deadline:
        time.sleep(0.02)
    _wait(tab)
    assert len([c for c in tab.calls if c == ("vpxsetup.py", ["state"])]) > n
    tab.on_close()
    assert not tab._watching


def test_patch_takes_the_download_the_folder_holds_without_asking(tab):
    tab.on_show()
    _wait(tab)
    tab.set(tables=[{"name": "Rush LE Tribute", "output": "Rush LE 2.0.2 (PAD).vpx", "patched": False,
                     "title": "rush_le", "titles": ["rush_le"], "download": r"C:\VP\tables\Rush LE 2.0.2.vpx"}])
    tab.window.pick = ""                             # no dialog answer: the folder's download is taken
    tab.answers[("padvpx.py", "patch")] = {"result": "ok", "_text": 'open "C:/VP/tables/Rush LE 2.0.2 (PAD).vpx"'}
    assert tab.patch("Rush LE 2.0.2 (PAD).vpx")
    _wait(tab)
    assert ("padvpx.py", ["patch", r"C:\VP\tables\Rush LE 2.0.2.vpx", "--out", r"C:\VP\tables"]) in tab.calls


def test_unread_downloads_are_read_after_the_page_is_up(tab, monkeypatch):
    state_rows = {"downloads": [{"name": "KISS", "file": "KISS.vpx", "path": r"C:\VP\tables\KISS.vpx", "read": False}]}
    orig = type(tab)._kit

    def kit(self, script, args, timeout=0, on_line=None):
        if args and args[0] == "state":
            return dict(orig(self, script, args, timeout, on_line), **state_rows)
        if args and args[0] == "downloads":
            return {"downloads": [dict(state_rows["downloads"][0], read=True, title="", catalog=None)], "tables": []}
        return orig(self, script, args, timeout, on_line)
    monkeypatch.setattr(type(tab), "_kit", kit)
    tab.on_show()
    _wait(tab)
    assert tab.get("downloads")[0]["read"] is True      # read on the extras thread, after the page was up


def test_a_download_read_before_its_map_existed_is_read_again(tmp_path, monkeypatch):
    """David saw KISS and GOT twice: once as a download 'No map yet', once
    patched. The download had been read when the kit had no map for it and
    the cache said 'no map fits' for good."""
    vs = _vpxsetup()
    import padvpx
    folder = tmp_path / "tables"
    folder.mkdir()
    _vpx_file(folder, "KISS (Stern 2015) 2.0.vpx")
    monkeypatch.setattr(vs, "DOWNLOADS_CACHE", str(tmp_path / "cache.json"))
    maps = {}
    monkeypatch.setattr(padvpx, "maps", lambda: dict(maps))
    monkeypatch.setattr(padvpx, "fitting", lambda path: [(t, dict(i, listed=True)) for t, i in maps.items()])
    rows = vs.read_downloads(str(folder))
    assert rows[0]["read"] and rows[0]["title"] == ""           # no map yet: none fits
    assert vs.downloads_in(str(folder))[0]["read"]               # and the cache answers
    mp = tmp_path / "kiss_le.shadow.json"
    mp.write_text("{}", encoding="utf-8")
    maps["kiss_le"] = {"map": str(mp), "listed": True}
    assert not vs.downloads_in(str(folder))[0]["read"]           # a new map: read again
    rows = vs.read_downloads(str(folder))
    assert rows[0]["title"] == "kiss_le"
    assert vs.link_downloads([{"titles": ["kiss_le"]}], rows)[0]["download"].endswith("KISS (Stern 2015) 2.0.vpx")


def test_a_spike1_tables_row_finds_its_iso(monkeypatch, tmp_path):
    vs = _vpxsetup()
    import padlaunch
    seen = []
    monkeypatch.setattr(padlaunch, "card_for", lambda title, platform="spike2": seen.append((title, platform)) or "")
    monkeypatch.setattr(vs, "downloads_in", lambda d, cache=None: [])
    vs.known_tables(str(tmp_path))
    assert ("got_le", "spike1") in seen and ("rush_le", "spike2") in seen
