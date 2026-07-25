"""Project files — one JSON snapshot of every path + option for a game.

monkeybug bounces between several Led Zeppelin / Beatles versions at once and
had to re-check every path and checkbox each time he switched.  A project
file captures the whole working setup — manufacturer, the Extract/Write
paths, and the Extract options — so loading one file puts the app exactly
back on that version.

Format 2 (batch 19) makes the project *folder-scoped*: the project IS the
extraction folder, and the file lives inside it as a hidden anchor named
:data:`ANCHOR_NAME`.  The anchor knows its folder implicitly (its own
dirname), so the on-disk payload only needs what a folder can't tell us:
the manufacturer, the stock image it derives from (the one path that lives
OUTSIDE the project — shared, referenced), the Extract options, free-text
notes, an optional build-location override, and the archived flag.

Plain JSON so the files are self-describing and diff/share-friendly.
Format is versioned; unknown keys are ignored on load AND preserved on
:func:`update_anchor`, so newer files degrade gracefully in older apps and
older apps don't strip newer fields.
"""

import json
import os
import sys

EXTENSION = ".pinproj"
FILETYPES = [("Pinball Asset Decryptor project", "*" + EXTENSION),
             ("All files", "*.*")]

# The hidden anchor file at a project folder's root.  A bare dotfile (no
# stem) so it sorts with the folder's other hidden state
# (.staged_changes.json / .checksums.md5 / .orig) rather than reading as an
# asset; on Windows it additionally gets the hidden attribute.
ANCHOR_NAME = ".pinproj"

_KIND = "pinball-asset-decryptor-project"
FORMAT = 2

# The path fields a format-1 project carried, in apply order (write_output
# before write_original: setting the original fires the fill-empty-Output-
# Folder default, which must not clobber the project's explicit value — same
# rule as app._load_manufacturer_paths).  Format 2 still WRITES all five
# (derived from the folder + stock image) so a batch-18 app can read a
# format-2 file, and still APPLIES them in this order.
PATH_FIELDS = ("extract_input", "extract_output", "write_output",
               "write_original", "write_assets")


def save(path, *, manufacturer_key, paths, extract_options,
         write_filename="", app_version="", stock_image=None, notes="",
         build_dir="", archived=False, extra=None):
    """Write a project file.  Raises OSError on an unwritable path.

    *stock_image* defaults from *paths* (extract_input, else write_original)
    — format 2's single "the one shared file outside the project" field.
    *extra* is an optional dict of already-loaded fields to preserve
    verbatim (unknown keys from a newer app); explicit fields win over it.
    """
    paths = {k: (paths.get(k) or "") for k in PATH_FIELDS}
    if stock_image is None:
        stock_image = paths["extract_input"] or paths["write_original"]
    data = dict(extra or {})
    data.update({
        "kind": _KIND,
        "format": FORMAT,
        "saved_with": app_version,
        "manufacturer": manufacturer_key,
        "stock_image": stock_image or "",
        "paths": paths,
        "write_filename": write_filename or "",
        "extract_options": dict(extract_options or {}),
        "notes": notes or "",
        "build_dir": build_dir or "",
        "archived": bool(archived),
    })
    _write_maybe_hidden(path, data)


def load(path):
    """Read + validate a project file.

    Returns the parsed dict (format 1 or 2 — format-1 files get the
    format-2 fields defaulted, including ``stock_image`` derived from the
    old path fields).  Raises ValueError with a user-readable message when
    the file isn't a project file (wrong kind / unparseable / missing
    manufacturer), OSError when it can't be read at all."""
    with open(path, "r", encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as e:
            raise ValueError("Not a project file (unreadable JSON): %s" % e)
    if not isinstance(data, dict) or data.get("kind") != _KIND:
        raise ValueError(
            "Not a Pinball Asset Decryptor project file:\n%s" % path)
    if not data.get("manufacturer"):
        raise ValueError("The project file names no manufacturer:\n%s" % path)
    if not isinstance(data.get("paths"), dict):
        data["paths"] = {}
    if not isinstance(data.get("extract_options"), dict):
        data["extract_options"] = {}
    # Format-2 fields, defaulted for format-1 files (batch 18).
    if not isinstance(data.get("stock_image"), str) or not data["stock_image"]:
        data["stock_image"] = (data["paths"].get("extract_input")
                               or data["paths"].get("write_original") or "")
    for key, default in (("notes", ""), ("build_dir", "")):
        if not isinstance(data.get(key), str):
            data[key] = default
    data["archived"] = bool(data.get("archived"))
    return data


# ----------------------------------------------------------------------
# Folder anchors (format 2: the project IS the folder)
# ----------------------------------------------------------------------

def anchor_path(folder):
    return os.path.join(folder, ANCHOR_NAME)


def has_anchor(folder):
    """True when *folder* is a project (contains the hidden anchor)."""
    try:
        return bool(folder) and os.path.isfile(anchor_path(folder))
    except OSError:
        return False


def load_anchor(folder):
    """:func:`load` the folder's anchor.  Same exceptions as load()."""
    return load(anchor_path(folder))


def update_anchor(folder, **updates):
    """Read-modify-write the folder's anchor, preserving every key the
    current app doesn't know about.  Best-effort by design: anchors ride
    along on flows (extract, staging) that must never fail because a NAS
    hiccupped or the folder is read-only.  Returns True when written."""
    try:
        data = load_anchor(folder)
    except (OSError, ValueError):
        return False
    data.update(updates)
    try:
        _write_maybe_hidden(anchor_path(folder), data)
    except OSError:
        return False
    return True


def project_build_dir(folder, data=None):
    """The folder's build-output directory: the anchor's ``build_dir``
    override when set, else ``<folder>/build``.  *data* may pass an
    already-loaded anchor to save the re-read."""
    if data is None and has_anchor(folder):
        try:
            data = load_anchor(folder)
        except (OSError, ValueError):
            data = None
    override = (data or {}).get("build_dir") or ""
    return override or os.path.join(folder, "build")


def _write_maybe_hidden(path, data):
    """Dump *data* as JSON to *path*, keeping/handing it the Windows hidden
    attribute when the name is the dotfile anchor.

    TRAP: ``open(path, "w")`` on a FILE_ATTRIBUTE_HIDDEN file raises
    PermissionError on Windows (CreateFile w/ TRUNCATE_EXISTING rejects the
    attribute mismatch) — so an existing anchor is un-hidden first and
    re-hidden after."""
    hide = os.path.basename(path) == ANCHOR_NAME
    if hide and os.path.isfile(path):
        _set_hidden(path, False)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    if hide:
        _set_hidden(path, True)


def _set_hidden(path, hidden):
    """Set/clear FILE_ATTRIBUTE_HIDDEN (Windows; silent no-op elsewhere —
    the leading dot already hides it on macOS/Linux).  Best-effort."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        FILE_ATTRIBUTE_HIDDEN = 0x2
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == -1:
            return
        if hidden:
            attrs |= FILE_ATTRIBUTE_HIDDEN
        else:
            attrs &= ~FILE_ATTRIBUTE_HIDDEN
        ctypes.windll.kernel32.SetFileAttributesW(str(path), attrs)
    except Exception:
        pass
