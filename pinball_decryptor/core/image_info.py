"""Technical details about the loaded image, for the Image Info window.

Collects everything the app can cheaply know about an image into a list of
``(section_title, [(name, value), ...])`` sections: the file itself, what the
manufacturer's detector says about it, and any platform-specific details the
plugin's :meth:`Manufacturer.image_info` contributes (firmware version,
partitions, validation manifest, on-card asset counts, …).

Users work with multiple firmware versions and report bugs by forum post, so
the point is one place that answers "exactly what image is this?" —
:func:`as_text` renders the same sections as a copy-pasteable report (peanuts).

GUI-free on purpose (the collector runs on a worker thread and is unit-tested
without Tk); the Image Info window only renders what this returns.
"""

import os
import time


def human_size(n):
    """``1536`` -> ``"1.5 KB"`` (same rendering as the Partition Explorer)."""
    try:
        size = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return ("%d %s" % (int(size), unit) if unit == "B"
                    else "%.1f %s" % (size, unit))
        size /= 1024.0


def _size_cell(n):
    """Human size with the exact byte count alongside (bug reports compare
    images byte-for-byte)."""
    return "%s (%s bytes)" % (human_size(n), format(int(n), ","))


def _file_section(path):
    st = os.stat(path)
    return ("File", [
        ("Name", os.path.basename(path)),
        ("Location", os.path.dirname(path) or "."),
        ("Size", _size_cell(st.st_size)),
        ("Modified", time.strftime("%Y-%m-%d %H:%M",
                                   time.localtime(st.st_mtime))),
    ])


def _detection_section(mfr, game):
    rows = [("Manufacturer", mfr.display)]
    if game is None:
        rows.append(("Detected", "Not recognized by %s" % mfr.display))
        return ("Detection", rows)
    rows.append(("Game", game.display))
    if getattr(game, "notes", ""):
        rows.append(("Format", game.notes))
    if not getattr(game, "supported", True):
        rows.append(("Supported", "No — %s"
                     % (game.unsupported_reason or "not yet supported")))
    return ("Detection", rows)


def collect(mfr, path, assets_dir=None):
    """All known sections for *path* under manufacturer *mfr*.

    Returns ``[(section_title, [(name, value), ...]), ...]``.  Never raises
    for a probe-level failure: a section that can't be read is replaced by a
    one-row explanation so the rest of the report still renders.

    *assets_dir* is passed through to the plugin's ``image_info`` hook for
    the platforms whose metadata only exists in the extract output (BOF's
    update-version date); nothing here reads the folder itself.
    """
    sections = []
    try:
        sections.append(_file_section(path))
    except OSError as e:
        sections.append(("File", [("Error", str(e))]))
    if mfr is not None:
        try:
            game = mfr.detect(path)
        except Exception:
            game = None
        sections.append(_detection_section(mfr, game))
        # Platform details only for a file the detector actually claims — a
        # foreign image would otherwise get one plugin's headers over noise.
        if game is not None:
            try:
                sections.extend(
                    mfr.image_info(path, assets_dir=assets_dir) or [])
            except Exception as e:
                sections.append(
                    ("Details", [("Error", "Could not read: %s" % e)]))
    return sections


def as_text(sections, title="Image Info"):
    """Render *sections* as the plain-text report the Copy button emits."""
    lines = [title, "=" * len(title)]
    for section, rows in sections:
        lines.append("")
        lines.append(section)
        width = max((len(name) for name, _v in rows), default=0)
        for name, value in rows:
            lines.append("  %-*s  %s" % (width, name, value))
    return "\n".join(lines) + "\n"
