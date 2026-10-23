"""PAD-664: the printable rules sheet of a project's modes, made from the mode files (Modes tab, Rules sheet...).

A blocks mode is worded by playing it on the desk (plugins/stern/blocks_sim.py): these pin the words for the
shipped blocks examples (the same programs as David's Heisei card), a form mode's and a C mode's words, the
person's own words winning, the sheet's order and modes left off, the PDF (no browser, no library: one Letter or A4
page, the text in it) and the HTML, and the dialog's wiring to the tab.
"""

import json
import os
import re
import zlib

import pytest

from pinball_decryptor.core import pdf_sheet
from pinball_decryptor.plugins.stern import block_modes as BM
from pinball_decryptor.plugins.stern import blocks_sim as BS
from pinball_decryptor.plugins.stern import code_modes as CM
from pinball_decryptor.plugins.stern import mode_project as MP
from tests.mode_examples.blocks import examples as BX
from pinball_decryptor.plugins.stern import rules_sheet as RS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TABS = os.path.join(ROOT, "pinball_decryptor", "webui", "static", "js", "tabs")


def _program(slug):
    for e in BX.EXAMPLES:
        if e["slug"] == slug:
            return BM.normalize(e["program"])
    raise AssertionError("no blocks example " + slug)


def _words(slug, others=()):
    return RS.blocks_rules(_program(slug), [(_program(o)["name"], _program(o)) for o in others])


def _project(tmp_path, slugs=("maser_barrage", "kamacuras")):
    project = str(tmp_path / "proj")
    for slug in slugs:
        folder = os.path.join(project, "modes", slug)
        os.makedirs(folder)
        with open(os.path.join(folder, "blocks.json"), "w", encoding="utf-8") as f:
            json.dump(_program(slug), f)
        with open(os.path.join(folder, slug + ".c"), "w", encoding="utf-8") as f:
            f.write("/* made from its blocks */\n")
    return project


# ------------------------------------------------------------------ a blocks mode played on the desk
def test_a_shot_count_start_its_stages_and_cash_out():
    w = _words("maser_barrage")
    assert w["name"] == "MASER BARRAGE"
    assert w["start"] == "Maser target 5 / 10 / 15, in one ball"      # its hits this ball: 5 x (starts + 1)
    assert len(w["stages"]) == 3
    assert w["stages"][0].startswith("Left ramp") and "Building" in w["stages"][0]
    assert w["stages"][1].startswith("Crossfire: Powerline left")
    assert w["cash"] == "Scoop"


def test_a_start_lit_at_another_shot_and_a_mode_with_no_clock():
    w = _words("kamacuras")                                       # 0 seconds: no clock, its waves end it
    assert w["start"] == "Top spinner 80 / 160 / 240; then the Right scoop"
    assert len(w["stages"]) == 4 and w["stages"][-1].startswith("The Biggest Mantis: Building 3x")
    assert w["cash"] == ""


def test_counters_that_level_up_weighted_shots_and_shots_in_turn():
    assert _words("godzilla_angry")["start"] == "1000 / 2000 / 3000 playfield switch hits; then the Building"
    assert _words("king_caesar")["start"] == ("Pop bumper 50 / 100 / 150 (Right return lane counts 2, Mecha exit "
                                              "bottom counts 3); then the Mecha exit bottom")
    assert _words("ghidorah_heads")["start"] == "Powerline left, center and right 6 / 12 / 18 in all, in one ball"
    assert _words("oxygen_destroyer")["start"] == "Left spinner 40 / 80 / 120, in one ball"


def test_a_mode_of_its_own_and_one_the_other_modes_light():
    # PAD-675: JET JAGUAR no longer joins the game's next mode - a mode of his own
    assert _words("anguirus_assist")["start"] == "Shield target left, center or right 8 / 16 / 24"
    w = _words("final_wars", others=("ghidorah_heads", "oxygen_destroyer", "maser_barrage", "kumonga"))
    assert w["start"] == ("1 / 2 / 3 rounds of KING GHIDORAH, OXYGEN DESTROYER and MASER BARRAGE; "
                          "then the Building")
    assert [s.split(":")[0] for s in w["stages"]] == ["Invasion", "Monster X", "Keizer Ghidorah", "Godzilla Rises"]
    assert "2 balls" in w["stages"][3]


