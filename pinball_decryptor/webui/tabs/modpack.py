"""Mod Pack tab: export / import a mod pack zip and, for plugins with
``capabilities.mod_transfer`` (Stern Spike 2), "Move Your Mods to Another
Card": the one-click port and the step-by-step transfer form.  (The
"Optional: Apply Delta on Top" box is the Write tab's, as in Tk.)

Port of ``gui/main_window.py`` ``_build_modpack_tab`` (3684-3997) and the
methods it wires (``_browse_transfer_*``, ``_prefill_transfer_dst``,
``_transfer_refresh_meta``, ``_transfer_probe_img_version``,
``_open_folder_link``), plus the Mod Pack arm of ``_scan_assets_tab_by_name``
that ``invalidate_asset_scans`` / ``reload_assets_tabs`` reach.  The flows
themselves (every question, picker and confirmation) stay in ``app.py``
(``_start_export``, ``_start_import``, ``_start_transfer_mods``,
``_start_port_mods``); this service gives them the variables they read and
the buttons that start them.
Status: docs/plans/web_ui_tabs/modpack.md.
"""

import os
import subprocess
import sys
import threading

from .. import compat
from .base import TabService, rpc

#: Tooltips and hints, word for word from the Tk tab.
PROJECT_TIP = ("Shared by every tab — it is set on the Extract tab. "
               "Click to open it.")


