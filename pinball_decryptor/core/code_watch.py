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
* one plain GET per page with the app's own User-Agent, so the site can see
  who reads it.

A manufacturer joins with :func:`register_source`.  Stern lists every
release on one page; JJP and BoF have a page per title (PAD-787), so theirs
come with *pages* and a check reads only the pages of the titles the owner
has a machine of.  The answers live in :func:`cache_file` beside
settings.json (wherever settings.json is at the time), not in settings: the
app owns settings and saves it on its own schedule, and a background check
must not race that.

``PAD_CODE_WATCH_URL`` points every source (every page of it) at another
page (the tests' and the screenshot rig's stub).  A server started for tests
or captures (``PAD_UI_NO_UPDATE_CHECK``) never reads the real page: only a
stub.
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
#: The most of a page read (Stern's is ~360 KB, JJP's ~320 KB).
MAX_BYTES = 4 * 1024 * 1024
ENV_URL = "PAD_CODE_WATCH_URL"

_sources = {}


def register_source(mfr_key, url, parse, pages=None, page_words=""):
    """*parse(text)* returns ``{release key: (a, b, c)}`` from a page.  *url*
    is the page a check reads (or, with *pages*, the hub a row links to when
    its title has no page of its own); *pages* maps a release key to the
    page that lists it.  *page_words* names the page in a sentence
    ("Stern's game-code page")."""
    _sources[mfr_key] = {"url": url, "parse": parse,
                         "pages": dict(pages or {}),
                         "words": page_words or "the game-code page"}


def cache_file():
    return os.path.join(os.path.dirname(config.SETTINGS_FILE), CACHE_NAME)


def allowed():
    """False in a server started for tests or captures, unless it was given
    a stub page: those never reach the manufacturer's site."""
    return bool(os.environ.get(ENV_URL)) or \
        not os.environ.get("PAD_UI_NO_UPDATE_CHECK")


def has_source(mfr_key):
    return mfr_key in _sources


def page_words(mfr_key):
    src = _sources.get(mfr_key)
    return src["words"] if src else "the game-code page"


def page_url(mfr_key, release_key=None):
    """The page a check reads for *release_key* and its row links to, or
    ``""``."""
    src = _sources.get(mfr_key)
    if src is None:
        return ""
    return os.environ.get(ENV_URL) or \
        src["pages"].get(release_key or "") or src["url"]


def _urls(mfr_key, keys):
    """The pages one check reads: the one page, or each of *keys*' pages
    (every page when *keys* is None)."""
    src = _sources[mfr_key]
    if not src["pages"]:
        return [page_url(mfr_key)]
    if keys is None:
        keys = list(src["pages"])
    return sorted({page_url(mfr_key, k) for k in keys})


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
    """``{"checked", "ok", "error", "latest": {key: [a, b, c]}, "read":
    [pages]}`` from the last read (``{}`` before the first)."""
    got = _load().get(mfr_key)
    return got if isinstance(got, dict) else {}


def due(mfr_key, now=None, keys=None):
    """True when the page has not been read in the last day (a few hours
    after a failed read), or a title in *keys* has a page the last check did
    not read (a machine added since)."""
    if mfr_key not in _sources:
        return False
    st = state(mfr_key)
    now = time.time() if now is None else now
    last = float(st.get("checked") or 0)
    wait = INTERVAL if st.get("ok") else RETRY
    if not last or now - last >= wait or now < last:
        return True
    if keys is not None and _sources[mfr_key]["pages"]:
        read = set(st.get("read") or [])
        return any(u not in read for u in _urls(mfr_key, keys))
    return False


def check(mfr_key, opener=None, now=None, keys=None):
    """Read the source's page (or the pages of *keys*) once and remember
    what they list; returns the new :func:`state`.  A failed read keeps the
    last good answer and records the error.  Call off the UI thread."""
    src = _sources.get(mfr_key)
    if src is None:
        return {}
    urls = _urls(mfr_key, keys)
    now = time.time() if now is None else now
    data = _load()
    prev = data.get(mfr_key) if isinstance(data.get(mfr_key), dict) else {}
    latest = dict(prev.get("latest") or {})
    errors, read = [], []
    for url in urls:
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": user_agent(), "Accept": "text/html"})
            with (opener or net.urlopen)(req, timeout=REQUEST_TIMEOUT) as resp:
                text = resp.read(MAX_BYTES).decode("utf-8", "replace")
            found = src["parse"](text)
            if not found:
                raise ValueError("the page lists no game code it can read")
            latest.update({k: list(v) for k, v in found.items()})
            read.append(url)
        except Exception as e:                            # noqa: BLE001
            errors.append(str(e) or e.__class__.__name__)
    entry = {"checked": now, "url": urls[0] if len(urls) == 1 else src["url"],
             "latest": latest, "read": read, "ok": not errors,
             "error": errors[0] if errors else ""}
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
