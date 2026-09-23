"""The web Replace Video tab (webui/tabs/video.py): the state each
manufacturer gets, every page action with its questions answered, the
sidecar it keeps, and the attributes the run logic reads off the window."""

import csv
import json
import os
import subprocess
import time

import pytest

from tests.webui_harness import web_app

VIDEO_MFRS = ["stern", "jjp", "spooky", "pb", "dp", "ap", "bof"]


def _wait(w, pred, timeout=20.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        st = w.state("video")
        if pred(st):
            return st
        time.sleep(0.05)
    raise AssertionError("timed out; video state: %r" % {
        k: v for k, v in w.state("video").items() if k != "rows"})


def _project(tmp_path, names=("video/attract.mp4", "video/intro.mp4",
                              "video/sub/boss.mp4")):
    """A project folder with clip-named files (not real video: the scan
    walk never opens them, and a failed probe is a normal "—" row)."""
    import hashlib
    root = tmp_path / "proj"
    lines = []
    for rel in names:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"\0" * 64)
        lines.append("%s\t%s\n" % (rel, hashlib.md5(b"\0" * 64).hexdigest()))
    # the extract's baseline: what "changed on disk" is measured against
    (root / ".checksums.md5").write_text("".join(lines), encoding="utf-8")
    return root


def _mine(tmp_path, name="mine.mp4"):
    d = tmp_path / "mine"
    d.mkdir(exist_ok=True)
    p = d / name
    p.write_bytes(b"\1" * 32)
    return p


def _set_project(w, folder):
    """Point the shared project folder at *folder*.  Another tab's trace
    failing on the way is that tab's problem (its own tests say so), not
    this one's: the value is stored before any trace runs."""
    def _set():
        try:
            w.window.write_assets_var.set(str(folder))
        except Exception:                               # noqa: BLE001
            pass
    w.run(_set)


def _scan(w, folder):
    _set_project(w, folder)
    w.call("video.scan")
    return _wait(w, lambda st: not st.get("scanning") and st.get("rows"))


def _rels(st):
    return [st["rows"][i]["rel"] for i in st["view"]]


def _row(st, rel):
    return next(r for r in st["rows"] if r["rel"] == rel)


# ------------------------------------------------------------ manufacturers
@pytest.mark.parametrize("mfr", VIDEO_MFRS)
def test_manufacturer_state(tmp_path, mfr):
    with web_app(tmp_path, mfr=mfr) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["video"]["visible"]
        st = w.state("video")
        assert st["rows"] == [] and st["view"] == []
        assert st["quality_report"] is (mfr == "stern")
        assert st["stern"] is (mfr == "stern")
        assert st["trim_tip"].startswith("When on, a replacement longer")
        note = (w.window.current_mfr.video_length_note() or "").strip()
        if note:
            assert st["trim_tip"].endswith(note)
        assert st["preview"]["rep"]["hint"] == "no replacement assigned"
        assert st["empty"] == ("Set the project folder on the Extract tab, "
                               "then click Scan.")
        # the run logic's reads are real, not stand-ins
        win = w.window
        for name in ("video_trim_var", "video_no_conversion_var",
                     "pending_video_assignments"):
            getattr(win, name)
        assert not {"video_trim_var", "video_no_conversion_var"} & set(
            getattr(win, "missing_exports", {}) or {})


@pytest.mark.parametrize("mfr,era", [("cgc", None), ("williams", None),
                                     ("stern", "whitestar"),
                                     ("stern", "spike1")])
def test_hidden_where_the_plugin_has_no_video(tmp_path, mfr, era):
    with web_app(tmp_path, mfr=mfr, era=era) as w:
        if mfr not in {m.key for m in w.window.manufacturers}:
            pytest.skip("no %s plugin" % mfr)
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["video"]["visible"]
        assert w.window.pending_video_assignments(str(tmp_path)) is None


