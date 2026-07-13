"""Cross-extract memory of the user's own audio names, keyed by content.

Whisper mis-hears some callouts the same way on every extract (monkeybug:
"Whisper renames incorrectly over and over on the same file").  When the user
renames an audio slot in Replace Audio, the chosen label is stored here keyed
by the sound's FACTORY content hash — the extract baseline md5, which is
stable across re-extracts of the same card and carries over between firmware
versions whenever the sound's bytes do.  The next Auto-name pass applies these
names FIRST, before Whisper ever listens: a remembered file is renamed
immediately and the transcriber skips it as already-named.

The label is only the part after the decode prefix ("idx0384 - <label>.wav"),
so a remembered name survives the Length-prefix setting and idx shifts between
firmware versions.  Only decode-shaped names (``idx####`` / ``music_cat##_####``)
are renameable this way — every other plugin's Write maps audio by its full
path, which a rename would break.

Best-effort throughout: a missing/corrupt store or an extract without a
``.checksums.md5`` baseline simply applies nothing.
"""

import hashlib
import json
import os
import re

from . import config

# One shared file alongside settings.json: {content_md5: label}.
AUDIO_NAMES_FILE = os.path.join(os.path.dirname(config.SETTINGS_FILE),
                                "audio_names.json")

_MAX_LABEL = 80          # same cap the auto-transcribe rename enforces
_FORBIDDEN = '<>:"|?*/\\'

# A decode audio name: optional play-length prefix, the idx/music_cat stem,
# then an optional " - <label>" suffix from any of the naming passes.
_DECODE_NAME_RE = re.compile(
    r"^(?P<prefix>(?:\d+m\d+s\d+ - )?(?:idx\d+|music_cat\d+_\d+))"
    r"(?: - (?P<label>.+))?(?P<ext>\.(?:wav|ogg))$",
    re.IGNORECASE)


def split_decode_name(basename):
    """``(prefix, label, ext)`` for a decode-shaped audio filename, else None.

    ``prefix`` keeps the play-length lead-in when present ("01m22s235 -
    idx0001"), ``label`` is the current name suffix ("" when bare)."""
    m = _DECODE_NAME_RE.match(basename)
    if not m:
        return None
    return m.group("prefix"), (m.group("label") or "").strip(), m.group("ext")


def sanitize_label(text):
    """Make *text* safe as the name part of a filename (same rules as the
    auto-transcribe rename): reserved chars to '_', whitespace collapsed,
    capped, trailing dots/spaces trimmed.  '' when nothing survives."""
    safe = []
    for ch in text or "":
        if ch in _FORBIDDEN:
            safe.append("_")
        elif ch in "\n\r\t":
            safe.append(" ")
        else:
            safe.append(ch)
    cleaned = " ".join("".join(safe).split())
    if len(cleaned) > _MAX_LABEL:
        cleaned = cleaned[:_MAX_LABEL].rstrip() + "..."
    return cleaned.rstrip(". ")


def _load_raw():
    """Raw store — values are either a bare label string (v0.63.0) or a
    ``{"label":..., "cat":...}`` dict (v0.63.1, so a rename keeps its Type
    bucket — monkeybug renamed an SFX and watched it turn into a callout)."""
    try:
        with open(AUDIO_NAMES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if not re.fullmatch(r"[0-9a-f]{32}", str(k).lower()):
            continue
        if isinstance(v, dict):
            label = sanitize_label(str(v.get("label", "")))
            cat = str(v.get("cat", "")).strip().lower() or None
        else:
            label, cat = sanitize_label(str(v)), None
        if label:
            entry = {"label": label}
            if cat:
                entry["cat"] = cat
            out[str(k).lower()] = entry
    return out


def load():
    """``{md5: label}`` — ``{}`` on missing/corrupt/foreign."""
    return {k: v["label"] for k, v in _load_raw().items()}


def load_categories():
    """``{md5: category}`` for the entries that recorded one (the Type bucket
    the slot had when the user renamed it)."""
    return {k: v["cat"] for k, v in _load_raw().items() if "cat" in v}


def _save(data):
    root = os.path.dirname(AUDIO_NAMES_FILE)
    try:
        os.makedirs(root, exist_ok=True)
        with open(AUDIO_NAMES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, sort_keys=True)
    except OSError:
        pass


def remember(md5, label, category=None):
    """Store *label* (and optionally the slot's Type *category*) for content
    *md5*; a blank label forgets the entry."""
    if not md5:
        return
    md5 = str(md5).lower()
    label = sanitize_label(label)
    data = _load_raw()
    if label:
        entry = {"label": label}
        cat = str(category or "").strip().lower()
        if cat:
            entry["cat"] = cat
        if data.get(md5) == entry:
            return
        data[md5] = entry
    elif md5 in data:
        del data[md5]
    else:
        return
    _save(data)


def baseline_md5(assets_dir, rel):
    """The factory content hash for *rel* from the extract baseline, or None.

    The baseline hash — not the file's current bytes — is the identity a
    future extract reproduces, so it stays correct even after the slot was
    modded on disk."""
    from .checksums import read_baseline_any
    try:
        return (read_baseline_any(assets_dir) or {}).get(rel)
    except Exception:
        return None


def file_md5(path):
    """md5 of *path*'s bytes, or None on any read error."""
    try:
        h = hashlib.md5()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def apply_saved_names(assets_dir, log=None):
    """Rename every baseline file whose factory hash has a remembered label.

    Walks the extract *baseline* (rel -> factory md5) rather than the disk, so
    matching is pure dictionary lookups — no hashing, no file reads.  Renames
    ``<prefix>[ - old label].ext`` to ``<prefix> - <label>.ext`` (overriding a
    Sound-Test / Whisper name: the user's correction wins), re-points the
    baseline, and returns the count renamed."""
    names = load()
    if not names:
        return 0
    from .checksums import read_baseline_any, rename_in_baseline
    try:
        baseline = read_baseline_any(assets_dir) or {}
    except Exception:
        baseline = {}
    renames = {}
    for rel, md5 in baseline.items():
        label = names.get(str(md5).lower())
        if not label:
            continue
        parts = split_decode_name(rel.rpartition("/")[2])
        if parts is None:
            continue
        prefix, cur_label, ext = parts
        if cur_label == label:
            continue
        src = os.path.join(assets_dir, *rel.split("/"))
        if not os.path.isfile(src):
            continue
        folder = rel.rpartition("/")[0]
        new_base = "%s - %s%s" % (prefix, label, ext)
        new_rel = (folder + "/" + new_base) if folder else new_base
        dst = os.path.join(assets_dir, *new_rel.split("/"))
        if os.path.exists(dst):
            if log:
                log("  skip saved name for %s: target exists" % rel, "info")
            continue
        try:
            os.replace(src, dst)
            renames[rel] = new_rel
        except OSError as e:
            if log:
                log("  saved-name rename failed for %s: %s" % (rel, e),
                    "error")
    if renames:
        rename_in_baseline(assets_dir, renames)
        if log:
            log("Applied %d saved name(s) from earlier renames — those "
                "files skip transcription." % len(renames), "success")
    return len(renames)