@pytest.mark.parametrize("slug", [e["slug"] for e in BX.EXAMPLES])
def test_every_shipped_example_is_worded(slug):
    w = _words(slug, others=[e["slug"] for e in BX.EXAMPLES if e["slug"] != slug])
    assert re.search(r"\d+ / \d+ / \d+", w["start"]), w["start"]
    assert len(w["stages"]) >= 3, w["stages"]
    assert all(s.strip() for s in w["stages"])


def test_the_desk_game_follows_the_blocks():
    prog = _program("meltdown")
    sim = BS.Sim(prog)
    for _ in range(15):
        sim.shot("Godzilla target")
        sim.advance(RS.SHOT_GAP_MS)
    # the fifteenth hit lights it there, and a light that shot put on waits for the next hit
    assert sim.lit == "Godzilla target" and not sim.running
    sim.shot("Godzilla target")
    assert sim.running and sim.lit is None
    assert not sim.has_clock                                       # 0 seconds: it runs until a block ends it
    sim.advance(10 * 60 * 1000)
    assert sim.running


# ------------------------------------------------------------------ form and C modes
def test_a_form_mode_says_its_fields():
    spec = MP.ModeSpec(name="RAMP FRENZY", start_shot="Left ramp", start_count=3,
                       scoring_shots=["Left ramp", "Right ramp"], seconds=30)
    w = RS.form_rules(spec)
    assert w["start"] == "Left ramp 3, in one ball"
    assert w["stages"] == ["Left ramp, Right ramp (30\u00a0s)"]
    spec.multiball, spec.balls = True, 3
    assert RS.form_rules(spec)["stages"] == ["3 balls, Left ramp, Right ramp (30\u00a0s)"]


def test_a_c_mode_says_its_clock_and_leaves_the_rest_to_its_maker():
    w = RS.code_rules(CM.CodeAssets(name="KAIJU", seconds=45))
    assert w["start"] == "" and w["stages"] == ["45\u00a0s"]


# ------------------------------------------------------------------ the sheet
def test_the_sheet_its_own_words_order_and_modes_left_off(tmp_path):
    project = _project(tmp_path)
    sheet = RS.build(project, None, "Godzilla Premium 1.16",
                     r"C:\x\Godzilla Premium 1.16 Heisei Custom V1.99D Kaiju Edition.raw")
    assert sheet["title"] == "Godzilla Custom Modes"
    assert sheet["intro"].startswith("This card adds 2 modes to Godzilla Premium 1.16 "
                                     "(Heisei Custom V1.99D Kaiju Edition).")
    assert [r["name"] for r in sheet["rows"]] == ["KAMACURAS", "MASER BARRAGE"]
    assert "a good shot tops the clock back up to 15\u00a0s" in sheet["foot"] or "15 s" in sheet["foot"]
    assert "A drain or tilt ends a mode." in sheet["foot"]

    RS.save_mode_words(project, "kamacuras", {"start": "Top spinner 50 / 100 / 150 lights the Right scoop",
                                              "tag": "REWORKED", "stages": "Waves of mantises\nThe biggest one"})
    st = RS.load_settings(project)
    st["order"], st["off"] = ["maser_barrage", "kamacuras"], []
    RS.save_settings(project, st)
    sheet = RS.build(project)
    km = sheet["rows"][1]
    assert [r["slug"] for r in sheet["rows"]] == ["maser_barrage", "kamacuras"]
    assert km["start"] == "Top spinner 50 / 100 / 150 lights the Right scoop" and km["tag"] == "REWORKED"
    assert km["stages"] == ["Waves of mantises", "The biggest one"]
    assert km["gen"]["start"] == "Top spinner 80 / 160 / 240; then the Right scoop"   # the app's, kept beside

    RS.save_mode_words(project, "kamacuras", {})                      # empty: the app's words again
    assert not os.path.exists(RS.mode_words_path(project, "kamacuras"))
    st["off"] = ["maser_barrage"]
    RS.save_settings(project, st)
    sheet = RS.build(project)
    assert [r["slug"] for r in sheet["rows"]] == ["kamacuras"]
    assert len(sheet["modes"]) == 2 and sheet["intro"].startswith("This card adds 1 mode to")


