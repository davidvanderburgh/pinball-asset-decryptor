"""Report a problem from inside the app (PAD-780).

Every report used to start with the user pasting a Copy Report into
Discord or a forum and a round of "which build, which card, what does the
log say".  This module is the report that answers those questions before
they are asked: the app's version and system, the manufacturer and tab,
the card's fingerprint and the project's build history, the tail of the
session log, the user's own words and, when they add one, a picture.

Three parts, none of them touching the UI (the window is
``webui/shellx_report.py``):

* the record: :func:`as_text` renders the report exactly as it is sent,
  so the window can show it before anything leaves the machine, and
  :func:`redact` takes file paths and the user's name out of it when they
  ask for that;
* the picture: :func:`shrink_picture` turns any picture into a JPEG small
  enough for the wire;
* the wire: :func:`send` posts it to the app's service (the same
  Cloudflare Worker that keeps the donations tally, ``tools/donations_worker``),
  and :func:`save_zip` writes the same bundle to a file for when the
  service cannot be reached, to attach by hand.

Nothing personal is gathered on its own: a name and an address are what
the user typed, the log is the app's own log, and the user sees the whole
record before it goes.
"""

import base64
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile

from . import session_log
from .net import urlopen

#: Cloudflare's browser integrity check refuses Python's default
#: User-Agent (403, error 1010) in production, so every request to the
#: service names the app (PAD-754 learned this the hard way).
USER_AGENT = "Pinball-Asset-Decryptor-Report"
TIMEOUT = 30
#: the session log's tail that goes with the report
MAX_LOG_LINES = 300
#: ... capped in bytes too: a line can be 4,000 characters (session_log)
MAX_LOG_CHARS = 200_000
#: the user's own words
MAX_TEXT = 4000
MAX_NAME = 80
MAX_EMAIL = 120
#: a picture is shrunk until it fits this (the service keeps a row under
#: Cloudflare D1's 2 MB; base64 adds a third)
MAX_PICTURE_BYTES = 700_000
PICTURE_MAX_SIDE = 1600


class ReportError(Exception):
    """The service refused the report, with a message meant for the user."""


# ---------------------------------------------------------------- redaction
# A Windows path, a UNC share, a home folder on Linux or a Mac, a mounted
# Windows drive under WSL and the usual removable-media roots.
_PATH = re.compile(
    r"(?<![\w])[A-Za-z]:[\\/][^\s\"'<>|]*"
    r"|\\\\[^\s\"'<>|]+"
    r"|/(?:home|Users|mnt|media|Volumes)/[^\s\"'<>|]*")


def redact(text, user=None):
    """*text* with every file path replaced by ``<path>`` and the user's
    account name by ``<user>``.  The name comes from the home folder when
    *user* is not given; a one-letter name is left alone (it would hit
    everywhere)."""
    if not text:
        return text or ""
    out = _PATH.sub("<path>", text)
    if user is None:
        user = os.path.basename(os.path.expanduser("~").rstrip("\\/"))
    if user and len(user) > 1:
        out = re.sub(re.escape(user), "<user>", out, flags=re.IGNORECASE)
    return out