class ModPackTab(TabService):
    ns = "modpack"
    key = "Mod Pack"
    label = "Mod Pack"
    group = "Build"
    icon = "modpack"
    exports = (
        "transfer_src_var", "transfer_dst_var", "transfer_oldstock_var",
        "transfer_newimg_var", "transfer_next_var",
        # read-only hints the Tk window carried as attributes too
        "transfer_output_var", "transfer_src_ver_var",
        "transfer_dst_ver_var", "transfer_oldstock_ver_var",
        "transfer_img_ver_var",
        "_prefill_transfer_dst", "_transfer_refresh_meta",
    )

    def __init__(self, window):
        super().__init__(window)
        # The four transfer fields (app._start_transfer_mods reads them).
        self.transfer_src_var = self.var("src")
        self.transfer_dst_var = self.var("dst")
        # Optional stock extract of the OLD version: its presence (not a
        # modal) chooses the accurate baseline route; empty = direct compare.
        self.transfer_oldstock_var = self.var("oldstock")
        # The NEW version's card image: auto-filled from the new extract's
        # recorded source so it can't drift to the old version.
        self.transfer_newimg_var = self.var("newimg")
        # Read-only hints recomputed by _transfer_refresh_meta.
        self.transfer_src_ver_var = self.var("src_ver")
        self.transfer_dst_ver_var = self.var("dst_ver")
        self.transfer_oldstock_ver_var = self.var("oldstock_ver")
        self.transfer_img_ver_var = self.var("img_ver")
        self.transfer_output_var = self.var("output")
        # Filled by the run logic after a successful transfer.
        self.transfer_next_var = self.var("next")

        self._transfer_img_probe_path = ""
        self._transfer_img_probe_after = None
        self._transfer_img_ver_cache = {}
        self._project_var = None
        self._project_trace = None

        for v in (self.transfer_src_var, self.transfer_dst_var,
                  self.transfer_oldstock_var, self.transfer_newimg_var):
            v.trace_add("write", lambda *_a: self._transfer_refresh_meta())
        self.set(project="", transfer_cap=False, modpack_cap=False,
                 running=False)

    # -- the shared project folder (Tk: _project_path_display over
    #    write_assets_var) ------------------------------------------------
    def _bind_project_var(self):
        var = getattr(self.window, "write_assets_var", None)
        if var is None:
            return
        if var is not self._project_var:
            if self._project_var is not None and self._project_trace:
                try:
                    self._project_var.trace_remove("write",
                                                   self._project_trace)
                except Exception:                    # noqa: BLE001
                    pass
            self._project_var = var
            self._project_trace = var.trace_add(
                "write", lambda *_a: self._mirror_project())
        self._mirror_project()

    def _mirror_project(self):
        var = self._project_var
        folder = ((var.get() if var is not None else "") or "").strip()
        if not self.ctx.loop.in_loop():
            self.ctx.loop.post(lambda: self.set(project=folder))
            return
        self.set(project=folder)

    # -- hooks -------------------------------------------------------------
    def on_manufacturer(self, mfr):
        caps = mfr.capabilities
        transfer = bool(getattr(caps, "mod_transfer", False))
        self.set(modpack_cap=bool(getattr(caps, "modpack", False)),
                 transfer_cap=transfer)
        self._bind_project_var()
        # Tk apply_manufacturer: the transfer section shows only for
        # mod_transfer plugins, and pre-fills the destination when it does.
        if transfer:
            self._prefill_transfer_dst()

    def on_show(self):
        # Tk _scan_assets_tab_by_name("Mod Pack") -> _prefill_transfer_dst
        self._bind_project_var()
        self._prefill_transfer_dst()

    def on_project(self, folder):
        self._bind_project_var()

    # -- cross-tab calls the run logic fans out (Tk invalidate_asset_scans /
    #    reload_assets_tabs -> _scan_assets_tab_by_name("Mod Pack")) --------
    def invalidate_asset_scans(self, rescan_visible=True):
        """Open project, closing it, the end of an extract: Tk re-scans the
        VISIBLE tab, and for Mod Pack that is the destination pre-fill."""
        if rescan_visible and self.window.current_tab_key() == self.key:
            self._on_loop(self._prefill_transfer_dst)

    def reload_assets_tabs(self):
        """A mod-pack import or a transfer: Tk re-scans every tab in the
        notebook (``_rescan_all_assets_tabs``), Mod Pack included."""
        if getattr(self, "_visible", False):
            self._on_loop(self._prefill_transfer_dst)

    def _on_loop(self, fn):
        if self.ctx.loop.in_loop():
            fn()
        else:
            self.ctx.loop.post(fn)

    def on_running(self, running, mode):
        self.set(running=bool(running))

    def on_close(self):
        pending = self._transfer_img_probe_after
        self._transfer_img_probe_after = None
        if pending is not None:
            try:
                self.ctx.loop.after_cancel(pending)
            except Exception:                        # noqa: BLE001
                pass

    # -- transfer form logic (Tk 21672-21790) -------------------------------
    def _prefill_transfer_dst(self):
        """Default the transfer destination to the Mod Folder (the usual flow:
        the user points the app at the NEW extract, then pulls mods into it).
        Only fills an empty field — never overwrites what the user picked."""
        if not (self.transfer_dst_var.get() or "").strip():
            var = getattr(self.window, "write_assets_var", None)
            cur = ((var.get() if var is not None else "") or "").strip()
            if cur:
                self.transfer_dst_var.set(cur)
        self._transfer_refresh_meta()

    def _transfer_refresh_meta(self):
        """Recompute the read-only version chips and the output-name preview
        from the current field values, and auto-fill the base card image (row
        4) from the new extract's recorded source (so the old-version image
        can never sneak in as the base)."""
        from ...core import extract_source

        src = (self.transfer_src_var.get() or "").strip()
        dst = (self.transfer_dst_var.get() or "").strip()
        oldstock = (self.transfer_oldstock_var.get() or "").strip()

        def _dir_ver(d):
            if not d:
                return ""
            try:
                v, exact = extract_source.version_for_dir(d)
            except Exception:                        # noqa: BLE001
                return ""
            if not v:
                return ""
            return ("version " + v) if exact else ("version ~ " + v)
        self.transfer_src_ver_var.set(_dir_ver(src))
        self.transfer_dst_ver_var.set(_dir_ver(dst))
        self.transfer_oldstock_ver_var.set(_dir_ver(oldstock))

        # Auto-fill the base image from the new extract's recorded source,
        # unless the user has typed their own path.
        if dst and not (self.transfer_newimg_var.get() or "").strip():
            try:
                rec = extract_source.read_extract_source(dst)
            except Exception:                        # noqa: BLE001
                rec = None
            recorded = (rec or {}).get("input_path")
            if recorded and os.path.isfile(recorded):
                # Setting the var re-enters this method via its trace; the
                # guard above (field now non-empty) stops the recursion.
                self.transfer_newimg_var.set(os.path.normpath(recorded))
                return

        img = (self.transfer_newimg_var.get() or "").strip()
        img_ver = (extract_source.version_hint_from_name(os.path.basename(img))
                   if img else None)
        self.transfer_img_ver_var.set(("version ~ " + img_ver)
                                      if img_ver else "")
        self._transfer_probe_img_version(img)
        if img:
            mfr = self.mfr
            suffix = getattr(mfr, "write_output_suffix",
                             "-modified") or "-modified"
            stem, ext = os.path.splitext(os.path.basename(img))
            self.transfer_output_var.set(
                "After transfer, the Write tab builds: %s%s%s"
                % (stem, suffix, ext))
        else:
            self.transfer_output_var.set("")

    def _transfer_probe_img_version(self, img):
        """Upgrade field 4's version chip from the instant filename guess to
        the version the card ITSELF reports, off the UI loop: debounced and
        cached by the file's identity, because the probe opens the multi-GB
        image.  The result only lands if the field still shows the same path
        by the time it arrives."""
        self._transfer_img_probe_path = img
        if not img or not os.path.isfile(img):
            return
        mfr = self.mfr
        if not hasattr(mfr, "card_version"):
            return
        try:
            st = os.stat(img)
            key = (os.path.normcase(img), st.st_size, st.st_mtime_ns)
        except OSError:
            return
        cache = self._transfer_img_ver_cache
        hit = cache.get(key)
        if hit is not None:
            if hit:
                self.transfer_img_ver_var.set("version " + hit)
            return
        pending = self._transfer_img_probe_after
        if pending is not None:
            self.ctx.loop.after_cancel(pending)

        def _start():
            self._transfer_img_probe_after = None

            def _work(img=img, key=key, mfr=mfr):
                try:
                    ver, exact = mfr.card_version(img)
                except Exception:                    # noqa: BLE001
                    ver, exact = None, False

                def _land():
                    cache[key] = ver if (ver and exact) else ""
                    if (ver and exact
                            and self._transfer_img_probe_path == img
                            and (self.transfer_newimg_var.get() or "")
                            .strip() == img):
                        self.transfer_img_ver_var.set("version " + ver)
                self.ctx.loop.post(_land)
            threading.Thread(target=_work, name="pad-modpack-imgver",
                             daemon=True).start()

        self._transfer_img_probe_after = self.ctx.loop.after(500, _start)

    # -- the page's calls: pickers (Tk 21633-21670) ---------------------------
    def _write_assets(self):
        var = getattr(self.window, "write_assets_var", None)
        return (var.get() if var is not None else "") or ""

    @rpc
    def browse(self, field):
        """Browse... on one of the four transfer rows."""
        init = self.window._initialdir_for
        if field == "src":
            path = self.window.ask_folder(
                "transfer_src",
                "Select your OLD extract folder (the one with your mods)",
                initialdir=init(self.transfer_src_var.get(),
                                self.transfer_dst_var.get(),
                                self._write_assets()))
            var = self.transfer_src_var
        elif field == "dst":
            path = self.window.ask_folder(
                "transfer_dst",
                "Select the NEW version's extract folder (freshly extracted)",
                initialdir=init(self.transfer_dst_var.get(),
                                self._write_assets(),
                                self.transfer_src_var.get()))
            var = self.transfer_dst_var
        elif field == "oldstock":
            path = self.window.ask_folder(
                "transfer_oldstock",
                "Select a STOCK (unmodified) extract of the OLD version "
                "— optional",
                initialdir=init(self.transfer_oldstock_var.get(),
                                self.transfer_src_var.get()))
            var = self.transfer_oldstock_var
        elif field == "newimg":
            path = self.window.ask_open(
                "transfer_newimg",
                "Select the NEW version's card image (.raw/.img) to build "
                "onto",
                [("Card image", "*.raw *.img *.bin"), ("All files", "*.*")],
                initialdir=init(
                    os.path.dirname(self.transfer_newimg_var.get() or ""),
                    self.transfer_dst_var.get()))
            var = self.transfer_newimg_var
        else:
            raise ValueError("no transfer field %r" % (field,))
        if path:
            var.set(os.path.normpath(path))
        return path or ""

    # -- the page's calls: the flows (app.py drives each one) ---------------
    def _run_cb(self, name):
        cb = self.window.cb.get(name)
        if cb is not None:
            cb()
            return True
        return False

    @rpc
    def export_pack(self):
        """Export Mod Pack... (app._start_export)."""
        return self._run_cb("on_export")

    @rpc
    def import_pack(self):
        """Import Mod Pack... (app._start_import)."""
        return self._run_cb("on_import")

    @rpc
    def port(self):
        """Port + build onto card image(s)... (app._start_port_mods)."""
        return self._run_cb("on_port_mods")

    @rpc
    def transfer(self):
        """Transfer mods -> new version... (app._start_transfer_mods)."""
        return self._run_cb("on_transfer_mods")

    # -- the project folder link (Tk _open_folder_link) ---------------------
    @rpc
    def open_project(self):
        """Click on the Project Folder link: open it in the file manager, or
        say plainly why there's nothing to open."""
        path = self._write_assets().strip()
        if not path:
            compat.messagebox.showinfo(
                "Open folder",
                "No project folder yet — set it on the Extract tab.")
            return False
        if not os.path.exists(path):
            compat.messagebox.showinfo(
                "Open folder",
                "This folder doesn't exist yet:\n%s" % path)
            return False
        return self._reveal_folder(path)

    @staticmethod
    def _reveal_folder(path):
        """Tk ``_reveal_in_file_manager`` for a folder (no web-window helper
        exists yet; see the status doc's core requests)."""
        from ...core import desktop
        path = os.path.abspath(path)
        try:
            if sys.platform == "win32":
                os.startfile(path)                 # noqa: S606 (Windows)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", path])
            else:
                ok, err = desktop.open_path(path)
                if not ok:
                    raise RuntimeError(err)
        except Exception as e:                       # noqa: BLE001
            compat.messagebox.showwarning(
                "Couldn't open file manager",
                "Couldn't reveal this file:\n%s\n\n%s" % (path, e))
            return False
        return True


TAB = ModPackTab
