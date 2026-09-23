"""The app's run logic, kept from the Tk-era GUI smoke tests.

These used to build a full Tk App per test (tests/test_gui_smoke.py).  The
window is the web UI now, so each test drives the same run logic through the
in-process web harness (tests/webui_harness.py), or calls the logic directly
(the plugin, a webui helper module, or an App method) when no window is needed.
"""

import os
import sys
import time

import pytest

from tests.webui_harness import web_app


def _wait(w, pred, timeout=15.0):
    """Drain the UI loop until *pred()* is true (or the time runs out)."""
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return pred()


# ---------------------------------------------------------------------------
# start-up, the title bar, the picker
# ---------------------------------------------------------------------------

def test_resolve_startup_manufacturer(all_manufacturers):
    """The launch-target decision: a saved key that still loads opens directly;
    a missing / stale key falls back to the picker (returns None)."""
    from pinball_decryptor.app import _resolve_startup_manufacturer as resolve
    stern = next(m for m in all_manufacturers if m.key == "stern")
    assert resolve(all_manufacturers, {"last_manufacturer": "stern"}) is stern
    assert resolve(all_manufacturers, {"last_manufacturer": "gone"}) is None
    assert resolve(all_manufacturers, {}) is None
    assert resolve(all_manufacturers, {"last_manufacturer": ""}) is None


def test_audio_raw_encode_env_always_pinned(tmp_path):
    """The match-to-callouts shaper is retired (batch 20): App startup pins
    PAD_STERN_AUDIO_RAW=1 unconditionally, so the Stern encoder always writes
    replacements as provided (no toggle, no persisted setting)."""
    with web_app(tmp_path) as w:
        assert os.environ.get("PAD_STERN_AUDIO_RAW") == "1"
        assert "audio_declick" not in w.app._settings


def test_stern_title_caption_from_vendor_filename(manufacturers_by_key):
    """Batch 20: the title bar identifies the game leanly (no platform echo),
    plus version + edition parsed off Stern's vendor filename."""
    from pinball_decryptor.core.registry import Game
    stern = manufacturers_by_key["stern"]
    g = Game(key="led_zeppelin", display="Led Zeppelin (Spike 2)",
             manufacturer_key="stern", era="spike2",
             notes="Spike 2 card image")
    cap = stern.title_caption(
        "X:/cards/led_zeppelin_le-1_22_0.Release.8G.sdcard.raw", g)
    assert cap == "Led Zeppelin v1.22.0 LE"
    # A renamed card still shows the bare title, never the platform suffix.
    assert stern.title_caption("X:/cards/backup.raw", g) == "Led Zeppelin"


def test_detected_game_caption_drives_title_bar(tmp_path):
    """The App composes the title bar from the detected-game caption (batch
    20) plus the loaded project (batch 19); losing the detection drops the
    caption again."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        w.run(app._on_detected_game_change, "Led Zeppelin v1.22 LE")
        assert "Led Zeppelin v1.22 LE" in app.root.title()
        assert "Led Zeppelin v1.22 LE" in w.state("shell")["title"]
        w.run(app._on_detected_game_change, None)
        assert "Led Zeppelin" not in app.root.title()


def test_checkout_badge_in_title_bar(tmp_path):
    """A window running an item worktree (the /next chooser flow) carries
    the checkout badge in the title bar, alongside the usual caption, so two
    open copies can be told apart.  The harness app runs under pytest so its
    badge is None; set it as the picker flow would."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app

        def _badge(value):
            app._checkout_badge = value
            app._refresh_title()
        w.run(_badge, "item/27 - Any Spike 2 title should load")
        w.run(app._on_detected_game_change, "Led Zeppelin v1.22 LE")
        title = app.root.title()
        assert "[item/27 - Any Spike 2 title should load]" in title
        assert "Led Zeppelin v1.22 LE" in title
        w.run(_badge, None)
        assert "item/27" not in app.root.title()


def test_manufacturer_picker_alphabetical_order(tmp_path):
    with web_app(tmp_path) as w:
        displays = [m.display for m in w.app._manufacturers]
        assert displays == sorted(displays, key=str.lower)


def test_picker_time_log_lines_flush_into_first_log(tmp_path):
    """Lines logged while the picker is showing (the startup update check)
    aren't dropped: they flush into the first manufacturer log that opens,
    links included."""
    with web_app(tmp_path) as w:
        win = w.window
        w.run(win.append_log, "startup-buffered-line", "info")
        w.run(win.append_log_link, "startup-buffered-link",
              "https://example.com/x")
        w.call("ui.pick_manufacturer", "spooky")
        w.drain()
        texts = [e["text"] for e in win.log_history()]
        assert "startup-buffered-line" in texts
        assert "startup-buffered-link" in texts
        assert not win._pending_log                 # buffer drained


def test_era_switcher_pills_flip_era_and_input_label(tmp_path):
    """The header era switcher (multi-era plugins only) flips the active era
    and the era-specific input label, clears the now-wrong input, and re-runs
    the prerequisite probes for the new era."""
    with web_app(tmp_path, mfr="stern") as w:
        stern = w.window.current_mfr
        try:
            assert stern.current_era == "spike2"
            assert w.state("extract")["input_label"] == "Card image"
            w.call("ui.set", "extract", "input", "dummy.img")
            kicked = []
            w.app._kick_off_prereq_check = lambda m: kicked.append(m)
            assert w.call("ui.set_era", "whitestar") is True
            w.drain()
            assert stern.current_era == "whitestar"
            assert w.state("extract")["input_label"] == "ROM zip"
            assert w.window.extract_input_var.get() == ""
            assert kicked and kicked[-1].current_era == "whitestar"
        finally:
            stern.set_era("spike2")


def test_path_history_records_dedupes_and_caps(tmp_path):
    """Path boxes keep a per-manufacturer recent-paths history (a tester):
    recorded at run start, most recent first, deduped case-insensitively,
    capped, and pushed into the window for the dropdowns."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app

        def _record(path):
            app._record_path_history(extract_input=path)
        for i in range(8):
            w.run(_record, "C:/imgs/card%d.raw" % i)
        hist = app._settings["path_history"]["stern"]["extract_input"]
        assert len(hist) == app._PATH_HISTORY_MAX
        assert hist[0].endswith("card7.raw")
        # Re-recording an older path moves it to the front without
        # duplicating.  The match is os.path.normcase: case-insensitive on
        # Windows, where C:/IMGS and c:/imgs are one folder; elsewhere a
        # path differing in case is a different file, so re-record it as is.
        again = ("C:/IMGS/CARD5.RAW" if sys.platform == "win32"
                 else "C:/imgs/card5.raw")
        w.run(_record, again)
        hist = app._settings["path_history"]["stern"]["extract_input"]
        assert len(hist) == app._PATH_HISTORY_MAX
        assert hist[0] == again
        assert sum("card5" in p.lower() for p in hist) == 1
        # The window sees the same lists (the dropdowns read them).
        assert w.window.path_history("extract_input") == hist
        assert w.state("shell")["path_history"]["extract_input"] == hist


def test_extract_options_persist_per_manufacturer(tmp_path):
    """Auto-name + extract-category checkboxes stick across a leave-and-return
    (the same settings.json round trip a restart does) and stay per
    manufacturer (a tester: 'do not stick between sessions')."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("extract")
        assert svc._extract_category_vars          # stern advertises some
        cat0 = next(iter(svc._extract_category_vars))
        w.call("ui.set", "extract", "transcribe", True)
        w.call("ui.set", "extract", "music_id", True)
        w.call("ui.set", "extract", "cat_" + cat0, False)
        # Leave for another manufacturer: spooky starts from ITS defaults...
        w.call("ui.pick_manufacturer", "spooky")
        w.drain()
        assert not svc.transcribe_var.get()
        assert not svc.music_id_var.get()
        # ...and returning to stern restores the saved ticks.
        w.call("ui.pick_manufacturer", "stern")
        w.drain()
        assert svc.transcribe_var.get()
        assert svc.music_id_var.get()
        assert not svc._extract_category_vars[cat0].get()
        others = [k for k in svc._extract_category_vars if k != cat0]
        assert all(svc._extract_category_vars[k].get() for k in others)


