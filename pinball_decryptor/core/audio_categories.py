"""Best-effort audio-slot categories for the Replace Audio "Type" filter.

Four buckets cover what the naming pipelines can tell apart (monkeybug's
"working on callouts, hide everything else"):

* ``music``    — jukebox/bank tracks: ``music_cat``-stem decodes, files the
                 transcriber isolation-tagged " - music", and AcoustID-titled
                 rows from ``music_titles.csv``.
* ``sfx``      — effects the game's own Sound Test menu names ("SE FX ...").
* ``callouts`` — speech: rows ``callouts.csv`` classified as speech, plus any
                 other user/transcript-labelled file.
* ``other``    — everything left (short unnamed effects, non-speech beds).

Everything is derived after the fact from filenames plus the two CSV
sidecars, so it works on any already-extracted folder — no re-extract needed.
Folders with no recognisable naming (other manufacturers, or a Stern extract
before any Auto-name pass) mostly classify ``other``; the GUI hides the
filter when it would be useless.
"""

import csv
import os
import re

MUSIC, SFX, CALLOUTS, OTHER = "music", "sfx", "callouts", "other"

_DUR_PREFIX_RE = re.compile(r"^\d+m\d+s\d+ - ", re.IGNORECASE)
_DECODE_RE = re.compile(
    r"^(?P<stem>idx\d+|music_cat\d+_\d+)(?: - (?P<label>.+))?$",
    re.IGNORECASE)


def _load_callouts(assets_dir):
    """``{rel: classification}`` from callouts.csv ('' folder = root)."""
    path = os.path.join(assets_dir, "callouts.csv")
    out = {}
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                folder = (row.get("folder") or "").strip()
                fname = (row.get("file") or "").strip()
                kind = (row.get("classification") or "").strip().lower()
                if fname and kind:
                    rel = (folder + "/" + fname) if folder else fname
                    out[rel] = kind
    except (OSError, ValueError, KeyError, csv.Error):
        return {}
    return out


def _load_music_titles(assets_dir):
    """Relative paths music_titles.csv confidently titled (nonempty title)."""
    path = os.path.join(assets_dir, "music_titles.csv")
    out = set()
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                rel = (row.get("relative_path") or "").strip()
                if rel and (row.get("title") or "").strip():
                    out.add(rel)
    except (OSError, ValueError, KeyError, csv.Error):
        return set()
    return out


def classify(assets_dir, rel_paths):
    """``{rel: category}`` for every path in *rel_paths*.

    Precedence: bank/menu identity from the filename (music_cat stem, "SE FX"
    label) beats the CSVs — monkeybug's pre-fix Led Zeppelin extract has SFX
    rows inside music_titles.csv, and a later user rename orphans a CSV row —
    then CSV classifications, then the label heuristics."""
    callouts = _load_callouts(assets_dir)
    titled = _load_music_titles(assets_dir)
    out = {}
    for rel in rel_paths:
        out[rel] = _classify_one(rel, callouts, titled)
    return out


def _classify_one(rel, callouts, titled):
    base = rel.rpartition("/")[2]
    stem = os.path.splitext(base)[0]
    m = _DECODE_RE.match(_DUR_PREFIX_RE.sub("", stem))
    label = (m.group("label") or "").strip() if m else ""
    if m and m.group("stem").lower().startswith("music_cat"):
        return MUSIC
    if label:
        low = label.lower()
        if low.startswith("se fx"):
            return SFX
        if low == "music" or low.startswith("music - "):
            return MUSIC
    kind = callouts.get(rel)
    if kind == "speech":
        return CALLOUTS
    if kind == "music":
        return MUSIC
    if kind == "non-speech":
        return OTHER
    if rel in titled:
        return MUSIC
    if label:
        return CALLOUTS          # a transcript or the user's own name
    return OTHER
