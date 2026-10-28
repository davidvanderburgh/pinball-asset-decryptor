"""The Report a problem window (PAD-780; ``shellx`` service).

The top bar's Report a problem button, the gear menu's entry and the link
on every error box open one window: what happened in the user's words,
the facts the developer always asks for next (version, system, card,
project history, the log's tail), an optional picture, a preview of the
whole record, and Send or Save as a file.  The record itself is
``core/problem_report.py``; this mixin is the glue: gathering the facts
off the window, the picture (a file, or a shot of the app's own window),
the send off the UI loop, and the fallback to a .zip when the service is
out of reach.

State: ``shellx.report`` = ``{"available", "busy", "last", "picture"}``.
Settings (``settings.json`` ``report``): ``name`` and ``email``, what the
form remembers, through the ``on_report_change`` callback.
"""

import logging
import os
import platform
import sys
import threading
import time
import urllib.error

from .. import __version__
from ..core import config, lineage, problem_report
from .rpc import RpcError, rpc

log = logging.getLogger(__name__)


class ReportMixin:
    """Mixed into ``ShellExtras``; ``_report_init`` runs from its
    ``__init__`` once the window's callbacks are known."""

    def _report_init(self):
        self._rep_settings = dict(self.window.cb.get("initial_report") or {})
        self._rep_picture = None        # {"name", "type", "data"}
        self._rep_busy = False
        self._rep_last = None
        self._publish_report()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _report_url():
        return config.REPORTS_URL

    def _publish_report(self):
        p = self._rep_picture
        self.set(report={
            "available": bool(self._report_url()),
            "busy": self._rep_busy,
            "last": self._rep_last,
            "picture": ({"name": p["name"], "kb": (len(p["data"]) + 512) // 1024}
                        if p else None),
            "capture": self._report_can_capture()})

    def _save_report_settings(self, **changes):
        self._rep_settings.update(changes)
        fn = self.window.cb.get("on_report_change")
        if fn is not None:
            fn(dict(self._rep_settings))

    def _report_can_capture(self):
        host = getattr(self.ctx, "host", None)
        return bool(sys.platform in ("win32", "darwin")
                    and host is not None and getattr(host, "window", None))

    def _report_facts(self):
        """The facts as ``[label, value]`` pairs, in the order the record
        shows them.  Everything here is already on the window; nothing
        opens a card."""
        facts = [["App", "v%s" % __version__],
                 ["System", "%s (%s), Python %s" % (
                     platform.platform(), sys.platform,
                     platform.python_version())]]
        mfr = getattr(self.window, "current_mfr", None)
        if mfr is not None:
            era = getattr(mfr, "current_era", "") or ""
            facts.append(["Manufacturer", mfr.display + (
                " (%s)" % era if era else "")])
        tab = ""
        try:
            tab = self.window.current_tab_key()
        except Exception:                               # noqa: BLE001
            pass
        if tab:
            facts.append(["Tab", tab])
        card = ""
        var = self._var_or_none("extract_input_var")
        if var is not None:
            card = (var.get() or "").strip()
        if card:
            words = card
            pr = None
            try:
                pr = lineage.card_print(card)
            except Exception:                           # noqa: BLE001
                pr = None
            if pr and pr.get("print"):
                words += "  print %s" % pr["print"]
                if pr.get("label"):
                    words += "  (%s%s)" % (
                        "official " if pr.get("official") else "",
                        pr["label"])
            facts.append(["Card", words])
        folder = ""
        var = self._var_or_none("write_assets_var")
        if var is not None:
            folder = (var.get() or "").strip()
        if folder:
            facts.append(["Project", folder])
            lin = lineage.read_lineage(folder)
            if lin:
                line, history = lineage.describe(lin)
                if line:
                    facts.append(["Build", line])
                for h in history[-6:]:
                    facts.append(["History", h])
        return facts

    def _report_record(self, text, name, email, hide_paths):
        report = {"app_version": __version__, "platform": sys.platform,
                  "facts": self._report_facts(),
                  "log": problem_report.log_tail(),
                  "text": text or "", "name": name or "",
                  "email": email or "", "hide_paths": bool(hide_paths),
                  "picture": self._rep_picture, "at": time.time()}
        return report

    # -------------------------------------------------------------- calls
    @rpc
    def report_open(self, prefill=""):
        """The window opened: the facts to show, the log's size, what the
        form remembers and the words an error box handed over."""
        facts = self._report_facts()
        return {"facts": facts,
                "log_lines": len(problem_report.log_tail()),
                "name": self._rep_settings.get("name") or "",
                "email": self._rep_settings.get("email") or "",
                "hide_paths": bool(self._rep_settings.get("hide_paths", True)),
                "prefill": prefill or "",
                "picture": self.get("report", {}).get("picture"),
                "capture": self._report_can_capture()}

    @rpc
    def report_preview(self, text="", name="", email="", hide_paths=True):
        """The record exactly as it would be sent."""
        report = self._report_record(text, name, email, hide_paths)
        return {"text": problem_report.as_text(report)}

    @rpc
    def report_picture(self, mode="pick"):
        """Add a picture to the report: ``pick`` a file, ``clear`` it."""
        if mode == "clear":
            self._rep_picture = None
            self._publish_report()
            return {"picture": None}
        path = self.window.ask_open(
            "report_picture", "Add a picture to the report",
            filetypes=[("Pictures", "*.png *.jpg *.jpeg *.gif *.webp *.bmp"),
                       ("All files", "*.*")])
        if not path:
            return {"picture": self.get("report", {}).get("picture")}
        try:
            data, kind = problem_report.shrink_picture(path)
        except ValueError as e:
            raise RpcError(str(e))
        self._rep_picture = {"name": os.path.basename(path), "type": kind,
                             "data": data}
        self._publish_report()
        return {"picture": self.get("report", {}).get("picture")}

    @rpc(loop=False)
    def report_capture(self):
        """A shot of the app's own window, taken a moment after the window
        hid its own dialog (the page unmounts it first).  Off the loop so
        the wait does not freeze the app."""
        host = getattr(self.ctx, "host", None)
        win = getattr(host, "window", None) if host is not None else None
        if win is None:
            raise RpcError("Couldn't take a picture of the window. Add a "
                           "file instead.")
        time.sleep(0.4)
        try:
            from PIL import ImageGrab
            x, y, w, h = int(win.x), int(win.y), int(win.width), int(win.height)
            if sys.platform == "win32":
                im = ImageGrab.grab(bbox=(x, y, x + w, y + h), all_screens=True)
            else:
                im = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            import io
            buf = io.BytesIO()
            im.save(buf, "PNG")
            data, kind = problem_report.shrink_picture(buf.getvalue())
        except Exception as e:                          # noqa: BLE001
            log.info("window capture failed: %s", e)
            raise RpcError("Couldn't take a picture of the window. Add a "
                           "file instead.")
        self._rep_picture = {"name": "the app window", "type": kind,
                             "data": data}
        self.ctx.loop.post(self._publish_report)
        return {"picture": {"name": "the app window",
                            "kb": (len(data) + 512) // 1024}}

    @rpc
    def report_send(self, text="", name="", email="", hide_paths=True):
        """Send the report.  Bad input is an :class:`RpcError` with the
        words the form shows.  The send runs off the loop: reached, a
        toast says so and the picture is cleared; unreachable, the window
        is told and offers the file."""
        if self._rep_busy:
            raise RpcError("A report is already on its way.")
        report = self._report_record(text, name, email, hide_paths)
        try:
            problem_report.validate(report)
        except ValueError as e:
            raise RpcError(str(e))
        self._save_report_settings(name=report["name"], email=report["email"],
                                   hide_paths=bool(hide_paths))
        url = self._report_url()
        if not url:
            raise RpcError("No report service is configured. Save the "
                           "report as a file instead.")
        self._rep_busy = True
        self._rep_last = None
        self._publish_report()
        key = config.REPORTS_APP_KEY

        def _run():
            try:
                out = problem_report.send(url, key, report)
            except problem_report.ReportError as e:
                self.ctx.loop.post(self._report_failed, str(e), False)
                return
            except (urllib.error.URLError, OSError, ValueError) as e:
                log.info("problem report not sent: %s", e)
                self.ctx.loop.post(
                    self._report_failed,
                    "The report service can't be reached right now. Save "
                    "the report as a file and attach it to a message "
                    "instead.", True)
                return
            self.ctx.loop.post(self._report_sent, out)
        threading.Thread(target=_run, daemon=True,
                         name="pad-problem-report").start()
        return {"sent": True}

    def _report_sent(self, out):
        self._rep_busy = False
        self._rep_picture = None
        self._rep_last = {"ok": True, "id": str(out.get("id") or "")}
        self._publish_report()
        self.toast("Report sent. Thank you.", "success")

    def _report_failed(self, message, offline):
        self._rep_busy = False
        self._rep_last = {"ok": False, "error": message, "offline": offline}
        self._publish_report()
        self.toast(message, "warning")

    @rpc
    def report_save(self, text="", name="", email="", hide_paths=True):
        """The same bundle as a .zip the user picks a place for."""
        report = self._report_record(text, name, email, hide_paths)
        try:
            problem_report.validate(report)
        except ValueError as e:
            raise RpcError(str(e))
        self._save_report_settings(name=report["name"], email=report["email"],
                                   hide_paths=bool(hide_paths))
        path = self.window.ask_save(
            "report_zip", "Save the report",
            initialfile=problem_report.default_zip_name(report["at"]),
            filetypes=[("Zip files", "*.zip")], defaultextension=".zip")
        if not path:
            return {"path": ""}
        try:
            problem_report.save_zip(report, path)
        except OSError as e:
            raise RpcError("Couldn't write the file: %s" % e)
        self.toast("Report saved: %s" % os.path.basename(path), "success")
        return {"path": path}