def test_settings_gear_and_prereq_strip_autohide(tmp_path):
    """The update check's result reaches the window: a found update puts the
    banner up (with a one-click Install when the release carries a Windows
    installer, an honest "Download update" for an AppImage, and the plain
    browser Download otherwise), lights the gear's dot, and says so in the
    log (David)."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app

        def _banner():
            return {b["id"]: b for b in
                    w.state("shell")["banners"]}.get("update")

        w.run(app._handle_update_check_result,
              ("99.0.0", "https://example.com/release", "", None), False)
        b = _banner()
        assert "v99.0.0 is available" in b["text"]
        assert [a["label"] for a in b["actions"]] == ["Download"]
        assert w.state("shell")["gear_dots"]["update"]
        texts = [e["text"] for e in w.window.log_history()]
        assert any(t.startswith("Update available: v99.0.0") for t in texts)

        setup = {"name": "setup.exe", "url": "https://x/w.exe", "size": 1,
                 "sha256": None, "kind": "windows-installer"}
        w.run(app._handle_update_check_result,
              ("99.0.1", "https://example.com/release", "", setup), False)
        assert [a["label"] for a in _banner()["actions"]] == [
            "Install update", "Release notes"]

        appimage = {"name": "PAD_v99_Linux_x86_64.AppImage",
                    "url": "https://x/pad.AppImage", "size": 1,
                    "sha256": None, "kind": "appimage"}
        w.run(app._handle_update_check_result,
              ("99.0.2", "https://example.com/release", "", appimage), False)
        assert _banner()["actions"][0]["label"] == "Download update"


# ---------------------------------------------------------------------------
# preview features (the signed preview code)
# ---------------------------------------------------------------------------

def _dt_days(n):
    import datetime
    return datetime.timedelta(days=n)


def test_the_mode_maker_is_hidden_until_a_preview_code_unlocks_it(tmp_path,
                                                                  monkeypatch):
    """The mode maker ships dark (core/preview.py): no Modes tab for Stern
    without a code.  Settings > Preview features takes one; a bad one says
    why and changes nothing, a good one shows the tab at once and is kept in
    settings.json, and Remove hides it again."""
    from pinball_decryptor.core import preview
    from tests.test_preview_switch import OTHER_SECRET, TEST_PUB, make_code
    monkeypatch.setattr(preview, "PUBLIC_KEYS", (TEST_PUB,))
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app

        def _modes_visible():
            tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
            return tabs["modes"]["visible"]

        assert not _modes_visible()
        ids = [it.get("id") for it in w.state("shell")["settings_items"]]
        assert "preview_features" in ids
        assert w.call("shellx.preview_state")["rows"] == []
        for bad, needle in (("hello", "not a preview code"),
                            (make_code(secret=OTHER_SECRET),
                             "not issued for this app"),
                            (make_code(days=3, issued=preview.utc_today()
                                       - _dt_days(20)), "ended on")):
            r = w.call("shellx.preview_unlock", bad)
            assert r["ok"] is False and needle in r["message"]
            assert not _modes_visible() and not preview.enabled("modes")
            assert preview.SETTINGS_KEY not in app._settings
        code = make_code(name="Test Person", days=30,
                         issued=preview.utc_today())
        r = w.call("shellx.preview_unlock",
                   code[:40] + "\n" + code[40:].lower())   # as pasted
        assert r["ok"] is True and r["message"].startswith("Unlocked.")
        assert preview.enabled("modes") and _modes_visible()
        assert app._settings[preview.SETTINGS_KEY] == [code]
        until = (preview.utc_today() + _dt_days(30)).isoformat()
        assert r["rows"][0]["lines"] == [
            "Mode maker: on for Test Person, until %s" % until]
        r = w.call("shellx.preview_remove", 0)
        assert r["ok"] is True
        assert not preview.enabled("modes") and not _modes_visible()
        assert preview.SETTINGS_KEY not in app._settings
        # another manufacturer never shows it, code or not
        w.call("shellx.preview_unlock", code)
        w.call("ui.pick_manufacturer", "spooky")
        w.drain()
        assert not _modes_visible()


def test_an_expired_code_turns_the_mode_maker_off_at_the_next_start(
        tmp_path, monkeypatch):
    """Verification happens at start-up (App._load_preview_codes, cached for
    the run): a stored code that has ended switches nothing on, and the log
    says so; a good one switches it on at the next start."""
    from pinball_decryptor.core import preview
    from tests.test_preview_switch import TEST_PUB, make_code
    monkeypatch.setattr(preview, "PUBLIC_KEYS", (TEST_PUB,))
    ended = make_code(days=5, issued=preview.utc_today() - _dt_days(10))
    with web_app(tmp_path, mfr="stern",
                 settings={preview.SETTINGS_KEY: [ended]}) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert not preview.enabled("modes") and not tabs["modes"]["visible"]
        said = [e["text"] for e in w.window.log_history()]
        assert any("Mode maker: expired on" in t for t in said), said
        assert any("1 code(s) checked in" in t for t in said), said
    good = make_code(issued=preview.utc_today())
    with web_app(tmp_path / "next", mfr="stern",
                 settings={preview.SETTINGS_KEY: [good]}) as w:
        tabs = {t["ns"]: t for t in w.state("shell")["tabs"]}
        assert preview.enabled("modes") and tabs["modes"]["visible"]


def test_the_write_scan_lists_no_mode_rows_with_the_switch_off(
        manufacturers_by_key, tmp_path, monkeypatch):
    """With the switch off a tester's project lists no "Pending (Modes)" or
    game's-own-modes rows: the Write leaves them out (and its log says so),
    so the list promises nothing."""
    from pinball_decryptor.plugins.stern import mode_project as MP
    from pinball_decryptor.plugins.stern import stock_modes as SM
    from pinball_decryptor.webui import write_scan
    project = str(tmp_path / "project")
    for _name, spec in MP.example_specs()[:2]:
        MP.new_mode(project, spec=spec)
    monkeypatch.setattr(SM, "staged_edits", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("read with the switch off")))
    stern = manufacturers_by_key["stern"]
    assert write_scan.mode_rows(stern, project, direct=False) == []
    assert write_scan.stock_mode_rows(stern, project) == []


#: The mode maker's own vocabulary, any of which gives it away
#: (case-insensitive substrings).  "mode" alone is an ordinary word in this
#: app (service mode, attract mode, a game's own battle modes on tabs that
#: predate the family), so the list is the family's words, not the word.
_REVEALING = ("mode maker", "modes tab", "try it", "code mode", "mode file",
              "mode.json", "film cutter", "from a film", "film cut",
              "showcase", "game's own modes", "mode of your own",
              "modes of your own", "mode of our own", "modes of our own",
              "own modes", "your own mode", "mode sdk", "mode runtime",
              "modes folder", "stock mode", "kaiju", "make a mode",
              "new mode", "a game mode")


def _revealing(texts):
    import re
    words = re.compile(r"\b(?:%s)\b" % "|".join(re.escape(t)
                                                  for t in _REVEALING), re.I)
    name = re.compile(r"\bModes\b")
    return [(where, text) for where, text in texts
            if words.search(text) or name.search(text)]


def _strings(value, where, out):
    if isinstance(value, str):
        if value:
            out.append((where, value))
    elif isinstance(value, dict):
        for k, v in value.items():
            _strings(v, "%s.%s" % (where, k), out)
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            _strings(v, "%s[%d]" % (where, i), out)


def _everything_readable(w):
    """Every text the page can show as the app stands: the store of every
    namespace except the pages of hidden tabs (nobody can open one), the
    visible rail, the log, and the "?" text of every visible tab."""
    snap = w.ctx.store.snapshot()
    rail = (snap.get("shell") or {}).get("tabs") or []
    hidden = {t["ns"] for t in rail if not t.get("visible")}
    out = []
    for ns, data in snap.items():
        if ns in hidden:
            continue
        data = dict(data or {})
        if ns == "shell":
            data["tabs"] = [t for t in rail if t.get("visible")]
        _strings(data, ns, out)
    for e in w.window.log_history():
        _strings(e.get("text"), "log", out)
    for t in rail:
        if t.get("visible") and t.get("key"):
            tips = w.call("shellx.tips", t["key"])
            _strings([tips["title"], tips["sections"]], "tips " + t["key"],
                     out)
    return out


def test_the_app_without_a_preview_code_names_nothing_of_the_mode_maker(
        tmp_path, monkeypatch):
    """THE CLEAN SURFACE (David, 2026-09-18): a copy of the app with no
    preview code shows nothing of the mode maker.  Everything the page can
    show (every namespace of the store but the hidden tabs', the rail, the
    log, and the "?" text of every visible tab) is walked on the picker and
    for EVERY manufacturer, and none of the family's words is in any of it.
    The Preview features window, before a code, names no feature at all.
    The control at the end switches the mode maker on and finds its words
    with the same walk, so the walk can see them."""
    from pinball_decryptor.core import preview
    from pinball_decryptor.webui.help_content import sections_for
    assert not preview.enabled("modes")
    with web_app(tmp_path) as w:
        hits = _revealing(_everything_readable(w))
        assert not hits, hits[:10]
        for key in sorted(m.key for m in w.window.manufacturers):
            w.call("ui.pick_manufacturer", key)
            w.drain()
            hits = _revealing(_everything_readable(w))
            assert not hits, (key, hits[:10])
        # the "?" text of the hidden tab itself, and of Write, say nothing
        bodies = []
        for tab in ("Modes", "Write"):
            _strings(sections_for(tab), tab, bodies)
        assert bodies and not _revealing(bodies), _revealing(bodies)
        # the Settings gear keeps "Preview features..." exactly as it is ...
        ids = [it.get("id") for it in w.state("shell")["settings_items"]]
        assert "preview_features" in ids
        # ... and its window, before a code, names no feature
        st = w.call("shellx.preview_state")
        assert st["rows"] == []
        said = []
        _strings(st, "preview", said)
        for label in preview.FEATURES.values():
            assert not [t for _w, t in said if label.lower() in t.lower()], \
                label
        assert not _revealing(said), _revealing(said)

        # THE CONTROL: the switch on, the same walk finds the tab and its
        # words
        real = preview.enabled
        monkeypatch.setattr(preview, "enabled",
                            lambda f: f == "modes" or real(f))
        w.call("ui.pick_manufacturer", "stern")
        w.run(w.window.service("shellx").apply_preview_features)
        w.drain()
        found = {t.strip() for _w, t in _revealing(_everything_readable(w))}
        assert "Modes" in found, sorted(found)[:10]
        bodies = []
        for tab in ("Modes", "Write"):
            _strings(sections_for(tab), tab, bodies)
        assert _revealing(bodies)


# ---------------------------------------------------------------------------
# Replace Audio
# ---------------------------------------------------------------------------

def _wav(path, seconds=0.25, rate=8000, amp=2000):
    import struct
    import wave
    os.makedirs(os.path.dirname(path), exist_ok=True)
    n = int(seconds * rate)
    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(rate)
        f.writeframes(b"".join(struct.pack("<h", amp if i % 16 < 8 else -amp)
                               for i in range(n)))


def _audio_project(tmp_path):
    folder = tmp_path / "proj"
    for i, rel in enumerate(("audio/idx0001.wav", "audio/idx0002.wav")):
        _wav(str(folder / rel), seconds=0.2 + 0.1 * i)
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(folder))
    return str(folder)


def _open_audio(w, folder):
    w.run(lambda: w.window.write_assets_var.set(folder))
    w.call("ui.select_tab", "audio")
    assert _wait(w, lambda: len(w.state("audio")["rows"]) > 0
                 and not w.state("audio")["scanning"]), w.state("audio")


def test_audio_advanced_env_mirror(tmp_path, monkeypatch):
    """Advanced audio options persist and mirror into the PAD_STERN_* env
    vars; defaults clear every var so the engine baseline stays
    authoritative.  The retired shaper knobs (fade / cap / roll-off, batch
    20) are actively CLEARED even when a stale persisted config still carries
    them.  Machine-render previews point next to the build output."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        for var in ("PAD_STERN_HEAD_MODE", "PAD_STERN_LEADOUT",
                    "PAD_STERN_PREVIEW_DIR", "PAD_STERN_SLOT_SEED_DB"):
            monkeypatch.delenv(var, raising=False)
        # Simulate an old session's leftover experiment env.
        monkeypatch.setenv("PAD_STERN_FADE_MS", "80.0")
        monkeypatch.setenv("PAD_STERN_HEADROOM", "0.6")
        monkeypatch.setenv("PAD_STERN_LOWPASS_HZ", "0")

        # A stale persisted cfg may still carry the retired keys: they must
        # be ignored, not re-applied.
        cfg = {"fade_ms": 80, "headroom_pct": 60, "lowpass_hz": 0,
               "head_mode": "stock", "leadout": "stock", "previews": True,
               "slot_seed": True, "slot_seed_db": 65}
        w.run(app._on_audio_advanced_change, cfg)
        for var in ("PAD_STERN_FADE_MS", "PAD_STERN_HEADROOM",
                    "PAD_STERN_LOWPASS_HZ"):
            assert var not in os.environ, var
        assert os.environ["PAD_STERN_HEAD_MODE"] == "stock"
        assert os.environ["PAD_STERN_LEADOUT"] == "stock"
        assert os.environ["PAD_STERN_SLOT_SEED_DB"] == "-65"
        assert app._settings["audio_advanced"] == cfg

        out = os.path.join("X:", "out", "card.raw")
        w.run(app._apply_audio_preview_env, out)
        assert os.environ["PAD_STERN_PREVIEW_DIR"].endswith(
            "card_machine_previews")

        w.run(app._on_audio_advanced_change, {})       # back to defaults
        for var in ("PAD_STERN_FADE_MS", "PAD_STERN_HEADROOM",
                    "PAD_STERN_LOWPASS_HZ", "PAD_STERN_HEAD_MODE",
                    "PAD_STERN_LEADOUT", "PAD_STERN_SLOT_SEED_DB"):
            assert var not in os.environ
        w.run(app._apply_audio_preview_env, out)
        assert "PAD_STERN_PREVIEW_DIR" not in os.environ


