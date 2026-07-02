"""Transfer a user's pending mods from one extract folder to another — the
"I modded version N, now version N+1 shipped, move my work over" workflow.

Mods live as two artifacts inside an extract folder (see :mod:`staged_changes`
and :mod:`text_manifest`):

* ``.staged_changes.json`` — the Replace-Audio/Video/Image assignments
  (``rel_path -> external replacement file``) plus the per-slot audio Loop/Keep
  flags and the trim toggles.
* ``text/strings.tsv`` — the on-screen-text edits, keyed by the *original*
  string.

Transferring is not a blind copy, because a new firmware version can change the
asset layout.  Two hazards, handled differently:

* **Audio** slots are ``audio/idxNNNN.wav`` where ``NNNN`` is the master-
  directory index.  A new version can insert / remove / reorder sounds, so the
  same index can be a *different sound*.  We therefore match audio by the
  **content of the stock WAV** (a cheap size + head/tail digest of the file the
  Extract produced, which stays stock until Write), not by the raw index — so a
  replacement follows its sound even if it moved to a new index, and an index
  that now holds a *different* sound is flagged rather than silently mis-applied.
* **Image / Video / Text** are keyed by stable identities (asset filename, or
  for text the original string).  A rel_path / original that no longer exists in
  the target is dropped (a safe no-op), never re-pointed.

``plan_transfer`` computes a reconciliation report without touching anything;
``apply_transfer`` merges the resolved edits into the target folder.  Nothing
here re-encodes or writes card data — the user still runs Write against the new
extract afterwards, which re-encodes each replacement for the new firmware.
"""

import hashlib
import os

from . import staged_changes, text_manifest

# Slot categories that carry ``rel_path -> replacement`` assignment maps.
_ASSIGN_KEYS = ("audio", "video", "image")
# Per-audio-slot flag maps that must follow a remapped audio key.
_AUDIO_FLAG_KEYS = ("audio_loop", "audio_keep")
# Toggle values copied verbatim (not per-slot).
_TOGGLE_KEYS = ("audio_trim", "video_trim", "video_no_conversion")

_HEAD = 256 * 1024
_TAIL = 64 * 1024


def content_signature(path):
    """A cheap, collision-safe signature of a file's *content*: its size plus a
    digest of the head and tail.  Two distinct extracted sounds never collide in
    practice (their WAV headers + leading samples differ), and it's fast even for
    a multi-hundred-MB music track.  Returns ``None`` if the file is unreadable.
    """
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            h.update(f.read(_HEAD))
            if size > _HEAD + _TAIL:
                f.seek(-_TAIL, os.SEEK_END)
                h.update(f.read(_TAIL))
    except OSError:
        return None
    return (size, h.hexdigest())


def _abs(root, rel):
    return os.path.join(root, rel.replace("/", os.sep))


def _stock_exists(root, rel):
    return os.path.isfile(_abs(root, rel))


def _plan_audio(source_dir, target_dir, saved_audio):
    """Reconcile audio assignments by stock-WAV content.

    Returns ``(matched, remapped, flagged, dropped)`` where each entry is a dict
    the caller can render and :func:`apply_transfer` can consume:
      matched  {src_rel, tgt_rel==src_rel, repl}
      remapped {src_rel, tgt_rel, repl}          (sound moved to a new index)
      flagged  {src_rel, repl, reason}           (index reused for another sound)
      dropped  {src_rel, repl, reason}           (sound no longer present)
    """
    matched, remapped, flagged, dropped = [], [], [], []
    if not saved_audio:
        return matched, remapped, flagged, dropped

    # Index the target's stock WAVs by content signature (audio/ only).
    tgt_audio_dir = os.path.join(target_dir, "audio")
    sig_to_rels = {}
    if os.path.isdir(tgt_audio_dir):
        for name in os.listdir(tgt_audio_dir):
            if not name.lower().endswith(".wav"):
                continue
            rel = "audio/" + name
            sig = content_signature(_abs(target_dir, rel))
            if sig is not None:
                sig_to_rels.setdefault(sig, []).append(rel)

    for src_rel, repl in saved_audio.items():
        src_sig = content_signature(_abs(source_dir, src_rel))
        cands = sig_to_rels.get(src_sig, []) if src_sig is not None else []
        if src_rel in cands:
            matched.append({"src_rel": src_rel, "tgt_rel": src_rel, "repl": repl})
        elif cands:
            # Same sound, moved to a different index. Prefer a deterministic pick.
            remapped.append({"src_rel": src_rel, "tgt_rel": sorted(cands)[0],
                             "repl": repl})
        elif _stock_exists(target_dir, src_rel):
            flagged.append({"src_rel": src_rel, "repl": repl,
                            "reason": "the sound at %s differs in the new "
                                      "version (index reused)" % src_rel})
        else:
            dropped.append({"src_rel": src_rel, "repl": repl,
                            "reason": "no matching sound in the new version"})
    return matched, remapped, flagged, dropped


def _plan_rel_category(source_dir, target_dir, saved_map):
    """Reconcile an image/video assignment map by rel_path (stable filename).

    Returns ``(matched, dropped)`` — matched entries note whether the stock
    asset's *content* changed (same name, new art) so the caller can surface it.
    """
    matched, dropped = [], []
    for rel, repl in (saved_map or {}).items():
        if _stock_exists(target_dir, rel):
            changed = (content_signature(_abs(source_dir, rel))
                       != content_signature(_abs(target_dir, rel)))
            matched.append({"rel": rel, "repl": repl, "content_changed": changed})
        else:
            dropped.append({"rel": rel, "repl": repl,
                            "reason": "no %s in the new version" % rel})
    return matched, dropped


