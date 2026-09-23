"""The app-wide menus, windows and banners (not a rail tab; ns ``shellx``).

What the Tk ``MainWindow`` kept around the notebook, on the page:

* the gear Settings menu (update check + interval, disk space, logs, voice
  recognition quality, prerequisites, preview features, the disclaimer) as
  ``shell.settings_items`` + ``window.settings_actions``;
* the green ? "Tips for this tab" window (``webui/help_content.py``);
* the Project menu's windows (``shellx_projects.py``) and Manage disk space
  (``shellx_disk.py``);
* updates: the blue banner, the "Up to date" answer, the download progress
  window (``show_update_banner`` & co, which the run logic calls);
* the amber "source image changed" banner on the asset-editing tabs;
* the log drawer's extras (previous sessions above a cut line, Save As, the
  on-disk logs), the picker's cards and the prerequisites strip's facts.

The page half is ``static/js/shell.js`` (menus, strip, picker, log drawer)
and ``static/js/shellx_dialogs.js`` (the windows).
"""

import logging
import os
import sys
import threading
import types

from ... import __version__
from ...core import session_log
from .. import compat
from ..picker_data import MFR_VISUALS, peek_text, tooltip_text
from ..shellx_disk import DiskMixin
from ..shellx_projects import ProjectsMixin
from ..update_interval import (UPDATE_INTERVAL_CHOICES,
                               normalize_update_interval)
from .base import TabService, rpc

log = logging.getLogger(__name__)

# Voice recognition quality in the ⚙ settings menu: the faster-whisper model
# Auto-name call-outs transcribes with.  The first entry is the default.
VOICE_QUALITY_CHOICES = (
    ("tiny.en", "Standard — fastest (~75 MB model)"),
    ("small.en", "High — better accuracy, ~4× slower (~500 MB model)"),
    ("medium.en", "Highest — best accuracy, ~10× slower (~1.5 GB model)"),
)
#: the tabs the stale-source banner shows on (MainWindow._on_tab_changed)
ASSET_TAB_KEYS = ("Write", "Replace Audio", "Replace Video",
                  "Replace Images", "Replace Text")

#: previous-session lines seeded above the log's cut line (Tk LOG_SEED_LINES)
LOG_SEED_LINES = 600


def update_action_verb(installer):
    """main_window._update_action_verb: Linux downloads an AppImage and
    installs nothing, so its button says so."""
    if (installer or {}).get("kind") == "appimage":
        return "Download update"
    return "Install update"


def _peek_and_tip(mfr):
    try:
        return peek_text(mfr.games), tooltip_text(mfr)
    except Exception:                                   # noqa: BLE001
        names = [g.display for g in mfr.games]
        return ", ".join(names[:4]), "\n".join([mfr.display, ""] + names)


def _visuals():
    return dict(MFR_VISUALS)