def test_audio_advanced_offers_replacement_loudness(tmp_path):
    """PAD-90: the loudness match is scale-invariant, so a user who remixes a
    track louder gets a byte-identical card.  The option to sit above (or
    below) the stock level has to reach the encoder env vars the spawned
    encode workers read."""
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        for var in ("PAD_STERN_MATCH_LOUDNESS", "PAD_STERN_MATCH_GAIN_DB"):
            os.environ.pop(var, None)
        w.run(app._on_audio_advanced_change,
              {"loudness": "match", "loudness_db": 6})
        cfg = app._settings["audio_advanced"]
        assert cfg["loudness"] == "match" and cfg["loudness_db"] == 6
        # "match" is the engine baseline, so only the offset sets a var
        assert "PAD_STERN_MATCH_LOUDNESS" not in os.environ
        assert os.environ["PAD_STERN_MATCH_GAIN_DB"] == "6"

        # Full-scale mode sets the kill switch; defaults clear both again.
        w.run(app._on_audio_advanced_change,
              {"loudness": "full", "loudness_db": -30})
        assert os.environ["PAD_STERN_MATCH_LOUDNESS"] == "0"
        assert os.environ["PAD_STERN_MATCH_GAIN_DB"] == "-12"   # clamped
        w.run(app._on_audio_advanced_change, {})
        for var in ("PAD_STERN_MATCH_LOUDNESS", "PAD_STERN_MATCH_GAIN_DB"):
            assert var not in os.environ


