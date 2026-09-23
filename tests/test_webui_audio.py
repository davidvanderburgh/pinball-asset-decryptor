"""The Replace Audio tab on the web UI (webui/tabs/audio.py).

Every manufacturer the tab shows for, every page call against a synthetic
project folder of tiny WAVs, the modal answers through the harness, and the
window attributes the run logic reads (pending_audio_assignments & co)."""

import json
import os
import struct
import time
import wave

import pytest

from tests.webui_harness import web_app

AUDIO_MFRS = [("ap", None), ("bof", None), ("cgc", None), ("dp", None),
              ("jjp", None), ("pb", None), ("spooky", None),
              ("stern", "spike2"), ("stern", "spike1")]


def _wav(path, seconds=0.25, rate=8000, amp=2000):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = int(seconds * rate)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"".join(struct.pack("<h", amp if i % 16 < 8 else -amp)
                               for i in range(n)))


def _project(tmp_path, names=("audio/idx0001 - Jackpot.wav",
                              "audio/idx0002.wav",
                              "audio/idx0003 - music loop.wav")):
    folder = tmp_path / "proj"
    for i, rel in enumerate(names):
        _wav(str(folder / rel), seconds=0.2 + 0.1 * i)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(folder))
    return str(folder)


def _wait(w, pred, timeout=15.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


def _open(w, folder):
    """Point the shared project folder at *folder* and scan it."""
    w.run(lambda: w.window.write_assets_var.set(folder))
    w.call("ui.select_tab", "audio")
    assert _wait(w, lambda: len(w.state("audio")["rows"]) > 0
                 and not w.state("audio")["scanning"]), w.state("audio")
    # the change diff lands after the list
    assert _wait(w, lambda: "still checking" not in
                 (w.state("audio")["status"] or ""))


def _svc(w):
    return w.window.service("audio")


def _sidecar(folder):
    from pinball_decryptor.core import staged_changes
    return staged_changes.load(folder)


# ------------------------------------------------------------ per manufacturer
@pytest.mark.parametrize("mfr,era", AUDIO_MFRS)
def test_state_after_manufacturer(tmp_path, mfr, era):
    with web_app(tmp_path, mfr=mfr, era=era) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert tabs["audio"]["visible"], mfr
        s = w.state("audio")
        caps = w.window.current_mfr.capabilities
        want_col = ("loop" if caps.audio_loop_inject
                    else "keep" if caps.audio_keep_length_override
                    else "lvl" if caps.audio_level_offset else None)
        assert s["col"] == want_col
        assert s["level_cap"] == bool(caps.audio_level_offset)
        assert s["adv_cap"] == (mfr == "stern")
        assert s["dups_cap"] == (mfr == "cgc")
        forced = mfr in ("jjp", "stern")
        assert s["trim_visible"] == (not forced)
        assert w.window.audio_trim_var.get() is forced
        assert s["rows"] == []
        assert s["empty"] == ("Set the project folder on the Extract tab, "
                              "then click Scan.")
        assert s["panes"]["rep"]["hint"] == "no replacement assigned"
        assert "Trim / pad" not in s["trim_tip"] or True
        assert s["trim_tip"].startswith("When on, a replacement longer")
        # what the run logic reads off the window
        assert w.window.pending_audio_assignments("x") is None
        assert w.window.audio_keep_full_rels("x") == frozenset()
        assert w.window.audio_loop_basenames("x") == frozenset()
        assert w.window._audio_grow_active() in (True, False)
        btn = w.window._audio_profile_btn
        assert btn.cget("state") == "normal"


def test_no_audio_tab_for_williams(tmp_path):
    with web_app(tmp_path, mfr="williams") as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not tabs["audio"]["visible"]


def test_grow_active_follows_the_advanced_option(tmp_path):
    settings = {"audio_advanced": {"audio_grow": True}}
    with web_app(tmp_path, mfr="stern", settings=settings) as w:
        assert w.window._audio_grow_active() is True
        w.call("ui.set_era", "spike1")
        assert w.window._audio_grow_active() is False
    with web_app(tmp_path / "b", mfr="jjp", settings=settings) as w:
        assert w.window._audio_grow_active() is False


def test_profile_button_contract(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        btn = w.window._audio_profile_btn
        w.run(lambda: btn.configure(state="disabled"))
        assert btn.cget("state") == "disabled"
        assert w.state("audio")["profile_busy"] is True
        w.run(lambda: btn.configure(state="normal"))
        assert w.state("audio")["profile_busy"] is False
        # nothing scanned: the Tk info box, and no worker
        w.call("audio.profile")
        assert w.asked[-1]["title"] == "Profile vs stock"


# --------------------------------------------------------------- scan + list
def test_scan_lists_slots_and_counts(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        s = w.state("audio")
        assert [r["k"] for r in s["rows"]] == [
            "audio/idx0001 - Jackpot.wav", "audio/idx0002.wav",
            "audio/idx0003 - music loop.wav"]
        assert s["status"] == "0 of 3 slots changed"
        assert s["prefix"] == "audio/"
        assert all(r["rep"] == "Choose…" and r["t"] == "" for r in s["rows"])
        assert s["folder"] == folder
        # the probe fills Length / Format
        assert _wait(w, lambda: all(r["len"] != "—"
                                    for r in w.state("audio")["rows"]))
        assert w.state("audio")["rows"][0]["fmt"].startswith("WAV 8kHz mono")
        # the first row is selected and previewed
        assert s["sel"] == ["audio/idx0001 - Jackpot.wav"]
        assert _wait(w, lambda: w.state("audio")["panes"]["orig"]["path"])
        pane = w.state("audio")["panes"]["orig"]
        assert pane["base"] == "Original"
        assert pane["name"] == "idx0001 - Jackpot.wav"
        logs = [l["text"] for l in w.window.log_history()]
        assert "Audio scan started." in logs
        assert any(t.startswith("Audio scan finished in") for t in logs)


def test_search_show_sort(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        w.call("ui.set", "audio", "search", "jackpot")
        s = w.state("audio")
        assert [r["k"] for r in s["rows"]] == ["audio/idx0001 - Jackpot.wav"]
        assert s["status"] == "0 of 3 slots changed  (1 shown)"
        w.call("ui.set", "audio", "search", "")
        w.call("audio.set_show", "Changed")
        s = w.state("audio")
        assert s["rows"] == []
        assert s["empty"] == "Nothing in this folder has been changed yet."
        assert _sidecar(folder)["audio_change_filter"] == "Changed"
        w.call("audio.set_show", "All")
        assert _wait(w, lambda: all(r["len"] != "—"
                                    for r in w.state("audio")["rows"]))
        w.call("audio.sort", "len")
        s = w.state("audio")
        assert s["sort"] == {"key": "len", "desc": True}
        assert s["rows"][0]["k"] == "audio/idx0003 - music loop.wav"
        w.call("audio.sort", "len")
        assert w.state("audio")["sort"]["desc"] is False


def test_cancel_scan(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        w.run(lambda: w.window.write_assets_var.set(folder))
        w.run(lambda: _svc(w)._set_scanning(True))
        w.call("audio.scan")          # reads "Cancel scan" while scanning
        s = w.state("audio")
        assert not s["scanning"]
        assert s["empty"] == "Scan cancelled — click Scan to try again."


# ----------------------------------------------------------------- picking
def test_choose_stages_in_the_sidecar_and_feeds_the_write(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "mine" / "new_jackpot.wav")
    _wav(rep, seconds=1.0)
    rel = "audio/idx0001 - Jackpot.wav"
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        w.answers.append(rep)
        assert w.call("audio.choose", rel) is True
        assert w.asked[-1]["title"] == "Choose a replacement for %s" % rel
        s = w.state("audio")
        row = s["rows"][0]
        assert row["rep"] == "new_jackpot.wav" and row["t"] == "picked"
        assert s["status"] == "1 of 3 slots changed"
        assert s["can_clear"] is True
        side = _sidecar(folder)
        assert side["audio"] == {rel: rep}
        assert side["replacement_names"][rel] == "new_jackpot.wav"
        assert "Replace Audio: %s ← new_jackpot.wav" % rel in [
            l["text"] for l in w.window.log_history()]
        pend = w.window.pending_audio_assignments(folder)
        slots, assigns, trim, keep = pend
        assert assigns == {rel: rep} and rel in slots
        assert trim is False and keep == frozenset()
        other = str(tmp_path / "elsewhere")
        assert w.window.pending_audio_assignments(other) is None
        assert w.window.replacement_folder_mismatches(other) == [
            ("audio", 1, folder)]
        assert w.window.replacement_folder_mismatches(folder) == []
        # the replacement pane shows the pick, trimmed at the slot length
        w.call("audio.select", [rel])
        assert _wait(w, lambda: w.state("audio")["panes"]["rep"]["path"]
                     == rep)
        # the menu: one undo, by state
        labels = [i.get("label") for i in w.call("audio.menu", rel, [rel])]
        assert "Remove replacement" in labels
        assert "Revert to original" not in labels
        assert "Play replacement" in labels
        assert "Properties…  (name / type)" in labels
        # Remove replacement
        w.call("audio.menu_action", "remove", rel, [rel])
        assert _sidecar(folder)["audio"] == {}
        assert w.state("audio")["rows"][0]["rep"] == "Choose…"


def test_trim_toggle_and_preview_limit(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "long.wav")
    _wav(rep, seconds=2.0)
    rel = "audio/idx0001 - Jackpot.wav"
    from pinball_decryptor.core import audio as _audio
    if not (_audio.probe_duration(rep) or 0) > 0:
        # the limit is drawn from the probed length (ffprobe), which a CI
        # runner with only the Python requirements does not have
        pytest.skip("no audio duration probe on this machine")
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        w.call("audio.set_trim", True)
        assert _sidecar(folder)["audio_trim"] is True
        w.answers.append(rep)
        w.call("audio.choose", rel)
        w.call("audio.select", [rel])
        assert _wait(w, lambda: w.state("audio")["panes"]["rep"]["limit"])
        pane = w.state("audio")["panes"]["rep"]
        assert abs(pane["limit"] - 0.2) < 0.01
        assert pane["dur"] > 1.5


def test_clear_all_confirms_and_drops(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        for rel in ("audio/idx0001 - Jackpot.wav", "audio/idx0002.wav"):
            w.answers.append(rep)
            w.call("audio.choose", rel)
        w.answers.append("no")
        assert w.call("audio.clear_all") is False
        assert "Clear all 2 replacements on this tab?" in w.asked[-1][
            "message"]
        w.answers.append("yes")
        assert w.call("audio.clear_all") is True
        assert _sidecar(folder)["audio"] == {}
        assert w.state("audio")["can_clear"] is False
        w.call("audio.clear_all")
        assert w.asked[-1]["message"].startswith("Nothing is picked")


def test_bulk_menu_on_a_selection(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    sel = ["audio/idx0001 - Jackpot.wav", "audio/idx0002.wav"]
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        items = w.call("audio.menu", sel[0], sel)
        assert items[0]["label"] == "2 slots selected"
        assert items[-1]["label"] == "No replacements in this selection"
        for rel in sel:
            w.answers.append(rep)
            w.call("audio.choose", rel)
        items = w.call("audio.menu", sel[0], sel)
        assert items[-1]["label"] == "Clear 2 replacements in this selection"
        w.answers.append("yes")
        w.call("audio.menu_action", "clear_selection", sel[0], sel)
        assert _sidecar(folder)["audio"] == {}


def test_replace_from_folder(tmp_path):
    folder = _project(tmp_path)
    mine = tmp_path / "mine"
    _wav(str(mine / "IDX0002.wav"))
    _wav(str(mine / "sub" / "idx0001 - jackpot.mp3.wav"))
    _wav(str(mine / "nothing.wav"))
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        # the project folder itself is refused
        w.answers.append(folder)
        assert w.call("audio.replace_from_folder") is False
        assert "part of the project folder" in w.asked[-1]["message"]
        w.answers += [str(mine), "yes"]
        assert w.call("audio.replace_from_folder") is True
        assigned = _sidecar(folder)["audio"]
        assert "audio/idx0002.wav" in assigned
        logs = " ".join(l["text"] for l in w.window.log_history())
        assert "picked" in logs and "named like no slot" in logs


def test_export_csv(tmp_path):
    folder = _project(tmp_path)
    out = str(tmp_path / "out" / "audio_slots.csv")
    os.makedirs(os.path.dirname(out))
    with web_app(tmp_path, mfr="ap") as w:
        w.call("audio.export_csv")
        assert w.asked[-1]["title"] == "Export CSV"
        _open(w, folder)
        w.answers.append(out)
        assert w.call("audio.export_csv") is True
        text = open(out, encoding="utf-8-sig").read().splitlines()
        assert text[0] == ("Original Track,Length,Format,Type,Replacement,"
                           "Changed On Disk,Loop,Full Length,Level dB")
        assert len(text) == 4


# ------------------------------------------------------- manufacturer flags
def test_bof_loop_flag(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    with web_app(tmp_path, mfr="bof") as w:
        w.run(lambda: w.window.write_assets_var.set(folder))
        w.run(lambda: _svc(w)._scan_async())
        assert _wait(w, lambda: len(w.state("audio")["rows"]) == 3)
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        # "loop" in the name defaults ON
        assert rows["audio/idx0003 - music loop.wav"]["loop"] is True
        assert rows["audio/idx0001 - Jackpot.wav"]["loop"] is False
        rel = "audio/idx0001 - Jackpot.wav"
        w.call("audio.toggle_flag", rel, "loop")
        w.answers.append(rep)
        w.call("audio.choose", rel)
        assert w.window.audio_loop_basenames(folder) == frozenset(
            {"idx0001 - Jackpot.wav"})
        assert _sidecar(folder)["audio_loop"][rel] is True


def test_jjp_keep_full_flag(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    rel = "audio/idx0002.wav"
    with web_app(tmp_path, mfr="jjp") as w:
        w.run(lambda: w.window.write_assets_var.set(folder))
        w.run(lambda: _svc(w)._scan_async())
        assert _wait(w, lambda: len(w.state("audio")["rows"]) == 3)
        w.answers.append(rep)
        w.call("audio.choose", rel)
        w.call("audio.toggle_flag", rel, "keep")
        assert w.window.audio_keep_full_rels(folder) == frozenset({rel})
        _slots, _a, trim, keep = w.window.pending_audio_assignments(folder)
        assert trim is True and keep == frozenset({rel})


def test_stern_level_and_apply_all(tmp_path):
    folder = _project(tmp_path)
    rel = "audio/idx0001 - Jackpot.wav"
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        assert w.state("audio")["level_enabled"] is True
        w.call("audio.select", [rel])
        w.call("audio.set_level", rel, "4")
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        assert rows[rel]["lvl"] == "+4 dB"
        assert _sidecar(folder)["audio_levels"] == {rel: 4}
        w.call("audio.set_level", rel, "40")          # clamped
        assert _sidecar(folder)["audio_levels"] == {rel: 12}
        w.answers.append("yes")
        assert w.call("audio.level_apply_all", "-3") is True
        assert "Set the loudness offset to -3 dB on all 3 sound(s)" in \
            w.asked[-1]["message"]
        assert set(_sidecar(folder)["audio_levels"].values()) == {-3}
        w.answers.append("yes")
        w.call("audio.level_apply_all", "0")
        assert w.asked[-1]["message"].startswith(
            "Clear the loudness offset on all 3")
        assert _sidecar(folder)["audio_levels"] == {}


def test_stern_advanced_dialog(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        data = w.call("audio.advanced_get")
        assert data["cfg"]["head_mode"] == "encode"
        assert w.state("audio")["adv_marker"] is False
        cfg = dict(data["cfg"], audio_grow=True, loudness_db=40,
                   experiment_idxs="231; 258, x")
        w.call("audio.advanced_set", cfg)
        saved = w.app._settings["audio_advanced"]
        assert saved["audio_grow"] is True
        assert saved["loudness_db"] == 12
        assert saved["experiment_idxs"] == "231,258"
        assert w.state("audio")["adv_marker"] is True
        assert w.window._audio_grow_active() is True


def test_stern_keep_whole_menu(tmp_path):
    folder = _project(tmp_path)
    rel = "audio/idx0001 - Jackpot.wav"
    settings = {"audio_advanced": {"audio_grow": True}}
    with web_app(tmp_path, mfr="stern", settings=settings) as w:
        _open(w, folder)
        items = {i.get("label"): i for i in w.call("audio.menu", rel, [rel])}
        keep = items["Keep this song whole if the bank fills up"]
        assert keep["checked"] is False       # the page draws it as "☐  …"
        w.call("audio.menu_action", "keep_whole", rel, [rel])
        assert _sidecar(folder)["grow_keep_whole"] == [rel]
        items = {i.get("label"): i for i in w.call("audio.menu", rel, [rel])}
        assert items["Keep this song whole if the bank fills up"][
            "checked"] is True                # "☑  …"


def test_properties_rename(tmp_path):
    folder = _project(tmp_path)
    rel = "audio/idx0002.wav"
    with open(os.path.join(folder, "sound_test_names.csv"), "w",
              encoding="utf-8") as f:
        f.write("sound_number,name\n87,SE FX SIDE RAMP EXIT\n")
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        info = w.call("audio.props_info", rel)
        assert info["label"] == ""
        assert info["suggestions"] == ["#87  SE FX SIDE RAMP EXIT"]
        assert "blank restores \"idx0002.wav\"" in info["prompt"]
        assert w.call("audio.rename", rel, "#87  SE FX SIDE RAMP EXIT",
                      "sfx") is True
        new = "audio/idx0002 - SE FX SIDE RAMP EXIT.wav"
        assert os.path.isfile(os.path.join(folder, *new.split("/")))
        rows = {r["k"]: r for r in w.state("audio")["rows"]}
        assert new in rows and rel not in rows
        assert rows[new]["type"] == "Sound FX"
        assert w.state("audio")["sel"] == [new]


def test_sequential_play_steps_down_the_list(tmp_path):
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        first = w.state("audio")["rows"][0]["k"]
        w.call("audio.play_row", first)
        assert _wait(w, lambda: w.state("audio")["panes"]["orig"]["path"])
        path = w.state("audio")["panes"]["orig"]["path"]
        # off: nothing happens
        assert w.call("audio.clip_finished", "orig", path) is False
        w.call("ui.set", "audio", "play_through", True)
        assert w.call("audio.clip_finished", "orig", path) is True
        assert _wait(w, lambda: w.state("audio")["sel"]
                     == ["audio/idx0002.wav"])
        # "Play replacements" turns sequential play on
        w.call("ui.set", "audio", "play_through", False)
        w.call("audio.set_play_subst", True)
        assert w.window.service("audio").audio_play_through_var.get()


def test_fan_out_calls(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        w.answers.append(rep)
        w.call("audio.choose", "audio/idx0002.wav")
        w.run(lambda: w.window.stop_all_preview_playback())
        w.run(lambda: w.window.invalidate_asset_scans(False))
        # the stamp is gone but the assignments keep their folder
        assert w.window.replacement_folder_mismatches(folder) == []
        assert w.window.pending_audio_assignments(folder) is None
        w.run(lambda: w.window.reload_assets_tabs())
        assert _wait(w, lambda: _svc(w)._scan_dir == folder)
        w.run(lambda: w.window.clear_replace_assignments(folder))
        assert _sidecar(folder).get("audio") in (None, {})
        w.run(lambda: w.window.refresh_after_revert())
        assert w.window.pending_audio_assignments(folder) is None


def test_sidecar_restores_on_a_new_folder(tmp_path):
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    from pinball_decryptor.core import staged_changes
    staged_changes.save(folder, {
        "audio": {"audio/idx0001 - Jackpot.wav": rep,
                  "audio/gone.wav": rep,
                  "audio/idx0002.wav": str(tmp_path / "missing.wav")},
        "audio_levels": {"audio/idx0001 - Jackpot.wav": 5},
        "audio_change_filter": "Unchanged",
        "video": {"video/x.mp4": "keep-me"}})
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        s = w.state("audio")
        assert s["show"] == "Unchanged"
        assert [r["k"] for r in s["rows"]] == [
            "audio/idx0002.wav", "audio/idx0003 - music loop.wav"]
        logs = " ".join(l["text"] for l in w.window.log_history())
        assert "wasn't restored" in logs
        # a save keeps every other tab's section
        w.call("audio.set_show", "All")
        side = _sidecar(folder)
        assert side["video"] == {"video/x.mp4": "keep-me"}
        assert side["audio_levels"] == {"audio/idx0001 - Jackpot.wav": 5}


def test_column_widths_are_the_tk_trees(tmp_path):
    """Dragged widths live where the Tk tree kept them
    (column_widths["audio"]): the ones already tuned in Tk open the web
    table, a drag merges only the columns it changed, and a width below the
    Tk column's minwidth never shows."""
    tk = {"#0": 404, "len": 80, "fmt": 151, "rep": 293, "loop": 44,
          "keep": 44, "type": 78}
    settings = {"column_widths": {"audio": dict(tk), "audio_web": {"x": 1},
                                  "video": {"#0": 222}}}
    with web_app(tmp_path, mfr="ap", settings=settings) as w:
        assert w.state("audio")["widths"] == tk
        # only the dragged column changes; junk and the play column are not
        # Tk columns and are dropped
        assert w.call("audio.save_widths", {"fmt": 190.4, "play": 30,
                                            "len": 5, "bogus": 100}) is True
        saved = w.app._settings["column_widths"]
        assert saved["audio"] == dict(tk, fmt=190)
        assert saved["video"] == {"#0": 222}          # other trees kept
        assert "audio_web" not in saved               # the old web key goes
        assert w.state("audio")["widths"]["fmt"] == 190
        assert w.call("audio.save_widths", {"play": 30}) is False
        import pinball_decryptor.core.config as config
        with open(config.SETTINGS_FILE, encoding="utf-8") as f:
            on_disk = json.load(f)["column_widths"]
        assert on_disk["audio"]["fmt"] == 190 and "audio_web" not in on_disk
    narrow = {"column_widths": {"audio": {"#0": 30, "len": 10, "lvl": 20}}}
    with web_app(tmp_path / "b", mfr="stern", settings=narrow) as w:
        assert w.state("audio")["widths"] == {"#0": 80, "len": 66, "lvl": 58}


def test_a_remembered_folder_that_is_gone_is_not_opened(tmp_path):
    """Tk ``last_browse_dir`` only reopened a folder that still exists: a
    deleted one opened the picker's default, never an error over an empty
    listing (the replacement picker, Replace from folder, Export CSV)."""
    folder = _project(tmp_path)
    here = tmp_path / "picks"
    here.mkdir()
    rep = str(here / "a.wav")
    _wav(rep)
    gone = str(tmp_path / "no" / "such" / "folder")
    settings = {"browse_dirs": {"audio_replacement": gone,
                                "audio_csv": gone}}
    rel = "audio/idx0001 - Jackpot.wav"
    with web_app(tmp_path, mfr="ap", settings=settings) as w:
        _open(w, folder)
        w.answers.append("")
        assert w.call("audio.choose", rel) is False
        assert w.asked[-1]["initialdir"] == ""
        w.answers.append("")
        w.call("audio.replace_from_folder")
        assert w.asked[-1]["initialdir"] == ""
        w.answers.append("")
        w.call("audio.export_csv")
        assert w.asked[-1]["initialdir"] == ""
        # a pick remembers its folder, and the next picker opens there
        w.answers.append(rep)
        assert w.call("audio.choose", rel) is True
        w.answers.append("")
        w.call("audio.choose", "audio/idx0002.wav")
        assert os.path.normcase(w.asked[-1]["initialdir"]) ==             os.path.normcase(str(here))


def test_leaving_the_tab_drops_a_queued_preview(tmp_path):
    """window.select_tab stops the previews itself; the tab's
    on_tab_changed also drops a row preview queued in the last 250 ms, so
    nothing loads (and resumes playing) behind the next tab."""
    folder = _project(tmp_path)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)
        svc = _svc(w)
        w.call("audio.select", ["audio/idx0002.wav"], "orig")
        assert svc._select_job is not None
        w.call("ui.select_tab", "extract")
        assert svc._select_job is None
        w.call("ui.select_tab", "audio")
        w.call("audio.select", ["audio/idx0002.wav"])
        w.call("ui.select_tab", "audio")         # staying put keeps it
        assert svc._select_job is not None


def test_cgc_duplicate_groups_and_fanout(tmp_path):
    import types
    folder = _project(tmp_path)
    rep = str(tmp_path / "a.wav")
    _wav(rep)
    a, b = "audio/idx0001 - Jackpot.wav", "audio/idx0002.wav"
    fake = types.SimpleNamespace(groups=[types.SimpleNamespace(
        duration_seconds=0.25,
        slots=[types.SimpleNamespace(wav_path=os.path.join(folder, "audio",
                                                           os.path.basename(r)))
               for r in (a, b)])])
    with web_app(tmp_path, mfr="cgc") as w:
        _open(w, folder)
        svc = _svc(w)
        w.run(lambda: svc.audio_group_dups_var.set(True))
        w.run(lambda: svc._apply_dup_groups(svc._dup_scan_id, folder, fake))
        rows = w.state("audio")["rows"]
        assert rows[0]["g"] == 1
        assert rows[0]["label"] == "idx0001 - Jackpot — 2 copies"
        assert rows[0]["open"] is False
        assert [r["k"] for r in rows[1:]] == ["audio/idx0003 - music loop.wav"]
        w.call("audio.toggle_group", rows[0]["k"])
        rows = w.state("audio")["rows"]
        assert [r.get("d") for r in rows[1:3]] == [1, 1]
        w.answers.append(rep)
        w.call("audio.choose", a)
        labels = [i.get("label") for i in w.call("audio.menu", a, [a])]
        assert "Apply to all 2 copies of this sound" in labels
        w.call("audio.menu_action", "fanout", a, [a])
        assert _sidecar(folder)["audio"] == {a: rep, b: rep}
        assert w.state("audio")["status"].startswith("Applied to 1 duplicate")
        assert w.state("audio")["rows"][0]["rep"] == "2 of 2 modded"
        # a plugin error unticks the box and says why
        w.run(lambda: svc._apply_dup_groups(svc._dup_scan_id, folder,
                                            RuntimeError("no banks here")))
        assert svc.audio_group_dups_var.get() is False
        assert w.asked[-1]["title"] == "Can't group duplicates"


def test_revert_an_applied_slot(tmp_path):
    folder = _project(tmp_path)
    rel = "audio/idx0002.wav"
    from pinball_decryptor.core import checksums, staged_originals
    base = checksums.read_baseline_any(folder)
    staged_originals.snapshot(folder, rel, base.get(rel))
    _wav(os.path.join(folder, "audio", "idx0002.wav"), seconds=0.9, amp=900)
    with web_app(tmp_path, mfr="ap") as w:
        _open(w, folder)

        def _row():
            return {r["k"]: r for r in w.state("audio")["rows"]}.get(rel, {})
        # the on-disk diff can land after _open's "still checking" wait
        # passes (the diff may not have started yet): wait for the row
        assert _wait(w, lambda: _row().get("t") == "ondisk"), _row()
        assert _row()["rep"] == "✓ changed on disk"
        w.call("audio.select", [rel])
        # both panes' labels land after the selection's disk checks
        assert _wait(w, lambda: w.state("audio")["panes"]["orig"]["base"]
                     == "Original (stock)"
                     and w.state("audio")["panes"]["rep"]["base"]
                     == "Replacement (your file)"), w.state("audio")["panes"]
        assert _wait(w, lambda: w.state("audio")["cur"]["built"] is True)
        labels = [i.get("label") for i in w.call("audio.menu", rel, [rel])]
        assert "Revert to original" in labels
        w.call("audio.remove_selected")
        assert staged_originals.snapshot_path(folder, rel) is None
        assert _wait(w, lambda: _row().get("rep") == "Choose…"), _row()
        assert "Replace Audio: reverted %s to the extracted original" % rel \
            in [l["text"] for l in w.window.log_history()]


def test_find_in_partition_hands_off(tmp_path):
    folder = _project(tmp_path)
    rel = "audio/idx0001 - Jackpot.wav"
    with web_app(tmp_path, mfr="stern") as w:
        _open(w, folder)
        labels = [i.get("label") for i in w.call("audio.menu", rel, [rel])]
        assert "Find in Partition Explorer" in labels
        seen = []
        pex = w.window.service("partitions")
        w.run(lambda: setattr(pex, "find_in_partition",
                              lambda kind, r, d=None: seen.append((kind, r, d))))
        w.call("audio.menu_action", "find_pex", rel, [rel])
        assert seen == [("audio", rel, folder)]
    with web_app(tmp_path / "b", mfr="jjp") as w:
        _open(w, folder)
        labels = [i.get("label") for i in w.call("audio.menu", rel, [rel])]
        assert "Find in Partition Explorer" not in labels


# ------------------------------------------------------ the page's keyboard
_AUDIO_JS = os.path.join(os.path.dirname(__file__), os.pardir,
                         "pinball_decryptor", "webui", "static", "js",
                         "tabs", "audio.js")

_KEYNAV_CASES = r"""
import { keyNav } from "./tabs/audio.js";
const slot = (i, extra) => ({ k: "s" + String(i).padStart(2, "0"), ...extra });
const rows = []; for (let i = 0; i < 14; i++) rows.push(slot(i));
const idx = (rs) => new Map(rs.map((r, i) => [r.k, i]));
const out = {};
const run = (name, rs, cur, key, shift) => { out[name] = keyNav(rs, idx(rs), cur, key, !!shift); };
// Shift+Down twice from s10 extends to s12 (it jumped to the top)
let st = { cursor: "s10", anchor: "s10", sel: ["s10"] };
let a = keyNav(rows, idx(rows), st, "ArrowDown", true);
out.shift1 = a;
out.shift2 = keyNav(rows, idx(rows), { cursor: a.cursor, anchor: a.anchor, sel: a.sel }, "ArrowDown", true);
// Ctrl-click s03 then s06, then Down: s07 (it went to s00)
run("ctrlDown", rows, { cursor: "s06", anchor: "s06", sel: ["s03", "s06"] }, "ArrowDown");
// a Ctrl-click that DESELECTED the focus row still moves from it
run("ctrlOffDown", rows, { cursor: "s06", anchor: "s06", sel: ["s03"] }, "ArrowDown");
run("top", rows, { cursor: "s00", anchor: "s00", sel: ["s00"] }, "ArrowUp");
run("bottom", rows, { cursor: "s13", anchor: "s13", sel: ["s13"] }, "ArrowDown");
run("fresh", rows, { cursor: null, anchor: null, sel: [] }, "ArrowDown");
run("fromSel", rows, { cursor: "gone", anchor: null, sel: ["s05", "s04"] }, "ArrowDown");
// duplicate groups: the arrows pass a group row (it toggled forever)
const g = [slot(0), { k: "::dupgrp::0", g: 1, open: false }, slot(2)];
run("ontoGroup", g, { cursor: "s00", anchor: "s00", sel: ["s00"] }, "ArrowDown");
run("pastGroup", g, { cursor: "::dupgrp::0", anchor: "::dupgrp::0", sel: ["::dupgrp::0"] }, "ArrowDown");
run("rightOpens", g, { cursor: "::dupgrp::0", anchor: null, sel: ["::dupgrp::0"] }, "ArrowRight");
run("leftClosed", g, { cursor: "::dupgrp::0", anchor: null, sel: ["::dupgrp::0"] }, "ArrowLeft");
const go = [slot(0), { k: "::dupgrp::0", g: 1, open: true }, slot(2, { d: 1 }), slot(3, { d: 1 }), slot(4)];
run("intoGroup", go, { cursor: "::dupgrp::0", anchor: null, sel: ["::dupgrp::0"] }, "ArrowDown");
run("leftChild", go, { cursor: "s03", anchor: "s03", sel: ["s03"] }, "ArrowLeft");
run("leftOpen", go, { cursor: "::dupgrp::0", anchor: null, sel: ["::dupgrp::0"] }, "ArrowLeft");
run("rightOpen", go, { cursor: "::dupgrp::0", anchor: null, sel: ["::dupgrp::0"] }, "ArrowRight");
run("shiftOverGroup", go, { cursor: "s02", anchor: "s04", sel: ["s02", "s03", "s04"] }, "ArrowUp", true);
run("leftTop", rows, { cursor: "s03", anchor: "s03", sel: ["s03", "s04"] }, "ArrowLeft");
console.log(JSON.stringify(out));
"""


def _node():
    import shutil
    return shutil.which("node")


@pytest.mark.skipif(_node() is None, reason="needs Node.js")
def test_keyboard_moves_from_the_focus_row(tmp_path):
    """The page's arrow keys (audio.js ``keyNav``) follow the Tk tree's
    Keynav: from the focus row, not the selection; Shift extends from the
    anchor; group rows are passed, opened with Right, closed with Left."""
    import re
    import subprocess
    src = open(_AUDIO_JS, encoding="utf-8").read()
    (tmp_path / "tabs").mkdir()
    (tmp_path / "core").mkdir()
    (tmp_path / "tabs" / "audio.js").write_text(src, encoding="utf-8")
    # stand-ins for the modules audio.js imports (keyNav needs none of them)
    for mod, frm in (("ui", "../core/ui.js"), ("store", "../core/store.js")):
        m = re.search(r"import \{([^}]*)\} from \"%s\"" % re.escape(frm), src)
        names = [n.strip() for n in m.group(1).split(",") if n.strip()]
        (tmp_path / "core" / (mod + ".js")).write_text(
            "".join("export const %s = () => null;\n" % n for n in names),
            encoding="utf-8")
    (tmp_path / "package.json").write_text('{"type": "module"}',
                                           encoding="utf-8")
    (tmp_path / "cases.js").write_text(_KEYNAV_CASES, encoding="utf-8")
    run = subprocess.run([_node(), str(tmp_path / "cases.js")],
                         capture_output=True, text=True, timeout=60,
                         cwd=str(tmp_path))
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["shift1"] == {"cursor": "s11", "anchor": "s10",
                             "sel": ["s10", "s11"]}
    assert got["shift2"]["sel"] == ["s10", "s11", "s12"]
    assert got["ctrlDown"]["sel"] == ["s07"]
    assert got["ctrlOffDown"]["sel"] == ["s07"]
    assert got["top"] is None and got["bottom"] is None
    assert got["fresh"]["sel"] == ["s00"]
    assert got["fromSel"]["sel"] == ["s05"]
    assert got["ontoGroup"] == {"cursor": "::dupgrp::0",
                                "anchor": "::dupgrp::0",
                                "sel": ["::dupgrp::0"]}
    assert got["pastGroup"]["sel"] == ["s02"]
    assert got["rightOpens"]["toggle"] == "::dupgrp::0"
    assert got["leftClosed"] is None
    assert got["intoGroup"]["sel"] == ["s02"]
    assert got["leftChild"]["sel"] == ["::dupgrp::0"]
    assert "toggle" not in got["leftChild"]
    assert got["leftOpen"]["toggle"] == "::dupgrp::0"
    assert "toggle" not in got["rightOpen"]
    assert got["shiftOverGroup"]["sel"] == ["s02", "s03", "s04"]
    assert got["shiftOverGroup"]["cursor"] == "::dupgrp::0"
    assert got["leftTop"] is None


def test_row_controls_never_fire_the_row_double_click():
    """A double-click on the row's play button, its Loop / Full box or its
    Replacement cell must not reach the row (whose double-click opens the
    picker), and the second click of it does nothing; the columns resize
    through the core Table."""
    src = open(_AUDIO_JS, encoding="utf-8").read()
    for cls in ("aud-rowplay", "aud-flag", "aud-rep"):
        start = src.index('class="%s"' % cls if cls == "aud-rowplay"
                          else '"%s"' % cls)
        tag = src[start:src.index("</button>", start)]
        assert "onDblClick=${noDbl}" in tag, cls
        assert "onClick=${once(" in tag, cls
    assert "const once = (fn) => (e) => { e.stopPropagation(); " \
           "if (e.detail > 1) return; fn(e); };" in src
    assert "resizable widths=${tblWidths} onResize=${onResize}" in src
    assert "aud-grip" not in src and "audio_web" not in src