class ShellExtras(ProjectsMixin, DiskMixin, TabService):
    ns = "shellx"
    key = ""
    label = ""
    group = ""
    icon = ""
    exports = (
        "voice_quality_var", "update_interval_var", "show_log_history_var",
        "set_update_check_running", "show_update_banner",
        "show_up_to_date_toast", "open_update_download_dialog",
        "apply_preview_features",
    )

    def __init__(self, window):
        super().__init__(window)
        cb = window.cb
        vq = cb.get("initial_voice_quality")
        if vq not in {v for v, _ in VOICE_QUALITY_CHOICES}:
            vq = VOICE_QUALITY_CHOICES[0][0]
        self.voice_quality_var = self.var("voice_quality", "str", vq)
        self.update_interval_var = self.var(
            "update_interval", "int",
            normalize_update_interval(cb.get("initial_update_interval")))
        self.show_log_history_var = self.var(
            "show_log_history", "bool",
            bool(cb.get("initial_show_log_history", True)))
        self._update_check_busy = False
        self._update_available = None       # (version, url, installer|None)
        self._update_banner_url = None
        self._update_banner_dismissed = None
        self._update_banner_shown = False
        self._download = None               # the download window's state
        self._stale_token = 0
        self._stale_dismissed = None        # (folder, text) this session
        self._stale_shown = None
        self._assets_hooked = False
        self._log_seeded = False
        self._projects_init()
        self._disk_init()
        self.set(update_state="", download=None, log_seed=None,
                 disk_badge="", picker=self._picker_cards(),
                 prereq_hints={}, platform=sys.platform)
        self._install_actions()
        self._publish_disclaimer()
        # App sets the window's theme after the services are built, so
        # the first-run theme is decided once it has (see _first_run_theme)
        if not (getattr(self.app, "_settings", None) or {}).get("theme"):
            self.ctx.loop.post(self._first_run_theme)
        self.ctx.store.set("shell", prereq_buttons=sys.platform != "darwin",
                           help_items=[])
        self.publish_settings_items()
        if sys.platform == "win32":
            try:
                self.ctx.loop.after(1500, self.start_disk_badge_check)
            except Exception:                           # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # plumbing into the window (its menus, banners and tab changes)
    # ------------------------------------------------------------------
    def _install_actions(self):
        win = self.window
        acts = dict(getattr(type(win), "settings_actions", {}) or {})
        for aid, fn in self._settings_action_table().items():
            acts[aid] = (lambda f: (lambda _win, *a: f(*a)))(fn)
        win.settings_actions = acts
        handlers = dict(getattr(type(win), "banner_handlers", {}) or {})
        handlers["update"] = lambda _win, action: self._update_banner_action(
            action)
        handlers["stale_source"] = (
            lambda _win, action: self._stale_banner_action(action))
        win.banner_handlers = handlers

    def _settings_action_table(self):
        return {
            "install_update": self._install_update_clicked,
            "download_update": self._open_update_url,
            "check_updates": self._handle_check_updates,
            "update_interval": self._pick_update_interval,
            "disk_space": lambda: self._open_dialog("disk_space"),
            "log_history": self._open_log_history,
            "open_log_file": self._open_log_history,
            "project_log": self._open_project_log,
            "toggle_log_history": self._toggle_log_history,
            "voice_quality": self._pick_voice_quality,
            "clear_voice_models": self._clear_voice_models,
            "recheck_prereqs": self._recheck_prereqs,
            "install_prereqs": self.install_prereqs,
            "preview_features": lambda: self._open_dialog("preview_features"),
            "view_disclaimer": lambda: self._open_dialog("disclaimer"),
            "tips": lambda: self._open_dialog("tips"),
            "change_history": self.change_history,
        }

    def _first_run_theme(self):
        """MainWindow: ``initial_theme or detect_system_theme()``.  With no
        theme in settings.json (a first run) the OS's light/dark choice is
        taken, and App._save_settings persists it with the next save, as
        Tk's did.  A concrete "dark"/"light" is stored, never "system", so
        the Tk build (PAD_UI=tk) can still read the file."""
        if (getattr(self.app, "_settings", None) or {}).get("theme"):
            return
        try:
            from pinball_decryptor.webui.theme import detect_system_theme
            theme = detect_system_theme()
        except Exception:                               # noqa: BLE001
            theme = "system"            # the page follows the OS itself
        if theme not in ("dark", "light", "system"):
            return
        self.window._current_theme = theme
        self.ctx.store.set("shell", theme=theme)

    def _open_dialog(self, name, **props):
        self.ctx.bus.publish("open_dialog", name=name, props=props)
        return True

    def _var_or_none(self, name):
        svc = (self.window.__dict__.get("_exports") or {}).get(name)
        if svc is None or svc is self:
            return None
        return getattr(svc, name, None)

    # ------------------------------------------------------------------
    # hooks
    # ------------------------------------------------------------------
    def on_manufacturer(self, mfr):
        hints = {}
        for p in getattr(mfr, "prerequisites", ()) or ():
            hints[p.name] = getattr(p, "install_hint", "") or ""
        self.set(prereq_hints=hints)
        if not self._log_seeded:
            self._log_seeded = True
            self._seed_log_history()
        self._hook_assets_folder()
        self.publish_settings_items()

    def on_running(self, running, mode):
        self.publish_settings_items()

    def on_tab_changed(self, ns):
        svc = self.window.service(ns) if ns else None
        key = svc.key if svc is not None else ""
        self._refresh_stale_source_banner(on_asset_tab=key in ASSET_TAB_KEYS)

    def _hook_assets_folder(self):
        """The project folder field (write_assets_var) drives the per-project
        log mirror and the top bar's project chip, as its Tk traces did."""
        if self._assets_hooked:
            return
        var = self._var_or_none("write_assets_var")
        if var is None:
            return
        self._assets_hooked = True
        var.trace_add("write", lambda *_a: self._on_assets_folder())
        self._follow_project_log()

    def _on_assets_folder(self):
        self._follow_project_log()
        fn = getattr(self.app, "_publish_project", None)
        if fn is not None:
            try:
                fn()
            except Exception:                           # noqa: BLE001
                log.exception("publish project")

    def _follow_project_log(self):
        """MainWindow._follow_project_log: mirror the log into the project
        folder now being worked on."""
        if os.environ.get("PAD_UI_NO_RIG") and not os.environ.get(
                "PAD_UI_PROJECT_LOG"):
            # captures and tests (scripts/webui_shot.py, the harness) run
            # against a COPY of settings.json that names real project
            # folders: never write their logs/project.log
            return
        var = self._var_or_none("write_assets_var")
        folder = (var.get() if var is not None else "") or ""
        try:
            if session_log.set_project(folder.strip(), version=__version__):
                if session_log.active_project():
                    self.window.append_log(
                        "Log for this project is also being written to %s"
                        % os.path.normpath(session_log.project_log_path()),
                        "info")
        except Exception:                               # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # the gear menu
    # ------------------------------------------------------------------
    def publish_settings_items(self):
        """The gear menu, in Tk's order and with Tk's cascades
        (_build_settings_menu): an item with ``submenu`` is a cascade.  The
        page puts its own Appearance and Zoom cascades after the leading
        update entry, where Tk had the theme toggle."""
        items = []
        if self._update_available:
            version, _url, installer = self._update_available
            if installer and self.window.cb.get("on_install_update"):
                items.append({"id": "install_update", "dot": True,
                              "label": "%s v%s…" % (
                                  update_action_verb(installer), version)})
            else:
                items.append({"id": "download_update", "dot": True,
                              "label": "Download update v%s…" % version})
            items.append({"sep": True})
        items.append({"id": "check_updates",
                      "label": ("Checking for updates…"
                                if self._update_check_busy
                                else "Check for updates"),
                      "disabled": self._update_check_busy})
        cur = self._int(self.update_interval_var.get())
        items.append({"label": "Check automatically", "submenu": [
            {"id": "update_interval", "args": [hours], "label": label,
             "checked": cur == hours, "radio": True}
            for hours, label in UPDATE_INTERVAL_CHOICES]})
        if sys.platform == "win32":
            label = "Manage disk space…"
            if self.disk_badge_suffix:
                label += "   %s" % self.disk_badge_suffix
            items.append({"id": "disk_space", "label": label,
                          "warn": bool(self.disk_badge_suffix)})
        items.append({"label": "Logs", "submenu": [
            {"id": "log_history", "label": "View log history…"},
            {"id": "project_log", "label": "View this project's log…"},
            {"id": "toggle_log_history",
             "label": "Show previous sessions in the log",
             "checked": bool(self.show_log_history_var.get())}]})
        items.append({"sep": True})
        vq = self.voice_quality_var.get()
        items.append({"label": "Voice recognition quality", "submenu": [
            {"id": "voice_quality", "args": [value], "label": label,
             "checked": vq == value, "radio": True}
            for value, label in VOICE_QUALITY_CHOICES] + [
            {"sep": True},
            {"id": "clear_voice_models",
             "label": "Clear downloaded voice models…",
             "needs_idle": True}]})
        items.append({"sep": True})
        # the cascade's LABEL is the live prerequisite summary, so the state
        # shows without opening it (the page counts shell.prereqs, which
        # the probes fill in)
        prereq = [{"id": "recheck_prereqs",
                   "label": "Re-check prerequisites",
                   "needs_prereqs": True}]
        if sys.platform != "darwin":
            prereq.append({"id": "install_prereqs",
                           "label": "Install / repair prerequisites…",
                           "label_missing": "Install missing prerequisites…"})
        items.append({"label": "Prerequisites", "prereq_summary": True,
                      "submenu": prereq})
        items.append({"sep": True})
        items.append({"id": "preview_features",
                      "label": "Preview features…"})
        items.append({"id": "view_disclaimer", "label": "View disclaimer…"})
        self.ctx.store.set("shell", settings_items=items,
                           gear_dots={"update": bool(self._update_available),
                                      "warn": bool(self.disk_badge_suffix)})

    @staticmethod
    def _int(v, default=0):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    def _pick_update_interval(self, hours):
        hours = normalize_update_interval(hours)
        self.update_interval_var.set(hours)
        fn = self.window.cb.get("on_update_interval_change")
        if fn is not None:
            fn(self.update_interval_var.get())
        self.publish_settings_items()
        return True

    def _pick_voice_quality(self, value):
        if value not in {v for v, _ in VOICE_QUALITY_CHOICES}:
            return False
        self.voice_quality_var.set(value)
        fn = self.window.cb.get("on_voice_quality_change")
        if fn is not None:
            fn(self.voice_quality_var.get())
        self.publish_settings_items()
        return True

    def _clear_voice_models(self):
        """⚙ → Voice recognition quality → Clear downloaded voice models."""
        mb = compat.messagebox
        if self.window._is_running():
            return False
        if not mb.askyesno(
                "Clear Downloaded Voice Models",
                "Delete all downloaded voice-recognition models?\n\n"
                "The next Auto-name call-outs run downloads its model "
                "again. This is the fix when a damaged download keeps "
                "failing with a \"model.bin\" error."):
            return False
        from ...core.transcribe import clear_whisper_cache
        try:
            n, freed = clear_whisper_cache()
        except Exception as e:                          # noqa: BLE001
            mb.showerror("Clear Downloaded Voice Models",
                         f"Could not clear the voice-model cache:\n{e}")
            return False
        if n:
            mbytes = freed / 1e6
            size = ("%.1f GB" % (mbytes / 1000.0)) if mbytes >= 1000 else (
                "%.0f MB" % mbytes)
            mb.showinfo(
                "Clear Downloaded Voice Models",
                f"Removed {n} cached model folder(s), freeing {size}.\n\n"
                f"The model re-downloads on the next Auto-name "
                f"call-outs run.")
        else:
            mb.showinfo("Clear Downloaded Voice Models",
                        "No downloaded voice models found.")
        return True

    def _recheck_prereqs(self):
        fn = self.window.cb.get("on_recheck_prereqs")
        if fn is not None:
            fn()
        return True

    @rpc
    def install_prereqs(self):
        """Install Missing / Install / repair prerequisites….  The run
        logic's boxes are the page's (app.messagebox is compat's)."""
        fn = self.window.cb.get("on_install_prereqs")
        if fn is None:
            return False
        fn()
        return True

    # ------------------------------------------------------------------
    # logs
    # ------------------------------------------------------------------
    def _open_log_history(self):
        path = session_log.log_path()
        if not os.path.isfile(path):
            compat.messagebox.showinfo(
                "Log history",
                "No log history yet — it starts collecting from now on.\n\n"
                "Everything the log pane shows is also saved to:\n%s" % path)
            return False
        from ..shellx_common import open_in_text_viewer
        open_in_text_viewer(path)
        return True

    def _open_project_log(self):
        path = session_log.project_log_path()
        mb = compat.messagebox
        if not path:
            mb.showinfo(
                "This project's log",
                "No project folder is open, so there is no per-project log "
                "yet.\n\nPick a project folder and everything from then on is "
                "written to a logs folder inside it as well as to the shared "
                "history.")
            return False
        if not os.path.isfile(path):
            mb.showinfo(
                "This project's log",
                "Nothing has been logged for this project yet — it starts "
                "collecting from now on.\n\nIt will be written to:\n%s" % path)
            return False
        from ..shellx_common import open_in_text_viewer
        open_in_text_viewer(path)
        return True

    def _seed_log_history(self):
        """MainWindow._seed_log_history: the previous sessions, dimmed above
        a cut line (the page draws them; this reads them)."""
        if not self.show_log_history_var.get():
            self.set(log_seed=None)
            return
        try:
            lines = session_log.previous_tail(max_lines=LOG_SEED_LINES)
        except Exception:                               # noqa: BLE001
            lines = []
        if not lines:
            self.set(log_seed=None)
            return
        truncated = len(lines) >= LOG_SEED_LINES
        cut = ("──────────── earlier sessions above · this session below "
               "────────────")
        if truncated:
            cut = ("──────────── earlier sessions above (last %d lines — "
                   "full history in the log file) · this session below "
                   "────────────" % LOG_SEED_LINES)
        self.set(log_seed={"lines": lines, "cut": cut})

    def _toggle_log_history(self):
        show = not bool(self.show_log_history_var.get())
        self.show_log_history_var.set(show)
        if show:
            self._seed_log_history()
        else:
            self.set(log_seed=None)
        fn = self.window.cb.get("on_show_log_history_change")
        if fn is not None:
            fn(show)
        self.publish_settings_items()
        return True

    @rpc
    def save_log(self, text):
        """The log's Save As…: the text the pane shows, to a .txt."""
        path = compat.filedialog.asksaveasfilename(
            title="Save log as…", defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return False
        try:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(text or "")
        except OSError as exc:
            compat.messagebox.showerror("Save log",
                                        "Couldn't save the log:\n%s" % exc)
            return False
        return True

    # ------------------------------------------------------------------
    # updates
    # ------------------------------------------------------------------
    def set_update_check_running(self, running):
        self._update_check_busy = bool(running)
        self.publish_settings_items()

    def _handle_check_updates(self):
        if self._update_check_busy:
            return False
        fn = self.window.cb.get("on_check_updates")
        if fn is not None:
            fn()
        return True

    def show_up_to_date_toast(self):
        self.set(update_state="latest")
        compat.messagebox.showinfo(
            "Up to date", f"You're on the latest version (v{__version__}).")

    def show_update_banner(self, version, url, installer=None):
        """MainWindow.show_update_banner: the blue banner, the gear's dot and
        its menu entry.  A version already dismissed this session does not
        re-open the banner; a newer one does."""
        self._update_banner_url = url
        muted = (version == self._update_banner_dismissed
                 and not self._update_banner_shown)
        can_auto = bool(installer and self.window.cb.get("on_install_update"))
        self._update_available = (version, url,
                                  installer if can_auto else None)
        verb = update_action_verb(installer) if can_auto else ""
        self.ctx.store.set("shell", update={
            "available": True, "version": version,
            "label": ("%s v%s" % (verb, version)) if can_auto
            else "v%s available" % version})
        self.set(update_state="available")
        self.publish_settings_items()
        if muted:
            return
        if can_auto:
            actions = [{"id": "install", "label": verb, "primary": True},
                       {"id": "notes", "label": "Release notes"}]
        else:
            actions = [{"id": "notes", "label": "Download", "primary": True}]
        self.window.set_banner("update", {
            "kind": "info", "icon": "bolt",
            "text": "Pinball Asset Decryptor v%s is available — you're on "
                    "v%s." % (version, __version__),
            "actions": actions, "dismiss": True})
        self._update_banner_shown = True

    def _update_banner_action(self, action):
        if action == "install":
            return self._install_update_clicked()
        if action == "notes":
            return self._open_update_url()
        if action == "dismiss":
            if self._update_available:
                self._update_banner_dismissed = self._update_available[0]
            self._update_banner_shown = False
            self.window.set_banner("update", None)
        return True

    def _install_update_clicked(self):
        """Banner / gear / top-bar chip "Install update"; with no installer
        for this platform it opens the release page instead."""
        if not self._update_available:
            return False
        version, url, installer = self._update_available
        fn = self.window.cb.get("on_install_update")
        if installer and fn is not None:
            fn(version, installer)
            return True
        return self._open_update_url()

    def _open_update_url(self):
        url = self._update_banner_url or (
            self._update_available[1] if self._update_available else None)
        self.open_link_checked(url, what="the release page")
        return True

    @rpc
    def open_link(self, url):
        """A link line in the log (the update check's "Download: <url>";
        Tk's _write_log_link bound a click to MainWindow.open_link)."""
        if not isinstance(url, str) or not url.strip():
            return False
        self.open_link_checked(url.strip(), what="that link")
        return True

    def open_link_checked(self, url, what="that link"):
        """MainWindow.open_link: open *url* in the browser off the loop, and
        when nothing can, put it on the clipboard and say so."""
        if not url:
            return

        def _work():
            from ...core import desktop
            try:
                ok, err = desktop.open_url(url)
            except Exception as e:                      # noqa: BLE001
                ok, err = False, str(e)
            if not ok:
                self.ctx.loop.post(self._link_failed, url, what, err)

        threading.Thread(target=_work, name="pad-shellx-link",
                         daemon=True).start()

    def _link_failed(self, url, what, err):
        session_log.append("Could not open %s: %s (%s)" % (what, url, err),
                           "warn")
        self.ctx.bus.publish("clipboard", text=url)
        compat.messagebox.showwarning(
            "Couldn't open your browser",
            "Nothing here could open %s.\n\n%s%s\n\n(%s)"
            % (what, url, "\n\nThe link has been copied to your clipboard.",
               err or "no details"))

    def open_update_download_dialog(self, version, on_cancel):
        """The 'Downloading update' window; returns a handle with
        ``set_progress(done, total)`` and ``close()`` (loop-only, like
        Tk's)."""
        st = {"cancelled": False, "on_cancel": on_cancel, "open": True}
        self._download = st
        self.set(download={
            "version": version,
            "text": "Downloading Pinball Asset Decryptor v%s…" % version,
            "detail": "Starting download…", "pct": None,
            "cancelling": False})

        def set_progress(done, total):
            if st["cancelled"] or not st["open"]:
                return
            cur = dict(self.get("download") or {})
            if total and total > 0:
                cur["pct"] = int(done * 100 / total)
                cur["detail"] = "%.0f of %.0f MB" % (done / 1048576,
                                                    total / 1048576)
            else:
                cur["detail"] = "%.0f MB" % (done / 1048576)
            self.set(download=cur)

        def close():
            st["open"] = False
            if self._download is st:
                self._download = None
                self.set(download=None)

        return types.SimpleNamespace(set_progress=set_progress, close=close)

    @rpc
    def download_cancel(self):
        st = self._download
        if st is None or st["cancelled"]:
            return False
        st["cancelled"] = True
        cur = dict(self.get("download") or {})
        cur.update(detail="Cancelling…", cancelling=True)
        self.set(download=cur)
        try:
            st["on_cancel"]()
        except Exception:                               # noqa: BLE001
            log.exception("update download cancel")
        return True

    # ------------------------------------------------------------------
    # source image changed (MainWindow._refresh_stale_source_banner)
    # ------------------------------------------------------------------
    def _refresh_stale_source_banner(self, on_asset_tab=True):
        self._stale_token += 1
        if not on_asset_tab:
            if self._stale_shown:
                self.window.set_banner("stale_source", None)
                self._stale_shown = None
            return
        var = self._var_or_none("write_assets_var")
        path = ((var.get() if var is not None else "") or "").strip()
        token = self._stale_token

        def _probe():
            from ...core.extract_source import (stale_dismissed,
                                                stale_source_message)
            stale = None
            if path:
                try:
                    stale = stale_source_message(path)
                except Exception:                       # noqa: BLE001
                    stale = None
            dismissed_on_disk = False
            if stale is not None:
                try:
                    dismissed_on_disk = stale_dismissed(path)
                except Exception:                       # noqa: BLE001
                    dismissed_on_disk = False
            self.ctx.loop.post(self._apply_stale_source_banner, token, path,
                               stale, dismissed_on_disk)

        threading.Thread(target=_probe, name="pad-shellx-stale",
                         daemon=True).start()

    def _apply_stale_source_banner(self, token, path, stale,
                                   dismissed_on_disk):
        if token != self._stale_token:
            return
        if stale is None:
            self._stale_dismissed = None
        show = bool(stale and self._stale_dismissed != (path, stale))
        if show and dismissed_on_disk:
            show = False
        if show:
            self._stale_shown = (path, stale)
            self.window.set_banner("stale_source", {
                "kind": "warn", "text": stale,
                "actions": [{"id": "dismiss_source", "label": "Dismiss",
                             "primary": True}],
                "dismiss": False})
        elif self._stale_shown:
            self._stale_shown = None
            self.window.set_banner("stale_source", None)

    def _stale_banner_action(self, action):
        if action not in ("dismiss_source", "dismiss"):
            return False
        shown = self._stale_shown
        var = self._var_or_none("write_assets_var")
        path = ((var.get() if var is not None else "") or "").strip()
        self._stale_dismissed = (path, shown[1] if shown else "")
        if path:
            try:
                from ...core.extract_source import dismiss_stale_source
                dismiss_stale_source(path)
            except Exception:                           # noqa: BLE001
                pass
        self._stale_shown = None
        self.window.set_banner("stale_source", None)
        return True

    # ------------------------------------------------------------------
    # tips (webui/help_content.py)
    # ------------------------------------------------------------------
    @rpc(loop=False)
    def tips(self, tab_key=None):
        """The ? window's content for *tab_key* (default: the tab showing):
        its own sections, then the General ones."""
        key = tab_key or self.window.current_tab_key() or "Extract"
        try:
            from ..help_content import GENERAL_CONTENT, sections_for
            sections = sections_for(key)
            general = list(GENERAL_CONTENT)
        except Exception:                               # noqa: BLE001
            log.exception("tips content")
            sections, general = [], []
        tabs = []
        for svc in self.window.tabs:
            if getattr(svc, "_visible", False) and svc.key:
                tabs.append({"key": svc.key, "label": svc.label,
                             "ns": svc.ns})
        return {"tab": key, "title": ("Tips — %s" % key) if key else "Tips",
                "sections": [[t, b] for t, b in sections],
                "general": [[t, b] for t, b in general],
                "tabs": tabs}

    # ------------------------------------------------------------------
    # the disclaimer (webui/disclaimer_text.py)
    # ------------------------------------------------------------------
    def _publish_disclaimer(self):
        from ..disclaimer_text import (DISCLAIMER_BODY, DISCLAIMER_HEADER,
                                       DISCLAIMER_TITLE)
        self.ctx.store.set("shell", disclaimer_text=DISCLAIMER_BODY,
                           disclaimer_title=DISCLAIMER_TITLE,
                           disclaimer_header=DISCLAIMER_HEADER)

    # ------------------------------------------------------------------
    # preview features (webui/preview_text.py)
    # ------------------------------------------------------------------
    def _preview_codes(self):
        fn = self.window.cb.get("preview_codes_provider")
        try:
            got = fn() if fn else []
        except Exception:                               # noqa: BLE001
            got = []
        return [c for c in (got or []) if isinstance(c, str)]

    def _set_preview_codes(self, codes):
        from ...core import preview
        fn = self.window.cb.get("on_preview_codes_change")
        if fn is not None:
            fn(list(codes))
        preview.load(codes)
        self.apply_preview_features()

    def apply_preview_features(self):
        """Show or hide what the preview switch gates (the Modes tab) for
        the manufacturer on screen."""
        win = self.window
        mfr = win.current_mfr
        if mfr is None:
            return
        on = win.modes_preview_on(mfr)
        panel = None
        for svc in win.tabs:
            if svc.key == "Modes":
                svc._visible = bool(on)
                panel = svc
        win.refresh_rail()
        win._ensure_visible_selection()
        if on and panel is not None:
            for name in ("refresh", "refresh_stock_modes"):
                fn = getattr(panel, name, None)
                if callable(fn):
                    try:
                        fn()
                    except Exception:                   # noqa: BLE001
                        pass

    def _preview_rows(self):
        from ...core import preview
        _active, rows = preview.judge(self._preview_codes())
        self._preview_statuses = rows
        return [{"i": i, "lines": list(st.lines),
                 "active": bool(getattr(st, "active", False))}
                for i, st in enumerate(rows)]

    @rpc
    def preview_state(self):
        from ..preview_text import INTRO, TITLE
        return {"title": TITLE, "intro": INTRO, "rows": self._preview_rows(),
                "empty": "No preview features are switched on."}

    @rpc
    def preview_unlock(self, text):
        from ...core import preview
        try:
            codes, grant = preview.add_code(self._preview_codes(), text or "")
        except preview.PreviewCodeError as e:
            return {"ok": False, "message": str(e),
                    "rows": self._preview_rows()}
        self._set_preview_codes(codes)
        return {"ok": True,
                "message": "Unlocked. " + "; ".join(preview.describe(grant))
                + ".", "rows": self._preview_rows()}

    @rpc
    def preview_remove(self, index=None):
        from ...core import preview
        rows = getattr(self, "_preview_statuses", None)
        if rows is None:
            self._preview_rows()
            rows = self._preview_statuses
        if index is None or not 0 <= int(index) < len(rows):
            return {"ok": False,
                    "message": "Pick a code in the list first, then Remove.",
                    "rows": self._preview_rows()}
        st = rows[int(index)]
        self._set_preview_codes(preview.remove_code(self._preview_codes(),
                                                    st.code))
        who = st.grant.name if st.grant else "a code that did not check out"
        return {"ok": True, "message": "Removed the code for %s." % who,
                "rows": self._preview_rows()}

    # ------------------------------------------------------------------
    # the picker's cards (webui/picker_data.py)
    # ------------------------------------------------------------------
    def _picker_cards(self):
        visuals = _visuals()
        cards = []
        for m in self.window.manufacturers:
            v = visuals.get(m.key) or {"color": "", "letter": "?"}
            games = list(getattr(m, "games", ()) or ())
            n_unsup = sum(1 for g in games
                          if not getattr(g, "supported", True))
            exts = list(getattr(getattr(m, "input_spec", None),
                                "extensions", ()) or ())
            ext_text = ", ".join(exts[:3]) + (", …" if len(exts) > 3 else "")
            parts = ["%d game%s" % (len(games), "s" if len(games) != 1
                                    else "")]
            if ext_text:
                parts.append(ext_text)
            if n_unsup:
                parts.append("%d unsupported" % n_unsup)
            badge = (getattr(m, "badge", "") or
                     ("BETA" if getattr(m, "beta", False) else ""))
            peek, tip = _peek_and_tip(m)
            cards.append({
                "key": m.key, "display": m.display,
                "letter": v.get("letter", "?"), "color": v.get("color", ""),
                "badge": badge, "beta": badge == "BETA",
                "stats": "  ·  ".join(parts), "peek": peek, "tip": tip,
                "games": [{"display": g.display,
                           "supported": bool(getattr(g, "supported", True)),
                           "reason": getattr(g, "unsupported_reason", "")
                           or ""} for g in games]})
        return cards

    # ------------------------------------------------------------------
    def on_close(self):
        st = self._relink
        if st is not None:
            st["cancel"] = True
        for job in list(self._jobs.values()):
            job["cancel"] = True


TAB = ShellExtras