# ------------------------------------------------------------------- scan
def test_scan_lists_slots_and_selects_the_first(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        st = _scan(w, proj)
        assert _rels(st) == ["video/attract.mp4", "video/intro.mp4",
                             "video/sub/boss.mp4"]
        r = _row(st, "video/sub/boss.mp4")
        assert r["name"] == "boss.mp4" and r["dir"] == "video/sub/"
        assert r["rep"] == "Choose…" and r["rep_cls"] == ""
        st = _wait(w, lambda s: s["preview"]["rel"] == "video/attract.mp4")
        assert st["preview"]["orig"]["title"] == "Original"
        assert st["select"]["rels"] == ["video/attract.mp4"]
        st = _wait(w, lambda s: "still checking" not in s["status"])
        assert st["status"] == "0 of 3 slots changed"
        assert any("Video scan started." in l["text"]
                   for l in w.run(w.window.log_history))


def test_empty_folder_and_cancel(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    with web_app(tmp_path, mfr="jjp") as w:
        _set_project(w, empty)
        w.call("video.scan")
        st = _wait(w, lambda s: not s["scanning"])
        assert st["empty"] == "No replaceable video found in this folder."
        _set_project(w, "")
        w.call("video.scan")
        st = _wait(w, lambda s: not s["scanning"])
        assert st["empty"].startswith("Set the project folder")
        w.call("video.cancel_scan")
        assert w.state("video")["empty"] == ("Scan cancelled — click Scan to "
                                             "try again.")


def test_search_filter_and_sort(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="spooky") as w:
        _scan(w, proj)
        w.call("ui.set", "video", "search", "INTRO")
        st = w.state("video")
        assert _rels(st) == ["video/intro.mp4"]
        assert st["status"].startswith("0 of 3 slots changed  (1 shown)")
        w.call("ui.set", "video", "search", "")
        w.call("video.sort", "#0")
        st = w.state("video")
        assert st["sort"] == {"key": "#0", "desc": True}
        assert _rels(st)[0] == "video/sub/boss.mp4"
        w.call("video.sort", "len")         # Length defaults to longest first
        assert w.state("video")["sort"] == {"key": "len", "desc": True}


# ------------------------------------------------------------------- picks
def test_pick_persists_and_feeds_the_build(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="spooky") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        assert w.call("video.choose", "video/intro.mp4") is True
        st = w.state("video")
        r = _row(st, "video/intro.mp4")
        assert r["rep"] == "mine.mp4" and r["rep_cls"] == "picked"
        assert st["status"].startswith("1 of 3 slots changed")
        assert st["can_clear"] is True
        assert w.asked[-1]["title"] == ("Choose a replacement for "
                                        "video/intro.mp4")
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any(t.startswith("Replace Video: video/intro.mp4 ← mine.mp4")
                   for t in log)
        side = json.loads((proj / ".staged_changes.json")
                          .read_text(encoding="utf-8"))
        assert side["video"] == {"video/intro.mp4": str(mine)}
        assert side["replacement_names"]["video/intro.mp4"] == "mine.mp4"
        assert side["video_trim"] is False
        pend = w.window.pending_video_assignments(str(proj))
        slots, assigns, trim, noconv, asis = pend
        assert assigns == {"video/intro.mp4": str(mine)}
        assert "video/attract.mp4" in slots
        assert (trim, noconv, asis) == (False, False, {})
        assert w.window.pending_video_assignments(str(tmp_path)) is None
        assert w.window.replacement_folder_mismatches(str(proj)) == []
        other = tmp_path / "other"
        other.mkdir()
        mism = w.window.replacement_folder_mismatches(str(other))
        assert ("video", 1, str(proj)) in mism
        # Show: Changed narrows to the pick; the choice is persisted
        w.call("video.set_change_filter", "Changed")
        assert _rels(w.state("video")) == ["video/intro.mp4"]
        w.call("video.set_change_filter", "Unchanged")
        assert "video/intro.mp4" not in _rels(w.state("video"))
        side = json.loads((proj / ".staged_changes.json")
                          .read_text(encoding="utf-8"))
        assert side["video_change_filter"] == "Unchanged"
    # a fresh session restores the pick and the filter from the sidecar
    with web_app(tmp_path / "again", mfr="spooky") as w:
        st = _scan(w, proj)
        assert _row(st, "video/intro.mp4")["rep"] == "mine.mp4"
        assert st["change_filter"] == "Unchanged"


def test_cancelled_picker_changes_nothing(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _scan(w, proj)
        assert w.call("video.choose", "video/intro.mp4") is False
        assert not (proj / ".staged_changes.json").exists()


def test_as_is_pick_of_the_wrong_type_offers_to_convert(tmp_path):
    proj = _project(tmp_path)
    mov = _mine(tmp_path, "clip.mov")
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.call("video.set_no_conversion", True)
        assert w.state("video")["trim_enabled"] is False
        w.answers += [str(mov), "yes"]
        w.call("video.choose", "video/attract.mp4")
        q = w.asked[-1]
        assert q["title"] == "Using your files as-is"
        assert "needs a .mp4 file, but clip.mov is .mov" in q["message"]
        side = json.loads((proj / ".staged_changes.json")
                          .read_text(encoding="utf-8"))
        assert side["video_asis_slots"] == {"video/attract.mp4": False}
        assert side["video_no_conversion"] is True
        # one clip set to be converted: trim applies again
        assert w.state("video")["trim_enabled"] is True
        pend = w.window.pending_video_assignments(str(proj))
        assert pend[3] is True and pend[4] == {"video/attract.mp4": False}


def test_turning_as_is_on_warns_about_picks_it_would_reject(tmp_path):
    proj = _project(tmp_path)
    mov = _mine(tmp_path, "clip.mov")
    with web_app(tmp_path, mfr="dp") as w:
        _scan(w, proj)
        w.answers.append(str(mov))
        w.call("video.choose", "video/intro.mp4")
        w.answers.append("ok")
        w.call("video.set_no_conversion", True)
        q = w.asked[-1]
        assert q["title"] == "Using your files as-is"
        assert "rejected at build time" in q["message"]
        assert w.window.video_no_conversion_var.get() is True


def test_per_clip_conversion(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="jjp") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        w.call("video.choose", "video/intro.mp4")
        info = w.call("video.row_menu", ["video/intro.mp4"])
        assert info["asis"] == "box" and info["follow"] == "convert"
        assert info["has_pick"] and info["can_clear"]
        assert info["stern"] is False
        w.call("video.set_asis", "video/intro.mp4", True)
        assert w.call("video.row_menu",
                      ["video/intro.mp4"])["asis"] == "asis"
        st = _wait(w, lambda s: _row(s, "video/intro.mp4")["conv"]
                   .startswith("• "))
        w.call("video.set_asis", "video/intro.mp4", None)
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("follows the box below again (converted)" in t
                   for t in log)
        multi = w.call("video.row_menu", ["video/intro.mp4",
                                          "video/attract.mp4"])
        assert multi == {"multi": True, "rows": 2, "targets": 1}


# ---------------------------------------------------------------- clearing
def test_clear_one_and_all(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="pb") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        w.call("video.choose", "video/intro.mp4")
        assert w.call("video.clear", ["video/intro.mp4"]) == 1
        assert _row(w.state("video"), "video/intro.mp4")["rep"] == "Choose…"
        assert w.state("video")["can_clear"] is False
        # nothing left: the button says so
        w.call("video.clear_all")
        assert w.asked[-1]["message"] == ("Nothing is picked on this tab, so "
                                          "there is nothing to clear.")
        for rel in ("video/intro.mp4", "video/attract.mp4"):
            w.answers.append(str(mine))
            w.call("video.choose", rel)
        w.answers.append("no")
        assert w.call("video.clear_all") == 0
        assert "Clear all 2 replacements on this tab?" in \
            w.asked[-1]["message"]
        assert "none of your own files are touched" in w.asked[-1]["message"]
        w.answers.append("yes")
        assert w.call("video.clear_all") == 2
        side = json.loads((proj / ".staged_changes.json")
                          .read_text(encoding="utf-8"))
        assert side["video"] == {}
        assert w.window.pending_video_assignments(str(proj)) is None


def test_clear_puts_an_applied_original_back(tmp_path):
    from pinball_decryptor.core import staged_originals
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        # a build applied a replacement: the slot has a .orig snapshot
        target = proj / "video" / "intro.mp4"
        staged_originals.snapshot(str(proj), "video/intro.mp4", None)
        target.write_bytes(b"replacement bytes")
        w.call("video.scan")
        # "not scanning" is already true before the rescan starts: wait for
        # what the rescan finds (the wait fails the test if it never comes)
        st = _wait(w, lambda s: not s["scanning"] and s["can_clear"])
        assert st["can_clear"] is True
        w.answers.append("yes")
        assert w.call("video.clear_all") == 1
        assert target.read_bytes() == b"\0" * 64


def test_replace_from_folder(tmp_path):
    proj = _project(tmp_path)
    mine = tmp_path / "bw"
    (mine / "deep").mkdir(parents=True)
    (mine / "Attract.MOV").write_bytes(b"x")
    (mine / "deep" / "boss.mp4").write_bytes(b"x")
    (mine / "unrelated.mp4").write_bytes(b"x")
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        # refuses the project folder itself
        w.answers.append(str(proj / "video"))
        assert w.call("video.replace_from_folder") is False
        assert "part of the project folder" in w.asked[-1]["message"]
        w.answers += [str(mine), "yes"]
        assert w.call("video.replace_from_folder") is True
        msg = w.asked[-1]["message"]
        assert msg.startswith("Use 2 file(s) from")
        assert "1 of them are a different file type" in msg
        st = w.state("video")
        assert _row(st, "video/attract.mp4")["rep"] == "Attract.MOV"
        assert _row(st, "video/sub/boss.mp4")["rep"] == "boss.mp4"
        log = [l["text"] for l in w.run(w.window.log_history)]
        assert any("named like no slot on this tab: unrelated.mp4" in t
                   for t in log)


def test_export_csv(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    out = tmp_path / "out" / "video_slots.csv"
    out.parent.mkdir()
    with web_app(tmp_path, mfr="ap") as w:
        w.call("video.export_csv")
        assert "the video table is empty" in w.asked[-1]["message"]
        _scan(w, proj)
        w.answers += [str(mine), str(out)]
        w.call("video.choose", "video/intro.mp4")
        assert w.call("video.export_csv") is True
        rows = list(csv.reader(out.open(encoding="utf-8-sig")))
        assert rows[0] == ["Original Video", "Length", "Resolution",
                           "Format", "Audio", "Replacement", "Convert",
                           "Changed On Disk"]
        assert [r[0] for r in rows[1:]] == ["video/attract.mp4",
                                            "video/intro.mp4",
                                            "video/sub/boss.mp4"]
        assert rows[2][5] == str(mine)


# ------------------------------------------------------------- fan-outs
def test_fan_outs(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        w.answers.append(str(mine))
        w.call("video.choose", "video/intro.mp4")
        seq = w.state("video")["stop_seq"]
        w.run(w.window.stop_all_preview_playback)
        assert w.state("video")["stop_seq"] == seq + 1
        # invalidate keeps the picks' folder identity for the mismatch check
        w.run(lambda: w.window.invalidate_asset_scans(False))
        assert w.window.replacement_folder_mismatches(str(proj)) == []
        w.run(w.window.reload_assets_tabs)
        st = _wait(w, lambda s: not s["scanning"] and s["rows"])
        assert _row(st, "video/intro.mp4")["rep"] == "mine.mp4"
        w.run(lambda: w.window.clear_replace_assignments(str(proj)))
        assert w.window.pending_video_assignments(str(proj)) is None
        side = json.loads((proj / ".staged_changes.json")
                          .read_text(encoding="utf-8"))
        assert not side.get("video")
        w.run(w.window.refresh_after_revert)
        _wait(w, lambda s: "still checking" not in s["status"])


def test_menu_and_dialog_calls(tmp_path):
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        info = w.call("video.row_menu", ["video/intro.mp4"])
        assert info["stern"] is True and info["has_pick"] is False
        assert info["reveal"] in ("Show in File Explorer", "Reveal in Finder",
                                  "Show in File Manager")
        # the fake clip never probes: "What this slot needs" says so
        assert w.call("video.target_spec", "video/intro.mp4") is None
        assert w.asked[-1]["title"] == "What this slot needs"
        w.call("video.play", "video/intro.mp4", "rep")
        assert w.asked[-1]["title"] == "No Replacement"
        w.call("video.play", "video/intro.mp4", "orig")
        st = w.state("video")
        assert st["play"]["side"] == "orig"
        assert st["preview"]["rel"] == "video/intro.mp4"
        # Check card…
        assert w.call("video.quality_open") is True
        q = w.state("video")["quality"]
        assert q["open"] and q["summary"] == ("Pick a card image and press "
                                             "Check.")
        w.call("video.quality_check", str(tmp_path / "nope.raw"))
        assert w.asked[-1]["title"] == "Pick a card image"
        w.call("video.quality_close")
        assert w.state("video")["quality"]["open"] is False


# ------------------------------------------- the panes follow the selection
def test_choose_previews_the_row_it_picks_for(tmp_path):
    """Tk: a Replacement-cell click, a double-click and Enter select the
    row and <<TreeviewSelect>> loads it, so the panes show the row the
    picker is for (picked or cancelled) and the pick lands in them."""
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        _wait(w, lambda s: s["preview"]["rel"] == "video/attract.mp4")
        # cancelled picker: the row is still the one on show
        assert w.call("video.choose", "video/intro.mp4") is False
        st = w.state("video")
        assert st["preview"]["rel"] == "video/intro.mp4"
        assert st["preview"]["rep"]["path"] is None
        # a pick on another row: its panes, with the new replacement
        w.answers.append(str(mine))
        assert w.call("video.choose", "video/sub/boss.mp4") is True
        st = w.state("video")
        assert st["preview"]["rel"] == "video/sub/boss.mp4"
        assert st["preview"]["rep"]["path"] == str(mine)
        assert st["preview"]["rep"]["label"] == "mine.mp4"
        assert st["preview"]["can_clear"] is True
        assert st["select"]["rels"] == ["video/sub/boss.mp4"]


def test_selecting_the_row_on_show_keeps_it_playing(tmp_path):
    """Tk _video_preview_selected: the row already loaded is left alone
    (a click on it while it plays doesn't restart it); ▶ on an empty pane
    (Tk _video_activate_pane) loads the row and plays that pane."""
    proj = _project(tmp_path)
    with web_app(tmp_path, mfr="stern") as w:
        _scan(w, proj)
        st = _wait(w, lambda s: s["preview"]["rel"] == "video/attract.mp4")
        seq, play = st["preview"]["orig"]["seq"], st["play"]["seq"]
        assert w.call("video.select", "video/attract.mp4", "orig") is True
        st = w.state("video")
        assert st["preview"]["orig"]["seq"] == seq
        assert st["play"]["seq"] == play
        assert w.call("video.activate_pane", "video/attract.mp4",
                      "rep") is True
        st = w.state("video")
        assert st["preview"]["orig"]["seq"] > seq
        assert st["play"] == {"side": "rep", "seq": play + 1}
        # a different row still loads, resuming on the pane that played
        w.call("video.select", "video/intro.mp4", "orig")
        st = w.state("video")
        assert st["preview"]["rel"] == "video/intro.mp4"
        assert st["play"] == {"side": "orig", "seq": play + 2}


def test_clear_reselects_the_cleared_rows(tmp_path):
    """Tk re-selects what a clear dropped (the page then previews the
    first of them, as <<TreeviewSelect>> did)."""
    proj = _project(tmp_path)
    mine = _mine(tmp_path)
    with web_app(tmp_path, mfr="dp") as w:
        _scan(w, proj)
        for rel in ("video/intro.mp4", "video/sub/boss.mp4"):
            w.answers.append(str(mine))
            w.call("video.choose", rel)
        w.answers.append("yes")
        assert w.call("video.clear", ["video/sub/boss.mp4",
                                      "video/intro.mp4"]) == 2
        st = w.state("video")
        assert set(st["select"]["rels"]) == {"video/intro.mp4",
                                             "video/sub/boss.mp4"}


# --------------------------------------------------------- rail count
def test_rail_badge_counts_the_changed_slots(tmp_path):
    proj = _project(tmp_path)
    mine = _mine(tmp_path)

    def badge(w):
        return {t["ns"]: t for t in w.state("shell")["tabs"]}["video"][
            "badge"]

    with web_app(tmp_path, mfr="spooky") as w:
        _scan(w, proj)
        assert badge(w) is None
        for rel in ("video/intro.mp4", "video/attract.mp4"):
            w.answers.append(str(mine))
            w.call("video.choose", rel)
        assert badge(w) == 2
        w.call("video.clear", ["video/intro.mp4"])
        assert badge(w) == 1
        w.call("ui.pick_manufacturer", "jjp")
        w.drain()
        assert badge(w) is None


# ------------------------------------------------------- column widths
def test_column_widths_persist(tmp_path):
    """Tk _persist_tree_columns: only the dragged columns are kept (and
    added to the ones dragged before); Tk's own "video" entry is left for
    the Tk app."""
    tk_widths = {"#0": 431, "len": 143}
    with web_app(tmp_path, mfr="stern",
                 settings={"column_widths": {"video": tk_widths}}) as w:
        assert w.state("video")["widths"] == {}
        assert w.call("video.save_widths",
                      {"rel": 300.4, "len": 5, "bogus": 90,
                       "fmt": True}) is True
        assert w.call("video.save_widths", {"fmt": 150}) is True
        assert w.call("video.save_widths", {"len": 2}) is False
        saved = w.app._settings["column_widths"]
        assert saved["video_web"] == {"rel": 300, "fmt": 150}
        assert saved["video"] == tk_widths
        assert w.state("video")["widths"] == {"rel": 300, "fmt": 150}
    # a restart restores them
    with web_app(tmp_path / "again", mfr="stern", settings={
            "column_widths": {"video_web": {"rel": 300, "rep": 0,
                                            "aud": "x"}}}) as w:
        assert w.state("video")["widths"] == {"rel": 300}


# -------------------------------------------------------- Check card…
def test_check_card_report_is_dropped_on_close_and_on_a_switch(tmp_path):
    """VideoQualityDialog: Close (or ×, Escape) stops the check and the next
    Check card… starts a fresh report; a manufacturer switch drops it too."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window._by_ns["video"]
        w.call("video.quality_open")
        svc._q_clips = ["x"]
        w.run(lambda: svc._quality_set(rows=[{"name": "a"}]))
        # open again: the same report is raised, not rebuilt
        w.call("video.quality_open")
        assert w.state("video")["quality"]["rows"] == [{"name": "a"}]
        scan = svc._q_scan
        w.call("video.quality_close")
        q = w.state("video")["quality"]
        assert q["open"] is False and q["rows"] == []
        assert svc._q_cancel is True and svc._q_scan == scan + 1
        w.call("video.quality_open")
        svc._q_cancel = False
        svc._q_clips = ["x"]
        w.call("ui.pick_manufacturer", "jjp")
        w.drain()
        assert svc._q_cancel is True and svc._q_clips == []
        assert w.state("video")["quality"]["open"] is False


# ------------------------------------------------ real clips (needs ffmpeg)
def _ffmpeg():
    from pinball_decryptor.core.video import find_ffmpeg, find_ffprobe
    return find_ffmpeg() if (find_ffmpeg() and find_ffprobe()) else None


@pytest.mark.skipif(not _ffmpeg(), reason="needs ffmpeg + ffprobe")
def test_real_clips_probe_poster_and_proxy(tmp_path):
    ff = _ffmpeg()
    proj = tmp_path / "proj" / "video"
    proj.mkdir(parents=True)
    for name, codec in (("a.mp4", ["-c:v", "libx264", "-pix_fmt",
                                   "yuv420p"]),
                        ("b.mov", ["-c:v", "mpeg4"])):
        subprocess.run([ff, "-v", "error", "-y", "-f", "lavfi", "-i",
                        "testsrc=size=320x180:rate=30:duration=1"]
                       + codec + [str(proj / name)], check=True,
                       timeout=60)
    with web_app(tmp_path, mfr="stern") as w:
        st = _scan(w, proj.parent)
        st = _wait(w, lambda s: all(r["res"] not in ("…",)
                                    for r in s["rows"]))
        a = _row(st, "video/a.mp4")
        assert a["res"] == "320×180" and a["len"] == "0:01"
        assert a["fmt"].startswith("MP4 h264")
        b = _row(st, "video/b.mov")
        assert b["fmt_bad"] is True          # Stern: not H.264
        st = _wait(w, lambda s: s["preview"]["orig"].get("poster"))
        pane = st["preview"]["orig"]
        assert pane["facts"]["codec"] == "h264"
        assert os.path.isfile(pane["poster"])
        w.call("video.select", "video/b.mov")
        st = _wait(w, lambda s: s["preview"]["rel"] == "video/b.mov"
                   and s["preview"]["orig"].get("facts"))
        assert st["preview"]["note"]["kind"] == "err"
        assert "WRONG FORMAT" in st["preview"]["note"]["text"]
        seq = st["preview"]["orig"]["seq"]
        w.call("video.make_proxy", "orig", seq, "mp4")
        st = _wait(w, lambda s: s["preview"]["orig"].get("proxy")
                   or s["preview"]["orig"].get("proxy_err"), timeout=60)
        assert st["preview"]["orig"]["proxy_err"] == ""
        assert os.path.getsize(st["preview"]["orig"]["proxy"]) > 0
        spec = w.call("video.target_spec", "video/a.mp4")
        assert ["Video codec", "H264"] in spec["spec"]
        assert "ffmpeg" in spec["cmd"]
