"""What a new game version brings: the stock assets it added, changed and
dropped against the version a project was extracted from (PAD-1388).

A modder moving a project onto a new code release wants to know, before the
build, whether the factory added videos, sounds, pictures or on-screen text
that the mod has no replacement for yet.  The answer is a stock-vs-stock
comparison of two EXTRACTS: the project (the old version) and a fresh
extract of the new card, which the one-click port makes anyway and reuses.

Stock, not what is on disk now: a Replace tab writes its pick OVER the
extracted file, so the project's own files are partly the mod.  Each
extract's ``.checksums.md5`` baseline is written at extract time and still
describes the card the folder came from, so every content match here reads
the baselines, never the modded bytes.  The one place the files themselves
are read is the sounds' second pass (the codec's lead-in frame differs on
every rebuilt sound; :mod:`.audio_compare`), and there a sound the user
replaced is read from its :mod:`.staged_originals` snapshot.

Pairing follows the mod transfer's own identities, so "new" means what the
transfer would also find no counterpart for:

* videos: the same bytes anywhere in the old version, then the same on-card
  path (``video/manifest.txt``), then the same file name;
* pictures: the same bytes, then the transfer's manifest pairing
  (:func:`.mod_transfer._image_rel_remap`), then the same file name;
* sounds: :func:`.audio_compare.diff_audio` (content first, renumbering and
  the codec lead-in stepped over);
* on-screen text: the strings of the Text tab's manifest, by their words.

``yours`` lists the slots the project REPLACED that the new version changed
or dropped: the first still get the replacement (worth a look: the factory
changed what it stands in for), the second have nowhere to land.
"""

import json
import os
import re

from . import audio_compare, staged_changes, staged_originals, text_manifest
from .checksums import read_baseline_any
from .folder_compare import kind_of

#: The report's kinds, in order: ``(kind, plural noun)``.
KINDS = (("video", "videos"), ("sound", "sounds"), ("image", "pictures"),
         ("text", "text lines"))

#: A kind's noun for one of it.
_ONE = {"video": "video", "sound": "sound", "image": "picture",
        "text": "text line"}

#: The file the full list is written to, beside the port's builds.
REPORT_SUFFIX = " - what's new.txt"


def _empty():
    return {"added": [], "changed": [], "removed": [], "same": 0}


def _by_md5(files):
    out = {}
    for rel, md5 in files.items():
        out.setdefault(md5, []).append(rel)
    return out


def _pair(old, new, key_old=None, key_new=None, names_first=False):
    """Pair two ``{rel: md5}`` maps of one kind.  Returns ``_empty()``-shaped
    lists of rels: *added* (new side), *changed* (``(old_rel, new_rel)``),
    *removed* (old side), and a count of new files whose bytes are already in
    the old version.

    Files with the same bytes pair first.  The rest pair by a second identity
    (*key_old* / *key_new*: an on-card path), by the same file name, and by
    the same name in another container (a clip re-encoded from .mp4 to .mov
    keeps its name, not its extension), each pass over every file before the
    next and each old file used once.  *names_first* puts the name passes
    before the key: a video's card path is its POSITION in its scene's asset
    list, which shifts when the factory inserts a clip (King Kong LE 0.93.0
    -> 1.00.0 moved Kong_BallSave from asset 23 to 39), while the clip's name
    is the scene's own."""
    out = _empty()
    old_md5 = _by_md5(old)
    new_md5 = set(new.values())
    used = set()             # old rels a new file accounts for
    rest = []
    for rel in sorted(new):
        hit = old_md5.get(new[rel])
        if hit:
            out["same"] += 1
            used.update(hit)
        else:
            rest.append(rel)
    by_key = {}
    if key_old is not None:
        for rel in old:
            k = key_old(rel)
            if k:
                by_key.setdefault(k, rel)
    by_stem = {}
    for r in sorted(old):
        by_stem.setdefault(os.path.splitext(r)[0].lower(), r)

    def by_card(rel):
        k = key_new(rel) if key_new is not None else None
        return by_key.get(k) if k else None

    def by_name(rel):
        return rel if rel in old else None

    def by_other_container(rel):
        return by_stem.get(os.path.splitext(rel)[0].lower())

    passes = ((by_name, by_other_container, by_card) if names_first
              else (by_card, by_name, by_other_container))
    twins = {}
    for find in passes:
        for rel in rest:
            if rel in twins:
                continue
            twin = find(rel)
            if (twin is not None and twin not in used
                    and old[twin] not in new_md5):
                twins[rel] = twin
                used.add(twin)
    for rel in rest:
        if rel in twins:
            out["changed"].append((twins[rel], rel))
        else:
            out["added"].append(rel)
    out["removed"] = sorted(r for r in old
                            if r not in used and old[r] not in new_md5)
    return out


