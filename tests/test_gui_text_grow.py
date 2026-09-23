"""Replace Text tab: growable game-program rows, Replace everywhere, the
Write tab's grow option and its pending-row status.

David (2026-09-07): "on the TEXT tab, it still gives me grief that it is too
long with a Max column still persisting. Ideally, changes here would
propagate everywhere and I would be able to easily view them to confirm it
looks good."  The engine side (plans/spike2_longer_program_text.md) places a
longer program string in a new area of the game program; this is the UI
half: the Max column shows the manifest's budget (96 for a growable row),
Apply accepts anything within it, "Replace everywhere…" changes a word in
every row at once, and the Write tab says which pending edit grows the
program and whether the Advanced option lets it.

The rules live in webui/text_rules.py; the tabs are driven through the web
UI's Text and Write services (webui/tabs/text.py, webui/tabs/write.py).
"""

import json
import os
import time

from pinball_decryptor.core import text_manifest as tm
from pinball_decryptor.webui import text_rules as R
from tests.webui_harness import web_app

GAME = "/godzilla_le/game"
SCENE = "/godzilla_le/assets/lcd/auto_loaded/aaaa1111bbbb2222/scene.radium"


def _row(path, original, replacement="", budget=None, grow=False,
         unused=False, fixed=False):
    r = {"path": path, "original": original, "replacement": replacement}
    if budget:
        r["budget"] = budget
    if grow:
        r["grow"] = True
    if fixed:
        r["fixed"] = True
    if unused:
        r["unused"] = True
    return r


def _wait(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.02)
    return pred()


def _load(w, assets, rows):
    tm.save(assets, rows)

    def _set():
        try:
            w.window.write_assets_var.set(assets)
        except Exception:                            # noqa: BLE001
            pass
    w.run(_set)
    w.call("ui.select_tab", "text")
    svc = w.window.service("text")
    assert _wait(w, lambda: not w.state("text")["scanning"]
                 and svc._text_scan_dir == assets
                 and len(svc._text_rows) == len(rows))
    return svc


def _select(w, svc, original):
    i = next(i for i, r in enumerate(svc._text_rows)
             if r["original"] == original)
    assert w.call("text.select", i) is True
    return i


def _list_row(w, original):
    return next(r for r in w.state("text")["rows"] if r["o"] == original)


def _type(w, new):
    w.call("ui.set", "text", "new", new)
    w.drain()
    return w.state("text")


# ---------------------------------------------------------------------------
# The rules
# ---------------------------------------------------------------------------

def test_grow_and_unused_flags_round_trip_in_the_manifest(tmp_path):
    """The 5th column carries the flags; a radium row and a 4-column manifest
    never see them, and an old reader that splits cols[0..3] is unaffected."""
    rows = [
        _row(SCENE, "TILT"),
        _row(GAME, "GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE", 96,
             grow=True),
        _row(GAME, "GEORGE GOMEZ", budget=12, unused=True),
        _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=28),
    ]
    tm.save(str(tmp_path), rows)
    text = (tmp_path / "text" / "strings.tsv").read_text(encoding="utf-8")
    lines = [ln for ln in text.splitlines() if not ln.startswith("#")]
    assert lines[1].split("\t")[4] == "grows"
    assert lines[2].split("\t")[4] == "unused"
    assert len(lines[0].split("\t")) == 3          # radium: no budget, no flags
    assert len(lines[3].split("\t")) == 4          # budget only
    back = tm.load(str(tmp_path))
    assert back[1].get("grow") is True and back[1]["budget"] == 96
    assert back[2].get("unused") is True and "grow" not in back[2]
    assert "grow" not in back[0] and "grow" not in back[3]
    assert tm.changed(str(tmp_path)) == {
        GAME: [("GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE")]}
    # An older 4-column manifest loads with neither flag.
    (tmp_path / "text" / "strings.tsv").write_text(
        "%s\tEBIRAH\t\t96\n" % GAME, encoding="utf-8")
    old = tm.load(str(tmp_path))
    assert old[0]["budget"] == 96 and "grow" not in old[0]


