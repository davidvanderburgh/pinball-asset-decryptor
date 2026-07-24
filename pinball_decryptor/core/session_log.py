"""Persistent rolling session log.

The GUI's log pane is per-process — closing the app (or updating in place,
which relaunches it) throws the text away, and monkeybug wanted to look back
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


def log_dir():
    return LOG_DIR_OVERRIDE or os.path.join(
        os.path.dirname(SETTINGS_FILE), "logs")


def log_path():
    return os.path.join(log_dir(), "session.log")


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
    prev = [ln for ln in lines[:last_banner] if ln.strip()]
    return prev[-max_lines:] if max_lines else prev


def append(text, level="info"):
    """Mirror one GUI log line into the rolling file."""
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    prefix = "" if level in ("info", "ts") else "[%s] " % level.upper()
    _append_raw("[%s] %s%s\n" % (stamp, prefix, text))


def _append_raw(line):
    try:
        os.makedirs(log_dir(), exist_ok=True)
        _roll_if_needed()
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        pass


def _roll_if_needed():
    path = log_path()
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