def test_a_form_mode_that_cannot_be_built_is_left_off(tmp_path):
    project = _project(tmp_path, ("maser_barrage",))
    MP.save(project, "broken", MP.ModeSpec(name="BROKEN", scoring_shots=[]))
    sheet = RS.build(project, MP.profile(MP.GODZILLA_PRO_1_15.key))
    assert [r["name"] for r in sheet["rows"]] == ["MASER BARRAGE"]
    assert [n for n, _why in sheet["left"]] == ["BROKEN"]


def test_the_title_words():
    assert RS.game_name("Godzilla Premium 1.16") == "Godzilla"
    assert RS.game_name("James Bond 007 LE 1.06") == "James Bond 007"
    assert RS.edition_words("Godzilla Premium 1.16", "Godzilla Premium 1.16.raw") == ""
    assert RS.join_shots(["Shield target left", "Shield target center", "Shield target right"]) == \
        "Shield target left, center or right"
    assert RS.title_words("THE NIGHT ATTACK") == "The Night Attack"
    assert RS.title_words("SERIZAWA'S CHOICE") == "Serizawa's Choice"


# ------------------------------------------------------------------ PDF and HTML
def _pdf_text(data):
    out = []
    for m in re.finditer(rb"stream\n(.*?)\nendstream", data, re.S):
        out.append(zlib.decompress(m.group(1)).decode("latin-1"))
    return "\n".join(out)


def _check_xref(data):
    start = int(re.search(rb"startxref\n(\d+)", data).group(1))
    assert data[start:start + 4] == b"xref"
    n = int(re.search(rb"xref\n0 (\d+)", data).group(1))
    offs = re.findall(rb"(\d{10}) 00000 n", data)
    assert len(offs) == n - 1
    for i, off in enumerate(offs, 1):
        assert data[int(off):].startswith(b"%d 0 obj" % i)


def test_the_pdf_is_one_page_of_the_sheet(tmp_path):
    project = _project(tmp_path, [e["slug"] for e in BX.EXAMPLES][:14])
    sheet = RS.build(project, None, "Godzilla Premium 1.16")
    for paper, box in (("letter", b"[0 0 792.00 612.00]"), ("a4", b"[0 0 841.89 595.28]")):
        data = RS.to_pdf(sheet, paper)
        assert data.startswith(b"%PDF-1.4") and data.rstrip().endswith(b"%%EOF")
        _check_xref(data)
        assert data.count(b"/Type /Page ") == 1 and box in data
        text = _pdf_text(data)
        shown = " ".join(re.findall(r"\((.*?)\) Tj", text))
        for r in sheet["rows"]:                                     # a long name may take two lines
            assert r["name"] in shown or all(w in shown.split() for w in r["name"].split()), r["name"]
        assert "(Godzilla Custom Modes)" in text and "/F2 22.00 Tf" in text
        assert b"/BaseFont /Helvetica-Bold" in data and b"FontFile" not in data     # nothing embedded


def test_a_long_sheet_runs_on_with_its_head_row():
    rows = [[[("MODE %d" % i, "bold")], [("Left ramp 3 / 6 / 9", "")], [("word " * 300, "")], [("Scoop", "")]]
            for i in range(14)]
    data = pdf_sheet.table_pdf("T", "intro", ["Mode", "Start", "Stages", "Cash out"], rows, "foot",
                               widths=(0.13, 0.25, 0.55, 0.07))
    pages = data.count(b"/Type /Page ")
    assert pages > 1
    assert _pdf_text(data).count("(Stages)") == pages
    _check_xref(data)


def test_text_the_fonts_cannot_write_and_words_kept_together():
    assert pdf_sheet.clean("Kaij\u016b \u2192 \u2265 3 \u00b7 \u2014") == "Kaiju > >= 3 \u00b7 \u2014"
    lines = pdf_sheet.wrap([("aaa bbb ", ""), ("2\u00a0", "bold"), ("Strands: x", "")], 8, 40)
    flat = [[s for _x, s, _st in line] for line in lines]
    at = [line for line in flat if "2\u00a0" in line]               # the number never ends a line alone
    assert at and at[0].index("2\u00a0") < len(at[0]) - 1, flat
    assert at[0][at[0].index("2\u00a0") + 1].startswith("Strands"), flat