# ------------------------------------------------------------------- the log
def log_tail(max_lines=MAX_LOG_LINES):
    """The last *max_lines* lines of the app's session log (this session's
    first; earlier sessions fill the rest when this one is short), cleaned
    the way the log pane cleans them.  ``[]`` when there is no log."""
    try:
        with open(session_log.log_path(), "r", encoding="utf-8",
                  errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    cleaned = [session_log.clean_line(ln) for ln in lines]
    tail = [ln for ln in cleaned if ln.strip()][-max_lines:]
    total = 0
    kept = []
    for ln in reversed(tail):
        total += len(ln) + 1
        if total > MAX_LOG_CHARS:
            break
        kept.append(ln)
    kept.reverse()
    return kept


# --------------------------------------------------------------- the picture
def shrink_picture(source):
    """``(jpeg_bytes, "image/jpeg")`` for *source* (a path or bytes),
    scaled to at most :data:`PICTURE_MAX_SIDE` on a side and recompressed
    until it is under :data:`MAX_PICTURE_BYTES`.  ``ValueError`` when it is
    not a picture."""
    try:
        from PIL import Image
    except ImportError as e:                           # pragma: no cover
        raise ValueError("Pictures need Pillow, which this copy of the app "
                         "does not have.") from e
    try:
        im = Image.open(io.BytesIO(source) if isinstance(source, (bytes,
                                                                   bytearray))
                        else source)
        im.load()
    except Exception as e:                              # noqa: BLE001
        raise ValueError("That file is not a picture the app can read.") \
            from e
    if im.mode not in ("RGB", "L"):
        im = im.convert("RGB")
    side = PICTURE_MAX_SIDE
    quality = 85
    while True:
        work = im.copy()
        work.thumbnail((side, side))
        buf = io.BytesIO()
        work.save(buf, "JPEG", quality=quality, optimize=True)
        data = buf.getvalue()
        if len(data) <= MAX_PICTURE_BYTES or (side <= 400 and quality <= 40):
            return data, "image/jpeg"
        if quality > 55:
            quality -= 15
        else:
            side = int(side * 0.75)
            quality = 70


# ---------------------------------------------------------------- the record
def _clean(text, limit):
    return " ".join(str(text or "").split())[:limit]


def validate(report):
    """Bound the user's fields in place and say what is missing.  The
    words are the ones the window shows."""
    text = (report.get("text") or "").strip()
    if len(text) < 10:
        raise ValueError("Say what happened, in a sentence or two.")
    report["text"] = text[:MAX_TEXT]
    report["name"] = _clean(report.get("name"), MAX_NAME)
    email = _clean(report.get("email"), MAX_EMAIL)
    if email and ("@" not in email or " " in email or "." not in
                  email.split("@")[-1]):
        raise ValueError("That doesn't look like an email address. Leave "
                         "it empty if you'd rather not give one.")
    report["email"] = email
    return report


def title_of(report):
    """The first line of what the user wrote, as the service and the
    tracker name the report."""
    first = (report.get("text") or "").strip().split("\n")[0]
    first = " ".join(first.split())
    return (first[:77] + "…") if len(first) > 80 else first


def as_text(report):
    """The whole record as plain text: what the user sees in the window's
    preview and exactly what the service stores.  ``hide_paths`` redacts
    the facts and the log; the user's own words are never changed."""
    hide = bool(report.get("hide_paths"))
    fix = redact if hide else (lambda s: s or "")
    at = report.get("at") or time.time()
    lines = ["Pinball Asset Decryptor problem report",
             "======================================",
             "Sent: %s (local time)" % time.strftime("%Y-%m-%d %H:%M",
                                                     time.localtime(at))]
    for label, value in report.get("facts") or ():
        if value in (None, ""):
            continue
        lines.append("%s: %s" % (label, fix(str(value))))
    who = report.get("name") or ""
    if report.get("email"):
        who = ("%s <%s>" % (who, report["email"])).strip()
    if who:
        lines.append("From: %s" % who)
    if hide:
        lines.append("File paths and the account name were left out at "
                     "the user's request.")
    if report.get("picture"):
        p = report["picture"]
        lines.append("Picture: %s (%s, %d KB)" % (
            p.get("name") or "picture", p.get("type") or "image",
            (len(p.get("data") or b"") + 512) // 1024))
    lines += ["", "What happened", "-------------",
              report.get("text") or "", ""]
    log = report.get("log") or []
    lines += ["Log (last %d lines)" % len(log), "-" * 24]
    lines += [fix(ln) for ln in log]
    return "\n".join(lines) + "\n"


def payload(report):
    """What goes on the wire: the record, the title, the picture base64."""
    out = {"app_version": report.get("app_version") or "",
           "platform": report.get("platform") or sys.platform,
           "title": title_of(report),
           "body": as_text(report),
           "name": report.get("name") or "",
           "email": report.get("email") or ""}
    p = report.get("picture")
    if p and p.get("data"):
        out["picture_type"] = p.get("type") or "image/jpeg"
        out["picture_b64"] = base64.b64encode(p["data"]).decode("ascii")
    return out


# ------------------------------------------------------------------ the wire
def _headers(**extra):
    h = {"Accept": "application/json", "User-Agent": USER_AGENT}
    h.update(extra)
    return h


def _read_json(resp):
    raw = resp.read()
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as e:
        raise ValueError("the service answered something that is not "
                         "JSON") from e


def send(url, key, report, timeout=TIMEOUT):
    """Post *report*.  Returns the service's answer (``{"ok": True, "id":
    ...}``).  A refusal (4xx with words) is :class:`ReportError`; a network
    failure is the urllib error, so the caller can offer the file instead."""
    if not url:
        raise ReportError("No report service is configured.")
    body = json.dumps(payload(report)).encode("utf-8")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/report", data=body, method="POST",
        headers=_headers(**{"Content-Type": "application/json",
                            "X-PAD-Key": key or ""}))
    try:
        with urlopen(req, timeout) as resp:
            out = _read_json(resp)
    except urllib.error.HTTPError as e:
        if 400 <= e.code < 500:
            try:
                msg = _read_json(e).get("error")
            except Exception:                           # noqa: BLE001
                msg = None
            raise ReportError(msg or "The service refused the report.")
        raise
    if not out.get("ok"):
        raise ReportError(out.get("error") or "The service refused the report.")
    return out


# ------------------------------------------------------------------ the file
def default_zip_name(at=None):
    return time.strftime("pad-problem-report-%Y%m%d-%H%M.zip",
                         time.localtime(at or time.time()))


def save_zip(report, path):
    """The same bundle as a .zip beside the user: ``report.txt`` and the
    picture, for a Discord post or a mail when the service is out of
    reach.  Returns *path*."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("report.txt", as_text(report))
        p = report.get("picture")
        if p and p.get("data"):
            ext = ".jpg" if (p.get("type") or "").endswith("jpeg") else ".png"
            z.writestr("picture" + ext, p["data"])
    return path
