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
  service cannot be reached, to attach by hand;
* the answer: no address is asked for.  The app keeps the id the service
  answered each report with (:func:`load_cache` / :func:`save_cache`,
  ``reports_cache.json`` beside settings.json), asks after them with
  :func:`fetch_status`, and tells the user in the app once the report's
  ticket shipped in a release or was closed (:func:`state_words`), with
  the developer's message when there is one;
* the board (PAD-914): every report on its way through the developer's
  queue, Received -> In the queue -> Being worked on -> Fix ready -> Done,
  with the ticket's number and how far through the work it is
  (:func:`stage_of`, :func:`board_entry`).  The developer's tracker pushes
  each report's stage to the service, and draws the very same board from
  the same script (``webui/static/js/report_board.js``) in the ticket, so
  what the user sees is what the developer sees.  An anonymous id made on
  this PC (:func:`install_id`) ties the app's reports together there;
* the question (PAD-972): when the developer needs something only the
  user has (a log, what they see), the tracker puts the report in the
  stage ``question`` with its words.  The board marks it "Needs your
  answer" (:func:`waiting`), and the user answers in the app with words
  and files (:func:`reply_file`, :func:`send_reply`), which the tracker
  collects from the service.

Nothing personal is gathered on its own: a name is what the user typed,
the log is the app's own log, and the user sees the whole record before
it goes.
"""

import base64
import io
import json
import os
import re
import secrets
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
#: this many of the app's own reports are remembered and asked after
KEEP_MINE = 20
#: the service is asked after the open ones this often in the background
#: while any is open (a question must reach a running app, PAD-972) ...
STATUS_AFTER = 15 * 60
#: ... and when the user opens the board or the Report a problem window,
#: when the last ask is older
BOARD_STATUS_AFTER = 10 * 60
#: an answer to the developer's question (tools/donations_worker's
#: REPLY_* limits): its words, its files, and every file's base64 together
MAX_REPLY = 20_000
REPLY_FILES = 5
REPLY_MAX_B64 = 1_500_000
#: ... which is this many bytes of files before base64
REPLY_MAX_BYTES = REPLY_MAX_B64 // 4 * 3
#: a log too big to go whole keeps at most this much of its end, which
#: leaves room for another file beside it
REPLY_TRIM_TO = 768 * 1024
#: a picture is shrunk until it fits this (the service keeps a row under
#: Cloudflare D1's 2 MB; base64 adds a third)
MAX_PICTURE_BYTES = 700_000
PICTURE_MAX_SIDE = 1600


class ReportError(Exception):
    """The service refused the report, with a message meant for the user."""


class QuestionClosed(ReportError):
    """The answer came too late: the report's question is no longer open
    (answered already, or the developer moved on)."""


# ---------------------------------------------------------------- redaction
# A Windows path, a UNC share, a home folder on Linux or a Mac, a mounted
# Windows drive under WSL and the usual removable-media roots.
_PATH = re.compile(
    r"(?<![\w])[A-Za-z]:[\\/][^\s\"'<>|]*"
    r"|\\\\[^\s\"'<>|]+"
    r"|/(?:home|Users|mnt|media|Volumes)/[^\s\"'<>|]*")


def redact(text, user=None, known=()):
    """*text* with every file path replaced by ``<path>`` and the user's
    account name by ``<user>``.  The name comes from the home folder when
    *user* is not given; a one-letter name is left alone (it would hit
    everywhere).  A path with a space in it cannot be told from the words
    after it, so the *known* paths (the card's, the project's) go whole
    first, with whatever runs on from them (PAD-929)."""
    if not text:
        return text or ""
    out = text
    for path in sorted({p for p in known if p and len(p) > 3},
                       key=len, reverse=True):
        for form in {path, path.replace("\\", "/")}:
            out = re.sub(re.escape(form.rstrip("\\/")) + r"[^\s\"'<>|]*",
                         "<path>", out, flags=re.IGNORECASE)
    out = _PATH.sub("<path>", out)
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


#: Visual Pinball's controller log (tools/spike2_emu/vpx/padcontroller.py's
#: LOG): a table's run, its DOF and its backglass are written there, never
#: to the session log, so a Visual Pinball report carried none of it (PAD-902)
MAX_VPX_LINES = 150
#: a report from another tab carries it too while a table ran this recently
VPX_RECENT_S = 2 * 3600
#: one line per switch edge and solenoid change: the rest drowns in them
_VPX_NOISE = re.compile(r"^\S+ (?:sol|sw) -?\d+ ->")


def vpx_log_path():
    return os.path.join(os.environ.get("TEMP") or os.environ.get("TMPDIR")
                        or "/tmp", "padcontroller.log")


def vpx_log_tail(tab="", max_lines=MAX_VPX_LINES, now=None):
    """The controller log's last *max_lines* lines, switch and solenoid
    edges left out, for a report from the Visual Pinball tab or one sent
    while a table ran in the last :data:`VPX_RECENT_S`.  ``[]`` otherwise,
    and when there is no log."""
    path = vpx_log_path()
    try:
        recent = (now or time.time()) - os.path.getmtime(path) < VPX_RECENT_S
        if tab != "Visual Pinball" and not recent:
            return []
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    kept = [ln[:1000] for ln in lines if ln.strip() and not _VPX_NOISE.match(ln)]
    return kept[-max_lines:]


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
    known = report.get("paths") or ()
    fix = ((lambda s: redact(s, known=known)) if hide
           else (lambda s: s or ""))
    at = report.get("at") or time.time()
    lines = ["Pinball Asset Decryptor problem report",
             "======================================",
             "Sent: %s (local time)" % time.strftime("%Y-%m-%d %H:%M",
                                                     time.localtime(at))]
    for label, value in report.get("facts") or ():
        if value in (None, ""):
            continue
        lines.append("%s: %s" % (label, fix(str(value))))
    if report.get("name"):
        lines.append("From: %s" % report["name"])
    if report.get("install"):
        lines.append("App id: %s (made on this PC, names nobody; it ties "
                     "this app's reports together)" % report["install"])
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
    vpx = report.get("vpx_log") or []
    if vpx:
        lines += ["", "Visual Pinball controller log (last %d lines)" % len(vpx),
                  "-" * 24]
        lines += [fix(ln) for ln in vpx]
    return "\n".join(lines) + "\n"


def payload(report):
    """What goes on the wire: the record, the title, the picture base64."""
    out = {"app_version": report.get("app_version") or "",
           "platform": report.get("platform") or sys.platform,
           "title": title_of(report),
           "body": as_text(report),
           "name": report.get("name") or ""}
    if report.get("install"):
        out["install"] = report["install"]
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


# ---------------------------------------------------------------- the answer
#: state -> what the window and the notice say
STATE_WORDS = {
    "received": "Received, not looked at yet",
    "filed": "Being looked at",
    "released": "Addressed in v%s",
    "closed": "Looked at and closed",
    "unknown": "No longer on record",
}


#: the board's columns, in order (report_board.js draws the same five)
STAGES = ("received", "queued", "working", "ready", "done")


#: the stage the tracker puts a report in while it waits on the user's
#: answer (PAD-972); the board draws it in Being worked on, with a look
#: of its own
QUESTION = "question"


def _int(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def waiting(entry):
    """True while *entry* has a question the user has not answered: the
    stage is ``question`` and no answer came after it."""
    return ((entry.get("stage") or "") == QUESTION and not answered(entry)
            and _int(entry.get("reply_at")) < _int(entry.get("question_at")))


def stage_of(entry):
    """Which column of the board *entry* is in.  The tracker's own stage
    when the service has one; a service that predates the board
    (PAD-914) has only the state, which says as much as it can.  A
    question waiting on the user is :data:`QUESTION`; one answered is
    back to being worked on."""
    state = entry.get("state") or "received"
    if answered(entry):
        return "done"
    stage = entry.get("stage") or ""
    if stage == QUESTION:
        return QUESTION if waiting(entry) else "working"
    if stage in STAGES and stage != "done":
        return stage
    return "queued" if state == "filed" else "received"


def board_entry(entry):
    """One report as the board draws it: the shape report_board.js reads,
    in the app and in the developer's tracker alike."""
    try:
        progress = int(entry.get("progress"))
    except (TypeError, ValueError):
        progress = -1
    return {"id": entry.get("id") or "", "title": entry.get("title") or "",
            "at": entry.get("at") or 0, "stage": stage_of(entry),
            "state": entry.get("state") or "received",
            "ticket": entry.get("ticket") or "",
            "progress": progress if 0 <= progress <= 100 else -1,
            "version": entry.get("version") or "",
            "message": entry.get("message") or "",
            "question": entry.get("question") or "",
            "waiting": waiting(entry),
            "answer_sent": bool(entry.get("answer_sent"))
            and not waiting(entry) and not answered(entry),
            "new": entry.get("seen") is False}