def _video_keys(folder):
    """``rel -> on-card path`` from an extract's ``video/manifest.txt``."""
    from .mod_transfer import _video_card_paths
    try:
        return {rel: card for card, rel in _video_card_paths(folder).items()}
    except Exception:                                   # noqa: BLE001
        return {}


def _image_keys(old_dir, new_dir):
    """``(key_old, key_new)`` pairing pictures the way the transfer does: an
    old picture's key is the first new rel the manifests pair it with."""
    from .mod_transfer import _image_rel_remap
    try:
        remap, _identified = _image_rel_remap(old_dir, new_dir)
    except Exception:                                   # noqa: BLE001
        return None, None
    back = {}
    for src, tgts in remap.items():
        for t in tgts:
            back.setdefault(t, src)
    first = {src: (tgts[0] if tgts else None) for src, tgts in remap.items()}
    return first.get, (lambda rel: rel if rel in back else None)


def _same_pixels(old_dir, new_dir, d, replaced):
    """Move the picture pairs whose PIXELS are the same out of *changed*:
    a font's glyph slices come out byte-different when only the atlas they
    were cut from moved (a quarter of King Kong LE 1.00.0's "changed"
    pictures).  A replaced picture is read from its stock snapshot."""
    from .mod_transfer import _pixels_identical
    keep = []
    for o, n in d["changed"]:
        src = (staged_originals.snapshot_path(old_dir, o) if o in replaced
               else None) or os.path.join(old_dir, o)
        try:
            same = _pixels_identical(src, os.path.join(new_dir, n))
        except Exception:                               # noqa: BLE001
            same = False
        if same:
            d["same"] += 1
        else:
            keep.append((o, n))
    d["changed"] = keep


def _replaced(folder):
    """Rels the project replaced: its Replace picks, plus any file with a
    stock snapshot (an edit written over the extract)."""
    out = set()
    try:
        saved = staged_changes.load(folder)
    except Exception:                                   # noqa: BLE001
        saved = {}
    for kind in ("audio", "video", "image"):
        out.update((saved.get(kind) or {}).keys())
    try:
        out.update(staged_originals.snapshot_rels(folder))
    except Exception:                                   # noqa: BLE001
        pass
    return {r.replace("\\", "/") for r in out}


def _sounds(old_dir, new_dir, replaced):
    """The sounds' pairing, with a replaced sound judged by its stock
    snapshot rather than the replacement written over it."""
    d = audio_compare.diff_audio(old_dir, new_dir)
    out = {"added": list(d["added"]), "removed": list(d["removed"]),
           "changed": list(d["changed"]),
           "same": d["same"] + len(d["moved"])}
    snap = {r: staged_originals.snapshot_path(old_dir, r)
            for r in replaced if r.startswith(audio_compare.AUDIO_DIR + "/")}
    snap = {r: p for r, p in snap.items() if p and os.path.isfile(p)}
    if not snap:
        return out

    def digest(path):
        try:
            return audio_compare.sound_digest(path)
        except Exception:                               # noqa: BLE001
            return None

    keep = []
    for old_rel, new_rel in out["changed"]:
        if old_rel in snap and digest(snap[old_rel]) == digest(
                os.path.join(new_dir, new_rel)):
            out["same"] += 1
        else:
            keep.append((old_rel, new_rel))
    out["changed"] = keep
    added = {digest(os.path.join(new_dir, r)): r for r in out["added"]}
    gone = []
    for old_rel in out["removed"]:
        hit = added.pop(digest(snap[old_rel]), None) if old_rel in snap \
            else None
        if hit:
            out["added"].remove(hit)
            out["same"] += 1
        else:
            gone.append(old_rel)
    out["removed"] = gone
    return out


