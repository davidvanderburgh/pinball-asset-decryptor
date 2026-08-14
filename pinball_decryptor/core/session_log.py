"""Persistent rolling session log.

The GUI's log pane is per-process — closing the app (or updating in place,
which relaunches it) throws the text away, and a tester wanted to look back
at what an earlier session did.  Every line the pane shows is therefore also
appended here, to a plain-text file that survives restarts and updates:

    <settings dir>/logs/session.log

The file rolls by size: when it passes ``MAX_BYTES`` it shifts to
``session.log.1`` (older rolls shift to ``.2`` / ``.3``, the oldest is
dropped), and rolled files older than ``KEEP_DAYS`` are pruned at startup —
so the history is capped both ways and can never grow without bound.

Everything here is best-effort: a full disk, a locked file or a read-only
profile must never take the GUI's own log down with it, so every public
function swallows OSError.
"""

import os
import re
import time

from .config import SETTINGS_FILE

# Roll the live file past ~2 MB (months of normal use), keep 3 rolls
# (~8 MB ceiling), and prune rolls not touched in 60 days.
MAX_BYTES = 2_000_000
KEEP_ROLLS = 3
KEEP_DAYS = 60

# Test hook: the GUI test fixture points this at a per-test temp dir so
# suites never append to (or roll!) the developer's real history.
LOG_DIR_OVERRIDE = None

# Every session opens with this banner; previous_tail() splits the live
# file on the LAST one to separate earlier sessions from the current run.
BANNER_PREFIX = "===== Pinball Asset Decryptor v"

# ONE poisoned line is all it takes to freeze every later startup.  A Tk Text
# widget measures every character it holds, and a single 341,705-char line —
# 341,626 of them NUL, a truncate-extended hole in the emulator's guest log
# read back as one "line" (2026-08-09) — pegged the main loop inside
# Tk_MeasureChars for 60-90 s on EVERY launch of EVERY app version, because
# they all seed their pane from this one file.  So lines are cleaned at both
# ends: on the way in (append) and on the way out (previous_tail — the file
# may hold poison written by an older version, which is exactly how the
# installed build kept freezing after the dev tree was fixed).
MAX_LINE_CHARS = 4000
# Control chars minus tab and newline.  NUL is the one that actually
# happened; the rest (\r included — Tk renders it as a control glyph) are
# dropped on the same reasoning rather than waiting for their own incident.
_HOSTILE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def clean_line(text):
    """Strip control characters and clamp the length of one log line.

    The clamp says what it cut — a silently shortened line reads as the
    whole truth and sends whoever reads it down the wrong path."""
    text = _HOSTILE.sub("", text)
    if len(text) > MAX_LINE_CHARS:
        text = "%s … [+%d chars]" % (text[:MAX_LINE_CHARS],
                                     len(text) - MAX_LINE_CHARS)
    return text


def log_dir():
    return LOG_DIR_OVERRIDE or os.path.join(
        os.path.dirname(SETTINGS_FILE), "logs")


def log_path():
    return os.path.join(log_dir(), "session.log")


# ---------------------------------------------------------------------------
# Per-project mirror.
#
# The rolling file above is one history for the whole app, which is right for
# everything that happens before (or outside) a project: prerequisite checks,
# update checks, the picker, an extract that is still choosing its folder.  It
# is wrong for a tester who keeps several projects on the go: "the logs are not
# independent of each project but rather they are one large one. So if you are
# bouncing around projects, this could get muddy" (batch 37).  And with two
# copies of the app open on two projects, both write the same file, so the two
# runs interleave line by line.
#
# So every line is ALSO appended to a log inside the project folder itself,
# from the moment that folder becomes the one being worked on.  Same rolling
# rules, so a project on a NAS can't grow one without bound either.
# ---------------------------------------------------------------------------

#: Folder of the project currently being worked on, or None.
_project_dir = None

PROJECT_LOG_DIR = "logs"
PROJECT_LOG_NAME = "project.log"


def project_log_path(folder=None):
    """Path of *folder*'s own log (the active project's when omitted), or
    None when no project is open."""
    folder = folder if folder is not None else _project_dir
    if not folder:
        return None
    return os.path.join(folder, PROJECT_LOG_DIR, PROJECT_LOG_NAME)


