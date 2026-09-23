"""Settings ▸ "Manage disk space…" on the page (Windows only), and the gear's
leftover-staging badge.

A port of the Tk ``DiskManagerDialog`` and
``MainWindow._start_disk_badge_check``: the same ``core.host_temp`` /
``core.wsl_disk`` calls and the same emulator card-cache helpers
(``emu_cache.scan_emu_cache`` / ``drop_emu_cache``), the same questions and
wording.  The window is the page dialog ``disk_space``; its state is
``shellx.disk``.

Captures and tests (``PAD_UI_NO_RIG``) never run wsl.exe or the rig: the WSL
half reads "not available" and the emulator cache "nothing cached".
"""

import logging
import os
import sys
import threading

from . import compat
from .rpc import rpc
from .shellx_common import fmt_binary as _fmt

log = logging.getLogger(__name__)

LOC_WSL, LOC_HOST, LOC_EMU = "wsl", "host", "emu"
LOC_LABEL = {
    LOC_WSL: "WSL staging",
    LOC_HOST: "Windows temp (%TEMP%)",
    LOC_EMU: "Spike 2 emulator card cache",
}

INTRO = ("The tools stage their work in WSL (Chicago Gaming, Dutch Pinball, "
         "Barrels of Fun, Jersey Jack) and in the Windows temp folder "
         "(Stern, plus render/ffmpeg scratch), and the Spike 2 emulator keeps "
         "whole cards cached on its own disk. None of them shrinks on its "
         "own — clean up here.")
TREE_NOTE = ("Select rows to remove, or use “Clean all”. Finished runs clean "
             "up after themselves, so the staging rows here are from crashed "
             "or cancelled runs. Cached emulator cards are different: they are "
             "meant to be there, and deleting one costs a re-copy the next "
             "time that card boots.")
RESIZE_NOTE = ("Set how large the WSL virtual disk may grow. Increase it when "
               "an extract needs more room than WSL has (the biggest titles "
               "can need 20+ GiB); the disk only uses real space as it fills. "
               "Shrinking is allowed down to what's already in use. No "
               "Administrator needed.")
RECLAIM_NOTE = ("Deleting WSL staging frees space inside WSL but doesn't "
                "return it to Windows. Compact the virtual disk to hand it "
                "back.")


def _probes_allowed():
    """wsl.exe and the rig are never touched by captures or tests."""
    return not (os.environ.get("PAD_UI_NO_RIG")
                or os.environ.get("PAD_UI_NO_PREREQS"))


def _emu_helpers():
    """emu_cache's card-cache scan/drop, or None (no emulator, no rig)."""
    try:
        from .emu_cache import drop_emu_cache, scan_emu_cache
        return scan_emu_cache, drop_emu_cache
    except Exception:                                   # noqa: BLE001
        return None


def _mb():
    return compat.messagebox


