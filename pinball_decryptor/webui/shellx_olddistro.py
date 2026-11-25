"""Settings ▸ Manage disk space ▸ what the app left in the PC's previous
Linux (PAD-1599, core/old_distro.py).

A section of its own that appears only while there is something to give
back: the window's open starts that distro's scan on a thread (it may have
to start), and the section stays hidden when the scan finds nothing, finds
the app still at work there, or was answered before (one-time).  One press
removes what is listed and gives the disk file's space back to Windows.

State: ``shellx.disk.old`` (None = no section) and ``shellx.disk.old_checked``
(the look is over, for captures).
"""

import logging
import threading

from ..core import old_distro
from .rpc import rpc
from .shellx_common import fmt_binary as _fmt

log = logging.getLogger(__name__)

#: The rows the section lists: one per kind, largest first.
_KIND_LABEL = {
    "card": "Spike 2 emulator card cache",
    "rig": "Emulators' games, runs and Python",
    "staging": "Extract and build staging",
}


def view_of(found):
    """The section's view for :func:`old_distro.check`'s answer."""
    name = found["name"]
    if found.get("compact_only"):
        return {"name": name, "rows": [], "busy": False,
                "head": "Give back the space the app freed in %s" % name,
                "note": ("What the app left in %s has been removed, but its "
                         "disk file (%s on your Windows drive) has not "
                         "shrunk yet: that needs WSL shut down for a "
                         "minute, which waits until nothing runs in Linux. "
                         "It also happens by itself when you close the app."
                         % (name, _fmt(found["size"]))),
                "button": "Give the space back…", "status": "",
                "items": []}
    by = {}
    for it in found["items"]:
        by.setdefault(it["kind"], []).append(it)
    rows = []
    for kind, items in sorted(by.items(),
                              key=lambda kv: -sum(i["size"] for i in kv[1])):
        rows.append({"text": "%s  (%d item%s)" % (
            _KIND_LABEL.get(kind, kind), len(items),
            "" if len(items) == 1 else "s"),
            "size": _fmt(sum(i["size"] for i in items)),
            "tip": "\n".join(i["what"] for i in items)})
    return {"name": name, "busy": False, "rows": rows,
            "head": "Left behind in %s" % name,
            "note": ("The app now works in a Linux of its own. Before that it "
                     "worked in %s, and what it left there is never used "
                     "again: %s in all. Its disk file takes %s on your "
                     "Windows drive. Save states, settings and high scores "
                     "stay, as does everything of yours."
                     % (name, _fmt(found["total"]), _fmt(found["size"]))),
            "button": "Remove and give the space back…", "status": "",
            "items": [{"kind": i["kind"], "path": i["path"]}
                      for i in found["items"]]}


class OldDistroMixin:
    """Mixed into the ``shellx`` service beside :class:`DiskMixin`."""

    def _old_found(self):
        d = self._disk
        return d.get("old_found") if d else None

    def _old_view(self, **kw):
        d = self._disk
        if d is None:
            return
        old = d["view"].get("old")
        if old is None:
            return
        old = dict(old)
        old.update(kw)
        self._disk_view(old=old)

    def _old_start_check(self, allowed):
        """The window opened: look once, off the UI thread."""
        if not allowed:
            self._disk_view(old=None, old_checked=True)
            return
        self._disk_view(old=None, old_checked=False)
        disk = self._disk

        def _worker():
            try:
                found = old_distro.check()
            except Exception:                           # noqa: BLE001
                log.exception("looking at the previous Linux")
                found = None
            self.ctx.loop.post(self._old_checked, disk, found)

        threading.Thread(target=_worker, name="pad-shellx-olddistro",
                         daemon=True).start()

    def _old_checked(self, disk, found):
        if self._disk is None or self._disk is not disk:
            return
        self._disk["old_found"] = found
        self._disk_view(old=view_of(found) if found else None,
                        old_checked=True)

    @staticmethod
    def _old_confirm_text(found):
        if found.get("compact_only"):
            return ("This shuts WSL down for a minute or two and compacts "
                    "%s's disk file, so the space freed in it goes back to "
                    "Windows.\n\nNothing runs in Linux meanwhile; if "
                    "something does, it waits.\n\nContinue?" % found["name"])
        return ("This deletes what the app left in %s (%s):\n\n%s\n\n"
                "Save states, settings, high scores and everything of yours "
                "stay. Then WSL is shut down for a minute or two and %s's "
                "disk file is compacted, so the space goes back to Windows "
                "(if something runs in Linux, that part waits).\n\n"
                "Continue?"
                % (found["name"], _fmt(found["total"]),
                   "\n".join("• %s  (%s)" % (i["what"], _fmt(i["size"]))
                             for i in found["items"][:12])
                   + ("\n• …and %d more" % (len(found["items"]) - 12)
                      if len(found["items"]) > 12 else ""),
                   found["name"]))

    @rpc
    def old_distro_clean(self):
        """The section's button."""
        from .shellx_disk import _mb
        found = self._old_found()
        d = self._disk
        if not found or d is None or d["busy"]:
            return False
        if not _mb().askyesno(
                "Give back the space in %s" % found["name"],
                self._old_confirm_text(found)):
            return False
        self._disk_busy(True)
        self._old_view(busy=True, status="Removing…")

        def say(msg):
            self.ctx.loop.post(lambda: self._old_view(status=str(msg)))

        def _worker():
            res = {"freed": 0, "kept": [], "before": None, "after": None,
                   "owed": [], "err": None}
            try:
                if not found.get("compact_only"):
                    freed, _removed, kept = old_distro.remove(
                        found["name"], found["items"])
                    res.update(freed=freed, kept=kept)
                    say("Removed %s. Giving the space back to Windows…"
                        % _fmt(freed))
                try:
                    res["before"], res["after"] = old_distro.compact(
                        found, progress=say)
                except old_distro.Busy as b:
                    res["owed"] = list(b.args[0])
            except Exception as e:                      # noqa: BLE001
                log.exception("previous Linux clean-up")
                res["err"] = str(e)
            self.ctx.loop.post(self._old_after, found, res)

        threading.Thread(target=_worker, name="pad-shellx-oldclean",
                         daemon=True).start()
        return True

    def _old_after(self, found, res):
        if self._disk is None:
            return
        name = found["name"]
        self._disk["busy"] = False
        if res["err"]:
            self._old_view(busy=False, status=res["err"])
            self._disk_busy(False, "")
            return
        parts = []
        if not found.get("compact_only"):
            parts.append("Removed %s from %s." % (_fmt(res["freed"]), name))
            if res["kept"]:
                parts.append("Kept %d in use: %s."
                             % (len(res["kept"]), ", ".join(res["kept"])))
        if res["before"] is not None:
            parts.append("Its disk file went from %s to %s: %s back to "
                         "Windows." % (_fmt(res["before"]), _fmt(res["after"]),
                                       _fmt(max(0, res["before"]
                                               - res["after"]))))
            self._disk["old_found"] = None
            self._old_view(busy=False, rows=[], button="", head=(
                "Gave back the space in %s" % name), note="",
                status=" ".join(parts))
        else:
            parts.append("Its disk file shrinks once WSL is idle (%s): when "
                         "you close the app, or press the button again."
                         % "; ".join(res["owed"][:3]))
            owed = dict(found, items=[], total=0, compact_only=True)
            self._disk["old_found"] = owed
            v = view_of(owed)
            v["status"] = " ".join(parts)
            self._disk_view(old=v)
        self._disk_busy(False, " ".join(parts))