def test_the_html_is_the_sheet_at_the_pdfs_size(tmp_path):
    project = _project(tmp_path)
    RS.save_mode_words(project, "kamacuras", {"tag": "<NEW>"})
    sheet = RS.build(project)
    page = RS.to_html(sheet, "a4")
    assert "@page { size: a4 landscape;" in page
    assert "<td class=\"mode\">KAMACURAS<span class=\"tag\">&lt;NEW&gt;</span></td>" in page
    size = RS._fit(sheet, "a4")[0]
    assert "font-size: %spt; line-height: 1.22" % size in page
    assert page.count("<tr><td") == 2


# ------------------------------------------------------------------ the tab
def test_every_call_the_dialog_makes_is_one_the_tab_answers():
    from pinball_decryptor.webui.tabs import modes as M
    with open(os.path.join(TABS, "modes_sheet.js"), encoding="utf-8") as f:
        js = f.read()
    with open(os.path.join(TABS, "modes.js"), encoding="utf-8") as f:
        tab = f.read()
    calls = set(re.findall(r'call\("modes\.([a-z_]+)"', js + tab))
    sheet_calls = {c for c in calls if c.startswith("sheet_")}
    assert sheet_calls == {"sheet_open", "sheet_close", "sheet_words", "sheet_setting", "sheet_on", "sheet_move",
                           "sheet_save"}, sheet_calls
    for name in sheet_calls:
        assert getattr(getattr(M.ModesTab, name), "__pad_rpc__", None), name
    assert ">Rules sheet…<//>" in tab and 'import { RulesSheetDialog } from "./modes_sheet.js";' in tab


class _Tab:
    """The rules sheet's part of the Modes tab, on a store of its own."""

    def __init__(self, project, save_to=""):
        from pinball_decryptor.webui.modes_sheet import RulesSheetMixin
        self.__class__ = type("T", (RulesSheetMixin, _Tab), {})
        self._project, self.state, self.said = project, {}, []
        self._profile = None
        self.window = type("W", (), {"ask_save": lambda _s, *a, **k: save_to})()
        self._init_sheet()

    def project(self):
        return self._project

    def set(self, **kw):
        self.state.update(kw)

    def get(self, key):
        return self.state.get(key)

    def _post(self, fn, *args):
        fn(*args)

    def _title_card(self, project):
        return None, ""

    def _save_if_edited(self):
        pass

    def _say(self, text):
        self.said.append(text)


def test_the_dialog_from_open_to_saved(tmp_path, monkeypatch):
    import threading
    project = _project(tmp_path)
    out = str(tmp_path / "Godzilla Custom Modes.pdf")
    monkeypatch.setattr(threading, "Thread", lambda target, **k: type("T", (), {"start": lambda s: target()})())
    tab = _Tab(project, out)
    tab.state["title_label"] = "Godzilla Premium 1.16"
    tab.sheet_open()
    sh = tab.state["sheet"]
    assert not sh["busy"] and sh["n_on"] == 2 and "<table>" in sh["html"]
    assert [r["name"] for r in sh["rows"]] == ["KAMACURAS", "MASER BARRAGE"]
    tab.sheet_words("kamacuras", "tag", "REWORKED")
    assert tab.state["sheet"]["rows"][0]["tag"] == "REWORKED"
    tab.sheet_move("kamacuras", 1)
    assert [r["slug"] for r in tab.state["sheet"]["rows"]] == ["maser_barrage", "kamacuras"]
    tab.sheet_on("maser_barrage", False)
    assert tab.state["sheet"]["n_on"] == 1
    tab.sheet_setting("paper", "a4")
    assert tab.state["sheet"]["paper"] == "a4"
    assert tab.sheet_save("pdf") == out
    with open(out, "rb") as f:
        assert b"[0 0 841.89 595.28]" in f.read()
    assert tab.said and "1 mode" in tab.said[-1]
    tab.sheet_close()
    assert tab.state["sheet"] is None
