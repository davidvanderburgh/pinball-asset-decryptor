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

# The Music filter is duration-aware on top of the name/CSV categories: any
# track at least this long is music to a listener, whatever the game calls
# it.  Led Zeppelin proved the need — it has NO music banks; its mode songs
# are ordinary cat-0 sounds the Sound Test names "SE FX SEQ ..." (David's
# 1.22.0 extract: every song classified sfx, the Music filter showed
# nothing).  Same threshold the transcribe/music-ID pipelines use.
MUSIC_MIN_SECONDS = 20.0

_DUR_PREFIX_RE = re.compile(r"^(\d+)m(\d+)s(\d+) - ", re.IGNORECASE)
_DECODE_RE = re.compile(
    r"^(?P<stem>idx\d+|music_cat\d+_\d+)(?: - (?P<label>.+))?$",
    re.IGNORECASE)


def name_duration_seconds(basename):
    """Play length parsed from a Length-prefix name ("01m22s235 - ..."),
    or None.  Instant duration for prefixed extracts — no header read."""
    m = _DUR_PREFIX_RE.match(basename)
    if not m:
        return None
    return int(m.group(1)) * 60 + int(m.group(2)) + int(m.group(3)) / 1000.0


def matches_filter(category, duration, type_key):
    """Does a slot with *category* and play *duration* (seconds, 0/None when
    unknown) belong under the Type filter *type_key*?

    Music is category OR length: long tracks count even when the game's own
    Sound Test calls them effects (a Led Zeppelin song is "SE FX ZEPPELIN
    AWARD" to the game), so a long SFX shows under both Music and Sound FX.
    Speech never lands in Music, and long tracks leave Other so the leftover
    bucket stays short unnamed effects."""
    if not type_key:
        return True
    long_enough = (duration or 0) >= MUSIC_MIN_SECONDS
    if type_key == MUSIC:
        return category == MUSIC or (category != CALLOUTS and long_enough)
    if type_key == OTHER:
        return category == OTHER and not long_enough
    return category == type_key


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

    Precedence: the user's own remembered category (a right-click rename
    records the slot's bucket, so a renamed SFX stays an SFX — monkeybug),
    then bank/menu identity from the filename (music_cat stem, "SE FX"
    label) which beats the CSVs — monkeybug's pre-fix Led Zeppelin extract
    has SFX rows inside music_titles.csv, and a later user rename orphans a
    CSV row — then CSV classifications, then the label heuristics."""
    callouts = _load_callouts(assets_dir)
    titled = _load_music_titles(assets_dir)
    remembered = _load_renamed_cats(assets_dir)
    out = {}
    for rel in rel_paths:
        out[rel] = remembered.get(rel) or _classify_one(rel, callouts, titled)
    return out


def _load_renamed_cats(assets_dir):
    """``{rel: category}`` for slots currently carrying a user-remembered
    name: the rename memory keys by factory content hash (baseline md5) and
    records the Type bucket the slot had when renamed.  Applied only while
    the on-disk label still equals the remembered one — a re-rename or an
    auto-name pass takes the file back to the derived rules."""
    from . import name_memory
    cats = name_memory.load_categories()
    if not cats:
        return {}
    labels = name_memory.load()
    from .checksums import read_baseline_any
    try:
        baseline = read_baseline_any(assets_dir) or {}
    except Exception:
        return {}
    out = {}
    for rel, md5 in baseline.items():
        md5 = str(md5).lower()
        cat = cats.get(md5)
        if cat not in (MUSIC, SFX, CALLOUTS, OTHER):
            continue
        parts = name_memory.split_decode_name(rel.rpartition("/")[2])
        if parts and parts[1] == labels.get(md5):
            out[rel] = cat
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
