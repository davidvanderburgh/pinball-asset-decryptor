"""The Animal shelters window and the paw chip (PAD-754; ``shellx`` service).

The app takes no money.  People who got something out of it are asked to
give to an animal shelter near them and then report the amount here, and
the top bar's paw chip shows what everyone has reported so far.  The money
side is ``core/donations.py``; this mixin is the glue: the cache and the
settings, the background fetch, the one-time prompt after a user's first
card write, and the ``shellx.donations_*`` calls the window makes.

State: ``shellx.donations`` is :func:`core.donations.view` (the chip's
words, the thermometer, the recent list, the form's remembered currency
and name).  Settings (``settings.json`` ``donations``): ``prompted`` (the
once-only window has been shown), ``currency`` and ``name`` (what the form
remembers), persisted through the ``on_donations_change`` callback.
"""

import logging
import os
import threading
import time
import urllib.error

from .. import __version__
from ..core import config, donations
from .rpc import RpcError, rpc

log = logging.getLogger(__name__)

#: the summary is re-read when the window opens or the cache is older than this
REFRESH_AFTER = 15 * 60


class DonationsMixin:
    """Mixed into ``ShellExtras``; ``_donations_init`` runs from its
    ``__init__`` once the window's callbacks are known."""

    def _donations_init(self):
        self._don_path = donations.cache_path(config.SETTINGS_FILE)
        self._don_cache = donations.load_cache(self._don_path)
        self._don_settings = dict(self.window.cb.get("initial_donations")
                                  or {})
        self._don_busy = False
        self._don_offline = False
        self._publish_donations()
        if self._donations_url() and not (
                os.environ.get("PAD_UI_NO_UPDATE_CHECK")
                and not os.environ.get("PAD_DONATIONS_URL")):
            self._donations_refresh(flush=True)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _donations_url():
        return config.DONATIONS_URL

    def _publish_donations(self):
        self.set(donations=donations.view(
            self._don_cache.get("summary"),
            self._don_cache.get("pending") or (),
            currency=self._don_settings.get("currency") or "USD",
            name=self._don_settings.get("name") or "",
            offline=self._don_offline,
            country=self._don_settings.get("country") or "",
            region=self._don_settings.get("region") or "",
            mine=self._don_cache.get("mine") or ()))

    def _save_donations_settings(self, **changes):
        self._don_settings.update(changes)
        fn = self.window.cb.get("on_donations_change")
        if fn is not None:
            fn(dict(self._don_settings))

    def _donations_refresh(self, flush=False):
        """Re-read the total off the UI loop; with ``flush``, send the
        entries kept from earlier first.  One at a time."""
        url = self._donations_url()
        if not url or self._don_busy:
            return False
        self._don_busy = True
        pending = list(self._don_cache.get("pending") or ()) if flush else []
        key = config.DONATIONS_APP_KEY

        def _run():
            remaining, summary, failed = pending, None, False
            try:
                if pending:
                    remaining, summary = donations.flush_pending(
                        url, key, pending)
                if summary is None:
                    summary = donations.fetch_summary(url)
            except (urllib.error.URLError, OSError, ValueError,
                    donations.DonationsError) as e:
                log.info("donations total not reachable: %s", e)
                failed = True
            self.ctx.loop.post(self._donations_refreshed, summary,
                               remaining if flush else None, failed)
        threading.Thread(target=_run, daemon=True,
                         name="pad-donations").start()
        return True

    def _donations_refreshed(self, summary, remaining, failed):
        self._don_busy = False
        self._don_offline = bool(failed)
        if summary is not None:
            self._don_cache["summary"] = summary
            self._don_cache["fetched_at"] = time.time()
        if remaining is not None:
            self._don_cache["pending"] = remaining
        donations.save_cache(self._don_path, self._don_cache)
        self._publish_donations()

    # -------------------------------------------------------------- calls
    @rpc
    def donations_open(self, auto=False):
        """The window opened: give it the view and refresh the total if the
        cache is stale (or has never been filled)."""
        age = time.time() - float(self._don_cache.get("fetched_at") or 0)
        if self._don_cache.get("summary") is None or age > REFRESH_AFTER \
                or self._don_cache.get("pending"):
            self._donations_refresh(flush=True)
        return self.get("donations")

    @rpc
    def donations_submit(self, amount, currency="USD", shelter="", name="",
                         show_name=True, country="", region=""):
        """Add one donation.  Bad input is an :class:`RpcError` with the
        words the form shows.  The send runs off the loop: reached, the
        fresh total is published and a toast says thanks; unreachable, the
        entry is kept and sent the next time the app can."""
        try:
            entry = donations.validate_entry(
                amount, currency, shelter, name, show_name,
                app_version=__version__, country=country, region=region)
        except ValueError as e:
            raise RpcError(str(e))
        self._save_donations_settings(currency=entry["currency"],
                                      name=entry["name"],
                                      country=entry["country"],
                                      region=entry["region"])
        url = self._donations_url()
        if not url:
            self._donations_keep(entry, "No donations service is configured.")
            return {"sent": False}
        key = config.DONATIONS_APP_KEY

        def _run():
            try:
                summary = donations.submit(url, key, entry)
            except donations.DonationsError as e:
                self.ctx.loop.post(self._donations_refused, str(e))
                return
            except (urllib.error.URLError, OSError, ValueError) as e:
                log.info("donation kept for later: %s", e)
                self.ctx.loop.post(self._donations_keep, entry, None)
                return
            self.ctx.loop.post(self._donations_sent, summary, entry)
        threading.Thread(target=_run, daemon=True,
                         name="pad-donation-send").start()
        return {"sent": True}

    def _donations_sent(self, summary, entry=None):
        self._don_offline = False
        self._don_cache["summary"] = summary
        self._don_cache["fetched_at"] = time.time()
        if entry is not None and summary.get("id"):
            # remember it as ours, with the token that lets us take it back
            mine = [m for m in self._don_cache.get("mine") or ()
                    if isinstance(m, dict)]
            mine.append({"id": summary["id"], "token": summary.get("token", ""),
                         "held": bool(summary.get("held")),
                         "at": time.time(), "entry": entry})
            self._don_cache["mine"] = mine[-10:]
        donations.save_cache(self._don_path, self._don_cache)
        self._publish_donations()
        if summary.get("held"):
            self.toast("Thank you. An entry that size is checked by hand "
                       "before it counts, so the total moves later.", "info")
        else:
            self.toast("Added to the total. Thank you.", "success")

    @rpc
    def donations_remove(self, key):
        """Take back one of this install's entries (the window's Yours list):
        a pending one is dropped here; a sent one is hidden by the service
        with the token it answered.  Returns the entry's fields so the form
        can be filled with them for a corrected go."""
        if str(key).startswith("pending:"):
            try:
                i = int(str(key).split(":", 1)[1])
                entry = self._don_cache["pending"].pop(i)
            except (ValueError, IndexError, KeyError):
                raise RpcError("That entry is already gone.")
            donations.save_cache(self._don_path, self._don_cache)
            self._publish_donations()
            return entry
        mine = [m for m in self._don_cache.get("mine") or ()
                if isinstance(m, dict)]
        hit = next((m for m in mine if m.get("id") == key), None)
        if hit is None:
            raise RpcError("That entry is already gone.")
        url = self._donations_url()
        key_app = config.DONATIONS_APP_KEY

        def _run():
            try:
                summary = donations.remove(url, key_app, hit["id"],
                                           hit.get("token", ""))
            except donations.DonationsError as e:
                # already hidden (David, or an earlier try): drop it here too
                log.info("donation %s not removable: %s", hit["id"], e)
                self.ctx.loop.post(self._donations_removed, hit, None)
                return
            except (urllib.error.URLError, OSError, ValueError) as e:
                log.info("donation %s could not be removed: %s", hit["id"], e)
                self.ctx.loop.post(
                    self.toast, "Couldn't reach the total just now. Try "
                    "Remove again in a moment.", "warning")
                return
            self.ctx.loop.post(self._donations_removed, hit, summary)
        threading.Thread(target=_run, daemon=True,
                         name="pad-donation-remove").start()
        return hit.get("entry") or {}

    def _donations_removed(self, hit, summary):
        self._don_cache["mine"] = [
            m for m in self._don_cache.get("mine") or ()
            if isinstance(m, dict) and m.get("id") != hit.get("id")]
        if summary is not None:
            self._don_offline = False
            self._don_cache["summary"] = summary
            self._don_cache["fetched_at"] = time.time()
        donations.save_cache(self._don_path, self._don_cache)
        self._publish_donations()
        self.toast("Taken back. Fix it and add it again.", "info")

    def _donations_refused(self, message):
        self.toast(message, "warning")

    def _donations_keep(self, entry, message):
        self._don_offline = True
        self._don_cache.setdefault("pending", []).append(entry)
        donations.save_cache(self._don_path, self._don_cache)
        self._publish_donations()
        self.toast(message or "Couldn't reach the total just now. Your entry "
                   "is kept and goes the next time the app can.", "warning")

    @rpc
    def donations_refresh(self):
        """The window's Refresh."""
        return self._donations_refresh(flush=True)

    # ------------------------------------------------------- the prompt
    def note_card_written(self):
        """A card write finished well (app.py ``_on_done``).  The first time
        on this install, open the window once, unasked: the moment the app
        has just saved someone money is the one time to ask.  Never again
        after that; the chip is always there."""
        if self._don_settings.get("prompted"):
            return False
        self._save_donations_settings(prompted=True)
        self._open_dialog("donations", auto=True)
        return True
