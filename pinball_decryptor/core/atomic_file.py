"""Write a small state file so it is always the old text or the new one.

The project anchor and settings.json are saved every few minutes (PAD-541),
and the staging sidecar on every pick.  An in-place ``open(path, "w")``
truncates first, so a crash or a full disk half-way left a cut-off file
nothing could read: the folder stopped being a project, or every setting and
pick was gone (PAD-545).  Here the text goes to a temp file in the same
folder, is flushed to disk, then renamed over the old one.
"""

import json
import os
import time
import uuid

#: Tries at renaming the temp file over the old one (under a second).
_REPLACE_TRIES = 6


def write_json_atomic(path, data, **dump_kw):
    """``json.dump(data, indent=2, **dump_kw)`` to *path*, atomically."""
    dump_kw.setdefault("indent", 2)
    _write(path, lambda fh: json.dump(data, fh, **dump_kw))


def write_text_atomic(path, text):
    """*text* to *path* (UTF-8, the system's newlines), atomically."""
    _write(path, lambda fh: fh.write(text))


def _write(path, fill):
    """*fill* (a callable given the open text file) into *path*.

    A rename refused for a moment (an antivirus or indexer holding the file,
    a NAS) is retried; if it never lands the old in-place write is the
    fallback, so a folder that only allows that keeps saving.  Raises OSError
    when nothing could be written; the temp file never stays behind."""
    # Beside *path* (a rename cannot cross drives), named per writer, and
    # made like open() would (umask, not mkstemp's 0600) so a file shared
    # with other users keeps its permissions.
    tmp = "%s.%d.%s.tmp" % (path, os.getpid(), uuid.uuid4().hex[:8])
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                 | getattr(os, "O_BINARY", 0), 0o666)
    try:
        if os.name != "nt":            # Windows: only a read-only bit
            try:
                os.chmod(tmp, os.stat(path).st_mode & 0o7777)
            except OSError:
                pass
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fill(fh)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        for attempt in range(_REPLACE_TRIES):
            try:
                os.replace(tmp, path)
                return
            except OSError:
                if attempt + 1 < _REPLACE_TRIES:
                    time.sleep(0.05 * (attempt + 1))
        with open(path, "w", encoding="utf-8") as fh:
            fill(fh)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