_WORD = re.compile(r"[A-Za-z]{3}")


def _readable(words):
    """Is *words* a line a player could read on screen?  The Text tab's
    game-program rows are every string the scan found in the program, most
    of them a few bytes of code that happen to be printable (">w", "0U") or
    the operating system's own messages ("DHCP is %s\\n"): none is worth a
    replacement, and King Kong LE's 1.00.0 has thousands."""
    w = (words or "").strip()
    if len(w) < 3 or not _WORD.search(w):
        return False
    if "%" in w or "\\" in w or any(c in w for c in "{}<>|_=;"):
        return False
    letters = sum(c.isalpha() or c == " " for c in w)
    return letters >= 0.75 * len(w)


def _text(old_dir, new_dir):
    """New and dropped on-screen strings, by their words."""
    def words(folder):
        try:
            rows = text_manifest.load(folder)
        except Exception:                               # noqa: BLE001
            rows = []
        return {r["original"].strip() for r in rows
                if not r.get("unused") and _readable(r.get("original", ""))}
    a, b = words(old_dir), words(new_dir)
    out = _empty()
    out["added"] = sorted(b - a)
    out["removed"] = sorted(a - b)
    out["same"] = len(a & b)
    return out


def card_version(folder):
    """The version an extract came from (its own record, else what the
    Mod Pack tab's version chips read), or ``""``."""
    try:
        with open(os.path.join(folder, ".extract_source.json"),
                  encoding="utf-8") as f:
            v = (json.load(f) or {}).get("card_version") or ""
    except (OSError, ValueError):
        v = ""
    if v:
        return v
    try:
        from .extract_source import version_for_dir
        return version_for_dir(folder)[0] or ""
    except Exception:                                   # noqa: BLE001
        return ""


def compare(old_dir, new_dir):
    """What *new_dir* (a stock extract of the new version) brings against
    *old_dir* (the project, extracted from the old one).  Read-only.

    Returns ``{"old", "new", "old_version", "new_version", "kinds": {kind:
    {"added", "changed", "removed", "same"}}, "yours": {"changed",
    "removed"}}``; *added* / *removed* hold rels (text: the words),
    *changed* ``(old_rel, new_rel)`` pairs."""
    old_base = read_baseline_any(old_dir) or {}
    new_base = read_baseline_any(new_dir) or {}
    split = {}
    for side, base in (("old", old_base), ("new", new_base)):
        for rel, md5 in base.items():
            k = kind_of(rel)
            if k in ("video", "image") and not os.path.basename(
                    rel).startswith("."):
                split.setdefault((side, k), {})[rel] = md5
    replaced = _replaced(old_dir)
    kinds = {}
    vk_old, vk_new = _video_keys(old_dir), _video_keys(new_dir)
    kinds["video"] = _pair(split.get(("old", "video"), {}),
                           split.get(("new", "video"), {}),
                           vk_old.get, vk_new.get, names_first=True)
    ik_old, ik_new = _image_keys(old_dir, new_dir)
    kinds["image"] = _pair(split.get(("old", "image"), {}),
                           split.get(("new", "image"), {}), ik_old, ik_new)
    _same_pixels(old_dir, new_dir, kinds["image"], replaced)
    kinds["sound"] = _sounds(old_dir, new_dir, replaced)
    kinds["text"] = _text(old_dir, new_dir)
    yours = {"changed": [], "removed": []}
    for k in ("video", "image", "sound"):
        yours["changed"] += [o for o, _n in kinds[k]["changed"]
                             if o in replaced]
        yours["removed"] += [o for o in kinds[k]["removed"] if o in replaced]
    return {"old": old_dir, "new": new_dir,
            "old_version": card_version(old_dir),
            "new_version": card_version(new_dir),
            "kinds": kinds, "yours": yours}


def _name(rel):
    return rel.split("/", 1)[-1] if "/" in rel else rel


