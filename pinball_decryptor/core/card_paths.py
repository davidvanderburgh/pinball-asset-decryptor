"""Map an extracted asset back to the file it came from on the card.

The Replace tabs work in terms of ``rel_path`` inside the extract folder
(``audio/…``, ``video/…``, ``images/…``); nothing in a slot says where on the
SD card that content actually lives.  The Stern extractor already records the
mapping in per-kind sidecar manifests, so this module just reads them back —
it is the lookup behind the Replace tabs' "Find in Partition Explorer"
(monkeybug batch 16: "it would be great if there was an option to find in
partition … to see which radium file they live in").

Every resolver returns ``(card_path, note)`` — *card_path* is absolute on the
card (leading ``/``), *note* explains a container relationship when the asset
isn't a standalone file (a radium-embedded PNG, a sound inside ``image.bin``)
— or ``(None, reason)`` when it can't be resolved.
"""

import os
import re

# audio/…idx0461.wav  -> the sound bank image.bin
_IDX_RE = re.compile(r"\bidx0*\d+", re.IGNORECASE)
# audio/…music_cat07_0003.wav -> the per-category bank image-sc07.bin
_MUSIC_RE = re.compile(r"music_cat(\d+)_\d+", re.IGNORECASE)


def _read_manifest(assets_dir, rel_manifest, key_col=0, path_col=1):
    """Parse a ``# header``-prefixed TSV manifest into ``{key: card_path}``.

    Missing/unreadable manifests yield ``{}`` — every caller treats that as
    "this extract can't answer", not as an error.
    """
    out = {}
    path = os.path.join(assets_dir, *rel_manifest.split("/"))
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.rstrip("\n")
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) <= max(key_col, path_col):
                    continue
                key, card = cols[key_col].strip(), cols[path_col].strip()
                if key and card and key not in out:
                    # First row wins: a radium image is content-deduplicated
                    # across containers, so the first occurrence is its "home".
                    out[key] = card
    except (OSError, UnicodeDecodeError):
        return {}
    return out


def _abs(card_path):
    return "/" + card_path.strip("/") if card_path else None


def video_card_path(assets_dir, rel_path):
    """On-card path of a ``video/<name>`` slot (a directly-stored asset)."""
    name = rel_path.split("/", 1)[1] if "/" in rel_path else rel_path
    card = _read_manifest(assets_dir, "video/manifest.txt").get(name)
    if not card:
        return None, ("No video/manifest.txt entry for this clip — "
                      "re-extract this card to record where it came from.")
    return _abs(card), ""


def image_card_path(assets_dir, rel_path):
    """On-card path of an ``images/<rel>`` slot, across all three stores:
    a loose file on the card, a ``scene.assets`` texture, or a PNG embedded
    inside a ``.radium`` container."""
    rel = rel_path.split("/", 1)[1] if "/" in rel_path else rel_path
    card = _read_manifest(assets_dir, "images/manifest.txt").get(rel)
    if card:
        return _abs(card), ""
    card = _read_manifest(
        assets_dir, "images/scene_textures/manifest.txt").get(rel)
    if card:
        return _abs(card), "This image is a texture stored inside %s." % card
    card = _read_manifest(
        assets_dir, "images/scene_textures/radium_images.txt").get(rel)
    if card:
        return _abs(card), ("This image is embedded inside the radium file "
                            "%s (it may appear in more than one)." % card)
    return None, ("No manifest entry for this image — re-extract this card "
                  "to record where it came from.")


def audio_container(rel_path):
    """Basename of the bank a Spike 2 sound was decoded out of, or ``None``.

    There is no audio manifest: sounds are decoded from the bank binaries, so
    the container is inferred from the extractor's own naming convention —
    ``idxNNNN`` sounds come from ``image.bin``, ``music_catNN_…`` from that
    category's ``image-scNN.bin``.
    """
    name = os.path.basename(rel_path)
    m = _MUSIC_RE.search(name)
    if m:
        return "image-sc%s.bin" % m.group(1)
    if _IDX_RE.search(name):
        return "image.bin"
    return None


def audio_card_hint(rel_path):
    """``(container_basename, note)`` for an audio slot, or ``(None, reason)``.

    Unlike video/images this is a *basename*, not a full path — the caller
    resolves it against the partition's file list, because the game directory
    varies by title.
    """
    container = audio_container(rel_path)
    if not container:
        return None, ("This sound's name doesn't say which bank it came "
                      "from, so it can't be located on the card.")
    return container, ("Sounds aren't separate files on the card — this one "
                       "is decoded out of %s." % container)