def test_max_label_budget_and_outgrows_are_tk_free():
    grow = _row(GAME, "GODZILLA VS EBIRAH", budget=96, grow=True)
    fixed = _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=28,
                 fixed=True)
    scene = _row(SCENE, "TILT")
    assert R.row_budget(grow) == 96
    assert R.row_max_label(grow) == "96 (grows)"
    assert R.row_max_label(fixed) == "28"
    # A scene row grows too (Write rewrites the scene at the new length):
    # its Max is the 96-byte line cap, or its own length when that is longer.
    assert R.row_max_label(scene) == "96 (grows)"
    assert R.row_budget(scene) == 96
    assert R.row_grows(scene) and not R.row_grows(fixed)
    assert R.row_budget(_row(SCENE, "X" * 120)) == 120
    assert R.row_outgrows(scene, "TILT!")
    assert "longest a line can be is 96" in R.too_long_message(
        scene, "T" * 97)
    assert "can't move" in R.too_long_message(fixed, "X" * 29)
    assert R.row_outgrows(grow, "GODZILLA VS BIOLLANTE")
    assert not R.row_outgrows(grow, "GODZILLA VS GIGAN!")
    # \n is one byte on a budgeted row
    two = _row(GAME, "GODZILLA\\nVS. EBIRAH", budget=96, grow=True)
    assert R.row_len(two, "GODZILLA\\nVS. EBIRAH") == 19
    assert "not used" in R.program_note(
        _row(GAME, "GEORGE GOMEZ", budget=12, unused=True))
    assert "new area of the game program" in R.program_note(grow)
    assert "edit both rows" in R.program_note(fixed)


def test_replace_plan_scopes_on_originals_and_reports_fits():
    rows = [
        _row(GAME, "GODZILLA VS EBIRAH", budget=96, grow=True),
        _row(GAME, "EBIRAH", budget=96, grow=True),
        _row(GAME, "BATTLE VS EBIRAH SHOT TIMER", budget=96, grow=True),
        _row(SCENE, "EBIRAH RULES"),                     # scene: grows
        _row(SCENE, "Ebirah wins", "EBIRAH!"),           # edited, lower-case
        _row(GAME, "TILT", budget=4, fixed=True),
        _row(GAME, "EBIRAH!", budget=7, fixed=True),      # fixed slot
    ]
    plan = R.replace_plan(rows, "EBIRAH", "BIOLLANTE")
    assert [p["index"] for p in plan] == [0, 1, 2, 3, 6]
    assert [p["new"] for p in plan] == [
        "GODZILLA VS BIOLLANTE", "BIOLLANTE", "BATTLE VS BIOLLANTE SHOT TIMER",
        "BIOLLANTE RULES", "BIOLLANTE!"]
    assert [p["fits"] for p in plan] == [True, True, True, True, False]
    # Match case off reaches the lower-case original too — matched on the
    # ORIGINAL, never the edit — and keeps the rest of the string intact.
    loose = R.replace_plan(rows, "ebirah", "BIOLLANTE", match_case=False)
    assert [p["index"] for p in loose] == [0, 1, 2, 3, 4, 6]
    assert loose[4]["new"] == "BIOLLANTE wins"
    assert loose[4]["fits"] is True                # a scene row grows
    assert loose[5]["fits"] is False               # 10 bytes in a 7 slot
    assert R.replace_plan(rows, "", "X") == []
    # every occurrence in a line is replaced
    assert R.replace_plan(
        [_row(GAME, "EBIRAH VS EBIRAH", budget=96, grow=True)],
        "EBIRAH", "GIGAN")[0]["new"] == "GIGAN VS GIGAN"


def test_split_edit_finds_the_one_changed_word():
    assert R.split_edit("GODZILLA VS EBIRAH STARTED",
                        "GODZILLA VS BIOLLANTE STARTED") == (
        "EBIRAH", "BIOLLANTE")
    assert R.split_edit("MEGALON", "SPACE GODZILLA") == (
        "MEGALON", "SPACE GODZILLA")
    assert R.split_edit("EBIRAH", "EBIRAH") is None
    assert R.split_edit("", "X") is None
    assert R.split_edit("AB", "AXB") is None         # pure insertion