def state_words(entry):
    """One line for one of the app's own reports."""
    state = entry.get("state") or "received"
    words = STATE_WORDS.get(state, STATE_WORDS["received"])
    if state == "released":
        words = words % (entry.get("version") or "?")
    return words


def answered(entry):
    """True once the developer's side said the last word on it."""
    return (entry.get("state") or "") in ("released", "closed", "unknown")


def fetch_status(url, key, ids, timeout=TIMEOUT):
    """``{id: {"state", "version", "message", "answered_at", "stage",
    "ticket", "progress", "question", "question_at", "reply_at"}}`` for
    the app's own report *ids* (at most 20 a call).  From ``stage`` on
    they are the board's and the question's; an older service leaves them
    out (blank, -1 for no progress, 0 for no moment)."""
    ids = [i for i in ids if i][:20]
    if not url or not ids:
        return {}
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/report/status?ids=" + ",".join(ids),
        headers=_headers(**{"X-PAD-Key": key or ""}))
    with urlopen(req, timeout) as resp:
        out = _read_json(resp)
    if not out.get("ok"):
        raise ReportError(out.get("error") or "The service refused the ask.")
    rows = {}
    for r in out.get("rows") or ():
        if isinstance(r, dict) and r.get("id"):
            rows[r["id"]] = {"state": r.get("state") or "received",
                             "version": r.get("version") or "",
                             "message": r.get("message") or "",
                             "answered_at": r.get("answered_at") or 0,
                             "stage": r.get("stage") or "",
                             "ticket": r.get("ticket") or "",
                             "progress": _progress(r.get("progress")),
                             "question": str(r.get("question") or ""),
                             "question_at": _int(r.get("question_at")),
                             "reply_at": _int(r.get("reply_at"))}
    return rows


