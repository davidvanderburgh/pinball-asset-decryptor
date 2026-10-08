"""Save a Replace tab's settings to a file, and load them back (PAD-300).

Images, Audio, Video and Text each keep what the user set up per project:
the three media tabs in the folder's :mod:`staged_changes` sidecar (which file
replaces which slot, plus each tab's per-slot ticks and options), Text in
``text/strings.tsv``.  A settings file is that state alone, as one small JSON
file: never the media itself, so a replacement still points at the file on
the PC that saved it (Project > Relink moved files... re-points the ones that
are somewhere else here).

Loading MERGES: a slot the file sets takes the file's choice, every other slot
keeps its own, and a slot this card does not have is left out and counted.
"""

import json
import os

FORMAT = "pad-tab-settings"
VERSION = 1

#: The sidecar sections each media tab owns.  Maps are ``{rel: value}``,
#: lists are rels, anything else is one tab-wide option.
SECTIONS = {
    "images": ("image", "image_keep_size", "image_group_tags",
               "image_color_slots", "color_all_images",
               "image_color_unlocked", "image_color_profiles"),
    "audio": ("audio", "audio_loop", "audio_keep", "audio_levels",
              "grow_keep_whole", "audio_trim"),
    "video": ("video", "video_asis_slots", "video_length_slots",
              "video_trim", "video_no_conversion", "video_best_quality",
              "video_color_slots", "color_all_videos", "video_color_stock",
              "video_color_profiles", "video_variants"),
}
#: The section holding each media tab's replacement picks.
PICKS = {"images": "image", "audio": "audio", "video": "video"}
#: Sections keyed by something other than a slot (kept whole on load).
NOT_BY_SLOT = ("image_group_tags",)
LABELS = {"images": "image", "audio": "audio", "video": "video",
          "text": "text"}


class TabSettingsError(Exception):
    """A file that is not a settings file of the wanted kind."""


def _write(path, kind, body):
    doc = {"format": FORMAT, "version": VERSION, "kind": kind}
    doc.update(body)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)


def read(path, kind):
    """The settings file at *path*, checked to be a *kind* one."""
    try:
        with open(path, encoding="utf-8") as f:
            doc = json.load(f)
    except ValueError:
        doc = None
    if not isinstance(doc, dict) or doc.get("format") != FORMAT:
        raise TabSettingsError(
            "%s is not a PAD settings file." % os.path.basename(path))
    got = doc.get("kind")
    if got != kind:
        raise TabSettingsError(
            "%s holds %s settings, not %s settings. Load it on the %s tab."
            % (os.path.basename(path), LABELS.get(got, "other"),
               LABELS[kind], str(got).capitalize() if got in LABELS
               else "matching"))
    return doc


# ---------------------------------------------------------------------------
# Images / Audio / Video: the sidecar sections
# ---------------------------------------------------------------------------
def media_sections(staged, kind):
    """This tab's sections of a loaded sidecar, empty ones left out."""
    out = {}
    for key in SECTIONS[kind]:
        val = staged.get(key)
        if isinstance(val, (dict, list)) and not val:
            continue
        if val is not None:
            out[key] = val
    return out


def media_count(sections, kind):
    """How many slots *sections* sets anything for."""
    rels = set()
    for key, val in sections.items():
        if key in NOT_BY_SLOT:
            continue
        if isinstance(val, dict):
            rels.update(val)
        elif isinstance(val, list):
            rels.update(val)
    return len(rels)


def export_media(staged, kind, path):
    """Write *kind*'s sections of the sidecar dict *staged* to *path*.
    Returns the number of slots it sets."""
    sections = media_sections(staged, kind)
    _write(path, kind, {"sections": sections})
    return media_count(sections, kind)


class MediaMerge:
    """What :func:`merge_media` did: the merged sidecar and the counts."""

    def __init__(self, data):
        self.data = data
        self.slots = set()        # slots on this card the file set
        self.missing = set()      # slots in the file this card lacks
        self.clash = set()        # slots that had a different pick here
        self.gone = set()         # picks whose file is not on this PC


def merge_media(staged, doc, kind, slots):
    """Merge the settings file *doc* into the sidecar dict *staged* for the
    slots in *slots* (rel paths this card has).  Returns a :class:`MediaMerge`
    whose ``data`` is the new sidecar; *staged* is not changed."""
    data = dict(staged)
    res = MediaMerge(data)
    sections = doc.get("sections")
    if not isinstance(sections, dict):
        sections = {}
    picks_key = PICKS[kind]
    for key in SECTIONS[kind]:
        if key not in sections:
            continue
        val = sections[key]
        if key in NOT_BY_SLOT:
            if isinstance(val, dict):
                merged = dict(data.get(key) or {})
                merged.update({str(k): str(v) for k, v in val.items()})
                data[key] = merged
            continue
        if isinstance(val, dict):
            mine = data.get(key)
            merged = dict(mine) if isinstance(mine, dict) else {}
            for rel, v in val.items():
                if rel not in slots:
                    res.missing.add(rel)
                    continue
                res.slots.add(rel)
                if key == picks_key:
                    if not isinstance(v, str) or not v.strip():
                        continue
                    old = merged.get(rel)
                    if old and os.path.normcase(old) != os.path.normcase(v):
                        res.clash.add(rel)
                    if not os.path.isfile(v):
                        res.gone.add(rel)
                merged[rel] = v
            data[key] = merged
        elif isinstance(val, list):
            mine = data.get(key)
            merged = list(mine) if isinstance(mine, list) else []
            for rel in val:
                if rel not in slots:
                    res.missing.add(rel)
                    continue
                res.slots.add(rel)
                if rel not in merged:
                    merged.append(rel)
            data[key] = merged
        elif isinstance(val, bool):
            data[key] = val
    return res


# ---------------------------------------------------------------------------
# Text: the edited rows of text/strings.tsv
# ---------------------------------------------------------------------------
def _edited(r):
    rep = r.get("replacement") or ""
    return bool(rep) and rep != r.get("original")


def text_edits(rows):
    """The edited manifest rows as ``[[path, original, new], ...]``."""
    return [[r.get("path", ""), r.get("original", ""), r["replacement"]]
            for r in rows if _edited(r)]


def export_text(rows, path):
    """Write the edited rows of *rows* to *path*.  Returns how many."""
    edits = text_edits(rows)
    _write(path, "text", {"edits": edits})
    return len(edits)


def match_text(doc, rows):
    """Pair each edit in the settings file *doc* with a row of *rows*.

    A string is keyed on its scene and its original text; when the same text
    shows more than once in one scene the n-th edit goes to the n-th copy.
    Returns ``(pairs, missing)``: ``[(row, new)]`` and the edits that found
    no row on this card."""
    edits = doc.get("edits")
    if not isinstance(edits, list):
        edits = []
    free = {}
    for r in rows:
        free.setdefault((r.get("path", ""), r.get("original", "")),
                        []).append(r)
    pairs, missing = [], []
    for e in edits:
        if not (isinstance(e, list) and len(e) >= 3
                and all(isinstance(x, str) for x in e[:3])):
            continue
        left = free.get((e[0], e[1]))
        if left:
            pairs.append((left.pop(0), e[2]))
        else:
            missing.append(e[:3])
    return pairs, missing
