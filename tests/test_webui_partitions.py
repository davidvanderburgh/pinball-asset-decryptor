"""The web UI's Partitions (Tk "Partition Explorer") and Compare tabs.

Driven through the in-process harness exactly as the page drives them: the
``@rpc`` calls run on the UI loop, modals and file pickers are answered from
``w.answers``.  The card is the tiny synthetic image from tests/_ext4_fake.py
(no real card is ever opened or written), and the replace journal is pointed
at the test's own folder.
"""

import os
import threading
import time

import pytest

from tests._ext4_fake import (FakeExt4Reader, install_fake_reader,
                              materialize_files, write_fake_card)
from tests.webui_harness import web_app


@pytest.fixture(autouse=True)
def _journal(tmp_path, monkeypatch):
    from pinball_decryptor.core import card_edits
    monkeypatch.setattr(card_edits, "CARD_EDITS_FILE",
                        str(tmp_path / "card_edits.json"))


@pytest.fixture
def card(tmp_path, monkeypatch):
    install_fake_reader(monkeypatch)
    return write_fake_card(tmp_path / "card.raw")


def _svc(w, ns):
    return w.window.service(ns)


def _wait(w, cond, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if w.run(cond):
            return
        time.sleep(0.02)
    raise AssertionError("condition never came true")


def _names(rows):
    return [r["name"] for r in rows]


# ---------------------------------------------------------------- gating
@pytest.mark.parametrize("mfr,era,visible", [
    ("stern", "", True), ("stern", "spike1", False),
    ("stern", "whitestar", False), ("jjp", "", False), ("spooky", "", False),
    ("williams", "", False)])
def test_tabs_follow_the_capabilities(tmp_path, mfr, era, visible):
    with web_app(tmp_path, mfr=mfr, era=era or None) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["partitions"]["visible"] is visible
        assert tabs["compare"]["visible"] is visible
        # nothing open, nothing enabled, the report empty
        p = w.state("partitions")
        assert p["rows"] == [] and p["parts"] == [] and not p["can_part"]
        assert not p["can_find"] and not p["can_all"] and p["busy"] is None
        c = w.state("compare")
        assert c["rows"] == [] and not c["has_report"] and not c["running"]
        assert c["limit"] == "50"


def test_exports_are_the_window_s(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        for name in ("compare_a_var", "compare_b_var", "compare_limit_var",
                     "partition_image_var", "partition_show_var"):
            assert hasattr(getattr(win, name), "get"), name
        assert callable(win._asset_find_in_partition)
        assert not (getattr(win, "missing_exports", None) or {}).get(
            "compare_a_var")


def test_saved_row_limit_is_restored(tmp_path):
    with web_app(tmp_path, mfr="stern",
                 settings={"compare_row_limit": "all"}) as w:
        assert w.window.compare_limit_var.get() == "All"
    with web_app(tmp_path / "2", mfr="stern",
                 settings={"compare_row_limit": "999"}) as w:
        assert w.window.compare_limit_var.get() == "50"


# ------------------------------------------------------ open + browse
def test_open_lists_partitions_and_the_root(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("partitions.open_image", card) is True
        s = w.state("partitions")
        labels = [p["label"] for p in s["parts"]]
        assert any(l.startswith("sda2 — Linux (ext4)")
                   and "not browsable" not in l for l in labels)
        assert sum("not browsable" in l for l in labels) == 3
        assert s["part"].startswith("sda2")
        assert _names(s["rows"]) == ["etc", "spk", "zeta", "game",
                                     "readme.txt"]
        game = next(r for r in s["rows"] if r["name"] == "game")
        assert game["type"].startswith("symlink → ")
        assert s["can_part"] and s["can_find"] and s["can_all"]
        # the open joined the recent-paths history
        assert w.window.path_history("partition_image") == [
            os.path.normpath(card)]
        assert s["history"] == [os.path.normpath(card)]
        logs = [e["text"] for e in w.window.log_history()]
        assert any("Opened %s" % card in t and "partitions." in t
                   for t in logs)


def test_open_failures_say_why(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        missing = str(tmp_path / "nope.raw")
        assert w.call("partitions.open_image", missing) is False
        assert w.asked[-1]["title"] == "File not found"
        junk = tmp_path / "junk.raw"
        junk.write_bytes(b"not a card")
        w.call("partitions.open_image", str(junk))
        assert w.asked[-1]["title"] in ("Not a card image",
                                        "Nothing to browse")


def test_expand_select_preview(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("partitions.open_image", card)
        w.call("partitions.toggle", "/etc")
        rows = w.state("partitions")["rows"]
        assert _names(rows)[:2] == ["etc", "init.d"]
        assert rows[1]["depth"] == 1 and rows[0]["open"]
        w.call("partitions.select", "/readme.txt")
        s = w.state("partitions")
        assert s["sel"] == "/readme.txt" and not s["sel_dir"]
        assert s["preview"]["kind"] == "text"
        assert s["preview"]["text"] == "hello world"
        w.call("partitions.select", "/etc")
        assert w.state("partitions")["preview"] is None
        w.call("partitions.toggle", "/etc")            # collapse
        assert "init.d" not in _names(w.state("partitions")["rows"])


def test_binary_preview_placeholder():
    from pinball_decryptor.webui.tabs.partitions import decode_preview, human
    assert decode_preview(b"\x00\x01\x02" * 50).startswith(
        "(binary file — 150 bytes")
    assert decode_preview(b"hi\n") == "hi\n"
    assert human(0) == "0 B" and human(1536) == "1.5 KB"
    assert human(6 * 1024 ** 3) == "6.0 GB"


def test_non_browsable_partition(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("partitions.open_image", card)
        fat = next(p["value"] for p in w.state("partitions")["parts"]
                   if p["value"].startswith("sda1"))
        w.call("partitions.select_partition", fat)
        s = w.state("partitions")
        assert s["rows"] == [] and not s["can_part"]
        assert s["status"] == \
            "This partition isn't a browsable ext filesystem."


def test_find_next_reveals_and_reports_misses(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("partitions.open_image", card)
        assert w.call("partitions.find_next", "game") == "/etc/init.d/game"
        s = w.state("partitions")
        assert s["sel"] == "/etc/init.d/game"
        assert next(r for r in s["rows"] if r["id"] == "/etc")["open"]
        assert w.call("partitions.find_next", "zzz-nope") is False
        assert w.state("partitions")["status"] == \
            "No file path contains “zzz-nope”."


def test_default_from_extract_on_show(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(lambda: w.window.extract_input_var.set(card))
        w.call("ui.select_tab", "partitions")
        assert w.window.partition_image_var.get() == os.path.normpath(card)
        assert w.state("partitions")["parts"]
    # a path the user typed is never overridden
    with web_app(tmp_path / "2", mfr="stern") as w:
        w.call("ui.set", "partitions", "image", "typed.raw")
        w.run(lambda: w.window.extract_input_var.set(card))
        w.call("ui.select_tab", "partitions")
        assert w.window.partition_image_var.get() == "typed.raw"
        assert w.state("partitions")["parts"] == []


def test_browse_opens_the_pick(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.answers.append(card)
        assert w.call("partitions.browse") == os.path.normpath(card)
        spec = w.asked[-1]
        assert spec["title"] == "Select a card image"
        assert spec["filetypes"][0] == ["Card image", "*.raw *.img *.bin"]
        assert w.state("partitions")["rows"]
        w.answers.append("")                       # cancelled: nothing
        assert not w.call("partitions.browse")


# ------------------------------------------------------------- extract
def test_extract_file_and_partition(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, "partitions")
        w.call("partitions.open_image", card)
        out = tmp_path / "out.txt"
        w.call("partitions.select", "/readme.txt")
        w.answers.append(str(out))
        assert w.call("partitions.extract_selected") is True
        _wait(w, lambda: not svc._busy)
        assert out.read_bytes() == b"hello world"
        s = w.state("partitions")
        assert s["status"] == "Extracted out.txt (11 B)."
        assert s["busy"] is None and s["busy_btn"] is None

        dump = tmp_path / "dump"
        dump.mkdir()
        w.answers.append(str(dump))
        assert w.call("partitions.extract_partition") is True
        _wait(w, lambda: not svc._busy)
        assert (dump / "sda2" / "zeta" / "b.bin").read_bytes() == b"BBBB"
        assert w.state("partitions")["status"].startswith("Extracted ")
        assert w.asked[-1]["title"] == \
            "Choose a folder to extract the whole partition into"

        every = tmp_path / "every"
        every.mkdir()
        w.answers.append(str(every))
        assert w.call("partitions.extract_all") is True
        _wait(w, lambda: not svc._busy)
        assert (every / "sda2" / "readme.txt").exists()
        assert w.state("partitions")["status"].startswith(
            "Extracted 1 partition — ")


def test_extract_cancel(tmp_path, card, monkeypatch):
    gate = threading.Event()
    orig = FakeExt4Reader.extract_file

    def gated(self, node, out_path, progress=None):
        assert gate.wait(10)
        return orig(self, node, out_path, progress=progress)

    monkeypatch.setattr(FakeExt4Reader, "extract_file", gated)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, "partitions")
        w.call("partitions.open_image", card)
        dump = tmp_path / "dump"
        dump.mkdir()
        w.answers.append(str(dump))
        w.call("partitions.extract_partition")
        s = w.state("partitions")
        assert s["busy_btn"] == "part" and s["busy"]["kind"] == "extract"
        assert s["busy"]["text"].startswith("Extracting…")
        # while busy: another image is refused, the partition snaps back
        assert w.call("partitions.open_image") is False
        assert w.asked[-1]["title"] == "Extract in progress"
        assert w.call("partitions.select_partition", "whatever") is False
        assert w.call("partitions.cancel_extract") is True
        assert w.state("partitions")["cancelling"] is True
        gate.set()
        _wait(w, lambda: not svc._busy)
        assert w.state("partitions")["status"] == \
            "Extract cancelled — partial files may remain."
        assert w.state("partitions")["can_part"]


def test_tree_stays_live_while_an_extract_runs(tmp_path, card, monkeypatch):
    """Tk left the tree usable mid-extract (only a spinner label sat in the
    middle of it): select + preview, expand, Find Next, Properties and Copy
    path all work, and Show rebuilds the tree while the extract carries on."""
    gate = threading.Event()
    orig = FakeExt4Reader.extract_file

    def gated(self, node, out_path, progress=None):
        assert gate.wait(10)
        return orig(self, node, out_path, progress=progress)

    monkeypatch.setattr(FakeExt4Reader, "extract_file", gated)
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, "partitions")
        w.call("partitions.open_image", card)
        dump = tmp_path / "dump"
        dump.mkdir()
        w.answers.append(str(dump))
        w.call("partitions.extract_partition")
        try:
            assert svc._busy and w.state("partitions")["busy_btn"] == "part"
            # select + preview
            assert w.call("partitions.select", "/readme.txt") is True
            s = w.state("partitions")
            assert s["sel"] == "/readme.txt"
            assert s["preview"]["text"] == "hello world"
            # expand a folder
            assert w.call("partitions.toggle", "/zeta") is True
            assert "/zeta/a.bin" in [r["id"] for r in
                                     w.state("partitions")["rows"]]
            # Find Next (Tk's button had no busy check)
            assert w.call("partitions.find_next", "init.d/game") == \
                "/etc/init.d/game"
            assert w.state("partitions")["sel"] == "/etc/init.d/game"
            # Properties… and Copy path (kept in the busy context menu)
            w.call("partitions.properties", "/zeta")
            _wait(w, lambda: w.state("partitions")["props"] is not None)
            assert dict(w.state("partitions")["props"]["rows"])["Size:"] \
                == "6 B in 2 files"
            w.call("partitions.close_props")
            w.call("partitions.copy_path", "/zeta/b.bin")
            assert w.app.root._clip == "/zeta/b.bin"
            # Show rebuilds the view; a Find drops it back to All
            w.call("partitions.set_show", "Changed")
            s = w.state("partitions")
            assert s["rows"] == [] and s["status"].startswith(
                "Nothing replaced on this partition yet")
            assert w.call("partitions.find_next", "readme") == "/readme.txt"
            s = w.state("partitions")
            assert s["show"] == "All" and s["sel"] == "/readme.txt"
            assert "etc" in _names(s["rows"])
            # ...and none of it touched the run: still busy, same button
            assert svc._busy and s["busy_btn"] == "part"
            assert s["busy"]["kind"] == "extract"
            # the other extracts stay refused until it ends
            assert w.call("partitions.extract_all") is False
        finally:
            gate.set()
        _wait(w, lambda: not svc._busy)
        assert (dump / "sda2" / "readme.txt").read_bytes() == b"hello world"
        assert w.state("partitions")["status"].startswith("Extracted ")


def test_show_waits_for_a_replace_then_applies(tmp_path, card, monkeypatch):
    """Mid-Replace the tree is not rebuilt (the image is re-opened, with the
    Show choice, the moment the write ends)."""
    from pinball_decryptor.plugins.stern.explorer import CardImage
    materialize_files(card)
    gate = threading.Event()
    orig = CardImage.replace_file

    def gated(self, *a, **k):
        assert gate.wait(10)
        return orig(self, *a, **k)

    monkeypatch.setattr(CardImage, "replace_file", gated)
    src = tmp_path / "new_game.sh"
    src.write_bytes(b"#!/bin/sh\necho HI\n")            # same size
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, "partitions")
        w.call("partitions.open_image", card)
        before = [r["id"] for r in w.state("partitions")["rows"]]
        w.answers.extend([str(src), "yes"])
        try:
            assert w.call("partitions.replace", "/etc/init.d/game") is True
            assert svc._busy_kind == "replace"
            w.call("partitions.set_show", "Changed")
            s = w.state("partitions")
            assert s["show"] == "Changed"
            assert [r["id"] for r in s["rows"]] == before
        finally:
            gate.set()
        _wait(w, lambda: not svc._busy)
        _wait(w, lambda: [r["id"] for r in w.state("partitions")["rows"]]
              == ["/etc", "/etc/init.d", "/etc/init.d/game"])


def test_dragged_column_widths_last_the_session(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.state("partitions")["widths"] is None
        assert w.call("partitions.set_widths",
                      {"name": 312.4, "size": 90, "type": 260,
                       "changed": 99, "bogus": 50, "tiny": 3}) is True
        assert w.state("partitions")["widths"] == {
            "name": 312, "size": 90, "type": 260}
        assert w.call("partitions.set_widths", {"name": 5}) is False
        assert w.state("partitions")["widths"] is None
        assert w.call("compare.set_widths", {"change": 280.6}) is True
        assert w.state("compare")["widths"] == {"change": 280}
        # session only, as the Tk trees were: nothing saved
        saved = w.app._settings.get("column_widths") or {}
        assert "partitions" not in saved and "compare" not in saved


def test_busy_pill_and_changed_rows_look():
    """Browser-only details the Python side cannot see: the busy pill lets
    clicks through to the tree, and a replaced file's whole row is drawn in
    the warning colour (Tk tag pex_changed coloured every cell)."""
    import pathlib
    import re
    css = (pathlib.Path(__file__).resolve().parents[1] / "pinball_decryptor"
           / "webui" / "static" / "css" / "tabs"
           / "partitions.css").read_text(encoding="utf-8")
    busy = re.search(r"\.pex-busy\s*\{([^}]*)\}", css).group(1)
    assert "pointer-events: none" in busy
    assert re.search(r"\.tbl \.pex-row-changed \.c\b[^{]*\{[^}]*"
                     r"var\(--warn\)", css)
    # "not on the card now" stays red, so its rule comes after
    assert css.index(".pex-row-missing .pex-type") > css.index(
        ".pex-row-changed .c")


# ---------------------------------------------------------- properties
def test_properties_of_a_file_and_a_folder(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("partitions.open_image", card)
        w.call("partitions.properties", "/readme.txt")
        props = w.state("partitions")["props"]
        rows = dict(props["rows"])
        assert props["title"] == "Properties — readme.txt"
        assert rows["Kind:"] == "file" and rows["Size:"] == "11 B"
        assert rows["Partition:"] == "sda2"
        assert rows["Path:"] == "/readme.txt"
        assert rows["Mounted at:"] == "<mount point>/readme.txt"
        w.call("partitions.close_props")
        assert w.state("partitions")["props"] is None
        w.call("partitions.properties", "/zeta")
        _wait(w, lambda: w.state("partitions")["props"] is not None)
        rows = dict(w.state("partitions")["props"]["rows"])
        assert rows["Kind:"] == "Folder" and rows["Size:"] == "6 B in 2 files"


def test_copy_path_reaches_the_clipboard(tmp_path, card):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("partitions.open_image", card)
        w.call("partitions.copy_path", "/readme.txt")
        assert w.app.root._clip == "/readme.txt"


# ------------------------------------------------------------- replace
def test_replace_same_size_journals_and_marks(tmp_path, card):
    placed = materialize_files(card)
    src = tmp_path / "new_game.sh"
    src.write_bytes(b"#!/bin/sh\necho HI\n")            # 18 bytes, same
    with web_app(tmp_path, mfr="stern") as w:
        svc = _svc(w, "partitions")
        w.call("partitions.open_image", card)
        w.answers.extend([str(src), "yes"])
        assert w.call("partitions.replace", "/etc/init.d/game") is True
        confirm = w.asked[-1]
        assert confirm["title"] == "Replace on card"
        assert "This WRITES to the card image" in confirm["message"]
        assert confirm["icon"] == "warning"
        _wait(w, lambda: not svc._busy)
        off, _old = placed["/etc/init.d/game"]
        with open(card, "rb") as f:
            f.seek(off)
            assert f.read(18) == b"#!/bin/sh\necho HI\n"
        s = w.state("partitions")
        assert s["status"].startswith("Replaced /etc/init.d/game (18 B)")

        # the journal drives Changed / Show filters / Properties
        w.call("partitions.set_show", "Changed")
        rows = w.state("partitions")["rows"]
        assert [r["id"] for r in rows] == ["/etc", "/etc/init.d",
                                           "/etc/init.d/game"]
        assert rows[-1]["changed"].startswith("replaced ")
        assert w.state("partitions")["status"] == \
            "1 file replaced on this partition."
        w.call("partitions.set_show", "Unchanged")
        w.call("partitions.toggle", "/etc")
        w.call("partitions.toggle", "/etc/init.d")
        ids = [r["id"] for r in w.state("partitions")["rows"]]
        assert "/etc/init.d" in ids and "/etc/init.d/game" not in ids
        w.call("partitions.set_show", "All")
        w.call("partitions.properties", "/readme.txt")
        assert w.state("partitions")["props"]["replaced"] == []
        w.call("partitions.find_next", "init.d/game")
        w.call("partitions.properties", "/etc/init.d/game")
        hist = w.state("partitions")["props"]["replaced"]
        assert len(hist) == 1 and hist[0]["source"] == str(src)


def test_replace_declined_writes_nothing(tmp_path, card):
    placed = materialize_files(card)
    src = tmp_path / "longer.sh"
    src.write_bytes(b"#!/bin/sh\n# a much longer boot script\n")
    with web_app(tmp_path, mfr="stern") as w:
        w.call("partitions.open_image", card)
        w.answers.extend([str(src), "no"])
        assert w.call("partitions.replace", "/etc/init.d/game") is False
        msg = w.asked[-1]["message"]
        assert "different size" in msg and "WSL2" in msg and "grown" in msg
        off, old = placed["/etc/init.d/game"]
        with open(card, "rb") as f:
            f.seek(off)
            assert f.read(len(old)) == old
        # folders are never replaced
        assert w.call("partitions.replace", "/etc") is False


def test_find_in_partition_from_a_replace_tab(tmp_path, card, monkeypatch):
    from pinball_decryptor.core import card_paths
    monkeypatch.setattr(card_paths, "video_card_path",
                        lambda d, rel: ("/zeta/b.bin", "the clip's file"))
    with web_app(tmp_path, mfr="stern") as w:
        # no image open and no Extract input: asks for one
        assert w.run(lambda: w.window._asset_find_in_partition(
            "video", "x.mp4", str(tmp_path))) is False
        assert "Pick the card image" in w.asked[-1]["message"]
        w.call("partitions.open_image", card)
        assert w.run(lambda: w.window._asset_find_in_partition(
            "video", "x.mp4", str(tmp_path))) == "/zeta/b.bin"
        s = w.state("partitions")
        assert s["sel"] == "/zeta/b.bin" and s["status"] == "the clip's file"
        assert w.state("shell")["tab"] == "partitions"


# ------------------------------------------------------------- compare
def _cards(tmp_path):
    a = tmp_path / "cards" / "led_zeppelin_le-1_21_0.raw"
    b = tmp_path / "cards" / "led_zeppelin_le-1_22_0.raw"
    a.parent.mkdir(parents=True, exist_ok=True)
    a.write_bytes(b"A" * 4096)
    b.write_bytes(b"B" * 2048)
    return str(a), str(b)


REPORT = [
    ("Compared", [("Image A", "led_zeppelin_le-1_21_0.raw — 4.0 KB"),
                  ("Version", "1.21.0 -> 1.22.0")]),
    ("Images", [("Modified", "60:")] + [
        ("", "gfx/%02d.png — content changed (1.0 KB)" % i,
         {"side": "B", "part": 2, "path": "/g/gfx/%02d.png" % i,
          "name": "%02d.png" % i}) for i in range(60)] + [
        ("Deleted", "1:"),
        ("", "gfx/old.png — 20.1 KB",
         {"side": "A", "part": 2, "path": "/g/gfx/old.png",
          "name": "old.png"})]),
]


def _run_compare(w, monkeypatch, sections=REPORT, seen=None):
    mfr = w.window.current_mfr

    def fake(a, b, assets_a=None, assets_b=None):
        if seen is not None:
            seen.update(a=a, b=b, xa=assets_a, xb=assets_b)
        return sections

    monkeypatch.setattr(mfr, "compare_images", fake)
    assert w.call("compare.run") is True
    _wait(w, lambda: not w.state("compare")["running"])


def test_compare_needs_two_real_images(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        assert w.call("compare.run") is False
        assert w.asked[-1]["title"] == "Pick two images"
        a, _b = _cards(tmp_path)
        w.run(lambda: w.window.compare_a_var.set(a))
        w.run(lambda: w.window.compare_b_var.set(str(tmp_path / "gone.raw")))
        assert w.call("compare.run") is False
        assert w.asked[-1]["title"] == "File not found"
        assert w.asked[-1]["message"].startswith("Image B:")


def test_compare_paints_folds_and_copies(tmp_path, monkeypatch):
    from pinball_decryptor.core.extract_source import write_extract_source
    with web_app(tmp_path, mfr="stern") as w:
        a, b = _cards(tmp_path)
        parent = tmp_path / "both"
        out_a = parent / "a"
        out_a.mkdir(parents=True)
        write_extract_source(str(out_a), a)
        w.run(lambda: w.window.remember_browse_dir("extract_both",
                                                   str(parent)))
        w.call("ui.set", "compare", "a", a)
        w.call("ui.set", "compare", "b", b)
        seen = {}
        _run_compare(w, monkeypatch, seen=seen)
        assert seen["a"] == a and seen["xa"] == str(out_a) \
            and seen["xb"] is None
        s = w.state("compare")
        assert s["has_report"] and s["status"] == ""
        rows = s["rows"]
        assert [r["kind"] for r in rows[:3]] == ["section", "head", "head"]
        # 50 of the 60 modified images, then the fold row
        items = [r for r in rows if r["kind"] == "item" and r["sec"] == 1]
        assert len(items) == 51                     # 50 + the one deleted
        more = next(r for r in rows if r["kind"] == "more")
        assert more["details"] == "… and 10 more — double-click to list them"
        assert w.window.path_history("compare_a") == [a]

        w.call("compare.set_limit", "12")
        rows = w.state("compare")["rows"]
        more = next(r for r in rows if r["kind"] == "more")
        assert more["details"] == "… and 48 more — double-click to list them"
        assert w.app._settings["compare_row_limit"] == "12"
        w.call("compare.activate", more["id"])
        rows = w.state("compare")["rows"]
        assert not any(r["kind"] == "more" for r in rows)
        assert len([r for r in rows if r["kind"] == "item"]) == 61
        w.call("compare.toggle_section", 1)
        rows = w.state("compare")["rows"]
        assert [r["kind"] for r in rows if r["sec"] == 1] == ["section"]
        w.call("compare.set_all_sections", False)

        text = w.call("compare.copy_report")
        assert text.startswith("Compare Report\n==============")
        assert "gfx/59.png" in text                 # every row, not the shown
        assert w.app.root._clip == text
        assert w.state("compare")["status"].startswith(
            "Report copied to clipboard")

        # a count row explains; a file row opens from the right card
        w.call("compare.activate", "s1g0")
        assert w.state("compare")["status"].startswith(
            "Only the listed files open")
        opened = []
        mfr = w.window.current_mfr
        monkeypatch.setattr(mfr, "extract_report_file",
                            lambda image, ref, out: (opened.append(
                                (image, ref["name"])), out)[1])
        from pinball_decryptor.core import desktop
        monkeypatch.setattr(desktop, "open_path",
                            lambda p, env=None: (True, ""))
        deleted = next(r for r in w.state("compare")["rows"]
                       if r["details"].startswith("gfx/old.png"))
        assert deleted["open"]
        w.call("compare.activate", deleted["id"])
        _wait(w, lambda: w.state("compare")["status"].startswith("Opened"))
        assert opened == [(a, "old.png")]
        assert w.state("compare")["status"] == "Opened old.png from image A."

        # a manufacturer switch drops the report
        w.call("ui.pick_manufacturer", "jjp")
        assert w.state("compare")["rows"] == []
        assert not w.state("compare")["has_report"]


def test_compare_counts_reports_so_a_selection_never_carries_over(
        tmp_path, monkeypatch):
    """Row ids are positional; the page drops its selected row whenever
    ``report`` moves (a new Compare, its result, a manufacturer switch), and
    keeps it across a repaint of the same report."""
    with web_app(tmp_path, mfr="stern") as w:
        a, b = _cards(tmp_path)
        w.call("ui.set", "compare", "a", a)
        w.call("ui.set", "compare", "b", b)
        r0 = w.state("compare")["report"]
        _run_compare(w, monkeypatch)
        r1 = w.state("compare")["report"]
        assert r1 > r0
        w.call("compare.set_limit", "12")
        more = next(r for r in w.state("compare")["rows"]
                    if r["kind"] == "more")
        w.call("compare.expand", more["id"])
        w.call("compare.toggle_section", 0)
        assert w.state("compare")["report"] == r1
        _run_compare(w, monkeypatch, sections=REPORT[:1])
        r2 = w.state("compare")["report"]
        assert r2 > r1
        w.call("ui.pick_manufacturer", "jjp")
        assert w.state("compare")["report"] > r2


def test_compare_error_section_never_sticks(tmp_path, monkeypatch):
    with web_app(tmp_path, mfr="stern") as w:
        a, b = _cards(tmp_path)
        w.call("ui.set", "compare", "a", a)
        w.call("ui.set", "compare", "b", b)
        mfr = w.window.current_mfr

        def boom(*a_, **k):
            raise RuntimeError("no readable data partition")
        monkeypatch.setattr(mfr, "compare_images", boom)
        w.call("compare.run")
        _wait(w, lambda: not w.state("compare")["running"])
        rows = w.state("compare")["rows"]
        assert rows[0]["change"] == "Error"
        assert rows[1]["change"] == "Could not compare"
        assert rows[1]["details"] == "no readable data partition"


def test_extract_both_checks_then_hands_over(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        a, b = _cards(tmp_path)
        seen = []
        w.window.cb["on_extract_both"] = lambda x, y: seen.append((x, y))
        assert w.call("compare.extract_both") is False
        assert w.asked[-1]["title"] == "Pick two images"
        w.call("ui.set", "compare", "a", a)
        w.call("ui.set", "compare", "b", a)
        assert w.call("compare.extract_both") is False
        assert w.asked[-1]["title"] == "Same image twice"
        w.call("ui.set", "compare", "b", b)
        assert w.call("compare.extract_both") is True
        assert seen == [(a, b)]


def test_compare_browse_uses_the_mfr_filetypes(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        a, _b = _cards(tmp_path)
        w.answers.append(a)
        assert w.call("compare.browse", "a") == os.path.normpath(a)
        spec = w.asked[-1]
        assert spec["title"] == "Select card image"
        assert spec["filetypes"][-1] == ["All files", "*.*"]
        assert w.window.compare_a_var.get() == os.path.normpath(a)
