"""The app-wide menus, windows and banners on the web UI (service "shellx").

Each test builds the real WebApp in-process (tests/webui_harness.py) and
drives the shellx service the way the page does: ui.settings_action for the
gear menu, ui.banner_action for the banners, shellx.* for the windows.
Modal questions are answered by ``w.answers``.
"""

import json
import os
import time

import pytest

from tests.webui_harness import web_app

MY_EXPORTS = ("voice_quality_var", "update_interval_var",
              "set_update_check_running", "show_update_banner",
              "show_up_to_date_toast", "open_update_download_dialog")


def until(w, pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        w.drain()
        if pred():
            return True
        time.sleep(0.05)
    return False


def settings_of(tmp_path):
    return json.loads((tmp_path / "cfg" / "settings.json").read_text(
        encoding="utf-8"))


def _flat(rows):
    for it in rows:
        yield it
        yield from _flat(it.get("submenu") or ())


def items(w):
    """Every gear-menu row, the cascades' rows included."""
    return list(_flat(w.state("shell")["settings_items"]))


def cascade(w, label):
    for it in w.state("shell")["settings_items"]:
        if it.get("submenu") is not None and it.get("label") == label:
            return it
    return None


def item(w, iid, **match):
    for it in items(w):
        if it.get("id") == iid and all(it.get(k) == v
                                       for k, v in match.items()):
            return it
    return None


# ------------------------------------------------------------ exports
def _mfr_keys():
    from pinball_decryptor.core.registry import all_manufacturers, load_plugins
    load_plugins()
    return {m.key for m in all_manufacturers()}


@pytest.mark.parametrize("mfr", ["stern", "jjp", "spooky", "pb", "williams",
                                 "cgc", "dp", "ap", "bof", "data_east",
                                 "sega"])
def test_my_exports_exist_for_every_manufacturer(tmp_path, mfr):
    if mfr not in _mfr_keys():
        pytest.skip("no %s plugin" % mfr)
    with web_app(tmp_path, mfr=mfr) as w:
        win = w.window
        svc = win.service("shellx")
        for name in MY_EXPORTS:
            assert getattr(win, name) == getattr(svc, name)
        stand_ins = set((getattr(win, "missing_exports", None) or {}))
        assert not stand_ins & set(MY_EXPORTS)
        # never a rail tab
        assert all(t["ns"] != "shellx" or not t["visible"]
                   for t in w.state("shell")["tabs"])
        # the gear menu is there for every manufacturer
        assert item(w, "check_updates") is not None
        assert item(w, "view_disclaimer") is not None


def test_stern_eras_keep_the_menu(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        for era in ("spike1", "whitestar", "spike2"):
            w.call("ui.set_era", era)
            assert item(w, "preview_features") is not None
            hints = w.state("shellx")["prereq_hints"]
            names = [p.name for p in w.window.current_mfr.prerequisites]
            assert set(hints) == set(names)


def test_menu_choices():
    """The gear menu's cascades: the voice models the transcriber knows,
    and the update intervals the run logic normalises to."""
    from pinball_decryptor.core.transcribe import _MODEL_APPROX_MB
    from pinball_decryptor.webui import update_interval as ui
    from pinball_decryptor.webui.tabs import shell_extras as sx
    assert [m for m, _ in sx.VOICE_QUALITY_CHOICES] == [
        "tiny.en", "small.en", "medium.en"]
    assert all(m in _MODEL_APPROX_MB for m, _ in sx.VOICE_QUALITY_CHOICES)
    assert sx.UPDATE_INTERVAL_CHOICES is ui.UPDATE_INTERVAL_CHOICES
    assert ui.UPDATE_INTERVAL_DEFAULT in dict(ui.UPDATE_INTERVAL_CHOICES)
    for hours, _label in ui.UPDATE_INTERVAL_CHOICES:
        assert ui.normalize_update_interval(hours) == hours
    for junk in (None, "", "6h", 5, -1):
        assert ui.normalize_update_interval(junk) == \
            ui.UPDATE_INTERVAL_DEFAULT


# ---------------------------------------------------------- gear menu
def test_gear_menu_keeps_the_tk_cascades(tmp_path):
    """_build_settings_menu's order and cascades: Check automatically ▸,
    Logs ▸, Voice recognition quality ▸ and the prerequisites summary ▸;
    the plain entries stay top-level."""
    import sys
    with web_app(tmp_path, mfr="stern") as w:
        top = w.state("shell")["settings_items"]
        shape = [("sep" if it.get("sep") else
                  (it.get("label") + " ▸") if it.get("submenu") is not None
                  else it.get("id")) for it in top]
        want = ["check_updates", "Check automatically ▸"]
        if sys.platform == "win32":
            want.append("disk_space")
        want += ["Logs ▸", "sep", "Voice recognition quality ▸", "sep",
                 "Prerequisites ▸", "sep", "preview_features",
                 "view_disclaimer"]
        assert shape == want
        assert not any(it.get("header") for it in items(w))
        up = cascade(w, "Check automatically")["submenu"]
        assert [it["label"] for it in up] == [
            "Only at startup", "Every hour", "Every 6 hours", "Once a day"]
        assert all(it["id"] == "update_interval" and it["radio"]
                   for it in up)
        logs = cascade(w, "Logs")["submenu"]
        assert [it["id"] for it in logs] == [
            "log_history", "project_log", "toggle_log_history"]
        vq = cascade(w, "Voice recognition quality")["submenu"]
        assert [it.get("id") or "sep" for it in vq] == [
            "voice_quality", "voice_quality", "voice_quality", "sep",
            "clear_voice_models"]
        assert vq[-1]["needs_idle"]
        pre = cascade(w, "Prerequisites")
        assert pre["prereq_summary"]            # the page shows the summary
        ids = [it["id"] for it in pre["submenu"]]
        assert ids == (["recheck_prereqs"] if sys.platform == "darwin"
                       else ["recheck_prereqs", "install_prereqs"])
        # a found update still leads, above the cascades
        w.run(lambda: w.window.show_update_banner("9.9.9", "u"))
        top = w.state("shell")["settings_items"]
        assert top[0]["id"] == "download_update" and top[0]["dot"]
        assert top[1].get("sep")


def test_update_interval_and_voice_quality(tmp_path):
    with web_app(tmp_path, mfr="stern",
                 settings={"update_check_hours": 24,
                           "voice_quality": "small.en"}) as w:
        win = w.window
        assert win.update_interval_var.get() == 24
        assert win.voice_quality_var.get() == "small.en"
        assert item(w, "update_interval", args=[24])["checked"]
        w.call("ui.settings_action", "update_interval", 1)
        assert win.update_interval_var.get() == 1
        assert settings_of(tmp_path)["update_check_hours"] == 1
        assert item(w, "update_interval", args=[1])["checked"]
        assert not item(w, "update_interval", args=[24])["checked"]
        w.call("ui.settings_action", "voice_quality", "medium.en")
        assert win.voice_quality_var.get() == "medium.en"
        assert settings_of(tmp_path)["voice_quality"] == "medium.en"
        assert item(w, "voice_quality", args=["medium.en"])["checked"]


def test_update_check_busy_label(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.run(w.window.set_update_check_running, True)
        it = item(w, "check_updates")
        assert it["label"] == "Checking for updates…" and it["disabled"]
        w.run(w.window.set_update_check_running, False)
        it = item(w, "check_updates")
        assert it["label"] == "Check for updates" and not it["disabled"]


def test_log_history_toggle_and_seed(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    from pinball_decryptor.core import session_log
    (logs / "session.log").write_text(
        session_log.BANNER_PREFIX + "0.1 =====\nold line one\nold line two\n",
        encoding="utf-8")
    with web_app(tmp_path, mfr="stern") as w:
        seed = w.state("shellx")["log_seed"]
        assert seed and "old line two" in seed["lines"]
        assert "earlier sessions above" in seed["cut"]
        assert item(w, "toggle_log_history")["checked"] is True
        w.call("ui.settings_action", "toggle_log_history")
        assert w.state("shellx")["log_seed"] is None
        assert settings_of(tmp_path)["show_log_history"] is False
        assert item(w, "toggle_log_history")["checked"] is False
        w.call("ui.settings_action", "toggle_log_history")
        assert w.state("shellx")["log_seed"]


def test_log_views_and_save(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        w.call("ui.settings_action", "project_log")
        assert w.asked[-1]["title"] == "This project's log"
        out = tmp_path / "saved.txt"
        w.answers.append(str(out))
        assert w.call("shellx.save_log", "[12:00:00] hello") is True
        assert out.read_text(encoding="utf-8") == "[12:00:00] hello"
        assert w.asked[-1]["kind"] == "file"
        assert w.asked[-1]["title"] == "Save log as…"


def test_clear_voice_models_asks_first(tmp_path, monkeypatch):
    import pinball_decryptor.core.transcribe as tr
    called = []
    monkeypatch.setattr(tr, "clear_whisper_cache",
                        lambda: called.append(1) or (0, 0))
    with web_app(tmp_path, mfr="stern") as w:
        w.answers.append("no")
        w.call("ui.settings_action", "clear_voice_models")
        assert not called
        w.answers.extend(["yes", "ok"])
        w.call("ui.settings_action", "clear_voice_models")
        assert called
        assert w.asked[-1]["message"] == "No downloaded voice models found."


def test_prereq_actions(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        seen = []
        win.cb["on_recheck_prereqs"] = lambda: seen.append("recheck")

        def fake_install():
            # the run logic asks with app.messagebox, which is the page's
            from pinball_decryptor import app as app_module
            app_module.messagebox.showinfo("Install Prerequisites", "hello")
            seen.append("install")
        win.cb["on_install_prereqs"] = fake_install
        w.call("ui.settings_action", "recheck_prereqs")
        w.call("shellx.install_prereqs")
        assert seen == ["recheck", "install"]
        assert w.asked[-1]["title"] == "Install Prerequisites"
        from pinball_decryptor import app as app_module
        from pinball_decryptor.webui import compat
        assert app_module.messagebox is compat.messagebox
        assert w.state("shell")["prereq_buttons"] == (os.sys.platform
                                                      != "darwin")


# ------------------------------------------------------------ updates
def test_update_banner_dismiss_and_newer(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        win.cb["on_install_update"] = lambda v, inst: None
        w.run(lambda: win.show_update_banner(
            "9.9.9", "https://example.invalid/r", installer={"kind": "setup"}))
        banners = {b["id"]: b for b in w.state("shell")["banners"]}
        b = banners["update"]
        assert "v9.9.9 is available" in b["text"]
        assert [a["label"] for a in b["actions"]] == ["Install update",
                                                      "Release notes"]
        assert w.state("shell")["update"]["available"]
        assert item(w, "install_update")["label"] == "Install update v9.9.9…"
        assert w.state("shell")["gear_dots"]["update"]
        w.call("ui.banner_action", "update", "dismiss")
        assert "update" not in {b["id"] for b in w.state("shell")["banners"]}
        # the repeating check does not bring the same version back ...
        w.run(lambda: win.show_update_banner("9.9.9", "u", installer=None))
        assert "update" not in {b["id"] for b in w.state("shell")["banners"]}
        assert item(w, "download_update") is not None
        # ... a newer one does, with the plain Download button (no installer)
        w.run(lambda: win.show_update_banner("9.9.10", "u2"))
        b = {b["id"]: b for b in w.state("shell")["banners"]}["update"]
        assert [a["label"] for a in b["actions"]] == ["Download"]


def test_install_update_hands_off(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        win = w.window
        got = []
        win.cb["on_install_update"] = lambda v, inst: got.append((v, inst))
        w.run(lambda: win.show_update_banner("9.9.9", "u",
                                             installer={"kind": "appimage"}))
        b = {b["id"]: b for b in w.state("shell")["banners"]}["update"]
        assert b["actions"][0]["label"] == "Download update"
        w.call("ui.banner_action", "update", "install")
        w.call("ui.settings_action", "install_update")
        assert got == [("9.9.9", {"kind": "appimage"})] * 2


def test_up_to_date_answer(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        from pinball_decryptor import __version__
        w.run(w.window.show_up_to_date_toast)
        assert w.asked[-1]["title"] == "Up to date"
        assert w.asked[-1]["message"] == (
            "You're on the latest version (v%s)." % __version__)
        assert w.state("shellx")["update_state"] == "latest"


def test_log_link_opens_the_url_or_says_it_cannot(tmp_path, monkeypatch):
    """The log's link line (the update check's "Download: <url>") is a page
    call, and like Tk's open_link it opens off the loop; when nothing can,
    the URL goes to the clipboard and "Couldn't open your browser" says
    so."""
    from pinball_decryptor.core import desktop
    opened = []
    with web_app(tmp_path, mfr="stern") as w:
        assert "shellx.open_link" in w.ctx.registry.names()
        monkeypatch.setattr(desktop, "open_url",
                            lambda url, env=None: (opened.append(url)
                                                   or (True, "")))
        assert w.call("shellx.open_link", "https://example.invalid/r")
        assert until(w, lambda: opened == ["https://example.invalid/r"])
        time.sleep(0.2)
        w.drain()
        assert not [a for a in w.asked
                    if a.get("title") == "Couldn't open your browser"]
        seq = w.ctx.bus.last_seq
        monkeypatch.setattr(desktop, "open_url",
                            lambda url, env=None: (False, "no opener"))
        assert w.call("shellx.open_link", "https://example.invalid/r2")
        assert until(w, lambda: any(
            a.get("title") == "Couldn't open your browser" for a in w.asked))
        box = [a for a in w.asked
               if a.get("title") == "Couldn't open your browser"][-1]
        assert "https://example.invalid/r2" in box["message"]
        assert "copied to your clipboard" in box["message"]
        assert "no opener" in box["message"]
        events = [json.loads(t) for _s, t in w.ctx.bus.since(seq)[0]]
        assert {"t": "clipboard", "text": "https://example.invalid/r2"} in [
            {k: e.get(k) for k in ("t", "text")} for e in events]
        assert w.call("shellx.open_link", "") is False


def test_first_run_theme_follows_the_os(tmp_path, monkeypatch):
    """MainWindow: initial_theme or detect_system_theme(), persisted with
    the next save; a saved theme wins."""
    from pinball_decryptor.webui import theme as tk_theme
    monkeypatch.setattr(tk_theme, "detect_system_theme", lambda: "light")
    with web_app(tmp_path, mfr="stern") as w:
        w.drain()
        assert w.state("shell")["theme"] == "light"
        assert w.window._current_theme == "light"
        w.run(w.app._save_settings)
        assert settings_of(tmp_path)["theme"] == "light"
    other = tmp_path / "second"
    other.mkdir()
    with web_app(other, mfr="stern", settings={"theme": "dark"}) as w:
        w.drain()
        assert w.state("shell")["theme"] == "dark"
        assert w.window._current_theme == "dark"


def test_tab_changes_come_from_the_window(tmp_path):
    """The window fans on_tab_changed itself (fans_tab_changes); shellx
    no longer wraps select_tab."""
    with web_app(tmp_path, mfr="stern") as w:
        assert "select_tab" not in vars(w.window)
        assert not hasattr(w.window.service("shellx"), "_hook_tab_changes")


def test_download_dialog_handle(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        cancelled = []
        h = w.run(lambda: w.window.open_update_download_dialog(
            "9.9.9", lambda: cancelled.append(1)))
        d = w.state("shellx")["download"]
        assert d["text"] == "Downloading Pinball Asset Decryptor v9.9.9…"
        assert d["detail"] == "Starting download…"
        w.run(h.set_progress, 38 * 1048576, 112 * 1048576)
        d = w.state("shellx")["download"]
        assert d["detail"] == "38 of 112 MB" and d["pct"] == 33
        w.run(h.set_progress, 5 * 1048576, 0)
        assert w.state("shellx")["download"]["detail"] == "5 MB"
        w.call("shellx.download_cancel")
        assert cancelled == [1]
        assert w.state("shellx")["download"]["detail"] == "Cancelling…"
        w.run(h.close)
        assert w.state("shellx")["download"] is None


# --------------------------------------------------- stale source banner
def test_stale_source_banner_on_asset_tabs(tmp_path):
    from pinball_decryptor.core.extract_source import (stale_dismissed,
                                                       write_extract_source)
    proj = tmp_path / "proj"
    proj.mkdir()
    img = tmp_path / "card.img"
    img.write_bytes(b"a" * 100)
    write_extract_source(str(proj), str(img))
    time.sleep(1.1)
    img.write_bytes(b"b" * 200)
    with web_app(tmp_path, mfr="stern") as w:
        svc_write = w.window.service("write")
        if svc_write is None or not getattr(svc_write, "_visible", False):
            pytest.skip("no Write tab yet")
        var = w.window._exports.get("write_assets_var")
        if var is None:
            pytest.skip("write_assets_var not ported yet")
        w.run(lambda: w.window.write_assets_var.set(str(proj)))

        def banner():
            return {b["id"]: b for b in w.state("shell")["banners"]}.get(
                "stale_source")
        w.call("ui.select_tab", "write")
        assert until(w, lambda: banner() is not None)
        assert "card.img" in banner()["text"]
        w.call("ui.select_tab", "extract")
        assert until(w, lambda: banner() is None)
        w.call("ui.select_tab", "write")
        assert until(w, lambda: banner() is not None)
        w.call("ui.banner_action", "stale_source", "dismiss_source")
        assert banner() is None
        assert stale_dismissed(str(proj))
        w.call("ui.select_tab", "audio")
        time.sleep(0.3)
        w.drain()
        assert banner() is None


# ---------------------------------------------------------------- tips
def test_tips_for_each_visible_tab(tmp_path):
    from pinball_decryptor.webui.help_content import (GENERAL_CONTENT,
                                                      sections_for)
    with web_app(tmp_path, mfr="stern") as w:
        t = w.call("shellx.tips")
        assert t["title"] == "Tips — %s" % t["tab"]
        assert len(t["general"]) == len(GENERAL_CONTENT)
        for tab in t["tabs"]:
            got = w.call("shellx.tips", tab["key"])
            assert [s[0] for s in got["sections"]] == [
                s[0] for s in sections_for(tab["key"])]
        w.call("ui.settings_action", "tips")      # opens without error


# ----------------------------------------------------------- disclaimer
def test_disclaimer_text(tmp_path):
    from pinball_decryptor.webui.disclaimer_text import (DISCLAIMER_BODY,
                                                         DISCLAIMER_TITLE)
    with web_app(tmp_path, mfr="stern") as w:
        sh = w.state("shell")
        assert sh["disclaimer_text"] == DISCLAIMER_BODY
        assert sh["disclaimer_title"] == DISCLAIMER_TITLE
        w.call("ui.settings_action", "view_disclaimer")


# --------------------------------------------------------------- preview
def test_preview_features_window(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        st = w.call("shellx.preview_state")
        assert st["title"] == "Preview features"
        assert st["rows"] == []
        r = w.call("shellx.preview_unlock", "not a code")
        assert r["ok"] is False and r["message"]
        r = w.call("shellx.preview_remove", None)
        assert r["message"] == "Pick a code in the list first, then Remove."


# -------------------------------------------------------------- picker
def test_picker_cards(tmp_path):
    with web_app(tmp_path) as w:
        cards = {c["key"]: c for c in w.state("shellx")["picker"]}
        assert set(cards) == {m.key for m in w.window.manufacturers}
        for m in w.window.manufacturers:
            c = cards[m.key]
            assert c["stats"].startswith("%d game" % len(m.games))
            unsup = [g for g in c["games"] if not g["supported"]]
            n = sum(1 for g in m.games if not g.supported)
            assert len(unsup) == n
            if n:
                assert "%d unsupported" % n in c["stats"]
        if "stern" in cards:
            assert cards["stern"]["letter"] == "S"


# ------------------------------------------------------------ projects
def test_new_project_checks_and_creates(tmp_path):
    from pinball_decryptor.core import project_file
    with web_app(tmp_path, mfr="stern") as w:
        f = w.call("shellx.project_form")
        assert "stern" in {m["key"] for m in f["mfrs"]}
        r = w.call("shellx.project_new_create", str(tmp_path / "nope"),
                   "x", "stern", "")
        assert r["error"] == "Pick a location that exists."
        r = w.call("shellx.project_new_create", str(tmp_path), "a:b",
                   "stern", "")
        assert r["error"] == "Enter a usable folder name."
        r = w.call("shellx.project_new_create", str(tmp_path), "p1",
                   "stern", str(tmp_path / "missing.raw"))
        assert r["error"].startswith("The stock image doesn't exist")
        r = w.call("shellx.project_new_create", str(tmp_path), "p1",
                   "stern", "")
        assert r["ok"]
        folder = tmp_path / "p1"
        assert project_file.has_anchor(str(folder))
        assert w.window.extract_output_var.get() == str(folder)
        assert settings_of(tmp_path)["project_dir"] == str(tmp_path)
        r = w.call("shellx.project_new_create", str(tmp_path), "p1",
                   "stern", "")
        assert "already contains a project" in r["error"]


def _new_project(w, tmp_path, name="p1"):
    r = w.call("shellx.project_new_create", str(tmp_path), name, "stern", "")
    assert r["ok"], r
    return str(tmp_path / name)


def test_fork_copies_and_opens(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        src = _new_project(w, tmp_path)
        (tmp_path / "p1" / "note.txt").write_text("hi", encoding="utf-8")
        form = w.call("shellx.fork_form")
        assert form["src"] == src and form["hint"] == "p1 fork"
        r = w.call("shellx.fork_start", src, str(tmp_path), "p1 fork")
        assert r.get("ok")
        dest = tmp_path / "p1 fork"
        w.answers.append("no")
        r = w.call("shellx.fork_start", src, str(tmp_path), "p2")
        assert r.get("cancelled") and not (tmp_path / "p2").exists()
        confirm = w.asked[-1]
        assert confirm["title"] == "Save project as"
        assert "The build output isn't copied" in confirm["message"]
        w.answers.append("yes")
        r = w.call("shellx.fork_start", src, str(tmp_path), "p3")
        assert r.get("started")
        assert until(w, lambda: w.state("shellx")["job"] is None)
        assert (tmp_path / "p3" / "note.txt").read_text(
            encoding="utf-8") == "hi"
        assert not dest.exists() or not os.listdir(dest)


def test_properties_notes_and_build(tmp_path):
    from pinball_decryptor.core import project_file
    with web_app(tmp_path, mfr="stern") as w:
        folder = _new_project(w, tmp_path)
        p = w.call("shellx.properties_state")
        assert p["folder"] == folder and p["anchored"] and p["is_active"]
        assert p["game"] == w.window.current_mfr.display
        assert until(w, lambda: "Extraction" in (
            w.state("shellx")["props"] or {}).get("sizes", ""))
        assert w.call("shellx.properties_save_notes", folder, "hello\n")
        assert project_file.load_anchor(folder)["notes"] == "hello"
        assert not w.call("shellx.properties_save_notes", folder, "hello")
        w.answers.append("ok")
        assert w.call("shellx.properties_delete_build", folder) is False
        assert w.asked[-1]["message"] == "No build output to delete."
        os.makedirs(os.path.join(folder, "build"))
        with open(os.path.join(folder, "build", "x.raw"), "wb") as f:
            f.write(b"z" * 10)
        w.answers.append("yes")
        assert w.call("shellx.properties_delete_build", folder) is True
        assert not os.path.isdir(os.path.join(folder, "build"))


def test_archive_asks_and_closes_the_open_project(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        folder = _new_project(w, tmp_path)
        w.answers.append("no")
        assert w.call("shellx.project_archive", folder) is False
        assert "currently open" in w.asked[-1]["message"]
        w.answers.append("yes")
        assert w.call("shellx.project_archive", folder) is True
        assert until(w, lambda: w.state("shellx")["job"] is None)
        assert until(w, lambda: w.app._project_folder() == "")


def test_manager_lists_removes_and_locates(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        folder = _new_project(w, tmp_path)
        rows = w.call("shellx.manager_refresh")
        mine = [r for r in rows if r["folder"] == folder]
        assert mine and mine[0]["anchored"] and mine[0]["state"] == ""
        assert until(w, lambda: folder in (w.state("shellx")["pm_sizes"]
                                           or {}))
        moved = tmp_path / "moved"
        moved.mkdir()
        w.answers.append(str(moved))
        assert w.call("shellx.manager_locate", folder)
        assert str(moved) in {r["folder"]
                              for r in w.state("shellx")["pm_rows"]}
        assert w.call("shellx.manager_remove", str(moved))
        assert str(moved) not in {r["folder"]
                                  for r in w.state("shellx")["pm_rows"]}
        assert os.path.isdir(moved)                # never touched


def test_relink_and_history_without_records(tmp_path):
    with web_app(tmp_path, mfr="stern") as w:
        _new_project(w, tmp_path)
        assert w.call("shellx.relink_open") is None
        assert w.asked[-1]["title"] == "Relink moved files"
        assert w.call("shellx.change_history") is False
        assert w.asked[-1]["title"] == "Change history"
        from pinball_decryptor.core import history_log
        history_log.record(str(tmp_path / "p1"), ["picked a sound"])
        assert w.call("shellx.change_history") is True
        path = history_log.path_for(str(tmp_path / "p1"))
        r = w.call("shellx.read_text_tail", path)
        assert any("picked a sound" in ln for ln in r["lines"])


def test_relink_finds_a_moved_file(tmp_path):
    from pinball_decryptor.core import staged_changes
    with web_app(tmp_path, mfr="stern") as w:
        folder = _new_project(w, tmp_path)
        gone = str(tmp_path / "old" / "media" / "boom.wav")
        staged_changes.save(folder, {"audio": {"sfx/a.wav": gone}})
        from pinball_decryptor.core import relink
        if not relink.recorded_sources(staged_changes.load(folder)):
            pytest.skip("sidecar layout differs")
        st = w.call("shellx.relink_open")
        assert st and st["rows"] and st["rows"][0]["file"] == "boom.wav"
        new_root = tmp_path / "new"
        (new_root / "media").mkdir(parents=True)
        (new_root / "media" / "boom.wav").write_bytes(b"RIFF")
        w.call("shellx.relink_search", str(new_root))
        assert until(w, lambda: w.state("shellx")["relink"]["can_apply"])
        w.answers.append("ok")
        assert w.call("shellx.relink_apply")
        data = staged_changes.load(folder)
        assert data["audio"]["sfx/a.wav"] == str(new_root / "media" /
                                                 "boom.wav")
        w.call("shellx.relink_close")


# ------------------------------------------------------------ disk space
def test_disk_space_window(tmp_path, monkeypatch):
    from pinball_decryptor.core import host_temp
    monkeypatch.setattr(host_temp, "usage", lambda: {
        "total": 100, "used": 60, "free": 40, "pct": 60, "drive": "C:"})
    monkeypatch.setattr(host_temp, "scan", lambda: [
        {"path": "p1", "size": 2048, "manufacturer": "Stern Pinball",
         "detail": "audio extract"},
        {"path": "p2", "size": 1024, "manufacturer": "Stern Pinball",
         "detail": "grow"}])
    deleted = []
    monkeypatch.setattr(host_temp, "delete",
                        lambda paths: deleted.extend(paths) or 1024)
    with web_app(tmp_path, mfr="stern") as w:
        w.call("shellx.disk_open")
        assert until(w, lambda: not w.state("shellx")["disk"]["busy"])
        d = w.state("shellx")["disk"]
        assert d["status"] == "Found 2 staging items using 3 KiB."
        assert d["bars"][0]["text"].startswith("WSL: not available")
        assert d["rows"][0]["text"].startswith("Windows temp (%TEMP%)")
        leaf = [r for r in d["rows"] if r["level"] == 2][-1]
        w.answers.append("no")
        assert w.call("shellx.disk_clean", leaf["leaves"]) is False
        assert w.asked[-1]["title"] == "Delete staging"
        w.answers.append("yes")
        assert w.call("shellx.disk_clean", leaf["leaves"]) is True
        assert until(w, lambda: w.state("shellx")["disk"]["status"]
                     .startswith("Freed"))
        assert deleted == ["p2"]
        assert len([r for r in w.state("shellx")["disk"]["rows"]
                    if r["level"] == 2]) == 1
        assert w.call("shellx.disk_close") is True
        assert w.state("shellx")["disk"] is None
