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

No address is asked for.  The app keeps the id the service answered each
report with, asks after them at startup (and when the window opens, when
the last ask is old) and, when one has been addressed in a release or
closed, shows a notice at the top (the ``report_answer`` banner) and the
developer's message under Your reports in the window.

State: ``shellx.report`` = ``{"available", "busy", "last", "picture",
"capture", "mine"}``.  Settings (``settings.json`` ``report``): ``name``
and ``hide_paths``, what the form remembers, through the
``on_report_change`` callback; the reports themselves in
``reports_cache.json`` beside settings.json.
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

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
           "Oct", "Nov", "Dec")


def _when(ts):
    try:
        t = time.localtime(float(ts))
    except (TypeError, ValueError, OverflowError):
        return ""
    return "%d %s %d" % (t.tm_mday, _MONTHS[t.tm_mon - 1], t.tm_year)


class ReportMixin:
    """Mixed into ``ShellExtras``; ``_report_init`` runs from its
    ``__init__`` once the window's callbacks are known."""

    def _report_init(self):
        self._rep_settings = dict(self.window.cb.get("initial_report") or {})
        self._rep_path = problem_report.cache_path(config.SETTINGS_FILE)
        self._rep_cache = problem_report.load_cache(self._rep_path)
        self._rep_picture = None        # {"name", "type", "data"}
        self._rep_busy = False
        self._rep_last = None
        self._rep_checking = False
        self._publish_report()
        # the notice, once the window has published its own first state
        # (a banner set during the services' construction is overwritten)
        self.ctx.loop.after_idle(self._report_show_news)
        if self._report_url() and not (
                os.environ.get("PAD_UI_NO_UPDATE_CHECK")
                and not os.environ.get("PAD_REPORTS_URL")):
            self._report_check_status()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _report_url():
        return config.REPORTS_URL

    def _report_mine_view(self):
        out = []
        for m in self._rep_cache.get("mine") or ():
            out.append({"id": m.get("id"), "title": m.get("title") or "",
                        "when": _when(m.get("at")),
                        "state": m.get("state") or "received",
                        "words": problem_report.state_words(m),
                        "message": m.get("message") or "",
                        "seen": m.get("seen", True)})
        return out

    def _publish_report(self):
        p = self._rep_picture
        self.set(report={
            "available": bool(self._report_url()),
            "busy": self._rep_busy,
            "last": self._rep_last,
            "picture": ({"name": p["name"], "kb": (len(p["data"]) + 512) // 1024}
                        if p else None),
            "capture": self._report_can_capture(),
            "mine": self._report_mine_view()})

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

    def _report_record(self, text, name, hide_paths):
        return {"app_version": __version__, "platform": sys.platform,
                "facts": self._report_facts(),
                "log": problem_report.log_tail(),
                "text": text or "", "name": name or "",
                "hide_paths": bool(hide_paths),
                "picture": self._rep_picture, "at": time.time()}

    # -------------------------------------------------------------- calls
    @rpc
    def report_open(self, prefill=""):
        """The window opened: the facts to show, the log's size, what the
        form remembers and the words an error box handed over.  An old
        ask after the app's own reports is repeated."""
        age = time.time() - float(self._rep_cache.get("checked_at") or 0)
        if age > problem_report.STATUS_AFTER:
            self._report_check_status()
        facts = self._report_facts()
        return {"facts": facts,
                "log_lines": len(problem_report.log_tail()),
                "name": self._rep_settings.get("name") or "",
                "hide_paths": bool(self._rep_settings.get("hide_paths", True)),
                "prefill": prefill or "",
                "picture": self.get("report", {}).get("picture"),
                "capture": self._report_can_capture()}

    @rpc
    def report_preview(self, text="", name="", hide_paths=True):
        """The record exactly as it would be sent."""
        report = self._report_record(text, name, hide_paths)
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
    def report_send(self, text="", name="", hide_paths=True):
        """Send the report.  Bad input is an :class:`RpcError` with the
        words the form shows.  The send runs off the loop: reached, the
        report joins Your reports and a toast says so; unreachable, the
        window is told and offers the file."""
        if self._rep_busy:
            raise RpcError("A report is already on its way.")
        report = self._report_record(text, name, hide_paths)
        try:
            problem_report.validate(report)
        except ValueError as e:
            raise RpcError(str(e))
        self._save_report_settings(name=report["name"],
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
            self.ctx.loop.post(self._report_sent, report, out)
        threading.Thread(target=_run, daemon=True,
                         name="pad-problem-report").start()
        return {"sent": True}

    def _report_sent(self, report, out):
        self._rep_busy = False
        self._rep_picture = None
        self._rep_last = {"ok": True, "id": str(out.get("id") or "")}
        if out.get("id"):
            problem_report.remember(self._rep_cache, report, out)
            problem_report.save_cache(self._rep_path, self._rep_cache)
        self._publish_report()
        self.toast("Report sent. Thank you.", "success")

    def _report_failed(self, message, offline):
        self._rep_busy = False
        self._rep_last = {"ok": False, "error": message, "offline": offline}
        self._publish_report()
        self.toast(message, "warning")

    @rpc
    def report_save(self, text="", name="", hide_paths=True):
        """The same bundle as a .zip the user picks a place for."""
        report = self._report_record(text, name, hide_paths)
        try:
            problem_report.validate(report)
        except ValueError as e:
            raise RpcError(str(e))
        self._save_report_settings(name=report["name"],
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

    # ---------------------------------------------------------- the answer
    def _report_check_status(self):
        """Ask the service after the app's own reports that have no last
        word yet, off the loop.  One at a time; nothing to ask, no call."""
        url = self._report_url()
        if not url or self._rep_checking:
            return False
        ids = [m["id"] for m in self._rep_cache.get("mine") or ()
               if not problem_report.answered(m)]
        if not ids:
            return False
        self._rep_checking = True
        key = config.REPORTS_APP_KEY

        def _run():
            rows = None
            try:
                rows = problem_report.fetch_status(url, key, ids)
            except (urllib.error.URLError, OSError, ValueError,
                    problem_report.ReportError) as e:
                log.info("report status not reachable: %s", e)
            self.ctx.loop.post(self._report_status_in, rows)
        threading.Thread(target=_run, daemon=True,
                         name="pad-report-status").start()
        return True

    def _report_status_in(self, rows):
        self._rep_checking = False
        if rows is None:
            return
        news = problem_report.apply_status(self._rep_cache, rows)
        self._rep_cache["checked_at"] = time.time()
        problem_report.save_cache(self._rep_path, self._rep_cache)
        self._publish_report()
        if news:
            self._report_show_news()

    def _report_show_news(self):
        """The notice at the top for every answered report the user has
        not seen yet: the release that addressed it, or that it closed."""
        news = [m for m in self._rep_cache.get("mine") or ()
                if m.get("seen") is False]
        if not news:
            self.window.set_banner("report_answer", None)
            return
        m = news[-1]
        title = m.get("title") or "your report"
        if m.get("state") == "released":
            text = "Your report \"%s\" is addressed in v%s." % (
                title, m.get("version") or "?")
        elif m.get("state") == "unknown":
            text = "Your report \"%s\" is no longer on record." % title
        else:
            text = "Your report \"%s\" was looked at and closed." % title
        if len(news) > 1:
            text += " (%d reports have news.)" % len(news)
        if m.get("message"):
            text += " " + m["message"]
        self.window.set_banner("report_answer", {
            "kind": "info", "text": text,
            "actions": [{"id": "view", "label": "Your reports",
                         "primary": True}]})

    def _report_banner_action(self, action):
        if action == "view":
            self._open_dialog("report")
            return True
        self.report_mine_seen()
        return True

    @rpc
    def report_mine_seen(self):
        """The user looked: the news is no longer new."""
        changed = False
        for m in self._rep_cache.get("mine") or ():
            if m.get("seen") is False:
                m["seen"] = True
                changed = True
        if changed:
            problem_report.save_cache(self._rep_path, self._rep_cache)
            self._publish_report()
        self.window.set_banner("report_answer", None)
        return True

    @rpc
    def report_refresh(self):
        """The window's own ask after the reports."""
        return self._report_check_status()