def test_audio_advanced_offers_longer_replacements_and_wires_them_up(
        tmp_path, monkeypatch):
    """The "Allow replacements longer than the original" option carries out
    to the env var the engine gates on.  The engine reads it from os.environ
    (spawned encode workers inherit that, nothing else), so an option that
    is saved but not wired up would look normal and silently keep trimming.
    It defaults to off."""
    monkeypatch.delenv("PAD_STERN_AUDIO_GROW", raising=False)
    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        assert not w.call("audio.advanced_get")["cfg"].get("audio_grow")
        assert "PAD_STERN_AUDIO_GROW" not in os.environ
        w.run(app._on_audio_advanced_change, {"audio_grow": True})
        assert os.environ.get("PAD_STERN_AUDIO_GROW") == "1"
        assert app._settings["audio_advanced"]["audio_grow"] is True
        w.run(app._on_audio_advanced_change, {})
        assert "PAD_STERN_AUDIO_GROW" not in os.environ


def test_audio_group_duplicates_off_by_default_and_not_remembered(tmp_path):
    """'Group duplicates' starts unchecked and isn't carried across a
    manufacturer switch: it kicks a ~10 s scan, so it must be opt-in each
    session, never restored on."""
    with web_app(tmp_path, mfr="cgc") as w:
        svc = w.window.service("audio")
        assert not svc.audio_group_dups_var.get()
        w.run(lambda: svc.audio_group_dups_var.set(True))
        w.call("ui.pick_manufacturer", "spooky")
        w.call("ui.pick_manufacturer", "cgc")
        w.drain()
        assert not svc.audio_group_dups_var.get()


def test_cgc_trim_lock_engages_only_for_pf_extract(tmp_path):
    """Selecting CGC leaves the Trim/pad checkbox a free toggle; a Pulp
    Fiction extract (fixed-length bank slots) forces trim on and HIDES the
    checkbox (batch 20: mandatory behavior isn't shown as an option); a
    WPC-remake extract (loose WAVs) brings the toggle back."""
    with web_app(tmp_path, mfr="cgc") as w:
        svc = w.window.service("audio")
        cgc = w.window.current_mfr
        # At manufacturer-select (no extract yet) the toggle is free + shown.
        assert w.state("audio")["trim_visible"] is True

        pf = tmp_path / "pf"
        (pf / "data").mkdir(parents=True)
        (pf / "data" / "pfmusic.bnk").write_bytes(b"")
        assert w.run(svc._apply_trim_lock, cgc, str(pf)) is True
        assert w.state("audio")["trim_visible"] is False
        assert svc.audio_trim_var.get() is True

        # A WPC-remake extract unlocks it again, and the saved preference is
        # restored rather than force-set.
        afm = tmp_path / "afm"
        (afm / "afmdata").mkdir(parents=True)
        (afm / "afmdata" / "s1.wav").write_bytes(b"")
        assert w.run(svc._apply_trim_lock, cgc, str(afm), False) is False
        assert w.state("audio")["trim_visible"] is True
        assert svc.audio_trim_var.get() is False


class _Slot:
    def __init__(self, duration):
        self.duration = duration


def test_audio_preview_limit_caps_trimmed_replacement(tmp_path):
    """When Trim/pad is on and a replacement is longer than its slot, the
    Replacement pane stops at the slot length (matching the machine); a slot
    exempted with "Full", trim off, or a shorter replacement is not capped."""
    with web_app(tmp_path, mfr="cgc") as w:
        svc = w.window.service("audio")
        rel = "data/pfmusic/pfmusic_sound_000.wav"

        def _setup():
            svc._by_rel = {rel: _Slot(46.0)}
            svc._assign = {rel: "C:/rep.wav"}
            svc._keep = {}
            svc.audio_trim_var.set(True)
        w.run(_setup)
        limit = svc._compute_preview_limit
        # Trim on + replacement longer than the 46s slot -> capped.
        assert w.run(limit, rel, 61.8) == 46.0
        # Trim off -> no cap even for the replacement.
        w.run(lambda: svc.audio_trim_var.set(False))
        assert w.run(limit, rel, 61.8) is None
        # A slot exempted via the per-slot "Full" flag -> no cap.
        w.run(lambda: svc.audio_trim_var.set(True))
        svc._keep = {rel: True}
        assert w.run(limit, rel, 61.8) is None
        # Replacement SHORTER than the slot -> no cap (padding is silent).
        svc._keep = {}
        assert w.run(limit, rel, 30.0) is None


