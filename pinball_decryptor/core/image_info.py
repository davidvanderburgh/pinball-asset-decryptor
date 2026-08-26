"""Technical details about the loaded image, for the Image Info window.

Collects everything the app can cheaply know about an image into a list of
``(section_title, [(name, value), ...])`` sections: the file itself, what the
manufacturer's detector says about it, and any platform-specific details the
plugin's :meth:`Manufacturer.image_info` contributes (firmware version,
partitions, validation manifest, on-card asset counts, …).

Users work with multiple firmware versions and report bugs by forum post, so
the point is one place that answers "exactly what image is this?" —
:func:`as_text` renders the same sections as a copy-pasteable report (a tester).

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


def group_rows(rows):
    """One section's rows split into its listed groups —
    ``[(head_row, [item_row, ...]), ...]``.

    A row with a name of its own is a head (``("Moved", "545:")``,
    ``("Version", "1.21.0 -> 1.22.0")``); the rows after it whose name is
    BLANK are the items listed under it, which is exactly how the Compare
    report writes a change list (``plugins.stern.compare._listed``).

    Splitting them out is what lets a renderer show the first N items of a
    4,000-entry group and keep the rest one click away, without the report
    itself having to guess how many rows the window can take — and without
    re-reading two cards when the user wants more of them.  A leading blank
    row (no head to belong to) becomes its own group rather than being
    dropped: the report is never edited on the way to the screen."""
    groups = []
    for row in rows:
        if row[0] or not groups:
            groups.append((row, []))
        else:
            groups[-1][1].append(row)
    return groups


def as_text(sections, title="Image Info"):
    """Render *sections* as the plain-text report the Copy button emits.

    A row is ``(name, value)`` or ``(name, value, ref)`` — the Compare report
    hangs an on-card file reference off its listed file rows (see
    ``Manufacturer.compare_images``).  Indexing rather than unpacking is what
    keeps the text report working for both.

    EVERY row is rendered, including the ones the window is currently showing
    only the first few of: a text report is scrollable and searchable in a way
    a tree is not, so Copy Report is the answer to "let me see all 3,968 of
    them" rather than a screenshot of the same truncation."""
    lines = [title, "=" * len(title)]
    for section, rows in sections:
        lines.append("")
        lines.append(section)
        width = max((len(r[0]) for r in rows), default=0)
        for row in rows:
            lines.append("  %-*s  %s" % (width, row[0], row[1]))
    return "\n".join(lines) + "\n"
