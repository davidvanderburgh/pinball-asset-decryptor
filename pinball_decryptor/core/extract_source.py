"""Records which source image an extract came from, so the GUI can warn
when the underlying image is swapped/reverted *after* assets were extracted.

The "Original Track / Image / Text" names the Replace tabs show come from the
files in the extract *output* folder, not from the source ``.raw``/``.img``.
If a user reverts the source image on disk (e.g. overwrites it with a fresh
copy of the same name) and re-opens the app, the previously-extracted assets
folder is unchanged, so the app keeps showing the old (modified) state — there
is nothing that ties those assets back to the now-changed image.

This module drops a tiny sidecar (:data:`SIDE_CAR`) into the extract output
folder recording the source image's path + ``(size, mtime)`` at extract time.
:func:`stale_source_message` re-checks that signature with a single ``stat``
(no multi-GB read) and returns a human warning when it no longer matches.
"""

import json
import os
from typing import Optional

# Sidecar file written at the root of every extract output folder.  Dotfile so
# the audio/video/image slot scanners (which skip dot-entries) ignore it.
SIDE_CAR = ".extract_source.json"


def _signature(input_path: str) -> Optional[dict]:
    try:
        st = os.stat(input_path)
    except OSError:
        return None
    return {
        "input_path": os.path.abspath(input_path),
        "input_name": os.path.basename(input_path),
        "size": st.st_size,
        # Whole seconds — avoids float-jitter false positives across
        # filesystems with differing mtime precision.
        "mtime": int(st.st_mtime),
    }


def write_extract_source(output_dir: str, input_path: str) -> None:
    """Record *input_path*'s identity into ``output_dir``/:data:`SIDE_CAR`.

    Best-effort: silently no-ops if *input_path* isn't a regular file (e.g. a
    Direct-SSD ``\\\\.\\PHYSICALDRIVE`` device) or the folder isn't writable.
    """
    if not output_dir or not os.path.isdir(output_dir):
        return
    if not input_path or not os.path.isfile(input_path):
        return
    sig = _signature(input_path)
    if sig is None:
        return
    try:
        with open(os.path.join(output_dir, SIDE_CAR), "w", encoding="utf-8") as f:
            json.dump(sig, f, indent=2)
    except OSError:
        pass


def stale_source_message(assets_dir: str) -> Optional[str]:
    """Return a warning string if the source image recorded for *assets_dir*
    has changed on disk since the extract, else ``None``.

    Returns ``None`` (no warning) when there's no sidecar — older extracts and
    non-file inputs simply opt out — or when the recorded source is missing or
    still matches.  Cheap: one ``stat`` of the source, no large reads.
    """
    if not assets_dir:
        return None
    try:
        with open(os.path.join(assets_dir, SIDE_CAR), encoding="utf-8") as f:
            recorded = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(recorded, dict):
        return None
    path = recorded.get("input_path")
    if not path or not os.path.isfile(path):
        # Source moved/deleted — can't prove it's stale, so stay quiet rather
        # than nag about a path the user may have intentionally relocated.
        return None
    current = _signature(path)
    if current is None:
        return None
    if (current["size"] == recorded.get("size")
            and current["mtime"] == recorded.get("mtime")):
        return None
    name = recorded.get("input_name") or os.path.basename(path)
    return (
        f"The source image “{name}” has changed on disk since these "
        "assets were extracted. The original-track names and replacements "
        "shown may not match the current image — re-run Extract to refresh."
    )