def test_audio_preview_keeps_a_longer_replacement_whole_when_the_bank_grows(
        tmp_path):
    """With the Stern longer-replacements option on, a replacement longer
    than its slot is kept whole on Write, so the Replacement pane must not
    mark its tail as trimmed: no cap, the original's end marked instead.
    Off, or on Spike 1 (no grow path), it trims exactly as before."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("audio")
        stern = w.window.current_mfr
        rel = "audio/idx0044.wav"

        def _setup():
            svc._by_rel = {rel: _Slot(0.32)}
            svc._assign = {rel: "C:/rep.wav"}
            svc._keep = {}
            svc.audio_trim_var.set(True)
        w.run(_setup)
        svc._advanced = dict(svc._advanced, audio_grow=False)
        assert w.run(svc._compute_preview_limit, rel, 45.6) == 0.32
        assert w.run(svc._preview_grow_from, rel, 45.6) is None

        svc._advanced = dict(svc._advanced, audio_grow=True)
        assert w.run(svc._compute_preview_limit, rel, 45.6) is None
        assert w.run(svc._preview_grow_from, rel, 45.6) == 0.32
        # a replacement that fits its slot has nothing to mark
        assert w.run(svc._preview_grow_from, rel, 0.30) is None

        # Spike 1 has no grow path, so the option does not reach its preview
        stern.set_era("spike1")
        try:
            assert w.run(svc._compute_preview_limit, rel, 45.6) == 0.32
        finally:
            stern.set_era("spike2")


def test_assign_and_clear_write_log_lines(tmp_path):
    """Staging or clearing a replacement writes a log line so a session can
    be double-checked afterwards (feedback batch 11: 'the log does not
    record any replaced video or audio')."""
    folder = _audio_project(tmp_path)
    rep = str(tmp_path / "new_song.wav")
    _wav(rep)
    rel = "audio/idx0001.wav"
    with web_app(tmp_path, mfr="spooky") as w:
        _open_audio(w, folder)
        w.answers.append(rep)
        w.call("audio.choose", rel)
        texts = [e["text"] for e in w.window.log_history()]
        assert "Replace Audio: audio/idx0001.wav ← new_song.wav" in texts
        w.call("audio.menu_action", "remove", rel, [rel])
        texts = [e["text"] for e in w.window.log_history()]
        assert any("cleared replacement for audio/idx0001.wav" in t
                   for t in texts)


# ---------------------------------------------------------------------------
# the project folder, Write
# ---------------------------------------------------------------------------

def test_collect_project_stats_counts_and_changes(tmp_path):
    """The Project Info stats (batch 20): asset counts by kind skip
    bookkeeping dot-dirs, total size includes them, and the Changed row folds
    staged picks + .orig build snapshots together."""
    from pinball_decryptor.core import staged_changes
    from pinball_decryptor.webui.extract_helpers import collect_project_stats

    proj = tmp_path / "proj"
    (proj / "audio").mkdir(parents=True)
    (proj / "audio" / "idx0001.wav").write_bytes(b"x" * 10)
    (proj / "audio" / "idx0002.wav").write_bytes(b"x" * 10)
    (proj / "video").mkdir()
    (proj / "video" / "clip.mp4").write_bytes(b"x" * 30)
    (proj / "images").mkdir()
    (proj / "images" / "logo.png").write_bytes(b"x" * 5)
    (proj / "notes.txt").write_bytes(b"x")
    # Bookkeeping: counts toward size on disk, not toward the asset rows.
    (proj / ".orig" / "audio").mkdir(parents=True)
    (proj / ".orig" / "audio" / "idx0001.wav").write_bytes(b"y" * 10)
    staged_changes.save(str(proj), {"audio": {"audio/idx0002.wav": "r.wav"}})

    rows = dict(collect_project_stats(str(proj)))
    assert rows["Audio"].startswith("2 file(s)")
    assert rows["Video"].startswith("1 file(s)")
    assert rows["Images"].startswith("1 file(s)")
    assert rows["Other files"].startswith("1 file(s)")
    assert "1 staged for the next build" in rows["Changed"]
    assert "1 changed by earlier builds" in rows["Changed"]
    assert "Project started" in rows


def test_sidecar_pending_fallback_without_tab_scan(tmp_path):
    """Assignments recorded in a folder's .staged_changes.json must reach the
    Write staging path even when no Replace tab has scanned that folder this
    session (mods just transferred in, or the app reopened straight onto
    Write): without the sidecar fallback the build silently dropped them."""
    from pinball_decryptor.core import staged_changes

    assets = tmp_path / "extract159"
    (assets / "images").mkdir(parents=True)
    (assets / "images" / "backglass.png").write_bytes(b"STOCK")
    repl = tmp_path / "modded" / "backglass.png"
    repl.parent.mkdir(parents=True)
    repl.write_bytes(b"1987-ART")
    staged_changes.save(str(assets), {
        "image": {"images/backglass.png": str(repl)}})

    with web_app(tmp_path, mfr="stern") as w:
        app = w.app
        # No Replace tab has scanned this folder: the in-memory getter is
        # empty...
        assert w.window.pending_image_assignments(str(assets)) is None
        # ...but the sidecar fallback rebuilds the pending tuple for the build.
        pend = app._sidecar_pending(str(assets), "image")
        assert pend is not None
        slots_by_rel, assignments, keep_size = pend
        assert assignments == {"images/backglass.png": str(repl)}
        assert "images/backglass.png" in slots_by_rel
        assert keep_size == frozenset()
        # A kept-size flag recorded for the pick reaches the build (PAD-154).
        staged_changes.save(str(assets), {
            "image": {"images/backglass.png": str(repl)},
            "image_keep_size": ["images/backglass.png", "images/gone.png"]})
        assert app._sidecar_pending(str(assets), "image")[2] == frozenset(
            {"images/backglass.png"})


def _seed_bof_assets(folder):
    folder.mkdir(parents=True, exist_ok=True)
    marker = "# Update check string\n"
    (folder / "updated_bash_profile").write_text(
        marker + "# 2025.06.23 \n", encoding="utf-8")
    (folder / "updated_updatecode").write_text(
        marker + "# 2025.06.20 \n", encoding="utf-8")
    (folder / ".checksums.md5").write_text("", encoding="utf-8")
    return str(folder)


def test_version_field_auto_shows_concrete_date(tmp_path):
    """BOF's update-version date: Auto (the default) shows the installed
    baseline plus one day, read-only, and is not an override."""
    assets = _seed_bof_assets(tmp_path / "bof")
    with web_app(tmp_path, mfr="bof") as w:
        win = w.window
        w.run(lambda: win.write_assets_var.set(assets))
        w.drain()
        assert win.write_version_auto_var.get() is True
        assert _wait(w, lambda: win.write_version_date_var.get()
                     == "2025.06.24"), win.write_version_date_var.get()
        assert win.write_version_override() is None
        assert win.write_version_validation_error() is None
        # a manual date older than the installed one is refused
        w.call("ui.set", "write", "version_auto", False)
        w.call("ui.set", "write", "version_date", "2025.06.10")
        assert win.write_version_validation_error() is not None


def test_write_output_ext_forces_correct_extension(manufacturers_by_key):
    """Flash-image plugins pin the extension their built image must carry, so
    a user-typed File Name can never come out extensionless or in the wrong
    format: Stern Spike 2 = .raw, CGC = .img.  Whitestar (capture-only) and
    plugins whose build name is looked up by the machine pin nothing."""
    stern = manufacturers_by_key["stern"]
    stern.set_era("spike2")
    try:
        assert stern.write_output_ext() == ".raw"
        # Extensionless -> appended; a recognised card extension -> swapped
        # in place (not stacked into ".img.raw"); already correct -> kept.
        assert stern.force_write_ext("my_mod") == "my_mod.raw"
        assert stern.force_write_ext("game.img") == "game.raw"
        assert stern.force_write_ext("game.bin") == "game.raw"
        assert stern.force_write_ext("game.raw") == "game.raw"
        # An unrecognised trailing extension is appended to, not clobbered,
        # so a dotted name never silently loses a part.
        assert stern.force_write_ext("v1.2.3") == "v1.2.3.raw"
        # Whitestar is MAME capture-only: no build, so no forced extension.
        stern.set_era("whitestar")
        assert stern.write_output_ext() == ""
        assert stern.force_write_ext("whatever") == "whatever"
    finally:
        stern.set_era("spike2")

    cgc = manufacturers_by_key["cgc"]
    assert cgc.write_output_ext() == ".img"
    assert cgc.force_write_ext("installer") == "installer.img"
    assert cgc.force_write_ext("installer.img") == "installer.img"

    # JJP builds a Clonezilla-derived install ISO, so it pins .iso.
    jjp = manufacturers_by_key.get("jjp")
    if jjp is not None:
        assert jjp.write_output_ext() == ".iso"
        assert jjp.force_write_ext("update") == "update.iso"

    # BOF's machine looks the update up by name, so it pins nothing.
    bof = manufacturers_by_key.get("bof")
    if bof is not None:
        assert bof.write_output_ext() == ""
        assert bof.force_write_ext("update") == "update"


def test_write_preview_scan_in_flight_counts_as_changes(tmp_path):
    """Build during a still-running preview scan must not trip the
    "nothing modified" warning: an in-flight scan means "unknown, assume
    changes" (the build diffs everything itself)."""
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("write")

        def _state(scanning):
            svc._rows = []
            svc._scanning = scanning
            return w.window._has_pending_write_changes()
        assert w.run(_state, False) is False
        assert w.run(_state, True) is True
        w.run(_state, False)


def test_compare_tab_gated_by_capability(tmp_path):
    """A manufacturer switch drops any rendered Compare report, so a stale
    diff can't survive under the new manufacturer's name.  (Which
    manufacturers show the tab: test_webui_partitions
    test_tabs_follow_the_capabilities.)"""
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("compare")
        svc._sections = [("Compared", [("Image A", "x.raw")])]
        w.call("ui.pick_manufacturer", "spooky")
        w.drain()
        assert svc._sections == []
        assert w.state("compare")["rows"] == []


def test_image_info_window_closes_on_mfr_switch(tmp_path):
    """Switching manufacturers closes the Image Info window: a JJP header must
    not sit over Stern card details."""
    f = tmp_path / "game.pkg"
    f.write_bytes(b"\0" * 1024)
    with web_app(tmp_path, mfr="spooky") as w:
        w.call("ui.set", "extract", "input", str(f))
        assert w.call("extract.open_image_info") is True
        assert _wait(w, lambda: (w.state("extract")["info"] or {}).get(
            "sections"))
        w.call("ui.pick_manufacturer", "jjp")
        w.drain()
        assert not w.state("extract")["info"]


def _spike1_card():
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "images", "Stern", "spike1", "ghostbusters_le-1_17.iso")