def _plan_text(source_dir, target_dir):
    """Reconcile text edits: a source edit transfers if its *original* string
    still exists somewhere in the target manifest.  Returns ``(matched,
    dropped)`` where matched entries carry the number of target rows they'll
    fill (edits apply to every scene sharing the original text)."""
    src_rows = text_manifest.load(source_dir)
    tgt_rows = text_manifest.load(target_dir)
    tgt_originals = {}
    for r in tgt_rows:
        tgt_originals.setdefault(r["original"], 0)
        tgt_originals[r["original"]] += 1

    matched, dropped = [], []
    seen = set()
    for r in src_rows:
        rep = r["replacement"]
        if not rep or rep == r["original"]:
            continue
        key = (r["original"], rep)
        if key in seen:
            continue
        seen.add(key)
        n = tgt_originals.get(r["original"], 0)
        if n:
            matched.append({"original": r["original"], "new": rep, "targets": n})
        else:
            dropped.append({"original": r["original"], "new": rep,
                            "reason": "that original text isn't in the new "
                                      "version"})
    return matched, dropped


def plan_transfer(source_dir, target_dir):
    """Compute a reconciliation plan moving *source_dir*'s mods onto
    *target_dir*.  Read-only.  Returns a dict::

        {"audio": {matched, remapped, flagged, dropped},
         "video": {matched, dropped},
         "image": {matched, dropped},
         "text":  {matched, dropped},
         "toggles": {key: value, ...},
         "totals": {"transfer": int, "flagged": int, "dropped": int}}
    """
    saved = staged_changes.load(source_dir)

    a_matched, a_remapped, a_flagged, a_dropped = _plan_audio(
        source_dir, target_dir, saved.get("audio"))
    v_matched, v_dropped = _plan_rel_category(
        source_dir, target_dir, saved.get("video"))
    i_matched, i_dropped = _plan_rel_category(
        source_dir, target_dir, saved.get("image"))
    t_matched, t_dropped = _plan_text(source_dir, target_dir)

    plan = {
        "audio": {"matched": a_matched, "remapped": a_remapped,
                  "flagged": a_flagged, "dropped": a_dropped},
        "video": {"matched": v_matched, "dropped": v_dropped},
        "image": {"matched": i_matched, "dropped": i_dropped},
        "text": {"matched": t_matched, "dropped": t_dropped},
        "toggles": {k: saved[k] for k in _TOGGLE_KEYS if k in saved},
    }
    transfer = (len(a_matched) + len(a_remapped) + len(v_matched)
                + len(i_matched) + len(t_matched))
    flagged = len(a_flagged)
    dropped = (len(a_dropped) + len(v_dropped) + len(i_dropped)
               + len(t_dropped))
    plan["totals"] = {"transfer": transfer, "flagged": flagged,
                      "dropped": dropped}
    return plan


def apply_transfer(source_dir, target_dir, plan, include_flagged=False):
    """Merge *plan*'s transferable edits into *target_dir*'s sidecar + text
    manifest.  Existing target edits are preserved unless a transferred entry
    targets the same slot/string.  ``include_flagged`` also applies the audio
    entries whose index was reused (off by default — those are the risky ones).
    Returns ``{"audio", "video", "image", "text"}`` counts actually written."""
    src_saved = staged_changes.load(source_dir)
    tgt = staged_changes.load(target_dir)

    src_loop = src_saved.get("audio_loop") or {}
    src_keep = src_saved.get("audio_keep") or {}
    tgt_audio = dict(tgt.get("audio") or {})
    tgt_loop = dict(tgt.get("audio_loop") or {})
    tgt_keep = dict(tgt.get("audio_keep") or {})

    def _put_audio(src_rel, tgt_rel, repl):
        tgt_audio[tgt_rel] = repl
        if src_rel in src_loop:
            tgt_loop[tgt_rel] = src_loop[src_rel]
        if src_rel in src_keep:
            tgt_keep[tgt_rel] = src_keep[src_rel]

    n_audio = 0
    for e in plan["audio"]["matched"] + plan["audio"]["remapped"]:
        _put_audio(e["src_rel"], e["tgt_rel"], e["repl"])
        n_audio += 1
    if include_flagged:
        for e in plan["audio"]["flagged"]:
            _put_audio(e["src_rel"], e["src_rel"], e["repl"])
            n_audio += 1
    if tgt_audio:
        tgt["audio"] = tgt_audio
    if tgt_loop:
        tgt["audio_loop"] = tgt_loop
    if tgt_keep:
        tgt["audio_keep"] = tgt_keep

    tgt_video = dict(tgt.get("video") or {})
    for e in plan["video"]["matched"]:
        tgt_video[e["rel"]] = e["repl"]
    if tgt_video:
        tgt["video"] = tgt_video

    tgt_image = dict(tgt.get("image") or {})
    for e in plan["image"]["matched"]:
        tgt_image[e["rel"]] = e["repl"]
    if tgt_image:
        tgt["image"] = tgt_image

    # Toggles copy over only if the target doesn't already set them.
    for k, v in plan.get("toggles", {}).items():
        tgt.setdefault(k, v)

    staged_changes.save(target_dir, tgt)

    # Text: fill matching originals in the target manifest.
    n_text = 0
    new_by_original = {e["original"]: e["new"] for e in plan["text"]["matched"]}
    if new_by_original:
        rows = text_manifest.load(target_dir)
        for r in rows:
            if r["original"] in new_by_original:
                r["replacement"] = new_by_original[r["original"]]
                n_text += 1
        if n_text:
            text_manifest.save(target_dir, rows)

    return {"audio": n_audio, "video": len(plan["video"]["matched"]),
            "image": len(plan["image"]["matched"]), "text": n_text}
