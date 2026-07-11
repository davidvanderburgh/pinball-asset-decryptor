"""Application controller — wires the GUI to manufacturer plugins."""

import json
import os
import queue
import re
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

from . import __version__
from .core import modpack
from .core.config import APP_NAME, SETTINGS_FILE
from .core.extract_source import write_extract_source
from .core.messages import (DoneMsg, LinkMsg, LogLineMsg, LogMsg, PhaseMsg,
                            PrereqMsg, ProgressMsg)
from .core.prereqs import check_prerequisite
from .core.registry import all_manufacturers, get_manufacturer, load_plugins
from .core.updater import check_for_update
from .gui.main_window import MainWindow


def _resolve_startup_manufacturer(manufacturers, settings):
    """The manufacturer to open directly on launch, or ``None`` to show the
    picker.  ``None`` when there's no saved ``last_manufacturer`` (first
    launch) or the saved key no longer maps to a loaded plugin (removed /
    renamed) — either way the picker is the safe fallback."""
    last = settings.get("last_manufacturer")
    if not last:
        return None
    return next((m for m in manufacturers
                 if getattr(m, "key", None) == last), None)


class App:
    def __init__(self):
        # Expose the bundled ffmpeg (imageio-ffmpeg, in the frozen Mac/Linux
        # apps) under the plain name "ffmpeg" on PATH before anything probes
        # for it -- so the per-plugin ffmpeg finders (some verbatim-upstream,
        # uneditable) and the `ffmpeg -version` prerequisite checks all resolve
        # it without a system install.  No-op when a real ffmpeg is on PATH.
        from .core.audio import ensure_bundled_ffmpeg_on_path
        ensure_bundled_ffmpeg_on_path()

        load_plugins()
        self._manufacturers = all_manufacturers()
        if not self._manufacturers:
            raise RuntimeError(
                "No manufacturer plugins registered.  Check the install.")

        self.root = tk.Tk()
        self.msg_queue = queue.Queue()
        self.pipeline = None
        self._active_mode = "extract"
        # Set when the user clicks Cancel; checked by the post-job chain
        # (transcribe / music-ID / etc.) so ONE press cancels the running job
        # AND every queued follow-up, instead of one press per chained job.
        # Reset when a new user-initiated run starts.
        self._cancel_requested = False
        self._current_mfr = None
        # Pending (debounced) prereq-check timer id — see
        # _kick_off_prereq_check.  Startup restores the saved input path
        # (which can trigger an era-switch recheck) AND _apply_manufacturer
        # kicks its own check, all within one Tk tick; coalescing them keeps
        # the log from showing the "Checking N prerequisites…" block twice.
        self._prereq_after_id = None
        # Replacement-staging failures from the most recent Write run
        # (list of (label, error)); drives the post-build "some replacements
        # were skipped" warning so a partial no-op isn't silent.
        self._staging_failures = []

        self._settings = self._load_settings_file()
        saved_theme = self._settings.get("theme")
        # Apply the saved "Match audio replacements to the game's callouts" pref
        # before any Write can spawn encode workers (they inherit this env var).
        # Default on.
        self._apply_audio_declick_env(
            bool(self._settings.get("audio_declick", True)))

        # First-launch disclaimer.  Boolean flag, unversioned: once the
        # user accepts, they never see it again — including across app
        # updates and reinstalls (the settings dir lives outside the
        # install dir).  Declining or closing the dialog exits cleanly
        # before we even build the main window.
        #
        # We CANNOT withdraw the root before showing the modal — on
        # Windows pythonw a transient Toplevel whose parent is withdrawn
        # never gets mapped, the grab fails silently, the dialog
        # destroys immediately, and the app exits with no traceback (the
        # "just crashing before the GUI shows" failure mode).  Instead
        # we size root tiny + off-screen-ish + title-only so it's barely
        # visible behind the modal, then hand it off to MainWindow.
        #
        # CI / test harnesses set ``PINBALL_SKIP_DISCLAIMER=1`` so the
        # GUI smoke tests don't hang waiting for a user click against a
        # modal that nobody can dismiss on a headless runner.
        skip_disclaimer = (os.environ.get("PINBALL_SKIP_DISCLAIMER")
                           or "PYTEST_CURRENT_TEST" in os.environ)
        need_disclaimer = (not skip_disclaimer
                           and not self._settings.get("disclaimer_accepted"))
        # Keep the window hidden until it's positioned + populated, so the user
        # never sees a flash of the default-geometry empty white box before the
        # saved placement lands (it's revealed with deiconify() at the end of
        # __init__).  The first-launch disclaimer modal can't run over a
        # withdrawn parent — on Windows pythonw a transient over a withdrawn
        # root never maps — so that path withdraws only after the modal closes.
        if not need_disclaimer:
            self.root.withdraw()
        if need_disclaimer:
            from .gui.disclaimer import show_disclaimer_dialog
            self.root.title(APP_NAME)
            self.root.geometry("1x1+0+0")  # minimal pre-dialog footprint
            self.root.update_idletasks()
            accepted = show_disclaimer_dialog(
                self.root, theme_name=(saved_theme or "light"))
            if not accepted:
                self.root.destroy()
                raise SystemExit(0)
            self._settings["disclaimer_accepted"] = True
            # Persist immediately, before MainWindow exists — we can't
            # use _save_settings() yet (it touches self.window).
            try:
                os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
                with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                    json.dump(self._settings, f, indent=2)
            except OSError:
                pass
            # Modal dismissed — hide the tiny pre-dialog root now, before we
            # build + position the real window, so it reveals cleanly too.
            self.root.withdraw()

        self.window = MainWindow(
            self.root,
            app_title=APP_NAME,
            manufacturers=self._manufacturers,
            on_manufacturer_change=self._on_manufacturer_change,
            on_extract=self._start_extract,
            on_extract_cancel=self._cancel,
            on_write=self._start_write,
            on_write_cancel=self._cancel,
            on_apply_delta=self._start_apply_delta,
            on_revert_all=self._start_revert_all,
            on_flash_image=self._start_flash_image,
            on_recheck_prereqs=self._recheck_prereqs,
            on_install_prereqs=self._launch_install_prereqs,
            on_back=self._on_back_to_picker,
            on_export=self._start_export,
            on_import=self._start_import,
            on_transfer_mods=self._start_transfer_mods,
            on_theme_change=self._on_theme_change,
            initial_theme=saved_theme,
            on_check_updates=self._check_for_update_now,
            initial_fda_acknowledged=bool(
                self._settings.get("macos_fda_acknowledged", False)),
            on_fda_acknowledge=self._on_fda_acknowledge,
            initial_column_widths=self._settings.get("column_widths", {}),
            on_column_widths_change=self._on_column_widths_change,
            initial_admin_warning_collapsed=bool(
                self._settings.get("admin_warning_collapsed", False)),
            on_admin_warning_collapsed_change=(
                self._on_admin_warning_collapsed_change),
            initial_voice_quality=self._settings.get("voice_quality"),
            on_voice_quality_change=self._on_voice_quality_change,
            initial_audio_declick=bool(
                self._settings.get("audio_declick", True)),
            on_audio_declick_change=self._on_audio_declick_change,
            on_partition_image_opened=self._on_partition_image_opened,
        )
        # Tracks whether the run in flight is a Direct-SSD pipeline,
        # so we can auto-acknowledge the macOS FDA banner after a
        # successful run (empirical proof that Full Disk Access is
        # actually working — that's a more reliable signal than the
        # TCC.db, which is SIP-protected and can't be queried).
        self._current_run_is_direct_ssd = False
        # (input_path, output_dir) of the extract in flight, so a successful
        # run can stamp the output folder with the source image's identity
        # (see core.extract_source / the stale-source banner).
        self._last_extract_io = None

        # Restore the user's last window size + position over MainWindow's
        # default (monkeybug: the app "does not remember my preferred sizing
        # and position").  Clamped to the current screen so a geometry saved on
        # a since-disconnected monitor can't open off-screen.
        self._restore_window_geometry()

        # Start where the user left off: most users work one machine at a
        # time, so the saved last_manufacturer opens directly (the header's
        # home button returns to the picker; the always-visible manufacturer
        # header keeps "which mfr am I on" unambiguous).  First launch — or
        # a saved key that no longer loads — starts at the picker.
        last_mfr = _resolve_startup_manufacturer(
            self._manufacturers, self._settings)
        if last_mfr is not None:
            self._apply_manufacturer(last_mfr)
        else:
            self.window.show_picker()

        # Reveal the window now that it's at its saved geometry and the picker
        # is laid out — the first thing the user sees is the real UI, not a
        # default-size empty frame flashing into its saved position.
        self.root.update_idletasks()
        self.root.deiconify()

        self._poll_queue()

        self.root.title(f"{APP_NAME} v{__version__}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.root.after(1500, self._check_for_update)

    def run(self):
        self.root.mainloop()

    def _on_close(self):
        # Stop any preview that's still playing -- an ffplay child is a
        # separate OS process and keeps playing the sound after the window
        # is gone unless we kill it first.
        try:
            self.window.stop_all_preview_playback()
        except Exception:
            pass
        self._save_settings()
        self.root.destroy()

    # ------------------------------------------------------------------
    # Queue polling — bridge background threads to the Tk main loop.
    # ------------------------------------------------------------------

    def _poll_queue(self):
        try:
            while True:
                msg = self.msg_queue.get_nowait()
                if isinstance(msg, LogMsg):
                    self.window.append_log(msg.text, msg.level)
                elif isinstance(msg, LinkMsg):
                    self.window.append_log_link(msg.text, msg.url)
                elif isinstance(msg, PhaseMsg):
                    self.window.set_phase(msg.index, mode=self._active_mode)
                elif isinstance(msg, ProgressMsg):
                    self.window.set_progress(
                        msg.current, msg.total, msg.desc, mode=self._active_mode)
                elif isinstance(msg, LogLineMsg):
                    self.window.update_log_line(msg.key, msg.text, msg.level)
                elif isinstance(msg, DoneMsg):
                    self._on_done(msg.success, msg.summary)
                elif isinstance(msg, PrereqMsg):
                    # Drop stale results if the user switched mfrs while
                    # the worker was still running.
                    if (self._current_mfr is not None and
                            self._current_mfr.key == msg.mfr_key):
                        self.window.set_prereq_result(
                            msg.result.name, msg.result.ok, msg.result.message)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # Manufacturer switching
    # ------------------------------------------------------------------

    def _on_manufacturer_change(self, mfr):
        if self._current_mfr is not None:
            self._save_manufacturer_paths(self._current_mfr.key)
        self._apply_manufacturer(mfr)
        # Persist immediately so a crash before _on_close doesn't lose
        # the user's most-recent manufacturer choice.
        self._save_settings()

    def _on_back_to_picker(self):
        """User clicked Back -> return to the manufacturer picker."""
        # Save the current mfr's paths so they're preserved across
        # picker -> re-enter cycles.  Don't clear _current_mfr; the
        # picker doesn't know about it and apply_manufacturer() reuses
        # _current_mfr to detect mfr-changes.
        if self._current_mfr is not None:
            self._save_manufacturer_paths(self._current_mfr.key)
            self._save_settings()
        self.window.show_picker()

    def _apply_manufacturer(self, mfr):
        self._current_mfr = mfr
        self._load_manufacturer_paths(mfr.key)
        self.window.apply_manufacturer(mfr)
        # Kick off the runtime-prereq check on a background thread.  The
        # GUI is already showing "[?] name" placeholders; results trickle
        # in via PrereqMsg.
        self._kick_off_prereq_check(mfr)

    # ------------------------------------------------------------------
    # Prerequisite checking
    # ------------------------------------------------------------------

    def _kick_off_prereq_check(self, mfr):
        """Coalesce prereq-check requests, then run the probe worker.

        Several call sites can fire within a single Tk tick at startup /
        on an era switch (restore-saved-path → era recheck, plus
        ``_apply_manufacturer``'s own kick).  Running each immediately
        spams the log with duplicate "Checking N prerequisites…" blocks
        and double-launches the probe threads.  Debouncing through a
        short ``after`` window collapses a same-tick burst into one
        check while leaving a user-initiated Re-check (spaced out in
        time) firing normally."""
        if self._prereq_after_id is not None:
            try:
                self.root.after_cancel(self._prereq_after_id)
            except Exception:
                pass
        self._prereq_after_id = self.root.after(
            60, lambda: self._run_prereq_check(mfr))

    def _run_prereq_check(self, mfr):
        """Run every prereq probe in a worker thread; post each result
        through the queue so the GUI updates incrementally.  Also log
        a 'checking...' line + a final summary so the empty log pane
        on app start has SOMETHING useful in it."""
        self._prereq_after_id = None
        if not mfr.prerequisites:
            self.msg_queue.put(LogMsg(
                f"{mfr.display}: no runtime prerequisites to check.", "info"))
            return
        target_key = mfr.key
        target_display = mfr.display
        prereqs = mfr.prerequisites

        self.msg_queue.put(LogMsg(
            f"Checking {len(prereqs)} prerequisite(s) for "
            f"{target_display}...", "info"))

        def _run():
            results = []
            for prereq in prereqs:
                # Bail early if the user switched mfrs mid-check
                if (self._current_mfr is None or
                        self._current_mfr.key != target_key):
                    return
                try:
                    result = check_prerequisite(prereq)
                except Exception as e:  # belt-and-suspenders
                    from .core.prereqs import PrerequisiteResult
                    result = PrerequisiteResult(
                        name=prereq.name, ok=False,
                        message=f"{type(e).__name__}: {e}",
                        reason=prereq.reason,
                        install_hint=prereq.install_hint)
                results.append(result)
                self.msg_queue.put(PrereqMsg(target_key, result))

            # Bail if user switched away while we were probing
            if (self._current_mfr is None or
                    self._current_mfr.key != target_key):
                return

            missing = [r for r in results if not r.ok]
            if not missing:
                self.msg_queue.put(LogMsg(
                    f"All prerequisites OK for {target_display}. "
                    f"Ready to extract / write.", "success"))
            else:
                names = ", ".join(r.name for r in missing)
                self.msg_queue.put(LogMsg(
                    f"Missing prerequisite(s) for {target_display}: "
                    f"{names}.", "error"))
                for r in missing:
                    detail = (f"  [x] {r.name}: {r.reason}"
                              + (f" — fix: {r.install_hint}"
                                 if r.install_hint else ""))
                    self.msg_queue.put(LogMsg(detail, "error"))
                self.msg_queue.put(LogMsg(
                    "Click 'Install Missing' above the tabs to install "
                    "everything that's missing.", "info"))

        threading.Thread(target=_run, daemon=True).start()

    def _recheck_prereqs(self):
        if self._current_mfr is not None:
            # Reset the indicators back to "[?]" before re-running so
            # the user sees the check actually happen.
            self.window.reset_prereqs(self._current_mfr.prerequisites)
            self._kick_off_prereq_check(self._current_mfr)

    def _launch_install_prereqs(self):
        """Spawn install_prerequisites.ps1 in an elevated PowerShell."""
        import sys
        from tkinter import messagebox

        if sys.platform == "darwin":
            messagebox.showinfo(
                "Install Prerequisites",
                "The auto-installer is Windows/Linux-only.\n\n"
                "On macOS, Spooky/JJP Clonezilla flows use Docker Desktop "
                "(install from https://www.docker.com/products/docker-desktop/) "
                "and gpg/ffmpeg from Homebrew (`brew install gnupg ffmpeg`).")
            return

        if sys.platform.startswith("linux"):
            script = self._find_prereqs_script_linux()
            if not script:
                messagebox.showerror(
                    "Install Prerequisites",
                    "Could not locate install_prerequisites_linux.sh.\n\n"
                    "If you're running from source, the script lives at "
                    "installer/install_prerequisites_linux.sh.")
                return
            # Launch the bash installer in a terminal so the user can
            # interact with the manufacturer picker and answer the sudo
            # prompt.  Try a few common terminal emulators.
            import shutil, subprocess
            for term, args in (
                ("x-terminal-emulator", ["-e"]),
                ("gnome-terminal",       ["--"]),
                ("konsole",              ["-e"]),
                ("xterm",                ["-e"]),
            ):
                if shutil.which(term):
                    subprocess.Popen([term, *args, "bash", script])
                    return
            messagebox.showinfo(
                "Install Prerequisites",
                f"No terminal emulator found.  Run manually:\n\n"
                f"  bash {script}")
            return

        script = self._find_prereqs_script()
        if not script:
            messagebox.showerror(
                "Install Prerequisites",
                "Could not locate install_prerequisites.ps1.\n\n"
                "If you're running from source, the script lives at "
                "installer/install_prerequisites.ps1.")
            return

        import subprocess
        # Re-launch PowerShell elevated; the script needs admin for
        # winget install + wsl --install.
        subprocess.Popen([
            "powershell", "-NoProfile", "-Command",
            f"Start-Process powershell -Verb RunAs -ArgumentList "
            f"'-NoProfile -ExecutionPolicy Bypass -File \"{script}\"'",
        ])

    @staticmethod
    def _find_prereqs_script():
        # core dir = pinball_decryptor/, app installed to {InstallDir}\
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(pkg_dir, "..", "install_prerequisites.ps1"),  # installed
            os.path.join(pkg_dir, "..", "installer", "install_prerequisites.ps1"),  # source
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return None

    @staticmethod
    def _find_prereqs_script_linux():
        pkg_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(pkg_dir, "..", "install_prerequisites_linux.sh"),
            os.path.join(pkg_dir, "..", "installer", "install_prerequisites_linux.sh"),
        ]
        for c in candidates:
            if os.path.isfile(c):
                return os.path.abspath(c)
        return None

    def _manufacturers_section(self):
        return self._settings.setdefault("manufacturers", {})

    def _load_manufacturer_paths(self, key):
        # Saved paths go through resolve_mapped_drive: a path saved as
        # "W:\…" in a normal session stops resolving when the app is later
        # run elevated (drive mappings are per logon session — monkeybug),
        # so restore its UNC equivalent instead of a dead letter.
        from .core.admin import resolve_mapped_drive as _rmd
        section = self._manufacturers_section().get(key, {})
        self.window.extract_input_var.set(
            _rmd(section.get("extract_input", "")))
        self.window.extract_output_var.set(
            _rmd(section.get("extract_output", "")))
        # Output before original: setting the original fires the fill-empty-
        # Output-Folder default (window._maybe_default_write_output), and a
        # restore that then wrote "" over it would throw the default away.
        self.window.write_output_var.set(_rmd(section.get("write_output", "")))
        self.window.write_upd_var.set(_rmd(section.get("write_original", "")))
        self.window.write_assets_var.set(_rmd(section.get("write_assets", "")))
        # Extract-tab checkbox state (auto-name / categories / JJP filters) —
        # per manufacturer, so the ticks stick across sessions (monkeybug).
        # apply_manufacturer() re-applies this after it rebuilds the dynamic
        # category checkboxes; setting it here covers the rest of the vars.
        self.window.set_extract_options(section.get("extract_options", {}))
        # This manufacturer's recent-paths lists back the path boxes'
        # dropdown history.  Stored in a top-level settings section (NOT
        # inside the manufacturers section, which _save_manufacturer_paths
        # rewrites wholesale).
        self.window.set_path_history(
            self._settings.get("path_history", {}).get(key, {}))

    # Dropdown history keeps this many recent paths per field (monkeybug
    # suggested "maybe last 6 files").
    _PATH_HISTORY_MAX = 6

    def _record_path_history(self, **field_paths):
        """Push the paths a run actually used onto the per-manufacturer
        recent-paths lists (most recent first, deduped, capped).  Recorded
        at run start — after validation — so only real, usable paths enter
        the history.  Persistence rides on the caller's _save_settings()."""
        if self._current_mfr is None:
            return
        hist = self._settings.setdefault("path_history", {}).setdefault(
            self._current_mfr.key, {})
        for field, path in field_paths.items():
            path = (path or "").strip()
            if not path:
                continue
            keep = [p for p in hist.get(field, [])
                    if os.path.normcase(p) != os.path.normcase(path)]
            hist[field] = [path] + keep[:self._PATH_HISTORY_MAX - 1]
        self.window.set_path_history(hist)

    def _on_partition_image_opened(self, path):
        """A card image the Partition Explorer actually opened joins the
        field's recent-paths dropdown (monkeybug: the same "last 5" memory
        as the Extract screen).  Saved immediately — this isn't tied to a
        run, so there's no later _save_settings() to ride on."""
        self._record_path_history(partition_image=path)
        self._save_settings()

    def _save_manufacturer_paths(self, key):
        # Don't clobber a manufacturer's previously-saved input path with a
        # cross-manufacturer path that happens to be in the field right now
        # (e.g. user on PB browsed to a Spooky .pkg and then switches mfrs).
        # Folder paths and the write-output dir aren't run through detect()
        # — they aren't manufacturer-specific.
        section = self._manufacturers_section()
        existing = section.get(key, {})
        mfr = get_manufacturer(key)

        def _safe_input_path(current_var, prev_saved):
            current = current_var.strip()
            if not current or mfr is None:
                return current
            try:
                if mfr.detect(current):
                    return current
            except Exception:
                pass
            return prev_saved  # cross-mfr path — keep what we had

        section[key] = {
            "extract_input": _safe_input_path(
                self.window.extract_input_var.get(),
                existing.get("extract_input", "")),
            "extract_output": self.window.extract_output_var.get().strip(),
            "write_original": _safe_input_path(
                self.window.write_upd_var.get(),
                existing.get("write_original", "")),
            "write_assets": self.window.write_assets_var.get().strip(),
            "write_output": self.window.write_output_var.get().strip(),
            "extract_options": self.window.get_extract_options(),
        }

    # ------------------------------------------------------------------
    # Callback helpers
    # ------------------------------------------------------------------

    def _make_callbacks(self):
        log_cb = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        phase_cb = lambda i: self.msg_queue.put(PhaseMsg(i))
        progress_cb = lambda c, t, d="": self.msg_queue.put(ProgressMsg(c, t, d))
        done_cb = lambda s, m: self.msg_queue.put(DoneMsg(s, m))
        return log_cb, phase_cb, progress_cb, done_cb

    def _post_log_line(self, key, text, level="info"):
        """Thread-safe poster for an in-place keyed log line (live per-sound
        decode progress).  Set on extract pipelines via ``set_log_line_cb``."""
        self.msg_queue.put(LogLineMsg(key, text, level))

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------

    def _start_extract(self):
        # Direct-SSD branch: when the source radio is on "ssd",
        # ``in_path`` is a physical-device path (e.g.
        # ``\\.\PHYSICALDRIVE3``), not a file.  Dispatch to the
        # manufacturer's Direct-SSD factory instead.  Plugins
        # without ``capabilities.direct_ssd`` never see this path
        # (the radio frame is hidden for them).
        if (self._current_mfr is not None
                and self._current_mfr.capabilities.direct_ssd
                and getattr(self.window, "extract_input_source_var", None)
                is not None
                and self.window.extract_input_source_var.get() == "ssd"):
            self._start_direct_ssd_extract()
            return

        in_path = self.window.extract_input_var.get().strip()
        output_path = self.window.extract_output_var.get().strip()
        # Normalize to native separators so a hand-typed or mixed path (e.g.
        # "c:\folder/decrypt_1") displays and propagates consistently to the
        # Replace tabs' assets folder below.  Re-setting the input var also
        # re-fires the "Detected: …" badge — if the file was still mid-copy
        # when it was first picked, the stale "Not recognised" heals here.
        if in_path:
            in_path = os.path.normpath(in_path)
            self.window.extract_input_var.set(in_path)
        if output_path:
            output_path = os.path.normpath(output_path)
            self.window.extract_output_var.set(output_path)

        if not in_path:
            messagebox.showwarning("Missing Input", "Please select an input file.")
            return
        if not os.path.isfile(in_path):
            messagebox.showerror("File Not Found", f"File not found:\n{in_path}")
            return
        if not output_path:
            messagebox.showwarning("Missing Input",
                "Please select an output folder.")
            return

        if self._extract_overwrite_risk(output_path):
            # icon: a question mark undersells "your edits get clobbered"
            # (monkeybug) — this is a warning-grade confirm.
            if not messagebox.askyesno(
                "Output Folder Not Empty",
                "The output folder already contains files this extract "
                "would overwrite.\n\nContinue?",
                icon="warning",
            ):
                return

        self._record_path_history(extract_input=in_path,
                                  extract_output=output_path)
        self._save_settings()

        # Point the shared assets folder at this extract's output dir so the
        # Replace Audio/Video/Image, Write, and Mod Pack tabs default to what we
        # just extracted (extract-then-edit is the common flow — the user
        # shouldn't have to re-pick the same folder).
        self.window.write_assets_var.set(output_path)
        # The Write tab's "Original" file is the same file you extracted from —
        # both pickers share the plugin's input filetypes, and Write rebuilds a
        # copy of that original (Stern's card .img/.raw, JJP's .iso/.upd, etc.).
        # Default it to this extract's input so the user doesn't re-pick it.  A
        # fresh extract means a fresh workflow, so overwrite any prior value.
        if self._current_mfr.capabilities.write:
            self.window.write_upd_var.set(in_path)

        self._active_mode = "extract"
        self._cancel_requested = False
        self._last_extract_io = (in_path, output_path)
        self.window.set_running(True, mode="extract")
        # A prior run's chained Auto-transcribe / Music-ID may have left the
        # phase row showing THEIR step list; restore the standard Extract tuple
        # before resetting it for this run.
        self.window._refresh_extract_phases()
        self.window.reset_steps(mode="extract")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()

        # Williams-only branch: two independent toggles drive which
        # half(s) of the extract run.
        #   * static_extract_var (default ON):  basic asset extract
        #   * capture_mode_var   (default OFF): PinMAME runtime capture
        # Four combinations are valid; "neither" we reject with a
        # message rather than silently no-op.
        has_capture_caps = self._current_mfr.capabilities.capture
        run_static = (
            not has_capture_caps
            or getattr(self.window, "static_extract_var", None) is None
            or self.window.static_extract_var.get())
        run_capture = (
            has_capture_caps
            and getattr(self.window, "capture_mode_var", None) is not None
            and self.window.capture_mode_var.get())
        if has_capture_caps and not run_static and not run_capture:
            messagebox.showwarning(
                "Nothing to do",
                "Tick at least one extract option:\n"
                "  • Basic extract (raw ROM assets), and/or\n"
                "  • Use PinMAME runtime capture")
            self._active_mode = None
            self.window.set_running(False, mode="extract")
            return

        if run_capture:
            try:
                duration = float(self.window.capture_duration_var.get())
            except (TypeError, ValueError):
                duration = 180.0
            frame_cb = getattr(self.window, "on_dmd_frame", None)
            if frame_cb is not None and hasattr(
                    self.window, "reset_dmd_preview"):
                self.window.reset_dmd_preview()
            capture_ready_cb = getattr(
                self.window, "on_capture_ready", None)
            self.pipeline = self._current_mfr.make_capture_pipeline(
                in_path, output_path,
                log_cb, phase_cb, progress_cb, done_cb,
                duration_seconds=duration,
                simulate_gameplay=(
                    self.window.capture_gameplay_var.get()
                    if hasattr(self.window, "capture_gameplay_var")
                    else True),
                frame_cb=frame_cb,
                capture_ready_cb=capture_ready_cb,
                also_run_static=run_static,
            )
        else:
            # No capture — pure basic-extract path (the same one all
            # other plugins always use).
            # If the transcribe checkbox is on (CGC-only currently),
            # wrap done_cb so a successful Extract chains into the
            # transcribe pipeline against the just-written output dir.
            # Compose the post-extract chain inner-first: music-ID runs AFTER
            # transcribe, so wrap music-ID (inner) then transcribe (outer).
            # Each wrap is a no-op when its checkbox is off.
            chained_done_cb = self._maybe_wrap_done_for_music_id(
                done_cb, output_path)
            chained_done_cb = self._maybe_wrap_done_for_transcribe(
                chained_done_cb, output_path)
            extra_kwargs = self._collect_asset_filter_kwargs()
            extra_kwargs.update(self._collect_extract_category_kwargs())
            extra_kwargs.update(self._collect_duration_names_kwargs())
            if getattr(
                    self._current_mfr.capabilities, "decode_dmd", False):
                extra_kwargs["decode_dmd"] = bool(
                    self.window.decode_dmd_var.get())
            if getattr(
                    self._current_mfr.capabilities, "chain_deltas", False):
                deltas = list(getattr(self.window, "extract_delta_paths", []))
                if deltas:
                    extra_kwargs["deltas"] = deltas
            self.pipeline = self._current_mfr.make_extract_pipeline(
                in_path, output_path,
                log_cb, phase_cb, progress_cb, chained_done_cb,
                **extra_kwargs,
            )
        # Live per-sound decode progress (Stern) updates keyed log lines in
        # place; harmless for plugins that never emit them.  Guard the call:
        # the JJP pipelines are ported standalone classes that don't inherit
        # BasePipeline, so they lack this hook — calling it unconditionally
        # raised AttributeError here on the main thread *before* the worker
        # thread started, leaving a phantom "running" UI (no worker, no log).
        if hasattr(self.pipeline, "set_log_line_cb"):
            self.pipeline.set_log_line_cb(self._post_log_line)
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    def _maybe_wrap_done_for_transcribe(self, original_done_cb, output_path):
        """If the user ticked the Auto-transcribe checkbox AND the
        active mfr supports it, return a wrapped done_cb that kicks
        off the transcribe pipeline after a successful Extract.
        Otherwise return the original done_cb unchanged.
        """
        if not getattr(
                self._current_mfr.capabilities, "transcribe", False):
            return original_done_cb
        if not getattr(self.window, "transcribe_var", None):
            return original_done_cb
        if not self.window.transcribe_var.get():
            return original_done_cb

        def wrapped(success, summary):
            if self._cancel_requested or not success:
                # Cancelled or failed → finalize now, don't chain.
                original_done_cb(success, summary)
                return
            # Defer the original done_cb until transcribe finishes,
            # otherwise the GUI's "Extract Complete" modal would steal
            # focus before transcribe even starts.
            self.msg_queue.put(LogMsg(
                "Extract done; chaining auto-transcribe...", "info"))
            # wrapped() runs on the Extract pipeline's worker thread.
            # Hop to the main thread before touching any Tk widgets
            # inside _start_transcribe (set_running, reset_steps, etc.)
            # -- root.after(0, ...) is the cheapest cross-thread hand-off.
            self.root.after(0, lambda: self._start_transcribe(
                assets_dir_override=output_path,
                outer_done_summary=summary,
                outer_done_cb=original_done_cb,
            ))
        return wrapped

    # ------------------------------------------------------------------
    # Direct-SSD pre-flight (elevation gate)
    # ------------------------------------------------------------------

    def _confirm_admin_for_ssd(self):
        """Defence-in-depth elevation check before a Direct-SSD run.

        Windows-only gate: ``wsl --mount`` and ``Set-Disk -IsOffline``
        demand elevation and there's no in-process way around that.
        macOS / Linux handle elevation differently — the pipeline's
        :meth:`_debugfs_run_elevated` pops an osascript / pkexec
        password dialog the moment it hits a permission-denied, so
        the user runs the app normally and approves the prompt.
        Blocking here on macOS/Linux would lock the user out for no
        reason.

        The GUI already disables the Extract / Apply Modifications
        buttons when this gate applies — so this normally won't
        fire.  Kept as a last-line guard for code paths that
        bypass the GUI (settings restored mid-run, keyboard
        shortcut, future entry points).

        Returns True if the caller may proceed; False if they must
        abort.
        """
        import sys
        if sys.platform != "win32":
            return True
        from .core.admin import is_admin
        if is_admin():
            return True
        messagebox.showerror(
            "Administrator Required",
            "Direct-SSD mode needs Windows Administrator "
            "privileges.\n\n"
            "wsl --mount and Set-Disk -IsOffline are both gated by "
            "Windows itself behind elevation — there is no "
            "workaround at the app level.\n\n"
            "To proceed:\n"
            "  1.  Close this app.\n"
            "  2.  Right-click the \"Pinball Asset Decryptor\" "
            "shortcut.\n"
            "  3.  Choose \"Run as administrator\".")
        return False

    # ------------------------------------------------------------------
    # Direct-SSD extract (JJP-only as of v0.6.5)
    # ------------------------------------------------------------------

    def _start_direct_ssd_extract(self):
        """Dispatch the Direct-SSD extract pipeline from the GUI."""
        # Pre-flight: Direct-SSD on Windows needs Administrator.  Both
        # Set-Disk -IsOffline and wsl --mount <physical drive> are
        # gated by Windows itself; running without elevation fails
        # with a cryptic WSL_E_ELEVATION_NEEDED_TO_MOUNT_DISK halfway
        # through the run.  Catch it BEFORE we start so the user
        # gets a clear modal + one-click UAC restart.
        if not self._confirm_admin_for_ssd():
            return

        device_path = self.window.extract_drive_var.get().strip()
        output_path = self.window.extract_output_var.get().strip()
        override_raw = (self.window
                        .extract_partition_override_var.get().strip())

        if not device_path:
            messagebox.showwarning(
                "No SSD selected",
                "Pick a drive from the Game SSD dropdown.\n\n"
                "If the dropdown is empty, click Refresh — and make "
                "sure the SSD is connected.")
            return
        if not output_path:
            messagebox.showwarning(
                "Missing Output",
                "Please select an output folder.")
            return
        if self._extract_overwrite_risk(output_path):
            if not messagebox.askyesno(
                "Output Folder Not Empty",
                "The output folder already contains files this extract "
                "would overwrite.\n\nContinue?",
                icon="warning",
            ):
                return

        partition_override = None
        if override_raw:
            try:
                partition_override = int(override_raw)
            except ValueError:
                messagebox.showerror(
                    "Invalid partition number",
                    f"\"Force partition #\" must be a whole number "
                    f"(got: {override_raw!r}).\n\n"
                    f"Leave blank to auto-discover.")
                return

        self._record_path_history(extract_output=output_path)
        self._save_settings()

        # Point the shared assets folder at this extract's output dir so the
        # Replace / Write / Mod Pack tabs default to what we just pulled off the
        # card (same as the file Extract path).
        self.window.write_assets_var.set(output_path)

        self._active_mode = "extract"
        self._current_run_is_direct_ssd = True
        self._cancel_requested = False
        self.window.set_running(True, mode="extract")
        # Restore the standard Extract phase tuple (a prior chained
        # transcribe / Music-ID run may have swapped it) before resetting.
        self.window._refresh_extract_phases()
        self.window.reset_steps(mode="extract")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        # Chain auto-name (transcribe + music-ID) after a successful Direct-SD
        # extract, exactly like the file Extract path: wrap done_cb inner-first
        # (music-ID runs AFTER transcribe).  Each wrap is a no-op when its
        # checkbox is off.
        chained_done_cb = self._maybe_wrap_done_for_music_id(
            done_cb, output_path)
        chained_done_cb = self._maybe_wrap_done_for_transcribe(
            chained_done_cb, output_path)
        self.pipeline = self._current_mfr.make_direct_ssd_extract_pipeline(
            device_path, output_path,
            log_cb, phase_cb, progress_cb, chained_done_cb,
            partition_override=partition_override,
            **self._collect_asset_filter_kwargs(),
            **self._collect_extract_category_kwargs(),
            **self._collect_duration_names_kwargs(),
        )
        # Guard: non-BasePipeline plugins (e.g. JJP) lack this hook — see the
        # matching call in the basic-extract path above.
        if hasattr(self.pipeline, "set_log_line_cb"):
            self.pipeline.set_log_line_cb(self._post_log_line)
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    def _collect_asset_filter_kwargs(self):
        """Build the per-category extract-filter kwargs for the
        manufacturer's pipeline factory.

        Only the plugins that advertise ``capabilities.asset_filters``
        get these kwargs (returning an empty dict otherwise keeps
        every other plugin's factory signature unchanged).  JJP maps
        them directly onto the upstream pipeline's
        ``extract_graphics`` / ``extract_sounds`` / ``full_dump``
        constructor params.
        """
        if (self._current_mfr is None
                or not getattr(
                    self._current_mfr.capabilities, "asset_filters",
                    False)):
            return {}
        return {
            "extract_graphics": bool(
                self.window.extract_graphics_var.get()),
            "extract_sounds": bool(
                self.window.extract_sounds_var.get()),
            "full_dump": bool(
                self.window.extract_filesystem_var.get()),
        }

    def _extract_overwrite_risk(self, output_path):
        """True if this extract would actually overwrite something in
        *output_path* (drives the "Output Folder Not Empty" confirm).

        For plugins with per-type Extract checkboxes the category keys map
        1:1 onto the output subfolders (audio/ video/ images/ text/), so
        only the SELECTED categories' non-empty subfolders count —
        monkeybug deleted audio/ to re-extract audio alone and still got
        warned about the leftover video/ + images/.  Top-level sidecars
        (.checksums.md5, callouts.csv, ...) are app-regenerated metadata,
        not user edits, so they don't count.  Plugins without categories
        keep the conservative any-content check."""
        if not os.path.isdir(output_path):
            return False
        cats = (self._collect_extract_category_kwargs()
                .get("extract_categories"))
        try:
            if not cats:
                return bool(os.listdir(output_path))
            return any(
                selected and os.path.isdir(os.path.join(output_path, key))
                and os.listdir(os.path.join(output_path, key))
                for key, selected in cats.items())
        except OSError:
            return False

    def _collect_extract_category_kwargs(self):
        """Build the ``extract_categories={key: bool}`` kwarg for the extract
        factory from the per-type checkboxes (capabilities.extract_categories).

        Empty dict for plugins without the capability (keeps their factory
        signature unchanged).  Used by Stern (Audio / Video / Images / Text)."""
        if (self._current_mfr is None
                or not getattr(self._current_mfr.capabilities,
                               "extract_categories", ())):
            return {}
        vars_ = getattr(self.window, "_extract_category_vars", {}) or {}
        if not vars_:
            return {}
        return {"extract_categories":
                {key: bool(var.get()) for key, var in vars_.items()}}

    def _collect_duration_names_kwargs(self):
        """``{"duration_names": bool}`` for plugins that advertise
        ``capabilities.audio_duration_names`` (length-prefixed extract audio
        filenames); empty dict otherwise so other factories' signatures stay
        unchanged."""
        if (self._current_mfr is None
                or not getattr(self._current_mfr.capabilities,
                               "audio_duration_names", False)):
            return {}
        return {"duration_names":
                bool(self.window.duration_names_var.get())}

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _start_write(self):
        if not self._current_mfr.capabilities.write:
            return

        # Restore the standard write phase row in case a prior flash-image run
        # left it showing the Check/Write/Flush steps (set_write_phases swaps
        # it; this picks the correct build/direct tuple back).
        self.window._refresh_extract_phases()

        # Direct-SSD write branch (see _start_extract for the
        # symmetric extract version).  In SSD mode there is no
        # original ISO and no output folder — the SSD itself is the
        # destination.
        if (self._current_mfr.capabilities.direct_ssd
                and getattr(self.window, "write_input_source_var", None)
                is not None
                and self.window.write_input_source_var.get() == "ssd"):
            self._start_direct_ssd_write()
            return

        original = self.window.write_upd_var.get().strip()
        assets_dir = self.window.write_assets_var.get().strip()
        output_dir = self.window.write_output_var.get().strip()

        if not original:
            messagebox.showwarning("Missing Input",
                "Please select the original file.")
            return
        if not os.path.isfile(original):
            messagebox.showerror("File Not Found",
                f"Original file not found:\n{original}")
            return
        if not assets_dir:
            messagebox.showwarning("Missing Input",
                "Please select the modified assets folder.")
            return
        if not os.path.isdir(assets_dir):
            messagebox.showerror("Invalid Folder",
                f"Folder not found:\n{assets_dir}")
            return
        if not output_dir:
            messagebox.showwarning("Missing Input",
                "Please select an output folder.")
            return

        # Resolve the output filename.  The Write tab's File Name box carries
        # the built file's name — pre-filled with the original's name plus the
        # plugin's distinguishing suffix (e.g. Stern's "-modified"), editable by
        # the user.  Fall back to that same default here if the box is somehow
        # empty (older settings, scripted call).  A full file path typed into
        # the Output Folder box is still honoured directly.
        build_name = ""
        name_var = getattr(self.window, "write_filename_var", None)
        if name_var is not None:
            build_name = name_var.get().strip()
        if os.sep in build_name or (os.altsep and os.altsep in build_name):
            messagebox.showwarning("Invalid File Name",
                "The build's File Name can't contain a folder separator.\n\n"
                "Set the destination folder in Output Folder and keep File "
                "Name to a plain file name.")
            return
        if not build_name:
            build_name = os.path.basename(original)
            suffix = getattr(self._current_mfr, "write_output_suffix", "")
            if not suffix and getattr(
                    self._current_mfr.capabilities, "flash_image", False):
                suffix = "-modified"
            if suffix:
                stem, ext = os.path.splitext(build_name)
                build_name = f"{stem}{suffix}{ext}"
        # Force the plugin's required output extension (e.g. Stern Spike 2's
        # ".raw", CGC's ".img") so a user-typed name is never extensionless or
        # in the wrong format for the machine's imaging tools.
        build_name = self._current_mfr.force_write_ext(build_name)
        primary_ext = (self._current_mfr.input_spec.extensions[0].lower()
                       if self._current_mfr.input_spec.extensions else "")
        if primary_ext and output_dir.lower().endswith(primary_ext):
            output_path = output_dir
        else:
            output_path = os.path.join(output_dir, build_name)

        if os.path.abspath(output_path) == os.path.abspath(original):
            messagebox.showerror("Same File",
                "The build's name matches the original file.\n\n"
                "Rename the build (File Name) or choose a different output "
                "folder so it doesn't overwrite the original.")
            return

        # Collision check: warn before clobbering an existing build with the
        # same name (a re-build, or a name the user picked that's already
        # taken).  Overwriting the original is caught above; everything else is
        # the user's call.
        if os.path.exists(output_path):
            if not messagebox.askyesno("File Exists",
                f"A file named:\n\n    {os.path.basename(output_path)}\n\n"
                f"already exists in:\n{os.path.dirname(output_path)}\n\n"
                "Building will overwrite it.  Continue?",
                icon="warning"):
                return

        # Catch the silent "assigned replacements for one folder, then pointed
        # Build at another" trap: the Write flow's folder-match guard would
        # drop those assignments and quietly build an unmodified image.  Warn
        # before we do all the work.
        mismatches = self.window.replacement_folder_mismatches(assets_dir)
        if mismatches:
            lines = "\n".join(
                f"  • {n} {label} replacement(s) — assigned for:\n        {folder}"
                for label, n, folder in mismatches)
            if not messagebox.askyesno(
                "Replacements won't be applied",
                "You assigned replacement(s) on the Replace tab(s), but they "
                "were made against a different folder than the \"Modified "
                "assets folder\" you're building:\n\n"
                f"{lines}\n\n"
                f"Building now produces an image WITHOUT those changes.  To "
                f"apply them, point the assets folder at the path above (or "
                f"re-assign for this folder).\n\n"
                "Build anyway?"):
                return

        # Validate a manual update-version date (BOF, Auto unchecked).
        if getattr(self._current_mfr.capabilities,
                   "write_version_date", False):
            err = self.window.write_version_validation_error()
            if err:
                messagebox.showwarning("Invalid Version Date", err)
                return

        self._record_path_history(write_original=original,
                                  write_assets=assets_dir,
                                  write_output=output_dir)
        self._save_settings()

        self._active_mode = "write"
        self._cancel_requested = False
        self.window.set_running(True, mode="write")
        self.window.reset_steps(mode="write")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()

        write_kwargs = {}
        if getattr(self._current_mfr.capabilities,
                   "write_version_date", False):
            # None in Auto mode; an explicit "YYYY.MM.DD" when the user
            # unchecks Auto and types one.  validate_write() already
            # blocked an invalid manual entry before we got here.
            write_kwargs["version_date_override"] = (
                self.window.write_version_override())

        if getattr(self._current_mfr.capabilities,
                   "audio_loop_inject", False):
            write_kwargs["loop_names"] = self.window.audio_loop_basenames(
                assets_dir)

        if getattr(self._current_mfr.capabilities,
                   "audio_keep_length_override", False):
            write_kwargs["keep_full_length_names"] = (
                self.window.audio_keep_full_rels(assets_dir))

        self.pipeline = self._current_mfr.make_write_pipeline(
            original, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb,
            **write_kwargs,
        )
        threading.Thread(
            target=self._run_pipeline_with_audio, args=(assets_dir,),
            daemon=True).start()

    # ------------------------------------------------------------------
    # Direct-SSD write (JJP-only as of v0.6.5)
    # ------------------------------------------------------------------

    def _start_direct_ssd_write(self):
        """Dispatch the Direct-SSD write pipeline from the GUI."""
        if not self._confirm_admin_for_ssd():
            return

        device_path = self.window.write_drive_var.get().strip()
        assets_dir = self.window.write_assets_var.get().strip()
        override_raw = (self.window
                        .write_partition_override_var.get().strip())

        if not device_path:
            messagebox.showwarning(
                "No SSD selected",
                "Pick a drive from the Game SSD dropdown.\n\n"
                "If the dropdown is empty, click Refresh — and make "
                "sure the SSD is connected.")
            return
        if not assets_dir:
            messagebox.showwarning(
                "Missing Input",
                "Please select the modified assets folder.")
            return
        if not os.path.isdir(assets_dir):
            messagebox.showerror(
                "Invalid Folder",
                f"Folder not found:\n{assets_dir}")
            return

        partition_override = None
        if override_raw:
            try:
                partition_override = int(override_raw)
            except ValueError:
                messagebox.showerror(
                    "Invalid partition number",
                    f"\"Force partition #\" must be a whole number "
                    f"(got: {override_raw!r}).\n\n"
                    f"Leave blank to auto-discover.")
                return

        # Last-chance confirmation — Direct-SSD writes go straight to
        # the connected drive with no undo.  The red warning above
        # the panel says this too; one more nag here costs the user
        # nothing and prevents a misclick on the wrong drive.
        if not messagebox.askyesno(
            "Write directly to SSD?",
            f"This will write modified files DIRECTLY to the "
            f"selected SSD:\n\n  {device_path}\n\n"
            f"There is no separate output file — changes apply to "
            f"the drive itself.\n\n"
            f"Proceed?",
        ):
            return

        self._record_path_history(write_assets=assets_dir)
        self._save_settings()

        self._active_mode = "write"
        self._current_run_is_direct_ssd = True
        self._cancel_requested = False
        self.window.set_running(True, mode="write")
        self.window.reset_steps(mode="write")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        ssd_write_kwargs = {}
        if getattr(self._current_mfr.capabilities,
                   "audio_keep_length_override", False):
            ssd_write_kwargs["keep_full_length_names"] = (
                self.window.audio_keep_full_rels(assets_dir))
        self.pipeline = self._current_mfr.make_direct_ssd_write_pipeline(
            device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override,
            **ssd_write_kwargs,
        )
        threading.Thread(
            target=self._run_pipeline_with_audio, args=(assets_dir,),
            daemon=True).start()

    def _start_flash_image(self, image_path, device_path):
        """Flash a pre-built image onto a card (dd-style whole-image write).

        The image + target card were collected and confirmed by the flash
        dialog (``gui.flash_dialog.FlashImageDialog``); this just runs the
        manufacturer's flash pipeline through the normal status area.  Admin and
        the destructive-write confirmation are enforced in the dialog before we
        get here."""
        mfr = self._current_mfr
        if mfr is None or not mfr.capabilities.flash_image:
            return

        self._save_settings()
        self._active_mode = "write"
        # A flash is a raw-device write — mark it so a success auto-dismisses
        # the macOS Full Disk Access banner (proof FDA works), same as Direct-SD.
        self._current_run_is_direct_ssd = True
        self._cancel_requested = False
        # Show the flash-specific phase row (Check card / Write image / Flush).
        self.window.set_write_phases(getattr(mfr, "flash_phases", ()))
        self.window.set_running(True, mode="write")
        # The Flash button doubles as this run's live Cancel (set_running
        # restores it when the run ends, whatever way it ends).
        self.window.set_flash_running(True)
        self.window.reset_steps(mode="write")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        self.pipeline = mfr.make_flash_pipeline(
            image_path, device_path, log_cb, phase_cb, progress_cb, done_cb)
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # ------------------------------------------------------------------
    # Transcribe (CGC opt-in, faster-whisper)
    # ------------------------------------------------------------------

    def _start_transcribe(self, assets_dir_override=None,
                          outer_done_summary=None, outer_done_cb=None):
        """Run the transcribe pipeline.

        Called from ``_start_extract`` (chained) when the user ticked
        the auto-transcribe checkbox.  ``assets_dir_override`` is the
        Extract output dir (passed directly to bypass any race with
        the Tk var); ``outer_done_summary`` + ``outer_done_cb`` let us
        defer the Extract's "Complete" modal until transcribe finishes
        so the user sees one terminal dialog instead of two.
        """
        if not self._current_mfr.capabilities.transcribe:
            return
        if outer_done_cb is not None:
            if self._cancel_requested:        # cancelled upstream → don't chain
                outer_done_cb(False, outer_done_summary or "")
                return
        else:
            self._cancel_requested = False     # standalone = a fresh run
        assets_dir = (assets_dir_override
                      or self.window.extract_output_var.get().strip()
                      or self.window.write_assets_var.get().strip())
        if not assets_dir or not os.path.isdir(assets_dir):
            messagebox.showerror(
                "Invalid Folder",
                f"Cannot run transcribe — folder not found:\n{assets_dir}")
            if outer_done_cb:
                outer_done_cb(True, outer_done_summary or "")
            return

        # Stay in extract mode so the status row keeps its labels.
        self._active_mode = "extract"
        # Only call set_running(True) when transcribe is the FIRST
        # action in the chain.  When it's chained after Extract
        # (outer_done_cb is set), the running state is already on and
        # calling it again would reset the elapsed timer to zero
        # mid-pipeline -- the user just saw Extract take 60s and now
        # the clock would say 00:00 again during transcribe.
        if outer_done_cb is None:
            self.window.set_running(True, mode="extract")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        # Give Auto-transcribe its OWN status block: swap the phase row to the
        # transcribe step list ("Load model / Transcribe / Rename / Write CSV")
        # and let phase_cb drive it, instead of leaving the Extract row's last
        # chip stuck active.  (Runs on the main thread -- chained via root.after,
        # standalone is a direct call -- so touching Tk here is safe.)
        self.window.show_chained_phases(
            getattr(self._current_mfr, "transcribe_phases", ()))

        # If we're chained, replace the normal done_cb with one that
        # merges transcribe's summary into the Extract summary and
        # delegates the final "Complete" modal to outer_done_cb.
        if outer_done_cb is not None:
            head = (outer_done_summary or "").rstrip()
            def merged_done(transcribe_success, transcribe_summary):
                label = ("Auto-transcribe:" if transcribe_success
                         else "Auto-transcribe failed:")
                combined = f"{head}\n\n{label}\n{transcribe_summary}"
                # Extract already succeeded; surface that as success
                # even if transcribe failed (the asset folder is still
                # usable -- the user can re-tick and try again).
                outer_done_cb(True, combined)
            done_cb = merged_done

        # "Auto-name call-outs" is a single action = transcribe + rename, so
        # always rename (the callouts.csv is still written either way).
        # Model size follows the ⚙ menu's voice-recognition quality pick.
        self.pipeline = self._current_mfr.make_transcribe_pipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=True,
            model_size=self.window.voice_quality_var.get())
        # Keyed log lines (the model-download "... 340 / 1500 MB" counter
        # rewrites one line in place instead of appending every tick).
        if hasattr(self.pipeline, "set_log_line_cb"):
            self.pipeline.set_log_line_cb(self._post_log_line)
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    def _maybe_wrap_done_for_music_id(self, original_done_cb, output_path):
        """If the music-ID checkbox is on AND the active mfr supports it, wrap
        done_cb so a successful Extract (then transcribe) chains the online
        AcoustID lookup.  Otherwise return done_cb unchanged."""
        if not getattr(self._current_mfr.capabilities, "music_id", False):
            return original_done_cb
        if not getattr(self.window, "music_id_var", None):
            return original_done_cb
        if not self.window.music_id_var.get():
            return original_done_cb

        def wrapped(success, summary):
            if self._cancel_requested or not success:
                original_done_cb(success, summary)
                return
            self.msg_queue.put(LogMsg(
                "Chaining online music identification...", "info"))
            self.root.after(0, lambda: self._start_music_id(
                assets_dir_override=output_path,
                outer_done_summary=summary,
                outer_done_cb=original_done_cb,
            ))
        return wrapped

    def _start_music_id(self, assets_dir_override=None,
                        outer_done_summary=None, outer_done_cb=None):
        """Run the online music-ID pipeline (chained after a successful
        Extract/transcribe).  Mirrors ``_start_transcribe``."""
        if not self._current_mfr.capabilities.music_id:
            return
        if outer_done_cb is not None:
            if self._cancel_requested:        # cancelled upstream → don't chain
                outer_done_cb(False, outer_done_summary or "")
                return
        else:
            self._cancel_requested = False     # standalone = a fresh run
        assets_dir = (assets_dir_override
                      or self.window.extract_output_var.get().strip()
                      or self.window.write_assets_var.get().strip())
        if not assets_dir or not os.path.isdir(assets_dir):
            messagebox.showerror(
                "Invalid Folder",
                f"Cannot identify music — folder not found:\n{assets_dir}")
            if outer_done_cb:
                outer_done_cb(True, outer_done_summary or "")
            return

        self._active_mode = "extract"
        if outer_done_cb is None:
            self.window.set_running(True, mode="extract")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        # Music-ID gets its OWN status block ("Scan / Identify / Write CSV"),
        # swapping the phase row + driving it with phase_cb (same hand-off rules
        # as _start_transcribe -- this runs on the main thread).
        self.window.show_chained_phases(
            getattr(self._current_mfr, "music_id_phases", ()))

        if outer_done_cb is not None:
            head = (outer_done_summary or "").rstrip()

            def merged_done(ok, summary):
                label = "Music ID:" if ok else "Music ID failed:"
                outer_done_cb(True, f"{head}\n\n{label}\n{summary}")
            done_cb = merged_done

        self.pipeline = self._current_mfr.make_music_id_pipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=True)
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # ------------------------------------------------------------------
    # Apply delta
    # ------------------------------------------------------------------

    def _start_apply_delta(self):
        if not self._current_mfr.capabilities.apply_delta:
            return

        assets_dir = self.window.write_assets_var.get().strip()
        if not assets_dir or not os.path.isdir(assets_dir):
            messagebox.showwarning(
                "Missing Assets Folder",
                "Pick the extracted assets folder on the Write tab first.")
            return

        primary_ext = (self._current_mfr.input_spec.extensions[0].lower()
                       if self._current_mfr.input_spec.extensions else "")
        delta_path = filedialog.askopenfilename(
            title=f"Select delta {primary_ext or 'file'} to apply on top",
            filetypes=[(self._current_mfr.input_spec.label,
                        " ".join(f"*{e}" for e in
                                 self._current_mfr.input_spec.extensions)
                        or "*.*"),
                       ("All files", "*.*")],
        )
        if not delta_path:
            return

        if not messagebox.askyesno(
            "Apply Delta",
            f"Overlay\n  {os.path.basename(delta_path)}\n"
            f"on top of\n  {assets_dir}\n\n"
            f"Files in the delta will overwrite matching files in the "
            f"folder, and new files will be added.\n\nContinue?"
        ):
            return

        self.window.append_log(
            f"Applying delta: {os.path.basename(delta_path)}", "info")

        mfr = self._current_mfr

        def _run():
            try:
                overwritten, added, _total = mfr.apply_delta(
                    assets_dir, delta_path,
                    log_cb=lambda t, l="info": self.msg_queue.put(LogMsg(t, l)),
                    progress_cb=lambda c, t, d="": self.msg_queue.put(
                        ProgressMsg(c, t, d)),
                )
                summary = (f"Delta applied:\n\n"
                           f"  {added} new file(s)\n"
                           f"  {overwritten} overwritten")
                self.root.after(0, lambda: messagebox.showinfo(
                    "Delta Applied", summary))
            except Exception as e:
                self.msg_queue.put(LogMsg(f"Apply delta failed: {e}", "error"))
                self.root.after(0, lambda: messagebox.showerror(
                    "Apply Delta Failed", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    # ------------------------------------------------------------------
    # Mod pack
    # ------------------------------------------------------------------

    def _start_export(self):
        if not self._current_mfr.capabilities.modpack:
            return

        assets_dir = self.window.write_assets_var.get().strip()
        if not assets_dir or not os.path.isdir(assets_dir):
            messagebox.showwarning("Missing Input",
                "Select an assets folder on the Write tab first.")
            return
        if not os.path.isfile(os.path.join(assets_dir, ".checksums.md5")):
            messagebox.showerror("No Baseline Checksums",
                "No .checksums.md5 found.  Extract first.")
            return

        zip_path = filedialog.asksaveasfilename(
            title="Save Mod Pack As",
            defaultextension=".zip",
            initialfile=f"{self._current_mfr.key}_mod_pack.zip",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if not zip_path:
            return

        self.window.append_log("Exporting mod pack...", "info")

        def _run():
            try:
                n, path = modpack.export_mod_pack(
                    assets_dir, zip_path,
                    log_cb=lambda t, l="info": self.msg_queue.put(LogMsg(t, l)),
                    progress_cb=lambda c, t, d="": self.msg_queue.put(
                        ProgressMsg(c, t, d)),
                )
                self.msg_queue.put(LogMsg(
                    f"Mod pack: {n} file(s) → {path}", "success"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Export Complete",
                    f"Mod pack saved to:\n{path}\n\n"
                    f"Contains {n} modified file(s)."))
            except Exception as e:
                self.msg_queue.put(LogMsg(f"Export failed: {e}", "error"))
                self.root.after(0, lambda: messagebox.showerror(
                    "Export Failed", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _start_import(self):
        if not self._current_mfr.capabilities.modpack:
            return

        assets_dir = self.window.write_assets_var.get().strip()
        if not assets_dir or not os.path.isdir(assets_dir):
            messagebox.showwarning("Missing Input",
                "Select an assets folder on the Write tab first.")
            return

        zip_path = filedialog.askopenfilename(
            title="Select Mod Pack ZIP",
            filetypes=[("Zip files", "*.zip"), ("All files", "*.*")],
        )
        if not zip_path:
            return

        if not messagebox.askyesno(
            "Import Mod Pack",
            f"Extract mod pack into:\n  {assets_dir}\n\n"
            f"Existing files with the same names will be overwritten.\n\nContinue?",
        ):
            return

        self.window.append_log("Importing mod pack...", "info")

        def _run():
            try:
                n = modpack.import_mod_pack(
                    zip_path, assets_dir,
                    log_cb=lambda t, l="info": self.msg_queue.put(LogMsg(t, l)),
                    progress_cb=lambda c, t, d="": self.msg_queue.put(
                        ProgressMsg(c, t, d)),
                )
                self.msg_queue.put(LogMsg(
                    f"Mod pack imported: {n} file(s).", "success"))
                self.root.after(0, lambda: messagebox.showinfo(
                    "Import Complete",
                    f"Imported {n} file(s)."))
            except Exception as e:
                self.msg_queue.put(LogMsg(f"Import failed: {e}", "error"))
                self.root.after(0, lambda: messagebox.showerror(
                    "Import Failed", str(e)))

        threading.Thread(target=_run, daemon=True).start()

    def _start_transfer_mods(self):
        """Pull the user's mods from the OLD extract folder onto the NEW one
        (both picked on the Mod Pack tab), reconciling layout changes.  Shows a
        reconciliation summary before applying, then re-scans so the transferred
        assignments appear on the Replace tabs."""
        if not getattr(self._current_mfr.capabilities, "mod_transfer", False):
            return
        from .core import mod_transfer

        source_dir = (self.window.transfer_src_var.get() or "").strip()
        target_dir = (self.window.transfer_dst_var.get() or "").strip()
        if not source_dir or not os.path.isdir(source_dir):
            messagebox.showwarning(
                "Pick the old extract",
                "Set 'Old extract' to the folder that has your mods (your "
                "previous version's extract).")
            return
        if not target_dir or not os.path.isdir(target_dir):
            messagebox.showwarning(
                "Pick the new extract",
                "Set 'New extract' to the NEW version's freshly-extracted "
                "folder (the one your mods move into).")
            return
        source_dir = os.path.normpath(source_dir)
        target_dir = os.path.normpath(target_dir)
        if os.path.normcase(source_dir) == os.path.normcase(target_dir):
            messagebox.showwarning(
                "Same folder",
                "The old and new extract folders are the same. Pick your "
                "previous version's extract as the old one.")
            return

        # Optional 3rd input: a stock extract of the OLD version.  Its presence
        # (not a modal) selects the accurate baseline route in the baked case.
        old_stock = (self.window.transfer_oldstock_var.get() or "").strip()
        if old_stock:
            old_stock = os.path.normpath(old_stock)
            if not os.path.isdir(old_stock):
                messagebox.showwarning(
                    "Old stock extract not found",
                    "The optional 'Stock extract of the OLD version' isn't a "
                    "folder. Fix the path or clear it to compare directly.")
                return
            if os.path.normcase(old_stock) in (os.path.normcase(source_dir),
                                               os.path.normcase(target_dir)):
                messagebox.showwarning(
                    "Wrong folder",
                    "The optional stock extract must be a THIRD folder: a "
                    "clean, unmodified extract of the SAME old version as your "
                    "modded one.")
                return
        else:
            old_stock = None

        # 4th input: the new version's base card image the build patches onto.
        new_img = (self.window.transfer_newimg_var.get() or "").strip()
        if new_img:
            new_img = os.path.normpath(new_img)
            if not os.path.isfile(new_img):
                messagebox.showwarning(
                    "Base image not found",
                    "The 'New version card image (.raw)' isn't a file. Fix the "
                    "path or clear it — you can also set it later on the Write "
                    "tab.")
                return
        else:
            new_img = None
        self._transfer_old_stock = old_stock
        self._transfer_new_img = new_img

        if getattr(self, "_transfer_busy", False):
            messagebox.showinfo(
                "Comparison running",
                "A transfer comparison is already running — progress is in "
                "the log below.")
            return

        self.window.append_log(
            "Transfer: reading pending edits from %s ..." % source_dir, "info")
        self._transfer_worker(
            lambda: mod_transfer.plan_transfer(
                source_dir, target_dir, log_cb=self._transfer_log_cb()),
            lambda plan: self._transfer_plan_ready(source_dir, target_dir,
                                                   plan),
            "Transfer failed")

    def _transfer_log_cb(self):
        """Worker-thread-safe logger for the transfer comparisons: lines land
        in the main log via the message queue."""
        return lambda t, l="info": self.msg_queue.put(LogMsg(t, l))

    def _transfer_worker(self, work, done, fail_title):
        """Run *work()* on a worker thread — the extract comparisons are
        minutes of file I/O on big or cloud-synced folders, so the UI must
        stay live and the log must keep moving — then continue with
        *done(result)* on the main thread.  One at a time via
        ``_transfer_busy``."""
        self._transfer_busy = True

        def _finish(result):
            self._transfer_busy = False
            done(result)

        def _fail(e):
            self._transfer_busy = False
            messagebox.showerror(fail_title, "Couldn't finish:\n%s" % e)

        def _work():
            try:
                result = work()
            except Exception as e:
                self.msg_queue.put(LogMsg("Transfer step failed: %s" % e,
                                          "error"))
                self.root.after(0, _fail, e)
                return
            self.root.after(0, _finish, result)

        threading.Thread(target=_work, daemon=True).start()

    def _transfer_plan_ready(self, source_dir, target_dir, plan):
        """Main-thread continuation of _start_transfer_mods once the pending-
        edits plan is computed."""
        totals = plan["totals"]
        if totals["transfer"] == 0 and totals["flagged"] == 0:
            if totals["dropped"]:
                # The source HAS pending edits — they just have no home in the
                # new version.  Not the baked-in-mods case.
                messagebox.showinfo(
                    "Nothing to transfer",
                    "That folder's edits have no matching slot or text in the "
                    "new version, so none of them can transfer.")
            else:
                self._transfer_baked_mods(source_dir, target_dir)
            return

        self._confirm_apply_transfer(source_dir, target_dir, plan)

    def _transfer_baked_mods(self, modded_dir, target_dir):
        """Route the baked-in-mods case (old extract has no pending Replace
        edits — modded with another tool before it was extracted) using the
        optional 3rd field instead of a modal:

        * Stock extract of the OLD version provided → diff modded-vs-stock,
          then run the normal content-matched transfer with the STOCK extract
          as the source (its WAVs are the stock content the audio matching
          keys off).  Full fidelity — the only route that carries audio/text.
        * Field empty → diff the modded extract DIRECTLY against the new one.
          Filename-keyed images/videos transfer; audio/text can't be told
          apart from the factory's own version-to-version changes."""
        stock_dir = getattr(self, "_transfer_old_stock", None)
        if not stock_dir:
            self.window.append_log(
                "No stock old-version extract given — comparing the modded "
                "extract directly against the new one (images + video only).",
                "info")
            self._transfer_direct_diff(modded_dir, target_dir)
            return
        self.window.append_log(
            "Using the stock old-version extract as a baseline — this is the "
            "accurate route and can also carry audio and text.", "info")
        from .core import mod_transfer

        log_cb = self._transfer_log_cb()
        self.window.append_log(
            "Comparing the modded extract against the stock same-version "
            "extract — progress below.", "info")

        def _work():
            diff = mod_transfer.diff_baked_mods(modded_dir, stock_dir,
                                                log_cb=log_cb)
            saved = diff["saved"]
            n_found = (len(saved["audio"]) + len(saved["video"])
                       + len(saved["image"]) + len(diff["text_rows"]))
            plan = None
            if n_found:
                plan = mod_transfer.plan_transfer(
                    stock_dir, target_dir, saved=saved,
                    src_text_rows=diff["text_rows"], log_cb=log_cb)
            return diff, plan

        self._transfer_worker(
            _work,
            lambda res: self._baked_diff_ready(modded_dir, stock_dir,
                                               target_dir, res[0], res[1]),
            "Compare failed")

    def _baked_diff_ready(self, modded_dir, stock_dir, target_dir, diff, plan):
        """Main-thread continuation of the stock-baseline compare."""
        saved = diff["saved"]
        n_found = (len(saved["audio"]) + len(saved["video"])
                   + len(saved["image"]) + len(diff["text_rows"]))
        if not n_found or plan is None:
            messagebox.showinfo(
                "No differences found",
                "The two extracts have identical content — no baked-in mods "
                "were detected. Make sure the stock extract is the same code "
                "version, extracted with this same app version.")
            return

        paired = diff["notes"]["paired_audio"]
        if paired >= 20 and len(saved["audio"]) * 2 > paired:
            if not messagebox.askyesno(
                    "Same code version?",
                    "%d of %d sounds differ between the two extracts. That "
                    "many differences usually means the stock extract is a "
                    "DIFFERENT code version, not a real set of mods.\n\n"
                    "Continue anyway?"
                    % (len(saved["audio"]), paired)):
                return

        intro = ("Found %d baked-in mod(s): %d audio, %d video, %d image, "
                 "%d text."
                 % (n_found, len(saved["audio"]), len(saved["video"]),
                    len(saved["image"]), len(diff["text_rows"])))
        self._confirm_apply_transfer(stock_dir, target_dir, plan,
                                     src_saved=saved, intro=intro,
                                     source_label=modded_dir)

    def _transfer_direct_diff(self, modded_dir, target_dir):
        """No-baseline route: diff the modded old extract directly against the
        new one.  Videos pair by on-card path, images by rel; audio/text can't
        be attributed without a baseline — heads-up notes surface what this
        route can't carry.  The comparison runs on a worker thread with
        progress in the log."""
        from .core import mod_transfer

        log_cb = self._transfer_log_cb()
        self.window.append_log(
            "Comparing the old (modded) extract directly against the new one "
            "— progress below; large folders take a while.", "info")
        self._transfer_worker(
            lambda: mod_transfer.plan_direct_diff(modded_dir, target_dir,
                                                  log_cb=log_cb),
            lambda plan: self._direct_diff_ready(modded_dir, target_dir, plan),
            "Compare failed")

    def _direct_diff_ready(self, modded_dir, target_dir, plan):
        """Main-thread continuation of the no-baseline compare."""
        notes = plan["notes"]
        caveats = []
        if notes["audio_unmatched"]:
            caveats.append(
                "%d old sound(s) have no identical sound in the new version — "
                "factory changes, or audio mods this route can't carry "
                "(those need a stock old-version extract)."
                % notes["audio_unmatched"])
        if notes["text_unmatched"]:
            caveats.append(
                "%d old text string(s) aren't in the new version — factory "
                "changes, or text mods this route can't carry."
                % notes["text_unmatched"])
        if notes["video_old_only"] or notes["image_old_only"]:
            caveats.append(
                "%d old video(s) / %d old image(s) have no counterpart in "
                "the new version and were skipped."
                % (notes["video_old_only"], notes["image_old_only"]))

        if plan["totals"]["transfer"] == 0:
            messagebox.showinfo(
                "No image or video differences",
                "No same-named image or video differs between the two "
                "extracts." + ("\n\n" + "\n".join(caveats) if caveats else ""))
            return

        n_vid = len(plan["video"]["matched"])
        n_img = len(plan["image"]["matched"])
        intro = ("Found %d differing video(s) and %d differing image(s) "
                 "between the old and new extracts." % (n_vid, n_img))
        # Without a same-version baseline a difference can be the FACTORY's own
        # between-version re-bake, not a mod.  Carrying those writes old-version
        # bytes over re-baked assets, which the newer game can count as content
        # mismatches (e.g. a "GAME VALIDATION ERROR" tech alert).  A real mod
        # rarely changes dozens of images, so escalate the caution when many do.
        if n_img >= 30:
            intro += ("\n\n%d images differ — that is a lot for a mod, and "
                      "usually means the factory re-baked images between the "
                      "two versions.  Transferring those puts old-version "
                      "content on the new card, which the game can flag.  For "
                      "an accurate transfer, cancel and fill field 3 (a STOCK, "
                      "unmodified extract of the SAME OLD version), which "
                      "carries ONLY your real mods." % n_img)
        else:
            intro += ("\nA difference can also be a factory change between "
                      "versions — after transferring, review the Replace tabs "
                      "and clear anything you didn't mod.")
        if caveats:
            intro += "\n\n" + "\n".join(caveats)
        self._confirm_apply_transfer(modded_dir, target_dir, plan,
                                     src_saved={}, intro=intro)

    def _confirm_apply_transfer(self, source_dir, target_dir, plan,
                                src_saved=None, intro=None, source_label=None):
        """Shared tail of both transfer flows: summarize the plan, confirm,
        apply, and refresh the Replace tabs."""
        from .core import mod_transfer

        totals = plan["totals"]
        if totals["transfer"] == 0 and totals["flagged"] == 0:
            messagebox.showinfo(
                "Nothing to transfer",
                "None of those mods have a matching slot or text in the new "
                "version, so nothing can transfer.")
            return

        summary = self._format_transfer_summary(plan)
        if intro:
            summary = intro + "\n\n" + summary
        if not messagebox.askyesno("Transfer mods?", summary):
            return

        include_flagged = False
        if totals["flagged"]:
            include_flagged = messagebox.askyesno(
                "Apply flagged audio too?",
                "%d audio slot(s) now hold a DIFFERENT sound in the new version "
                "(the index was reused). Applying these would put your "
                "replacement on a different sound than before.\n\n"
                "Apply them anyway?  (No = skip just those; recommended.)"
                % totals["flagged"])

        try:
            res = mod_transfer.apply_transfer(
                source_dir, target_dir, plan, include_flagged=include_flagged,
                src_saved=src_saved)
        except Exception as e:
            messagebox.showerror("Transfer failed",
                                 "Couldn't write the transferred mods:\n%s" % e)
            return

        tags_note = ("" if not res.get("group_tags")
                     else ", %d group name(s)" % res["group_tags"])
        self.window.append_log(
            "Transferred mods from %s: %d audio, %d video, %d image, %d text%s."
            % (source_label or source_dir, res["audio"], res["video"],
               res["image"], res["text"], tags_note), "success")
        # Point the app at the new extract so the Replace tabs / Write show
        # the transferred assignments without a manual re-browse.
        cur = os.path.normpath((self.window.write_assets_var.get() or "")
                               .strip())
        moved_folder = os.path.normcase(cur) != os.path.normcase(target_dir)
        if moved_folder:
            self.window.write_assets_var.set(target_dir)

        # Wire the Write tab's base image to the NEW version's card image so
        # the build patches your mods onto the new firmware (and names the
        # output after it).  This is the step whose absence produced an
        # old-version-named build: the assets moved to the new version but the
        # base image stayed on the old one.
        new_img = getattr(self, "_transfer_new_img", None)
        wired_img = False
        if new_img and os.path.isfile(new_img):
            self.window.write_upd_var.set(new_img)
            wired_img = True
            self.window.append_log(
                "Write tab's base image set to %s — the build targets the new "
                "version." % os.path.basename(new_img), "info")
        self.window.reload_assets_tabs()

        # Spell out the exact next step, in the log (survives the dialog) and
        # on the panel's persistent next-step line.
        if wired_img:
            suffix = getattr(self._current_mfr, "write_output_suffix",
                             "-modified") or "-modified"
            stem, ext = os.path.splitext(os.path.basename(new_img))
            next_step = (
                "Next: open the Write tab and click the build button. It will "
                "produce %s%s%s — your mods on the new version."
                % (stem, suffix, ext))
        else:
            next_step = (
                "Next: open the Write tab, set 'Original' to the NEW version's "
                "card image (.raw), then build. (Tip: set field 4 here first "
                "and it wires that up for you.)")
        self.window.append_log("Transfer complete. " + next_step, "success")
        if hasattr(self.window, "transfer_next_var"):
            self.window.transfer_next_var.set("✓ " + next_step)

        messagebox.showinfo(
            "Transfer complete",
            "Transferred: %d audio, %d video, %d image, %d text%s.\n\n%s%s\n\n%s"
            % (res["audio"], res["video"], res["image"], res["text"],
               tags_note,
               ("The Mod Folder now points at the new extract.\n"
                if moved_folder else ""),
               ("The Write tab's base image is set to the new version.\n"
                if wired_img else ""),
               next_step))

    @staticmethod
    def _format_transfer_summary(plan):
        a = plan["audio"]; v = plan["video"]; i = plan["image"]; t = plan["text"]
        lines = ["Move your mods onto the new extract:", ""]
        lines.append("Audio:  %d matched, %d moved to a new index, "
                     "%d flagged, %d dropped"
                     % (len(a["matched"]), len(a["remapped"]),
                        len(a["flagged"]), len(a["dropped"])))
        lines.append("Video:  %d matched, %d dropped"
                     % (len(v["matched"]), len(v["dropped"])))
        lines.append("Image:  %d matched, %d dropped"
                     % (len(i["matched"]), len(i["dropped"])))
        lines.append("Text:   %d matched, %d dropped"
                     % (len(t["matched"]), len(t["dropped"])))
        g = plan.get("group_tags") or {}
        if g.get("matched") or g.get("dropped"):
            lines.append("Groups: %d renamed group name(s) carried, %d dropped"
                         % (len(g.get("matched", ())),
                            len(g.get("dropped", ()))))
        dropped = plan["totals"]["dropped"]
        if dropped:
            lines.append("")
            lines.append("%d edit(s) can't transfer (the slot/text no longer "
                         "exists in the new version) and will be skipped."
                         % dropped)
        lines.append("")
        lines.append("Your existing edits on the new extract are kept. "
                     "Proceed?")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Replace Audio / Video — auto-applied as part of Write (no manual step)
    # ------------------------------------------------------------------

    def _run_pipeline_with_audio(self, assets_dir):
        """Worker-thread entry for a Write run: apply any Replace-Audio,
        Replace-Video and Replace-Image assignments into the assets folder
        first, then run the pipeline (which repacks the now-changed files).

        Guards against a *silent no-op build*: if the user assigned
        replacements but NONE could be staged (e.g. ffmpeg missing, so every
        convert failed), building would copy the original image unchanged and
        report success — the user flashes it and sees none of their edits.
        We stop loudly instead.  Partial failures are remembered so the
        success dialog can flag which replacements were skipped."""
        pend_a = self._stage_pending_audio(assets_dir)
        pend_v = self._stage_pending_video(assets_dir)
        pend_i = self._stage_pending_image(assets_dir)
        pending = pend_a[0] + pend_v[0] + pend_i[0]
        staged = pend_a[1] + pend_v[1] + pend_i[1]
        failures = pend_a[2] + pend_v[2] + pend_i[2]
        self._staging_failures = failures

        if pending and not staged:
            detail = "\n".join(f"  • {rel}: {err}"
                               for rel, err in failures[:20])
            if len(failures) > 20:
                detail += f"\n  • ... and {len(failures) - 20} more"
            msg = (
                f"None of your {pending} assigned replacement(s) could be "
                f"applied, so the update was NOT built — the output would have "
                f"been an unmodified copy of the original image (it boots fine "
                f"but shows none of your changes).\n\n"
                f"{detail}\n\n"
                f"This is almost always a missing/!unfound ffmpeg (every "
                f"replacement is re-encoded to the game's exact audio format, "
                f"which needs it).  Click \"Install Missing\" above the tabs, "
                f"restart, and try again.")
            self.msg_queue.put(LogMsg(
                "Aborting build: none of the assigned replacements could be "
                "applied, so the output would be unmodified.", "error"))
            self.msg_queue.put(DoneMsg(False, msg))
            return

        self.pipeline.run()

    def _sidecar_pending(self, assets_dir, kind):
        """Rebuild a ``pending_<kind>_assignments``-shaped tuple straight from
        *assets_dir*'s ``.staged_changes.json``.

        The Replace tabs restore the sidecar into memory only when they scan
        the folder — if none has this session (mods just transferred in, or
        the app reopened straight onto Write), ``pending_*_assignments``
        returns None and the build would silently drop the recorded
        assignments.  This fallback re-derives the tuple on the write worker
        thread: re-scan the slots, filter the sidecar to live entries
        (``staged_changes.live_assignments``), probe just the assigned video
        slots, and read the toggles from the sidecar (GUI defaults when the
        sidecar predates them).  Returns ``None`` when the sidecar has nothing
        live for this folder."""
        from .core import staged_changes

        mfr = self._current_mfr
        cap = {"audio": "replace_audio", "video": "replace_video",
               "image": "replace_image"}[kind]
        if (mfr is None or not getattr(mfr.capabilities, cap, False)
                or not assets_dir or not os.path.isdir(assets_dir)):
            return None
        saved = staged_changes.load(assets_dir)
        if not saved.get(kind):
            return None

        def _hook(name):
            try:
                return getattr(mfr, name)(assets_dir)
            except Exception:
                return None

        if kind == "audio":
            from .core.audio_slots import scan_audio_slots
            slots = scan_audio_slots(assets_dir,
                                     roots=_hook("audio_slot_dirs"),
                                     exts=_hook("audio_slot_exts"))
        elif kind == "video":
            from .core.video_slots import scan_video_slots
            slots = scan_video_slots(assets_dir,
                                     roots=_hook("video_slot_dirs"),
                                     exts=_hook("video_slot_exts"),
                                     probe=False)
        else:
            from .core.image_slots import scan_image_slots
            slots = scan_image_slots(assets_dir,
                                     roots=_hook("image_slot_dirs"),
                                     exts=_hook("image_slot_exts"),
                                     probe=False)
        slots_by_rel = {s.rel_path: s for s in slots}
        assignments = staged_changes.live_assignments(saved.get(kind),
                                                      slots_by_rel)
        if not assignments:
            return None

        if kind == "audio":
            keep_map = saved.get("audio_keep") or {}
            keep_full = frozenset(r for r in assignments if keep_map.get(r))
            trim = bool(saved.get("audio_trim",
                                  self.window.audio_trim_var.get()))
            return (slots_by_rel, assignments, trim, keep_full)
        if kind == "video":
            # Probe only the assigned slots — the tab's background pass probes
            # the whole folder, far too slow to repeat here per build.
            from .core.video import backend_for, detect_video_info
            for rel in assignments:
                s = slots_by_rel[rel]
                if s.info is None and backend_for(s.abs_path) is None:
                    try:
                        s.info = detect_video_info(s.abs_path)
                    except Exception:
                        s.info = None
                    s.probed = True
            return (slots_by_rel, assignments,
                    bool(saved.get("video_trim",
                                   self.window.video_trim_var.get())),
                    bool(saved.get("video_no_conversion",
                                   self.window.video_no_conversion_var.get())))
        return (slots_by_rel, assignments)

    def _stage_pending_audio(self, assets_dir):
        """Convert + write the user's assigned replacement tracks over the
        matching files in *assets_dir* (so the Write pipeline that follows
        repacks them).  Runs on the write worker thread; logs via the queue.

        Returns ``(pending, staged, failures)`` — *pending* is how many
        replacements were assigned for this folder, *staged* how many landed on
        disk, *failures* a list of ``(label, error)``.  ``(0, 0, [])`` when
        nothing is assigned for this folder."""
        pend = (self.window.pending_audio_assignments(assets_dir)
                or self._sidecar_pending(assets_dir, "audio"))
        if not pend:
            return (0, 0, [])
        slots_by_rel, assignments, trim, keep_full = pend
        from .core.audio_slots import stage_replacements
        log_cb = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        self.msg_queue.put(LogMsg(
            f"Applying {len(assignments)} audio replacement(s) before "
            f"repack...", "info"))
        try:
            staged, failures = stage_replacements(
                slots_by_rel, assignments, trim_to_length=trim, log_cb=log_cb,
                assets_dir=assets_dir, keep_full_rels=keep_full)
            self.msg_queue.put(LogMsg(
                f"Applied {staged} audio replacement(s)."
                + (f"  {len(failures)} could not be converted (see above)."
                   if failures else ""),
                "success" if not failures else "error"))
            return (len(assignments), staged,
                    [(f"audio: {rel}", err) for rel, err in failures])
        except Exception as e:
            self.msg_queue.put(LogMsg(
                f"Audio replacement failed: {e}", "error"))
            return (len(assignments), 0, [("audio replacements", str(e))])

    def _stage_pending_video(self, assets_dir):
        """Re-encode + write the user's assigned replacement clips over the
        matching files in *assets_dir* (so the Write pipeline that follows
        repacks them).  Runs on the write worker thread; logs via the queue.
        Returns ``(pending, staged, failures)`` — see _stage_pending_audio."""
        pend = (self.window.pending_video_assignments(assets_dir)
                or self._sidecar_pending(assets_dir, "video"))
        if not pend:
            return (0, 0, [])
        slots_by_rel, assignments, trim, no_conversion = pend
        from .core.video_slots import stage_replacements
        log_cb = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        self.msg_queue.put(LogMsg(
            f"Applying {len(assignments)} video replacement(s) before "
            f"repack...", "info"))
        try:
            staged, failures = stage_replacements(
                slots_by_rel, assignments, trim_to_length=trim,
                no_conversion=no_conversion, log_cb=log_cb,
                assets_dir=assets_dir)
            self.msg_queue.put(LogMsg(
                f"Applied {staged} video replacement(s)."
                + (f"  {len(failures)} could not be converted (see above)."
                   if failures else ""),
                "success" if not failures else "error"))
            return (len(assignments), staged,
                    [(f"video: {rel}", err) for rel, err in failures])
        except Exception as e:
            self.msg_queue.put(LogMsg(
                f"Video replacement failed: {e}", "error"))
            return (len(assignments), 0, [("video replacements", str(e))])

    def _stage_pending_image(self, assets_dir):
        """Scale + write the user's assigned replacement images over the
        matching files in *assets_dir* (so the Write pipeline that follows
        repacks them).  Runs on the write worker thread; logs via the queue.
        Returns ``(pending, staged, failures)`` — see _stage_pending_audio."""
        pend = (self.window.pending_image_assignments(assets_dir)
                or self._sidecar_pending(assets_dir, "image"))
        if not pend:
            return (0, 0, [])
        slots_by_rel, assignments = pend
        from .core.image_slots import stage_replacements
        log_cb = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        self.msg_queue.put(LogMsg(
            f"Applying {len(assignments)} image replacement(s) before "
            f"repack...", "info"))
        try:
            staged, failures = stage_replacements(
                slots_by_rel, assignments, log_cb=log_cb, assets_dir=assets_dir)
            self.msg_queue.put(LogMsg(
                f"Applied {staged} image replacement(s)."
                + (f"  {len(failures)} could not be converted (see above)."
                   if failures else ""),
                "success" if not failures else "error"))
            return (len(assignments), staged,
                    [(f"image: {rel}", err) for rel, err in failures])
        except Exception as e:
            self.msg_queue.put(LogMsg(
                f"Image replacement failed: {e}", "error"))
            return (len(assignments), 0, [("image replacements", str(e))])

    # ------------------------------------------------------------------
    # Revert all changes
    # ------------------------------------------------------------------

    def _start_revert_all(self, assets_dir):
        """Revert every staged edit in *assets_dir* back to the extracted
        originals.  The fast path is instant (restore from the per-edit ``.orig``
        snapshots); any edit made before snapshots existed is re-derived from the
        source card by a per-plugin fallback pipeline."""
        from .core import staged_changes, staged_originals, text_manifest

        if not assets_dir or not os.path.isdir(assets_dir):
            messagebox.showwarning(
                "No assets folder",
                "Pick your modified assets folder first.")
            return
        if not os.path.isfile(os.path.join(assets_dir, ".checksums.md5")):
            messagebox.showwarning(
                "Not an Extract folder",
                "This folder has no .checksums.md5 baseline, so there's nothing "
                "to compare against. Point at the folder Extract produced.")
            return
        # Spell out exactly what's about to happen (which files, and what's NOT
        # touched) — "revert all" was too vague about its scope.
        sc = staged_changes.load(assets_dir)
        n_assign = sum(len(sc.get(k) or {})
                       for k in ("audio", "video", "image"))
        n_text = text_manifest.count_changed(assets_dir)
        bullets = []
        cleared = []
        if n_assign:
            cleared.append("%d staged replacement(s)" % n_assign)
        if n_text:
            cleared.append("%d text edit(s)" % n_text)
        if cleared:
            bullets.append("  •  clears " + " and ".join(cleared))
        bullets.append("  •  restores every modified file to the original "
                       "version from your Extract")
        bullets.append("  •  leaves your Extract baseline and the source card "
                       "untouched")
        if not messagebox.askyesno(
                "Revert all changes",
                "Revert all changes in:\n\n  %s\n\nThis:\n%s\n\nIt can't be "
                "undone." % (assets_dir, "\n".join(bullets))):
            return

        # Say so in the log right away — the first worker line ("Checking for
        # edits made before snapshots existed…") read like scan noise, and
        # monkeybug concluded the button did nothing (batch 10).
        self.msg_queue.put(LogMsg(
            "Reverting all changes in %s…" % assets_dir, "info"))
        self.window.begin_revert_view()

        # 1) Clear the in-memory + on-disk assignment state and text edits.
        self.window.clear_replace_assignments(assets_dir)
        try:
            text_manifest.revert_all(assets_dir)
        except Exception:
            pass
        # 2) Instant snapshot restores (the common, going-forward case).
        try:
            instant = len(staged_originals.revert_all(assets_dir))
        except Exception:
            instant = 0

        self._active_mode = "write"
        self._revert_active = True
        self._cancel_requested = False
        self.window.set_running(True, mode="write")
        self.window.reset_steps(mode="write")
        self.window.set_status("Reverting…")
        threading.Thread(
            target=self._run_revert, args=(assets_dir, instant),
            daemon=True).start()

    def _run_revert(self, assets_dir, instant_count):
        """Worker: find edits with no snapshot (legacy / hand-edited) and, if a
        source card + a plugin fallback are available, re-derive them; otherwise
        report them as needing a re-extract.  Posts a DoneMsg either way."""
        from .core.checksums import all_changed

        log = lambda t, l="info": self.msg_queue.put(LogMsg(t, l))
        prog = lambda c, t, d="": self.msg_queue.put(ProgressMsg(c, t, d))
        try:
            log("Checking for edits made before snapshots existed…", "info")
            remaining = sorted(all_changed(
                assets_dir,
                progress=lambda c, t: prog(c, t, "Checking files…"),
                cancel=lambda: self._cancel_requested,
                quick=True))
        except Exception as e:
            log("Change scan failed (%s); restored snapshots only." % e,
                "warning")
            remaining = []
        if self._cancel_requested:
            self.msg_queue.put(DoneMsg(False, "Revert cancelled."))
            return
        if not remaining:
            self.msg_queue.put(DoneMsg(
                True, "Reverted %d change(s) to the extracted originals."
                % instant_count))
            return

        mfr = self._current_mfr
        make = getattr(mfr, "make_revert_pipeline", None)
        source, is_device, override = self._revert_source()
        if make is None or not source:
            log("%d file(s) were changed before per-edit backups existed and "
                "need the source card (or a re-extract) to reset." % len(remaining),
                "warning")
            self.msg_queue.put(DoneMsg(
                True,
                "Reverted %d change(s). %d file(s) predate the per-edit backups "
                "— re-extract the card to reset those." % (instant_count,
                                                           len(remaining))))
            return

        log("Restoring %d file(s) from the source card…" % len(remaining),
            "info")
        log_cb, _phase_cb, progress_cb, done_cb = self._make_callbacks()
        self.pipeline = make(
            source, assets_dir, remaining,
            log_cb, lambda _i: None, progress_cb, done_cb,
            is_device=is_device, partition_override=override)
        self.pipeline.run()   # posts the final DoneMsg via done_cb

    def _revert_source(self):
        """``(source, is_device, partition_override)`` for the revert fallback,
        read from the Write tab's current source selection — the original image
        in Build mode, or the physical card in Direct-SD mode."""
        w = self.window
        if (self._current_mfr is not None
                and self._current_mfr.capabilities.direct_ssd
                and getattr(w, "write_input_source_var", None) is not None
                and w.write_input_source_var.get() == "ssd"):
            dev = (w.write_drive_var.get() or "").strip()
            raw = (w.write_partition_override_var.get() or "").strip()
            override = int(raw) if raw.isdigit() else None
            return (dev, True, override) if dev else ("", True, None)
        src = (w.write_upd_var.get() or "").strip()
        return (src if os.path.isfile(src) else "", False, None)

    # ------------------------------------------------------------------
    # Cancel / Done
    # ------------------------------------------------------------------

    def _cancel(self):
        if self._cancel_requested:
            return                       # one press is enough
        self._cancel_requested = True
        self.window.append_log("Cancelling...", "error")
        # Disable the Cancel button + show feedback so the user knows the press
        # registered and doesn't have to keep mashing it; the action button is
        # re-enabled only when the (whole) job actually stops, via set_running.
        self.window.set_cancelling()
        if self.pipeline:
            self.pipeline.cancel()

    def _on_done(self, success, summary):
        # Revert runs reuse the write run-state but have their own messaging +
        # a post-run rescan (on-disk asset bytes changed under the tabs).
        if getattr(self, "_revert_active", False):
            self._revert_active = False
            self.window.set_running(False, mode="write")
            if self._cancel_requested:
                self._cancel_requested = False
                self.window.set_status("Cancelled")
                self.window.append_log("Revert cancelled.", "info")
            elif success:
                self.window.set_status("Reverted")
                self.window.append_log(summary, "success")
                messagebox.showinfo("Revert Complete", summary)
            else:
                self.window.set_status("Failed")
                messagebox.showerror("Revert Failed", summary)
            self.window.refresh_after_revert()
            return

        is_extract = self._active_mode == "extract"
        # Snapshot the run's wall-clock now — set_running(False) below clears
        # the window's timer state.  Covers the whole chain (extract +
        # auto-name follow-ups) because chained jobs never restart the clock.
        run_elapsed = None
        if self.window._start_time is not None:
            run_elapsed = time.time() - self.window._start_time
        # On success, advance the phase indicator past the last phase
        # so every step shows green instead of leaving the final
        # phase stuck on "active" (blue) forever.  set_phase walks
        # labels and marks any with index < target as green; passing
        # len(phases) makes the comparison true for every label.
        if success and self._current_mfr is not None:
            phases = (self._current_mfr.extract_phases if is_extract
                      else self._current_mfr.write_phases)
            if phases:
                self.window.set_phase(len(phases), mode=self._active_mode)
        # Empirical FDA proof: if a Direct-SSD run just completed
        # successfully on macOS, Full Disk Access must be in order
        # for every helper involved.  Auto-dismiss the banner so the
        # warning matches reality going forward.  We do this on the
        # FIRST success; idempotent on subsequent runs.
        import sys as _sys
        if (success and self._current_run_is_direct_ssd
                and _sys.platform == "darwin"):
            self.window.acknowledge_macos_fda()
        self._current_run_is_direct_ssd = False
        # Stamp the output folder with the source image's identity so the
        # Replace/Write tabs can warn if that image is later swapped/reverted
        # on disk while these assets are still being edited.  File inputs only;
        # write_extract_source no-ops on device paths.
        if is_extract and success and self._last_extract_io:
            in_path, out_path = self._last_extract_io
            write_extract_source(out_path, in_path)
            # The assets folder was pointed at this output dir at extract START
            # (before it held any files), so any Replace-tab scan triggered in
            # the meantime stamped a stale/empty cache for this exact path.
            # Clear the stamps so the next tab visit re-scans the now-populated
            # folder instead of trusting the path-keyed short-circuit.
            self.window.invalidate_asset_scans()
        self._last_extract_io = None
        self.window.set_running(False, mode=self._active_mode)
        if self._cancel_requested:
            # User cancelled — don't dress it up as a failure with a scary
            # error modal; just note it and reset.
            self._cancel_requested = False
            self.window.set_status("Cancelled")
            self.window.append_log("Cancelled.", "info")
        elif success:
            self.window.set_status("Complete!")
            if is_extract:
                # No modal for extraction — the per-asset progress already
                # scrolls by in the log, so a blocking popup just gets in the
                # way of dismissing it.  Drop the summary into the log instead,
                # closed out by an unambiguous "fully done" line (monkeybug).
                self.window.append_log(summary, "success")
                if run_elapsed is not None:
                    h, rem = divmod(int(run_elapsed), 3600)
                    m, s = divmod(rem, 60)
                    self.window.append_log(
                        f"Extract completed. Total time: "
                        f"{h:02d}:{m:02d}:{s:02d}.", "success")
            else:
                fails = self._staging_failures
                if fails:
                    # The build succeeded but some assigned replacements
                    # couldn't be applied — surface them so the user knows
                    # those slots still play their original asset (instead of
                    # quietly shipping a partially-unmodified image).
                    detail = "\n".join(f"  • {rel}: {err}"
                                       for rel, err in fails[:20])
                    if len(fails) > 20:
                        detail += f"\n  • ... and {len(fails) - 20} more"
                    messagebox.showwarning(
                        "Update built — some replacements were skipped",
                        f"{summary}\n\n"
                        f"⚠ {len(fails)} assigned replacement(s) could NOT be "
                        f"applied and were left unchanged (those slots will "
                        f"play/show their original asset):\n\n{detail}\n\n"
                        f"This is usually a missing ffmpeg — install it (the "
                        f"\"Install Missing\" button), then rebuild.")
                else:
                    messagebox.showinfo("Write Complete", summary)
        else:
            self.window.set_status("Failed")
            title = "Extract Failed" if is_extract else "Write Failed"
            messagebox.showerror(title, summary)
        # Clear staging-failure state so it never leaks into a later run.
        self._staging_failures = []

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    def _check_for_update(self):
        """Auto-run update check at startup (silent if up-to-date).

        Result lands as a prominent banner at the top of the window
        (``show_update_banner``) instead of in the per-manufacturer
        log panel — the old per-mfr log placement coupled the update
        notice to whichever manufacturer was selected, and the
        notice would scroll off or disappear when the user switched
        plugins.  The banner persists across picker ↔ working-view
        transitions and is dismissible per-session.

        Stays silent when the user is already on the latest version
        — this is the *background* check; users who want explicit
        confirmation either way click the "Check for updates" button,
        which calls :meth:`_check_for_update_now` instead.
        """
        self._run_update_check(show_up_to_date_toast=False)

    def _check_for_update_now(self):
        """User-triggered "Check for updates" button click.

        Same fetch as the startup auto-check but with two UX
        affordances: the button reads "Checking…" while the request
        is in flight (so the user knows the click was received), and
        when the response says "no newer version", we pop a "you're
        on the latest" modal so the user has feedback either way.
        Also useful for local dev — flipping ``__version__`` to an
        older string lets you exercise the banner code path on
        demand without restarting the app.
        """
        self._run_update_check(show_up_to_date_toast=True)

    def _run_update_check(self, *, show_up_to_date_toast):
        """Shared worker for the auto / manual update checks."""
        mfr_repo = (self._current_mfr.update_repo
                    if self._current_mfr else None)
        if show_up_to_date_toast:
            self.window.set_update_check_running(True)
        # Mirror the check into the log too (David) — the startup check runs
        # while the picker is showing, so these lines are buffered and land
        # in the first manufacturer log that opens.
        self.window.append_log("Checking for updates...", "info")

        def _run():
            try:
                result = check_for_update(__version__, repo=mfr_repo)
                failed = None
            except Exception as e:
                # Keep the real error — v0.41 and earlier reduced every
                # failure to "couldn't reach GitHub", which hid the actual
                # macOS cause (no CA roots -> CERTIFICATE_VERIFY_FAILED)
                # and made field reports undiagnosable.
                result, failed = None, f"{type(e).__name__}: {e}"
            self.root.after(
                0, self._handle_update_check_result,
                result, show_up_to_date_toast, failed)
        threading.Thread(target=_run, daemon=True).start()

    def _handle_update_check_result(self, result, show_up_to_date_toast,
                                    failed=None):
        """Main-thread continuation of the update check."""
        self.window.set_update_check_running(False)
        if result:
            version, url, _notes = result
            self.window.show_update_banner(version, url)
            self.window.append_log(
                f"Update available: v{version} (you're on v{__version__}).",
                "success")
            self.window.append_log_link(f"  Download: {url}", url)
        elif failed:
            # Network/API error — don't claim "up to date" when we couldn't
            # actually check.
            self.window.append_log(
                f"Update check failed — couldn't reach GitHub ({failed}).",
                "error")
            if show_up_to_date_toast:
                messagebox.showwarning(
                    "Update check failed",
                    "Couldn't reach GitHub to check for updates.\n"
                    "Check your internet connection and try again.\n\n"
                    f"Details: {failed}")
        else:
            self.window.append_log(
                f"You're on the latest version (v{__version__}).", "info")
            if show_up_to_date_toast:
                self.window.show_up_to_date_toast()

    # ------------------------------------------------------------------
    # Settings
    # ------------------------------------------------------------------

    def _load_settings_file(self):
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return {}

    def _restore_window_geometry(self):
        """Re-apply the saved window geometry ("WxH+X+Y"), clamped to the
        current screen.  No-op when there's no saved geometry (first launch)."""
        geo = self._settings.get("window_geometry")
        if not isinstance(geo, str):
            return
        m = re.fullmatch(r"\s*(\d+)x(\d+)([+-]\d+)([+-]\d+)\s*", geo)
        if not m:
            return
        w, h, x, y = (int(m.group(1)), int(m.group(2)),
                      int(m.group(3)), int(m.group(4)))
        try:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
        except tk.TclError:
            return
        # Clamp size to the screen, and position so a good chunk of the window
        # (incl. the titlebar) stays on-screen and reachable.
        w = max(720, min(w, sw))
        h = max(700, min(h, sh))
        x = max(-(w - 120), min(x, sw - 120))
        y = max(0, min(y, sh - 120))
        try:
            self.root.geometry("%dx%d+%d+%d" % (w, h, x, y))
        except tk.TclError:
            pass

    def _save_settings(self):
        if self._current_mfr is not None:
            self._save_manufacturer_paths(self._current_mfr.key)
            self._settings["last_manufacturer"] = self._current_mfr.key
        self._settings["theme"] = self.window._current_theme
        # Remember the window size + position for next launch.  Skip odd/tiny
        # geometries (e.g. the 1x1 pre-dialog footprint) so we never persist a
        # window the user can't see.
        try:
            geo = self.root.winfo_geometry()
            gm = re.match(r"(\d+)x(\d+)", geo)
            if gm and int(gm.group(1)) >= 400 and int(gm.group(2)) >= 400:
                self._settings["window_geometry"] = geo
        except tk.TclError:
            pass
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except OSError:
            pass

    def _on_fda_acknowledge(self, acknowledged):
        """Persist the macOS FDA banner dismissal across restarts.

        Called from the window when the user clicks "Hide this
        notice" on the FDA banner, and also when we
        auto-acknowledge after the first successful Direct-SSD run.
        """
        self._settings["macos_fda_acknowledged"] = bool(acknowledged)
        self._save_settings()

    def _on_theme_change(self, _theme):
        self._save_settings()

    def _on_column_widths_change(self, widths):
        """Persist the Replace-tree column widths the user dragged so the layout
        survives a restart (monkeybug).  *widths* is ``{tree_key: {col: px}}``."""
        self._settings["column_widths"] = widths
        self._save_settings()

    def _on_admin_warning_collapsed_change(self, collapsed):
        """Persist whether the admin-warning body is collapsed so a returning
        user who's read it once keeps it minimised (monkeybug)."""
        self._settings["admin_warning_collapsed"] = bool(collapsed)
        self._save_settings()

    def _apply_audio_declick_env(self, enabled):
        """Reflect the "Match audio replacements to the game's callouts" toggle
        into the env var the Stern spike2 encoder reads.  On (default) leaves it
        unset; off sets ``PAD_STERN_AUDIO_RAW=1``.  Spawned encode workers inherit
        os.environ at pool-creation time, so setting it here (the process that
        runs Write) reaches both the serial and the parallel encode paths."""
        if enabled:
            os.environ.pop("PAD_STERN_AUDIO_RAW", None)
        else:
            os.environ["PAD_STERN_AUDIO_RAW"] = "1"

    def _on_audio_declick_change(self, enabled):
        """Persist the match-to-callouts toggle and apply it to the encoder
        env var so the next Write uses it."""
        enabled = bool(enabled)
        self._settings["audio_declick"] = enabled
        self._apply_audio_declick_env(enabled)
        self._save_settings()

    def _on_voice_quality_change(self, model_size):
        """Persist the ⚙-menu voice-recognition quality pick (the
        faster-whisper model Auto-name call-outs transcribes with), and log
        whether that model is already downloaded — a quality bump otherwise
        silently implies a multi-GB download on the next extract (David:
        "log the status of that download when it is selected")."""
        self._settings["voice_quality"] = model_size
        self._save_settings()
        try:
            from .core.transcribe import whisper_model_cached, \
                _MODEL_APPROX_MB
            if whisper_model_cached(model_size):
                self.window.append_log(
                    f"Voice recognition quality set to {model_size} — "
                    f"model already downloaded, ready to use.", "info")
            else:
                approx = _MODEL_APPROX_MB.get(model_size)
                size = f" (~{approx} MB)" if approx else ""
                self.window.append_log(
                    f"Voice recognition quality set to {model_size} — "
                    f"model not downloaded yet{size}; it downloads once, "
                    f"automatically, on the next Auto-name call-outs run.",
                    "info")
        except Exception:
            pass