def _progress(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return -1
    return n if 0 <= n <= 100 else -1


def cache_path(settings_file):
    return os.path.join(os.path.dirname(settings_file), "reports_cache.json")


def load_cache(path):
    """``{"mine": [entries], "checked_at": float}``; a missing or broken
    file is an empty cache.  An entry: ``id, title, at, state, version,
    message, answered_at, seen``."""
    out = {"mine": [], "checked_at": 0.0, "install": ""}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    if isinstance(data.get("mine"), list):
        out["mine"] = [m for m in data["mine"]
                       if isinstance(m, dict) and m.get("id")][-KEEP_MINE:]
    try:
        out["checked_at"] = float(data.get("checked_at") or 0)
    except (TypeError, ValueError):
        pass
    if re.fullmatch(r"[0-9a-f]{16}", str(data.get("install") or "")):
        out["install"] = data["install"]
    return out


def install_id(cache):
    """This app's anonymous id, made the first time it is needed and kept
    in the cache: 16 random hex digits, nothing about the PC or the user.
    The developer's tracker groups the reports that carry it, so the
    ticket shows the whole board this app shows."""
    if not cache.get("install"):
        cache["install"] = secrets.token_hex(8)
    return cache["install"]


def save_cache(path, cache):
    """Never raises: a cache that cannot be written only loses the memory
    of a report, never the report."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        from .atomic_file import write_json_atomic
        write_json_atomic(path, cache)
    except OSError:
        pass


def remember(cache, report, answer):
    """Add the report the service just took to the cache's ``mine``."""
    cache.setdefault("mine", []).append({
        "id": str(answer.get("id") or ""), "title": title_of(report),
        "at": report.get("at") or time.time(), "state": "received",
        "version": "", "message": "", "answered_at": 0, "seen": True,
        "stage": "received", "ticket": "", "progress": -1})
    cache["mine"] = cache["mine"][-KEEP_MINE:]
    return cache


def apply_status(cache, rows):
    """Fold the service's answers into the cache.  Returns the entries
    whose news is NEW: just released or closed, or a question the user
    has not seen yet."""
    news = []
    for m in cache.get("mine") or ():
        r = rows.get(m.get("id"))
        if not r:
            continue
        was = m.get("state") or "received"
        asked_at = _int(m.get("question_at"))
        m["state"] = r["state"]
        m["version"] = r["version"]
        m["message"] = r["message"]
        m["answered_at"] = r["answered_at"]
        m["stage"] = r.get("stage") or ""
        m["ticket"] = r.get("ticket") or ""
        m["progress"] = r.get("progress", -1)
        m["question"] = r.get("question") or ""
        m["question_at"] = _int(r.get("question_at"))
        # an answer sent from here is kept as said until the service has
        # it too (its clock is the service's; ours only stood in)
        m["reply_at"] = max(_int(r.get("reply_at")),
                            _int(m.get("reply_at"))
                            if m.get("question_at") == asked_at else 0)
        if waiting(m) and m["question_at"] != asked_at:
            m["answer_sent"] = False
            m["seen"] = False
            news.append(m)
        elif answered(m) and not answered({"state": was}):
            m["seen"] = False
            news.append(m)
    return news


def note_answer_sent(cache, rid, now=None):
    """The service took the user's answer to *rid*'s question: the entry
    is no longer waiting (the service's own reply_at comes with the next
    ask) and its card says the answer went."""
    for m in cache.get("mine") or ():
        if m.get("id") == rid:
            m["reply_at"] = max(int(now or time.time()),
                                _int(m.get("question_at")))
            m["stage"] = "working"
            m["answer_sent"] = True
            return m
    return None


# ------------------------------------------------------------- the answer back
#: files the app reads as text, and so may trim to their tail to fit
_TEXT_EXT = (".log", ".txt", ".ini", ".cfg", ".xml", ".json", ".csv",
             ".vbs", ".md", ".yaml", ".yml")


def _looks_text(name, data):
    if os.path.splitext(name)[1].lower() in _TEXT_EXT:
        return True
    head = data[:4096]
    if b"\0" in head:
        return False
    try:
        head.decode("utf-8")
    except UnicodeDecodeError as e:
        return e.start > len(head) - 4          # cut mid-character at the end
    return True


def _kb(n):
    return "%d KB" % ((n + 1023) // 1024) if n < 1024 * 1024 \
        else "%.1f MB" % (n / (1024 * 1024))


def reply_file(path, room=REPLY_MAX_BYTES):
    """One file for an answer: ``{"name", "type", "data", "size",
    "trimmed"}``.  *room* is how many bytes are left for it.  A text file
    (a log) too big for that keeps its last lines, with a first line
    saying it was trimmed; anything else too big is a ``ValueError`` with
    the words the window shows."""
    import mimetypes
    name = os.path.basename(path) or "file"
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        raise ValueError("Couldn't read %s: %s" % (name, e.strerror or e))
    kind = mimetypes.guess_type(name)[0] or (
        "text/plain" if os.path.splitext(name)[1].lower() in _TEXT_EXT
        else "application/octet-stream")
    size = len(data)
    if size <= room:
        return {"name": name, "type": kind, "data": data, "size": size,
                "trimmed": False}
    if room < 4096 or not _looks_text(name, data):
        raise ValueError(
            "%s is %s, more than the %s an answer can still carry. Attach a "
            "smaller file, or a picture of the part that matters."
            % (name, _kb(size), _kb(max(0, room))))
    keep = min(room, REPLY_TRIM_TO)
    note = ("[The app trimmed this file to fit: the last %s of %s.]\n"
            % (_kb(keep - 200), _kb(size))).encode("utf-8")
    tail = data[-(keep - len(note) - 100):]
    cut = tail.find(b"\n")
    if 0 <= cut < 4096:
        tail = tail[cut + 1:]
    if kind == "application/octet-stream":
        kind = "text/plain"
    return {"name": name, "type": kind, "data": note + tail, "size": size,
            "trimmed": True}


def send_reply(url, key, rid, message, files, timeout=TIMEOUT):
    """Post the user's answer to *rid*'s question: *message* and *files*
    (:func:`reply_file` dicts).  :class:`QuestionClosed` when the question
    is no longer open (409), :class:`ReportError` for another refusal; a
    network failure is the urllib error."""
    if not url:
        raise ReportError("No report service is configured.")
    message = (message or "").strip()
    files = list(files or ())
    if not message and not files:
        raise ReportError("Write an answer or attach a file.")
    if len(message) > MAX_REPLY:
        raise ReportError("The answer is too long: keep it under %d "
                          "characters, or attach it as a file." % MAX_REPLY)
    if len(files) > REPLY_FILES:
        raise ReportError("At most %d files go with an answer." % REPLY_FILES)
    body = {"message": message,
            "files": [{"name": f["name"], "type": f.get("type") or "",
                       "b64": base64.b64encode(f["data"]).decode("ascii")}
                      for f in files]}
    if sum(len(f["b64"]) for f in body["files"]) > REPLY_MAX_B64:
        raise ReportError("The files are too big to send together.")
    req = urllib.request.Request(
        url.rstrip("/") + "/v1/report/%s/reply" % rid,
        data=json.dumps(body).encode("utf-8"), method="POST",
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
            if e.code == 409:
                raise QuestionClosed(
                    "This question is no longer open. Check now shows "
                    "where the report is.")
            if e.code == 404:
                msg = None                  # a service from before PAD-972
            raise ReportError(msg or "The service refused the answer.")
        raise
    if not out.get("ok"):
        raise ReportError(out.get("error") or "The service refused the answer.")
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
