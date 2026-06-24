"""Stern Spike 2 Spine skeleton export.

Spine scenes (radium element type ``"Spine"``) embed a complete Spine 3.1
skeleton as a plain-JSON, u64-length-prefixed string inside ``scene.radium``:

    {"skeleton":{"hash":"...","spine":"3.1.08","width":...,"height":...},
     "bones":[...],"slots":[...],"skins":{...},"animations":{...}}

The JSON is written out **verbatim** (a byte-exact slice of the radium); no
transform is applied.  Reverse-engineered offline; validated 14 skeletons /
698 animations on Elvira.

Alongside each skeleton we emit a ``*.atlas.json`` attachment manifest
(:func:`build_atlas`): every skin/slot/attachment with its declared geometry,
plus the animation list.  IMPORTANT (empirically verified): the Spine
attachment frames are **not** the loose fmt4/fmt5 texture leaves -- Spine scenes
have no ``scene.assets`` and no ``<N>.asset`` records at all.  Each skeleton's
frame pixels are embedded inside its own multi-MB ``scene.radium`` in a custom,
not-yet-decoded frame format, so the atlas maps attachments to geometry, not to
PNG files (honest provenance is recorded in the ``frame_source`` field).

Upstream-plugin port of the standalone ``export_spine.py`` RE script: the
skeleton scan + verbatim emit are byte-identical; only the I/O is adapted to
read radium files through the pure-Python ext4 reader (:mod:`.ext4`).
"""

import json
import os
import struct

# Spine JSON blobs can be large; the LP-string scan must allow well past 64 KiB
# (real skeletons reach a few MiB once animation curves are inlined).
_MAX_LP = 16 << 20
_GROUP_PREFIXES = ("spine", "video", "stream", "image", "texture")
_SKELETON_MAGIC = b'{"skeleton"'


def _lp_strings(data, max_len=_MAX_LP):
    """Yield ``(offset, bytes)`` for every printable u64-length-prefixed string."""
    i, n = 0, len(data)
    while i + 8 <= n:
        ln = struct.unpack_from("<Q", data, i)[0]
        if 1 <= ln <= max_len and i + 8 + ln <= n:
            s = data[i + 8:i + 8 + ln]
            if all(9 <= b < 127 for b in s):
                yield i + 8, s
                i += 8 + ln
                continue
        i += 1


def _group_name(data):
    """The scene group tag, e.g. ``'spine.Gargoyle'`` (first dotted token)."""
    for _, s in _lp_strings(data, max_len=512):
        t = s.decode("ascii", "replace")
        if "." in t and t.split(".")[0] in _GROUP_PREFIXES:
            return t
    return None


def extract_skeleton(data):
    """Return ``(group, json_bytes)`` for a scene.radium blob, or ``None``.

    Only blobs that actually contain a Spine skeleton (``{"skeleton"`` ... that
    ``json.loads`` parses) are returned; everything else yields ``None``."""
    if _SKELETON_MAGIC not in data:
        return None
    group = _group_name(data)
    for _, s in _lp_strings(data):
        if s[:len(_SKELETON_MAGIC)] == _SKELETON_MAGIC:
            try:
                json.loads(s.decode("utf-8"))
            except Exception:                        # noqa: BLE001
                continue
            return group, s
    return None


def build_atlas(meta):
    """Build an attachment/animation manifest from a parsed skeleton dict.

    The Spine attachment frames for these scenes are NOT loose fmt4/fmt5 texture
    leaves; each skeleton's frame pixels are embedded inside its own
    ``scene.radium`` in a custom, as-yet-undecoded frame format.  So this maps
    every attachment to the geometry the skeleton JSON declares, giving a
    complete loadable index of the rig without claiming PNG links that don't
    exist."""
    skel = meta.get("skeleton", {}) or {}
    attachments = []
    for skin_name, slots in (meta.get("skins", {}) or {}).items():
        if not isinstance(slots, dict):
            continue
        for slot_name, atts in slots.items():
            if not isinstance(atts, dict):
                continue
            for att_name, adef in atts.items():
                adef = adef or {}
                attachments.append({
                    "skin": skin_name, "slot": slot_name, "name": att_name,
                    "type": adef.get("type", "region"),
                    "w": adef.get("width"), "h": adef.get("height"),
                    "path": adef.get("path"),
                })
    anims = meta.get("animations", {}) or {}
    return {
        "spine": skel.get("spine"),
        "w": skel.get("width"), "h": skel.get("height"),
        "bones": len(meta.get("bones", []) or []),
        "slots": len(meta.get("slots", []) or []),
        "skins": list((meta.get("skins", {}) or {}).keys()),
        "animations": len(anims),
        "animation_names": sorted(anims.keys()),
        "frame_source": "scene.radium (embedded custom frame format, not decoded)",
        "attachments": attachments,
    }


