"""Manage disk space — a "disk management" modal for the app's scratch space.

The app stages its heavy disk work in two places on Windows:

  * **WSL** — the native-tool pipelines (Chicago Gaming, Dutch Pinball, Barrels
    of Fun, Jersey Jack) do their ext4/dd/debugfs work inside the default WSL2
    distro, whose virtual disk grows on demand and never shrinks on its own.
  * **The Windows temp dir** (``%TEMP%``) — other paths stage host-side, most
    notably **Stern Spike 2**, which never touches WSL at all.

A completed run cleans up after itself, but crashed/cancelled runs leave
staging behind in either place.  This modal shows, at a glance:
  * how full each disk is (usage bars),
  * every leftover staging item, grouped by location → manufacturer/game, with
    its size, and
  * a separate "Reclaim space to Windows" step that compacts the WSL virtual
    disk so freed bytes actually return to the Windows drive.

Cleaning up staging is fast and needs no privileges; reclaiming compacts the
``.vhdx`` (shuts WSL down, needs Administrator) and is an explicit secondary
action.  Slow work runs on worker threads and marshals back via ``after``.
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk

from ..core import host_temp, wsl_disk
from .theme import THEMES, dark_titlebar, platform_font

_LOC_WSL = "wsl"
_LOC_HOST = "host"
_LOC_LABEL = {_LOC_WSL: "WSL staging", _LOC_HOST: "Windows temp (%TEMP%)"}


def _fmt(n):
    """Binary GiB/MiB/KiB size string (matches how WSL/df report space)."""
    if n is None:
        return "—"
    if n >= 1024 ** 3:
        return "%.2f GiB" % (n / 1024 ** 3)
    if n >= 1024 ** 2:
        return "%.1f MiB" % (n / 1024 ** 2)
    if n >= 1024:
        return "%.0f KiB" % (n / 1024)
    return "%d B" % n


class DiskManagerDialog:
    """Modal disk-management view of WSL staging + the Windows temp dir."""

    def __init__(self, parent, theme_name, on_close=None):
        self._parent = parent
        self._on_close = on_close
        self._theme = THEMES.get(theme_name) or THEMES["light"]
        self._sans, self._mono = platform_font()
        self._entries = []          # combined scan: dicts + 'location' key
        self._iid_meta = {}         # leaf iid -> {'path', 'location'}
        self._size_by = {}          # (location, path) -> size, for confirms
        self._busy = False
        self._scan_id = 0
        self._wsl_ok = False
        self._usage_wsl = None
        self._usage_host = None
        self._vhdx = None

        self._build()
        self._refresh()

    # ------------------------------------------------------------------
    def _build(self):
        th = self._theme
        dlg = tk.Toplevel(self._parent)
        self._dlg = dlg
        # Hidden until built + positioned (deiconify at the tail); otherwise
        # dark_titlebar/_center's update_idletasks maps it at the default
        # spot first and it flickers into place (David).
        dlg.withdraw()
        dlg.title("Manage disk space")
        dlg.configure(bg=th["bg"])
        dark_titlebar(dlg, th is THEMES["dark"])
        dlg.transient(self._parent)
        dlg.protocol("WM_DELETE_WINDOW", self._close)

        body = ttk.Frame(dlg, padding=16)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Manage disk space",
                  font=(self._sans, 13, "bold")).pack(anchor="w")
        ttk.Label(
            body,
            text=("The tools stage their work in WSL (Chicago Gaming, Dutch "
                  "Pinball, Barrels of Fun, Jersey Jack) and in the Windows "
                  "temp folder (Stern, plus render/ffmpeg scratch). Neither "
                  "shrinks on its own — clean up leftover staging here."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=620, justify="left").pack(anchor="w", pady=(2, 12))

        # ---- Usage bars (WSL + Windows temp drive) --------------------
        self._wsl_usage_lbl, self._wsl_bar = self._make_usage_row(
            body, "Checking WSL…")
        self._host_usage_lbl, self._host_bar = self._make_usage_row(
            body, "Checking Windows temp drive…")

        # ---- Leftover-staging tree ------------------------------------
        ttk.Label(body, text="Leftover staging",
                  font=(self._sans, 10, "bold")).pack(anchor="w", pady=(8, 0))
        ttk.Label(
            body,
            text=("Select rows to remove, or use “Clean all”. Finished runs "
                  "clean up after themselves; what shows here is from crashed "
                  "or cancelled runs."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=620, justify="left").pack(anchor="w", pady=(0, 4))

        tree_wrap = ttk.Frame(body)
        tree_wrap.pack(fill="both", expand=True)
        self._tree = ttk.Treeview(
            tree_wrap, columns=("size",), show="tree headings",
            selectmode="extended", height=10)
        self._tree.heading("#0", text="Location / manufacturer / item")
        self._tree.heading("size", text="Size")
        self._tree.column("#0", width=440, anchor="w")
        self._tree.column("size", width=110, anchor="e", stretch=False)
        vsb = ttk.Scrollbar(tree_wrap, orient="vertical",
                            command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<<TreeviewSelect>>", lambda _e: self._update_buttons())

        srow = ttk.Frame(body)
        srow.pack(fill="x", pady=(8, 0))
        self._refresh_btn = ttk.Button(srow, text="Refresh",
                                       command=self._refresh)
        self._refresh_btn.pack(side="left")
        self._clean_sel_btn = ttk.Button(
            srow, text="Clean selected", command=self._clean_selected,
            state="disabled")
        self._clean_sel_btn.pack(side="left", padx=(8, 0))
        self._clean_all_btn = ttk.Button(
            srow, text="Clean all", command=self._clean_all, state="disabled")
        self._clean_all_btn.pack(side="left", padx=(8, 0))

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=14)

        # ---- Reclaim section (WSL .vhdx) ------------------------------
        ttk.Label(body, text="Reclaim WSL space to Windows",
                  font=(self._sans, 10, "bold")).pack(anchor="w")
        self._reclaim_lbl = ttk.Label(
            body,
            text=("Deleting WSL staging frees space inside WSL but doesn't "
                  "return it to Windows. Compact the virtual disk to hand it "
                  "back."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=620, justify="left")
        self._reclaim_lbl.pack(anchor="w", pady=(0, 4))
        rrow = ttk.Frame(body)
        rrow.pack(fill="x")
        self._reclaim_btn = ttk.Button(
            rrow, text="Reclaim space to Windows…", command=self._reclaim,
            state="disabled")
        self._reclaim_btn.pack(side="left")

        ttk.Separator(body, orient="horizontal").pack(fill="x", pady=14)

        # ---- Resize section (grow/shrink the WSL .vhdx) ---------------
        ttk.Label(body, text="Resize WSL disk",
                  font=(self._sans, 10, "bold")).pack(anchor="w")
        self._resize_lbl = ttk.Label(
            body,
            text=("Set how large the WSL virtual disk may grow. Increase it "
                  "when an extract needs more room than WSL has (the biggest "
                  "titles can need 20+ GiB); the disk only uses real space as "
                  "it fills. Shrinking is allowed down to what's already in "
                  "use. No Administrator needed."),
            font=(self._sans, 9), foreground=th["gray"],
            wraplength=620, justify="left")
        self._resize_lbl.pack(anchor="w", pady=(0, 4))
        zrow = ttk.Frame(body)
        zrow.pack(fill="x")
        self._resize_btn = ttk.Button(
            zrow, text="Resize WSL disk…", command=self._resize,
            state="disabled")
        self._resize_btn.pack(side="left")

        # ---- Status + close -------------------------------------------
        self._status = ttk.Label(body, text="", font=(self._sans, 9),
                                  wraplength=620, justify="left")
        self._status.pack(anchor="w", pady=(12, 0))
        crow = ttk.Frame(body)
        crow.pack(fill="x", pady=(12, 0))
        ttk.Button(crow, text="Close", command=self._close).pack(side="right")

        dlg.bind("<Escape>", lambda _e: self._close())
        self._center()
        dlg.deiconify()
        dlg.lift()
        dlg.update_idletasks()
        try:
            dlg.grab_set()
        except tk.TclError:
            dlg.update()
            dlg.grab_set()

    def _make_usage_row(self, parent, initial):
        th = self._theme
        lbl = ttk.Label(parent, text=initial, font=(self._sans, 10, "bold"))
        lbl.pack(anchor="w")
        bar = tk.Canvas(parent, height=18, highlightthickness=1,
                        highlightbackground=th["border"], bg=th["trough"])
        bar.pack(fill="x", pady=(3, 8))
        bar.bind("<Configure>",
                 lambda _e, b=bar: self._redraw_bar(b, getattr(b, "_pct", None)))
        return lbl, bar

    def _center(self):
        dlg = self._dlg
        self._parent.update_idletasks()
        dlg.update_idletasks()
        dw = max(dlg.winfo_reqwidth(), 680)
        dh = max(dlg.winfo_reqheight(), 620)
        pw, ph = self._parent.winfo_width(), self._parent.winfo_height()
        if pw <= 1 or ph <= 1:
            sw, sh = dlg.winfo_screenwidth(), dlg.winfo_screenheight()
            x, y = (sw - dw) // 2, (sh - dh) // 2
        else:
            x = self._parent.winfo_rootx() + (pw - dw) // 2
            y = self._parent.winfo_rooty() + (ph - dh) // 2
        dlg.geometry("%dx%d+%d+%d" % (dw, dh, max(0, x), max(0, y)))

    # ------------------------------------------------------------------
    # Usage bars
    # ------------------------------------------------------------------
    def _render_wsl_usage(self):
        if self._wsl_ok and self._usage_wsl:
            u = self._usage_wsl
            self._wsl_usage_lbl.configure(
                text="WSL disk: %s used of %s  (%s free, %d%%)" % (
                    _fmt(u["used"]), _fmt(u["total"]), _fmt(u["free"]),
                    u["pct"]))
            self._redraw_bar(self._wsl_bar, u["pct"])
        else:
            self._wsl_usage_lbl.configure(
                text="WSL: not available — %s" % getattr(self, "_wsl_msg", ""))
            self._redraw_bar(self._wsl_bar, None)

    def _render_host_usage(self):
        if self._usage_host:
            u = self._usage_host
            self._host_usage_lbl.configure(
                text="Windows temp drive (%s): %s used of %s  (%s free, %d%%)"
                % (u["drive"], _fmt(u["used"]), _fmt(u["total"]),
                   _fmt(u["free"]), u["pct"]))
            self._redraw_bar(self._host_bar, u["pct"])
        else:
            self._host_usage_lbl.configure(text="Windows temp drive: unknown")
            self._redraw_bar(self._host_bar, None)

    @staticmethod
    def _adjust_usage(usage, freed):
        """Optimistically fold *freed* bytes back into a usage dict in place."""
        if not usage or not freed:
            return
        usage["used"] = max(0, usage["used"] - freed)
        usage["free"] = usage["free"] + freed
        usage["pct"] = (int(round(usage["used"] * 100 / usage["total"]))
                        if usage["total"] else 0)

    def _redraw_bar(self, bar, pct):
        bar.delete("all")
        bar._pct = pct
        if pct is None:
            return
        w = bar.winfo_width()
        h = int(bar["height"])
        th = self._theme
        color = th["success"] if pct < 75 else (
            "#d98a00" if pct < 90 else th["error"])
        fill_w = int(w * pct / 100)
        if fill_w > 0:
            bar.create_rectangle(0, 0, fill_w, h, fill=color, width=0)

    # ------------------------------------------------------------------
    # State helpers
    # ------------------------------------------------------------------
    def _set_busy(self, busy, status=None):
        self._busy = busy
        if status is not None:
            self._status.configure(text=status)
        if not self._alive():
            return
        self._refresh_btn.configure(state="disabled" if busy else "normal")
        reclaim_ok = (not busy and self._wsl_ok and self._vhdx
                      and self._vhdx.get("path"))
        self._reclaim_btn.configure(state="normal" if reclaim_ok else "disabled")
        # Resizing only needs a usable WSL distro (no .vhdx lookup / no admin).
        self._resize_btn.configure(
            state="normal" if (not busy and self._wsl_ok) else "disabled")
        if busy:
            self._clean_sel_btn.configure(state="disabled")
            self._clean_all_btn.configure(state="disabled")
        else:
            self._update_buttons()

    def _update_buttons(self):
        if self._busy or not self._alive():
            return
        self._clean_all_btn.configure(
            state="normal" if self._entries else "disabled")
        self._clean_sel_btn.configure(
            state="normal" if self._selected_metas() else "disabled")

    def _alive(self):
        try:
            return bool(self._dlg.winfo_exists())
        except tk.TclError:
            return False

    def _leaf_metas_under(self, iid):
        """All leaf {'path','location'} dicts at or below tree node *iid*."""
        if iid in self._iid_meta:
            return [self._iid_meta[iid]]
        out = []
        for child in self._tree.get_children(iid):
            out.extend(self._leaf_metas_under(child))
        return out

    def _selected_metas(self):
        metas, seen = [], set()
        for iid in self._tree.selection():
            for m in self._leaf_metas_under(iid):
                key = (m["location"], m["path"])
                if key not in seen:
                    seen.add(key)
                    metas.append(m)
        return metas

    # ------------------------------------------------------------------
    # Scan / refresh
    # ------------------------------------------------------------------
    def _refresh(self):
        if self._busy:
            return
        self._scan_id += 1
        my_id = self._scan_id
        self._set_busy(True, "Scanning…")
        self._wsl_usage_lbl.configure(text="Checking WSL…")

        def _worker():
            data = {}
            # Host temp is local — always works, even without WSL.
            try:
                data["host_usage"] = host_temp.usage()
                data["host_entries"] = host_temp.scan()
            except Exception as e:  # noqa: BLE001
                data["host_usage"] = None
                data["host_entries"] = []
                data["host_err"] = str(e)
            # WSL — may be absent; degrade gracefully.
            ok, msg = wsl_disk.available()
            data["wsl_ok"] = ok
            data["wsl_msg"] = msg
            if ok:
                try:
                    data["wsl_usage"] = wsl_disk.usage()
                    data["wsl_entries"] = wsl_disk.scan_staging()
                    data["vhdx"] = wsl_disk.vhdx_info()
                except Exception as e:  # noqa: BLE001
                    data["wsl_ok"] = False
                    data["wsl_msg"] = str(e)
            self._after(self._apply_scan, my_id, data)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_scan(self, my_id, data):
        if my_id != self._scan_id or not self._alive():
            return

        # WSL usage bar.
        self._wsl_ok = data.get("wsl_ok", False)
        self._usage_wsl = data.get("wsl_usage")
        self._wsl_msg = data.get("wsl_msg", "")
        self._render_wsl_usage()

        # Windows temp drive usage bar.
        self._usage_host = data.get("host_usage")
        self._render_host_usage()

        # Combined entries (tag each with its location).
        entries = []
        for e in data.get("wsl_entries", []):
            entries.append({**e, "location": _LOC_WSL})
        for e in data.get("host_entries", []):
            entries.append({**e, "location": _LOC_HOST})
        self._entries = entries
        self._vhdx = data.get("vhdx")
        self._populate_tree()
        self._update_reclaim_label()

        total = sum(e["size"] for e in self._entries)
        if self._entries:
            status = "Found %d staging item(s) using %s." % (
                len(self._entries), _fmt(total))
        else:
            status = "No leftover staging — nothing to clean up."
        self._set_busy(False, status)

    def _populate_tree(self):
        tree = self._tree
        tree.delete(*tree.get_children())
        self._iid_meta = {}
        self._size_by = {}
        for e in self._entries:
            self._size_by[(e["location"], e["path"])] = e["size"]

        for loc in (_LOC_WSL, _LOC_HOST):
            loc_items = [e for e in self._entries if e["location"] == loc]
            if not loc_items:
                continue
            loc_size = sum(e["size"] for e in loc_items)
            loc_node = tree.insert(
                "", "end", text="%s  —  %d item%s" % (
                    _LOC_LABEL[loc], len(loc_items),
                    "" if len(loc_items) == 1 else "s"),
                values=(_fmt(loc_size),), open=True)
            groups = {}
            for e in loc_items:
                groups.setdefault(e["manufacturer"], []).append(e)
            for mfr, items in sorted(
                    groups.items(),
                    key=lambda kv: sum(e["size"] for e in kv[1]),
                    reverse=True):
                gsize = sum(e["size"] for e in items)
                mfr_node = tree.insert(
                    loc_node, "end", text="    %s  (%d)" % (mfr, len(items)),
                    values=(_fmt(gsize),), open=True)
                for e in sorted(items, key=lambda x: x["size"], reverse=True):
                    leaf = tree.insert(
                        mfr_node, "end", text="        %s" % e["detail"],
                        values=(_fmt(e["size"]),))
                    self._iid_meta[leaf] = {"path": e["path"],
                                            "location": e["location"]}

    def _update_reclaim_label(self):
        if not self._wsl_ok:
            self._reclaim_lbl.configure(
                text=("WSL isn't available, so there's no virtual disk to "
                      "reclaim. (Windows temp cleanup above still applies.)"))
            return
        v = self._vhdx or {}
        if not v.get("path"):
            self._reclaim_lbl.configure(
                text=("Couldn't locate the WSL virtual disk, so reclaiming "
                      "isn't available — staging cleanup above still works."))
            return
        extra = ""
        if v.get("reclaimable"):
            extra = "  About %s could be returned to Windows." % _fmt(
                v["reclaimable"])
        self._reclaim_lbl.configure(
            text=("The WSL virtual disk occupies %s on your Windows drive.%s\n"
                  "Compacting shuts WSL down and needs Administrator; it takes "
                  "a few minutes." % (_fmt(v.get("size")), extra)))

    # ------------------------------------------------------------------
    # Clean
    # ------------------------------------------------------------------
    def _clean_selected(self):
        self._do_clean(self._selected_metas(), "selected")

    def _clean_all(self):
        metas = [{"path": e["path"], "location": e["location"]}
                 for e in self._entries]
        self._do_clean(metas, "all")

    def _do_clean(self, metas, label):
        if self._busy or not metas:
            return
        total = sum(self._size_by.get((m["location"], m["path"]), 0)
                    for m in metas)
        if not messagebox.askyesno(
                "Delete staging",
                "Delete %d staging item(s) (%s)?\n\nThis only removes leftover "
                "intermediate files — your extracted assets and built images "
                "are not touched." % (len(metas), _fmt(total)),
                parent=self._dlg):
            return
        wsl_paths = [m["path"] for m in metas if m["location"] == _LOC_WSL]
        host_paths = [m["path"] for m in metas if m["location"] == _LOC_HOST]
        deleted = set(wsl_paths) | set(host_paths)
        self._set_busy(True, "Deleting %s staging…" % label)

        def _worker():
            wsl_freed = host_freed = 0
            err = None
            try:
                if wsl_paths:
                    wsl_freed = wsl_disk.delete(wsl_paths)
                if host_paths:
                    host_freed = host_temp.delete(host_paths)
            except Exception as e:  # noqa: BLE001
                err = str(e)
            self._after(self._after_clean, wsl_freed, host_freed, deleted, err)

        threading.Thread(target=_worker, daemon=True).start()

    def _after_clean(self, wsl_freed, host_freed, deleted, err):
        if not self._alive():
            return
        if err:
            self._set_busy(False, "")
            messagebox.showerror("Delete failed", err, parent=self._dlg)
            return
        # Update the view in place instead of forcing a full re-scan (which
        # would restart WSL + re-run `find` and feel like a hang).  Drop the
        # cleaned rows and fold the freed bytes back into the usage bars; the
        # numbers we just acted on are authoritative.  Refresh stays available
        # for an exact re-scan.
        self._entries = [e for e in self._entries if e["path"] not in deleted]
        self._populate_tree()
        self._adjust_usage(self._usage_wsl, wsl_freed)
        self._render_wsl_usage()
        self._adjust_usage(self._usage_host, host_freed)
        self._render_host_usage()
        # Freeing WSL space grows what a compact could reclaim.
        if self._vhdx and self._vhdx.get("reclaimable") is not None:
            self._vhdx["reclaimable"] += wsl_freed
        self._update_reclaim_label()
        self._set_busy(False, "Freed %s." % _fmt(wsl_freed + host_freed))

    # ------------------------------------------------------------------
    # Reclaim (compact .vhdx)
    # ------------------------------------------------------------------
    def _reclaim(self):
        if self._busy:
            return
        from ..core.admin import is_admin
        if not is_admin():
            messagebox.showwarning(
                "Administrator required",
                "Reclaiming space compacts the WSL virtual disk, which needs "
                "Administrator rights.\n\nClose the app, right-click it and "
                "choose “Run as administrator”, then reopen this window. "
                "(Cleaning up staging above does NOT need admin.)",
                parent=self._dlg)
            return
        if not messagebox.askyesno(
                "Reclaim space to Windows",
                "This will shut down WSL and compact its virtual disk so freed "
                "space is returned to Windows.\n\n• Any other WSL work will be "
                "stopped.\n• It can take a few minutes.\n\nMake sure no extract "
                "or build is running, then continue?",
                parent=self._dlg):
            return
        self._set_busy(True, "Reclaiming…")

        def _worker():
            try:
                reclaimed = wsl_disk.reclaim(progress=self._progress_from_thread)
                self._after(self._after_reclaim, reclaimed, None)
            except Exception as e:  # noqa: BLE001
                self._after(self._after_reclaim, 0, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _progress_from_thread(self, msg):
        self._after(lambda: self._status.configure(text=msg)
                    if self._alive() else None)

    def _after_reclaim(self, reclaimed, err):
        if not self._alive():
            return
        if err:
            self._set_busy(False, "")
            messagebox.showerror("Reclaim failed", err, parent=self._dlg)
            return
        messagebox.showinfo(
            "Reclaimed",
            "Returned %s to Windows by compacting the WSL virtual disk."
            % _fmt(reclaimed), parent=self._dlg)
        # Clear the operation flag so the follow-up _refresh isn't swallowed by
        # its own `if self._busy: return` guard (which would leave the dialog
        # stuck "busy" and warn on close).
        self._busy = False
        self._refresh()

    # ------------------------------------------------------------------
    # Resize (grow/shrink the .vhdx via `wsl --manage --resize`)
    # ------------------------------------------------------------------
    def _resize(self):
        if self._busy:
            return
        if not self._wsl_ok:
            messagebox.showinfo(
                "WSL not available",
                "There's no WSL distro to resize.", parent=self._dlg)
            return
        ok, msg = wsl_disk.resize_supported()
        if not ok:
            messagebox.showwarning("Resize not available", msg,
                                   parent=self._dlg)
            return
        u = self._usage_wsl or {}
        host_free = None
        try:
            host_free = wsl_disk.host_free_bytes()
        except Exception:  # noqa: BLE001
            pass
        new_bytes = self._ask_new_size(
            u.get("total"), u.get("used"), u.get("free"), host_free)
        if not new_bytes:
            return
        if not messagebox.askyesno(
                "Resize WSL disk",
                "Resize the WSL virtual disk to %s?\n\n• WSL will be shut down "
                "— close any running extract or build first.\n• It can take a "
                "few minutes.\n\nContinue?" % _fmt(new_bytes),
                parent=self._dlg):
            return
        self._set_busy(True, "Resizing…")

        def _worker():
            try:
                usage = wsl_disk.resize_disk(
                    new_bytes, progress=self._progress_from_thread)
                self._after(self._after_resize, usage, None)
            except Exception as e:  # noqa: BLE001
                self._after(self._after_resize, None, str(e))

        threading.Thread(target=_worker, daemon=True).start()

    def _ask_new_size(self, total, used, free, host_free):
        """Modal GB prompt; returns the chosen size in bytes, or None.

        Bounds: a floor a couple GiB above what's in use (you can't discard
        live data) and a ceiling of the current size plus the host drive's free
        space (you can't back more than the Windows drive can hold).
        """
        th = self._theme
        GiB = 1024 ** 3
        cur_gib = int(round((total or 0) / GiB)) or 1
        min_gib = max(1, int((used or 0) // GiB) + 2)
        max_gib = None
        if total is not None and host_free is not None:
            max_gib = max(min_gib, int((total + host_free) // GiB))
        result = {"bytes": None}

        win = tk.Toplevel(self._dlg)
        win.title("Resize WSL disk")
        win.configure(bg=th["bg"])
        dark_titlebar(win, th is THEMES["dark"])
        win.transient(self._dlg)
        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Resize WSL disk",
                  font=(self._sans, 12, "bold")).pack(anchor="w")
        info = "Current: %s max, %s used, %s free." % (
            _fmt(total), _fmt(used), _fmt(free))
        if host_free is not None:
            info += "\nWindows drive backing WSL has %s free." % _fmt(host_free)
        ttk.Label(frm, text=info, font=(self._sans, 9),
                  foreground=th["gray"], justify="left").pack(
            anchor="w", pady=(2, 10))
        row = ttk.Frame(frm)
        row.pack(anchor="w")
        ttk.Label(row, text="New size:", font=(self._sans, 10)).pack(
            side="left")
        var = tk.StringVar(value=str(cur_gib))
        ent = ttk.Entry(row, width=8, textvariable=var)
        ent.pack(side="left", padx=(6, 4))
        ttk.Label(row, text="GB").pack(side="left")
        bounds = "Allowed: %d – %s GB." % (
            min_gib, max_gib if max_gib is not None else "?")
        ttk.Label(frm, text=bounds, font=(self._sans, 8),
                  foreground=th["gray"]).pack(anchor="w", pady=(4, 0))
        err = ttk.Label(frm, text="", font=(self._sans, 9),
                        foreground=th["error"], wraplength=360, justify="left")
        err.pack(anchor="w", pady=(2, 0))

        def _ok():
            raw = var.get().strip()
            try:
                gib = int(float(raw))
            except ValueError:
                err.configure(text="Enter a whole number of GB.")
                return
            if gib < min_gib:
                err.configure(text="Too small — WSL is using %s. Minimum "
                              "%d GB." % (_fmt(used), min_gib))
                return
            if max_gib is not None and gib > max_gib:
                err.configure(text="Larger than the host drive can back. "
                              "Maximum %d GB." % max_gib)
                return
            result["bytes"] = gib * GiB
            win.destroy()

        brow = ttk.Frame(frm)
        brow.pack(fill="x", pady=(14, 0))
        ttk.Button(brow, text="Cancel", command=win.destroy,
                   style="Danger.TButton").pack(side="right")
        ttk.Button(brow, text="Resize", command=_ok,
                   style="Go.TButton").pack(side="right", padx=(0, 8))
        ent.focus_set()
        ent.select_range(0, "end")
        win.bind("<Return>", lambda _e: _ok())
        win.bind("<Escape>", lambda _e: win.destroy())
        win.update_idletasks()
        win.grab_set()
        self._dlg.wait_window(win)
        return result["bytes"]

    def _after_resize(self, usage, err):
        if not self._alive():
            return
        if err:
            self._set_busy(False, "")
            messagebox.showerror("Resize failed", err, parent=self._dlg)
            return
        # Update the WSL usage bar from the authoritative post-resize numbers
        # *before* the confirmation pops, so the bar already matches behind it.
        if usage:
            self._usage_wsl = usage
            self._render_wsl_usage()
            self._dlg.update_idletasks()
        messagebox.showinfo(
            "Resized",
            "WSL disk is now %s (%s free)." % (
                _fmt(usage.get("total")), _fmt(usage.get("free"))),
            parent=self._dlg)
        # Clear the operation flag first, else the follow-up _refresh hits its
        # own `if self._busy: return` guard and the dialog stays stuck "busy".
        self._busy = False
        # Full re-scan reconciles staging + the Reclaim section's .vhdx numbers.
        self._refresh()

    # ------------------------------------------------------------------
    def _after(self, fn, *a):
        """Marshal *fn* onto the Tk main loop if the dialog still exists."""
        try:
            self._dlg.after(0, lambda: fn(*a) if self._alive() else None)
        except tk.TclError:
            pass

    def _close(self):
        if self._busy:
            if not messagebox.askyesno(
                    "Operation in progress",
                    "A disk operation is still running. Close anyway?",
                    parent=self._dlg):
                return
        try:
            self._dlg.grab_release()
        except tk.TclError:
            pass
        self._dlg.destroy()
        if self._on_close:
            try:
                self._on_close()
            except Exception:
                pass
