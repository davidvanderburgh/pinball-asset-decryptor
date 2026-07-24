"""Project files — one JSON snapshot of every path + option for a game.

monkeybug bounces between several Led Zeppelin / Beatles versions at once and
had to re-check every path and checkbox each time he switched.  A project
file captures the whole working setup — manufacturer, the Extract/Write
paths, and the Extract options — so loading one file puts the app exactly
back on that version.

Plain JSON with a ``.pinproj`` extension so the files are self-describing
and diff/share-friendly.  Format is versioned; unknown keys are ignored on
load so newer files degrade gracefully in older apps.
"""

import json
import os

EXTENSION = ".pinproj"
FILETYPES = [("Pinball Asset Decryptor project", "*" + EXTENSION),
             ("All files", "*.*")]

_KIND = "pinball-asset-decryptor-project"
FORMAT = 1

# The path fields a project carries, in apply order (write_output before
# write_original: setting the original fires the fill-empty-Output-Folder
# default, which must not clobber the project's explicit value — same rule
# as app._load_manufacturer_paths).
PATH_FIELDS = ("extract_input", "extract_output", "write_output",
               "write_original", "write_assets")


def save(path, *, manufacturer_key, paths, extract_options,
         write_filename="", app_version=""):
    """Write a project file.  Raises OSError on an unwritable path."""
    data = {
        "kind": _KIND,
        "format": FORMAT,
        "saved_with": app_version,
        "manufacturer": manufacturer_key,
        "paths": {k: (paths.get(k) or "") for k in PATH_FIELDS},
        "write_filename": write_filename or "",
        "extract_options": dict(extract_options or {}),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


def load(path):
    """Read + validate a project file.

    Returns the parsed dict.  Raises ValueError with a user-readable message
    when the file isn't a project file (wrong kind / unparseable / missing
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
    return data
