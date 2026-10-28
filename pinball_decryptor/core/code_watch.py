"""The game-code watcher behind My machines (PAD-783): once a day, read a
manufacturer's public code-update page and remember the newest build of each
release it lists, so a machine's row can say "1.17 is out" with a link.

Rules (the ticket's, and the shape of :mod:`.updater`'s own check):

* link only: the page is READ, never a download on it.  The app fetches no
  stock image or update, ever; the row links to the page and the owner
  clicks through;
* once a day per manufacturer (a failed read tries again after a few hours),
  only while the owner has a machine of that make, and never when they have
  switched the check off;
* one plain GET with the app's own User-Agent, so the site can see who reads it.

A manufacturer joins with :func:`register_source` (Stern Spike 2 today; JJP
and BoF take the same shape).  The answers live in :func:`cache_file` beside
settings.json (wherever settings.json is at the time), not in settings: the app owns settings and saves it on its own
schedule, and a background check must not race that.

``PAD_CODE_WATCH_URL`` points every source at another page (the tests' and
the screenshot rig's stub).  A server started for tests or captures
(``PAD_UI_NO_UPDATE_CHECK``) never reads the real page: only a stub.
"""

import json
import os
import time
import urllib.request

from . import config, net

CACHE_NAME = "code_watch.json"
#: Seconds between two reads of one page.
INTERVAL = 24 * 3600
#: Seconds before a read that failed is tried again.
RETRY = 3 * 3600
REQUEST_TIMEOUT = 15
#: The most of a page read (Stern's is ~360 KB).
MAX_BYTES = 4 * 1024 * 1024
ENV_URL = "PAD_CODE_WATCH_URL"

_sources = {}


def register_source(mfr_key, url, parse):
    """*parse(text)* returns ``{release key: (a, b, c)}`` from the page at
    *url*."""
    _sources[mfr_key] = (url, parse)


def cache_file():
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), CACHE_NAME)


def allowed():
    """False in a server started for tests or captures, unless it was given
    a stub page: those never reach the manufacturer's site."""
    return bool(os.environ.get(ENV_URL)) or         not os.environ.get("PAD_UI_NO_UPDATE_CHECK")


def has_source(mfr_key):
    return mfr_key in _sources


def page_url(mfr_key):
    """The page a check reads and a row links to, or ``""``."""
    src = _sources.get(mfr_key)
    if src is None:
        return ""
    return os.environ.get(ENV_URL) or src[0]


def user_agent():
    from .. import __version__
    return "Pinball-Asset-Decryptor/%s (game-code check, once a day)" % (
        __version__)


def _load():
    try:
        with open(cache_file(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(data):
    try:
        path = cache_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def state(mfr_key):
    """``{"checked", "ok", "error", "latest": {key: [a, b, c]}}`` from the
    last read (``{}`` before the first)."""
    got = _load().get(mfr_key)
    return got if isinstance(got, dict) else {}


def due(mfr_key, now=None):
    """True when the page has not been read in the last day (a few hours
    after a failed read)."""
    if mfr_key not in _sources:
        return False
    st = state(mfr_key)
    now = time.time() if now is None else now
    last = float(st.get("checked") or 0)
    wait = INTERVAL if st.get("ok") else RETRY
    return not last or now - last >= wait or now < last


def check(mfr_key, opener=None, now=None):
    """Read the page once and remember what it lists; returns the new
    :func:`state`.  A failed read keeps the last good answer and records
    the error.  Call off the UI thread."""
    url_parse = _sources.get(mfr_key)
    if url_parse is None:
        return {}
    url, parse = page_url(mfr_key), url_parse[1]
    now = time.time() if now is None else now
    data = _load()
    prev = data.get(mfr_key) if isinstance(data.get(mfr_key), dict) else {}
    entry = {"checked": now, "url": url,
             "latest": dict(prev.get("latest") or {})}
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": user_agent(), "Accept": "text/html"})
        with (opener or net.urlopen)(req, timeout=REQUEST_TIMEOUT) as resp:
            text = resp.read(MAX_BYTES).decode("utf-8", "replace")
        found = parse(text)
        if not found:
            raise ValueError("the page lists no game code it can read")
        entry.update(ok=True, error="",
                     latest={k: list(v) for k, v in found.items()})
    except Exception as e:                                # noqa: BLE001
        entry.update(ok=False, error=str(e) or e.__class__.__name__)
    data[mfr_key] = entry
    _save(data)
    return entry


def newest(mfr_key, release_key):
    """The newest build of *release_key* the last read saw, as a tuple, or
    ``None``."""
    v = (state(mfr_key).get("latest") or {}).get(release_key)
    try:
        return tuple(int(x) for x in v) if v else None
    except (TypeError, ValueError):
        return None