def test_pending_text_status_names_the_grow_path():
    longer = _row(GAME, "GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE", 96,
                  grow=True)
    same = _row(GAME, "TILT", "TOLT", 96, grow=True)
    fixed = _row(GAME, "EBIRAH", "GIGAN!", 18, fixed=True)
    assert R.pending_text_status(longer) == R.PENDING_TEXT_GROWS
    assert R.pending_text_status(longer, grow_on=False) == \
        R.PENDING_TEXT_GROW_OFF
    assert R.pending_text_status(same) == R.PENDING_TEXT
    assert R.pending_text_status(fixed) == R.PENDING_TEXT
    # a scene row: longer = the scene is rewritten; same length = in place
    scene_longer = _row(SCENE, "TILT", "TILT WARNING")
    scene_same = _row(SCENE, "REPLAY", "SAVED!")
    assert R.pending_text_status(scene_longer) == R.PENDING_TEXT_GROWS_SCENE
    assert R.pending_text_status(scene_longer, grow_on=False) == \
        R.PENDING_TEXT_GROW_OFF
    assert R.pending_text_status(scene_same) == R.PENDING_TEXT


# ---------------------------------------------------------------------------
# The tabs
# ---------------------------------------------------------------------------

def test_apply_accepts_35_bytes_on_a_96_row_and_refuses_97(tmp_path):
    assets = str(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets, [
            _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=96,
                 grow=True)])
        _select(w, svc, "BATTLE VS MEGALON SHOT TIMER")
        assert _list_row(w, "BATTLE VS MEGALON SHOT TIMER")["mx"] == \
            "96 (grows)"
        assert "can grow" in w.state("text")["scene_note"]

        new = "BATTLE VS SPACE GODZILLA SHOT TIMER"
        assert len(new) == 35
        st = _type(w, new)
        assert st["budget"].startswith("35 / 96 bytes")
        assert "new area of the game program" in st["budget"]
        assert "too long" not in st["budget"]
        assert st["budget_over"] is False
        assert w.call("text.apply") is True
        assert tm.changed(assets) == {
            GAME: [("BATTLE VS MEGALON SHOT TIMER", new)]}
        assert _list_row(w, "BATTLE VS MEGALON SHOT TIMER")["n"] == new

        st = _type(w, "X" * 97)
        assert "too long" in st["budget"]
        assert st["budget_over"] is True
        assert w.call("text.apply") is False
        warned = w.asked[-1]
        assert warned["icon"] == "warning"
        assert "96" in warned["message"]
        assert "longest a line" in warned["message"]
        assert tm.changed(assets) == {
            GAME: [("BATTLE VS MEGALON SHOT TIMER", new)]}   # unchanged


def test_apply_refuses_30_bytes_on_a_28_byte_row_that_cannot_grow(tmp_path):
    assets = str(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets, [
            _row(GAME, "BATTLE VS MEGALON SHOT TIMER", budget=28,
                 fixed=True)])
        _select(w, svc, "BATTLE VS MEGALON SHOT TIMER")
        assert _list_row(w, "BATTLE VS MEGALON SHOT TIMER")["mx"] == "28"
        assert "can grow" not in w.state("text")["scene_note"]
        st = _type(w, "BATTLE VS BIOLLANTE SHOT TIMER")     # 30 bytes
        assert st["budget"].startswith("30 / 28 bytes")
        assert "too long" in st["budget"]
        assert st["budget_over"] is True
        assert w.call("text.apply") is False
        msg = w.asked[-1]["message"]
        assert "only 28 fit" in msg
        assert "patched in place" in msg
        assert tm.changed(assets) == {}


def test_unused_row_says_so(tmp_path):
    assets = str(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets, [_row(GAME, "GEORGE GOMEZ", budget=12,
                                     unused=True)])
        _select(w, svc, "GEORGE GOMEZ")
        st = w.state("text")
        assert "(not used by the game)" in st["scene_note"]
        assert "(not used by the game)" in st["budget"]