@pytest.mark.skipif(not os.path.isfile(_spike1_card()),
                    reason="Spike 1 sample card not present")
def test_settings_tab_loads_spike1_card():
    """The Default Settings tab decodes a Spike 1 card's operator adjustments
    (from the game ELF) into the all-settings list: the read side of Spike 1
    settings parity."""
    from pinball_decryptor.webui.tabs.defaults import read_image
    got = read_image(_spike1_card())
    assert got[0] == "ok_spike1", got
    rows = got[1]
    assert len(rows) > 100                      # GBLE carries ~175 adjustments
    r0 = rows[0]
    assert set(r0) >= {"id", "name", "label", "default", "min", "max", "step"}
    assert r0["name"].startswith("AD_")         # stable synthetic key
    # a real firmware label made it through (not a raw AD_ id)
    assert any("VOLUME" in r["label"].upper() or "COIN" in r["label"].upper()
               for r in rows)


# ---------------------------------------------------------------------------
# Replace Images: "Group by scene"
# ---------------------------------------------------------------------------

def _seed_image_assets(tmp_path):
    """An assets folder with three radium-frame PNGs (one animation), one
    loose PNG, the extractor manifests describing them, and a baseline."""
    st = tmp_path / "images" / "scene_textures"
    st.mkdir(parents=True)
    # The slicer's glyphs dir marks this as a modern extract: name hints
    # are only trusted when the extractor recorded which members are fonts.
    (st / "glyphs").mkdir()
    frames = ["radimg_Char_Select_8x8_00000001.png",
              "radimg_Char_Select_8x8_00000002.png",
              "radimg_8x8_00000003.png"]
    for fn in frames:
        (st / fn).write_bytes(b"\x89PNG-fake")
    (tmp_path / "images" / "loose").mkdir()
    (tmp_path / "images" / "loose" / "logo.png").write_bytes(b"\x89PNG-fake")
    card = "/game/scenes/a1b2c3d4e5f6/scene.radium"
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        # File order is NOT play order: offsets 300, 100, 200.
        f.write("scene_textures/%s\t%s\t300\t16\t8\t8\t5\n" % (frames[2], card))
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (frames[0], card))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (frames[1], card))
    with open(tmp_path / "images" / "manifest.txt", "w",
              encoding="utf-8") as f:
        f.write("# output\tcard path\tbytes\n")
        f.write("loose/logo.png\t/game/assets/loose/logo.png\t9\n")
    (tmp_path / ".checksums.md5").write_text("", encoding="utf-8")
    return str(tmp_path)


def test_image_group_scan_parses_manifests(tmp_path):
    """The manifest parser groups radium frames under their container with a
    friendly element-name label, counts dedup occurrences, and yields nothing
    for a folder with no manifests."""
    from pinball_decryptor.webui.tabs.images import scan_image_groups
    assets = _seed_image_assets(tmp_path)
    groups, occ, _where = scan_image_groups(assets)
    key = "rad::/game/scenes/a1b2c3d4e5f6/scene.radium"
    rel1 = "images/scene_textures/radimg_Char_Select_8x8_00000001.png"
    # Label = element hint + searchable container-hash shorthand: hints
    # repeat across sibling containers, so the hash half disambiguates.
    assert groups[rel1] == (key, "Char_Select · a1b2c3d4", 100)
    # The nameless frame inherits the group label; order = its data offset.
    rel3 = "images/scene_textures/radimg_8x8_00000003.png"
    assert groups[rel3] == (key, "Char_Select · a1b2c3d4", 300)
    assert occ[rel1] == 1
    # Group KEY keeps the manifest's leading slash (so saved tags match); the
    # display LABEL drops it for consistency with the other tabs (a tester).
    assert groups["images/loose/logo.png"] == (
        "dir::/game/assets/loose", "game/assets/loose", 0)
    empty = tmp_path / "no_manifests"
    empty.mkdir()
    assert scan_image_groups(str(empty)) == ({}, {}, {})