def _emit(out_dir, scene_hash, group, js, index):
    g = (group or "spine.unknown").replace("/", "_")
    base = "%s__%s" % (g, scene_hash)
    cand, k = base, 0
    while os.path.exists(os.path.join(out_dir, cand + ".json")):
        k += 1
        cand = "%s_%d" % (base, k)
    with open(os.path.join(out_dir, cand + ".json"), "wb") as f:
        f.write(js)                                  # byte-exact verbatim JSON
    meta = json.loads(js.decode("utf-8"))
    skel = meta.get("skeleton", {}) or {}
    atlas = build_atlas(meta)
    atlas["group"] = group
    atlas["scene"] = scene_hash
    atlas["json"] = cand + ".json"
    with open(os.path.join(out_dir, cand + ".atlas.json"), "w") as f:
        json.dump(atlas, f, indent=2)
    index.append({
        "group": group, "scene": scene_hash, "json": cand + ".json",
        "atlas": cand + ".atlas.json",
        "spine": skel.get("spine"), "w": skel.get("width"),
        "h": skel.get("height"),
        "bones": len(meta.get("bones", []) or []),
        "slots": len(meta.get("slots", []) or []),
        "animations": len(meta.get("animations", {}) or {}),
        "attachments": len(atlas["attachments"]),
    })


# ---------------------------------------------------------------------------
# extraction phase (reads radium through the ext4 reader)
# ---------------------------------------------------------------------------
def extract_spine(reader, output_dir, log=None, progress=None, cancel=None):
    """Export every embedded Spine skeleton on the card to
    ``output_dir/spine/`` (verbatim ``<group>__<scene>.json`` + ``.atlas.json``
    + an ``index.json`` catalog).  Returns the number of skeletons exported."""
    log = log or (lambda *a, **k: None)
    cancel = cancel or (lambda: False)

    log("Scanning .radium scene files for Spine skeletons...", "info")
    rads = []
    for path, _ino, node in reader.iter_regular_files(min_size=1):
        if cancel():
            return 0
        if path.endswith("/scene.radium"):
            rads.append((path, node))
    if not rads:
        log("No scene.radium files found.", "info")
        return 0

    out_dir = os.path.join(output_dir, "spine")
    index, made = [], False
    for i, (path, node) in enumerate(rads):
        if cancel():
            break
        try:
            data = reader.read_file_bytes(node)
        except Exception:                            # noqa: BLE001
            continue
        res = extract_skeleton(data)
        if res is None:
            continue
        if not made:
            os.makedirs(out_dir, exist_ok=True)
            made = True
        group, js = res
        scene_hash = path[:-len("/scene.radium")].rsplit("/", 1)[-1]
        _emit(out_dir, scene_hash, group, js, index)
        if progress:
            progress(len(index), len(index), index[-1]["json"])

    if not index:
        log("No Spine skeletons found.", "info")
        return 0
    try:
        with open(os.path.join(out_dir, "index.json"), "w") as f:
            json.dump(index, f, indent=2)
    except Exception:                                # noqa: BLE001
        pass
    n_anim = sum(e["animations"] for e in index)
    n_att = sum(e.get("attachments", 0) for e in index)
    log("Exported %d Spine skeleton(s) (%d animations, %d attachments) to %s."
        % (len(index), n_anim, n_att, out_dir), "success")
    return len(index)
