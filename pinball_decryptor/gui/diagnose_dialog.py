"""Card-diagnostics dialog — read the installer's log off a flashed card.

A small modal (opened from the Write tab's flash section for manufacturers
that implement ``diagnose_card``, currently CGC) that picks a physical card
from the same ``core.drives`` enumeration the flash dialog uses, runs the
manufacturer's read-only diagnosis on a worker thread, and shows the report
in a scrollable text box with a "Save report…" button.

Everything is read-only; the point is support: after an on-machine install
fails (CGC's "SHELL ERROR"), the installer leaves its copy log on an ext4
partition Windows can't read, and ``wsl --mount`` can't attach most USB SD
readers (removable media).  The manufacturer's ``diagnose_card`` reads it
back through ``core.rawdevice`` instead.
"""

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core.admin import is_admin
from .theme import THEMES, dark_titlebar, platform_font


class DiagnoseCardDialog:
    """Modal running a manufacturer's read-only card diagnosis."""

    def __init__(self, parent, manufacturer, theme_name):
        self._parent = parent
        self._mfr = manufacturer
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._sans, self._mono = platform_font()
        self._drives = []
        self._selected = None
        self._enum_id = 0
        self._running = False
        self._report = None
        # Worker threads must never touch Tk directly (Tcl isn't thread-safe;
        # calling .after() from a worker deadlocks against the main loop).
        # The read worker posts (kind, payload) tuples here and a main-thread
        # timer drains them.
        self._q = queue.Queue()
        self._drain_job = None

        self._build()
        self._refresh_drives()

    # ------------------------------------------------------------------
    def _build(self):
        th = self._theme
        noun = getattr(self._mfr, "direct_medium_noun", "SD card")
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        dlg.title("Card diagnostics")
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        dlg.transient(self._parent)
        dlg.protocol("WM_DELETE_WINDOW", self._close)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(
            body, text="Read the installer's log from a %s" % noun,
            font=(self._sans, 12, "bold")).pack(anchor="w", pady=(0, 2))
        help_text = getattr(
            self._mfr, "diagnose_card_help",
            "Reads diagnostic information off the card. Read-only.")
        ttk.Label(
            body, text=help_text, font=(self._sans, 9),
            foreground=th["gray"], wraplength=640, justify="left").pack(
            anchor="w", pady=(0, 10))

        card_row = ttk.Frame(body)
        card_row.pack(fill="x", pady=4)
        ttk.Label(card_row, text="Card:", width=8, anchor="w").pack(
            side="left")
        self._drive_var = tk.StringVar()
        self._drive_combo = ttk.Combobox(
            card_row, textvariable=self._drive_var, state="readonly")
        self._drive_combo.pack(side="left", fill="x", expand=True)
        self._drive_combo.bind(
            "<<ComboboxSelected>>", lambda _e: self._on_drive_selected())
        ttk.Button(card_row, text="Refresh",
                   command=self._refresh_drives).pack(side="left",
                                                      padx=(4, 0))
        self._read_btn = ttk.Button(card_row, text="Read card",
                                    command=self._start_read)
        self._read_btn.pack(side="left", padx=(8, 0))
        # A card isn't the only thing worth diagnosing: the SAME check runs on
        # a built or source ``.img`` file, which is how you confirm an image
        # has a real payload BEFORE flashing (no Administrator needed to read a
        # plain file).  The dropdown only lists physical drives, so without
        # this there's no way to point diagnostics at a file on disk.
        self._file_btn = ttk.Button(card_row, text="Image file…",
                                    command=self._start_read_file)
        self._file_btn.pack(side="left", padx=(4, 0))

        if not is_admin():
            tk.Label(
                body,
                text=("⚠ Reading a physical card needs Administrator (close "
                      "the app, right-click the shortcut, choose \"Run as "
                      "administrator\", and reopen). Diagnosing an image "
                      "file with \"Image file…\" does not need Administrator."),
                bg=th["bg"], fg=th["error"], font=(self._sans, 9),
                wraplength=640, justify="left", anchor="w").pack(
                fill="x", pady=(2, 0))

        text_frame = ttk.Frame(body)
        text_frame.pack(fill="both", expand=True, pady=(10, 0))
        self._text = tk.Text(
            text_frame, height=24, width=92, wrap="none",
            font=(self._mono, 9), bg=th["field_bg"], fg=th["fg"],
            state="disabled")
        yscroll = ttk.Scrollbar(text_frame, orient="vertical",
                                command=self._text.yview)
        xscroll = ttk.Scrollbar(text_frame, orient="horizontal",
                                command=self._text.xview)
        self._text.configure(yscrollcommand=yscroll.set,
                             xscrollcommand=xscroll.set)
        self._text.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        text_frame.rowconfigure(0, weight=1)
        text_frame.columnconfigure(0, weight=1)

        btn_row = ttk.Frame(body)
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="Close", command=self._close).pack(
            side="right")
        self._save_btn = ttk.Button(btn_row, text="Save report…",
                                    command=self._save_report,
                                    state="disabled")
        self._save_btn.pack(side="right", padx=(0, 8))

        self._center()
        dlg.bind("<Escape>", lambda _e: self._close())
        dlg.deiconify()
        dlg.lift()
        dlg.update_idletasks()
        try:
            dlg.grab_set()
        except tk.TclError:
            dlg.update()
            dlg.grab_set()

    def _center(self):
        dlg = self._dlg
        self._parent.update_idletasks()
        dlg.update_idletasks()
        dw = max(dlg.winfo_reqwidth(), 700)
        dh = dlg.winfo_reqheight()
        pw = self._parent.winfo_width()
        ph = self._parent.winfo_height()
        if pw <= 1 or ph <= 1:
            sw = self._parent.winfo_screenwidth()
            sh = self._parent.winfo_screenheight()
            x, y = (sw - dw) // 2, (sh - dh) // 2
        else:
            x = self._parent.winfo_rootx() + (pw - dw) // 2
            y = self._parent.winfo_rooty() + (ph - dh) // 2
        dlg.geometry("%dx%d+%d+%d" % (dw, dh, max(0, x), max(0, y)))

    # ------------------------------------------------------------------
    # Drive enumeration (same worker-thread pattern as FlashImageDialog).
    def _refresh_drives(self):
        self._enum_id += 1
        my_id = self._enum_id
        self._drive_combo["values"] = ["Detecting drives…"]
        self._drive_var.set("Detecting drives…")
        prefer = getattr(self._mfr, "direct_target_kind", "sd_card")

        def _worker():
            try:
                from ..core.drives import (list_physical_drives,
                                           pick_best_game_ssd)
                drives = list_physical_drives()
                pick = pick_best_game_ssd(drives, prefer=prefer)
            except Exception:
                drives, pick = [], (None, None, None)
            try:
                self._dlg.after(0, self._apply_drives, my_id, drives, pick)
            except (RuntimeError, tk.TclError):
                pass

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_drives(self, my_id, drives, pick):
        if my_id != self._enum_id:
            return
        from ..core.drives import visible_drives
        prefer = getattr(self._mfr, "direct_target_kind", "sd_card")
        best = pick[0] if pick else None
        drives = visible_drives(drives, prefer=prefer,
                                keep=[best] if best else ())
        self._drives = drives
        if not drives:
            self._drive_combo["values"] = ["(no drives found — click Refresh)"]
            self._drive_var.set(self._drive_combo["values"][0])
            self._selected = None
            return
        self._drive_combo["values"] = [d.display for d in drives]
        chosen = best if (best and best in drives) else drives[0]
        self._drive_var.set(chosen.display)
        self._selected = chosen

    def _on_drive_selected(self):
        idx = self._drive_combo.current()
        self._selected = (self._drives[idx]
                          if 0 <= idx < len(self._drives) else None)

    # ------------------------------------------------------------------
    def _append(self, msg):
        try:
            self._text.configure(state="normal")
            self._text.insert("end", msg + "\n")
            self._text.see("end")
            self._text.configure(state="disabled")
        except tk.TclError:
            pass

    def _start_read(self):
        if self._running:
            return
        card = self._selected
        if card is None:
            messagebox.showwarning(
                "No card selected",
                "Pick a card from the dropdown. If it's empty, connect the "
                "card and click Refresh.", parent=self._dlg)
            return
        if not is_admin():
            messagebox.showerror(
                "Administrator required",
                "Reading raw disk sectors needs Administrator. Re-launch the "
                "app as administrator and try again.\n\nTo diagnose an image "
                "*file* instead (no Administrator needed), use \"Image "
                "file…\".", parent=self._dlg)
            return
        self._launch(card.device_path)

    def _start_read_file(self):
        """Diagnose a built or source ``.img`` file (no Administrator; the
        dropdown only offers physical drives)."""
        if self._running:
            return
        path = filedialog.askopenfilename(
            parent=self._dlg, title="Select an installer image to diagnose",
            filetypes=[("Installer image", "*.img *.raw *.bin"),
                       ("All files", "*.*")])
        if not path:
            return
        self._launch(path)

    def _launch(self, target):
        """Shared: run the manufacturer's read-only diagnosis on *target* (a
        physical device path or an image file path) on a worker thread."""
        self._running = True
        self._report = None
        self._read_btn.configure(state="disabled")
        self._file_btn.configure(state="disabled")
        self._save_btn.configure(state="disabled")
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")

        def _worker():
            # Runs off the main thread: push everything through the queue,
            # never call Tk here.
            try:
                report = self._mfr.diagnose_card(
                    target,
                    log=lambda m: self._q.put(("log", m)))
                self._q.put(("done", report))
            except Exception as e:  # noqa: BLE001 - surfaced in the report box
                self._q.put(("error", str(e)))

        threading.Thread(target=_worker, daemon=True).start()
        self._schedule_drain()

    def _schedule_drain(self):
        try:
            self._drain_job = self._dlg.after(60, self._drain_queue)
        except tk.TclError:
            self._drain_job = None

    def _drain_queue(self):
        """Main-thread: apply queued worker messages to the UI."""
        self._drain_job = None
        try:
            while True:
                kind, payload = self._q.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "done":
                    self._finish_read(payload, None)
                    return
                elif kind == "error":
                    self._finish_read(None, payload)
                    return
        except queue.Empty:
            pass
        if self._running:
            self._schedule_drain()

    def _finish_read(self, report, error):
        self._running = False
        try:
            self._read_btn.configure(state="normal")
            self._file_btn.configure(state="normal")
        except tk.TclError:
            return
        if error is not None:
            self._append("")
            self._append("FAILED: %s" % error)
            return
        self._report = report
        self._append("")
        self._append(report)
        self._save_btn.configure(state="normal")

    def _save_report(self):
        if not self._report:
            return
        path = filedialog.asksaveasfilename(
            parent=self._dlg, title="Save diagnostics report",
            defaultextension=".txt",
            initialfile="card_diagnostics.txt",
            filetypes=[("Text file", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self._report + "\n")
        except OSError as e:
            messagebox.showerror("Save failed", str(e), parent=self._dlg)
            return
        messagebox.showinfo(
            "Saved", "Report saved to:\n%s" % path, parent=self._dlg)

    def _close(self):
        if self._drain_job is not None:
            try:
                self._dlg.after_cancel(self._drain_job)
            except tk.TclError:
                pass
            self._drain_job = None
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()