def test_image_group_label_skips_font_atlases(tmp_path):
    """A scene whose first named member is a FONT atlas must not be labeled
    after the font (Stern names fonts "Stern_...", so every hash-named member
    matched a search for "stern" through the invisible label: a tester).
    The hint comes from the first non-atlas named member, or falls back to
    the hash shorthand when the font is the only named member."""
    from pinball_decryptor.webui.tabs.images import scan_image_groups
    st = tmp_path / "images" / "scene_textures"
    st.mkdir(parents=True)
    atlas = "radimg_Stern_FooFont_512x512_deadbeef.png"
    named = "radimg_Char_Select_8x8_00000001.png"
    plain = "radimg_8x8_00000002.png"
    for fn in (atlas, named, plain):
        (st / fn).write_bytes(b"\x89PNG-fake")
    # What marks the atlas as a font: its extracted glyphs/<stem>/ dir.
    (st / "glyphs" / atlas[:-4]).mkdir(parents=True)
    card_a = "/game/scenes/aaaaaaaa1111/scene.radium"
    card_b = "/game/scenes/bbbbbbbb2222/scene.radium"
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        # Scene A: font first (offset 100), real named element later.
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (atlas, card_a))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (named, card_a))
        # Scene B: the font is the ONLY named member.
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (atlas, card_b))
        f.write("scene_textures/%s\t%s\t200\t16\t8\t8\t5\n" % (plain, card_b))
    groups, _occ, where = scan_image_groups(str(tmp_path))
    rel_named = "images/scene_textures/" + named
    rel_plain = "images/scene_textures/" + plain
    assert groups[rel_named][1] == "Char_Select · aaaaaaaa"
    assert groups[rel_plain][1] == "bbbbbbbb"
    # The atlas itself keeps its membership (home = scene A): only the
    # label derivation skips it.
    rel_atlas = "images/scene_textures/" + atlas
    assert [g[0] for g in where[rel_atlas]] == [
        "rad::" + card_a, "rad::" + card_b]


def _png(path, size=(8, 8), color=(200, 30, 30, 255)):
    from PIL import Image
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    Image.new("RGBA", size, color).save(str(path))


def _seed_shared_image_assets(tmp_path):
    """Two scenes that share one image: the extract dedupes it to a single
    PNG whose HOME group is the first scene, so the second scene owns no
    first-occurrence row at all (a tester's training scene)."""
    st = tmp_path / "images" / "scene_textures"
    shared = "radimg_Logo_8x8_000000aa.png"
    own = "radimg_Only_8x8_000000bb.png"
    _png(st / shared)
    _png(st / own, color=(30, 200, 30, 255))
    home = "/game/scenes/aaaaaaaa1111/scene.radium"
    other = "/game/scenes/bbbbbbbb2222/scene.radium"
    with open(st / "radium_images.txt", "w", encoding="utf-8") as f:
        f.write("# output\tradium card path\tdata offset\tlength"
                "\tpad_w\tpad_h\tfmt\n")
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (shared, home))
        f.write("scene_textures/%s\t%s\t100\t16\t8\t8\t5\n" % (own, home))
        # The second scene draws ONLY the shared image: nothing is first
        # seen here, so before the fix this scene had no rows anywhere.
        f.write("scene_textures/%s\t%s\t400\t16\t8\t8\t5\n" % (shared, other))
    from pinball_decryptor.core import checksums
    checksums.generate_checksums(str(tmp_path))
    return str(tmp_path), "images/scene_textures/" + shared


def _images_open(w, assets):
    def _set():
        try:
            w.window.write_assets_var.set(assets)
        except Exception:                                # noqa: BLE001
            pass
    w.run(_set)
    w.call("images.scan")
    assert _wait(w, lambda: not w.state("images").get("scanning")
                 and w.state("images").get("total")), w.state("images")


def _group_heads(w):
    return [e["g"] for e in w.state("images")["view"] if isinstance(e, dict)]


def test_image_search_finds_scene_by_any_occurrence(tmp_path, monkeypatch):
    """Searching a scene id finds the images that scene draws even when they
    are filed under another scene, and shows them UNDER the scene searched
    for."""
    pytest.importorskip("PIL")
    from pinball_decryptor.core import tag_library
    from pinball_decryptor.webui.tabs.images import scan_image_groups
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "tag_library.json"))
    assets, shared = _seed_shared_image_assets(tmp_path / "gz")
    groups, occ, where = scan_image_groups(assets)
    home_key = "rad::/game/scenes/aaaaaaaa1111/scene.radium"
    other_key = "rad::/game/scenes/bbbbbbbb2222/scene.radium"
    # One home group, but both containers recorded, home first.
    assert groups[shared][0] == home_key
    assert [g[0] for g in where[shared]] == [home_key, other_key]
    assert occ[shared] == 2

    with web_app(tmp_path, mfr="stern") as w:
        _images_open(w, assets)
        svc = w.window.service("images")
        w.call("images.set_grouped", True)
        # The second scene's id now finds its image, grouped under THAT scene.
        w.call("ui.set", "images", "search", "bbbbbbbb")
        assert _group_heads(w) == [other_key]
        assert svc._view_groups[other_key] == [shared]
        # The full on-card scene hash (what a file listing shows) works too.
        w.call("ui.set", "images", "search", "bbbbbbbb2222")
        assert _group_heads(w) == [other_key]
        # Its home scene still lists it, alongside the image only it has.
        w.call("ui.set", "images", "search", "aaaaaaaa")
        assert _group_heads(w) == [home_key]
        assert len(svc._view_groups[home_key]) == 2
        # Flat mode searches scenes too (it used to match paths only).
        w.call("images.set_grouped", False)
        w.call("ui.set", "images", "search", "bbbbbbbb")
        st = w.state("images")
        assert [svc._slots[i].rel_path for i in st["view"]] == [shared]
        w.call("ui.set", "images", "search", "")


def test_group_tags_reseed_across_reextract(tmp_path, monkeypatch):
    """A group name given one extract is restored when the SAME card is
    re-extracted to a fresh folder (a tester: tags lost on re-extract).  The
    per-card library is keyed by the source card's file name, so only the
    same-version card seeds; the fresh folder's sidecar also gets the name so
    it rides Mod Transfer / reopen.  A blank rename restores the manifest
    label and drops the tag."""
    pytest.importorskip("PIL")
    from pinball_decryptor.core import (extract_source, staged_changes,
                                        tag_library)
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "settings" / "group_tags.json"))
    card = tmp_path / "turtles_pro-1_59_0.Release.8G.sdcard.raw"
    card.write_bytes(b"\x00" * 32)
    key = "rad::/game/scenes/aaaaaaaa1111/scene.radium"

    a, _shared = _seed_shared_image_assets(tmp_path / "A")
    extract_source.write_extract_source(a, str(card))
    b, _shared = _seed_shared_image_assets(tmp_path / "B")
    extract_source.write_extract_source(b, str(card))
    with web_app(tmp_path, mfr="stern") as w:
        svc = w.window.service("images")
        # First extract: rename a group -> sidecar AND the card library.
        _images_open(w, a)
        w.call("images.rename_group", key, "Boss Intro")
        assert tag_library.load() == {
            "turtles_pro-1_59_0.release.8g.sdcard.raw": {key: "Boss Intro"}}
        assert staged_changes.load(a)["image_group_tags"] == {
            key: "Boss Intro"}

        # Second extract of the same card to a blank folder: name comes back.
        assert not staged_changes.load(b).get("image_group_tags")
        _images_open(w, b)
        assert svc._group_tags.get(key) == "Boss Intro"
        assert staged_changes.load(b).get("image_group_tags") == {
            key: "Boss Intro"}
        w.call("images.set_grouped", True)
        heads = [e for e in w.state("images")["view"] if isinstance(e, dict)]
        assert [h["l"] for h in heads if h["g"] == key] == ["Boss Intro"]

        # A blank rename restores the manifest label and drops the tag.
        w.call("images.rename_group", key, "")
        heads = [e for e in w.state("images")["view"] if isinstance(e, dict)]
        assert [h["l"] for h in heads if h["g"] == key] != ["Boss Intro"]
        assert not staged_changes.load(b).get("image_group_tags")