def test_replace_everywhere_updates_three_rows_and_skips_one(tmp_path):
    assets = str(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets, [
            _row(GAME, "GODZILLA VS EBIRAH", budget=96, grow=True),
            _row(GAME, "EBIRAH", budget=96, grow=True),
            _row(GAME, "BATTLE VS EBIRAH SHOT TIMER", budget=96, grow=True),
            _row(SCENE, "EBIRAH RULES"),                    # scene: grows
            _row(SCENE, "TILT"),
            _row(GAME, "EBIRAH!", budget=7, fixed=True),    # fixed 7-byte slot
        ])
        write = w.window.service("write")
        fp_before = w.run(write._fingerprint)
        # Opened from a row whose New text changed one word: Find / Replace
        # are pre-filled with that word.
        _select(w, svc, "GODZILLA VS EBIRAH")
        _type(w, "GODZILLA VS BIOLLANTE")
        pre = w.call("text.replace_open")
        assert pre == {"find": "EBIRAH", "repl": "BIOLLANTE"}
        plan = w.call("text.replace_plan", pre["find"], pre["repl"], True)
        assert plan["text"].startswith("4 of 5 matching rows fit")
        assert plan["can_apply"] is True
        assert len(plan["misfits"]) == 1
        assert plan["misfits"][0]["o"] == "EBIRAH!"
        assert plan["misfits"][0]["n"] == "BIOLLANTE!"

        n_asked = len(w.asked)
        res = w.call("text.replace_apply", "EBIRAH", "BIOLLANTE", True)
        assert res == {"applied": 4, "skipped": 1}
        assert tm.changed(assets) == {
            GAME: [
                ("GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE"),
                ("EBIRAH", "BIOLLANTE"),
                ("BATTLE VS EBIRAH SHOT TIMER",
                 "BATTLE VS BIOLLANTE SHOT TIMER")],
            SCENE: [("EBIRAH RULES", "BIOLLANTE RULES")]}
        told = [a["message"] for a in w.asked[n_asked:]]
        assert told and "4 row(s) changed" in told[0]
        assert "EBIRAH!" in told[0] and "Max 7" in told[0]
        assert w.run(write._fingerprint) != fp_before
        # the list shows the new text on every changed row
        assert _list_row(w, "EBIRAH")["n"] == "BIOLLANTE"
        assert _list_row(w, "EBIRAH RULES")["n"] == "BIOLLANTE RULES"
        assert _list_row(w, "EBIRAH!")["n"] == ""

        # A word nothing matches plans nothing; an empty Find is not a search.
        plan = w.call("text.replace_plan", "MOTHRA", "X", True)
        assert plan["text"].startswith("0 of 0")
        assert plan["can_apply"] is False
        assert w.call("text.replace_apply", "MOTHRA", "X", True) is None


def test_grow_setting_round_trips_and_lands_in_the_environment(tmp_path,
                                                               monkeypatch):
    import pinball_decryptor.app as app_mod
    monkeypatch.setenv("PAD_STERN_TEXT_GROW", os.environ.get(
        "PAD_STERN_TEXT_GROW", "1"))
    with web_app(tmp_path, mfr="stern") as w:
        app, win = w.app, w.window
        # default on, mirrored at startup
        assert win.write_text_grow_var.get() is True
        assert win.text_grow_enabled() is True
        assert os.environ["PAD_STERN_TEXT_GROW"] == "1"

        w.call("ui.set", "write", "text_grow", False)
        w.drain()
        assert app._settings["text_grow"] is False
        assert os.environ["PAD_STERN_TEXT_GROW"] == "0"
        with open(app_mod.SETTINGS_FILE, encoding="utf-8") as f:
            assert json.load(f)["text_grow"] is False
        assert app._text_grow_setting() is False

        w.call("ui.set", "write", "text_grow", True)
        w.drain()
        assert os.environ["PAD_STERN_TEXT_GROW"] == "1"
        with open(app_mod.SETTINGS_FILE, encoding="utf-8") as f:
            assert json.load(f)["text_grow"] is True
        # a settings file that never saw the key reads as on
        app._settings.pop("text_grow", None)
        assert app._text_grow_setting() is True


