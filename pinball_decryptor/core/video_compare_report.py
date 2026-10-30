"""PAD-812: the Video tab's compare report, a CSV with a row for every clip the
project puts in a slot's place - each replacement, each random clip (PAD-446)
and each mode's row of a shared clip (PAD-444) - beside the game's own clip it
stands in for: length to the hundredth of a second, the difference, the length
it will have on the card after Write, resolution, frame rate, frames, codec,
audio and size.

Tk-free and UI-free: the tab gathers :class:`Entry` items (cheap, on its loop)
and :func:`write` probes the files and writes the CSV (off the loop: one
ffprobe per file, memoised in :func:`core.video.detect_video_info`)."""

import csv
import os
from dataclasses import dataclass
from typing import Optional

from .video import detect_video_info

HEADER = [
    "Slot", "Played in", "What", "Stock clip", "Replacement file",
    "Stock length (s)", "Replacement length (s)", "Difference (s)",
    "Length after Write (s)", "Stock resolution", "Replacement resolution",
    "Stock fps", "Replacement fps", "Stock frames", "Replacement frames",
    "Stock codec", "Replacement codec", "Stock audio", "Replacement audio",
    "Stock size (MB)", "Replacement size (MB)", "Notes",
]

#: how the length after Write is decided (the Video tab's Length choice)
AFTER_STOCK = "stock"         # trimmed / padded to the stock clip's length
AFTER_OWN = "own"             # kept at the replacement's own length
# anything else: a float, the typed length in seconds


@dataclass
class Entry:
    """One clip the project plays in a slot's place."""
    slot: str                         # the row's rel path
    what: str                         # "Replacement", "Random clip 2 of 3", ...
    stock_rel: str                    # the game's clip it stands in for
    stock_path: str                   # that clip's pristine file
    file: str                         # the clip played instead ("" = none yet)
    after: object = AFTER_OWN         # AFTER_STOCK / AFTER_OWN / seconds
    played_in: str = ""               # the modes that play the slot
    stock_info: Optional[object] = None  # a probe the tab already holds
    asis: bool = False                # copied onto the card as it is (no conversion)


def _secs(v):
    return "%.2f" % v if v and v > 0 else ""


def _res(info):
    if info is not None and info.width and info.height:
        return "%dx%d" % (info.width, info.height)
    return ""


def _fps(info):
    if info is None or not info.fps:
        return ""
    return ("%.3f" % info.fps).rstrip("0").rstrip(".")


def _frames(info):
    if info is None:
        return ""
    if info.nframes:
        return str(int(info.nframes))
    if info.fps and info.duration:
        return str(int(round(info.fps * info.duration)))
    return ""


def _audio(info):
    if info is None:
        return ""
    return info.audio_summary() or "none"


def _mb(path):
    try:
        return "%.2f" % (os.path.getsize(path) / 1e6)
    except OSError:
        return ""


def _probe(path):
    if not path or not os.path.isfile(path):
        return None
    try:
        return detect_video_info(path)
    except Exception:                                   # noqa: BLE001 - a row without it
        return None


def row(entry, probe=_probe):
    """*entry* as a CSV row (HEADER's columns)."""
    stock = entry.stock_info if entry.stock_info is not None else probe(entry.stock_path)
    rep = probe(entry.file) if entry.file else None
    s_len = stock.duration if stock is not None else 0.0
    r_len = rep.duration if rep is not None else 0.0
    notes = []
    diff = ""
    if s_len > 0 and r_len > 0:
        d = round(r_len, 2) - round(s_len, 2)
        diff = "%+.2f" % d if abs(d) >= 0.005 else "0.00"
    after = ""
    if isinstance(entry.after, (int, float)) and not isinstance(entry.after, bool) \
            and entry.after > 0:
        after = _secs(float(entry.after))
        notes.append("Length set to %s s for this clip" % after)
    elif entry.after == AFTER_STOCK:
        after = _secs(s_len)
        if diff and diff != "0.00":
            notes.append("%s on Write to the stock length" % (
                "cut" if r_len > s_len else "padded"))
    elif entry.file:
        after = _secs(r_len)
    if not entry.file:
        notes.append("no replacement: plays the game's own clip")
    elif not os.path.isfile(entry.file):
        notes.append("replacement file not found")
    elif rep is None:
        notes.append("replacement could not be read (is ffmpeg installed?)")
    if stock is None:
        notes.append("stock clip could not be read")
    if entry.asis and entry.file:
        notes.append("used as it is (no conversion)")
    elif stock is not None and rep is not None:
        if _res(stock) and _res(rep) and _res(stock) != _res(rep):
            notes.append("scaled to %s on Write" % _res(stock))
        if _fps(stock) and _fps(rep) and _fps(stock) != _fps(rep):
            notes.append("converted to %s fps on Write" % _fps(stock))
    return [
        entry.slot, entry.played_in, entry.what, entry.stock_rel, entry.file,
        _secs(s_len), _secs(r_len), diff, after,
        _res(stock), _res(rep), _fps(stock), _fps(rep),
        _frames(stock), _frames(rep),
        stock.vcodec if stock is not None else "",
        rep.vcodec if rep is not None else "",
        _audio(stock), _audio(rep) if entry.file else "",
        _mb(entry.stock_path), _mb(entry.file) if entry.file else "",
        "; ".join(notes),
    ]


def write(path, entries, probe=_probe, cancel=None):
    """Probe every entry's files and write the report to *path*. Returns the
    number of rows written; raises OSError when the file can't be written."""
    rows = []
    for e in entries:
        if cancel is not None and cancel():
            break
        rows.append(row(e, probe))
    tmp = path + ".part"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    os.replace(tmp, path)
    return len(rows)