class DiskMixin:
    """Mixed into the ``shellx`` service."""

    def _disk_init(self):
        self._disk = None               # the open window's working state
        self._disk_scan_id = 0
        self.disk_badge_suffix = ""
        self.set(disk=None)

    # ------------------------------------------------------------------
    # the gear's amber badge (MainWindow._start_disk_badge_check)
    # ------------------------------------------------------------------
    def start_disk_badge_check(self):
        if sys.platform != "win32" or not _probes_allowed():
            return

        def _worker():
            count, total = 0, 0
            try:
                from ..core import host_temp
                for e in host_temp.scan():
                    count += 1
                    total += e["size"]
            except Exception:                           # noqa: BLE001
                pass
            try:
                from ..core import wsl_disk
                if wsl_disk.is_running():
                    for e in wsl_disk.scan_staging():
                        count += 1
                        total += e["size"]
            except Exception:                           # noqa: BLE001
                pass
            self.ctx.loop.post(self.apply_disk_badge, count, total)

        threading.Thread(target=_worker, name="pad-shellx-diskbadge",
                         daemon=True).start()

    def apply_disk_badge(self, count, total):
        self.disk_badge_suffix = ("⚠ %s" % _fmt(total)) if count > 0 else ""
        self.set(disk_badge=self.disk_badge_suffix)
        self.publish_settings_items()

    # ------------------------------------------------------------------
    # the window
    # ------------------------------------------------------------------
    def _disk_state(self):
        d = self._disk
        if d is None:
            return None
        return dict(d["view"])

    def _disk_view(self, **kw):
        if self._disk is None:
            return
        self._disk["view"].update(kw)
        self.set(disk=dict(self._disk["view"]))

    @rpc
    def disk_open(self):
        """The window opened: its first scan."""
        self._disk = {
            "busy": False, "entries": [], "size_by": {}, "wsl_ok": False,
            "wsl_msg": "", "usage": {LOC_WSL: None, LOC_HOST: None,
                                     LOC_EMU: None},
            "vhdx": None,
            "view": {"intro": INTRO, "tree_note": TREE_NOTE,
                     "resize_note": RESIZE_NOTE, "reclaim_note": RECLAIM_NOTE,
                     "bars": [
                         {"key": LOC_WSL, "text": "Checking WSL…",
                          "pct": None},
                         {"key": LOC_HOST,
                          "text": "Checking Windows temp drive…",
                          "pct": None},
                         {"key": LOC_EMU,
                          "text": "Checking the Spike 2 emulator cache…",
                          "pct": None}],
                     "rows": [], "status": "", "busy": False,
                     "can_clean_all": False, "can_reclaim": False,
                     "can_resize": False}}
        self.set(disk=self._disk_state())
        self.disk_refresh()
        return self._disk_state()

    def _disk_busy(self, busy, status=None):
        d = self._disk
        if d is None:
            return
        d["busy"] = busy
        kw = {"busy": busy}
        if status is not None:
            kw["status"] = status
        reclaim_ok = bool(not busy and d["wsl_ok"] and d["vhdx"]
                          and d["vhdx"].get("path"))
        kw["can_reclaim"] = reclaim_ok
        kw["can_resize"] = bool(not busy and d["wsl_ok"])
        kw["can_clean_all"] = bool(not busy and d["entries"])
        self._disk_view(**kw)

    @rpc
    def disk_refresh(self):
        d = self._disk
        if d is None or d["busy"]:
            return False
        self._disk_scan_id += 1
        my_id = self._disk_scan_id
        bars = [dict(b) for b in d["view"]["bars"]]
        bars[0]["text"] = "Checking WSL…"
        self._disk_view(bars=bars)
        self._disk_busy(True, "Scanning…")
        allowed = _probes_allowed()

        def _worker():
            from ..core import host_temp, wsl_disk
            data = {}
            try:
                data["host_usage"] = host_temp.usage()
                data["host_entries"] = host_temp.scan()
            except Exception as e:                      # noqa: BLE001
                data["host_usage"] = None
                data["host_entries"] = []
                data["host_err"] = str(e)
            if allowed:
                ok, msg = wsl_disk.available()
            else:
                ok, msg = False, "not checked in this session."
            data["wsl_ok"], data["wsl_msg"] = ok, msg
            if ok:
                try:
                    data["wsl_usage"] = wsl_disk.usage()
                    data["wsl_entries"] = wsl_disk.scan_staging()
                    data["vhdx"] = wsl_disk.vhdx_info()
                except Exception as e:                  # noqa: BLE001
                    data["wsl_ok"] = False
                    data["wsl_msg"] = str(e)
            helpers = _emu_helpers() if allowed else None
            if helpers:
                data["emu_entries"], data["emu_usage"] = helpers[0]()
            else:
                data["emu_entries"], data["emu_usage"] = [], None
            self.ctx.loop.post(self._disk_apply_scan, my_id, data)

        threading.Thread(target=_worker, name="pad-shellx-diskscan",
                         daemon=True).start()
        return True

    def _bar_texts(self):
        d = self._disk
        u = d["usage"]
        bars = []
        w = u[LOC_WSL]
        if d["wsl_ok"] and w:
            bars.append({"key": LOC_WSL, "pct": w["pct"],
                         "text": "WSL disk: %s used of %s  (%s free, %d%%)"
                         % (_fmt(w["used"]), _fmt(w["total"]),
                            _fmt(w["free"]), w["pct"])})
        else:
            bars.append({"key": LOC_WSL, "pct": None,
                         "text": "WSL: not available — %s" % d["wsl_msg"]})
        h = u[LOC_HOST]
        if h:
            bars.append({"key": LOC_HOST, "pct": h["pct"],
                         "text": "Windows temp drive (%s): %s used of %s  "
                                 "(%s free, %d%%)"
                         % (h["drive"], _fmt(h["used"]), _fmt(h["total"]),
                            _fmt(h["free"]), h["pct"])})
        else:
            bars.append({"key": LOC_HOST, "pct": None,
                         "text": "Windows temp drive: unknown"})
        e = u[LOC_EMU]
        if e:
            bars.append({"key": LOC_EMU, "pct": e["pct"],
                         "text": "Spike 2 emulator disk: %s used of %s  "
                                 "(%s free, %d%%)"
                         % (_fmt(e["used"]), _fmt(e["total"]),
                            _fmt(e["free"]), e["pct"])})
        else:
            bars.append({"key": LOC_EMU, "pct": None,
                         "text": "Spike 2 emulator cache: nothing cached"})
        return bars

    def _disk_rows(self):
        """The tree, flattened: location → manufacturer → item, with the
        leaf metas each node covers (the page selects nodes)."""
        d = self._disk
        rows = []
        d["size_by"] = {(e["location"], e["path"]): e["size"]
                        for e in d["entries"]}
        for loc in (LOC_WSL, LOC_HOST, LOC_EMU):
            loc_items = [e for e in d["entries"] if e["location"] == loc]
            if not loc_items:
                continue
            loc_id = "L:" + loc
            rows.append({
                "id": loc_id, "level": 0,
                "text": "%s  —  %d item%s" % (
                    LOC_LABEL[loc], len(loc_items),
                    "" if len(loc_items) == 1 else "s"),
                "size": _fmt(sum(e["size"] for e in loc_items)),
                "leaves": [[loc, e["path"]] for e in loc_items]})
            groups = {}
            for e in loc_items:
                groups.setdefault(e["manufacturer"], []).append(e)
            for mfr, items in sorted(
                    groups.items(),
                    key=lambda kv: sum(e["size"] for e in kv[1]),
                    reverse=True):
                mid = "M:%s:%s" % (loc, mfr)
                rows.append({
                    "id": mid, "level": 1,
                    "text": "%s  (%d)" % (mfr, len(items)),
                    "size": _fmt(sum(e["size"] for e in items)),
                    "leaves": [[loc, e["path"]] for e in items]})
                for e in sorted(items, key=lambda x: x["size"],
                                reverse=True):
                    rows.append({
                        "id": "I:%s:%s" % (loc, e["path"]), "level": 2,
                        "text": e["detail"], "size": _fmt(e["size"]),
                        "leaves": [[loc, e["path"]]]})
        return rows

    def _reclaim_text(self):
        d = self._disk
        if not d["wsl_ok"]:
            return ("WSL isn't available, so there's no virtual disk to "
                    "reclaim. (Windows temp cleanup above still applies.)")
        v = d["vhdx"] or {}
        if not v.get("path"):
            return ("Couldn't locate the WSL virtual disk, so reclaiming "
                    "isn't available — staging cleanup above still works.")
        extra = ""
        if v.get("reclaimable"):
            extra = "  About %s could be returned to Windows." % _fmt(
                v["reclaimable"])
        return ("The WSL virtual disk occupies %s on your Windows drive.%s\n"
                "Compacting shuts WSL down and needs Administrator; it takes "
                "a few minutes." % (_fmt(v.get("size")), extra))

    def _disk_apply_scan(self, my_id, data):
        d = self._disk
        if d is None or my_id != self._disk_scan_id:
            return
        d["wsl_ok"] = data.get("wsl_ok", False)
        d["wsl_msg"] = data.get("wsl_msg", "")
        d["usage"] = {LOC_WSL: data.get("wsl_usage"),
                      LOC_HOST: data.get("host_usage"),
                      LOC_EMU: data.get("emu_usage")}
        entries = []
        for e in data.get("wsl_entries", []) or []:
            entries.append(dict(e, location=LOC_WSL))
        for e in data.get("host_entries", []) or []:
            entries.append(dict(e, location=LOC_HOST))
        for e in data.get("emu_entries", []) or []:
            entries.append(dict(e, location=LOC_EMU))
        d["entries"] = entries
        d["vhdx"] = data.get("vhdx")
        staging = [e for e in entries if e["location"] != LOC_EMU]
        cached = [e for e in entries if e["location"] == LOC_EMU]
        parts = []
        if staging:
            parts.append("%d staging item%s using %s" % (
                len(staging), "" if len(staging) == 1 else "s",
                _fmt(sum(e["size"] for e in staging))))
        if cached:
            parts.append("%d cached card%s using %s" % (
                len(cached), "" if len(cached) == 1 else "s",
                _fmt(sum(e["size"] for e in cached))))
        status = ("Found " + " and ".join(parts) + ".") if parts else \
            "No leftover staging and no cached cards."
        self._disk_view(bars=self._bar_texts(), rows=self._disk_rows(),
                        reclaim_note=self._reclaim_text())
        self._disk_busy(False, status)

    # ------------------------------------------------------------------
    # clean
    # ------------------------------------------------------------------
    @rpc
    def disk_clean(self, metas, label="selected"):
        """Clean selected / Clean all.  *metas*: [[location, path], ...];
        None = every entry."""
        d = self._disk
        if d is None or d["busy"]:
            return False
        if metas is None:
            metas = [[e["location"], e["path"]] for e in d["entries"]]
            label = "all"
        seen, uniq = set(), []
        for loc, path in metas or []:
            if (loc, path) not in seen:
                seen.add((loc, path))
                uniq.append((loc, path))
        if not uniq:
            return False
        wsl_paths = [p for loc, p in uniq if loc == LOC_WSL]
        host_paths = [p for loc, p in uniq if loc == LOC_HOST]
        emu_labels = [p for loc, p in uniq if loc == LOC_EMU]
        staging_n = len(wsl_paths) + len(host_paths)
        staging_sz = sum(d["size_by"].get((loc, p), 0)
                         for loc, p in uniq if loc != LOC_EMU)
        emu_sizes = {lb: d["size_by"].get((LOC_EMU, lb), 0)
                     for lb in emu_labels}
        emu_sz = sum(emu_sizes.values())
        lines = []
        if staging_n:
            lines.append("%d staging item%s (%s) — leftover intermediate "
                         "files only." % (staging_n,
                                          "" if staging_n == 1 else "s",
                                          _fmt(staging_sz)))
        if emu_labels:
            lines.append("%d cached emulator card%s (%s) — each one re-copies "
                         "the next time that card boots."
                         % (len(emu_labels),
                            "" if len(emu_labels) == 1 else "s",
                            _fmt(emu_sz)))
        if not _mb().askyesno(
                "Delete staging",
                "Delete:\n\n  • " + "\n  • ".join(lines)
                + "\n\nYour extracted assets and built images are not "
                  "touched."):
            return False
        deleted = set(uniq)
        self._disk_busy(True, "Deleting %s…" % label)
        helpers = _emu_helpers()

        def _worker():
            from ..core import host_temp, wsl_disk
            wsl_freed = host_freed = emu_freed = 0
            err = None
            try:
                if wsl_paths:
                    wsl_freed = wsl_disk.delete(wsl_paths)
                if host_paths:
                    host_freed = host_temp.delete(host_paths)
                if emu_labels and helpers:
                    emu_freed = helpers[1](emu_labels, emu_sizes)
            except Exception as e:                      # noqa: BLE001
                err = str(e)
            self.ctx.loop.post(self._disk_after_clean, wsl_freed, host_freed,
                               emu_freed, deleted, err)

        threading.Thread(target=_worker, name="pad-shellx-diskclean",
                         daemon=True).start()
        return True

    @staticmethod
    def _adjust_usage(usage, freed):
        if not usage or not freed:
            return
        usage["used"] = max(0, usage["used"] - freed)
        usage["free"] = usage["free"] + freed
        usage["pct"] = (int(round(usage["used"] * 100 / usage["total"]))
                        if usage["total"] else 0)

    def _disk_after_clean(self, wsl_freed, host_freed, emu_freed, deleted,
                          err):
        d = self._disk
        if d is None:
            return
        if err:
            self._disk_busy(False, "")
            _mb().showerror("Delete failed", err)
            return
        d["entries"] = [e for e in d["entries"]
                        if (e["location"], e["path"]) not in deleted]
        self._adjust_usage(d["usage"][LOC_WSL], wsl_freed)
        self._adjust_usage(d["usage"][LOC_HOST], host_freed)
        self._adjust_usage(d["usage"][LOC_EMU], emu_freed)
        if d["vhdx"] and d["vhdx"].get("reclaimable") is not None:
            d["vhdx"]["reclaimable"] += wsl_freed
        self._disk_view(bars=self._bar_texts(), rows=self._disk_rows(),
                        reclaim_note=self._reclaim_text())
        self._disk_busy(False, "Freed %s."
                        % _fmt(wsl_freed + host_freed + emu_freed))

    # ------------------------------------------------------------------
    # reclaim (compact the .vhdx)
    # ------------------------------------------------------------------
    @rpc
    def disk_reclaim(self):
        d = self._disk
        if d is None or d["busy"]:
            return False
        from ..core.admin import is_admin
        if not is_admin():
            _mb().showwarning(
                "Administrator required",
                "Reclaiming space compacts the WSL virtual disk, which needs "
                "Administrator rights.\n\nClose the app, right-click it and "
                "choose “Run as administrator”, then reopen this window. "
                "(Cleaning up staging above does NOT need admin.)")
            return False
        if not _mb().askyesno(
                "Reclaim space to Windows",
                "This will shut down WSL and compact its virtual disk so freed "
                "space is returned to Windows.\n\n• Any other WSL work will be "
                "stopped.\n• It can take a few minutes.\n\nMake sure no "
                "extract or build is running, then continue?"):
            return False
        self._disk_busy(True, "Reclaiming…")

        def _worker():
            from ..core import wsl_disk
            try:
                reclaimed = wsl_disk.reclaim(progress=self._disk_progress)
                self.ctx.loop.post(self._disk_after_reclaim, reclaimed, None)
            except Exception as e:                      # noqa: BLE001
                self.ctx.loop.post(self._disk_after_reclaim, 0, str(e))

        threading.Thread(target=_worker, name="pad-shellx-reclaim",
                         daemon=True).start()
        return True

    def _disk_progress(self, msg):
        self.ctx.loop.post(lambda: self._disk_view(status=str(msg)))

    def _disk_after_reclaim(self, reclaimed, err):
        if self._disk is None:
            return
        if err:
            self._disk_busy(False, "")
            _mb().showerror("Reclaim failed", err)
            return
        _mb().showinfo(
            "Reclaimed",
            "Returned %s to Windows by compacting the WSL virtual disk."
            % _fmt(reclaimed))
        if self._disk is not None:
            self._disk["busy"] = False
            self.disk_refresh()

    # ------------------------------------------------------------------
    # resize (wsl --manage --resize)
    # ------------------------------------------------------------------
    @rpc
    def disk_resize_prepare(self):
        """Resize WSL disk…: the checks before the size prompt, and the
        prompt's numbers (or None when it cannot go ahead)."""
        from ..core import wsl_disk
        d = self._disk
        if d is None or d["busy"]:
            return None
        if not d["wsl_ok"]:
            _mb().showinfo("WSL not available",
                           "There's no WSL distro to resize.")
            return None
        ok, msg = wsl_disk.resize_supported()
        if not ok:
            _mb().showwarning("Resize not available", msg)
            return None
        u = d["usage"][LOC_WSL] or {}
        host_free = None
        try:
            host_free = wsl_disk.host_free_bytes()
        except Exception:                               # noqa: BLE001
            pass
        gib = 1024 ** 3
        total, used, free = u.get("total"), u.get("used"), u.get("free")
        cur_gib = int(round((total or 0) / gib)) or 1
        min_gib = max(1, int((used or 0) // gib) + 2)
        max_gib = None
        if total is not None and host_free is not None:
            max_gib = max(min_gib, int((total + host_free) // gib))
        info = "Current: %s max, %s used, %s free." % (
            _fmt(total), _fmt(used), _fmt(free))
        if host_free is not None:
            info += "\nWindows drive backing WSL has %s free." % _fmt(
                host_free)
        return {"cur": cur_gib, "min": min_gib, "max": max_gib,
                "info": info, "used": _fmt(used),
                "bounds": "Allowed: %d – %s GB." % (
                    min_gib, max_gib if max_gib is not None else "?")}

    @rpc
    def disk_resize(self, gib):
        d = self._disk
        if d is None or d["busy"]:
            return False
        new_bytes = int(gib) * 1024 ** 3
        if not _mb().askyesno(
                "Resize WSL disk",
                "Resize the WSL virtual disk to %s?\n\n• WSL will be shut down "
                "— close any running extract or build first.\n• It can take a "
                "few minutes.\n\nContinue?" % _fmt(new_bytes)):
            return False
        self._disk_busy(True, "Resizing…")

        def _worker():
            from ..core import wsl_disk
            try:
                usage = wsl_disk.resize_disk(new_bytes,
                                             progress=self._disk_progress)
                self.ctx.loop.post(self._disk_after_resize, usage, None)
            except Exception as e:                      # noqa: BLE001
                self.ctx.loop.post(self._disk_after_resize, None, str(e))

        threading.Thread(target=_worker, name="pad-shellx-resize",
                         daemon=True).start()
        return True

    def _disk_after_resize(self, usage, err):
        d = self._disk
        if d is None:
            return
        if err:
            self._disk_busy(False, "")
            _mb().showerror("Resize failed", err)
            return
        if usage:
            d["usage"][LOC_WSL] = usage
            self._disk_view(bars=self._bar_texts())
        _mb().showinfo("Resized", "WSL disk is now %s (%s free)." % (
            _fmt((usage or {}).get("total")),
            _fmt((usage or {}).get("free"))))
        if self._disk is not None:
            self._disk["busy"] = False
            self.disk_refresh()

    # ------------------------------------------------------------------
    @rpc
    def disk_close(self):
        """Close (or Esc): asks first while an operation runs; re-checks the
        gear badge afterwards.  Returns True when the window may close."""
        d = self._disk
        if d is not None and d["busy"]:
            if not _mb().askyesno(
                    "Operation in progress",
                    "A disk operation is still running. Close anyway?"):
                return False
        self._disk = None
        self._disk_scan_id += 1
        self.set(disk=None)
        self.start_disk_badge_check()
        return True
