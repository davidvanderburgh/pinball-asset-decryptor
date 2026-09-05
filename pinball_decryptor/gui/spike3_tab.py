"""The 'Spike 3' tab - get the OTP key off a Stern Spike 3 board, then verify
it, without anyone touching a command line.

Spike 3 stores its assets on LUKS2 volumes whose key is fused into the board's
customer OTP and is in NO file on the SD card.  The decrypt is fully worked out
and runs on a PC; the one missing input is a single read of that key off a real
machine.  This tab makes that read a two-step, drag-and-drop job:

* PREPARE turns a card image (or a bare ``boot.img``) into a patched
  ``boot.img`` + ``boot.sig`` that, at boot, writes the key to ``OTP_KEY.TXT``
  on the FAT boot partition.  The owner backs up two files, drops these two in,
  boots once, and copies ``OTP_KEY.TXT`` back.  Nothing large moves, and if the
  board enforces secure boot it simply will not boot (harmless - restore the
  backup), which is itself the answer to whether secure boot is on.
* READ takes whatever the owner brings back - ``OTP_KEY.TXT``, the boot folder,
  a pasted key, or a whole card image - and shows the 64-hex key.
* VERIFY tries that key against the LUKS2 headers in a card image (or a single
  header file) and says which volumes it opens - the global-vs-per-device test.

This is only a control surface.  Every byte of crypto and boot-image patching
lives in ``stern-spike-3/tools`` (``build_extractor_card.py``, ``luks_otp.py``)
and is reached through :mod:`..core.spike3`, which builds those tools' command
lines and reads their output back.  The tab reimplements none of it.

Unlike the Emulate / Multi-boot tabs, nothing here needs WSL: the Spike 3 tools
are pure host Python, so this tab runs the same on every platform.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..core import spike3


class Spike3Panel:
    """The whole tab.  Built by ``MainWindow._build_spike3_tab``, which hands
    it the app's log sink, theme accessor and status line."""

    def __init__(self, parent, log=None, theme_fn=None, status_fn=None,
                 resize_fn=None):
        self._parent = parent
        self._frame = None
        self._log_sink = log or (lambda msg: None)
        self._theme_fn = theme_fn or (lambda: "dark")
        self._status_fn = status_fn or (lambda msg: None)
        self._resize_fn = resize_fn or (lambda: None)
        self._busy = False
        self._prepared_dir = None       # set once PREPARE succeeds

        # Form state.
        self.src_var = tk.StringVar()
        self.sig_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.read_var = tk.StringVar()
        self.key_var = tk.StringVar()
        self.header_var = tk.StringVar()

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------
    def build(self, frame):
        self._frame = frame
        pad = dict(padx=10, pady=4)

        intro = ttk.Label(
            frame, justify="left", font=("Segoe UI", 9),
            text="Spike 3 keeps its assets encrypted with a key fused into the "
                 "board - it is in no file on the card.\nPrepare a card here, "
                 "have the machine's owner boot it once, then bring the result "
                 "back to read and verify the key.")
        intro.pack(anchor="w", **pad)

        # --- Step 1: prepare -----------------------------------------
        s1 = ttk.LabelFrame(frame, text=" Step 1 - Prepare the extractor card ")
        s1.pack(fill=tk.X, **pad)
        self._file_row(s1, "Card image or boot.img:", self.src_var,
                       self._browse_source)
        self._file_row(s1, "Boot signature (optional):", self.sig_var,
                       self._browse_sig,
                       hint="only if the source is a bare boot.img")
        self._file_row(s1, "Save the two files to:", self.out_var,
                       self._browse_outdir, folder=True)

        b1 = ttk.Frame(s1)
        b1.pack(fill=tk.X, padx=8, pady=(4, 8))
        self.prepare_btn = ttk.Button(b1, text="Prepare extractor files",
                                      command=self._on_prepare)
        self.prepare_btn.pack(side=tk.LEFT)
        self.copy_btn = ttk.Button(b1, text="Copy onto boot partition…",
                                   command=self._on_copy_to_card,
                                   state="disabled")
        self.copy_btn.pack(side=tk.LEFT, padx=(8, 0))

        self.instructions = self._text(s1, height=9)
        self.instructions.pack(fill=tk.X, padx=8, pady=(0, 8))
        self._set_text(self.instructions, _PREP_HELP)

        # --- Step 2: read + verify -----------------------------------
        s2 = ttk.LabelFrame(frame, text=" Step 2 - Read the answer back ")
        s2.pack(fill=tk.X, **pad)

        self._file_row(s2, "OTP_KEY.TXT, folder, image, or paste a key:",
                       self.read_var, self._browse_readback,
                       folder_too=self._browse_readfolder)
        rb = ttk.Frame(s2)
        rb.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(rb, text="Read key", command=self._on_read).pack(
            side=tk.LEFT)

        kr = ttk.Frame(s2)
        kr.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Label(kr, text="Recovered key:", width=22).pack(side=tk.LEFT)
        key_entry = ttk.Entry(kr, textvariable=self.key_var,
                              state="readonly")
        key_entry.pack(side=tk.LEFT, fill=tk.X, expand=True)

        self._file_row(s2, "Verify against (card image or header):",
                       self.header_var, self._browse_header)
        vb = ttk.Frame(s2)
        vb.pack(fill=tk.X, padx=8, pady=(0, 6))
        ttk.Button(vb, text="Verify key", command=self._on_verify).pack(
            side=tk.LEFT)

        self.results = self._text(s2, height=8)
        self.results.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))
        self._set_text(self.results, "No key read yet.")
        # The tools' streaming output goes to the app's shared Log pane below
        # the tabs (see _log), not a second box of its own.

    # ------------------------------------------------------------------
    # Small widget helpers
    # ------------------------------------------------------------------
    def _file_row(self, parent, label, var, browse, folder=False,
                  folder_too=None, hint=None):
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, padx=8, pady=3)
        ttk.Label(row, text=label, width=22).pack(side=tk.LEFT)
        ttk.Entry(row, textvariable=var).pack(
            side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(row, text="Folder…" if folder else "Browse…",
                   command=browse).pack(side=tk.LEFT, padx=(6, 0))
        if folder_too is not None:
            ttk.Button(row, text="Folder…",
                       command=folder_too).pack(side=tk.LEFT, padx=(6, 0))
        if hint:
            ttk.Label(parent, text="    " + hint, foreground="gray",
                      font=("Segoe UI", 8)).pack(anchor="w", padx=8)

    def _text(self, parent, height):
        colors = self._colors()
        t = tk.Text(parent, height=height, wrap="word", relief="flat",
                    font=("Consolas", 9), padx=6, pady=4,
                    background=colors["field_bg"], foreground=colors["fg"],
                    insertbackground=colors["fg"])
        t.tag_configure("ok", foreground=colors["success"])
        t.tag_configure("bad", foreground=colors["error"])
        t.tag_configure("warn", foreground=colors["warning"])
        t.configure(state="disabled")
        return t

    def _colors(self):
        from .theme import THEMES
        name = self._theme_fn() if callable(self._theme_fn) else "dark"
        return THEMES.get(name, THEMES["dark"])

    def _set_text(self, widget, text, tag=None):
        widget.configure(state="normal")
        widget.delete("1.0", tk.END)
        widget.insert(tk.END, text, tag or ())
        widget.configure(state="disabled")


    # ------------------------------------------------------------------
    # Browse handlers
    # ------------------------------------------------------------------
    def _browse_source(self):
        p = filedialog.askopenfilename(
            title="Card image or boot.img",
            filetypes=[("Card image / boot.img",
                        "*.raw *.img *.bin BOOT.IMG"), ("All files", "*.*")])
        if p:
            self.src_var.set(p)
            if not self.out_var.get():
                self.out_var.set(os.path.join(
                    os.path.dirname(p), "spike3_extractor"))

    def _browse_sig(self):
        p = filedialog.askopenfilename(
            title="Boot signature",
            filetypes=[("Boot signature", "*.sig BOOT.SIG"),
                       ("All files", "*.*")])
        if p:
            self.sig_var.set(p)

    def _browse_outdir(self):
        p = filedialog.askdirectory(title="Save the two files to")
        if p:
            self.out_var.set(p)

    def _browse_readback(self):
        p = filedialog.askopenfilename(
            title="OTP_KEY.TXT or card image",
            filetypes=[("Key file or image", "*.txt *.raw *.img *.bin"),
                       ("All files", "*.*")])
        if p:
            self.read_var.set(p)

    def _browse_readfolder(self):
        p = filedialog.askdirectory(title="Boot partition folder")
        if p:
            self.read_var.set(p)

    def _browse_header(self):
        p = filedialog.askopenfilename(
            title="Card image or LUKS header",
            filetypes=[("Image or header", "*.raw *.img *.bin"),
                       ("All files", "*.*")])
        if p:
            self.header_var.set(p)

    # ------------------------------------------------------------------
    # Worker plumbing (the worker NEVER touches Tk)
    # ------------------------------------------------------------------
    def _ui(self, fn):
        if self._frame is not None:
            self._frame.after(0, fn)

    def _log(self, line, level="info"):
        """Send a line to the app's shared Log pane, colour-coded by *level*
        ("info" / "success" / "error" - the pane's own tags).  Falls back to a
        one-argument sink (a test's plain callable)."""
        try:
            self._log_sink(line, level)
        except TypeError:
            self._log_sink(line)

    def _set_busy(self, busy):
        self._busy = busy
        state = "disabled" if busy else "normal"
        for b in (self.prepare_btn,):
            try:
                b.configure(state=state)
            except tk.TclError:
                pass

    def _start(self, work):
        if self._busy:
            self._status_fn("Spike 3: a task is already running.")
            return False
        self._set_busy(True)
        threading.Thread(target=self._wrap(work), daemon=True).start()
        return True

    def _wrap(self, work):
        def run():
            try:
                work()
            except Exception as exc:                # noqa: BLE001
                self._log("[spike3] error: %s" % exc, "error")
                self._ui(lambda: self._status_fn("Spike 3: failed - see the "
                                                 "tool output."))
            finally:
                self._ui(lambda: self._set_busy(False))
        return run

    def _log_block(self, text, level="info"):
        """Send a tool's captured multi-line output to the shared Log, one line
        at a time so each gets the pane's timestamp.  Runs on the worker."""
        for line in (text or "").splitlines():
            if line.strip():
                self._log("[spike3] " + line, level)

    # ------------------------------------------------------------------
    # Step 1: prepare
    # ------------------------------------------------------------------
    def _on_prepare(self):
        src = self.src_var.get().strip()
        outdir = self.out_var.get().strip()
        sig = self.sig_var.get().strip() or None
        if not src or not os.path.exists(src):
            messagebox.showerror("Spike 3", "Pick a card image or boot.img "
                                            "first.")
            return
        if not spike3.tools_available():
            messagebox.showerror("Spike 3", _TOOLS_MISSING)
            return
        if not outdir:
            outdir = os.path.join(os.path.dirname(src), "spike3_extractor")
            self.out_var.set(outdir)

        def work():
            self._ui(lambda: self._status_fn("Spike 3: building extractor "
                                             "files…"))
            rc, out = spike3.run_prepare(src, outdir, boot_sig=sig)
            self._log_block(out, "info" if rc == 0 else "error")
            img = os.path.join(outdir, "boot.img")
            if rc == 0 and os.path.exists(img):
                self._prepared_dir = outdir
                self._ui(self._prepare_ok)
            else:
                self._ui(lambda: self._status_fn(
                    "Spike 3: prepare failed (exit %d) - see the Log." % rc))
        self._start(work)

    def _prepare_ok(self):
        outdir = self._prepared_dir or self.out_var.get()
        self.copy_btn.configure(state="normal")
        self._status_fn("Spike 3: extractor files ready in %s" % outdir)
        self._set_text(self.instructions,
                       _prep_done_text(outdir))

    def _on_copy_to_card(self):
        outdir = self._prepared_dir or self.out_var.get().strip()
        img = os.path.join(outdir, "boot.img")
        sig = os.path.join(outdir, "boot.sig")
        if not os.path.exists(img):
            messagebox.showerror("Spike 3", "Prepare the files first.")
            return
        dest = filedialog.askdirectory(
            title="The card's boot partition (the drive that opens on this PC)")
        if not dest:
            return
        existing = os.path.join(dest, "boot.img")
        if not os.path.exists(existing):
            if not messagebox.askyesno(
                    "Spike 3",
                    "That folder has no boot.img on it, so it may not be the "
                    "card's boot partition.\n\nCopy the extractor files there "
                    "anyway?"):
                return

        def work():
            backup = os.path.join(dest, "spike3-backup-%s"
                                  % time.strftime("%Y%m%d-%H%M%S"))
            try:
                if os.path.exists(existing):
                    os.makedirs(backup, exist_ok=True)
                    for name in ("boot.img", "boot.sig"):
                        srcf = os.path.join(dest, name)
                        if os.path.exists(srcf):
                            shutil.copy2(srcf, os.path.join(backup, name))
                    self._log("[spike3] backed up originals to %s" % backup)
                for name in ("boot.img", "boot.sig"):
                    srcf = os.path.join(outdir, name)
                    if os.path.exists(srcf):
                        shutil.copy2(srcf, os.path.join(dest, name))
                        self._log("[spike3] copied %s -> %s" % (name, dest))
                self._ui(lambda: self._status_fn(
                    "Spike 3: card prepped. Eject it, boot the machine once, "
                    "then read OTP_KEY.TXT back."))
            except OSError as exc:
                self._log("[spike3] copy failed: %s" % exc, "error")
                self._ui(lambda: self._status_fn(
                    "Spike 3: could not write to that drive - %s" % exc))
        self._start(work)

    # ------------------------------------------------------------------
    # Step 2: read + verify
    # ------------------------------------------------------------------
    def _on_read(self):
        raw = self.read_var.get().strip()
        if not raw:
            messagebox.showerror("Spike 3", "Point me at OTP_KEY.TXT, the boot "
                                            "folder, a card image, or paste a "
                                            "key.")
            return
        # A pasted key is not a path - accept it directly.
        pasted = spike3.parse_key_text(raw)
        if pasted and not os.path.exists(raw):
            self._show_key(pasted, "Read the key you pasted.")
            return

        def work():
            res = spike3.read_key(raw)
            self._ui(lambda: self._deliver_read(res))
        self._start(work)

    def _deliver_read(self, res):
        if res.key_hex:
            self._show_key(res.key_hex, res.note)
        else:
            self.key_var.set("")
            self._set_text(self.results, res.note or "No key found.", "bad")
            self._log(res.note or "Spike 3: no key found.", "error")
            self._status_fn("Spike 3: no key found.")

    def _show_key(self, key_hex, note):
        self.key_var.set(key_hex)
        self._set_text(self.results, "KEY: %s\n\n%s\n\n%s"
                       % (key_hex, note,
                          "Verify it against a card image below to see which "
                          "games it opens."), "ok")
        self._log("Recovered OTP key: %s" % key_hex, "success")
        self._status_fn("Spike 3: key recovered (%s...)." % key_hex[:12])

    def _on_verify(self):
        key = self.key_var.get().strip()
        target = self.header_var.get().strip()
        if not spike3.is_valid_key_hex(key):
            messagebox.showerror("Spike 3", "Read a valid 64-hex key first.")
            return
        if not target or not os.path.exists(target):
            messagebox.showerror("Spike 3", "Pick a card image or a LUKS "
                                            "header file to verify against.")
            return
        if not spike3.tools_available():
            messagebox.showerror("Spike 3", _TOOLS_MISSING)
            return

        def work():
            self._ui(lambda: self._status_fn("Spike 3: verifying…"))
            self._ui(lambda: self._set_text(self.results, "Verifying…"))
            size = os.path.getsize(target)
            if size <= 32 * (1 << 20):
                # A small file is a single carved header.
                results = [self._verify_header(target, "header", key)]
            else:
                results = self._verify_image(target, key)
            self._ui(lambda: self._render_verify(results))
        self._start(work)

    def _verify_header(self, header_path, name, key):
        rc, text = spike3.run_verify(header_path, key)
        self._log_block(text, "info")
        info = spike3.interpret_verify_output(text, rc)
        return {"name": name, "valid": info["valid"],
                "master_key": info["master_key"]}

    def _verify_image(self, image, key):
        results = []
        tmp = tempfile.mkdtemp(prefix="spike3_hdr_")
        try:
            for part in spike3.KNOWN_PARTITIONS:
                if not spike3.looks_like_luks2(image, part.lba):
                    continue
                hp = os.path.join(tmp, "%s.bin" % part.name)
                try:
                    spike3.carve_header(image, part.lba, hp)
                except OSError as exc:
                    self._log("[spike3] carve %s failed: %s"
                              % (part.name, exc))
                    continue
                r = self._verify_header(hp, part.name, key)
                r["desc"] = part.desc
                results.append(r)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return results

    def _render_verify(self, results):
        if not results:
            self._set_text(self.results,
                           "No LUKS2 volumes found to verify against. If this "
                           "is a card image, its partitions may be laid out "
                           "differently - send it to David.", "warn")
            self._status_fn("Spike 3: nothing to verify.")
            return
        lines = []
        good = 0
        for r in results:
            mark = "VALID  " if r["valid"] else "invalid"
            tail = ("  %s" % r.get("desc", "")) if r.get("desc") else ""
            line = "[%s] %s%s" % (mark, r["name"], tail)
            lines.append(line)
            self._log("Spike 3 verify " + line,
                      "success" if r["valid"] else "error")
            if r["valid"]:
                good += 1
        summary = ""
        if good == len(results) and good > 0:
            summary = ("\nThis one key opens every LUKS volume in this image. "
                       "Try it against a DIFFERENT game's image to prove the "
                       "key is global (one read covers every Spike 3).")
        elif good:
            summary = ("\nThe key opens some but not all volumes - worth "
                       "sending the full result to David.")
        else:
            summary = ("\nThe key did not open anything here. Double-check it "
                       "came from this machine, or that this is a real Spike 3 "
                       "image.")
        tag = "ok" if good else "bad"
        self._set_text(self.results, "\n".join(lines) + "\n" + summary, tag)
        self._status_fn("Spike 3: verified %d/%d volumes."
                        % (good, len(results)))


_TOOLS_MISSING = (
    "The Spike 3 tools did not ship with this build of the app. Update to the "
    "latest version and try again."
)


_PREP_HELP = (
    "Pick a Spike 3 card image (or a bare boot.img) above and click Prepare.\n"
    "You get two small files, boot.img and boot.sig, plus the exact steps to "
    "send to the machine's owner. Nothing large is written and the original "
    "card is never modified here."
)


def _prep_done_text(outdir):
    return (
        "DONE. Your two files are in:\n    %s\n\n"
        "What the machine's owner does (all drag-and-drop, no typing):\n"
        "  1. Power the machine off, take out the SD card, put it in a PC.\n"
        "  2. If Windows offers to \"format\" a drive, click Cancel - do NOT "
        "format. Only one section of the card opens on a PC.\n"
        "  3. On the drive that opens, copy its boot.img and boot.sig into a "
        "safe backup folder first (the restore point).\n"
        "  4. Copy the two files above onto that drive, replacing the "
        "originals. Eject, put the card back, power on once.\n"
        "  5. Boots to the game -> a new OTP_KEY.TXT is on that drive; send it "
        "back. Won't boot -> secure boot is on (harmless); restore the backup "
        "and tell David.\n"
        "  6. Either way, put the backup's two files back at the end.\n\n"
        "Use \"Copy onto boot partition...\" to do steps 3-4 automatically on "
        "a card that is in THIS PC (it backs up the originals first)."
        % outdir
    )