def test_one_row_still_clears_without_a_confirm(tmp_path, monkeypatch):
    """The per-row menu entry is the shared clear path with a selection of
    one, and it must not have grown a dialog: it was a single click before
    (PAD-128)."""
    pytest.importorskip("PIL")
    from pinball_decryptor.core import tag_library
    monkeypatch.setattr(tag_library, "LIBRARY_FILE",
                        str(tmp_path / "tag_library.json"))
    assets, _shared = _seed_shared_image_assets(tmp_path / "gz")
    rep = tmp_path / "mine" / "mine.png"
    _png(rep, color=(1, 2, 3, 255))
    with web_app(tmp_path, mfr="stern") as w:
        _images_open(w, assets)
        svc = w.window.service("images")
        rels = sorted(s.rel_path for s in svc._slots)
        for rel in rels:
            w.answers = [str(rep)]
            w.call("images.choose", rel)
        asked = len(w.asked)
        assert w.call("images.act", "clear_one", rels[0], [rels[0]]) == 1
        assert len(w.asked) == asked, w.asked[asked:]
        pend = w.window.pending_image_assignments(assets)
        assert sorted(pend[1]) == rels[1:]
        texts = [e["text"] for e in w.window.log_history()]
        assert any("cleared replacement for %s" % rels[0] in t for t in texts)


# ---------------------------------------------------------------------------
# Replace Video: the Convert column and the preview still
# ---------------------------------------------------------------------------

def test_video_convert_column_reports_as_is_vs_reencode(tmp_path):
    """The video list says what Write will DO with each assigned clip, instead
    of leaving it in the log at pick time (feedback batch 22)."""
    from pinball_decryptor.core.video_slots import VideoSlot
    from pinball_decryptor.webui import video_helpers as vh
    slot = VideoSlot(rel_path="video/a.mov",
                     abs_path=str(tmp_path / "a.mov"),
                     ext=".mov", info=None, size=1)
    rep = tmp_path / "rep.mov"
    rep.write_bytes(b"x")
    # "No conversion" on + matching container = copied through verbatim.
    assert vh.conv_mode(slot, str(rep), True, False) == vh.CONV_ASIS
    # ...and a container the copy-through would reject NAMES what it needs
    # (this used to report nothing at all: batch 23).
    other = tmp_path / "rep.mp4"
    other.write_bytes(b"x")
    assert vh.conv_mode(slot, str(other), True, False) == \
        vh.CONV_WRONG_TYPE % ".mov"
    # Unassigned rows stay blank.
    assert vh.conv_mode(slot, None, True, False) == ""


def _frame_png(color):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (32, 18), color).save(buf, "PNG")
    return buf.getvalue()


def _fake_frames(monkeypatch, answers):
    """Stand in for ffmpeg: each extract_frame_png call returns the next of
    *answers* and records the position it was asked for."""
    from pinball_decryptor.core import video
    asked = []
    queue = list(answers)

    def fake(path, pos, w, h):
        asked.append(pos)
        return queue.pop(0) if queue else None
    monkeypatch.setattr(video, "extract_frame_png", fake)
    return asked


def test_video_poster_keeps_looking_when_the_frame_is_black(tmp_path,
                                                            monkeypatch):
    """A black still and a broken preview look identical, which is exactly
    what a field report couldn't tell apart.  Sample on past a black frame,
    and when the clip really is black everywhere, say so instead of leaving a
    bare black rectangle."""
    pytest.importorskip("PIL")
    from pinball_decryptor.webui import video_helpers as vh
    clip = str(tmp_path / "clip.mp4")
    # Black frame + somewhere else to look -> try the next spot, and a frame
    # with picture in it is the still, no note.
    asked = _fake_frames(monkeypatch, [_frame_png((0, 0, 0)),
                                       _frame_png((10, 90, 200))])
    poster, note = vh.representative_poster(clip, dur=10.0)
    assert asked == [pytest.approx(5.0), pytest.approx(2.5)]
    assert poster and os.path.isfile(poster) and note == ""
    # Black everywhere we looked -> a note, not an empty pane.
    black = _frame_png((0, 0, 0))
    _fake_frames(monkeypatch, [black] * 5)
    poster, note = vh.representative_poster(clip, dur=10.0)
    assert poster is None and note == vh.NOTE_ALL_BLACK
    assert "Every frame sampled is black" in note


def test_video_poster_does_not_seek_past_a_short_clip():
    """463 of Batman's 6331 clips are under 0.2 s (a one-frame still is
    1/30 s).  A blind 0.5 s offset landed past their last frame, ffmpeg
    returned nothing, and the pane told a field reporter his file couldn't be
    decoded, for a clip that is perfectly fine, just short."""
    from pinball_decryptor.webui import video_helpers as vh
    assert vh.poster_spots(0.033333) == [0.0]   # its first frame IS the clip
    # Duration unknown: still guess 0.5 s in, but frame 0 now backs it up.
    assert vh.poster_spots(0.0) == [0.5, 0.0]
    # A normal clip keeps its mid-clip sampling, 0.0 as the last resort.
    assert vh.poster_spots(10.0) == pytest.approx([5.0, 2.5, 7.5, 0.8, 0.0])


def test_video_poster_tries_the_next_spot_when_a_seek_decodes_nothing(
        tmp_path, monkeypatch):
    """A duration that overstates the clip makes ffmpeg return no frame at
    all.  That is a bad offset, not a bad file: keep sampling."""
    pytest.importorskip("PIL")
    from pinball_decryptor.webui import video_helpers as vh
    asked = _fake_frames(monkeypatch, [None, _frame_png((10, 90, 200))])
    poster, note = vh.representative_poster(str(tmp_path / "clip.mp4"),
                                            dur=10.0)
    assert asked == [pytest.approx(5.0), pytest.approx(2.5)]
    assert poster and note == ""


def test_video_poster_explains_a_frame_it_cannot_show(tmp_path, monkeypatch):
    """A dead decode must not fall through to a silent black pane: it has to
    name itself."""
    from pinball_decryptor.core import video
    from pinball_decryptor.webui import video_helpers as vh
    _fake_frames(monkeypatch, [])                  # ffmpeg gives us nothing
    monkeypatch.setattr(video, "find_ffmpeg", lambda: "ffmpeg")
    poster, note = vh.representative_poster(str(tmp_path / "clip.mp4"),
                                            dur=10.0)
    assert poster is None and note == vh.NOTE_NO_FRAME
