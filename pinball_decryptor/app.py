"""Application controller — wires the GUI to manufacturer plugins."""

import json
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from . import __version__
from .core import modpack
from .core.config import APP_NAME, SETTINGS_FILE
from .core.messages import (DoneMsg, LinkMsg, LogMsg, PhaseMsg, PrereqMsg,
                            ProgressMsg)
from .core.prereqs import check_prerequisite
from .core.registry import all_manufacturers, get_manufacturer, load_plugins
from .core.updater import check_for_update
from .gui.main_window import MainWindow


class App:
    def __init__(self):
        load_plugins()
        self._manufacturers = all_manufacturers()
        if not self._manufacturers:
            raise RuntimeError(
                "No manufacturer plugins registered.  Check the install.")

        self.root = tk.Tk()
        self.msg_queue = queue.Queue()
        self.pipeline = None
        self._active_mode = "extract"
        self._current_mfr = None

        self._settings = self._load_settings_file()
        saved_theme = self._settings.get("theme")

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
            on_recheck_prereqs=self._recheck_prereqs,
            on_install_prereqs=self._launch_install_prereqs,
            on_back=self._on_back_to_picker,
            on_export=self._start_export,
            on_import=self._start_import,
            on_theme_change=self._on_theme_change,
            initial_theme=saved_theme,
            on_check_updates=self._check_for_update_now,
        )

        # Start at the manufacturer picker.  Even if the user has a
        # last_manufacturer saved, the explicit pick step makes "which
        # mfr am I about to work on" unambiguous and prevents the
        # accidental mid-session mfr switch class of bug.
        self.window.show_picker()

        self._poll_queue()

        self.root.title(f"{APP_NAME} v{__version__}")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.root.after(1500, self._check_for_update)

    def run(self):
        self.root.mainloop()

    def _on_close(self):
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
        """Run every prereq probe in a worker thread; post each result
        through the queue so the GUI updates incrementally.  Also log
        a 'checking...' line + a final summary so the empty log pane
        on app start has SOMETHING useful in it."""
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
        section = self._manufacturers_section().get(key, {})
        self.window.extract_input_var.set(section.get("extract_input", ""))
        self.window.extract_output_var.set(section.get("extract_output", ""))
        self.window.write_upd_var.set(section.get("write_original", ""))
        self.window.write_assets_var.set(section.get("write_assets", ""))
        self.window.write_output_var.set(section.get("write_output", ""))

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

        if os.path.isdir(output_path) and os.listdir(output_path):
            if not messagebox.askyesno(
                "Output Folder Not Empty",
                "The output folder already contains files.\n\n"
                "Extracting will overwrite existing files.\n\nContinue?",
            ):
                return

        self._save_settings()

        # If we have a .upd input and the manufacturer supports Write, mirror
        # the chosen paths into the Write tab so the user doesn't re-pick.
        ext = os.path.splitext(in_path)[1].lower()
        if ext in (".upd",) and self._current_mfr.capabilities.write:
            self.window.write_upd_var.set(in_path)
            self.window.write_assets_var.set(output_path)

        self._active_mode = "extract"
        self.window.set_running(True, mode="extract")
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
            chained_done_cb = self._maybe_wrap_done_for_transcribe(
                done_cb, output_path)
            self.pipeline = self._current_mfr.make_extract_pipeline(
                in_path, output_path,
                log_cb, phase_cb, progress_cb, chained_done_cb,
            )
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
            if not success:
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
        if os.path.isdir(output_path) and os.listdir(output_path):
            if not messagebox.askyesno(
                "Output Folder Not Empty",
                "The output folder already contains files.\n\n"
                "Extracting will overwrite existing files.\n\nContinue?",
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

        self._save_settings()

        self._active_mode = "extract"
        self.window.set_running(True, mode="extract")
        self.window.reset_steps(mode="extract")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        self.pipeline = self._current_mfr.make_direct_ssd_extract_pipeline(
            device_path, output_path,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override,
        )
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _start_write(self):
        if not self._current_mfr.capabilities.write:
            return

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

        # Resolve the output filename: same as original, in the chosen folder.
        # Allow the user to point output at an explicit filename too.
        original_name = os.path.basename(original)
        primary_ext = (self._current_mfr.input_spec.extensions[0].lower()
                       if self._current_mfr.input_spec.extensions else "")
        if primary_ext and output_dir.lower().endswith(primary_ext):
            output_path = output_dir
        else:
            output_path = os.path.join(output_dir, original_name)

        if os.path.abspath(output_path) == os.path.abspath(original):
            messagebox.showerror("Same File",
                "Output path would overwrite the original file.\n\n"
                "Choose a different output folder.")
            return

        self._save_settings()

        self._active_mode = "write"
        self.window.set_running(True, mode="write")
        self.window.reset_steps(mode="write")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()

        self.pipeline = self._current_mfr.make_write_pipeline(
            original, assets_dir, output_path,
            log_cb, phase_cb, progress_cb, done_cb,
        )
        threading.Thread(target=self.pipeline.run, daemon=True).start()

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

        self._save_settings()

        self._active_mode = "write"
        self.window.set_running(True, mode="write")
        self.window.reset_steps(mode="write")

        log_cb, phase_cb, progress_cb, done_cb = self._make_callbacks()
        self.pipeline = self._current_mfr.make_direct_ssd_write_pipeline(
            device_path, assets_dir,
            log_cb, phase_cb, progress_cb, done_cb,
            partition_override=partition_override,
        )
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

        log_cb, _phase_cb, progress_cb, done_cb = self._make_callbacks()
        # Don't drive the Extract phase indicator -- transcribe phases
        # don't line up with Extract's "Detect / Outer / Inner /
        # Checksums" labels; would just be visual noise.
        phase_cb = lambda _i: None

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

        rename_after = bool(
            getattr(self.window, "transcribe_rename_var", None)
            and self.window.transcribe_rename_var.get())

        self.pipeline = self._current_mfr.make_transcribe_pipeline(
            assets_dir, log_cb, phase_cb, progress_cb, done_cb,
            rename_after=rename_after)
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

    # ------------------------------------------------------------------
    # Cancel / Done
    # ------------------------------------------------------------------

    def _cancel(self):
        if self.pipeline:
            self.window.append_log("Cancelling...", "error")
            self.pipeline.cancel()

    def _on_done(self, success, summary):
        is_extract = self._active_mode == "extract"
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
        self.window.set_running(False, mode=self._active_mode)
        if success:
            self.window.set_status("Complete!")
            title = "Extract Complete" if is_extract else "Write Complete"
            messagebox.showinfo(title, summary)
        else:
            self.window.set_status("Failed")
            title = "Extract Failed" if is_extract else "Write Failed"
            messagebox.showerror(title, summary)

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

        def _run():
            try:
                result = check_for_update(__version__, repo=mfr_repo)
            except Exception:
                result = None
            self.root.after(
                0, self._handle_update_check_result,
                result, show_up_to_date_toast)
        threading.Thread(target=_run, daemon=True).start()

    def _handle_update_check_result(self, result, show_up_to_date_toast):
        """Main-thread continuation of the update check."""
        self.window.set_update_check_running(False)
        if result:
            version, url, _notes = result
            self.window.show_update_banner(version, url)
        elif show_up_to_date_toast:
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

    def _save_settings(self):
        if self._current_mfr is not None:
            self._save_manufacturer_paths(self._current_mfr.key)
            self._settings["last_manufacturer"] = self._current_mfr.key
        self._settings["theme"] = self.window._current_theme
        try:
            os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except OSError:
            pass

    def _on_theme_change(self, _theme):
        self._save_settings()