def active_project():
    """The folder whose log is currently being mirrored to, or None."""
    return _project_dir


def set_project(folder, version="", label=""):
    """Point the per-project mirror at *folder* (None to stop mirroring).

    Returns True when the target actually changed.  Both logs get a banner
    naming the project, so the shared history stays readable when the user
    bounces between folders and the project's own log says where each run of
    it begins.
    """
    global _project_dir
    folder = (folder or "").strip() or None
    if folder:
        folder = os.path.normpath(folder)
        if not os.path.isdir(folder):
            folder = None
    if folder == _project_dir:
        return False
    _project_dir = folder
    if folder is None:
        return True
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    name = label or os.path.basename(folder) or folder
    _append_raw("\n----- Project: %s (%s) — %s -----\n"
                % (name, folder, stamp))
    _append_project_raw(
        "\n%s%s — %s opened %s =====\n"
        % (BANNER_PREFIX, version or "?", name, stamp))
    return True


def _append_project_raw(line):
    path = project_log_path()
    if not path:
        return
    # Never recreate a project folder that has gone (deleted, or a NAS that
    # dropped): makedirs below would happily rebuild the tree at a stale
    # mount point, which is worse than losing the mirror for those lines.
    if not os.path.isdir(_project_dir):
        return
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _roll_if_needed(path)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass                    # a NAS that went away must not break the GUI


def start_session(version):
    """Stamp a session-start banner (called once at app startup)."""
    _prune_old_rolls()
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    _append_raw(
        "\n%s%s — session started %s =====\n"
        % (BANNER_PREFIX, version, stamp))


def previous_tail(max_lines=None):
    """Every non-empty line from sessions BEFORE the current one —
    everything above the live file's final session banner.  The GUI seeds
    the log pane with these (dimmed, above a cut line) so the previous
    sessions' log survives a restart or an in-place update right where the
    user already looks.  Unbounded by default: the live file is already
    size-capped by the roll (MAX_BYTES), so "the whole thing" is at most a
    couple of MB and a partial cut-off would just read as confusing
    (David).  ``max_lines`` remains for callers that want a shorter tail.
    ``[]`` when there's no history (fresh install, or the file rolled)."""
    try:
        with open(log_path(), "r", encoding="utf-8",
                  errors="replace") as fh:
            lines = fh.read().splitlines()
    except OSError:
        return []
    last_banner = None
    for i, line in enumerate(lines):
        if line.startswith(BANNER_PREFIX):
            last_banner = i
    if not last_banner:            # no banner, or the file STARTS with ours
        return []
    # Clean BEFORE the empty filter: a line of pure NULs isn't "whitespace"
    # to str.strip(), so it would survive the filter and reach the widget.
    cleaned = (clean_line(ln) for ln in lines[:last_banner])
    prev = [ln for ln in cleaned if ln.strip()]
    return prev[-max_lines:] if max_lines else prev


def append(text, level="info"):
    """Mirror one GUI log line into the rolling file — and into the open
    project's own log, when there is one (see :func:`set_project`)."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prefix = "" if level in ("info", "ts") else "[%s] " % level.upper()
    line = "[%s] %s%s\n" % (stamp, prefix, clean_line(text))
    _append_raw(line)
    _append_project_raw(line)


def _append_raw(line):
    try:
        os.makedirs(log_dir(), exist_ok=True)
        _roll_if_needed()
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _roll_if_needed(path=None):
    path = path or log_path()
    try:
        if os.path.getsize(path) < MAX_BYTES:
            return
    except OSError:
        return                      # no live file yet — nothing to roll
    # Shift session.log -> .1 -> .2 -> .3 (the old .3 is dropped).
    for i in range(KEEP_ROLLS, 0, -1):
        older = "%s.%d" % (path, i)
        newer = path if i == 1 else "%s.%d" % (path, i - 1)
        try:
            if os.path.exists(older):
                os.remove(older)
            if os.path.exists(newer):
                os.rename(newer, older)
        except OSError:
            pass


def _prune_old_rolls():
    """Drop rolled files whose last write is older than KEEP_DAYS."""
    cutoff = time.time() - KEEP_DAYS * 86400
    for i in range(1, KEEP_ROLLS + 1):
        p = "%s.%d" % (log_path(), i)
        try:
            if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                os.remove(p)
        except OSError:
            pass
