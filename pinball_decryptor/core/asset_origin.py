"""Is each extracted asset the official card's, or custom? (Simon, 2026-11-21)

"We should also consider adding another column (Probably audio, video, images and even text) to account for
whether the asset is original or custom (custom being an asset that isn't original but has been extracted from
the current card)."

A project extracted from the card the game shipped on is all **Original**.  A project extracted from any other
card (one PAD wrote, or a card someone else modified) is measured against an extract of the official card of the
same release found on this PC (:func:`lineage.find_official_extract`): each file's MD5 taken at extract
(``.checksums.md5``) against the official extract's, and each line of text (``text/strings.tsv``, by scene and
words) against its lines.  An asset the official extract has the same is **Original**; any other is **Custom**.
With no official extract to measure against, a Stern project's pictures and clips are measured against the
official release's record shipped with the app (``stock_prints.project_off_stock``); sounds and text are then
not known (None).
"""
from __future__ import annotations

import os

ORIGINAL = "Original"
CUSTOM = "Custom"

_CACHE = {}


def _baseline(folder):
    from .checksums import read_baseline_any
    try:
        return read_baseline_any(folder) or {}
    except Exception:                                   # noqa: BLE001
        return {}


def _text_keys(folder):
    """``{(source, words)}`` of a project's ``text/strings.tsv`` (its first two columns)."""
    out = set()
    try:
        with open(os.path.join(folder, "text", "strings.tsv"), encoding="utf-8") as f:
            for line in f:
                if line.startswith("#"):
                    continue
                cols = line.rstrip("\r\n").split("\t")
                if len(cols) >= 2:
                    out.add((cols[0], cols[1]))
    except OSError:
        pass
    return out


def _stamp(folder):
    out = []
    for name in (".checksums.md5", ".pad-lineage.json", ".extract_source.json"):
        try:
            st = os.stat(os.path.join(folder, name))
            out.append((st.st_mtime_ns, st.st_size))
        except OSError:
            out.append(None)
    return tuple(out)


def origins(assets_dir, candidates=()):
    """``{"official": True when the project came off the official card, "against": the folder or record measured
    against ("" when none), "custom": {asset rel (images/..., audio/..., video/...)}, "known": {kind: True when
    that kind could be measured}, "text_custom": {(source, words)}}``, cached until the project's sidecars
    change."""
    if not assets_dir or not os.path.isdir(assets_dir):
        return {"official": False, "against": "", "custom": set(), "known": {}, "text_custom": set()}
    key = os.path.normcase(os.path.abspath(assets_dir))
    stamp = _stamp(assets_dir)
    got = _CACHE.get(key)
    if got and got[0] == stamp:
        return got[1]
    from . import lineage
    out = {"official": False, "against": "", "custom": set(), "known": {}, "text_custom": set()}
    try:
        sidx, official = lineage._release_of(assets_dir)
    except Exception:                                   # noqa: BLE001
        sidx, official = "", False
    if official:
        out["official"] = True
        out["known"] = {k: True for k in ("images", "audio", "video", "text")}
    else:
        ref = ""
        try:
            ref = lineage.find_official_extract(assets_dir, candidates) if sidx else ""
        except Exception:                               # noqa: BLE001
            ref = ""
        if ref:
            mine, theirs = _baseline(assets_dir), _baseline(ref)
            for rel, md5 in mine.items():
                kind = rel.split("/", 1)[0]
                if kind in ("images", "audio", "video") and theirs.get(rel) != md5:
                    out["custom"].add(rel)
            out["text_custom"] = _text_keys(assets_dir) - _text_keys(ref)
            out["against"] = ref
            out["known"] = {k: True for k in ("images", "audio", "video", "text")}
        else:
            try:
                from ..plugins.stern.stock_prints import project_off_stock
                off = project_off_stock(assets_dir)
            except Exception:                           # noqa: BLE001
                off = None
            if off is not None:
                out["custom"] = set(off.get("files") or ())
                out["against"] = off.get("label") or "the official release"
                out["known"] = {"images": True, "video": True}
    _CACHE[key] = (stamp, out)
    return out


def origin_of(info, rel):
    """``"Original"``, ``"Custom"`` or None (not known) for the asset *rel* (``images/...``, ``audio/...`` or
    ``video/...``) of :func:`origins` *info*."""
    kind = rel.split("/", 1)[0]
    if not info.get("known", {}).get(kind):
        return None
    return CUSTOM if rel in info["custom"] else ORIGINAL


def text_origin_of(info, source, words):
    """The same for a line of text (its scene or program ``source`` and its ``words``)."""
    if not info.get("known", {}).get("text"):
        return None
    return CUSTOM if (source, words) in info["text_custom"] else ORIGINAL


def tip(info, value):
    """The Origin cell's tooltip."""
    if value is None:
        return ("Not known: this project didn't come off the official card, and no extract of the official card "
                "was found on this PC to compare it with.")
    if value == CUSTOM:
        return ("Custom: on the card this project was extracted from, but not the official card's (it was "
                "measured against %s)." % (os.path.basename(info.get("against") or "") or "the official card"))
    if info.get("official"):
        return "Original: this project was extracted from the official card."
    return ("Original: the same as the official card's (measured against %s)."
            % (os.path.basename(info.get("against") or "") or "the official card"))