def headline(news):
    """One sentence: what the new version adds, e.g. "1.00.0 adds 12 videos,
    3 sounds and no new pictures or text lines"."""
    ver = news.get("new_version") or "The new version"
    have, none = [], []
    for k, noun in KINDS:
        n = len(news["kinds"][k]["added"])
        (have if n else none).append(
            "%d %s" % (n, _ONE[k] if n == 1 else noun) if n else noun)
    if not have:
        return "%s adds no new videos, sounds, pictures or text." % ver
    said = (", ".join(have[:-1]) + " and " + have[-1]
            if len(have) > 1 else have[0])
    if none:
        said += "; no new " + (", ".join(none[:-1]) + " or " + none[-1]
                               if len(none) > 1 else none[0])
    return "%s adds %s." % (ver, said)


def summary_lines(news):
    """``[(level, line)]`` for the log: the headline, then per kind its
    added / changed / removed counts, then the slots the project replaced
    that this version changed or dropped."""
    out = [("success" if not any(news["kinds"][k]["added"] for k, _ in KINDS)
            else "warning", "What's new: " + headline(news))]
    for k, noun in KINDS:
        d = news["kinds"][k]
        out.append(("info", "  %s: %d new, %d changed, %d gone, %d the same"
                    % (noun.capitalize(), len(d["added"]), len(d["changed"]),
                       len(d["removed"]), d["same"])))
    y = news["yours"]
    if y["changed"]:
        out.append(("warning", "  %d slot(s) you replaced were changed in "
                    "this version; your replacement still goes on: %s"
                    % (len(y["changed"]), ", ".join(
                        _name(r) for r in y["changed"][:8]))))
    if y["removed"]:
        out.append(("warning", "  %d slot(s) you replaced are gone in this "
                    "version, so those replacements have nowhere to go: %s"
                    % (len(y["removed"]), ", ".join(
                        _name(r) for r in y["removed"][:8]))))
    return out


def report_text(news):
    """The full list, for the file written beside the builds."""
    lines = ["What's new in %s (compared with %s)" % (
        news.get("new_version") or "the new card",
        news.get("old_version") or "your project"), "",
        headline(news), "",
        "Your project:  %s" % news["old"],
        "New extract:   %s" % news["new"], ""]
    for k, noun in KINDS:
        d = news["kinds"][k]
        lines.append("== %s: %d new, %d changed, %d gone ==" % (
            noun.capitalize(), len(d["added"]), len(d["changed"]),
            len(d["removed"])))
        for title, items in (("New", d["added"]),
                             ("Changed", [n for _o, n in d["changed"]]),
                             ("Gone", d["removed"])):
            if items:
                lines.append("  %s:" % title)
                lines += ["    " + _name(i) for i in items]
        lines.append("")
    y = news["yours"]
    for title, items in (("Slots you replaced that this version changed",
                          y["changed"]),
                         ("Slots you replaced that this version dropped",
                          y["removed"])):
        if items:
            lines.append("== %s ==" % title)
            lines += ["  " + _name(i) for i in items]
            lines.append("")
    return "\n".join(lines)


def write_report(news, path):
    with open(path, "w", encoding="utf-8") as f:
        f.write(report_text(news))
    return path


def for_page(news, cap=200):
    """The page's copy: per kind the counts and the first *cap* names of
    each list (the report file has all of them)."""
    kinds = []
    for k, noun in KINDS:
        d = news["kinds"][k]
        lists = {"added": [_name(r) for r in d["added"]],
                 "changed": [_name(n) for _o, n in d["changed"]],
                 "removed": [_name(r) for r in d["removed"]]}
        kinds.append({"kind": k, "noun": noun, "same": d["same"],
                      **{"n_" + key: len(v) for key, v in lists.items()},
                      **{key: v[:cap] for key, v in lists.items()}})
    return {"headline": headline(news),
            "old_version": news.get("old_version") or "",
            "new_version": news.get("new_version") or "",
            "kinds": kinds,
            "yours_changed": [_name(r) for r in news["yours"]["changed"]],
            "yours_removed": [_name(r) for r in news["yours"]["removed"]]}
