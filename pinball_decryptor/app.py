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

        if sys.platform != "win32":
            messagebox.showinfo(
                "Install Prerequisites",
                "The bundled installer script is Windows-only.\n\n"
                "On macOS, Spooky/JJP Clonezilla flows use Docker Desktop "
                "(install from https://www.docker.com/products/docker-desktop/) "
                "and gpg/ffmpeg from Homebrew (`brew install gnupg ffmpeg`).\n\n"
                "On Linux, install partclone, e2fsprogs, xorriso, pigz, gpg, "
                "ffmpeg, zstd, and python3-zstandard via your package "
                "manager.")
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

        self.pipeline = self._current_mfr.make_extract_pipeline(
            in_path, output_path,
            log_cb, phase_cb, progress_cb, done_cb,
        )
        threading.Thread(target=self.pipeline.run, daemon=True).start()

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def _start_write(self):
        if not self._current_mfr.capabilities.write:
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
        mfr_repo = (self._current_mfr.update_repo
                    if self._current_mfr else None)

        def _run():
            result = check_for_update(__version__, repo=mfr_repo)
            if result:
                version, url, notes = result
                self.msg_queue.put(LogMsg(f"Update available: v{version}", "info"))
                if notes:
                    for line in notes.splitlines():
                        line = line.strip()
                        if line:
                            self.msg_queue.put(LogMsg(f"  {line}", "info"))
                self.msg_queue.put(LinkMsg(f"Download v{version}", url))
        threading.Thread(target=_run, daemon=True).start()

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