def test_write_tab_pending_row_says_the_game_program_grows(tmp_path):
    assets = str(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("write")["text_grow_cap"] is True
        _load(w, assets, [
            _row(GAME, "GODZILLA VS EBIRAH", "GODZILLA VS BIOLLANTE", 96,
                 grow=True),
            _row(GAME, "TILT", "TOLT", 96, grow=True),
            _row(SCENE, "REPLAY", "SAVED!"),
            _row(SCENE, "GAME OVER", "GAME OVER, MAN"),  # longer: scene grows
        ])
        write = w.window.service("write")
        w.call("ui.set", "write", "text_grow", True)
        w.run(write._refresh_pending_text_rows)

        def _text_rows():
            return [(rel, status) for rel, ext, status, _tag in write._rows
                    if ext == "text"]
        rows = _text_rows()
        assert len(rows) == 4
        by_status = {}
        for rel, status in rows:
            by_status.setdefault(status, []).append(rel)
        assert by_status[R.PENDING_TEXT_GROWS] == [
            "GODZILLA VS EBIRAH  →  GODZILLA VS BIOLLANTE"]
        assert by_status[R.PENDING_TEXT_GROWS_SCENE] == [
            "GAME OVER  →  GAME OVER, MAN"]
        assert sorted(by_status[R.PENDING_TEXT]) == [
            "REPLAY  →  SAVED!", "TILT  →  TOLT"]

        # Advanced off: the over-long edits are listed as skipped, the rest
        # stay
        w.call("ui.set", "write", "text_grow", False)
        w.drain()
        statuses = sorted(s for _r, s in _text_rows())
        assert statuses == sorted([R.PENDING_TEXT, R.PENDING_TEXT,
                                   R.PENDING_TEXT_GROW_OFF,
                                   R.PENDING_TEXT_GROW_OFF])
        w.call("ui.set", "write", "text_grow", True)
        w.drain()
        assert R.PENDING_TEXT_GROWS in [s for _r, s in _text_rows()]


def test_a_program_row_from_an_older_project_still_takes_longer_text(
        tmp_path):
    """David, 2026-09-07, on a project extracted by an older build: "on the
    text tab, it still shows too long in red".

    Its manifest carries every game-program string's ORIGINAL length as the
    budget and no flags at all, which used to read as "this line cannot
    move" — so the tab refused text the Write step would have placed.  No
    flag now means nobody has measured yet: the row offers the 96-byte line
    cap, and Write checks the string against the card."""
    assets = str(tmp_path / "proj")
    with web_app(tmp_path, mfr="stern") as w:
        svc = _load(w, assets, [_row(GAME, "BATTLE VS SPACE G TIMER",
                                     budget=23)])
        _select(w, svc, "BATTLE VS SPACE G TIMER")
        assert _list_row(w, "BATTLE VS SPACE G TIMER")["mx"] == "96 (grows)"
        note = w.state("text")["scene_note"]
        assert "can grow" in note and "checked against the card" in note
        st = _type(w, "BATTLE VS SPACE GODZILLA TIMER")        # 30 bytes
        assert st["budget"].startswith("30 / 96 bytes")
        assert "too long" not in st["budget"]
        assert st["budget_over"] is False
        assert w.call("text.apply") is True
        assert tm.changed(assets) == {
            GAME: [("BATTLE VS SPACE G TIMER",
                    "BATTLE VS SPACE GODZILLA TIMER")]}


def test_an_unflagged_row_grows_but_a_scanned_fixed_one_does_not():
    """The rules twin of the above, and the line it must not blur: a row the
    scan measured and found immovable carries ``fixed`` and keeps its slot."""
    old = _row(GAME, "BATTLE VS SPACE G TIMER", budget=23)
    scanned = _row(GAME, "BATTLE VS SPACE G TIMER", budget=23, fixed=True)
    assert R.row_grows(old) and R.row_budget(old) == 96
    assert R.row_max_label(old) == "96 (grows)"
    assert not R.row_grows(scanned)
    assert R.row_budget(scanned) == 23
    assert R.row_max_label(scanned) == "23"
    # and the fixed flag survives a manifest round trip
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tm.save(d, [scanned])
        assert tm.load(d)[0].get("fixed") is True
